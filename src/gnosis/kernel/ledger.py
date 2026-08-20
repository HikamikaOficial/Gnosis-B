"""Append-only, hash-chained, event-oriented run ledger.

Each run gets one JSONL file. Events are the only way state changes are
recorded for audit/replay; the API intentionally exposes no update/delete
so callers cannot silently rewrite history. (Filesystem-level immutability
is a hardening step left for a later milestone.)

Every event carries ``prev_hash`` (the previous event's ``event_hash``,
or GENESIS_HASH for seq 1) and ``event_hash`` (hash_canonical of the
event payload minus ``event_hash`` itself), both derived from the single
kernel canonical-bytes primitive (kernel.canonical, ADR-0004). Appends
re-verify the whole chain from genesis before extending it — Directive 2
of the archaeology findings: never extend a chain from an unverified
anchor. O(n) per append is deliberate and acceptable at run-ledger scale;
a checkpointed anchor is a later optimization if ledgers ever grow enough
to warrant one.

Appends are serialized through a FileLock (kernel.file_lock) rather than a
plain threading.Lock: the read-verify-then-write critical section must
be atomic across processes too, not just threads in one process, or two
writers can race and silently drop an event. Reads tolerate a truncated
final line (the signature of a process killed mid-write) by dropping it
rather than raising, since fsync'd earlier lines remain intact evidence;
a malformed *non-final* line, a sequence gap, or a hash-chain break is
real corruption and raises, naming the offending line.

Ledgers written before hash chaining existed (no ``event_hash`` fields)
remain readable as legacy evidence but refuse new appends: extending an
unverifiable prefix would launder it into a "verified" chain.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .canonical import GENESIS_HASH, hash_canonical
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
    # None only on legacy events written before hash chaining existed.
    prev_hash: str | None = None
    event_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "seq": self.seq,
            "ts": self.ts,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "data": self.data,
        }
        if self.prev_hash is not None:
            payload["prev_hash"] = self.prev_hash
        if self.event_hash is not None:
            payload["event_hash"] = self.event_hash
        return payload

    def hashable_payload(self) -> dict[str, Any]:
        """The exact object whose canonical hash is ``event_hash``."""
        payload = self.to_dict()
        payload.pop("event_hash", None)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LedgerEvent:
        return cls(
            seq=data["seq"],
            ts=data["ts"],
            run_id=data["run_id"],
            event_type=data["event_type"],
            data=data.get("data", {}),
            prev_hash=data.get("prev_hash"),
            event_hash=data.get("event_hash"),
        )


class RunLedger:
    """Append-only, hash-chained JSONL ledger for a single run. Safe for
    concurrent writers, in-process threads or separate processes, via
    FileLock."""

    def __init__(self, path: Path, lock_timeout_s: float = 30.0):
        self.path = path
        self._lock_timeout_s = lock_timeout_s
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def _locked(self) -> FileLock:
        # One FileLock instance PER critical section, per the FileLock
        # contract: a shared instance raises on concurrent acquire from a
        # second thread of the same object instead of waiting its turn.
        return FileLock(lock_path_for(self.path), timeout_s=self._lock_timeout_s)

    def append(self, run_id: str, event_type: str, data: dict[str, Any] | None = None) -> LedgerEvent:
        with self._locked():
            # Directive 2: verify the whole chain before extending it.
            next_seq, prev_hash = self._verified_anchor_locked()
            event = LedgerEvent(
                seq=next_seq,
                ts=datetime.now(UTC).isoformat(),
                run_id=run_id,
                event_type=event_type,
                data=data or {},
                prev_hash=prev_hash,
            )
            event = replace(event, event_hash=hash_canonical(event.hashable_payload()))
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return event

    def _verified_anchor_locked(self) -> tuple[int, str]:
        """Verify the full chain and return (next_seq, prev_hash anchor)."""
        events = list(self._iter_events(tolerant=True))
        self._verify_chain(events)
        if not events:
            return 1, GENESIS_HASH
        tail_hash = events[-1].event_hash
        if tail_hash is None:
            raise LedgerCorruptionError(
                f"{self.path} is a legacy pre-chain ledger; it stays readable as "
                "evidence but refuses new appends (cannot chain from an "
                "unverifiable anchor)"
            )
        return events[-1].seq + 1, tail_hash

    def verify_chain(self) -> list[LedgerEvent]:
        """Recompute and check every hash from genesis; return the events.

        Raises LedgerCorruptionError on any interior malformation, sequence
        gap, payload/hash mismatch, or broken prev-hash link. A fully legacy
        ledger (no hashes anywhere) is returned as-is: readable evidence,
        explicitly unverifiable, and rejected at append time instead.
        """
        events = list(self._iter_events(tolerant=True))
        self._verify_chain(events)
        return events

    def _verify_chain(self, events: list[LedgerEvent]) -> None:
        expected_prev = GENESIS_HASH
        chained_seen = False
        for index, event in enumerate(events):
            if event.seq != index + 1:
                raise LedgerCorruptionError(
                    f"Sequence gap in {self.path} at line {index + 1}: "
                    f"expected seq {index + 1}, found {event.seq}"
                )
            if event.event_hash is None:
                if chained_seen:
                    raise LedgerCorruptionError(
                        f"Legacy (unhashed) event after chained events in "
                        f"{self.path} at line {index + 1}"
                    )
                continue  # legacy prefix: tolerated for reads
            if index > 0 and events[index - 1].event_hash is None:
                # A chained event may never follow a legacy one, even with a
                # plausible-looking prev_hash: that would launder an
                # unverifiable prefix into a "verified" chain.
                raise LedgerCorruptionError(
                    f"Chained event after legacy prefix in {self.path} at line {index + 1}"
                )
            chained_seen = True
            if event.prev_hash != expected_prev:
                raise LedgerCorruptionError(
                    f"Broken hash chain in {self.path} at line {index + 1}: "
                    f"prev_hash does not match previous event_hash"
                )
            recomputed = hash_canonical(event.hashable_payload())
            if recomputed != event.event_hash:
                raise LedgerCorruptionError(
                    f"Tampered event in {self.path} at line {index + 1}: "
                    f"event_hash does not match payload"
                )
            expected_prev = event.event_hash

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
