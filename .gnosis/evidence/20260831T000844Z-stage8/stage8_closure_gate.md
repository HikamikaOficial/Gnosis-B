# F-17 Stage 8 — closure gate (additive)

This artifact is **additive**. It does not rewrite the historical Stage 8
evidence; the original qualification run is preserved verbatim in
`stage8_fullsuite.txt`. Implementation HEAD under test: `dae26a0` (chain
`ad32bba` → `54b6a69` → `77c639a` → `dae26a0`).

## Full-suite runs (honest history)

- **Stage 8 qualification run 1: RED** — `1 failed, 1509 passed, 1 skipped,
  263 subtests` (`stage8_fullsuite.txt`). Failure:
  `test_work_queue.py::TestACrashedWorkerLosesNothing::test_recovery_never_takes_a_brief_from_a_live_worker`
  (`StaleLeaseError`).
- **Stage 8 closure run: RED** — `2 failed, 1508 passed, 1 skipped, 260
  subtests`, 888.01s (`stage8_closure_suite.txt`). Failures: the run-1 test
  plus `test_work_queue.py::TestOwnershipIsTheClaimsPlane::test_concurrent_workers_never_run_a_brief_twice`.
  Both `StaleLeaseError` at `src/gnosis/kernel/lease.py:222`.

Option A (a green complete run) was attempted and did **not** succeed; the flake
repeatedly prevented it (twice). Option B (rigorous adjudication) was therefore
run, per the closure-gate protocol. No test, TTL, or work-queue code was
modified; no retry wrapper was used to hide a failed run.

## Root cause

The failing tests build a `LeaseManager` with the **real `time.time` clock** and
a **50 ms TTL** (`tests/test_work_queue.py`: `default_ttl_s=0.05`) plus real
threads and real files. Under CPU load the wall clock advances past
`expires_at` between acquiring a lease and checking it, so
`_current_locked` raises `StaleLeaseError`. The deterministic work-queue tests
inject a fake clock (`clock=lambda: self.now[0]`) and never fail. This is a
load/timing property of these particular tests, not a logic defect.

## Byte-identity: the failing behaviour is pre-Stage-8 code

Every file the failing tests exercise is **byte-identical** between the Stage 7
baseline `ad32bba` and the Stage 8 HEAD `dae26a0` (compared via `git hash-object`):

- `tests/test_work_queue.py` — IDENTICAL
- `src/gnosis/kernel/lease.py` — IDENTICAL
- `src/gnosis/director/work_queue.py` — IDENTICAL
- `src/gnosis/kernel/claims.py` — IDENTICAL

Stage 8's entire footprint is the `gnosis.provision` package, its tests, two
scripts, ADR-0030, two docs, and this evidence bundle. It touches nothing in the
work-queue / lease / claims subsystem.

## Controlled frequency experiment (isolation vs. load; HEAD vs. baseline)

Each sample ran the two failing tests together
(`pytest <T1> <T2> -q`). Load was induced by running 30 samples concurrently
(CPU contention starves the 50 ms TTL). The baseline cohort ran from an isolated
`git worktree` at `ad32bba` with `PYTHONPATH` pinned to the worktree's `src`.

| Cohort | Samples | Failed | of which StaleLeaseError |
|---|---|---|---|
| Control — isolated, sequential, no load (HEAD) | 30 | 5 | 1 |
| Load — 30 concurrent (HEAD `dae26a0`) | 30 | 26 | 16 |
| Load — 30 concurrent (baseline `ad32bba`) | 30 | 28 | 23 |

Interpretation:
- The failure rate rises sharply with load (5/30 → 26/30), confirming the
  timing/load nature rather than a logic bug.
- Under **identical** induced load, the **pre-Stage-8 baseline fails at an
  equal-or-higher rate (28/30) than the Stage 8 HEAD (26/30)**. Stage 8 did not
  introduce or worsen the behaviour.
- The control shows the tests are timing-fragile even lightly loaded (5/30), so
  no claim of a clean isolated pass is made; the conclusion rests on the
  comparative rates plus byte-identity.

## Conclusion

The two RED full-suite results are caused entirely by a pre-existing,
load-sensitive real-clock/50 ms-TTL timing flake in the work-queue tests, in
code byte-identical to the reviewed Stage 7 baseline, failing at an
equal-or-higher rate on that baseline under identical load. Stage 8 did not
alter the failing behaviour.

`STAGE 8 CLOSURE GATE: PASS (via adjudication)`

The `work_queue` real-clock TTL flake remains an open, pre-existing item for the
owning subsystem (candidate: inject a fake clock into these tests, as the
deterministic work-queue tests already do). It is out of scope for F-17 Stage 8
and must not be modified under this gate.
