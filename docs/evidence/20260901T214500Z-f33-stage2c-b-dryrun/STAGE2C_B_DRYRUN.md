# F-33 Stage 2C-B — Composed Qualification: Build + Dry-Run Checkpoint

Result: **DRY-RUN PASS; OS-REAL NOT RUN (checkpoint).** Per the authorizer's
selected option ("Build + dry-run, checkpoint"), this slice constructs the
composed OS-real qualification harness and validates everything achievable
**filesystem-only** — no Windows provisioning, no Worker account, no Publisher
service, no named pipe, no DPAPI, no provider/live-Claude calls — then STOPS
before the privileged/billed portion. F-33 Stage 2C-B remains **NOT RUN** for the
OS-real authoritative parts.

## Why a checkpoint (the finding that prompted it)
There is **no existing OS-real composed qualification harness**. `GnosisDeployment
Provisioner` has no production/probe `base_provision` wiring, and no script
referenced the R2 pieces (`canonical_launch`, trusted composed record, live
`CliReviewer`, `PipePublisherClient`). The existing OS-real harness
(`scripts/probe_stage8_provisioning.py`) provisions real F-17 accounts/services
but drives the OLD Stage-6 composition, not the R2 composed model. Executing a
first-run privileged harness that creates real OS accounts/services on the user's
actual workstation and spends the live-call budget cannot guarantee the §47
no-residue property, so the authorizer chose to build + dry-run and checkpoint.

## Preconditions verified (read-only)
- Shell elevation: `net session` succeeds (Administrator context available).
- `claude` CLI present: v2.1.252 at `C:\Users\nicol\.local\bin\claude.exe`.
- Neither was exercised for provisioning or billed calls in this slice.

## Deliverable
`scripts/probe_f33_stage2c_b_composed.py` — the composed Stage-2C-B harness, with
two modes:
- **DRY-RUN (default):** a filesystem `base_provision` simulates the F-17 base by
  copying the trust-plane closure into the canonical package root (exactly as
  `f17_publisher_files` hands it to the real F-17 Provisioner), then drives the R2
  composed model end to end.
- **OS-REAL (`--os-real`):** intentionally **guarded** — it refuses to run until a
  privileged `base_provision` (real F-17 Provisioner via the Stage-8 machinery) is
  wired, so no first privileged run can happen by accident (verified: it prints
  the guard and provisions nothing).

## Dry-run result — 17 PASS · 0 FAIL · 13 deferred
Composed model wiring validated filesystem-only:
- **PROVISION-TIME gate** — returns a verified `ComposedDeployment`; trusted record
  written OUTSIDE the package tree (`state_base/GNOSIS_COMPOSED.json`); record
  binds app + F-17 digests; gate is fail-closed (injected final-verify failure →
  provision raises + rollback).
- **PRE-LAUNCH gate** — `canonical_launch` emits `python -I -B <entry> run --brief
  demo`; refuses an application byte tamper; refuses an F-17 re-observation
  mismatch.
- **STARTUP gate** — the deployed measured `operator_entry.py`, run under a real
  interpreter `-I -B`, self-verifies and reaches `cli.main` (rc≠70) on a valid
  tree; aborts with exit 70 on a one-byte entry tamper; aborts with exit 70 on a
  coherent app+manifest tamper (record unchanged).
- **ONE TRUST TREE** — `TRUST COPY COUNT = 1`; Director + trust modules resolve
  under the one package root; no source-checkout path in resolution; CWD shadow
  resisted under `-I`.
- Gate summary: `PROVISION-TIME=PASS`, `PRE-LAUNCH=PASS`, `STARTUP=PASS` (dry-run).

Full console + JSON: `dryrun.txt`, `dryrun_report.json`.

## OS-REAL steps intentionally DEFERRED (each with its exact production symbol)
1. `OSREAL.base_provision` — privileged F-17 `Provisioner` (Stage-8 machinery) →
   `BaseDeployment{observed deployment_digest, F-17 uninstall rollback}`.
2. `OSREAL.worker_account_sid` — temporary non-admin Worker account + SID boundary
   vs Director SID.
3. `OSREAL.acls` — NTFS ACLs: Worker cannot write the trusted record /
   `APPLICATION.json` / `operator_entry.py` / `deterministic_worker.py` / measured
   bytes.
4. `OSREAL.canonical_launch_spawn_true` — `canonical_launch(spawn=True)` →
   deployment-bound `python -I -B operator_entry` → `gnosis.director.cli:main`.
5. `OSREAL.real_worker_boundary` — `TrustedExecutionRunner` →
   `TrustedExecutionPort` → F-17 `worker_launcher` → real Worker (SID, integrity,
   Job containment, LaunchSpec seal).
6. `OSREAL.verifier` — production governance verifier PASS + fail-closed negative.
7. `OSREAL.live_reviewer` — `adapters.cli_review.CliReviewer` over
   `runner.claude_cli_runner` LIVE — consumes L2..L5 (≤5 cumulative).
8. `OSREAL.real_publisher` — `director.publisher_client.PipePublisherClient` → real
   named pipe → F-17 Publisher service (no `InProcessPublisherClient` fallback).
9. `OSREAL.anchored` — `create_trusted_run` → `authorize_publishable` → `PUBLISH` →
   persisted `PublicationState.ANCHORED` → operator exit 0.
10. `OSREAL.negatives_N1_N6` — worker fail / reviewer refuse / verifier fail /
    publisher unavailable / identity mismatch / not-anchored → operator non-zero.
11. `OSREAL.mutation_matrix_F33F` — F33F-1..12 against the live composed pipeline;
    the composed-identity mutants are already covered filesystem-only by the R2
    E-M table, the pipeline mutants require OS-real.
12. `OSREAL.recovery_CR1_CR3` — completed-not-committed / committed-not-observed /
    service-restart reconciliation via existing F-17 mechanisms.
13. `OSREAL.rollback_and_verify` — finally-scoped uninstall + §47 residue
    verification → `ROLLBACK = PASS`.

## Guards (this slice)
Provider calls = 0. Live Claude calls = 0. OS provisioning = NONE (verified: no
`Gnosis*` Worker account or Publisher service exists post-run). Cumulative live
calls = 1 used / 4 remaining (L2 NOT consumed). `src/gnosis` production diff =
NONE. `src/gnosis/trust/*` diff = NONE. Historical provisioner byte-stable.
F-37 = NOT STARTED. NVIDIA/NIM = NOT PRESENT.

## Remaining work before an authoritative OS-real PASS
Wire `OSREAL.base_provision` to the real F-17 `Provisioner` (Stage-8 machinery)
returning a `BaseDeployment`, then run `--os-real` under explicit authorization to
execute items 2–13 with a live reviewer (L2+) and full finally-scoped rollback +
residue verification. Estimated one bounded live call (L2) for the positive E2E if
the reviewer returns a clean PASS; negatives N1/N3/N4/N5/N6 and F33F pipeline
mutants use failure injection (no live calls); N2 reviewer-semantic negative may
use one further bounded call (L3) if a genuinely live refusal is required.

## Next
STOP for the authorizer's go-ahead on the privileged/billed OS-real run (or a
dedicated wiring slice for `OSREAL.base_provision`). F-33 stays OPEN; Stage-2C-B
NOT YET QUALIFIED.
