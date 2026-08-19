"""Gnosis's own Memory Plane contract (M3).

Gnosis owns this interface; external memory systems are providers behind
it, exactly like kernel.code_intelligence.CodeIntelligenceProvider. No
kernel code should import a vendor-specific memory client directly.

Every shape here is evidence-backed, not speculative: MemoryStatus's
lifecycle and MemoryProvider's method set were derived from real,
executed behavior of zmem (M3.1 lab benchmark: remember/propose/promote/
reject/revoke/inject/why, all actually run) and m3-memory's CLI surface
(memory_supersede, valid_from/valid_to bitemporal fields, memory_history).

This is explicitly NOT the run ledger (kernel.ledger.RunLedger). The
ledger is immutable, append-only, raw execution evidence -- everything
that happened. Memory is curated, governed, and revisable -- a claim
about the world that started as evidence and was judged worth keeping.
Not every ledger event deserves to become a memory.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class MemoryStatus(str, Enum):
    """OBSERVED -> CANDIDATE -> QUARANTINED -> ACTIVE -> SUPERSEDED/REVOKED.

    Matches real zmem behavior: human/system-authored content can skip
    QUARANTINED and go straight to ACTIVE (see MemoryProvider.remember
    vs .propose); agent/tool/import-authored content is expected to sit
    in QUARANTINED pending an explicit promote/reject.
    """

    OBSERVED = "OBSERVED"
    CANDIDATE = "CANDIDATE"
    QUARANTINED = "QUARANTINED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class IllegalMemoryTransitionError(RuntimeError):
    def __init__(self, current: MemoryStatus, target: MemoryStatus):
        super().__init__(f"Illegal memory transition: {current.value} -> {target.value}")
        self.current = current
        self.target = target


MEMORY_TRANSITIONS: dict[MemoryStatus, frozenset[MemoryStatus]] = {
    MemoryStatus.OBSERVED: frozenset({MemoryStatus.CANDIDATE}),
    MemoryStatus.CANDIDATE: frozenset({MemoryStatus.QUARANTINED, MemoryStatus.ACTIVE}),
    MemoryStatus.QUARANTINED: frozenset({MemoryStatus.ACTIVE, MemoryStatus.REVOKED}),
    MemoryStatus.ACTIVE: frozenset({MemoryStatus.SUPERSEDED, MemoryStatus.REVOKED}),
    MemoryStatus.SUPERSEDED: frozenset(),
    MemoryStatus.REVOKED: frozenset(),
}

MEMORY_TERMINAL_STATES = frozenset({MemoryStatus.SUPERSEDED, MemoryStatus.REVOKED})


def validate_memory_transition(current: MemoryStatus, target: MemoryStatus) -> MemoryStatus:
    if target not in MEMORY_TRANSITIONS.get(current, frozenset()):
        raise IllegalMemoryTransitionError(current, target)
    return target


@dataclass(frozen=True)
class MemoryEvidence:
    """Provenance: WHERE a memory came from and HOW confident we are.
    source_kind mirrors zmem's real, enforced vocabulary (human/system
    authored content is trusted enough to skip quarantine)."""

    source_kind: str  # "human" | "system" | "tool" | "document" | "agent" | "import"
    source_uri: str | None = None
    actor_uri: str | None = None
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind, "source_uri": self.source_uri,
            "actor_uri": self.actor_uri, "confidence": self.confidence,
        }


@dataclass(frozen=True)
class MemoryRecord:
    """WHAT do we know, WHEN was it true, WHY do we believe it (via
    .evidence), and WHAT superseded it. `valid_from`/`valid_to` are the
    bitemporal fields verified present in m3-memory's real memory_write
    CLI surface; `supersedes`/`superseded_by` are the explicit-lineage
    fields matching its real memory_supersede tool."""

    memory_id: str
    content: str
    memory_type: str
    status: MemoryStatus
    evidence: MemoryEvidence
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    valid_from: str | None = None
    valid_to: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    labels: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id, "content": self.content, "memory_type": self.memory_type,
            "status": self.status.value, "evidence": self.evidence.to_dict(),
            "created_at": self.created_at, "updated_at": self.updated_at,
            "valid_from": self.valid_from, "valid_to": self.valid_to,
            "supersedes": self.supersedes, "superseded_by": self.superseded_by,
            "labels": list(self.labels),
        }


@dataclass(frozen=True)
class MemoryQuery:
    """`as_of` is the bitemporal query hook: None means "current truth";
    a timestamp means "what did we believe was true at that instant" (the
    Director's T1-vs-current temporal-truth scenario)."""

    text: str
    as_of: str | None = None
    scope: str | None = None
    include_superseded: bool = False
    limit: int = 10


@dataclass(frozen=True)
class MemoryResult:
    query: MemoryQuery
    records: tuple[MemoryRecord, ...]
    stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_text": self.query.text, "as_of": self.query.as_of,
            "records": [r.to_dict() for r in self.records], "stale": self.stale,
        }


@dataclass(frozen=True)
class MemoryInfluence:
    """Answers "WHAT decisions/actions did it influence?" -- a receipt
    tying an action to the memories that shaped it. `proof` is an opaque
    verifiable token slot (zmem's real implementation uses a Merkle proof
    root; other providers may leave this None)."""

    action_id: str
    memory_ids: tuple[str, ...]
    created_at: str = field(default_factory=_utc_now_iso)
    proof: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id, "memory_ids": list(self.memory_ids),
            "created_at": self.created_at, "proof": self.proof,
        }


