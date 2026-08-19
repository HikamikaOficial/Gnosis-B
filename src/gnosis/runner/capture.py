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
    parsed_json: dict | None = None

    @property
    def succeeded(self) -> bool:
        return (not self.timed_out) and (not self.cancelled) and self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": list(self.command), "exit_code": self.exit_code, "timed_out": self.timed_out,
            "cancelled": self.cancelled, "duration_s": self.duration_s, "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path, "started_at": self.started_at, "ended_at": self.ended_at,
            "parsed_json": self.parsed_json, "succeeded": self.succeeded,
        }
