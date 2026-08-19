"""Append-only, event-oriented run ledger.

Each run gets one JSONL file. Events are the only way state changes are
recorded for audit/replay; the API intentionally exposes no update/delete
so callers cannot silently rewrite history. (Filesystem-level immutability
is a hardening step left for a later milestone; see the M0 engineer
report limitations section.)
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True)
class LedgerEvent:
    seq: int
    ts: str
    run_id: str
    event_type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LedgerEvent":
        return cls(
            seq=data["seq"],
            ts=data["ts"],
            run_id=data["run_id"],
            event_type=data["event_type"],
            data=data.get("data", {}),
        )


class RunLedger:
    """Append-only JSONL ledger for a single run."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, run_id: str, event_type: str, data: dict[str, Any] | None = None) -> LedgerEvent:
        with self._lock:
            next_seq = self._last_seq() + 1
            event = LedgerEvent(
                seq=next_seq,
                ts=datetime.now(timezone.utc).isoformat(),
                run_id=run_id,
                event_type=event_type,
                data=data or {},
            )
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return event

    def _last_seq(self) -> int:
        last = 0
        for event in self.read_all():
            last = event.seq
        return last

    def read_all(self) -> list[LedgerEvent]:
        return list(self._iter_events())

    def _iter_events(self) -> Iterator[LedgerEvent]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                yield LedgerEvent.from_dict(json.loads(line))
