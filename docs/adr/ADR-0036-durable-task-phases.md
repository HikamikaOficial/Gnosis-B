# ADR-0036 — Durable task phases and bounded proof recovery

Date: 2026-09-27
Status: implemented; targeted regression verified; final V1 qualification pending

## Problem

An interrupted brief previously retained files but could not resume its canonical
pipeline with the same task identity. A non-live resubmission allocated another
task, and a live record could remain stranded after process death. Initial
implementation attempts were attached to the parent only after the scheduler
returned. Convergence and proof capture also had gaps before their final records.

## Decision

The production deployment supplies `PipelineCheckpointStore` under the existing
protected trust-state root. The stored plan binds the exact brief, stable task,
deployment/repository configuration, verifier, reviewer attribution/adapter,
execution mode and convergence limits. Recovery never loads executable objects,
credentials or rules from disk. A closed, typed, bounded JSON codec preserves
verification, review, malformed evidence, attempts and observed launch records.
Immutable generations and compare-and-swap updates retain the prior complete
checkpoint if an update is interrupted. Missing/corrupt selectors fail closed.

The per-brief operation lock serializes callers. A new engine callback reserves
the initial attempt and durable budget before child launch. Its policy snapshot
also names the runner's actual fixed permission mode. Corrections retain their
own prelaunch reference and completion callback. Recovery reattaches the existing
worktree, never resets lifetime attempt/launch counts, and retains chronological
run references when a resumed implementation follows an interrupted attempt.

Convergence reserves each round before observation and saves a review before a
mutating fix. Resumption retains findings, malformed evidence, failure history,
flaky-verification history and stalemate counters. Interrupted rounds consume the
existing finite round budget. A completed review is reused only when the current
subject bytes still match; its display/proof copy is restored from protected
evidence if the preceding process died before writing it.

Proof capture has at most three persisted attempts. Each uses a distinct staging
directory and independent subject copy; failed evidence is retained. A protected
receipt records the verified digest before the sealed directory is finalized.
Recovery validates that external digest at either side of the rename, then uses
the existing publication checkpoint and Publisher reconciliation. It never
overwrites an unrecorded final bundle or trusts a resealed altered bundle.

Supervisor handler exceptions, quota/budget parks and invalid return values now
pass through the same deposition and fenced-transition handling as successful
returns. A replaced owner reports ownership loss instead of trying to decide the
new owner's work. This does not yet provide cancellation inside the whole handler.

## Evidence and limits

Tests recreate pipelines over real Git/worktree state; two kill a separate Python
process with `os._exit` during implementation/review. Other cases interrupt a fix,
exhaust attempts/rounds across restarts, change reviewed bytes, and stop before or
after proof receipts/finalization. Canonical graph tests use real Windows capture
and durable anchoring with an explicit fake Worker/provider and in-process
Publisher transport. They are not dedicated-account/provider qualification.

The supervisor replacement-owner matrix reproduced five failures before repair.
No production policy, evaluator, hidden test, baseline, security boundary or
authentication method was relaxed. A live-lease queue test now uses an injected
fixed clock: its original 50 ms wall-time assumption expired during legitimate
Windows disk writes. Expired-lease tests retain expiry checks.

Remaining: project CLI/scheduling, lease/cancellation across the full composition,
dependency-aware integration and recovery, interrupted-fix publication semantics,
fresh elevated deployment/provider qualification and the full V1 survival suite.
V1 and F-33 remain open.
