# ADR-0016 — The hold/park plane under a scheduler (adapter milestone, 4/4)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `.gnosis/evidence/20260820T215628Z/` (captured argv, exit
  codes and output — see D-023); `tests/test_scheduler.py` (17 tests);
  552 passed; mypy strict clean over 47 files.
- Independent review: **not done.** Codex is `RATE_LIMITED` until
  2026-09-19 and internal reviewer agents are out of usage credits.
  Self-review only — which found one dead mechanism (below). Stated
  plainly, as ADR-0015 does, because a unit reviewed only by its author
  should be read as such.
- Builds on: ADR-0012 (holds, reconcile, `boot_sweep`).

## Context

ADR-0012 built credential-scoped rate-limit holds, recovery-as-reconcile
and `boot_sweep`, and stated as a Known Limitation that none of it had a
production caller. Last of the four mechanisms Directive 9's review found
were parallel fictions.

## Decision

`TaskScheduler` is deliberately small — not a queue, a worker pool or a
priority system, which are the multi-worker milestone. It is the three
places the hold plane has to be consulted for it to be real:

1. **Before a launch**, `admits()` decides. A task refused by a hold is
   PARKED: recorded, resumable, not failed, and never counted against
   agent quality (rules 6 and 7).
2. **After a run parks**, a durable hold is placed. Only a
   `RATE_LIMITED` classification places one — holding a credential
   because a test failed would take the whole system down for a bug.
3. **At boot**, `boot_sweep` gives every stranded run a disposition and
   this is the half that writes it, so no record is left neither
   progressing nor terminal.

`HoldStore` is an append-only JSONL. `HoldRegistry` is rebuilt from it on
every pump rather than mutated, so a double pump, a second scheduler and
a restart all land in the same state.

### Observations compete; decisions supersede

`reconcile` keeps the **most restrictive** competing hold, so two
observations of a shut window can never relax each other by arriving in
the wrong order. The consequence is that an appended row can never
*narrow* an existing hold — which quietly made `probe()` dead code: its
PROBE row simply lost to the ACCOUNT row it was meant to replace.

So the store carries two row kinds. A `hold` row is an observation and
competes. A `supersede` row is a decision and draws a line: earlier rows
for that credential no longer apply. Both are durable and both name a
reason, which is the property that matters — **a window is never
reopened silently, only by a recorded act.** It also gives an operator
the honest way to clear a hold that reality has overtaken (a topped-up
account) without editing a file.

### The clock is wall time

`reset_at` is an epoch timestamp the provider supplied. A monotonic
reading is neither comparable to it nor meaningful across the restart
these rows exist to survive; mixing them would make every durable hold
look permanently unexpired. Pinned by a test that uses the real default
clock rather than the injected one.

## Known limitations (stated, not implied)

- **One credential per scheduler.** Multi-credential rotation (try the
  next account when one is shut) is not modelled. The store is already
  keyed by credential, so this is a scheduler concern, not a data one.
- **No queue.** `submit()` runs one task synchronously and returns; a
  parked task is reported to the caller, not retained for later. Whoever
  owns the work list decides what to do with a park — deliberately, since
  a queue that silently retries a parked task is how a stampede starts.
- **`probe()` is available but nothing calls it automatically.** Deciding
  *when* to spend a probe against a shut window is a scheduling policy
  this milestone does not set.
- **`boot()` liveness is best-effort.** An unknown fingerprint reads as
  "not demonstrably alive", which re-adopts work rather than stranding
  it — the safer direction, but it can re-adopt a run whose process is
  actually alive on a platform where the fingerprint cannot be read.

## Self-review note

Writing `test_a_probe_admits_only_the_named_run` is what exposed
`probe()` being inert: the code read correctly and did nothing, because
the restrictiveness rule it had to cooperate with was written for a
different purpose. Same lesson as L-0007 — the test that asserts a
*consequence* finds what the test asserting a value cannot.
