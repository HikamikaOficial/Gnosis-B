"""Strict replay + write-ahead intent (Directive 7).

Two mechanisms that together make a run reproducible and its side effects
decidable, from docs/research/REFERENCE_REPOSITORY_FINDINGS.md §7:

**Strict replay (`InteractionStore`).** Every LLM/tool call is recorded
under a content hash of its *response-determining* parameters — which the
caller declares explicitly in a `CallSpec` rather than the store guessing
from an opaque blob. Replay is **occurrence-aware**: the same key called
three times replays the first, second and third recorded responses in
order, preserving both call order and multiplicity. Replay is **strict by
default**: a miss is a `ReplayMiss` abort, never a silent fall-through to
a live model (bernstein's `DeterministicStore` rule). Falling through is
`ReplayMode.REPLAY_OR_RECORD` — an explicit opt-in, not a default.

**Write-ahead intent (`IntentJournal`).** Before a side-effecting tool
executes, an `intent.declared` row is persisted carrying the side-effect
provenance flags (side_effect, idempotent, has_revert, idempotency_key).
The outcome is a second row. Rewind/fork/compensation safety then becomes
a *query* over the journal, never a guess: an intent declared with no
outcome is precisely the "did it actually happen?" case a crash leaves
behind, and it is reported as such instead of being assumed either way.

The journal is a `RunLedger` (ADR-0004): append-only, hash-chained,
tamper-evident, torn-tail tolerant. Keys use `kernel.canonical`, the
kernel's single hash contract — no second encoding is introduced here.
"""
from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from .canonical import hash_canonical
from .file_lock import FileLock, lock_path_for
from .ledger import RunLedger

INTENT_DECLARED = "intent.declared"
INTENT_COMPLETED = "intent.completed"
INTENT_FAILED = "intent.failed"


class ReplayError(RuntimeError):
    pass


class ReplayMiss(ReplayError):
    """Strict replay found no recorded response for this call.

    Carries the key and occurrence so a failing replay names exactly what
    was missing instead of degrading into a live call."""

    def __init__(self, spec: CallSpec, occurrence: int, recorded: int):
        super().__init__(
            f"replay miss for tool {spec.tool!r} key {spec.key()[:16]}… "
            f"occurrence {occurrence} (only {recorded} recorded)"
        )
        self.spec = spec
        self.occurrence = occurrence
        self.recorded = recorded


class ReplayMode(str, Enum):
    RECORD = "RECORD"                    # execute live, record the response
    REPLAY = "REPLAY"                    # strict: a miss aborts
    REPLAY_OR_RECORD = "REPLAY_OR_RECORD"  # explicit opt-in fall-through


@dataclass(frozen=True)
class CallSpec:
    """One call, identified by its response-determining parameters.

    ``params`` must contain everything that can change the response
    (model, provider, temperature, max_tokens, effort, prompt, tool
    arguments…) and nothing that cannot (timestamps, durations, request
    ids). Anything non-determining belongs in ``metadata``, which is
    recorded but never keyed — folding a timestamp into the key would
    make every replay a miss."""

    tool: str
    params: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    def key(self) -> str:
        return hash_canonical({"tool": self.tool, "params": self.params})


@dataclass(frozen=True)
class InteractionRecord:
    key: str
    tool: str
    occurrence: int
    params: dict[str, Any]
    response: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    # A call that really happened but whose response could not be encoded.
    # Recorded so the audit trail and occurrence numbering stay complete;
    # replaying it fails closed instead of inventing a value.
    unrecordable: str | None = None

    def replayed_response(self) -> Any:
        if self.unrecordable is not None:
            raise ReplayError(
                f"occurrence {self.occurrence} of tool {self.tool!r} was executed "
                f"live but its response could not be recorded ({self.unrecordable}); "
                "it cannot be replayed"
            )
        return self.response

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": self.key, "tool": self.tool, "occurrence": self.occurrence,
            "params": self.params, "response": self.response, "metadata": self.metadata,
        }
        if self.unrecordable is not None:
            payload["unrecordable"] = self.unrecordable
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InteractionRecord:
        return cls(
            key=data["key"], tool=data["tool"], occurrence=data["occurrence"],
            params=data["params"], response=data["response"],
            metadata=data.get("metadata", {}),
            unrecordable=data.get("unrecordable"),
        )


