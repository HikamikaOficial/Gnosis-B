"""In-process reference MemoryProvider.

Not a stub, not a mock: a real, correct implementation of the full
lifecycle (OBSERVED->CANDIDATE->QUARANTINED->ACTIVE->SUPERSEDED/REVOKED),
bitemporal as_of queries, supersession, revocation-with-retroactive-
traceability, and influence receipts. Used to (a) prove the contract is
actually implementable coherently, not just abstractly typed, and (b)
give Gnosis's own test suite deterministic scenarios to run against
without depending on an external memory system being installed.

A future GovernanceMemoryAdapter/FactualMemoryAdapter (zmem/m3-memory)
would satisfy the same contract by shelling out to those tools instead
of using the in-process dict below -- exactly the CodegraphMcpAdapter
pattern from kernel.code_intelligence_adapters.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from .memory import (
    MemoryEvidence,
    MemoryInfluence,
    MemoryProvider,
    MemoryQuery,
    MemoryRecord,
    MemoryResult,
    MemoryRevision,
    MemoryStatus,
    MemoryUnavailable,
    validate_memory_transition,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id(prefix: str, counter: int) -> str:
    return f"{prefix}_{counter:06d}"


class InMemoryMemoryProvider(MemoryProvider):
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}
        self._history: dict[str, list[MemoryRevision]] = {}
        self._influences: dict[str, MemoryInfluence] = {}
        self._counter = 0

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return _new_id(prefix, self._counter)

    def _set_status(self, record: MemoryRecord, target: MemoryStatus, reason: str) -> MemoryRecord:
        validate_memory_transition(record.status, target)
        updated = MemoryRecord(
            memory_id=record.memory_id, content=record.content, memory_type=record.memory_type,
            status=target, evidence=record.evidence, created_at=record.created_at, updated_at=_now(),
            valid_from=record.valid_from, valid_to=record.valid_to,
            supersedes=record.supersedes, superseded_by=record.superseded_by, labels=record.labels,
        )
        self._records[record.memory_id] = updated
        self._history.setdefault(record.memory_id, []).append(MemoryRevision(
            memory_id=record.memory_id, previous_status=record.status, new_status=target, reason=reason,
        ))
        return updated

    def remember(
        self, content: str, memory_type: str, evidence: MemoryEvidence,
        valid_from: str | None = None, labels: tuple[str, ...] = (),
    ) -> MemoryRecord:
        memory_id = self._next_id("mem")
        record = MemoryRecord(
            memory_id=memory_id, content=content, memory_type=memory_type,
            status=MemoryStatus.OBSERVED, evidence=evidence, valid_from=valid_from, labels=tuple(labels),
        )
        self._records[memory_id] = record
        self._history[memory_id] = []
        record = self._set_status(record, MemoryStatus.CANDIDATE, "authored")
        record = self._set_status(record, MemoryStatus.ACTIVE, f"trusted source: {evidence.source_kind}")
        return record

    def propose(
        self, content: str, memory_type: str, evidence: MemoryEvidence,
        valid_from: str | None = None, labels: tuple[str, ...] = (),
    ) -> MemoryRecord:
        memory_id = self._next_id("mem")
        record = MemoryRecord(
            memory_id=memory_id, content=content, memory_type=memory_type,
            status=MemoryStatus.OBSERVED, evidence=evidence, valid_from=valid_from, labels=tuple(labels),
        )
        self._records[memory_id] = record
        self._history[memory_id] = []
        record = self._set_status(record, MemoryStatus.CANDIDATE, "proposed")
        record = self._set_status(record, MemoryStatus.QUARANTINED, "pending review")
        return record

    def promote(self, memory_id: str) -> MemoryRecord:
        record = self._require(memory_id)
        return self._set_status(record, MemoryStatus.ACTIVE, "promoted")

    def reject(self, memory_id: str, reason: str) -> MemoryRecord:
        record = self._require(memory_id)
        return self._set_status(record, MemoryStatus.REVOKED, f"rejected: {reason}")

    def supersede(self, memory_id: str, new_content: str, evidence: MemoryEvidence) -> MemoryRecord:
        old = self._require(memory_id)
        new_id = self._next_id("mem")
        new_record = MemoryRecord(
            memory_id=new_id, content=new_content, memory_type=old.memory_type,
            status=MemoryStatus.OBSERVED, evidence=evidence, valid_from=_now(), supersedes=old.memory_id,
            labels=old.labels,
        )
        self._records[new_id] = new_record
        self._history[new_id] = []
        new_record = self._set_status(new_record, MemoryStatus.CANDIDATE, "supersession")
        new_record = self._set_status(new_record, MemoryStatus.ACTIVE, f"supersedes {old.memory_id}")

        superseded_old = MemoryRecord(
            memory_id=old.memory_id, content=old.content, memory_type=old.memory_type,
            status=old.status, evidence=old.evidence, created_at=old.created_at, updated_at=_now(),
            valid_from=old.valid_from, valid_to=_now(), supersedes=old.supersedes, superseded_by=new_id,
            labels=old.labels,
        )
        self._records[old.memory_id] = superseded_old
        self._set_status(superseded_old, MemoryStatus.SUPERSEDED, f"superseded by {new_id}")
        return new_record

    def revoke(self, memory_id: str, reason: str) -> MemoryRecord:
        record = self._require(memory_id)
        return self._set_status(record, MemoryStatus.REVOKED, f"revoked: {reason}")

    def _require(self, memory_id: str) -> MemoryRecord:
        record = self._records.get(memory_id)
        if record is None:
            raise MemoryUnavailable(f"No such memory: {memory_id}")
        return record

    def query(self, query: MemoryQuery) -> MemoryResult:
        candidates: list[MemoryRecord] = []
        for record in self._records.values():
            if record.status == MemoryStatus.REVOKED:
                continue  # never surfaced, even historically -- see why()/history() for audit
            if query.as_of is not None:
                if not self._valid_at(record, query.as_of):
                    continue
            else:
                if record.status == MemoryStatus.SUPERSEDED and not query.include_superseded:
                    continue
                if record.status not in (MemoryStatus.ACTIVE, MemoryStatus.SUPERSEDED):
                    continue
            if not self._matches(record, query.text):
                continue
            candidates.append(record)

        candidates.sort(key=lambda r: r.created_at)
        return MemoryResult(query=query, records=tuple(candidates[: query.limit]))

    def _matches(self, record: MemoryRecord, text: str) -> bool:
        """Word-overlap matching, not exact substring: a natural-language
        query ("What is the API rate limit?") must be able to find terse
        stored content ("The API rate limit is 1000 req/s.") even though
        the query is never a literal substring of the content. A
        production adapter would delegate to the backing tool's own
        search (as zmem/m3-memory do); this is a reference-quality
        heuristic, not a claim about retrieval-precision benchmarking."""
        if not text:
            return True
        content_lower = record.content.lower()
        if text.lower() in content_lower:
            return True
        if any(text.lower() in label.lower() for label in record.labels):
            return True
        words = [w.strip("?.,!:;\"'()") for w in text.lower().split()]
        significant = [w for w in words if len(w) > 2]
        if not significant:
            return False
        hits = sum(1 for w in significant if w in content_lower)
        return hits >= max(1, len(significant) // 2)

    def _valid_at(self, record: MemoryRecord, as_of: str) -> bool:
        if record.valid_from is not None and as_of < record.valid_from:
            return False
        if record.valid_to is not None and as_of >= record.valid_to:
            return False
        return True

    def inject(self, action_id: str, task: str, agent: str) -> MemoryInfluence:
        result = self.query(MemoryQuery(text=task, limit=50))
        memory_ids = tuple(r.memory_id for r in result.records)
        proof = hashlib.sha256(json.dumps({"action_id": action_id, "memory_ids": list(memory_ids)}).encode()).hexdigest()
        influence = MemoryInfluence(action_id=action_id, memory_ids=memory_ids, proof=proof)
        self._influences[action_id] = influence
        return influence

    def why(self, action_id: str) -> MemoryInfluence:
        influence = self._influences.get(action_id)
        if influence is None:
            raise MemoryUnavailable(f"No recorded influence for action: {action_id}")
        return influence

    def history(self, memory_id: str) -> tuple[MemoryRevision, ...]:
        if memory_id not in self._history:
            raise MemoryUnavailable(f"No such memory: {memory_id}")
        return tuple(self._history[memory_id])
