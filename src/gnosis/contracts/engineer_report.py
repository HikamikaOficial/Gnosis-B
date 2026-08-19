"""Typed contract for the ENGINEER REPORT handoff mandated by the project
CLAUDE.md. Structured so it can be rendered to the exact Markdown template
the Director expects, or round-tripped as JSON for a future MCP transport."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ReportStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class EngineerReport:
    task_id: str
    run_id: str
    status: ReportStatus
    objective: str
    work_completed: tuple[str, ...] = field(default_factory=tuple)
    files_changed: tuple[str, ...] = field(default_factory=tuple)
    engineering_decisions: tuple[str, ...] = field(default_factory=tuple)
    verification: tuple[str, ...] = field(default_factory=tuple)
    problems_encountered: tuple[str, ...] = field(default_factory=tuple)
    remaining_risks: tuple[str, ...] = field(default_factory=tuple)
    architecture_impact: str = "None."
    recommended_next_step: str = ""
    created_at: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("EngineerReport.task_id must be non-empty")
        if not self.run_id.strip():
            raise ValueError("EngineerReport.run_id must be non-empty")
        if not isinstance(self.status, ReportStatus):
            raise ValueError(f"EngineerReport.status must be a ReportStatus, got {self.status!r}")
        if not self.objective.strip():
            raise ValueError("EngineerReport.objective must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "status": self.status.value,
            "objective": self.objective,
            "work_completed": list(self.work_completed),
            "files_changed": list(self.files_changed),
            "engineering_decisions": list(self.engineering_decisions),
            "verification": list(self.verification),
            "problems_encountered": list(self.problems_encountered),
            "remaining_risks": list(self.remaining_risks),
            "architecture_impact": self.architecture_impact,
            "recommended_next_step": self.recommended_next_step,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EngineerReport:
        return cls(
            task_id=data["task_id"],
            run_id=data["run_id"],
            status=ReportStatus(data["status"]),
            objective=data["objective"],
            work_completed=tuple(data.get("work_completed", ())),
            files_changed=tuple(data.get("files_changed", ())),
            engineering_decisions=tuple(data.get("engineering_decisions", ())),
            verification=tuple(data.get("verification", ())),
            problems_encountered=tuple(data.get("problems_encountered", ())),
            remaining_risks=tuple(data.get("remaining_risks", ())),
            architecture_impact=data.get("architecture_impact", "None."),
            recommended_next_step=data.get("recommended_next_step", ""),
            created_at=data.get("created_at", _utc_now_iso()),
        )

    def to_markdown(self) -> str:
        def _bullets(items: tuple[str, ...]) -> str:
            return "\n".join(f"- {item}" for item in items) if items else "- (none)"

        return (
            "# ENGINEER REPORT\n\n"
            f"## Status\n{self.status.value}\n\n"
            f"## Objective\n{self.objective}\n\n"
            f"## Work completed\n{_bullets(self.work_completed)}\n\n"
            f"## Files changed\n{_bullets(self.files_changed)}\n\n"
            f"## Engineering decisions\n{_bullets(self.engineering_decisions)}\n\n"
            f"## Verification\n{_bullets(self.verification)}\n\n"
            f"## Problems encountered\n{_bullets(self.problems_encountered)}\n\n"
            f"## Remaining risks\n{_bullets(self.remaining_risks)}\n\n"
            f"## Architecture impact\n{self.architecture_impact}\n\n"
            f"## Recommended next step\n{self.recommended_next_step}\n"
        )
