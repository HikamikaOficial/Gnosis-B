"""A bound on what one brief may spend, enforced where spending happens.

Every loop in this kernel is individually bounded — `max_attempts` on a
run, `max_rounds` on convergence, `max_unchanged_rounds` on stalemate —
and none of that bounds a BRIEF. Three retries of an implementation, then
three convergence rounds each launching a reviewer and a fixer, is a
dozen agent launches nobody authorised as a total. Constitution rule 8
says no loop is unlimited; the circuit-breaker list names wall-time and
budget explicitly, and until now that line had no implementation.

Two things are counted, because they are the two that actually run out:

- **wall clock**, which bounds a brief that is slow rather than numerous;
- **agent launches**, which bounds one that is numerous rather than slow.

Tokens are deliberately not counted. The kernel shells out to a CLI and
never sees a token count it could trust; inventing an estimate and
enforcing on it would be a budget in name only. When an adapter can
report real usage, this is where it goes.

The ledger is consulted at the same place the policy gate is consulted —
immediately before a launch — because that is the last moment at which
refusing still costs nothing.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class BudgetExhausted(RuntimeError):
    """The brief has spent what it was given.

    Not an agent failure: nobody did anything wrong, the work simply cost
    more than it was authorised to cost. Callers map it to a park or an
    escalation, never to FAIL_CODE."""

    def __init__(self, kind: str, spent: float, limit: float) -> None:
        super().__init__(f"budget exhausted: {kind} {spent:.1f} of {limit:.1f}")
        self.kind = kind
        self.spent = spent
        self.limit = limit


@dataclass(frozen=True)
class Budget:
    """What a brief may spend. `None` means unbounded on that axis."""

    wall_clock_s: float | None = None
    max_agent_launches: int | None = None

    def __post_init__(self) -> None:
        for name in ("wall_clock_s", "max_agent_launches"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number or None, got {value!r}")
            if value <= 0:
                # A zero budget authorises nothing and would read as a
                # configuration mistake rather than a decision; an
                # operator who wants that says `max_agent_launches=None`
                # plus a policy that denies.
                raise ValueError(f"{name} must be positive, got {value!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"wall_clock_s": self.wall_clock_s,
                "max_agent_launches": self.max_agent_launches}


class BudgetLedger:
    """Tracks one brief's spend across ALL of its invocations.

    The first version tracked one *invocation*, which is not the same
    thing and made the whole mechanism defeatable: a parked brief that is
    released and re-claimed got a fresh ledger, so repeating that cycle
    launched agents forever while every individual run looked bounded
    (independent review). A budget that resets on resumption is a budget
    in name only, and rule 4 says the state that matters survives the
    process. `prior_launches` and `prior_elapsed_s` are how a resumed run
    inherits what the brief already spent; `BudgetStore` is where they
    come from.
    """

    def __init__(self, budget: Budget | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 prior_launches: int = 0,
                 prior_elapsed_s: float = 0.0) -> None:
        # MONOTONIC here, unlike the hold plane's wall clock: this measures
        # an ELAPSED interval inside one process, which is exactly what a
        # monotonic clock is for and what a wall clock gets wrong when the
        # system time is adjusted mid-brief.
        self.budget = budget or Budget()
        self.clock = clock
        self.started_at = clock()
        self.prior_elapsed_s = max(0.0, float(prior_elapsed_s))
        self.launches = max(0, int(prior_launches))
        self.refusals: list[str] = []

    @property
    def elapsed_s(self) -> float:
        """This invocation's elapsed time PLUS what earlier ones spent.

        Monotonic within an invocation, because that is what measures an
        interval correctly; carried across invocations as a number,
        because a monotonic reading means nothing in another process.
        """
        return self.prior_elapsed_s + max(0.0, self.clock() - self.started_at)

    @property
    def this_invocation_s(self) -> float:
        return max(0.0, self.clock() - self.started_at)

    def remaining_launches(self) -> int | None:
        if self.budget.max_agent_launches is None:
            return None
        return max(0, self.budget.max_agent_launches - self.launches)

    def check(self) -> None:
        """Raise if the brief may not spend any more. Consulted BEFORE a
        launch: refusing after the money is gone is not a budget."""
        limit = self.budget.wall_clock_s
        if limit is not None and self.elapsed_s >= limit:
            self.refusals.append("wall_clock")
            raise BudgetExhausted("wall_clock_s", self.elapsed_s, limit)
        launches = self.budget.max_agent_launches
        if launches is not None and self.launches >= launches:
            self.refusals.append("agent_launches")
            raise BudgetExhausted("max_agent_launches", self.launches, launches)

    def spend_launch(self) -> None:
        """Record a launch that is about to happen.

        Counted before the child starts, not after it returns: a launch
        that crashes still consumed the thing being bounded, and counting
        on the way out would let a crash-looping brief spend forever.
        """
        self.launches += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget": self.budget.to_dict(),
            "elapsed_s": round(self.elapsed_s, 3),
            "launches": self.launches,
            "remaining_launches": self.remaining_launches(),
            "refusals": list(self.refusals),
        }


class BudgetStore:
    """Durable per-brief spend, so a budget survives park and resume.

    One JSON file per brief. Deliberately not append-only: this is a
    running total, not a history — the history of what a brief did lives
    in its run ledgers and its reports, which are the tamper-evident
    records. What is needed here is a number that cannot be reset by
    restarting.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, brief_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in brief_id)
        return self.root / f"{safe or 'brief'}.json"

    def load(self, brief_id: str) -> tuple[int, float]:
        """(launches, elapsed_s) this brief has already spent.

        Unreadable state reads as ZERO SPENT, which is the permissive
        direction — stated plainly rather than hidden. The alternative,
        refusing to run a brief whose spend record is damaged, converts a
        corrupt file into a permanently un-runnable brief; the attempt
        cap on the queue is the bound that still applies in that case.
        """
        try:
            payload = json.loads(self._path(brief_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return 0, 0.0
        if not isinstance(payload, dict):
            return 0, 0.0
        launches = payload.get("launches", 0)
        elapsed = payload.get("elapsed_s", 0.0)
        if isinstance(launches, bool) or not isinstance(launches, int):
            launches = 0
        if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)):
            elapsed = 0.0
        return max(0, launches), max(0.0, float(elapsed))

    def record(self, brief_id: str, ledger: BudgetLedger) -> None:
        """Persist what this brief has now spent in total."""
        payload = {
            "brief_id": brief_id,
            "launches": ledger.launches,
            "elapsed_s": round(ledger.elapsed_s, 3),
        }
        path = self._path(brief_id)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    def ledger_for(self, brief_id: str, budget: Budget | None,
                   clock: Callable[[], float] = time.monotonic) -> BudgetLedger:
        launches, elapsed = self.load(brief_id)
        return BudgetLedger(budget, clock=clock,
                            prior_launches=launches, prior_elapsed_s=elapsed)
