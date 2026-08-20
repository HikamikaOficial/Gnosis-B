# ADR-0006 — Durable claims plane + engine write-path fencing (Directive 4, part two)

- Status: ACCEPTED
- Date: 2026-08-19
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_claims.py` (25 tests), `tests/test_engine.py::TestTaskEngineWorkAuthority`
  (7 tests incl. mid-run deposition, deposed-retry refusal, slow-verifier
  survival); suite 239/239; mypy strict clean; multi-agent adversarial
  review run pre-commit (4 lenses, 18 raw findings → 6 confirmed + 4
  coverage gaps confirmed by self-verification; all repaired, see
  "Review outcome" below).
- Source: `docs/research/REFERENCE_REPOSITORY_FINDINGS.md` §4 (beads CAS claims,
  AWF fencing epochs, smithers in-transaction re-check, grit's two lessons);
  builds on ADR-0005 (lease plane).

## Decision

### `gnosis.kernel.claims.ClaimStore` — the durable ownership plane

Task ownership is a versioned, durable record (`TaskClaim`: holder,
status ACTIVE/RELEASED/RESOLVED/RECLAIMED, fencing `epoch`, CAS
`version`), persisted via the kernel's FileLock + atomic_io pattern with
a full per-task mutation history. Semantics, matching the directive
verbatim:

- Every ownership mutation is a CAS on `version` (mismatch → typed
  `StaleClaimError`); a same-actor retry of an ACTIVE claim is idempotent
  and moves neither version nor epoch (retrying is not a mutation).
- Fencing `epoch` increments per task inside the claim mutation itself
  and survives all status changes (`last_epochs`), so every grant is
  strictly ordered against every earlier one.
- Conflicts are typed data: `ClaimConflictError` carries the entire
  current claim.
- `reclaim_if(task_id, expected_version, predicate, reason)` is the TTL
  sweep primitive: the expiry predicate is re-evaluated under the claim
  store's lock at mutation time, and a skipped reclaim returns None (a
  sweep that finds nothing to do is normal, not exceptional).

### `WorkAuthority` — the two-plane facade

Acquire = durable claim first, then the ephemeral lease (lock order
claims→leases everywhere; LeaseStore never calls back, so no deadlock).
`assert_current` re-proves both planes. `resolve`/`release` end both.
`sweep` reclaims ACTIVE claims whose lease has expired. Lease liveness
(heartbeats, TTL) never enters claim history.

### Engine fencing

`TaskEngine.execute_task(authority=, worker_id=)` now: acquires the
grant before any state transition; re-proves ownership at attempt start
and — because the CLI run is the long deposition window — again after
the runner returns, *before* recording the outcome; heartbeats both the
run file and the lease from the runner's heartbeat callback, and on
deposition mid-run cancels the child process cooperatively instead of
leaking it, then aborts with the typed stale error before any durable
write (NO STALE WRITE at the write path, not by convention).

On verified success the claim is RESOLVED and the lease released in the
same authority call. On failure/cancellation the claim deliberately
stays ACTIVE — grit's lesson: never auto-release ownership of
unresolved work — and the lease is left to expire so the TTL sweep
produces an audited RECLAIMED transition.

## Review outcome and repairs (2026-08-20, pre-commit)

The adversarial review of the first version confirmed real defects, all
repaired before this unit was committed:

1. **Self-deposition after verified success (major).** The lease was only
   heartbeated inside the CLI loop; a verifier outliving the remaining
   TTL deposed a healthy worker after its work had passed verification.
   Fix: `GrantHeartbeatPump`, a background thread keeping the lease alive
   for the grant's whole lifetime (CLI, backoffs, verification, resolve),
   detecting deposition and cancelling the child cooperatively. Pinned by
   `test_slow_verifier_survives_via_pump` and
   `test_pump_detects_mid_run_deposition_and_cancels_child`.
2. **Renewals shrank the caller's TTL (major).** `WorkGrant` now carries
   `ttl_s`; every renewal honors it.
3. **Sweep vs acquire()'s claim-then-lease window (major).** "Never
   leased yet" was indistinguishable from "lease expired". Fix:
   `reclaim_grace_s` — claims mutated more recently than the grace window
   are never sweep-eligible.
4. **resolve()/release() non-atomic across planes (minor).** A lease that
   expired after the claim durably committed made completed work look
   failed. Fix: post-commit lease release absorbs `StaleLeaseError` only.
5. **Coverage gaps (4 findings, confirmed by self-verification after the
   review's verifier pass was cut short).** The pump path, the
   attempt-entry guard, each authority plane individually, and
   `WorkAuthority.release` are now each pinned by a dedicated test.
6. **Shared FileLock instance across threads (originally REFUTED by the
   review's verifier — wrongly).** The new pump tests crashed on
   `FileLock(...) is already held by this instance`: LeaseStore/
   ClaimStore/RunLedger held one FileLock instance for all operations,
   violating FileLock's one-instance-per-critical-section contract the
   moment a second thread (the pump) appeared. Fixed in all three stores
   (fresh FileLock per critical section; OS-level lock still serializes).
   See L-0004: a refuted finding is not a dead finding.

Also hardened while repairing: `atomic_write_text` absorbs transient
Windows sharing violations on `os.replace` with a bounded retry (the
L-0002 class, hit live by these tests under AV scanning).

## Accepted limitations (documented in code)

- Known benign race: a heartbeat can revive a lease concurrently with a
  sweep that already entered the claim lock; the claim is reclaimed, the
  holder's next guard fails loudly, no stale write lands, but in-flight
  work is interrupted. Acceptable at V1 sweep cadence.
- The orchestrator's BriefRecordStore claim check (M1-era, best-effort,
  single-process assumption) is NOT yet migrated onto WorkAuthority —
  tracked as the natural next step when the multi-task scheduler lands.
- Claims guard the engine's write paths; structural sole-writer
  enforcement inside RunStore itself (rejecting writes without a token)
  is deferred to the multi-process worker milestone.
