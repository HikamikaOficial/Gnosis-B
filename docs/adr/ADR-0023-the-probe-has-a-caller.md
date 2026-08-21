# ADR-0023 — The probe has a caller: testing a guessed window with one launch

- Status: ACCEPTED
- Date: 2026-08-21
- Evidence: `.gnosis/evidence/20260821T145030Z/` (711 passed, mypy strict
  clean over 54 files, ruff at the 19-finding baseline);
  `tests/test_scheduler.py::TestTheProbeHasACaller` (12 tests) and
  `tests/test_pipeline.py::TestTheProbeReachesThePathThatLaunches`.
- Independent review: **DONE 2026-08-21, verdict FAIL, 13 findings** —
  by an independent read-only agent in a clean context, **not by Codex**,
  whose usage limit stood. Two criticals. Nine repaired, four recorded as
  still open; see the addendum.
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

A probe SUSPENDS the hold it covers rather than replacing it; the
independent review found that replacing left an abandoned probe with a
wide-open, unprobeable credential (addendum finding 1).

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
  narrowing stands until `ttl_s` — after which the SUSPENDED hold
  governs again. (Before the independent review this said "bounded, not
  zero"; at the bound the credential was in fact wide open. See addendum
  finding 1.)
- **A probing run slower than `ttl_s` is not stopped.** The lease expires
  and another probe may start while the first is still running, so two
  launches can overlap on the credential. This description was written
  when it was optimistic rather than accurate — see addendum finding 1
  for what actually happened, and the repair that makes it true now.
- **Failed probes retry at a constant rate, not exponentially.** A failed
  probe re-holds the account for the ordinary fallback window, so probing
  costs one launch per window rather than backing off.
- **The independent review was not Codex** — a same-family reviewer
  shares blind spots a different model would not.
- **`_resolve_probe` is still check-then-act**, and four other findings
  remain open; they are listed at the end of the addendum rather than
  here so that what was FOUND stays next to what was claimed.

## Self-review (written before any independent verdict was available)

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

## Independent review addendum (2026-08-21, verdict FAIL, 13 findings)

The self-review above found six defects. The independent pass found
thirteen, **two of them critical, and both were misdescribed in this
ADR's own Known limitations** — which is the more useful fact: the gaps
were not unknown, they were understated.

1. *(critical, repaired)* **An abandoned probe left the credential wide
   open, and unprobeable ever after.** A `narrow` row DESTROYED the hold
   it replaced rather than suspending it, so when the probe lease expired
   there was nothing left: `reconcile` found no hold and admitted
   everyone, and `probe_is_due` — which needs an ACCOUNT hold to narrow —
   could never fire again. A mechanism whose failure mode is *more open
   than not having it* is worse than absent. Limitation #3 described this
   as "two launches can overlap"; the truth was unbounded, ungated
   launches. Reproduced, then repaired: a narrow now SUSPENDS, a live
   PROBE governs while it lives, and the suspended hold governs again
   when the lease expires. `HoldRegistry.reconcile` orders them by scope,
   not by restrictiveness, and the ordering is order-independent both
   ways round (pinned by test).
2. *(critical, repaired)* **The claim guarded the wrong predicate.**
   `narrow_if_unclaimed` made "only one claimant" atomic while leaving
   "there is still a hold worth probing" a check-then-act, so a provider
   window arriving between the two reads could be suspended by a stale
   claim — contradicting this ADR's promise that a provider window is
   never probed. Dueness is now re-validated inside the lock.
3. *(major, repaired)* **A timeout or a crash reopened the credential.**
   `observe` treated every non-`RATE_LIMITED` classification as "the
   probe came back clean". An absence of an answer is not an answer, and
   a safety mechanism fails shut: only `PASS` resolves a probe now.
4. *(major, repaired)* **`ttl_s < lead_s` was legal** and opened the
   credential *earlier* than not probing at all, while the constructor
   claimed the feature is strictly less permissive. Refused at
   construction.
5. *(major, repaired)* **The probe identity was guessable.** With
   `is_resume` no longer required, admission rested entirely on a string
   equal to the task id (or `task:stage:1`) — and asserting it IS
   admission. "A claim any caller could make was the original defect; an
   exact identity is not that" was only true while the identity was
   unguessable, and it never was. The holder is now the caller's name
   plus a secret minted inside the claim, which also removes the
   `_probe_seq` collision on the re-review path (finding 6).
6. *(major, repaired)* **`_probe_seq` reset per runner instance**, and
   the pipeline builds a fresh `GatedAgentRunner` per re-review — so
   every re-review of a task produced the identical probe identity,
   violating the invariant this ADR states as absolute.
7. *(major, repaired)* **With a `CredentialPool` configured, nothing
   probed at all.** Rotation parked before reaching the probe block, so
   the caller was dead again in exactly the configuration ADR-0024 adds
   — "the same defect wearing the repair's clothes", one level deeper.
   `select` failing now falls through to a probe pass over the allowed
   credentials.
8. *(major, repaired in the tests)* **The restructured concurrency test
   bypassed the production entry point.** It called
   `narrow_if_unclaimed` directly, so mutating `claim_probe` to drop the
   claim entirely left the whole suite green. This is the same category
   of defect the self-review claimed to have closed. The threaded test
   now races through `claim_probe`, and a store-level test keeps the CAS
   itself covered.

**Still open:**

- **`_resolve_probe`'s supersede is check-then-act**, and `supersede`
  drops every earlier row for the credential — so a provider hold placed
  between the read and the append is erased. The same argument that
  forced `narrow_if_unclaimed` to exist applies here and was not applied.
- **The unknown-window "new capability" targets a state no production
  path produces**: `hold_from_classification` always assigns a finite
  `reset_at`, so `reset_at is None` is only reachable by hand-placing a
  row. The branch is harmless but the claimed scope was inflated.
- **`test_only_one_gated_launch_gets_through_the_guess` runs no gated
  launch through the guess** — its `first` runner is constructed and
  never run. Two gated launches contending for one probe is still
  uncovered.
- **The mutation checks this ADR cites left no captured artifact.**

Evidence for the repairs: `.gnosis/evidence/20260821T170951Z/`.
