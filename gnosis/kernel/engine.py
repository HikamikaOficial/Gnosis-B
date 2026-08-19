"""Bootstrap task engine.

Wires together the M0 primitives, state machines, run store, the Claude
Code CLI runner, retry policy, deterministic verification, git evidence,
and redaction, into a single-task execution lifecycle. This is
intentionally the thinnest glue that proves the primitives compose; a real
multi-task orchestrator (scheduling, worktrees, councils, Night Cycle) is
future work with its own extension point here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ..contracts.engineer_report import EngineerReport, ReportStatus
from ..runner.capture import ExecutionResult
from ..runner.claude_cli_runner import CancellationToken, ClaudeCodeCLIRunner
from ..runner.retry import RetryPolicy, execute_with_retry
from .git_evidence import capture_git_evidence
from .ids import new_run_id
from .redaction import redact
from .run_store import RunStore
from .state_machine import RunState, TaskState, TaskStateMachine
from .verification import Verifier, VerificationResult


@dataclass
class TaskExecutionOutcome:
    task_id: str
    run_ids: list
    final_task_state: TaskState
    verification: Optional[VerificationResult]
    execution_result: Optional[ExecutionResult]
    report: EngineerReport


class TaskEngine:
    """Executes a single task: run the Claude Code CLI (with retries and
    crash-safe durable state), then deterministically verify the result."""

    def __init__(
        self,
        run_store: RunStore,
        cli_runner: Any = None,
        retry_policy: Optional[RetryPolicy] = None,
    ):
        self.run_store = run_store
        self.cli_runner = cli_runner or ClaudeCodeCLIRunner()
        self.retry_policy = retry_policy or RetryPolicy()

    def execute_task(
        self,
        task_id: str,
        objective: str,
        prompt: str,
        repo_path: Path,
        verifier: Optional[Verifier] = None,
        timeout_s: float = 1800.0,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> TaskExecutionOutcome:
        task_sm = TaskStateMachine(TaskState.CREATED)
        task_sm.transition(TaskState.PLANNED)
        task_sm.transition(TaskState.IN_PROGRESS)

        pre_git = capture_git_evidence(repo_path)
        run_ids: list = []
        last_result: Optional[ExecutionResult] = None

        def attempt(attempt_number: int) -> ExecutionResult:
            nonlocal last_result
            run_id = new_run_id()
            run_ids.append(run_id)
            paths = self.run_store.create_run(run_id, task_id)
            ledger = self.run_store.ledger_for(run_id)
            ledger.append(run_id, "run.attempt_started", {"attempt": attempt_number, "objective": objective})
            self.run_store.update_state(run_id, RunState.RUNNING)
            self.run_store.heartbeat(run_id)

            result = self.cli_runner.run(
                prompt=prompt, cwd=repo_path, stdout_path=paths.stdout, stderr_path=paths.stderr,
                timeout_s=timeout_s, cancellation_token=cancellation_token,
                heartbeat_fn=lambda pid: self.run_store.heartbeat(run_id),
            )

            if result.succeeded:
                final_state = RunState.SUCCEEDED
            elif result.timed_out:
                final_state = RunState.TIMED_OUT
            elif result.cancelled:
                final_state = RunState.CANCELLED
            else:
                final_state = RunState.FAILED

            self.run_store.update_state(run_id, final_state)
            ledger.append(run_id, "run.attempt_finished", {
                "attempt": attempt_number, "exit_code": result.exit_code,
                "timed_out": result.timed_out, "cancelled": result.cancelled,
                "duration_s": result.duration_s,
            })
            paths.result.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
            last_result = result
            return result

        def should_retry(result: ExecutionResult) -> bool:
            return (not result.cancelled) and (not result.succeeded)

        execute_with_retry(attempt, should_retry, self.retry_policy)

        post_git = capture_git_evidence(repo_path)
        latest_run_id = run_ids[-1] if run_ids else None
        if latest_run_id:
            git_dir = self.run_store.paths_for(latest_run_id).git_dir
            (git_dir / "pre.json").write_text(json.dumps(pre_git.to_dict(), indent=2), encoding="utf-8")
            (git_dir / "post.json").write_text(json.dumps(post_git.to_dict(), indent=2), encoding="utf-8")

        cli_succeeded = bool(last_result and last_result.succeeded)
        verification_result: Optional[VerificationResult] = None

        if cli_succeeded:
            task_sm.transition(TaskState.VERIFYING)
            if verifier is not None:
                verification_result = verifier.run(repo_path)
                if latest_run_id:
                    self.run_store.ledger_for(latest_run_id).append(
                        latest_run_id, "task.verification_result", verification_result.to_dict(),
                    )
            verification_passed = verification_result.passed if verification_result else True
            task_sm.transition(TaskState.COMPLETED if verification_passed else TaskState.FAILED)
        else:
            task_sm.transition(TaskState.FAILED)

        problems: tuple = ()
        if not cli_succeeded and latest_run_id:
            stderr_path = self.run_store.paths_for(latest_run_id).stderr
            if stderr_path.exists():
                tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                problems = (redact(tail),) if tail.strip() else ()
        elif verification_result is not None and not verification_result.passed:
            problems = (redact(verification_result.stderr_excerpt),)

        report = EngineerReport(
            task_id=task_id,
            run_id=latest_run_id or "NONE",
            status=ReportStatus.COMPLETED if task_sm.state == TaskState.COMPLETED else ReportStatus.PARTIAL,
            objective=objective,
            work_completed=(f"Executed {len(run_ids)} run attempt(s) via the Claude Code CLI runner.",),
            verification=(
                (f"{verification_result.name}: " + ("PASSED" if verification_result.passed else "FAILED"),)
                if verification_result else ("No verifier supplied.",)
            ),
            problems_encountered=problems,
            recommended_next_step=(
                "None, task completed and verified." if task_sm.state == TaskState.COMPLETED
                else "Investigate the run/verification failure captured in this run's evidence before retrying."
            ),
        )

        return TaskExecutionOutcome(
            task_id=task_id, run_ids=run_ids, final_task_state=task_sm.state,
            verification=verification_result, execution_result=last_result, report=report,
        )
