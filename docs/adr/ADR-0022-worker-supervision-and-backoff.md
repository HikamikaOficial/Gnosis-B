# ADR-0022 — Worker supervision: pacing, bounds, and the line a supervisor may not cross

- Status: ACCEPTED
- Date: 2026-08-21
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `.gnosis/evidence/20260821T170951Z/` (755 passed, mypy strict
  clean over 55 files, ruff at the 19-finding baseline), superseding the
  pre-review capture `20260821T135555Z/` (695 passed);
  `tests/test_supervisor.py` (17 tests),
  `tests/test_work_queue.py::TestACrashBetweenThePlaneAndTheFile` and
  `::TestAWaitNobodyCanSee`.
- Independent review: **DONE 2026-08-21, verdict FAIL, 19 findings** —
  by an independent read-only agent in a clean context, **not by Codex**,
  whose usage limit stood (reset reported 2026-09-20). Three criticals.
  Eight findings repaired, seven recorded as still open; see the
  addendum. A same-family reviewer is a weaker channel than a different
  model, and the addendum says so rather than implying parity.
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

- **The independent review was not Codex.** See the addendum: a
  same-family reviewer shares blind spots a different model would not.
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

## Self-review (written before any independent verdict was available)

Four defects found by attacking the same categories the review brief
named. Three were real and are repaired. Kept verbatim, because the
addendum below is the measurement of what this section MISSED — nineteen
findings against four, three of them critical.

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

## Independent review addendum (2026-08-21, verdict FAIL, 19 findings)

Reviewed by an independent read-only agent in a clean context, **not by
Codex** — its usage limit stood. A same-family reviewer is a weaker
channel than a different model and this addendum does not pretend
otherwise; it is the review this unit would otherwise never have had.
The reviewer modified nothing (tree fingerprint identical either side).

**Three criticals, all real, all reproduced before repair.**

1. *(critical, repaired)* **`WorkAuthority.sweep()` had no production
   caller, so the entire crash-recovery story was inoperative.**
   `recover()` asks the claims plane whether a claim is still ACTIVE;
   nothing ages a dead worker's claim OUT of ACTIVE except the TTL sweep.
   A killed worker's brief therefore stayed ACTIVE for ever, `recover`
   skipped it on every boot, and it sat in `running/` where no scan looks
   — the exact ghost rule 4 forbids and the exact ghost `recover` exists
   to prevent. Every test of that path swept by hand, so the suite was
   green over a mechanism nothing called. `run()` now sweeps before
   recovering. Verified: `grep -rn "\.sweep(" src/` returned nothing.
2. *(critical, repaired)* **`_move` invented a record when the origin had
   vanished, clearing the attempt bound.** The stub `{"brief":
   {"brief_id": ...}}` had no `attempts`, so the next `claim` read 0 — an
   automated path clearing the bound the module swears only an operator
   can clear — and no `title`, so `DirectorBrief.from_dict` raised inside
   `claim` *after* the grant was taken, poisoning the brief permanently.
   A vanished record is now recorded in `skipped` and the move abandoned.
3. *(critical, partially repaired)* **"Recovery runs first" was true;
   what it recovered was not paced, and two supervisors could race it.**
   The pacing half is repaired (see 4); the concurrent-`recover()` race
   is NOT — see Still open.

4. *(major, repaired)* **A deposed worker wrote to the live worker's
   record.** No `GrantHeartbeatPump` was started, so any handler slower
   than the lease TTL deposed itself and then stamped and moved a record
   a NEW owner was running. The pump now covers the whole handler, and a
   worker that finds itself deposed touches nothing and exits as
   `DEPOSED`.
5. *(major, repaired)* **"Every exit names its reason" was false.** A
   `StaleClaimError`/`StaleLeaseError` from any transition escaped `run()`
   and discarded the whole report. Named as `OWNERSHIP_LOST`.
6. *(major, repaired)* **Two clocks.** `not_before` was written with the
   supervisor's clock and read with the queue's, and nothing checked they
   agree: `WorkerSupervisor(queue, clock=time.monotonic)` over a default
   queue wrote deadlines a wall-clock read always sees as past, so every
   parked brief resumed at full speed with nothing recorded. The
   parameter is gone; the supervisor takes the queue's clock.
7. *(major, repaired)* **A rate limit sent work to a human.** The bare
   `except Exception` blocked ANY raise, so `CredentialHeld` and
   `BudgetExhausted` — rules 6 and 7, the things the hold plane exists to
   treat as parks — ended as briefs awaiting an operator. They park, paced.
8. *(major, repaired)* **`QUEUE_EMPTY` was reported over a queue full of
   backing-off briefs.** `ALL_WAITING` now exists and the report carries
   `waiting`. The test that asserted the old behaviour asserted it as
   correct.

**Still open, and stated rather than quietly carried:**

- **Concurrent `recover()` is not safe.** Two supervisors starting
  together can both read a stranded record and both write it, leaving one
  brief simultaneously in `running/` and `pending/`. `recover` holds no
  lock and never re-checks the claim at mutation time — the opposite of
  `ClaimStore.reclaim_if`, which this kernel documents as the right shape.
- **A crash that was not a park resumes unpaced.** Recovery returns the
  record with no `not_before`, so a crash loop re-launches at full speed,
  bounded only by `max_attempts`.
- **`supervisor.queue.requeue(...)` is one attribute hop away.** The line
  the module draws is a docstring, and the test that "pins" it asserts a
  `hasattr`. There is no capability or policy gate at that boundary.
- **`_stamp`'s fallback is not neutral for BLOCK.** If the stamp no-ops,
  a block reverts to claim-status routing, which targets `pending` — the
  critical defect this ADR reports as repaired, still reachable by that
  path.
- **Default breakers are off.** `max_briefs` and `wall_clock_s` default
  to `None`, so a default-constructed supervisor is a `while True` bounded
  only by `max_consecutive_parks` — a counter held in memory, which is the
  very argument the module uses to justify making `not_before` durable.
- **`WorkerSupervisor` still has no production caller.** A class that
  could be a worker process exists; the process does not.
- **The mutation checks this ADR cites left no artifact.** They were run,
  and by this project's own bar a claim about a red run with no captured
  red output is not evidence.

Evidence for the repairs: `.gnosis/evidence/20260821T170951Z/` (755
passed, mypy clean over 55 files, ruff at the 19 baseline).
