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
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..runner.liveness import ProcessFingerprint, is_alive
from .engine import TaskEngine, TaskExecutionOutcome
from .failures import (
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
        with (
            FileLock(lock_path_for(self.path), timeout_s=self._lock_timeout_s),
            self.path.open("a", encoding="utf-8") as fh,
        ):
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

        holds: list[RateLimitHold] = []
        damaged: list[str] = []
        for number, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                if payload.get("row") == "narrow":
                    # Supersede and replace, indivisibly.
                    credential = _require_supersede_fields(payload)
                    holds = [h for h in holds if h.credential != credential]
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
    ) -> None:
        self.engine = engine
        self.run_store = run_store
        self.holds = holds
        self.credential = credential
        self.scheduler_id = scheduler_id
        self.clock = clock
        self.stale_after_s = stale_after_s
        self.registry = HoldRegistry()

    # -- the hold plane ---------------------------------------------------

    def live_holds(self) -> list[RateLimitHold]:
        """Rebuild from durable rows. Idempotent by construction."""
        return self.registry.reconcile(self.holds.read().holds, self.clock())

    def admits(self, *, is_resume: bool = False, probe_run_id: str | None = None) -> bool:
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
            self.credential, self.clock(), is_resume=is_resume,
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
        if not self.admits(is_resume=is_resume, probe_run_id=probe_run_id):
            held = self.registry.hold_for(self.credential)
            return ScheduleOutcome(
                task_id=task_id, launched=False, reason_code=PARK_REASON, hold=held,
            )

        # Re-check immediately before the launch. Another scheduler can
        # place a hold between the decision and the child, and this shrinks
        # that window from "however long setup takes" to microseconds — the
        # same pattern the engine's ownership guard uses. It does NOT close
        # the window: a check-then-act without a reservation cannot, and
        # the ADR says so rather than implying otherwise.
        if not self.admits(is_resume=is_resume, probe_run_id=probe_run_id):
            return ScheduleOutcome(
                task_id=task_id, launched=False, reason_code=PARK_REASON,
                hold=self.registry.hold_for(self.credential),
            )

        outcome = self.engine.execute_task(**task_kwargs)
        hold = self._maybe_place_hold(outcome)
        return ScheduleOutcome(
            task_id=task_id, launched=True,
            reason_code=(outcome.classification.reason_code
                         if outcome.classification else "no_classification"),
            execution=outcome, hold=hold,
        )

    def _maybe_place_hold(self, outcome: TaskExecutionOutcome) -> RateLimitHold | None:
        """Turn a parked run into a durable, credential-scoped hold.

        Only a RATE_LIMITED classification places one. Every other failure
        is about the work, not the window, and holding a credential
        because a test failed would take the whole system down for a bug.
        """
        classification = outcome.classification
        if classification is None or classification.failure is not FailureClass.RATE_LIMITED:
            return None
        hold = hold_from_classification(
            classification, self.credential, self.clock(), scope=HoldScope.ACCOUNT,
        )
        if hold is None:
            return None
        return self.holds.place(hold)

    def probe(self, run_id: str) -> RateLimitHold:
        """Narrow an ACCOUNT hold to a single probing run.

        The named run is the ONLY one admitted while this stands. An
        unattributed probe would admit every queued resume at once, which
        is the stampede a probe exists to prevent (ADR-0012).
        """
        self.live_holds()
        current = self.registry.hold_for(self.credential)
        reason = current.reason_code if current else "rate_limited:probe"
        reset_at = current.reset_at if current else None
        # Narrowing is a DECISION, not an observation: without drawing the
        # line first, the broader ACCOUNT hold simply outranks this row and
        # the probe never takes effect. Both rows go down in ONE append, so
        # a crash between them cannot leave the credential wide open.
        return self.holds.narrow(
            self.credential, self.clock(), reason=f"probe:{run_id}",
            replacement=RateLimitHold(
                credential=self.credential, scope=HoldScope.PROBE,
                reason_code=reason, reset_at=reset_at, placed_at=self.clock(),
                probe_holder=run_id,
                window_estimated=current.window_estimated if current else False,
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
