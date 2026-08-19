"""Typed contract for a Director (ChatGPT) brief handed to the Principal
Engineer (Claude Code). Frozen + validated so a malformed brief fails fast
at construction rather than drifting silently through the kernel."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class BriefSource(str, Enum):
    MANUAL = "manual"
    MCP = "mcp"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DirectorBrief:
    brief_id: str
    title: str
    mission: str
    source: BriefSource
    created_at: str = field(default_factory=_utc_now_iso)
    non_negotiables: tuple[str, ...] = field(default_factory=tuple)
    constraints: tuple[str, ...] = field(default_factory=tuple)
    acceptance_criteria: tuple[str, ...] = field(default_factory=tuple)
    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.brief_id.strip():
            raise ValueError("DirectorBrief.brief_id must be non-empty")
        if not self.title.strip():
            raise ValueError("DirectorBrief.title must be non-empty")
        if not self.mission.strip():
            raise ValueError("DirectorBrief.mission must be non-empty")
        if not isinstance(self.source, BriefSource):
            raise ValueError(f"DirectorBrief.source must be a BriefSource, got {self.source!r}")
        try:
            datetime.fromisoformat(self.created_at)
        except ValueError as exc:
            raise ValueError(f"DirectorBrief.created_at must be ISO-8601: {self.created_at!r}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "brief_id": self.brief_id,
            "title": self.title,
            "mission": self.mission,
            "source": self.source.value,
            "created_at": self.created_at,
            "non_negotiables": list(self.non_negotiables),
            "constraints": list(self.constraints),
            "acceptance_criteria": list(self.acceptance_criteria),
            "raw_text": self.raw_text,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DirectorBrief":
        return cls(
            brief_id=data["brief_id"],
            title=data["title"],
            mission=data["mission"],
            source=BriefSource(data["source"]),
            created_at=data.get("created_at", _utc_now_iso()),
            non_negotiables=tuple(data.get("non_negotiables", ())),
            constraints=tuple(data.get("constraints", ())),
            acceptance_criteria=tuple(data.get("acceptance_criteria", ())),
            raw_text=data.get("raw_text", ""),
            metadata=dict(data.get("metadata", {})),
        )
