"""Record a gated agent invocation in the existing RunStore and append audit.

This wrapper owns attempt recording only. The gate still owns policy, holds and
budget, and the inner trusted runner still owns the actual Worker launch. Unique
raw paths survive rework failures and cannot overwrite an earlier round.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..kernel.atomic_io import atomic_write_text
from ..kernel.execution_scope import ExecutionScope
from ..kernel.ids import new_run_id
from ..kernel.run_store import RunStore
from ..kernel.state_machine import RunState
from .capture import ExecutionResult, RecordedAttempt
from .gated_runner import CredentialHeld, GatedAgentRunner


class RecordedAgentRunner:
    def __init__(self, inner: GatedAgentRunner, store: RunStore, *, task_id: str,
                 stage: str, on_started: Callable[[str], None] | None = None,
                 on_finished: Callable[[RecordedAttempt], None] | None = None) -> None:
        self.inner = inner
        self.store = store
        self.task_id = task_id
        self.stage = stage
        self.on_started = on_started
        self.on_finished = on_finished
        self.attempts: list[RecordedAttempt] = []
        self.scope: ExecutionScope | None = inner.scope

    @property
    def binary(self) -> str:
        return self.inner.binary

    def run(self, prompt: str, cwd: Path, stdout_path: Path, stderr_path: Path,
            timeout_s: float = 1800.0,
            **kwargs: Any) -> ExecutionResult:
        # Caller paths identify the adapter request, but canonical raw output is
        # always under this new run. ExecutionResult carries the actual paths.
        if "run_id" in kwargs:
            raise ValueError("recorded attempt identity is minted by the recorder")
        if self.scope is not None:
            self.scope.check()
        run_id = new_run_id()
        paths = self.store.create_run(run_id, self.task_id)
        audit = self.store.ledger_for(run_id)
        meta = self.store.read_meta(run_id)
        meta.extra = {"stage": self.stage, "cwd": str(cwd)}
        self.store.write_meta(run_id, meta)
        index = len(self.attempts)
        self.attempts.append(RecordedAttempt(run_id, self.task_id, self.stage, RunState.PENDING.value))
        audit.append(run_id, "run.attempt_created", {"task_id": self.task_id,
                     "stage": self.stage, "cwd": str(cwd)})
        state = RunState.RUNNING
        error_type: str | None = None
        result: ExecutionResult | None = None
        first_decision = len(self.inner.decisions)
        called_inner = False

        def heartbeat(pid: int) -> None:
            # Like TaskEngine, record the owning Director's fingerprint so
            # killing the controller makes its unfinished attempt recoverable.
            if self.scope is not None:
                self.scope.check()
            self.store.heartbeat(run_id)

        try:
            if self.on_started is not None:
                self.on_started(run_id)
            self.store.update_state(run_id, state)
            self.store.heartbeat(run_id)
            audit.append(run_id, "run.attempt_started", {"stage": self.stage})
            launch_args = dict(kwargs)
            launch_args["heartbeat_fn"] = heartbeat
            if self.inner.accepts_run_id:
                launch_args["run_id"] = run_id
            called_inner = True
            result = self.inner.run(prompt=prompt, cwd=cwd, stdout_path=paths.stdout,
                                    stderr_path=paths.stderr, timeout_s=timeout_s, **launch_args)
            state = (RunState.SUCCEEDED if result.succeeded else RunState.CANCELLED
                     if result.cancelled else RunState.TIMED_OUT if result.timed_out
                     else RunState.FAILED)
            return result
        except Exception as exc:
            # Preserve raw/structured output even when the gate converts a
            # provider response to a park. Infrastructure errors retain their
            # class; no fabricated failing code-verification is produced.
            error_type = type(exc).__name__
            result = self.inner.last_result if called_inner else None
            state = RunState.RATE_LIMITED if isinstance(exc, CredentialHeld) else RunState.FAILED
            raise
        finally:
            if self.scope is not None:
                self.scope.check()
            attempt = RecordedAttempt(run_id, self.task_id, self.stage, state.value,
                                      result, error_type)
            self.attempts[index] = attempt
            for stage, decision in self.inner.decisions[first_decision:]:
                audit.append(run_id, "policy.decision", {"stage": stage,
                             "verdict": decision.verdict.value, "reason": decision.reason})
            if called_inner and self.inner.classification is not None:
                audit.append(run_id, "run.attempt_classified", self.inner.classification.to_dict())
            if result is not None:
                atomic_write_text(paths.result, json.dumps(result.to_dict(), indent=2, sort_keys=True))
            atomic_write_text(paths.root / "attempt.json",
                              json.dumps(attempt.to_dict(), indent=2, sort_keys=True))
            audit.append(run_id, "run.attempt_finished", {"stage": self.stage,
                         "state": state.value, "error_type": error_type})
            self.store.update_state(run_id, state)
            if self.on_finished is not None:
                self.on_finished(attempt)
