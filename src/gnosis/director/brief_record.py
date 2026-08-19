"""Durable lifecycle record for one ingested DirectorBrief.

Structured JSON is the canonical state (per Director instruction: human-
readable Markdown views may exist, but must never be the source of truth
if a typed representation is available). One BriefRecord ties a brief_id
to at most one task_id, which is what makes duplicate-ingestion rejection
and safe resume possible: a brief that already has a record is never
re-assigned a second task.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ..kernel.atomic_io import atomic_write_text
from ..kernel.file_lock import FileLock, lock_path_for


class BriefRecordState(str, Enum):
    INGESTED = "INGESTED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"


@dataclass
class BriefRecord:
    brief_id: str
    task_id: str
    state: str
    created_at: str
    updated_at: str
    run_ids: list = field(default_factory=list)
    report_path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "brief_id": self.brief_id, "task_id": self.task_id, "state": self.state,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "run_ids": list(self.run_ids), "report_path": self.report_path, "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BriefRecord:
        return cls(
            brief_id=data["brief_id"], task_id=data["task_id"], state=data["state"],
            created_at=data["created_at"], updated_at=data["updated_at"],
            run_ids=list(data.get("run_ids", [])), report_path=data.get("report_path"),
            error=data.get("error"),
        )


class BriefRecordStore:
    """One JSON file per brief_id under `root`, atomic writes, locked
    read-modify-write so concurrent orchestrator ticks cannot race."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, brief_id: str) -> Path:
        return self.root / f"{brief_id}.json"

    def exists(self, brief_id: str) -> bool:
        return self._path(brief_id).exists()

    def create(self, brief_id: str, task_id: str, state: BriefRecordState) -> BriefRecord:
        now = datetime.now(UTC).isoformat()
        record = BriefRecord(
            brief_id=brief_id, task_id=task_id, state=state.value,
            created_at=now, updated_at=now,
        )
        self._write(record)
        return record

    def get(self, brief_id: str) -> BriefRecord:
        return BriefRecord.from_dict(json.loads(self._path(brief_id).read_text(encoding="utf-8")))

    def update(self, brief_id: str, **changes: Any) -> BriefRecord:
        """Locked read-modify-write: apply `changes` as attribute updates
        to the stored record and persist atomically."""
        with FileLock(lock_path_for(self._path(brief_id)), timeout_s=30.0):
            record = self.get(brief_id)
            for key, value in changes.items():
                setattr(record, key, value.value if isinstance(value, Enum) else value)
            record.updated_at = datetime.now(UTC).isoformat()
            self._write(record)
            return record

    def _write(self, record: BriefRecord) -> None:
        atomic_write_text(self._path(record.brief_id), json.dumps(record.to_dict(), indent=2, sort_keys=True))

    def list_in_states(self, states: set) -> list[BriefRecord]:
        wanted = {s.value if isinstance(s, Enum) else s for s in states}
        records = []
        for path in sorted(self.root.glob("*.json")):
            record = BriefRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            if record.state in wanted:
                records.append(record)
        return records
