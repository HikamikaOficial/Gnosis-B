# ADR-0004 — Canonical hash primitive, chained ledger, frozen transition tables

- Status: ACCEPTED
- Date: 2026-08-19
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_canonical.py`, `tests/test_ledger.py`
  (TestRunLedgerHashChain), `tests/test_state_machine.py`
  (TestTransitionTableHardening); suite 183/183; source directives in
  `docs/research/REFERENCE_REPOSITORY_FINDINGS.md` §1–§3.

## Context

The Tier-S archaeology found three near-universal mechanisms across the
strongest kernel references (bernstein, opentraces, agent-capsule,
reprise, agent-workspace-fabric, symphony): a single canonical-bytes
hash contract under every chain, an append-only hash-chained journal
with fail-closed recovery, and a single immutable transition allow-list
that every surface imports. The M0–M3 kernel already had append-only
JSONL ledgers and explicit state machines, but no hashing and mutable
transition dicts.

## Decisions

1. **`gnosis.kernel.canonical` is the only hash primitive.**
   `canonical_json_bytes = json.dumps(sort_keys=True, separators=(",",":"),
   ensure_ascii=False, allow_nan=False).encode("utf-8")`; every kernel
   hash is sha256 over those bytes. The contract is documented in the
   module and pinned by a re-derivable test vector. Future subsystems
   (replay keys, action identities, approval bindings) MUST reuse it —
   introducing a second encoding requires superseding this ADR.

2. **RunLedger events are hash-chained from a genesis anchor.** Each
   event carries `prev_hash` and `event_hash`; `append()` re-verifies the
   entire chain before extending it (never extend an unverified anchor).
   Torn final lines remain tolerated as crash evidence; interior
   malformation, sequence gaps, payload tampering, or chain breaks raise
   `LedgerCorruptionError` naming the line. Pre-chain ledgers stay
   readable as legacy evidence but refuse appends, and a chained event
   following a legacy prefix is rejected even with a plausible
   `prev_hash` (no laundering). O(n) verification per append is accepted
   at run-ledger scale; a checkpointed anchor is the designated
   optimization if that assumption breaks.

3. **Transition tables are `MappingProxyType` of frozensets**, and
   `IllegalTransitionError` carries `(current, target, allowed_next)` so
   every surface reports the same complete verdict without re-deriving
   rules.

## Consequences

- Any tampering with recorded run history is now detectable by
  recomputation, and refusing to extend corrupt chains makes laundering
  structurally impossible rather than merely discouraged.
- Old ledgers under `runs/` (pre-chain) are read-only evidence.
- The remaining Directive backlog (fenced leases as directive 4,
  provenance-gated worktree destruction as 5, etc.) builds on this
  primitive and is tracked in NEXT_ACTIONS.
