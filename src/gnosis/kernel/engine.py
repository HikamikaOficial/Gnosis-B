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
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..contracts.engineer_report import EngineerReport, ReportStatus
from ..runner.capture import ExecutionResult
from ..runner.claude_cli_runner import CancellationToken, ClaudeCodeCLIRunner, McpRunnerConfig
from ..runner.retry import RetryPolicy, execute_with_retry
from .claims import GrantHeartbeatPump, WorkAuthority, WorkGrant
from .code_intelligence import CodeIntelligenceProvider, CodeIntelligenceUnavailable
from .git_evidence import capture_git_evidence
from .ids import new_run_id
from .redaction import redact
from .run_store import RunStore
from .state_machine import RunState, TaskState, TaskStateMachine
from .verification import VerificationResult, Verifier


def _gather_code_intelligence_context(
    provider: CodeIntelligenceProvider,
    repo_path: Path,
    focus_symbols: Sequence[str],
    max_context_chars: int,
) -> tuple[str, dict[str, Any]]:
    """Best-effort structural context gathering for `focus_symbols`, run
    once before the CLI attempt loop. Never raises: any provider failure
    (missing tool, timeout, stale index) is caught and recorded in the
    returned evidence, never blocks task execution -- code intelligence
    is an accelerant, not a dependency (see kernel.code_intelligence).

    Bounded by construction: each explore() call is already capped by
    the adapter, and `max_context_chars` caps the *combined* text
    actually included in the prompt, this is the context-budgeting hook
    a future MemoryRouter can drive with a smarter number.
    """
    provider_name = type(provider).__name__
    queries: list[dict[str, Any]] = []
    blocks: list[str] = []
    total_chars = 0

    try:
        provider.index(repo_path, full=False)
    except CodeIntelligenceUnavailable as exc:
        queries.append({"op": "index", "success": False, "error": str(exc)})

    try:
        index_status = provider.status().to_dict()
    except CodeIntelligenceUnavailable as exc:
        index_status = {"available": False, "stale": True, "detail": str(exc)}

    if index_status.get("available") and index_status.get("stale"):
        blocks.append(
            "**Note:** the code-intelligence index may be stale (pending "
            "changes since last sync) -- verify structural claims before "
            "relying on them."
        )

    for symbol in focus_symbols:
        started = time.monotonic()
        try:
            ctx = provider.explore(symbol)
            latency_ms = round((time.monotonic() - started) * 1000, 1)
            remaining = max_context_chars - total_chars
            included = ctx.text[:remaining] if remaining > 0 else ""
            if included:
                blocks.append(f"### Code intelligence: {symbol}\n{included}")
                total_chars += len(included)
            queries.append({
                "op": "explore", "symbol": symbol, "success": True, "latency_ms": latency_ms,
                "related_symbols": list(ctx.related_symbols), "chars_returned": len(ctx.text),
                "chars_included": len(included),
            })
        except CodeIntelligenceUnavailable as exc:
            latency_ms = round((time.monotonic() - started) * 1000, 1)
            queries.append({
                "op": "explore", "symbol": symbol, "success": False,
                "latency_ms": latency_ms, "error": str(exc),
            })

    evidence = {
        "provider": provider_name, "index_status": index_status,
        "queries": queries, "context_included_chars": total_chars,
    }
    return "\n\n".join(blocks), evidence


@dataclass
class TaskExecutionOutcome:
    task_id: str
    run_ids: list[str]
    final_task_state: TaskState
    verification: VerificationResult | None
    execution_result: ExecutionResult | None
    report: EngineerReport