class InteractionStore:
    """Occurrence-aware, content-addressed cassette of recorded calls.

    One append-only JSONL file. Recording appends; replaying consumes
    per-key FIFO cursors held in memory for the life of this instance, so
    a fresh instance replays a run from the beginning — replay is a
    property of the run, not of the process.
    """

    def __init__(self, path: Path, mode: ReplayMode | str = ReplayMode.RECORD,
                 lock_timeout_s: float = 30.0):
        self.path = path
        # Coerce, never trust the caller's type. ReplayMode subclasses str,
        # so a bare "REPLAY" compares EQUAL in `in (...)` tests but is not
        # IDENTICAL in `is` tests — which turned strict replay into a
        # silent live call (adversarial review, reproduced). Coercing here
        # removes the whole class of mismatch.
        self.mode = ReplayMode(mode)
        self._lock_timeout_s = lock_timeout_s
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._by_key: dict[str, list[InteractionRecord]] = {}
        self._cursor: dict[str, int] = {}
        # Incremental occurrence accounting for the append path.
        self._counted: dict[str, int] = {}
        self._scanned_bytes = 0
        self._order: list[InteractionRecord] = []
        self._load()

    # -- recording / replaying ------------------------------------------

    def call(self, spec: CallSpec, live_fn: Callable[[], Any]) -> Any:
        """Return this call's response, from the cassette or live, per mode.

        ``live_fn`` is invoked only when the mode allows a live call; in
        strict REPLAY it is never invoked, so a replayed run cannot reach
        the network even if a key is missing.
        """
        occurrence = self._cursor.get(spec.key(), 0)
        if self.mode in (ReplayMode.REPLAY, ReplayMode.REPLAY_OR_RECORD):
            existing = self._by_key.get(spec.key(), [])
            if occurrence < len(existing):
                self._cursor[spec.key()] = occurrence + 1
                return existing[occurrence].replayed_response()
            if self.mode is ReplayMode.REPLAY:
                raise ReplayMiss(spec, occurrence, len(existing))
        response = live_fn()
        # Return the ROUND-TRIPPED value, not the live object: a recording
        # run and a replaying run must observe byte-identical responses, or
        # "deterministic replay" is a lie the first time a tuple comes back
        # as a list. Verified: without this, RECORD saw ('a','b') where
        # REPLAY saw ['a','b'].
        record = self._append(spec, response)
        self._cursor[spec.key()] = record.occurrence + 1
        return record.replayed_response()

    def replayed_count(self, spec: CallSpec) -> int:
        return self._cursor.get(spec.key(), 0)

    def records(self) -> list[InteractionRecord]:
        """Recorded interactions in TRUE CALL ORDER.

        Grouping by key hash (the previous behavior) produced a
        pseudo-random order and made an exported fixture strictly less
        faithful than the cassette it came from (adversarial review)."""
        return list(self._order)

    def unused(self) -> list[InteractionRecord]:
        """Recorded interactions this replay never consumed — the signal
        that a golden fixture and the current code have diverged."""
        return [
            record
            for key, records in self._by_key.items()
            for record in records[self._cursor.get(key, 0):]
        ]

    # -- internals -------------------------------------------------------

    def _append(self, spec: CallSpec, response: Any) -> InteractionRecord:
        """Append one interaction, allocating its occurrence number under
        the file lock.

        The occurrence must be derived from what is ON DISK inside the
        critical section, not from this instance's in-memory cursor: two
        recorders (threads or processes) sharing a cassette otherwise both
        compute occurrence 0 and write duplicates, corrupting every later
        replay (Codex review).
        """
        unrecordable: str | None = None
        try:
            json.dumps(response, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            # The live call already happened, so the cassette must record
            # that it happened — dropping the row would silently shift
            # every later occurrence. The response itself is unusable, so
            # replaying this row fails closed instead of inventing a value.
            unrecordable = f"{type(exc).__name__}: {exc}"
            response = None

        # Metadata is caller-supplied and its docstring invites timestamps
        # and request ids — i.e. exactly the objects json refuses. It must
        # never be able to destroy the row for a call that really happened
        # (adversarial review, reproduced: a datetime in metadata left zero
        # rows on disk). Degrade it to a printable form instead.
        metadata = spec.metadata
        try:
            json.dumps(metadata, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            metadata = {
                "_unencodable_metadata": repr(spec.metadata)[:2000],
                "_error": f"{type(exc).__name__}: {exc}",
            }

        with FileLock(lock_path_for(self.path), timeout_s=self._lock_timeout_s):
            occurrence = self._occurrences_on_disk(spec.key())
            record = InteractionRecord(
                key=spec.key(), tool=spec.tool, occurrence=occurrence,
                params=spec.params, response=response, metadata=metadata,
                unrecordable=unrecordable,
            )
            line = json.dumps(record.to_dict(), sort_keys=True, allow_nan=False)
            # Re-read what was actually serialized: this is the value the
            # store returns and the value a later replay will produce.
            record = InteractionRecord.from_dict(json.loads(line))
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                # fsync like RunLedger: a flushed-but-unsynced tail is
                # exactly the torn line that would otherwise be lost.
                os.fsync(fh.fileno())
        self._by_key.setdefault(record.key, []).append(record)
        self._order.append(record)
        # _counted is NOT bumped here: the next append's tail scan reads
        # this row from disk and counts it there. Doing both double-counted
        # and produced occurrences 0, 2, 4.
        return record

    def _occurrences_on_disk(self, key: str) -> int:
        """Count of recorded occurrences for ``key``. Called under the lock.

        Reads only the bytes appended since this instance last looked:
        re-parsing the whole cassette on every append made recording
        quadratic in its own call count, with the exclusive lock held
        (adversarial review).
        """
        if not self.path.exists():
            return self._counted.get(key, 0)
        size = self.path.stat().st_size
        if size > self._scanned_bytes:
            with self.path.open("r", encoding="utf-8") as fh:
                fh.seek(self._scanned_bytes)
                tail = fh.read()
            consumed = self._scanned_bytes
            for raw in tail.splitlines(keepends=True):
                if not raw.endswith("\n"):
                    break  # partial trailing line: leave it unconsumed
                consumed += len(raw.encode("utf-8"))
                line = raw.strip()
                if not line:
                    continue
                try:
                    other = json.loads(line).get("key")
                except json.JSONDecodeError:
                    continue  # interior corruption is _load's business
                if isinstance(other, str):
                    self._counted[other] = self._counted.get(other, 0) + 1
            self._scanned_bytes = consumed
        return self._counted.get(key, 0)

    def _load(self) -> None:
        if not self.path.exists():
            return
        raw_lines = [line for line in self.path.read_text(encoding="utf-8").splitlines()
                     if line.strip()]
        last_index = len(raw_lines) - 1
        for index, line in enumerate(raw_lines):
            try:
                record = InteractionRecord.from_dict(json.loads(line))
            except (json.JSONDecodeError, KeyError) as exc:
                if index == last_index:
                    # Torn final line: a process killed mid-append. Earlier
                    # fsync'd rows are intact evidence, exactly as RunLedger
                    # treats its own tail — bricking the cassette over a
                    # crash would lose a whole recorded run.
                    break
                raise ReplayError(
                    f"corrupt cassette line {index + 1} in {self.path}: {exc}"
                ) from exc
            self._by_key.setdefault(record.key, []).append(record)
            self._order.append(record)
        for key, records in self._by_key.items():
            records.sort(key=lambda r: r.occurrence)
            # Replay serves records BY POSITION, so the occurrence labels
            # must be exactly 0..n-1. A gap or a duplicate (hand-edited
            # fixture, partial recovery) would otherwise silently replay a
            # different call's response instead of aborting — the one
            # outcome strict replay exists to prevent (adversarial review,
            # reproduced).
            expected = list(range(len(records)))
            actual = [r.occurrence for r in records]
            if actual != expected:
                raise ReplayError(
                    f"cassette {self.path} has non-contiguous occurrences for "
                    f"key {key[:16]}…: {actual} (expected {expected})"
                )


# -- write-ahead intent ---------------------------------------------------


class IntentStatus(str, Enum):
    DECLARED = "DECLARED"    # persisted, outcome unknown (crash window)
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class SideEffect:
    """Provenance of what a tool call is about to do.

    ``idempotent``: re-running it is safe. ``has_revert``: a compensating
    action exists. ``idempotency_key``: the token a remote system uses to
    deduplicate a retry."""

    side_effect: bool
    idempotent: bool = False
    has_revert: bool = False
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "side_effect": self.side_effect, "idempotent": self.idempotent,
            "has_revert": self.has_revert, "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SideEffect:
        return cls(
            side_effect=data["side_effect"], idempotent=data.get("idempotent", False),
            has_revert=data.get("has_revert", False),
            idempotency_key=data.get("idempotency_key"),
        )


@dataclass(frozen=True)
class IntentRecord:
    intent_id: str
    tool: str
    status: IntentStatus
    effect: SideEffect
    params: dict[str, Any]
    outcome: dict[str, Any] | None = None
    seq: int = 0            # ledger sequence of the declaration
    certain: bool = True    # False when the outcome is only inferred

    @property
    def unresolved(self) -> bool:
        """The side effect's fate is unknown: either no outcome was ever
        recorded (crash window), or the outcome recorded is an inference
        rather than an observation — a body that raised proves the call
        did not RETURN, never that the effect did not LAND (adversarial
        review: those two were indistinguishable)."""
        return self.status is IntentStatus.DECLARED or not self.certain

    @property
    def blocks_rewind(self) -> bool:
        """A side effect that can be neither safely repeated nor undone —
        rewinding past it is unsafe, and the journal says so rather than
        the caller guessing."""
        return self.effect.side_effect and not self.effect.idempotent and not self.effect.has_revert


class IntentJournal:
    """Write-ahead journal of side-effecting intents, on a hash-chained
    RunLedger (ADR-0004): append-only and tamper-evident.

    Usage::

        with journal.intent("git.push", effect, params) as handle:
            do_the_thing()
            handle.complete({"pushed": True})

    The declaration is durable BEFORE the body runs; an exception marks
    the intent failed and propagates; a crash leaves it DECLARED, which
    ``unresolved()`` reports as an open question rather than assuming
    either outcome.
    """

    def __init__(self, ledger: RunLedger, run_id: str):
        self.ledger = ledger
        self.run_id = run_id
        self._counter = 0

    def intent(self, tool: str, effect: SideEffect,
               params: dict[str, Any] | None = None) -> _IntentHandle:
        self._counter += 1
        # Globally unique, not per-instance: two journals over the same
        # ledger — the normal case when a crashed run is RESUMED — used to
        # mint the same id, and folding then let a later completion mark a
        # still-unresolved DANGEROUS intent as done (Codex review,
        # critical). uuid4 removes the collision entirely.
        intent_id = f"INTENT-{self._counter:04d}-{uuid.uuid4().hex[:12]}"
        payload = {
            "intent_id": intent_id, "tool": tool, "effect": effect.to_dict(),
            "params": params or {},
        }
        # Durable BEFORE the side effect: this ordering is the whole point.
        self.ledger.append(self.run_id, INTENT_DECLARED, payload)
        return _IntentHandle(self, intent_id, tool, effect, params or {})

    def _record_outcome(self, intent_id: str, event_type: str,
                        outcome: dict[str, Any], certain: bool = True) -> None:
        self.ledger.append(self.run_id, event_type,
                           {"intent_id": intent_id, "outcome": outcome,
                            "certain": certain})

    # -- queries (rewind safety is answered here, never guessed) ---------

    def records(self, verify: bool = True) -> list[IntentRecord]:
        """Fold the journal into intent records.

        ``verify=True`` (the default) recomputes the ledger's hash chain
        first: these records decide whether destroying work is safe, and a
        safety answer read from an unverified chain is worthless (Codex
        review). Pass verify=False only for non-safety inspection.
        """
        declared: dict[str, dict[str, Any]] = {}
        declared_seq: dict[str, int] = {}
        status: dict[str, IntentStatus] = {}
        outcomes: dict[str, dict[str, Any]] = {}
        certain: dict[str, bool] = {}
        order: list[str] = []
        events = self.ledger.verify_chain() if verify else self.ledger.read_all()
        for event in events:
            # Scope to this run: one ledger may carry several runs' events.
            if event.run_id != self.run_id:
                continue
            if event.event_type == INTENT_DECLARED:
                intent_id = event.data["intent_id"]
                declared[intent_id] = event.data
                declared_seq[intent_id] = event.seq
                status[intent_id] = IntentStatus.DECLARED
                certain[intent_id] = True
                order.append(intent_id)
            elif event.event_type in (INTENT_COMPLETED, INTENT_FAILED):
                intent_id = event.data["intent_id"]
                if intent_id in declared:
                    status[intent_id] = (
                        IntentStatus.COMPLETED if event.event_type == INTENT_COMPLETED
                        else IntentStatus.FAILED
                    )
                    outcomes[intent_id] = event.data.get("outcome", {})
                    certain[intent_id] = bool(event.data.get("certain", True))
        return [
            IntentRecord(
                intent_id=intent_id, tool=declared[intent_id]["tool"],
                status=status[intent_id],
                effect=SideEffect.from_dict(declared[intent_id]["effect"]),
                params=declared[intent_id].get("params", {}),
                outcome=outcomes.get(intent_id),
                seq=declared_seq[intent_id],
                certain=certain[intent_id],
            )
            for intent_id in order
        ]

    def unresolved(self) -> list[IntentRecord]:
        """Intents whose side effect's fate is unknown — no outcome at all
        (crash window), or an outcome that was inferred rather than
        observed. After a crash these are exactly the calls that must be
        resolved by inspection, not assumption."""
        return [r for r in self.records() if r.unresolved]

    def rewind_blockers(self, since_seq: int = 0) -> list[IntentRecord]:
        """Side effects that neither repeat safely nor revert, plus every
        intent of unknown fate (an unknown outcome cannot be declared
        safe).

        ``since_seq`` scopes the question to "can I rewind to this
        checkpoint?" — rewind is inherently rewind-to-a-point, and intents
        that predate the target are irrelevant to it (adversarial review).
        The default, 0, asks about the whole run.
        """
        return [
            r for r in self.records()
            if r.seq > since_seq and (r.blocks_rewind or r.unresolved)
        ]

    def can_rewind(self, since_seq: int = 0) -> bool:
        return not self.rewind_blockers(since_seq=since_seq)


class _IntentHandle:
    """Context manager returned by ``IntentJournal.intent``."""

    def __init__(self, journal: IntentJournal, intent_id: str, tool: str,
                 effect: SideEffect, params: dict[str, Any]):
        self.journal = journal
        self.intent_id = intent_id
        self.tool = tool
        self.effect = effect
        self.params = params
        self._resolved = False
        # Set the moment an outcome write is attempted. If that write
        # fails, the exception reaches __exit__, which must NOT then
        # record the opposite outcome for an effect that actually
        # succeeded (adversarial review): leaving the intent DECLARED —
        # "we could not record what happened" — is the honest state.
        self._outcome_attempted = False

    def complete(self, outcome: dict[str, Any] | None = None) -> None:
        if self._resolved:
            raise ReplayError(f"intent {self.intent_id} already resolved")
        self._outcome_attempted = True
        self.journal._record_outcome(self.intent_id, INTENT_COMPLETED, outcome or {})
        self._resolved = True

    def fail(self, outcome: dict[str, Any] | None = None) -> None:
        if self._resolved:
            raise ReplayError(f"intent {self.intent_id} already resolved")
        self._outcome_attempted = True
        self.journal._record_outcome(self.intent_id, INTENT_FAILED, outcome or {})
        self._resolved = True

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._resolved or self._outcome_attempted:
            # Either resolved, or an outcome write was attempted and threw:
            # inventing the opposite verdict here would be worse than the
            # missing row (the intent stays DECLARED = unknown fate).
            return
        if exc_type is not None:
            # The body raised: record it as an INFERRED failure. An
            # exception proves the call did not RETURN, never that the
            # effect did not LAND, so `certain=False` keeps this intent in
            # unresolved()/rewind_blockers() instead of passing it off as a
            # known non-occurrence (adversarial review).
            self.journal._record_outcome(
                self.intent_id, INTENT_FAILED,
                {"error": repr(exc), "effect_landed": "unknown"}, certain=False,
            )
            self._resolved = True
            return
        # Body finished without saying what happened. Leaving the intent
        # DECLARED (rather than inventing a completion) is deliberate: an
        # unclaimed outcome is exactly the state unresolved() exists to
        # report.


def golden_fixture(store: InteractionStore) -> Iterator[dict[str, Any]]:
    """Recorded interactions as fixture rows, in true call order — a
    golden run becomes a regression fixture (catacomb's pattern) without
    a second format."""
    for record in store.records():
        yield record.to_dict()


def write_golden_fixture(store: InteractionStore, path: Path) -> Path:
    """Freeze a recorded run as a fixture file.

    The fixture IS a cassette (same format), so ``load_golden_fixture``
    is the round trip and no importer has to be written twice — the
    previous one-way export had no import path at all (adversarial
    review)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in golden_fixture(store):
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return path


def load_golden_fixture(path: Path) -> InteractionStore:
    """Open a frozen fixture for strict replay — the regression-test entry
    point: a run replayed against this store cannot reach the network,
    and any drift from the golden run aborts."""
    return InteractionStore(path, mode=ReplayMode.REPLAY)