@dataclass(frozen=True)
class MemoryRevision:
    """One audit-trail entry: a status transition, WHY it happened, and
    WHO/WHAT caused it. A sequence of these is a memory's `history()`."""

    memory_id: str
    previous_status: MemoryStatus
    new_status: MemoryStatus
    reason: str
    changed_at: str = field(default_factory=_utc_now_iso)
    changed_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id, "previous_status": self.previous_status.value,
            "new_status": self.new_status.value, "reason": self.reason,
            "changed_at": self.changed_at, "changed_by": self.changed_by,
        }


class MemoryUnavailable(RuntimeError):
    """Raised when a provider cannot answer. Callers must treat memory as
    optional context, never a hard dependency of task correctness --
    exactly the CodeIntelligenceUnavailable contract in
    kernel.code_intelligence, applied to memory."""


class MemoryProvider(ABC):
    """The contract. Every method here maps to something actually
    exercised against a real tool in the M3.1 lab benchmark (zmem's CLI),
    not a speculative API. IS-allowed-to-influence is enforced by the
    remember/propose split: `remember` is for already-trusted sources and
    goes ACTIVE immediately; `propose` starts at CANDIDATE/QUARANTINED
    and requires an explicit `promote` before it can be returned by
    `query()` or included by an `inject()` context gather."""

    @abstractmethod
    def remember(
        self, content: str, memory_type: str, evidence: MemoryEvidence,
        valid_from: str | None = None, labels: tuple[str, ...] = (),
    ) -> MemoryRecord:
        """Store a trusted memory; goes ACTIVE immediately."""
        raise NotImplementedError

    @abstractmethod
    def propose(
        self, content: str, memory_type: str, evidence: MemoryEvidence,
        valid_from: str | None = None, labels: tuple[str, ...] = (),
    ) -> MemoryRecord:
        """Propose a memory that is not yet authorized to influence
        actions; starts QUARANTINED pending promote()/reject()."""
        raise NotImplementedError

    @abstractmethod
    def promote(self, memory_id: str) -> MemoryRecord:
        """QUARANTINED -> ACTIVE."""
        raise NotImplementedError

    @abstractmethod
    def reject(self, memory_id: str, reason: str) -> MemoryRecord:
        """QUARANTINED -> REVOKED, without it ever having influenced anything."""
        raise NotImplementedError

    @abstractmethod
    def supersede(self, memory_id: str, new_content: str, evidence: MemoryEvidence) -> MemoryRecord:
        """Create a new ACTIVE record that replaces `memory_id`; the old
        record moves to SUPERSEDED (kept, not deleted -- temporal truth
        at the old record's valid window is preserved)."""
        raise NotImplementedError

    @abstractmethod
    def revoke(self, memory_id: str, reason: str) -> MemoryRecord:
        """ACTIVE/QUARANTINED -> REVOKED. Must stop influencing future
        actions immediately; past actions it already influenced remain
        traceable via why()/history(), not erased."""
        raise NotImplementedError

    @abstractmethod
    def query(self, query: MemoryQuery) -> MemoryResult:
        """Retrieve ACTIVE (and, if requested, SUPERSEDED) memories
        relevant to `query`. Must never silently return REVOKED memories."""
        raise NotImplementedError

    @abstractmethod
    def inject(self, action_id: str, task: str, agent: str) -> MemoryInfluence:
        """Retrieve authorized memories for an agent action and record
        the receipt of what influenced it."""
        raise NotImplementedError

    @abstractmethod
    def why(self, action_id: str) -> MemoryInfluence:
        """Explain which memories shaped a past action (even if some have
        since been revoked -- the historical receipt does not change)."""
        raise NotImplementedError

    @abstractmethod
    def history(self, memory_id: str) -> tuple[MemoryRevision, ...]:
        """Full status-change audit trail for one memory."""
        raise NotImplementedError


class NullMemoryProvider(MemoryProvider):
    """Reference implementation: always unavailable. Proves the contract
    requires no specific vendor to exist -- Gnosis works with zero memory
    providers configured, exactly like NullCodeIntelligenceProvider."""

    def remember(
        self, content: str, memory_type: str, evidence: MemoryEvidence,
        valid_from: str | None = None, labels: tuple[str, ...] = (),
    ) -> MemoryRecord:
        raise MemoryUnavailable("No MemoryProvider is configured.")

    def propose(
        self, content: str, memory_type: str, evidence: MemoryEvidence,
        valid_from: str | None = None, labels: tuple[str, ...] = (),
    ) -> MemoryRecord:
        raise MemoryUnavailable("No MemoryProvider is configured.")

    def promote(self, memory_id: str) -> MemoryRecord:
        raise MemoryUnavailable("No MemoryProvider is configured.")

    def reject(self, memory_id: str, reason: str) -> MemoryRecord:
        raise MemoryUnavailable("No MemoryProvider is configured.")

    def supersede(self, memory_id: str, new_content: str, evidence: MemoryEvidence) -> MemoryRecord:
        raise MemoryUnavailable("No MemoryProvider is configured.")

    def revoke(self, memory_id: str, reason: str) -> MemoryRecord:
        raise MemoryUnavailable("No MemoryProvider is configured.")

    def query(self, query: MemoryQuery) -> MemoryResult:
        raise MemoryUnavailable("No MemoryProvider is configured.")

    def inject(self, action_id: str, task: str, agent: str) -> MemoryInfluence:
        raise MemoryUnavailable("No MemoryProvider is configured.")

    def why(self, action_id: str) -> MemoryInfluence:
        raise MemoryUnavailable("No MemoryProvider is configured.")

    def history(self, memory_id: str) -> tuple[MemoryRevision, ...]:
        raise MemoryUnavailable("No MemoryProvider is configured.")
