# ADR-0019 — The multi-worker plane: a durable queue and a per-brief budget

- Status: ACCEPTED
- Date: 2026-08-21
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `.gnosis/evidence/20260821T020757Z/`;
  `tests/test_work_queue.py` (25 tests, incl. 6 real threads racing on
  24 briefs), `tests/test_pipeline.py::TestABriefIsBounded` (3);
  643 passed; mypy strict clean over 52 files.
- Independent review: **done, 2026-08-21, verdict FAIL** — Codex,
  read-only. Seven findings, two critical; all repaired. See the
  addendum.
- Builds on: ADR-0006 (durable CAS claims, fencing epochs, leases),
  ADR-0017 (the pipeline a worker runs).

## Context

Everything so far ran one brief at a time, synchronously.
`GovernedPipeline.run_pending` iterates a list; there is nowhere for work
to wait and no way for two workers to disagree safely. ADR-0016's and
ADR-0018's Known limitations name the pieces: no queue, no cross-task
ordering, `probe()` uncalled, `changed_paths` unreasoned-about, and no
budget across a brief.

This ADR takes the first and the last of those. The ordering questions
need a scheduler that has a work list first, which is what this builds.

## Decision

### Ownership is not this module's business

`WorkAuthority.acquire` is already "exactly one holder, provably" —
durable CAS with fencing epochs plus an expiring lease, hardened across
two reviews. A queue with its own ownership notion would mean two
answers to "who owns this" and a bug the day they disagree. So the queue
is **a place to put briefs**, and every worker races through the claims
plane:

- every worker scans the same `pending/` directory and sees the same
  briefs;
- they all call `acquire`, and the CAS lets exactly one through;
- a `ClaimConflictError` is the mechanism working, not a failure, so the
  loser moves to the next brief.

A crashed worker's CLAIM is reclaimed by the lease TTL, and that is not
enough on its own: the queue keeps file state separately, so a killed
worker's brief sat in `running/` where no worker ever looks — ownership
free, record unreachable, which is exactly the ghost rule 4 forbids.
`recover()` closes that, and `drain` calls it before the first claim,
because a mechanism nothing calls is a parallel fiction.

Where a recovered record GOES depends on what the claim says happened,
not merely that nobody holds it: a `RESOLVED` claim means the work
finished and the crash was in the bookkeeping, so it goes to `done/`.
Returning it to `pending` would re-execute finished work — worse than
the ghost (addendum 2).

Liveness is still not this module's notion. It asks the claims plane
what the claim's status is; the sweep that decides it lives in
`WorkAuthority`.

**`release` is separate from `complete` on purpose.** A park (rule 6)
leaves the work untouched and resumable, so a released brief returns to
`pending` and is claimable again — by this worker later, or another now.
A queue where a park consumed the work would quietly turn rule 6 into a
data-loss bug.

### A brief is bounded, not just its loops

Every loop here was already bounded — `max_attempts`, `max_rounds`,
`max_unchanged_rounds` — and none of that bounds a BRIEF. Three
implementation attempts, then three convergence rounds each launching a
reviewer and a fixer, is a dozen agent launches nobody authorised as a
total. Rule 8 lists wall-time and budget among the required circuit
breakers, and that line had no implementation.

The ledger is **durable and per brief**, not per invocation. The first
version was per invocation, which made the mechanism defeatable: a
parked brief that was released and re-claimed got a fresh ledger, so
repeating that cycle launched agents forever while every individual run
looked bounded (addendum 4). `BudgetStore` carries the running total
across resumptions and restarts, because rule 4 says the state that
matters survives the process.

`Budget` counts two things because they are the two that run out: wall
clock (a brief that is slow) and agent launches (a brief that is
numerous). It is consulted in `GatedAgentRunner`, at the same moment as
the policy gate, because that is the last point at which refusing still
costs nothing — and a launch is **counted before the child starts**,
since a launch that crashes still consumed what is being bounded.

Tokens are deliberately not counted: the kernel shells out to a CLI and
never sees a count it could trust, and enforcing on an invented estimate
would be a budget in name only.

**Exhaustion is a park, never a failure.** Nobody did anything wrong;
the work cost more than it was authorised to cost. The brief reports
PARTIAL with the implementation intact and a next step naming the
budget.

### The implementation's launches are charged after the fact