class TaskEngine:
    """Executes a single task: run the Claude Code CLI (with retries and
    crash-safe durable state), then deterministically verify the result."""

    def __init__(
        self,
        run_store: RunStore,
        cli_runner: Any = None,
        retry_policy: RetryPolicy | None = None,
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
        verifier: Verifier | None = None,
        timeout_s: float = 1800.0,
        cancellation_token: CancellationToken | None = None,
        mcp: McpRunnerConfig | None = None,
        code_intelligence: CodeIntelligenceProvider | None = None,
        focus_symbols: Sequence[str] | None = None,
        max_context_chars: int = 12000,
        authority: WorkAuthority | None = None,
        worker_id: str | None = None,
        lease_ttl_s: float | None = None,
        lease_heartbeat_interval_s: float | None = None,
    ) -> TaskExecutionOutcome:
        # Two-plane ownership (Directive 4 / ADR-0006): when a WorkAuthority
        # is supplied, this engine invocation must hold the durable claim
        # and the live lease for the task, and re-proves both before every
        # durable mutation. A deposed worker raises StaleLeaseError /
        # StaleClaimError instead of writing — the NO STALE WRITE invariant
        # enforced at the engine's write paths, not by convention.
        grant: WorkGrant | None = None
        pump: GrantHeartbeatPump | None = None
        if authority is not None:
            if not worker_id:
                raise ValueError("worker_id is required when a WorkAuthority is supplied")
            grant = authority.acquire(task_id, worker_id, ttl_s=lease_ttl_s)
            if cancellation_token is None:
                # Deposition detected mid-run cancels the child process
                # instead of leaking it.
                cancellation_token = CancellationToken()
            token = cancellation_token
            # The pump keeps the lease alive for the grant's WHOLE lifetime
            # — CLI runs, retry backoffs, verification, resolve — so a slow
            # verifier can no longer self-depose a healthy worker
            # (adversarial-review finding on the first version of this
            # unit). Deposition cancels the child cooperatively.
            interval = (
                lease_heartbeat_interval_s
                if lease_heartbeat_interval_s is not None
                else min(max(grant.ttl_s / 4.0, 0.05), 15.0)
            )
            pump = GrantHeartbeatPump(
                authority, grant, interval_s=interval,
                on_deposed=lambda exc: token.cancel(),
            )
            pump.start()

        def guard() -> None:
            # Surface a pump-detected deposition deterministically, then
            # re-prove both planes.
            if pump is not None and pump.deposed is not None:
                raise pump.deposed
            if authority is not None and grant is not None:
                authority.assert_current(grant)

        try:
            return self._execute_guarded(
                task_id=task_id, objective=objective, prompt=prompt,
                repo_path=repo_path, verifier=verifier, timeout_s=timeout_s,
                cancellation_token=cancellation_token, mcp=mcp,
                code_intelligence=code_intelligence, focus_symbols=focus_symbols,
                max_context_chars=max_context_chars, authority=authority,
                grant=grant, guard=guard,
            )
        finally:
            if pump is not None:
                pump.stop()

    def _execute_guarded(
        self,
        task_id: str,
        objective: str,
        prompt: str,
        repo_path: Path,
        verifier: Verifier | None,
        timeout_s: float,
        cancellation_token: CancellationToken | None,
        mcp: McpRunnerConfig | None,
        code_intelligence: CodeIntelligenceProvider | None,
        focus_symbols: Sequence[str] | None,
        max_context_chars: int,
        authority: WorkAuthority | None,
        grant: WorkGrant | None,
        guard: Callable[[], None],
    ) -> TaskExecutionOutcome:
        task_sm = TaskStateMachine(TaskState.CREATED)
        task_sm.transition(TaskState.PLANNED)
        task_sm.transition(TaskState.IN_PROGRESS)

        pre_git = capture_git_evidence(repo_path)
        run_ids: list[str] = []
        last_result: ExecutionResult | None = None

        ci_evidence: dict[str, Any] | None = None
        effective_prompt = prompt
        if code_intelligence is not None and focus_symbols:
            context_block, ci_evidence = _gather_code_intelligence_context(
                code_intelligence, repo_path, focus_symbols, max_context_chars,
            )
            if context_block:
                effective_prompt = f"{context_block}\n\n---\n\n{prompt}"

        def attempt(attempt_number: int) -> ExecutionResult:
            nonlocal last_result
            guard()
            run_id = new_run_id()
            run_ids.append(run_id)
            paths = self.run_store.create_run(run_id, task_id)
            ledger = self.run_store.ledger_for(run_id)
            if attempt_number == 1 and ci_evidence is not None:
                ledger.append(run_id, "code_intelligence.context_gathered", ci_evidence)
                (paths.root / "code_intelligence.json").write_text(
                    json.dumps(ci_evidence, indent=2, sort_keys=True), encoding="utf-8",
                )
            ledger.append(run_id, "run.attempt_started", {
                "attempt": attempt_number, "objective": objective,
                "mcp": mcp.to_dict() if mcp is not None else None,
                "code_intelligence_used": ci_evidence is not None,
            })
            self.run_store.update_state(run_id, RunState.RUNNING)
            self.run_store.heartbeat(run_id)

            result = self.cli_runner.run(
                prompt=effective_prompt, cwd=repo_path, stdout_path=paths.stdout, stderr_path=paths.stderr,
                timeout_s=timeout_s, cancellation_token=cancellation_token, mcp=mcp,
                heartbeat_fn=lambda pid: self.run_store.heartbeat(run_id),
            )

            # The CLI run is a long window in which a deposition can happen
            # (the pump detects it and cancels the child); re-prove
            # ownership before recording the outcome.
            guard()

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

        guard()
        post_git = capture_git_evidence(repo_path)
        latest_run_id = run_ids[-1] if run_ids else None
        if latest_run_id:
            git_dir = self.run_store.paths_for(latest_run_id).git_dir
            (git_dir / "pre.json").write_text(json.dumps(pre_git.to_dict(), indent=2), encoding="utf-8")
            (git_dir / "post.json").write_text(json.dumps(post_git.to_dict(), indent=2), encoding="utf-8")

        cli_succeeded = bool(last_result and last_result.succeeded)
        verification_result: VerificationResult | None = None

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

        # Verified success resolves the claim and releases the lease in the
        # same authority call. On failure/cancellation the claim deliberately
        # stays ACTIVE, bound to the unresolved work (grit's merge-failure
        # lesson); the lease is left to expire so the TTL sweep reclaims it
        # as an audited RECLAIMED transition instead of a silent release.
        if authority is not None and grant is not None and task_sm.state == TaskState.COMPLETED:
            authority.resolve(grant, outcome="COMPLETED")

        problems: tuple[str, ...] = ()
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
