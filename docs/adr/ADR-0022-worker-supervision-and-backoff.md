# ADR-0022 — Worker supervision: pacing, bounds, and the line a supervisor may not cross

- Status: ACCEPTED
- Date: 2026-08-21
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `.gnosis/evidence/20260821T135555Z/` (695 passed, mypy strict
  clean over 54 files, ruff at the 19-finding baseline);
  `tests/test_supervisor.py` (17 tests),
  `tests/test_work_queue.py::TestACrashBetweenThePlaneAndTheFile` and
  `::TestAWaitNobodyCanSee`.
- Independent review: **NOT DONE — Codex refused with a usage-limit
  error** (reset reported as 2026-09-20). This unit ships self-reviewed,
  and that is a weaker claim than every unit since ADR-0017. See
  "Self-review" below for what was found without it, and take the
  findings as evidence of what an independent pass would likely have
  added, not as a substitute for one.
- Builds on: ADR-0019 (the queue and `drain`), ADR-0016 (the boot sweep
  and the hold plane), ADR-0006 (claims and leases).

## Context

ADR-0019 left `drain`: a generator a caller iterates. There is no worker
process, no restart story, no health, and a released brief is re-offered
instantly. The queue's `max_attempts` stops that loop, but nothing paces
it — a brief parked because a rate-limit window is shut is re-tried as
fast as the caller can loop, which is precisely the behaviour rule 6
exists to prevent.

## Decision

### The interesting question is authority, not retry

Re-running a brief is not free: it launches agents, spends a budget, and
may repeat side effects nobody recorded. The constitution says
irreversible acts are prepared, not executed, without higher authority.
So the line is drawn in the module itself:

**A supervisor MAY** pace a retry, stop when the queue empties, stop on
its own circuit breakers, and take an exhausted brief out of circulation.
All of those either do nothing or do less.

**A supervisor MAY NOT** clear an attempt count, resurrect a blocked
brief, or re-run work a worker recorded as having an unknown outcome.
Those are `WorkQueue.requeue`, which exists for an operator to call.

### Backoff is durable, on the brief's own record

`not_before`, written by `release()`, exponential in the brief's durable
attempt count. Backoff held in a worker's memory is backoff a restart
forgets — and what it paces, launches against a shut window, is exactly
what must not resume at full speed after a crash. That is L-0024's shape
applied to pacing.

### A transition is two writes, and the gap between them is a decision

`complete`, `release` and `block` are each a claims-plane call followed
by a file move. A crash between them left the record in `running/` for
recovery to route on claim status alone — which could not distinguish "a
worker decided this must be blocked" from "a worker died holding it", and
returned the blocked brief to `pending`. The decision is now **stamped on
the record before the plane call**, and recovery finishes what the dead
worker decided instead of overruling it. The stamp clears itself on
arrival, so a requeued brief cannot carry a marker from a past life.

### An unusable `not_before` is ignored out loud

`inf`, `NaN`, `True` and a string all mean "never claimable" if honoured
literally, leaving the brief in `pending` looking available to anyone who
lists the queue — the invisible ghost rule 4 forbids, arriving through
the pacing door. They are ignored and recorded in `skipped`. `waiting()`
exists so an operator asking "why is nothing moving" sees the wait rather
than inferring it.

### Circuit breakers, against rule 8's list

| rule 8 asks for | where it is |
| --- | --- |
| max attempts | `WorkQueue.max_attempts`; exhausted briefs MOVE to `blocked/` |
| wall-time | `SupervisorPolicy.wall_clock_s`, checked between briefs |
| budget | `BudgetStore`, per brief, durable (ADR-0019) |
| invalid-output limit | a handler returning a non-`Disposition` blocks the brief |
| max no-diff rounds | N/A at this layer; it is the convergence loop's |
| max **same** failure | **absent** — see limitations |

`max_consecutive_parks` is the addition rule 8 does not name: a queue
where every brief parks is a system waiting on something external, and
spinning through it re-learns the same answer.

## Known limitations (stated, not implied)

- **No independent review.** The first unit since ADR-0016 without one.
- **`wall_clock_s` bounds the loop, not a handler.** Nothing here can
  interrupt a call in progress; one long handler overruns it arbitrarily.
- **No "max same failure".** `max_consecutive_parks` counts parks
  regardless of reason, so a brief parking for a *new* reason each time
  and one parking for the same reason are treated identically. Doing this
  properly needs the park reason to be typed, not a string.
- **Recovery re-offers work whose outcome it cannot know.** Where no
  decision was recorded, recovery cannot tell "claimed, handler never
  started" from "claimed, handler half-ran, worker died". `attempts` is
  the bound — the claim increments it, so a crash loop terminates in
  `blocked/`. Saying "a supervisor never re-runs unknown work" would be
  false; the module says the true thing instead.
- **One worker per `run()`.** Concurrency comes from running several,
  which the claims plane already makes safe; there is no worker pool,
  no health endpoint and no supervision tree.
- **`_stamp` is best-effort.** If the pre-write fails, the transition
  proceeds and recovery falls back to claim-status routing — where it was
  before. It can add information, never withhold a move.

## Self-review (no independent verdict available)

Four defects found by attacking the same categories the review brief
named. Three were real and are repaired:

1. *(critical, repaired)* **A block decision was lost to a crash.**
   Reproduced directly: claim, release the claim, crash before the move;
   `recover()` returned the brief to `pending`, claimable again, with the
   decision that a human must look at it erased. Fixed by the intent
   stamp. Mutation-checked — reverting the routing fails the test.
2. *(major, repaired)* **"Backoff is durable" was false across that same
   window.** A park that crashed between the plane call and the move lost
   its `not_before` entirely, so pacing evaporated exactly when the system
   was least healthy. Same fix; mutation-checked against `_stamp`.
3. *(major, repaired)* **An invalid handler output was silently a park.**
   A bare `return` — the commonest handler bug — fell into the `else`
   branch and became an indefinite pacing loop that read as a system
   waiting on a window. It is now an `INVALID_OUTPUT` stop and the brief
   is blocked, because the outcome is as unknown as a raise. The check is
   `isinstance`, not identity: `Disposition` is a `str` enum, so the
   string `"PARK"` compares equal to a member and must still be refused.
4. *(minor, corrected)* **A false claim in the module docstring.** It
   said a supervisor may not "decide that work whose outcome is unknown
   should run again", while `run()` calls `recover()` as its first act.
   The claim is now the narrower true one, with the gap named.

Typing the handler result as `object` rather than `Disposition` is what
makes the guard reachable to mypy — the annotation is a promise the
runtime cannot enforce, and this loop is where that is discovered.
