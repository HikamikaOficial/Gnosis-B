# ADR-0005 — Fenced, expiring lease plane (Directive 4, part one)

- Status: ACCEPTED
- Date: 2026-08-19
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_lease.py` (11 tests incl. deposed-holder denial and
  thread-contention single-winner); suite 194/194; mypy strict clean.
- Source directive: `docs/research/REFERENCE_REPOSITORY_FINDINGS.md` §4
  (two-plane ownership, evidenced by beads' CAS claims + lease plane and
  bernstein's fencing); MASTER_AUTONOMOUS_BUILD_DIRECTIVE §Leases.

## Decision

`gnosis.kernel.lease.LeaseStore`: assignment of a mutable resource is a
lease with `lease_id`, `holder`, monotonic `fencing_token`,
issue/expiry/heartbeat timestamps, persisted in one JSON file via
atomic_io under a FileLock (the kernel's established cross-process
pattern). Semantics:

- `acquire` grants only when no live lease exists; an expired lease is
  taken over with a strictly greater token. Renewal is exclusively
  `heartbeat`'s job — a second acquire by the *same* holder raises too,
  so double-acquire bugs surface instead of silently renewing.
- **Fencing tokens are monotonic across the resource's whole history**,
  surviving release/regrant (`last_tokens` retained), so any downstream
  consumer that tracks the highest accepted token can reject late writes
  from deposed holders.
- After expiry/takeover, every operation with the old `lease_id`
  (`heartbeat`, `assert_current`, `release`) raises `StaleLeaseError` —
  the NO STALE WRITE survival invariant, test-enforced.
- Injectable clock: expiry logic is deterministically tested without
  sleeps. Wall-clock expiry is an accepted V1 limitation (single
  workstation); revisit if the kernel ever spans hosts.

## Out of scope (tracked)

- The durable *claims* plane (task assignment as work-graph state that
  survives restarts, beads-style row-version CAS) — Directive 4 part two.
- Wiring `assert_current`/token checks into TaskEngine's write paths and
  the worktree lifecycle — lands with the claims plane.
