# ADR-0023 — The probe has a caller: testing a guessed window with one launch

- Status: ACCEPTED
- Date: 2026-08-21
- Evidence: `.gnosis/evidence/20260821T145030Z/` (711 passed, mypy strict
  clean over 54 files, ruff at the 19-finding baseline);
  `tests/test_scheduler.py::TestTheProbeHasACaller` (12 tests) and
  `tests/test_pipeline.py::TestTheProbeReachesThePathThatLaunches`.
- Independent review: **NOT DONE — Codex refused with a usage-limit
  error** (reset reported 2026-09-20; re-checked at the start of this
  unit). The second consecutive unit shipped self-reviewed. Both are
  recorded as review debt in `NEXT_ACTIONS.md`.
- Builds on: ADR-0016 (which built `probe()` and called it from nowhere),
  ADR-0012 (holds, reconcile, boot sweep), ADR-0006 (claims plane).

## Context

ADR-0016 built the PROBE hold scope, the `narrow` row, the
holder-identity check, and `TaskScheduler.probe()`. Its own Known
limitations said nothing in production invoked it, and a mechanism
nothing calls is a parallel fiction.

Reproduced before touching anything: an ACCOUNT hold on a window the
kernel **estimated** (the bounded fallback for prose evidence) admits
nobody while it stands and, one second after the guess elapses, admits
**every** queued resume at once. The evidence that the window was ever a
guess disappears with the hold, so at the moment a caller would most want
to probe, there is nothing left to probe.

## Decision

**A probe is claimed before the guess elapses, not after.** Reaching back
`lead_s` is what makes the decision possible while there is still
something to decide.

### What is probed, and what is not

A window the **provider supplied** is never probed. It is not a guess,
and spending a launch to contradict it buys nothing. Probing applies to
the kernel's own estimates: `window_estimated` holds within `lead_s` of
elapsing, and unknown-window holds (`reset_at is None`) that have stood
for `unknown_window_wait_s`. The second case is new capability rather
than tuning: such a hold **never expires by itself** — the "loaded gun"
an earlier review named — and a probe is now the only way out of one.

### A probe is a lease, not a window

`probe()` used to copy the `reset_at` of the hold it replaced. That was
wrong in both directions: a timestamp already in the past made the probe
hold expire the instant it was written, admitting everyone — the exact
stampede — and a `None` made a hold that never expires, pinning the
credential to a run that may already be dead. The replacement now gets
its own `ttl_s` deadline and never inherits.

### The claim has exactly one winner

`narrow_if_unclaimed` performs the read and the append **under one
lock**. A check-then-append was not enough: two schedulers finding the
probe due at the same instant both narrowed, the later row won the
rebuild, and the loser could already have passed its own admission check
and launched. This is the same compare-and-set shape the claims plane
uses, for the same reason.

### A successful probe reopens the credential

`observe()` now takes the probe's identity. A launch that did **not** hit
the limit is the answer the probe was asking for, and nothing used to
read it: the narrowing stood until its own deadline while the window was
demonstrably open, so a successful probe kept every other run parked.
Reopening is a recorded `supersede` row — a window is never reopened
silently, only by a recorded act.

### The caller is wired where launches actually happen

`TaskScheduler.submit()` is **not** how the pipeline launches agents;
`GatedAgentRunner` calls `admits()` directly. A probe caller wired only
into `submit` would have left the reviewer, the fixer and the re-reviewer
going through a gate that never probes — the same defect, one level up.
`HoldGate` therefore carries `claim_probe`, and the runner uses it.

The probe holder is per **launch** (`task:stage:sequence`), never per
task or per stage: a convergence loop runs the same stage for the same
task repeatedly, and a reused identity would let a later round ride an
earlier round's probe. A shared identity is the defect this mechanism has
already been repaired for once.

`is_resume` is no longer required to match a probe holder. Once the
identity matches the durable row, the flag adds no restriction, while
requiring it means a caller that forgets it denies the probe its own
passage. A claim any caller could make was the original defect; an exact
identity is not that.

## Known limitations (stated, not implied)

- **The stampede is only prevented inside the lead window.** After an
  estimated `reset_at` passes, the hold is gone and admission is open to
  everyone, exactly as before. If no launch is attempted during `lead_s`,
  nothing probes. A busy system hits that window; an idle one has no
  stampede to prevent — but this is a mitigation, not a proof.
- **A claimed probe that never launches holds its lease.** If the claim
  succeeds and the immediately following admission check fails, the
  narrowing stands until `ttl_s`. Bounded, not zero.
- **A probing run slower than `ttl_s` is not stopped.** The lease expires
  and another probe may start while the first is still running, so two
  launches can overlap on the credential.
- **Failed probes retry at a constant rate, not exponentially.** A failed
  probe re-holds the account for the ordinary fallback window, so probing
  costs one launch per window rather than backing off.
- **No independent review.** Second consecutive unit.

## Self-review (no independent verdict available)

1. *(critical, repaired)* **The caller was wired to the wrong door.** The
   automatic probe went into `TaskScheduler.submit()`, which nothing in
   the pipeline uses — `GatedAgentRunner` gates on `admits()` directly.
   Fixing "a mechanism nothing calls" by adding a caller nothing reaches
   would have been the same defect wearing the repair's clothes. Found by
   grepping for who actually consumes the gate before writing the ADR.
   Mutation-checked.
2. *(critical, repaired)* **The probe inherited the window it replaced**,
   so at the only moment it was needed it wrote a hold that was already
   expired, or one that could never expire.
3. *(major, repaired)* **The claim was a check-then-append**, not a
   claim.
4. *(major, repaired)* **A successful probe was never read**, leaving the
   credential narrowed while the window was open.
5. *(major, corrected in the tests)* **A test that proved nothing.** The
   first concurrency test passed with the single-winner guard mutated
   away, because `probe_is_due` stopped the second caller before the
   contested step was ever reached — the race never materialised. It was
   restructured so every caller passes the due check *before* the
   barrier, and it now fails when the guard is removed. A green test over
   an interleaving that did not occur is worse than no test: it is
   evidence of a property nobody verified.
6. *(minor, corrected)* **A test comment that overclaimed.** The
   sequential five-run test was described as preventing a stampede; a
   failed launch re-holds the credential anyway, so sequentially there is
   none. The comment now says what the test shows and names the
   concurrent test that shows the rest.
