# ADR-0016 — The hold/park plane under a scheduler (adapter milestone, 4/4)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `.gnosis/evidence/20260821T001211Z/` (captured argv, exit
  codes and output — see D-023); `tests/test_scheduler.py` (24 tests);
  566 passed; mypy strict clean over 47 files.
- Independent review: **done, 2026-08-21, verdict FAIL** — Codex,
  read-only. Nine findings, five critical and all pointing the same way:
  the hold plane failed OPEN. See the addendum.
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

1. **Before a launch**, `admits()` decides — and decides again
   immediately before the child, because another scheduler can place a
   hold in between. A task refused by a hold is PARKED: recorded,
   resumable, not failed, and never counted against agent quality (rules
   6 and 7).
2. **After a run parks**, a durable hold is placed. Only a
   `RATE_LIMITED` classification places one — holding a credential
   because a test failed would take the whole system down for a bug.
3. **At boot**, `boot_sweep` gives every stranded run a disposition and
   this is the half that writes it, so no record is left neither
   progressing nor terminal.

`HoldStore` is an append-only JSONL. `HoldRegistry` is rebuilt from it on
every pump rather than mutated, so a double pump, a second scheduler and
a restart all land in the same state.

### Damage denies

A hold plane that cannot read its own records must not report "no
holds". The first version skipped unreadable rows and returned the rest,
reasoning that refusing everything would open every window at once —
which was backwards: skipping the row opens the window *it* described,
and a truncated sole hold silently admitted work against a shut
credential. `HoldStore.read()` returns a `HoldSnapshot` carrying both the
holds and whatever was unreadable, and `admits()` denies when anything is
damaged. Reads take the writer's lock, so a half-written row is never
observed as an absent one.

### Observations compete; decisions supersede

`reconcile` keeps the **most restrictive** competing hold, so two
observations of a shut window can never relax each other by arriving in
the wrong order. The consequence is that an appended row can never
*narrow* an existing hold — which quietly made `probe()` dead code: its
PROBE row simply lost to the ACCOUNT row it was meant to replace.

So the store carries three row kinds. A `hold` row is an observation and
competes. A `supersede` row is a decision and draws a line: earlier rows
for that credential no longer apply — and it must be complete (a
credential, a reason, a timestamp), because a half-specified control row
still erased every hold. A `narrow` row is supersede-and-replace **as one
row**, which is what `probe()` writes: two rows in a single append was
not enough, since a crash can flush one line and not the next, leaving a
supersede with nothing replacing it. The atomic unit is the line, so an
atomic transition has to be a line. A test walks every byte-prefix of the
log and asserts that none of them admits work.

All of them are durable and all of them name a reason, which is the
property that matters — **a window is never reopened silently, only by a
recorded act.** It also gives an operator the honest way to clear a hold
that reality has overtaken (a topped-up account) without editing a file.

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
- **`admits()` is a check, not a reservation.** Re-checking immediately
  before the launch shrinks the window between the decision and the child
  to microseconds; it does not close it. Closing it needs a lease on the
  credential, which is the multi-worker milestone. Stated because a
  check-then-act cannot be made exact by narrowing it.
- **The hold log grows without bound and is re-read on every pump.**
  Measured: 20 000 rows is ~3.7 MiB and ~140 ms per read, and expired
  rows are still parsed every time. The work per pump is linear in the
  log, and the log only grows — so calling a pump "bounded" would be
  false. Compaction (snapshot + truncate) is the
  fix and it is deliberately not built yet: it trades durable evidence
  for speed, which is a decision for whoever runs this continuously —
  and today nothing does. Recorded with the measurement rather than as a
  vague "may grow".
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

## Codex review addendum (2026-08-21, independent, verdict FAIL)

Nine findings. Transcript:
`.gnosis/lab/kernel-reviews/codex-review-2026-08-21-scheduler.jsonl`.
Five were critical, and they all pointed the same way: **the hold plane
failed open** — five different ways for a credential known to be shut to
admit work. For a safety mechanism that is the wrong direction in every
one of them.

1. *(critical, repaired)* **A damaged or truncated row read as "no
   hold".** The skip-and-continue policy I wrote sacrificed exactly the
   hold it could not parse. Damage now denies.
2. *(critical, repaired in part)* **TOCTOU, and readers ignored the
   writer's lock.** Reads now take the lock, and `submit()` re-checks
   immediately before the launch. The residual — a check is not a
   reservation — is now in Known limitations rather than implied away.
3. *(critical, repaired)* **A `supersede` row needed neither a reason nor
   a timestamp**, so a half-specified control row still erased every hold
   on a credential. Both are required now; an incomplete decision is
   damage.
4. *(critical, repaired)* **`probe()` opened a window between two rows.**
   Supersede-then-place meant a crash in between left the credential
   durably open. It is one `narrow` row now, and a test walks every
   byte-prefix of the log asserting none admits work.
5. *(critical, repaired)* **A PROBE hold admitted by scheduler identity,
   not by run.** Any submission from any scheduler sharing the id got in
   — the stampede a probe exists to prevent. My own test hid it by giving
   `scheduler_id` and `probe(run_id)` the same string; the identities are
   deliberately different now.
6. *(major, repaired)* **The recovery boundary accepted `Infinity`,
   `NaN` and booleans as a window.** `hold_from_classification` validates
   on the way in; `from_dict` did not on the way out, so a damaged row
   could hold a credential forever — and `NaN` additionally made
   `reconcile` order-dependent, since every comparison against NaN is
   false.
7. *(major, claim corrected)* Per-pump work is linear in a log that only
   grows, so describing it as bounded was wrong. The measurement is in
   Known limitations.
8. *(critical, repaired)* **One corrupt heartbeat aborted the entire boot
   sweep**, leaving every later run with no disposition — the sweep
   causing the very ghost it exists to prevent.
9. *(major, repaired)* **Liveness trusted too much.** A heartbeat with no
   `start_time` made `is_alive` answer "a process with this PID exists",
   which on a recycled PID is a different process wearing a dead run's
   identity; and a future timestamp was clamped to zero staleness, making
   a dead run look freshly checked in. Both report *unknown* now, which
   the sweep treats as not demonstrably alive — re-adopting work costs a
   re-run, stranding it costs the work.

Codex found no path turning an ordinary failure into a credential hold,
and no path writing a `RATE_LIMITED` run as `FAILED`: rules 6 and 7 hold.

**What this says about the self-review below.** It found one dead
mechanism — real, and the kind of thing only writing a test finds. It
found none of the five fail-open paths, because they all live in the part
of the design I was most confident about. That is exactly the shape
L-0016 predicts.
