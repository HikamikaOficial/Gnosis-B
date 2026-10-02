"""Structured capture of a subprocess execution, the CLI runner's result type."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutionResult:
    command: tuple[str, ...]
    exit_code: int | None
    timed_out: bool
    cancelled: bool
    duration_s: float
    stdout_path: str
    stderr_path: str
    started_at: str
    ended_at: str
    parsed_json: dict[str, Any] | None = None
    # F-17 Stage 5. `command` KEEPS ITS HISTORICAL MEANING — the LOGICAL command
    # Gnosis ordered — so replay and cassettes are unaffected by which transport
    # carried it. The transport (a short bootstrap invocation) is deliberately
    # NOT merged into it; what the trusted launcher observed is recorded
    # separately here: launcher kind/version, launch_spec_digest,
    # logical_command_digest and the OS-observed worker SID. None on the
    # same-user path, which is what makes the difference visible in evidence.
    launch: dict[str, Any] | None = None

    @property
    def succeeded(self) -> bool:
        return (not self.timed_out) and (not self.cancelled) and self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": list(self.command), "exit_code": self.exit_code, "timed_out": self.timed_out,
            "cancelled": self.cancelled, "duration_s": self.duration_s, "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path, "started_at": self.started_at, "ended_at": self.ended_at,
            "parsed_json": self.parsed_json, "succeeded": self.succeeded,
            "launch": self.launch,
        }


@dataclass(frozen=True)
class RecordedAttempt:
    """One durable agent invocation; success here is not task completion."""

    run_id: str
    task_id: str
    stage: str
    state: str
    result: ExecutionResult | None = None
    error_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "task_id": self.task_id, "stage": self.stage,
                "state": self.state, "result": self.result.to_dict() if self.result else None,
                "error_type": self.error_type}
