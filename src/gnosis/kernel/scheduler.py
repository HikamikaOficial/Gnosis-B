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
        self._append({"row": "hold", **hold.to_dict()})
        return hold

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
        self._append({"row": "supersede", "credential": credential,
                      "at": at, "reason": reason})

    def _append(self, payload: dict[str, Any]) -> None:
        with (
            FileLock(lock_path_for(self.path), timeout_s=self._lock_timeout_s),
            self.path.open("a", encoding="utf-8") as fh,
        ):
            fh.write(json.dumps(payload, sort_keys=True) + "\n")

    def records(self) -> list[RateLimitHold]:
        """Live hold rows: everything after the last supersede per credential.

        A row half-written by a killed process is skipped rather than
        raising: the rest of the file is still true, and refusing to read
        any holds because of one bad line would open every window at
        once — the failure mode with the worst blast radius here.
        """
        if not self.path.exists():
            return []
        holds: list[RateLimitHold] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                if payload.get("row") == "supersede":
                    credential = payload["credential"]
                    holds = [h for h in holds if h.credential != credential]
                    continue
                holds.append(RateLimitHold.from_dict(payload))
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                continue
        return holds


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
        return self.registry.reconcile(self.holds.records(), self.clock())

    def admits(self, *, is_resume: bool = False) -> bool:
        self.live_holds()
        return self.registry.admits(
            self.credential, self.clock(), is_resume=is_resume,
            runner_id=self.scheduler_id,
        )

    def submit(self, *, is_resume: bool = False, **task_kwargs: Any) -> ScheduleOutcome:
        """Run one task, unless the credential is held.

        A refusal here is a PARK, not a failure: the work is untouched and
        resumable, and rule 7 forbids charging the agent for a window
        somebody else's traffic closed.
        """
        task_id = str(task_kwargs.get("task_id", "<unknown>"))
        if not self.admits(is_resume=is_resume):
            held = self.registry.hold_for(self.credential)
            return ScheduleOutcome(
                task_id=task_id, launched=False, reason_code=PARK_REASON, hold=held,
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
        # line first, the broader ACCOUNT hold simply outranks this row
        # and the probe never takes effect.
        self.holds.supersede(
            self.credential, self.clock(), reason=f"probe:{run_id}")
        return self.holds.place(RateLimitHold(
            credential=self.credential, scope=HoldScope.PROBE, reason_code=reason,
            reset_at=reset_at, placed_at=self.clock(), probe_holder=run_id,
            window_estimated=current.window_estimated if current else False,
        ))

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
        beat = self.run_store.read_heartbeat(run_id)
        if not beat:
            return None, None
        alive: bool | None = None
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
                stale_s = max(0.0, (datetime.now(UTC) - written).total_seconds())
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