A convergence launch is refused *before* it costs anything. The
implementation launch cannot be — the pipeline does not own the engine's
runner and cannot gate it — so its attempts are charged to the ledger
once it returns. That is sound only because the engine has its own hard
bound (`RetryPolicy.max_attempts`), so the phase cannot run away; what
the budget then bounds exactly is everything after it. Stated because
"the budget covers every launch" would otherwise be the third claim in
this project to overreach in the same direction.

## Known limitations (stated, not implied)

- **No cross-task ordering.** The queue hands out whatever is pending in
  name order. Nothing notices that two briefs touch overlapping paths, or
  that landing A will certainly break B. `changed_paths` is recorded
  (ADR-0018) and still nothing reasons about it.
- **No worker supervision.** `drain` is a generator a caller loops; there
  is no worker process, no restart, no health. A crashed worker's brief
  is reclaimable through the lease TTL, which is recovery, not
  supervision.
- **Threads, not processes, are what the concurrency test proves.** The
  claims plane is file-locked and process-safe by construction, but the
  evidence here is 6 threads in one process; cross-process racing is
  argued from `ClaimStore`'s own tests rather than demonstrated here.
- **A released brief is re-offered immediately**, so a caller that parks
  in a tight loop would spin. `Budget` does NOT bound that — parking
  launches nothing and spends nothing — so the queue carries its own
  `max_attempts`, durable on the record (addendum 6). What is still
  missing is backoff: the bound stops the loop, it does not pace it.
- **`probe()` still has no automatic caller**, and multi-credential
  rotation is still unmodelled (ADR-0016).

## Codex review addendum (2026-08-21, independent, verdict FAIL)

Seven findings. Transcript:
`.gnosis/lab/kernel-reviews/codex-review-2026-08-21-work-queue.jsonl`.

1. *(critical, already repaired)* **A crash after the file move stranded
   the brief.** Found by self-review before the verdict arrived and
   confirmed independently: the lease TTL reclaims the CLAIM, and nothing
   scanned `running/`, so the record was unreachable forever.
   `recover()` plus `drain` calling it.
2. *(critical, repaired)* **My own fix was wrong for one case.**
   `complete` resolves the claim and *then* moves the file; a crash
   between them leaves a RESOLVED claim in `running/`, and the first
   `recover()` returned that to `pending` — re-executing finished work,
   which is worse than the ghost it was written to prevent. Recovery now
   reads the claim's status and routes a RESOLVED record to `done/`.
3. *(major, repaired)* **A stale grant could hand out work.** The grant
   is taken before the file moves; a stalled worker can have its lease
   expire and its claim reclaimed inside that gap, then win the move and
   return `ClaimedWork` it no longer owns. `assert_current` is now asked
   at the last moment before the work leaves `claim()` — the claims
   plane's own NO STALE WRITE guard, which was available and unused.
4. *(critical in effect, repaired)* **The budget was per invocation, not
   per brief.** A parked brief that was released and re-claimed got a
   fresh ledger with `launches` back to zero, so the park/resume cycle
   launched agents without limit while each run looked bounded. The
   module's own docstring said "tracks one brief's spend"; it tracked
   one invocation. `BudgetStore` makes the total durable.
5. *(major, claim corrected + partly repaired)* **Implementation retries
   are charged after the fact**, so `max_agent_launches` does not bound
   that phase precisely. The ADR documented the mechanism but claimed the
   brief was bounded. The claim is now precise, and the ledger is checked
   *before* the implementation as well, so a brief that has already spent
   everything cannot start another implementation phase.
6. *(major, repaired)* **`drain` re-offers a released brief immediately**
   and the budget does not bound that loop, because parking launches
   nothing. The queue now carries `max_attempts`, durable on the record;
   an exhausted brief stops being offered and says so in `skipped`
   rather than being silently skipped forever.
7. *(minor, repaired)* **Concurrent enqueue was not idempotent.** Two
   enqueuers both passed the existence check before either wrote, and
   replace-based writing let the later one silently win. Exclusive
   create (`open(..., "x")`) makes the filesystem the arbiter.

Codex found no defect in the monotonic-clock choice within a live
ledger, in `GatedAgentRunner`'s check-then-charge ordering, or in the
sorted-name ordering being presented as fair — it is documented as
arbitrary rather than claimed to be fair.
