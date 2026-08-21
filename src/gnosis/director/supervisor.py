"""A worker loop that paces itself and knows what it may not decide.

ADR-0019 left `drain`: a generator a caller iterates, with no worker
process, no restart, no health, and a released brief re-offered
instantly. The queue's `max_attempts` stops that loop; nothing paced it.

The design question worth answering here is not "how do I retry" — it is
**what may a supervisor decide on its own?** The constitution says
irreversible acts are prepared, not executed, without higher authority,
and re-running a brief is not free: it launches agents, spends a budget,
and may repeat side effects whose outcome nobody recorded.

So the line is drawn explicitly:

**A supervisor MAY** pace a retry, stop when the queue is empty, stop on
its own circuit breakers, and take an exhausted brief out of
circulation. All of those either do nothing or do less.

**A supervisor MAY NOT** clear an attempt count, resurrect a blocked
brief, or re-run work a worker recorded as having an unknown outcome.
Those are `WorkQueue.requeue`, which exists for an operator to call.
A bound an automated path could clear is not a bound.

The honest edge of that line: **recovery does re-offer work whose owner
died**, and it cannot know whether the handler ran. What it can now tell
is whether a decision was RECORDED — a park, a block, a completion is
stamped on the record before the claims-plane call, so recovery finishes
what the dead worker decided instead of overruling it. Where no decision
was recorded, the brief is re-offered and `attempts` is the bound: the
claim increments it, so a crash loop ends in `blocked/` rather than
running forever. Saying "a supervisor never re-runs unknown work" would
be false, and a false claim is worse than the gap it hides.

**Backoff is durable**, written to the brief's own record as
`not_before`. Backoff held in a worker's memory is backoff a restart
forgets, and what it paces — launches against a shut window — is
exactly what must not resume at full speed after a crash. That is
L-0024's shape, and it applies to pacing as much as to budgets.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .work_queue import ClaimedWork, WorkQueue


class Disposition(str, Enum):
    """What the handler decided about one brief."""

    COMPLETED = "COMPLETED"    # finished, whatever the outcome was
    PARK = "PARK"              # try again later; not a failure
    BLOCK = "BLOCK"            # a human must look at this


class StopReason(str, Enum):
    QUEUE_EMPTY = "QUEUE_EMPTY"
    MAX_BRIEFS = "MAX_BRIEFS"
    WALL_CLOCK = "WALL_CLOCK"
    CONSECUTIVE_PARKS = "CONSECUTIVE_PARKS"
    HANDLER_RAISED = "HANDLER_RAISED"
    INVALID_OUTPUT = "INVALID_OUTPUT"


@dataclass(frozen=True)
class BackoffPolicy:
    """How long a parked brief waits before it is offered again.

    Exponential in the brief's own attempt count, which is durable on its
    record — so the pacing survives the restart that a memory-held
    counter would reset.
    """

    base_s: float = 5.0
    factor: float = 2.0
    max_s: float = 300.0

    def __post_init__(self) -> None:
        for name in ("base_s", "factor", "max_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number, got {value!r}")
            if value <= 0:
                raise ValueError(f"{name} must be positive, got {value!r}")
        if self.factor < 1:
            # A shrinking backoff paces nothing and would read as pacing.
            raise ValueError("factor must be >= 1")

    def delay_for(self, attempts: int) -> float:
        exponent = max(0, attempts - 1)
        return min(self.max_s, self.base_s * (self.factor ** exponent))


@dataclass(frozen=True)
class SupervisorPolicy:
    """Circuit breakers, per rule 8. Every one of them is finite."""

    max_briefs: int | None = None
    # Checked between briefs. It bounds how long the LOOP runs, not how
    # long one handler takes — nothing here can interrupt a call in
    # progress, and pretending otherwise would be the false claim.
    wall_clock_s: float | None = None
    # Consecutive parks with nothing completing in between. A queue where
    # every brief parks is a system waiting on something external, and a
    # worker spinning through it learns nothing new each pass.
    max_consecutive_parks: int = 5

    def __post_init__(self) -> None:
        if self.max_consecutive_parks < 1:
            raise ValueError("max_consecutive_parks must be >= 1")


@dataclass(frozen=True)
class SupervisionReport:
    worker_id: str
    stopped_because: StopReason
    completed: tuple[str, ...] = field(default_factory=tuple)
    parked: tuple[str, ...] = field(default_factory=tuple)
    blocked: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def handled(self) -> int:
        return len(self.completed) + len(self.parked) + len(self.blocked)

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "stopped_because": self.stopped_because.value,
            "completed": list(self.completed), "parked": list(self.parked),
            "blocked": list(self.blocked),
            "errors": [list(pair) for pair in self.errors],
        }


class WorkerSupervisor:
    """Claims, runs, and paces — and escalates rather than deciding."""

    def __init__(
        self,
        queue: WorkQueue,
        backoff: BackoffPolicy | None = None,
        policy: SupervisorPolicy | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.queue = queue
        self.backoff = backoff or BackoffPolicy()
        self.policy = policy or SupervisorPolicy()
        self.clock = clock

    def run(self, worker_id: str,
            handler: Callable[[ClaimedWork], Disposition]) -> SupervisionReport:
        """Work until a stop condition. Every exit names its reason.

        Recovery runs first: a previous worker's stranded record comes
        back before this one starts claiming, which is where ADR-0016's
        boot sweep runs for the same reason.
        """
        self.queue.recover()
        started = self.clock()
        completed: list[str] = []
        parked: list[str] = []
        blocked: list[str] = []
        errors: list[tuple[str, str]] = []
        consecutive_parks = 0

        while True:
            if self.policy.max_briefs is not None and \
                    len(completed) + len(parked) + len(blocked) >= self.policy.max_briefs:
                return self._report(worker_id, StopReason.MAX_BRIEFS,
                                    completed, parked, blocked, errors)
            if self.policy.wall_clock_s is not None and \
                    self.clock() - started >= self.policy.wall_clock_s:
                return self._report(worker_id, StopReason.WALL_CLOCK,
                                    completed, parked, blocked, errors)
            if consecutive_parks >= self.policy.max_consecutive_parks:
                # Nothing is completing. Continuing would re-learn the
                # same answer at whatever rate the backoff allows.
                return self._report(worker_id, StopReason.CONSECUTIVE_PARKS,
                                    completed, parked, blocked, errors)

            work = self.queue.claim(worker_id)
            if work is None:
                return self._report(worker_id, StopReason.QUEUE_EMPTY,
                                    completed, parked, blocked, errors)

            try:
                # `object`, not `Disposition`: the annotation is a promise
                # the runtime cannot enforce, and this loop is the place
                # that finds out. Typing it honestly is also what keeps
                # the check below from reading as dead code.
                returned: object = handler(work)
            except Exception as exc:  # noqa: BLE001 - see below
                # The brief is CLAIMED. A handler that raises must not
                # leave it owned by a worker that has stopped — that is
                # the stranding ADR-0019's review found, arriving through
                # a different door. It is blocked, not retried: the
                # outcome is unknown, and re-running work a worker
                # recorded as unknown is not this supervisor's decision.
                self.queue.block(work, reason=f"handler_raised:{type(exc).__name__}")
                blocked.append(work.brief_id)
                errors.append((work.brief_id, f"{type(exc).__name__}: {exc}"))
                return self._report(worker_id, StopReason.HANDLER_RAISED,
                                    completed, parked, blocked, errors)

            if not isinstance(returned, Disposition):
                # Rule 8 asks for an invalid-output limit. Falling through
                # to the park branch would turn a handler bug — a bare
                # `return`, the commonest one — into an indefinite pacing
                # loop that looks like a system waiting on a window. The
                # outcome is as unknown as a raise, and treated the same.
                self.queue.block(
                    work, reason=f"invalid_disposition:{type(returned).__name__}")
                blocked.append(work.brief_id)
                errors.append((work.brief_id,
                               f"handler returned {returned!r}, not a Disposition"))
                return self._report(worker_id, StopReason.INVALID_OUTPUT,
                                    completed, parked, blocked, errors)

            disposition = returned
            if disposition is Disposition.COMPLETED:
                self.queue.complete(work, outcome="COMPLETED")
                completed.append(work.brief_id)
                consecutive_parks = 0
            elif disposition is Disposition.BLOCK:
                self.queue.block(work, reason="handler_requested_block")
                blocked.append(work.brief_id)
                consecutive_parks = 0
            else:
                delay = self.backoff.delay_for(work.attempts)
                self.queue.release(work, reason="parked",
                                   not_before=self.clock() + delay)
                parked.append(work.brief_id)
                consecutive_parks += 1

    @staticmethod
    def _report(worker_id: str, reason: StopReason, completed: list[str],
                parked: list[str], blocked: list[str],
                errors: list[tuple[str, str]]) -> SupervisionReport:
        return SupervisionReport(
            worker_id=worker_id, stopped_because=reason,
            completed=tuple(completed), parked=tuple(parked),
            blocked=tuple(blocked), errors=tuple(errors),
        )
