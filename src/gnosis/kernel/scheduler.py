"""The hold/park plane under a real scheduler (adapter milestone 4/4).

ADR-0012 built credential-scoped rate-limit holds, recovery-as-reconcile
and `boot_sweep`, and said plainly that none of it had a production
caller. This is that caller — the last of the four mechanisms Directive
9's review found were parallel fictions.

The scheduler is deliberately small. It is not a queue, a worker pool or
a priority system; those are the multi-worker milestone. It is the three
places where the hold plane has to be consulted for it to be real:

1. **Before a launch**, ask whether the credential is admitted. A task
   refused by a hold is PARKED — recorded, resumable, not failed, and
   never counted against agent quality (rules 6 and 7).
2. **After a run parks**, place a durable hold, so the next launch (in
   this process or a later one) sees it. A hold that lives only in memory
   is a hold the restart forgets, which is how one rate limit becomes a
   stampede.
3. **At boot**, sweep runs left stranded by a crash, so no record is left
   neither progressing nor terminal.

Durability is a JSONL of hold rows. The registry is rebuilt from them on
every pump, never mutated in place: `reconcile` is a rebuild, so a double
pump, a concurrent scheduler and a restart all land in the same state.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..runner.liveness import ProcessFingerprint, is_alive
from .credentials import CredentialKind, CredentialPool, Rotation
from .engine import TaskEngine, TaskExecutionOutcome
from .failures import (
    UNKNOWN_WINDOW_FALLBACK_S,
    Disposition,
    FailureClass,
    FailureClassification,
    HoldRegistry,
    HoldScope,
    RateLimitHold,
    StrandedRun,
    SweepOutcome,
    boot_sweep,
    hold_from_classification,
)
from .file_lock import FileLock, lock_path_for
from .run_store import RunStore
from .state_machine import RunState

PARK_REASON = "rate_limited:credential_on_hold"


def _require_supersede_fields(payload: dict[str, Any]) -> str:
    """A control row that reopens a credential must be complete.

    `at` and `reason` were optional, so a half-specified row still erased
    every hold on a credential (Codex review). An incomplete decision is
    damage, and damage denies."""
    credential = payload.get("credential")
    if not isinstance(credential, str) or not credential:
        # ValueError throughout: a malformed durable row is corrupt data,
        # not a caller type error, and `read()` catches ValueError to
        # report damage (which denies).
        raise ValueError("supersede without a credential")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason:
        raise ValueError("supersede without a reason")
    at = payload.get("at")
    if isinstance(at, bool) or not isinstance(at, (int, float)):
        raise ValueError("supersede without a timestamp")  # noqa: TRY004
    return credential


@dataclass(frozen=True)
class HoldSnapshot:
    """What the durable log says, and what it could not say.

    `damaged` is load-bearing: a hold plane that cannot read its own
    records must not report "no holds"."""

    holds: tuple[RateLimitHold, ...]
    damaged: tuple[str, ...]


class HoldStore:
    """Append-only durable holds. One JSONL file, one lock.

    Append-only rather than a mutable table on purpose: a hold is a fact
    about a moment ("this credential was shut at T, reopening at R"), and
    facts are not edited. Expiry is computed at read time by `reconcile`,
    which means a stale row is inert rather than wrong.
    """

    def __init__(self, path: Path, lock_timeout_s: float = 30.0) -> None:
        self.path = path
        self._lock_timeout_s = lock_timeout_s
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def place(self, hold: RateLimitHold) -> RateLimitHold:
        self._append([{"row": "hold", **hold.to_dict()}])
        return hold

    def narrow(self, credential: str, at: float, reason: str,
               replacement: RateLimitHold) -> RateLimitHold:
        """Supersede and replace as ONE row.

        Two rows in one append is not enough: a crash can flush the first
        line and not the second, leaving a supersede with nothing
        replacing it — a credential wide open, durably. One row makes a
        torn write unparseable instead, which `read()` reports as damage
        and the scheduler denies on. The atomic unit here is the LINE, so
        an atomic transition has to be a line (Codex review, caught by a
        test that walked every prefix of the log).
        """
        self._append([{
            "row": "narrow", "credential": credential, "at": at,
            "reason": reason, "hold": replacement.to_dict(),
        }])
        return replacement

    def narrow_if_unclaimed(self, credential: str, at: float, reason: str,
                            replacement: RateLimitHold,
                            still_due: Callable[[RateLimitHold | None], bool]
                            | None = None) -> RateLimitHold | None:
        """Narrow, but only if nobody else already did — one winner.

        A check-then-append is not a claim. Two schedulers finding the
        probe due at the same instant both appended, the later row won the
        rebuild, and the loser could already have passed its own
        admission check and launched: two runs testing a window that may
        still be shut, which is the stampede in miniature. The read and
        the append happen under ONE lock here, which is the same
        compare-and-set shape the claims plane uses and for the same
        reason — a decision with exactly one winner cannot be assembled
        from two unsynchronised steps.
        """
        with FileLock(lock_path_for(self.path), timeout_s=self._lock_timeout_s):
            snapshot = self._read_unlocked()
            if snapshot.damaged:
                # Deny in the shut direction, as everywhere else.
                return None
            live = HoldRegistry().reconcile(snapshot.holds, at)
            current = next((h for h in live if h.credential == credential), None)
            if current is not None and current.scope is HoldScope.PROBE:
                return None
            if still_due is not None and not still_due(current):
                # DUENESS IS RE-CHECKED HERE, not only before the lock.
                # The atomic section used to guard "nobody else is
                # probing" while leaving "there is still a hold worth
                # probing" a check-then-act — so a provider window placed
                # between the two reads could be probed, and the ADR
                # promises a provider window never is (independent
                # review). Guarding the winner without guarding the
                # PRECONDITION is half a claim.
                return None
            self._write_unlocked([{
                "row": "narrow", "credential": credential, "at": at,
                "reason": reason, "hold": replacement.to_dict(),
            }])
        return replacement

    def supersede(self, credential: str, at: float, reason: str) -> None:
        """Draw a line: earlier rows for this credential no longer apply.

        `reconcile` deliberately keeps the MOST RESTRICTIVE competing
        hold, so two observations of a shut window can never relax each
        other by arriving in the wrong order. But that also means an
        appended row can never NARROW an existing hold — which made
        `probe()` dead code, since a PROBE row simply lost to the ACCOUNT
        row it was meant to replace. Its own test caught it.

        So observations and decisions are different rows. An observation
        competes; a decision supersedes. Both are durable and both name a
        reason, which is the property that matters: a window is never
        reopened silently, only by a recorded act.
        """
        self._append([{"row": "supersede", "credential": credential,
                       "at": at, "reason": reason}])

    def _append(self, payloads: list[dict[str, Any]]) -> None:
        with FileLock(lock_path_for(self.path), timeout_s=self._lock_timeout_s):
            self._write_unlocked(payloads)

    def _write_unlocked(self, payloads: list[dict[str, Any]]) -> None:
        """Caller holds the lock. Split out so that a read and an append
        can share one, which is what makes a claim a claim."""
        with self.path.open("a", encoding="utf-8") as fh:
            for payload in payloads:
                fh.write(json.dumps(payload, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def read(self) -> HoldSnapshot:
        """Live holds, plus whether anything was unreadable.

        **Damage is not "no hold".** The first version skipped unreadable
        rows and returned the rest, reasoning that refusing everything
        would open every window at once. That was backwards: skipping the
        row ALSO opens the window it described, and if the damaged row was
        the only hold on a credential, a truncated line silently admitted
        work against a shut one (Codex review). A safety mechanism has to
        fail in the shut direction, so damage is reported and the caller
        denies.

        Reading happens under the writer's lock: without it a reader can
        observe a half-written row and treat a hold that IS being placed
        as absent.
        """
        if not self.path.exists():
            # Never written to. Distinct from damaged: there is nothing to
            # fail closed about.
            return HoldSnapshot(holds=(), damaged=())

        with FileLock(lock_path_for(self.path), timeout_s=self._lock_timeout_s):
            text = self.path.read_text(encoding="utf-8")
        return self._parse(text)

    def _read_unlocked(self) -> HoldSnapshot:
        """Caller holds the lock. See `narrow_if_unclaimed`."""
        if not self.path.exists():
            return HoldSnapshot(holds=(), damaged=())
        return self._parse(self.path.read_text(encoding="utf-8"))

    @staticmethod
    def _parse(text: str) -> HoldSnapshot:
        holds: list[RateLimitHold] = []
        damaged: list[str] = []
        for number, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                if payload.get("row") == "narrow":
                    # SUSPEND and cover, indivisibly — not replace. The
                    # rows this narrows are kept, so a probe lease that
                    # expires unanswered hands the credential back to the
                    # hold it was testing instead of leaving it open
                    # (independent review). Ordering is decided in
                    # `HoldRegistry.reconcile`, by decision time.
                    _require_supersede_fields(payload)
                    holds.append(RateLimitHold.from_dict(payload["hold"]))
                    continue
                if payload.get("row") == "supersede":
                    credential = _require_supersede_fields(payload)
                    holds = [h for h in holds if h.credential != credential]
                    continue
                holds.append(RateLimitHold.from_dict(payload))
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
                damaged.append(f"line {number}: {type(exc).__name__}: {exc}")
        return HoldSnapshot(holds=tuple(holds), damaged=tuple(damaged))

    def records(self) -> list[RateLimitHold]:
        """Live holds only. Prefer `read()`, which also reports damage."""
        return list(self.read().holds)


@dataclass(frozen=True)
class ProbePolicy:
    """When one run goes first, and how long it has to answer.

    A probe is claimed BEFORE the estimated window elapses, not after.
    Once an estimated `reset_at` passes, the hold is gone from the live
    state and with it the evidence that the window was ever a guess —
    every queued resume is admitted at once, which is the stampede the
    probe mechanism exists to prevent. Reaching back `lead_s` is what
    makes the decision possible while there is still something to decide.
    """

    # How far before an estimated reset one run is let through.
    lead_s: float = 60.0
    # How long that run holds the credential. A probe is a LEASE, not a
    # window: the probing run can die, and a narrowing that outlived its
    # holder would pin the credential to a process that no longer exists.
    ttl_s: float = 120.0
    # An unknown window never expires by itself, so a probe is the only
    # way out of one. Waiting this long first keeps that from firing the
    # instant such a hold is placed.
    unknown_window_wait_s: float = UNKNOWN_WINDOW_FALLBACK_S

    def __post_init__(self) -> None:
        for name in ("lead_s", "ttl_s", "unknown_window_wait_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number, got {value!r}")
            if value <= 0:
                raise ValueError(f"{name} must be positive, got {value!r}")
        if self.ttl_s <= self.lead_s:
            # The probe SUSPENDS the window for the length of its lease.
            # A lease shorter than the lead hands the credential back
            # before the window it replaced would have ended — opening it
            # EARLIER than not probing at all, while the constructor
            # claims the feature is strictly less permissive (independent
            # review).
            raise ValueError(
                f"ttl_s ({self.ttl_s}) must exceed lead_s ({self.lead_s}): "
                "a probe lease shorter than the lead reopens the window early"
            )


@dataclass(frozen=True)
class ScheduleOutcome:
    """What the scheduler did with one submission."""

    task_id: str
    launched: bool
    reason_code: str
    execution: TaskExecutionOutcome | None = None
    hold: RateLimitHold | None = None

    @property
    def parked(self) -> bool:
        return not self.launched

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id, "launched": self.launched,
            "reason_code": self.reason_code,
            "hold": self.hold.to_dict() if self.hold else None,
        }


class TaskScheduler:
    """Launches tasks only when the credential's window is open."""

    def __init__(
        self,
        engine: TaskEngine,
        run_store: RunStore,
        holds: HoldStore,
        credential: str,
        scheduler_id: str = "scheduler-1",
        # WALL CLOCK, not monotonic. `reset_at` on a durable hold is an
        # epoch timestamp the provider supplied, and a monotonic reading
        # is neither comparable to it nor meaningful across the restart
        # these rows are written to survive: mixing them makes every
        # durable hold look permanently unexpired.
        clock: Callable[[], float] = time.time,
        stale_after_s: float = 120.0,
        probe_policy: ProbePolicy | None = None,
        # When present, `submit` chooses among these instead of using the
        # single `credential`. Rotation stays inside the primary's KIND
        # unless a kind is explicitly authorised (rules 25, 26, 13).
        credentials: CredentialPool | None = None,
        authorised_kinds: frozenset[CredentialKind] = frozenset(),
        base_environment: Mapping[str, str] | None = None,
        # Default ON. It is strictly LESS permissive than the behaviour it
        # replaces — today an estimated window elapsing admits everyone —
        # so deny-by-default argues for it, not against it.
        probe_when_due: bool = True,
    ) -> None:
        self.engine = engine
        self.run_store = run_store
        self.holds = holds
        self.credential = credential
        self.scheduler_id = scheduler_id
        self.clock = clock
        self.stale_after_s = stale_after_s
        self.probe_policy = probe_policy or ProbePolicy()
        self.credentials = credentials
        self.authorised_kinds = authorised_kinds
        # Captured once: a binding built from an environment that changed
        # underneath is not reproducible.
        self._base_environment = dict(
            base_environment if base_environment is not None else os.environ)
        self.probe_when_due = probe_when_due
        self.registry = HoldRegistry()

    # -- the hold plane ---------------------------------------------------

    def live_holds(self) -> list[RateLimitHold]:
        """Rebuild from durable rows. Idempotent by construction."""
        return self.registry.reconcile(self.holds.read().holds, self.clock())

    def admits(self, *, is_resume: bool = False, probe_run_id: str | None = None,
               credential: str | None = None) -> bool:
        """May work start on this credential right now?

        `probe_run_id` names the RUN being admitted, not the process
        asking. Passing the scheduler's own id meant a PROBE hold admitted
        any submission from any scheduler sharing that id — the stampede a
        probe exists to prevent, hidden by a test whose scheduler id and
        probe id happened to be the same string (Codex review).
        """
        snapshot = self.holds.read()
        if snapshot.damaged:
            # Unreadable rows are not "no holds". Deny until an operator
            # looks: a safety mechanism fails in the shut direction.
            return False
        self.registry.reconcile(snapshot.holds, self.clock())
        return self.registry.admits(
            credential or self.credential, self.clock(), is_resume=is_resume,
            runner_id=probe_run_id,
        )

    def submit(self, *, is_resume: bool = False, probe_run_id: str | None = None,
               **task_kwargs: Any) -> ScheduleOutcome:
        """Run one task, unless the credential is held.

        A refusal here is a PARK, not a failure: the work is untouched and
        resumable, and rule 7 forbids charging the agent for a window
        somebody else's traffic closed.
        """
        task_id = str(task_kwargs.get("task_id", "<unknown>"))
        rotation: Rotation | None = None
        credential_id: str | None = None
        if self.credentials is not None:
            rotation = self.credentials.select(
                lambda cid: self.admits(is_resume=is_resume,
                                        probe_run_id=probe_run_id, credential=cid),
                authorised_kinds=self.authorised_kinds,
            )
            if rotation is not None:
                credential_id = rotation.credential.credential_id
            else:
                # Every credential held, or behind a boundary nobody
                # authorised. Both are parks, and the second one is a
                # refusal to spend rather than an absence of capacity.
                return ScheduleOutcome(
                    task_id=task_id, launched=False, reason_code=PARK_REASON,
                    hold=self.registry.hold_for(self.credentials.primary.credential_id),
                )
        if not self.admits(is_resume=is_resume, probe_run_id=probe_run_id,
                           credential=credential_id):
            # THE AUTOMATIC CALLER. `probe()` existed and nothing invoked
            # it, so the kernel's own guessed windows still ended in a
            # stampede — a mechanism nothing calls is a parallel fiction.
            # This is the moment it is needed: a submission is being
            # parked on a hold the kernel ESTIMATED, and rather than every
            # queued run being released together when that guess elapses,
            # one goes first and the rest keep waiting.
            #
            # The holder is the TASK being admitted, not the scheduler:
            # a shared identity was the original defect, and this one is
            # unique to the unit of work asking.
            if self.probe_when_due and probe_run_id is None:
                claimed = self.claim_probe(task_id, credential=credential_id)
                if claimed is not None:
                    probe_run_id = claimed.probe_holder
            if not self.admits(is_resume=is_resume, probe_run_id=probe_run_id,
                               credential=credential_id):
                held = self.registry.hold_for(credential_id or self.credential)
                return ScheduleOutcome(
                    task_id=task_id, launched=False, reason_code=PARK_REASON,
                    hold=held,
                )

        # Re-check immediately before the launch. Another scheduler can
        # place a hold between the decision and the child, and this shrinks
        # that window from "however long setup takes" to microseconds — the
        # same pattern the engine's ownership guard uses. It does NOT close
        # the window: a check-then-act without a reservation cannot, and
        # the ADR says so rather than implying otherwise.
        if not self.admits(is_resume=is_resume, probe_run_id=probe_run_id,
                           credential=credential_id):
            return ScheduleOutcome(
                task_id=task_id, launched=False, reason_code=PARK_REASON,
                hold=self.registry.hold_for(credential_id or self.credential),
            )

        if rotation is not None and self.credentials is not None:
            # THE BINDING, at the engine's launch too. Choosing a
            # credential and then running with the ambient environment
            # would rotate the DECISION and not the launch — the audit
            # trail would record an identity the child never used.
            task_kwargs["launch_env"] = self.credentials.launch_environment(
                rotation.credential, self._base_environment)
        outcome = self.engine.execute_task(**task_kwargs)
        hold = self.observe(outcome.classification, probe_run_id=probe_run_id,
                            credential=credential_id)
        return ScheduleOutcome(
            task_id=task_id, launched=True,
            reason_code=(outcome.classification.reason_code
                         if outcome.classification else "no_classification"),
            execution=outcome, hold=hold,
        )

    def observe(self, classification: FailureClassification | None,
                probe_run_id: str | None = None,
                credential: str | None = None) -> RateLimitHold | None:
        """Record what one launch's classification implies for the window.

        Public because the implementation is not the only thing that
        launches an agent: a convergence round's reviewer and fixer hit
        the same credential, and a rate limit there used to be invisible
        to the hold plane — it surfaced as unreadable agent output, no
        hold was placed, and the next round launched straight into the
        same shut window. Rule 6 says that is a park, not agent output.
        """
        if classification is None or classification.failure is not FailureClass.RATE_LIMITED:
            # Every other failure is about the work, not the window.
            # Holding a credential because a test failed would take the
            # whole system down for a bug.
            #
            # A CLEAN launch is the answer the probe was asking for, and
            # nothing used to read it: the narrowing stood until its own
            # deadline while the window was demonstrably open, so a
            # successful probe kept every other run parked.
            #
            # "Not rate-limited" is NOT that answer. A timeout, a crash or
            # an unparseable result is an ABSENCE of an answer, and
            # reading absence as "the window is open" reopens a credential
            # on no evidence — a safety mechanism has to fail in the shut
            # direction (independent review). The probe simply stays
            # claimed until its lease runs out, and the suspended hold
            # governs again after it.
            if classification is not None and classification.failure is FailureClass.PASS:
                self._resolve_probe(probe_run_id, credential)
            return None
        target = credential or self.credential
        hold = hold_from_classification(
            classification, target, self.clock(), scope=HoldScope.ACCOUNT,
        )
        if hold is None:
            return None
        if probe_run_id is not None:
            # The probe ANSWERED, and the answer is "still shut". A live
            # PROBE row outranks an ACCOUNT row, so leaving it standing
            # would keep admitting the very run that just hit the limit
            # until its lease ran out. Ending it is what makes the new
            # observation govern.
            self._end_probe(probe_run_id, target, reason="probe_rate_limited")
        return self.holds.place(hold)

    def _end_probe(self, probe_run_id: str, credential: str, reason: str) -> None:
        """Retire this run's probe row, if it is still the live one."""
        self.live_holds()
        live = self.registry.hold_for(credential)
        if (live is not None and live.scope is HoldScope.PROBE
                and live.probe_holder == probe_run_id):
            self.holds.supersede(credential, self.clock(),
                                 reason=f"{reason}:{probe_run_id}")

    def _resolve_probe(self, probe_run_id: str | None,
                       credential: str | None = None) -> None:
        """A probe that came back clean reopens the credential."""
        if probe_run_id is None:
            return
        target = credential or self.credential
        self.live_holds()
        hold = self.registry.hold_for(target)
        if (hold is None or hold.scope is not HoldScope.PROBE
                or hold.probe_holder != probe_run_id):
            # Not this run's probe to end — including the case where a
            # later hold already superseded it.
            return
        self.holds.supersede(target, self.clock(),
                             reason=f"probe_succeeded:{probe_run_id}")
        self.live_holds()

    def probe(self, run_id: str, ttl_s: float | None = None,
              credential: str | None = None) -> RateLimitHold:
        """Narrow an ACCOUNT hold to a single probing run.

        The named run is the ONLY one admitted while this stands. An
        unattributed probe would admit every queued resume at once, which
        is the stampede a probe exists to prevent (ADR-0012).

        The replacement gets its OWN deadline and never inherits the
        window it replaces. Inheriting was wrong in both directions: a
        `reset_at` already in the past made the probe hold expire the
        instant it was written — admitting everyone, the exact stampede —
        and a `None` made it a hold that never expires, pinning the
        credential to a run that may already be dead. A probe is a lease
        on the credential, and a lease that cannot expire is not one.
        """
        target = credential or self.credential
        self.live_holds()
        current = self.registry.hold_for(target)
        reason = current.reason_code if current else "rate_limited:probe"
        reset_at = self.clock() + (
            ttl_s if ttl_s is not None else self.probe_policy.ttl_s)
        # Narrowing is a DECISION, not an observation: without drawing the
        # line first, the broader ACCOUNT hold simply outranks this row and
        # the probe never takes effect. Both rows go down in ONE append, so
        # a crash between them cannot leave the credential wide open.
        return self.holds.narrow(
            target, self.clock(), reason=f"probe:{run_id}",
            replacement=RateLimitHold(
                credential=target, scope=HoldScope.PROBE,
                reason_code=reason, reset_at=reset_at, placed_at=self.clock(),
                probe_holder=run_id,
                # Estimated by construction: this deadline is the kernel's
                # lease on one run, never a window a provider supplied.
                window_estimated=True,
            ),
        )

    def probe_is_due(self, credential: str | None = None) -> RateLimitHold | None:
        """The hold one run should now be let through to test, if any.

        Due when the kernel is about to act on its OWN guess: an estimated
        window within `lead_s` of elapsing, or an unknown window that has
        stood for `unknown_window_wait_s`. A window the PROVIDER supplied
        is never probed — it is not a guess, and spending a launch to
        contradict it buys nothing. A live PROBE hold is never re-probed:
        somebody is already answering the question.
        """
        self.live_holds()
        hold = self.registry.hold_for(credential or self.credential)
        if hold is None or hold.scope is not HoldScope.ACCOUNT:
            return None
        return hold if self._is_probeable(hold, self.clock()) else None

    def _is_probeable(self, hold: RateLimitHold, now: float) -> bool:
        """Is this hold one of the kernel's own guesses, and due?"""
        if not hold.window_estimated and hold.reset_at is not None:
            return False
        if hold.reset_at is None:
            # A hold that never expires needs a probe or it is an outage.
            due_at = hold.placed_at + self.probe_policy.unknown_window_wait_s
        else:
            due_at = hold.reset_at - self.probe_policy.lead_s
        return now >= due_at

    def claim_probe(self, run_id: str,
                    credential: str | None = None) -> RateLimitHold | None:
        """Take the probe for `run_id`, or None if it is not ours to take.

        Exactly one winner, because the read and the append happen under
        one lock. A check-then-append was not enough: two schedulers
        finding the probe due at the same instant both narrowed, the later
        row won the rebuild, and the loser could already have passed its
        own admission check and launched — two runs testing a window that
        may still be shut.
        """
        target = credential or self.credential
        current = self.probe_is_due(target)
        if current is None:
            return None
        now = self.clock()
        # The holder is the caller's name PLUS a secret minted here. A
        # holder of `TASK-7`, or of `TASK-7:review:1`, is a string any
        # process holding the task id can assert — and since `admits`
        # matches on it alone, asserting it IS the admission. "A claim any
        # caller could make was the original defect; an exact identity is
        # not that" was only true while the identity was unguessable, and
        # it never was (independent review). The name keeps attribution;
        # the token makes winning the claim the only way to have it.
        holder = f"{run_id}:{secrets.token_hex(8)}"
        return self.holds.narrow_if_unclaimed(
            target, now, reason=f"probe:{run_id}",
            replacement=RateLimitHold(
                credential=target, scope=HoldScope.PROBE,
                reason_code=current.reason_code, placed_at=now,
                reset_at=now + self.probe_policy.ttl_s, probe_holder=holder,
                window_estimated=True,
            ),
            still_due=lambda live: (
                live is not None and live.scope is HoldScope.ACCOUNT
                and self._is_probeable(live, now)
            ),
        )

    # -- recovery ---------------------------------------------------------

    def boot(self, classify: Callable[[str], FailureClassification | None] | None = None,
             ) -> list[SweepOutcome]:
        """Give every stranded run a disposition, then act on it.

        The sweep itself is pure (ADR-0012); this is the half that writes.
        A run the sweep failed is marked FAILED durably, because a record
        that is neither progressing nor terminal is the ghost the whole
        mechanism exists to prevent. A run it re-adopted is left in place
        for the normal path to pick up — the sweep decides nothing
        special.
        """
        outcomes = boot_sweep(self._stranded(classify), stale_after_s=self.stale_after_s)
        for outcome in outcomes:
            if outcome.disposition is Disposition.FAILED:
                try:
                    self.run_store.update_state(outcome.run.run_id, RunState.CRASHED)
                except (FileNotFoundError, ValueError):
                    # A run that vanished or refuses the transition is not
                    # a reason to abandon the rest of the sweep: the point
                    # is that EVERY run gets a disposition.
                    continue
        return outcomes

    def _stranded(self, classify: Callable[[str], FailureClassification | None] | None,
                  ) -> list[StrandedRun]:
        runs: list[StrandedRun] = []
        for run_id in self.run_store.list_run_ids():
            try:
                meta = self.run_store.read_meta(run_id)
            except (FileNotFoundError, ValueError):
                continue
            alive, stale_s = self._liveness(run_id)
            runs.append(StrandedRun(
                run_id=run_id, task_id=meta.task_id, state=meta.state,
                process_alive=alive, heartbeat_stale_s=stale_s,
                classification=classify(run_id) if classify else None,
            ))
        return runs

    def _liveness(self, run_id: str) -> tuple[bool | None, float | None]:
        """Is the process that owned this run still there, and how stale?

        `None` for alive means "unknown", which the sweep treats as not
        demonstrably alive. Claiming a dead process is alive would strand
        the run forever; the opposite merely re-adopts work.
        """
        try:
            beat = self.run_store.read_heartbeat(run_id)
        except Exception:  # noqa: BLE001 - one bad file must not end the sweep
            # `read_heartbeat` json.loads an arbitrary file. A single
            # truncated heartbeat aborted the ENTIRE boot sweep, leaving
            # every later run with no disposition — the ghost the sweep
            # exists to prevent, caused by the sweep (Codex review).
            return None, None
        if not isinstance(beat, dict) or not beat:
            return None, None
        alive: bool | None = None
        if beat.get("start_time") is None:
            # `is_alive` answers "a process with this PID exists", which on
            # a recycled PID is a different process wearing a dead run's
            # identity. Without a start time there is nothing to tell them
            # apart, so the honest answer is "unknown" — which the sweep
            # treats as not demonstrably alive and re-adopts, rather than
            # stranding the run forever on a coincidence.
            alive = None
        else:
            try:
                alive = is_alive(ProcessFingerprint.from_dict(beat))
            except (TypeError, ValueError, KeyError):
                alive = None
        stale_s: float | None = None
        recorded = beat.get("ts")
        if isinstance(recorded, str):
            try:
                written = datetime.fromisoformat(recorded)
            except ValueError:
                written = None
            if written is not None:
                if written.tzinfo is None:
                    written = written.replace(tzinfo=UTC)
                age = (datetime.now(UTC) - written).total_seconds()
                # A heartbeat from the FUTURE is clock skew or a bad
                # record, not freshness. Clamping it to zero made a dead
                # run look like it had just checked in and stranded it;
                # reporting it as unknown lets the sweep re-adopt, which
                # only costs re-running work (Codex review).
                stale_s = age if age >= 0 else None
        return alive, stale_s


def holds_summary(holds: Iterable[RateLimitHold]) -> Sequence[dict[str, Any]]:
    """Operator-facing view: what is shut, until when, and how sure we are."""
    return [
        {
            **hold.to_dict(),
            # Surfaced explicitly: an estimated window is the kernel's
            # bounded guess, not something the provider said, and an
            # operator deciding whether to wait needs to know which.
            "window_source": "estimated" if hold.window_estimated else "provider",
        }
        for hold in sorted(holds, key=lambda h: (h.credential, h.scope.value))
    ]
