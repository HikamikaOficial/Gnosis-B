# ADR-0008 — Review-convergence loop (Directive 6)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_convergence.py` (16 deterministic tests); suite
  266/266; mypy strict clean; dual adversarial review pre-commit
  (multi-agent workflow + independent Codex — outcome recorded below).
- Source: `docs/research/REFERENCE_REPOSITORY_FINDINGS.md` §6 (ralphex
  convergence semantics + fingerprint stalemate, orca GateLedger +
  per-severity gates, cezar unbypassable park, agent-arena dissent
  preservation).

## Decision

`gnosis.kernel.convergence.ConvergenceLoop`: the kernel owns the
implement→verify→review→fix loop; reviewers and fixers are injected
callables (deterministic fakes in tests; Claude/Codex adapters later).

- **Signal ∧ evidence.** Convergence requires the deterministic
  verification to pass AND the independent review verdict PASS AND no
  blocking finding — with all three probes actually collected
  (`evidence_ok`). A fixer's `claims_done` over an unchanged repo
  fingerprint is downgraded to continue-with-warning.
- **Tri-state rounds.** Clean → CONVERGED; something to fix → fix_fn,
  then another independent round; `cannot_fix` → typed CANNOT_FIX exit.
  An UNCERTAIN verdict with nothing fixable schedules another
  independent round and, over an unchanging repo, runs into the
  stalemate breaker rather than looping.
- **Stalemate breaker.** Fingerprint = `hash_canonical({HEAD, status,
  diff})` (kernel.canonical — one hash contract, ADR-0004). N
  consecutive unchanged fingerprints → STALEMATE; the counter resets on
  change and never counts rounds whose fingerprint collection failed —
  a broken probe must not masquerade as a stuck repo (nor grant fresh
  rounds: a gap holds the baseline).
- **Nothing lost.** Findings below the blocking-severity set or the
  confidence floor are gated — carried in the ledger that rides on
  EVERY exit path — never dropped. Non-blocking findings present at
  convergence are preserved as dissent.
- **Bounded.** `max_rounds` is required and finite; exhaustion is the
  typed ROUNDS_EXHAUSTED outcome.

## Deliberate semantics (decided, not accidental)

- A clean round that would also trip the stalemate counter CONVERGES:
  verified success outranks a stuck-repo heuristic.
- Probe failures (verify/review/fingerprint raising) are data — a
  warning plus a non-convergent, non-stalemate-counting round — while
  `fix_fn` exceptions propagate raw: a crashing fixer is an agent
  failure for the caller's taxonomy (Directive 9) to classify.
- Convergence with a broken fingerprint probe is impossible by design
  (`evidence_ok` includes it): fail-closed, bounded by max_rounds.
- Reviewer read-only-ness is not enforceable at this layer (callables);
  it is enforced where reviewers get materialized (read-only sandbox
  adapters), per constitution rule 9.

## Also fixed here

`capture_git_evidence` recorded the literal string "HEAD" as `head_sha`
on commit-less repos (`git rev-parse HEAD` echoes the argument to
stdout); only a real 40/64-hex sha is recorded now.

## Review outcome and repairs (2026-08-20, pre-commit)

Dual adversarial review; all confirmed findings repaired before commit.

**Codex** (`exec --sandbox read-only --json`): FAIL, 3 findings, all
verified true:

1. Verify/review probe failures still advanced the stalemate streak —
   a broken probe could masquerade as a stuck repo. Repair: the streak
   counts only rounds with COMPLETE evidence.
2. Fingerprint gaps did not break streak consecutiveness (A, gap, A, A
   stalemated). Repair: a non-evidence round breaks the consecutive run
   entirely — streak and baseline; "N consecutive unchanged rounds" now
   means literally that.
3. A fail→pass verification flip on an unchanged fingerprint could
   converge on one lucky/gameable pass. Repair: flip detection — a pass
   contradicting an earlier fail on the same fingerprint must be
   reproduced in an independent round before convergence.

**Multi-agent workflow** (tests lens completed; other lenses cut by a
session limit and their 6 findings verified manually instead): all 6
confirmed — three surviving mutants (fingerprint leg of `evidence_ok`,
ledger carriage on STALEMATE/EXHAUSTED exits, `evidence_ok` gate on the
fix branch), the untested false-positive direction of the DONE-claim
warning, `git_fingerprint` raising on git timeout/OSError despite its
None-contract, and the silent (unwarned) None-fingerprint round. All
repaired: `_run_git` now fails closed on TimeoutExpired/OSError, a
returned-None fingerprint is warned like a raise, and eight new tests
pin every one of these points (tests 16 → 24).
