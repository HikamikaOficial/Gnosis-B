"""Deciding which converged task lands first, and what that costs the rest.

ADR-0018 made landing safe: nothing reaches the shared branch that did
not pass verification on the MERGED tree. It made it safe *after the
fact* — the second of two conflicting tasks spends an entire convergence
loop, several agent launches, and only then discovers its work cannot
land. Ordering is about spending less of that, and about one thing
ADR-0018 does not address at all.

**The thing it does not address.** "Converged" means two pieces of
evidence: deterministic verification passed AND an independent review
passed. When the target branch moves, integration re-runs the
verification (on the merged tree) and re-runs *nothing* of the review.
But a review is evidence about a specific tree — the reviewer judged
that this change was correct in the tree it was shown. Once the base
moves, that judgement is about a tree which no longer exists, and
nothing said so. Half the convergence guarantee was silently
re-established and half was silently assumed.

So this module's real output is not "an order". It is an order plus, for
each task, **whether its review is still evidence about the tree it will
land on**.

**What path overlap can and cannot do.** Overlapping paths mean two
tasks EDITED THE SAME FILE. That is all it means. It is not a
probability of conflict — git merges by hunk, and two edits to one file
routinely combine cleanly — and it says nothing whatever about semantic
conflicts: the headline test of ADR-0018 is a semantic break between
tasks with DISJOINT paths, a rename on one side and a new caller of the
old name on the other. No ordering built on path names can catch that.
Post-merge verification remains the only thing that decides, and
claiming more here would be the same overreach this project has
corrected in eight consecutive units.

Planning is a pure function over declared facts, like `PolicyEngine`:
same inputs, same plan, recomputable later from recorded evidence.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LandingReason(str, Enum):
    """Why a task is where it is in the plan."""

    FRESH_BASE = "FRESH_BASE"          # forked from the current target head
    STALE_BASE = "STALE_BASE"          # the target moved after it forked
    BASE_MOVED_BY_PLAN = "BASE_MOVED_BY_PLAN"  # an earlier landing moves it
    PATH_OVERLAP = "PATH_OVERLAP"      # shares files with an earlier landing


@dataclass(frozen=True)
class ReadyTask:
    """A converged, un-landed task, described by facts a planner can use."""

    task_id: str
    base_sha: str
    changed_paths: tuple[str, ...]
    # When convergence finished. Ordering is FIFO among equals, because a
    # queue that reorders on a quality signal starves whatever the signal
    # dislikes, and nothing here has earned the right to do that.
    converged_at: float = 0.0

    def __post_init__(self) -> None:
        # NaN compares neither less nor greater, so a stable sort would
        # let INPUT ORDER decide the plan — and the docstring promises two
        # planners agree (independent review). A plan that depends on the
        # order it was handed its tasks is not recomputable evidence.
        value = self.converged_at
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"converged_at must be a number, got {value!r}")
        if not math.isfinite(float(value)):
            raise ValueError(f"converged_at must be finite, got {value!r}")
        if not self.task_id:
            raise ValueError("a ready task must have an id")

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "base_sha": self.base_sha,
                "changed_paths": list(self.changed_paths),
                "converged_at": self.converged_at}


@dataclass(frozen=True)
class PlannedLanding:
    task: ReadyTask
    position: int
    reason: LandingReason
    # THE load-bearing field. False means: by the time this lands, the
    # tree it will land on is not the tree its reviewer judged, so the
    # review half of "converged" no longer holds. Verification is re-run
    # by the integrator; the review is not, and pretending otherwise
    # would keep half a guarantee while reporting a whole one.
    review_still_applies: bool
    # Every reason that applies. `reason` is the headline; a task can be
    # both stale-based and path-overlapping, and reporting one hid the
    # other.
    reasons: tuple[LandingReason, ...] = ()
    overlaps_with: tuple[str, ...] = ()
    shared_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task.task_id, "position": self.position,
            "reason": self.reason.value,
            "reasons": [r.value for r in self.reasons],
            "review_still_applies": self.review_still_applies,
            "overlaps_with": list(self.overlaps_with),
            "shared_paths": list(self.shared_paths),
        }


@dataclass(frozen=True)
class LandingPlan:
    head: str
    landings: tuple[PlannedLanding, ...] = field(default_factory=tuple)

    @property
    def first(self) -> PlannedLanding | None:
        return self.landings[0] if self.landings else None

    def needing_rereview(self) -> tuple[PlannedLanding, ...]:
        return tuple(p for p in self.landings if not p.review_still_applies)

    def to_dict(self) -> dict[str, Any]:
        return {"head": self.head,
                "landings": [p.to_dict() for p in self.landings]}


def plan_landings(head: str, tasks: list[ReadyTask]) -> LandingPlan:
    """Order converged tasks for landing, and say what each order costs.

    Pure. The rules, in the order they apply:

    1. **Fresh bases first.** A task forked from the current head lands
       without anyone's base moving, and its review is still evidence
       about the tree it lands on. Anything else is already working from
       a tree that has changed.
    2. **FIFO among equals**, ties broken by task id so the plan is
       deterministic and two planners agree. Ordering by "smallest diff"
       or "fewest conflicts" would starve large or unlucky tasks, and
       nothing here has evidence that would justify that.
    3. **Only the first landing keeps its review.** Every later one lands
       on a tree the first one moved, so its reviewer judged something
       else. This is the honest answer and it is deliberately
       inconvenient: it says a batch of converged tasks is not a batch of
       landable tasks.
    4. **Path overlap is reported, not used to reorder.** It records that
       two tasks edited the same file — not that they conflict, which
       only the merge decides, and not anything about semantic breakage.
       It is a signal for a human reading the plan, not an input to it.
    """
    # One entry per task. A duplicate id planned as two entries reported
    # a task overlapping ITSELF and could integrate it twice in one pass
    # (independent review); the first occurrence wins so the plan stays a
    # function of the set of tasks, not of how many times each was named.
    unique: dict[str, ReadyTask] = {}
    for task in tasks:
        unique.setdefault(task.task_id, task)

    ordered = sorted(unique.values(), key=lambda t: (t.base_sha != head,
                                                     t.converged_at, t.task_id))

    landings: list[PlannedLanding] = []
    claimed: dict[str, str] = {}   # path -> task that will land it first
    for position, task in enumerate(ordered):
        shared = sorted({p for p in task.changed_paths if p in claimed})
        overlaps = sorted({claimed[p] for p in shared})

        # ALL the reasons that apply, not just the highest-precedence
        # one. A task can be both path-overlapping and stale-based, and
        # showing only PATH_OVERLAP let an operator read a merge-risk
        # signal where there was also a review-evidence failure
        # (independent review). `reason` stays as the headline for
        # existing callers; `reasons` is the account.
        reasons: list[LandingReason] = []
        if shared:
            reasons.append(LandingReason.PATH_OVERLAP)
        if task.base_sha != head:
            reasons.append(LandingReason.STALE_BASE)
        if position > 0:
            reasons.append(LandingReason.BASE_MOVED_BY_PLAN)
        if not reasons:
            reasons.append(LandingReason.FRESH_BASE)
        reason = reasons[0]

        landings.append(PlannedLanding(
            task=task, position=position, reason=reason,
            # Only a task that forked from the CURRENT head and lands
            # FIRST is judged against the tree it lands on.
            review_still_applies=(position == 0 and task.base_sha == head),
            reasons=tuple(reasons),
            overlaps_with=tuple(overlaps),
            shared_paths=tuple(shared),
        ))
        for path in task.changed_paths:
            claimed.setdefault(path, task.task_id)

    return LandingPlan(head=head, landings=tuple(landings))


class AttemptStatus(str, Enum):
    LANDED = "LANDED"
    ATTEMPTED = "ATTEMPTED"              # integration ran and did not land
    SKIPPED_STALE_REVIEW = "SKIPPED_STALE_REVIEW"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"      # an earlier landing superseded the plan
    PLAN_SUPERSEDED = "PLAN_SUPERSEDED"  # the head moved between plan and land


@dataclass(frozen=True)
class LandingAttempt:
    """What actually happened to one entry of a plan.

    Every entry gets one, including the ones never tried: returning a
    shorter list than the plan would leave a caller unable to tell
    "refused because its review expired" from "we stopped before reaching
    it", which are different things an operator would act on differently.
    """

    planned: PlannedLanding
    status: AttemptStatus
    result: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {"planned": self.planned.to_dict(), "status": self.status.value,
                "result": self.result.to_dict() if self.result is not None else None}


class LandingCoordinator:
    """Lands a batch of converged tasks in planned order, or explains why not.

    The production caller for `plan_landings`, because a planner nothing
    calls is a parallel fiction (Directive 9) — and because the plan's
    most important output, `review_still_applies`, has to be ACTED on by
    something or it is a field nobody reads.

    Default behaviour is deliberately conservative: a task whose review no
    longer describes the tree it would land on is NOT landed. It is
    returned as needing re-review. Landing it anyway would keep the
    verification half of convergence and quietly drop the review half,
    which is the shape of every claim this project has had to retract.
    `allow_stale_review=True` is the explicit opt-out for an operator who
    has decided that a re-verified merge is enough for their repo.
    """

    def __init__(self, integrator: Any,
                 stale_review_authorised: set[str] | None = None,
                 re_reviewer_for: Callable[[str], Any] | None = None) -> None:
        self.integrator = integrator
        # A FACTORY, not a reviewer: the reviewer's policy identity and
        # its evidence directory are per task, so one shared instance
        # would judge every task under the first one's name.
        self.re_reviewer_for = re_reviewer_for
        # Whether a stale review can be REPLACED with a fresh verdict
        # rather than only waived.
        self.can_rereview = (re_reviewer_for is not None
                             or getattr(integrator, "re_reviewer", None) is not None)
        # PER TASK, not a global switch. A boolean made every stale entry
        # eligible at once and carried no record of who decided what — so
        # the only way to land one deliberately re-reviewed task was to
        # authorise all of them, which pressures the opt-out into being
        # the default (independent review). A set names exactly the tasks
        # an operator has re-reviewed.
        self.stale_review_authorised = set(stale_review_authorised or ())

    def _live_head(self) -> str | None:
        head, _ = self.integrator.preview_head() if hasattr(
            self.integrator, "preview_head") else (None, None)
        return head

    def plan(self, head: str, task_ids: list[str],
             converged_at: dict[str, float] | None = None) -> LandingPlan:
        """Read each task's facts from the repository, then plan."""
        stamps = converged_at or {}
        ready: list[ReadyTask] = []
        for task_id in task_ids:
            base_sha, changed = self.integrator.preview(task_id)
            if base_sha is None:
                continue
            ready.append(ReadyTask(
                task_id=task_id, base_sha=base_sha, changed_paths=changed,
                converged_at=stamps.get(task_id, 0.0),
            ))
        return plan_landings(head, ready)

    def land(self, plan: LandingPlan,
             convergence_for: dict[str, Any]) -> list[LandingAttempt]:
        """Integrate in planned order. Stops after the first landing.

        Stopping is not a limitation to be optimised away later: once one
        task lands, every remaining plan entry was computed against a head
        that no longer exists. Continuing down a stale plan would be
        planning theatre — the caller re-plans against the new head, which
        is cheap and honest.

        Every plan entry still gets an attempt record, including the ones
        never tried, so a caller can tell a refusal from a stop.
        """
        live = self._live_head()
        if live is not None and live != plan.head:
            # The plan was computed against a head that has since moved,
            # so every `review_still_applies=True` in it is about a tree
            # that no longer exists. The integrator would still refuse to
            # advance unverified — but it cannot rescue review evidence,
            # and honouring a stale plan's True is exactly the silent
            # half-guarantee this module exists to prevent (independent
            # review). Re-plan; it is cheap.
            return [LandingAttempt(planned, AttemptStatus.PLAN_SUPERSEDED)
                    for planned in plan.landings]

        attempts: list[LandingAttempt] = []
        landed = False
        for planned in plan.landings:
            if landed:
                attempts.append(LandingAttempt(planned, AttemptStatus.NOT_ATTEMPTED))
                continue
            stale = not planned.review_still_applies
            authorised = planned.task.task_id in self.stale_review_authorised
            if stale and not authorised and not self.can_rereview:
                # No verdict available and no authority: the only honest
                # answer is to refuse.
                attempts.append(
                    LandingAttempt(planned, AttemptStatus.SKIPPED_STALE_REVIEW))
                continue
            # A stale review is RECOVERABLE now: the integrator can run an
            # independent reviewer against the merged tree, which is the
            # tree that actually lands (ADR-0021). Operator authority
            # remains as the escape hatch for a repo that has decided a
            # re-verified merge is enough, but it is no longer the only
            # way past — which is what made it pressure toward being the
            # default.
            task_id = planned.task.task_id
            outcome = self.integrator.integrate(
                task_id, convergence_for.get(task_id),
                # Staleness is the integrator's to determine; this only
                # carries the operator's WAIVER for a specific task.
                waive_stale_review=authorised,
                re_reviewer=(self.re_reviewer_for(task_id)
                             if self.re_reviewer_for is not None else None),
            )
            landed = bool(getattr(outcome, "integrated", False))
            attempts.append(LandingAttempt(
                planned,
                AttemptStatus.LANDED if landed else AttemptStatus.ATTEMPTED,
                outcome,
            ))
        return attempts
