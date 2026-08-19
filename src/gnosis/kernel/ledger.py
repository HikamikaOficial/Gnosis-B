"""Append-only, event-oriented run ledger.

Each run gets one JSONL file. Events are the only way state changes are
recorded for audit/replay; the API intentionally exposes no update/delete
so callers cannot silently rewrite history. (Filesystem-level immutability
is a hardening step left for a later milestone.)

Appends are serialized through a FileLock (kernel.file_lock) rather than a
plain threading.Lock: the read-last-seq-then-write critical section must
be atomic across processes too, not just threads in one process, or two
writers can race and silently drop an event. Reads tolerate a truncated
final line (the signature of a process killed mid-write) by dropping it
rather than raising, since fsync'd earlier lines remain intact evidence;
a malformed *non-final* line is treated as real corruption and raises.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .file_lock import FileLock, lock_path_for


class LedgerCorruptionError(RuntimeError):
    pass


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
    """Append-only JSONL ledger for a single run. Safe for concurrent
    writers, in-process threads or separate processes, via FileLock."""

    def __init__(self, path: Path, lock_timeout_s: float = 30.0):
        self.path = path
        self._lock = FileLock(lock_path_for(path), timeout_s=lock_timeout_s)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, run_id: str, event_type: str, data: dict[str, Any] | None = None) -> LedgerEvent:
        with self._lock:
            next_seq = self._last_seq_locked() + 1
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

    def _last_seq_locked(self) -> int:
        last = 0
        for event in self._iter_events(tolerant=True):
            last = event.seq
        return last

    def read_all(self, tolerant: bool = True) -> list[LedgerEvent]:
        return list(self._iter_events(tolerant=tolerant))

    def _iter_events(self, tolerant: bool) -> Iterator[LedgerEvent]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            raw_lines = [line.strip() for line in fh]
        raw_lines = [line for line in raw_lines if line]
        last_index = len(raw_lines) - 1
        for index, line in enumerate(raw_lines):
            try:
                yield LedgerEvent.from_dict(json.loads(line))
            except (json.JSONDecodeError, KeyError) as exc:
                if tolerant and index == last_index:
                    # Truncated final write (process killed mid-append).
                    # Earlier fsync'd lines remain intact evidence.
                    return
                raise LedgerCorruptionError(
                    f"Corrupt ledger line {index + 1} in {self.path}: {exc}"
                ) from exc
