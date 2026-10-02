# F-33 Stage 2C-B0-R1 — Complete OS-Real Backend Wiring + Non-Privileged Qualification

Result: **PASS (pending narrow independent acceptance).** All privileged-path code
now EXISTS and is dry-qualified; Stage-2C-B1 requires only configuration +
authorization + execution. No Windows provisioning, no provider calls, no process
spawn, no F-17 change.

## Starting state / B0 gap
- Starting HEAD: `7d132cfd1fcb55c6aa9ca639ff750a3c8f405c3f`.
- Accepted B0 gap: the OS-real path required "wire OSREAL.base_provision to the
  real F-17 Provisioner" — i.e. part of the privileged path was unimplemented.
  This slice completes it so no substantial privileged orchestration remains.

## Deliverables (scripts/test only; NO src/gnosis change)
- `scripts/stage2cb.py` — the ONE orchestration graph + budget + journal +
  residue/recovery + preflight + route/env selection + `make_base_provision`
  (consumes the real F-17 `Provisioner`).
- `scripts/stage2cb_ops.py` — `DryOperations` (fake OS boundary, real filesystem)
  and `WindowsRealOperations` (the REAL guarded privileged backend).
- `scripts/probe_f33_stage2c_b_composed.py` — extended: `--simulate-b1` runs the
  SAME B1 graph with `DryOperations`; `--os-real` selects `WindowsRealOperations`
  (guarded → refuses without authorization). Also fixed a real staticmethod
  save/restore bug in the B0 dry-run (it had rebound `verify` as an instance
  method process-wide).
- `tests/test_stage2cb_backend.py` — 35 tests + 9 subtests (dry qualification).

## OSREAL backend consumes the real F-17 Provisioner (not reimplemented)
`make_base_provision(config, ops)` constructs the **real**
`gnosis.provision.provisioner.Provisioner(config, ops, publisher_files=f17 trust
closure, …)`, calls `.install(pw)` and returns
`BaseDeployment{deployment_digest = InstallResult.deployment_digest (OBSERVED,
not fabricated), rollback = Provisioner.uninstall()}`. All side effects flow
through F-17's own injected `Operations` protocol — F-17 owns F-17 semantics.
Verified in the dry run: `create_worker`, `protect_secret`, `sc.exe create`, and
`icacls …` calls are recorded as issued by `Provisioner.install()` through `ops`.

## One orchestration graph, injected backend (§6)
`Stage2CBOrchestrator.run()` is written once and parameterized by an
`OperationsBackend`. `DryOperations` and `WindowsRealOperations` both feed it; the
dry and real modes are the SAME control flow, differing only in the lowest-level
operations. `--os-real` selects the real backend, which is GUARDED
(`authorized=True` required) and refuses to construct in a non-authorized run.

## Complete privileged-operation inventory (§7) — all IMPLEMENTED
Worker create/delete + SID resolution (F-17 `ops.create_worker`/`delete_worker`/
`resolve_sid`), DPAPI (`ops.protect_secret`), runtime relocation + app deployment
(`Provisioner._deploy_code` + `GnosisDeploymentProvisioner`), ACLs (`Provisioner.
_apply_acls`/`_set_service_dacl` via `ops.run(icacls…)`), service create/config/
start/stop/delete (`Provisioner._install_service` + `WindowsRealOperations.
service_start`/`service_stop` + `sc.exe delete` in uninstall), pipe readiness
(`pipe_ready`), Worker launch (production `TrustedExecutionRunner` → F-17
`worker_launcher`, inside the operator), publication (`PipePublisherClient`),
ANCHORED observation (`observe_anchored` reads `TrustedRunIdentityStore`),
cleanup (F-17 `uninstall` + journal). **No TODO / pass-only / NotImplementedError
on the live path** (asserted by `test_no_unimplemented_on_live_path`; HBM14).

## Simulated B1 positive trace (§8, §28) — dry
`Stage2CBOrchestrator.run()` with `DryOperations` traverses:
`base_provision → composed_deployment → trusted_record → acls → service_start →
pipe_ready → route_selected → operator_launch → anchored_check → success`, then
finally-scoped rollback. Result: success (COMPLETED ∧ ANCHORED ∧ exit 0);
`canonical_launch(spawn=True)` encoded, process-creation seam intercepted;
`PipePublisherClient` selected; `PROVIDER_CALLS_REAL=0`; `OS_EFFECTS_REAL=0`;
rollback complete; `OS-REAL EXECUTION = NOT RUN`.

## Canonical launch / worker / reviewer / publisher call sites (§9,§11,§12,§13)
- `canonical_launch(comp, reobserve_f17, spawn=True)` is encoded in the graph; the
  argv is `python -I -B <measured operator_entry> run --brief <run_id>` and the
  spawn seam actually fires (HBM10 catches spawn=False).
- Route selection (`select_production_route`) asserts
  `PipePublisherClient` (never `InProcessPublisherClient`; HBM11),
  `ClaudeCLIRunner` reviewer (replay forbidden; HBM15 structural),
  worker path `TrustedExecutionRunner → gnosis.trust.worker_launcher` (HBM16),
  and an ABSOLUTE reviewer binary (relative → refused).

## Live-call budget (§10)
`LiveCallBudget(used, max_total=5)`: used=1→4 permitted, used=4→1, used=5→0,
used>5 invalid (fail closed). The orchestrator consumes exactly one call for the
governed live reviewer and refuses to launch when the budget is exhausted
(HBM7/HBM8). B0-R1 external calls: **0**.

## Transaction journal + rollback (§18–§21)
Every acquisition registers its cleanup BEFORE the next major operation
(f17-uninstall registered immediately after base; service-stop immediately after
start). Failure injection at each of the 9 orchestration stages → reverse cleanup
runs (post-base failure actually calls `delete_worker`; post-service failure calls
`service_stop`; HBM3/HBM4). Partial-acquisition failures inside F-17 install
(create_worker / service_start) fail closed without claiming cleanup for
un-acquired resources. Cleanup-failure injection (delete_worker / service_stop) →
`rollback_ok=False` with the residue reported, other cleanups still attempted
(HBM6). No false rollback PASS.

## Collision / residue / recovery (§22–§24)
Preflight fails closed on: not elevated, HEAD mismatch, F-17 not stable,
non-absolute reviewer, no budget, worker/service/root collision, owned residue
present, missing utilities. `ResidueManifest` (schema `gnosis.stage2cb.residue.v1`)
round-trips and parses fail-closed (truncated/corrupt/wrong-schema/extra-key).
`plan_recovery` returns a cleanup plan ONLY when ownership matches EXACTLY (HBM5);
unknown/mismatched ownership → refusal, no prefix-only destructive cleanup.

## Provider environment isolation (§25)
`worker_environment` strips `ANTHROPIC*/CLAUDE*/AWS*/OPENAI*` (HBM12); the Worker
never receives Claude auth/session state. `reviewer_environment` is a closed
allowlist (`SystemRoot,TEMP,TMP,USERPROFILE,APPDATA,LOCALAPPDATA,PATH,HOMEDRIVE,
HOMEPATH`) for the Director's live review call only (HBM2).

## H1–H20 (all PASS filesystem-only after R1)
H1 canonical composed provisioner used — PASS. H2 real F-17 Provisioner consumed —
PASS. H3 single orchestration graph (injected ops) — PASS. H4 provision-time gate
fail-closed — PASS. H5 trusted record outside tree — PASS. H6 pre-launch gate
(re-observe+re-measure+compare) — PASS. H7 startup self-verify — PASS. H8 one trust
tree (count=1) — PASS. H9 checkout independence — PASS. H10 shadow resistance —
PASS. H11 canonical launch spawn=True encoded — PASS. H12 PipePublisherClient
selected — PASS. H13 worker path = F-17 launcher — PASS. H14 reviewer route =
ClaudeCLIRunner (no replay) — PASS. H15 provider env isolation — PASS. H16 budget
enforcement — PASS. H17 transaction journal + rollback — PASS. H18 failure-injection
reverse cleanup — PASS. H19 collision preflight fail-closed — PASS. H20 residue
manifest + ownership-safe recovery — PASS.

## HBM1–HBM16 (§30)
APPLIED / CAUGHT (14): HBM1 (dry OS guard), HBM2 (reviewer env allowlist), HBM3
(account rollback registration), HBM4 (service rollback registration), HBM5
(unrelated-resource cleanup), HBM6 (rollback-failure ignored), HBM7 (provider
ledger reset), HBM8 (>5 calls), HBM10 (spawn=False), HBM11 (InProcessPublisher),
HBM12 (worker keeps secrets), HBM13 (bypass F-17 Provisioner / fabricated digest),
HBM14 (unimplemented live path), HBM16 (worker bypasses F-17 launcher).
STRUCTURAL (2): HBM9 (the graph uses the canonical `GnosisDeploymentProvisioner`;
manual glue is not present), HBM15 (the reviewer runs inside the operator
subprocess; the harness selects the production runner via the route and cannot
replace it with an always-PASS object). **No security-relevant survivor.**

## Remaining DEFERRED inventory (§32) — the exact B1 execution plan
Only facts that INHERENTLY require actual OS/live execution remain; NO
implementation items:
- observe the real Worker SID and Director-SID boundary;
- observe the real NTFS ACLs (worker denied write on record/manifest/entry/worker
  image/measured bytes; DPAPI blob unreadable);
- execute the real Worker (integrity level, Job Object containment, LaunchSpec seal);
- execute the real Publisher service + named pipe (PipePublisherClient E2E);
- execute the live reviewer (CliReviewer over ClaudeCLIRunner) — consumes L2..L5;
- observe persisted `PublicationState.ANCHORED` and operator exit 0;
- observe real service create→start→stop→delete and account create→delete lifecycle;
- N1–N6 live negatives, F33F live-pipeline mutants, CR1–CR3 recovery OS-real;
- §47 residue verification (ROLLBACK = PASS) after real provisioning.

## Tests / gates
- Backend: `tests/test_stage2cb_backend.py` — 35 passed, 9 subtests.
- Targeted (backend + operator_stack + gnosis_deployment): 83 passed, exit 0.
- HBM: 14/14 CAUGHT (2 structural).
- Full suite: see `full_suite.txt` (`PYTEST_EXIT_CODE` captured directly).
- `mypy --strict src`: Success, 88 files (production unchanged). Ruff (new
  harness/tests): clean.

## Guards
Provider calls = 0. Live Claude calls = 0. OS provisioning = NONE. Production
`src/gnosis` diff = NONE. `src/gnosis/trust/*` diff = NONE. Historical provisioner
+ Stage-6/8 probes = UNCHANGED. F-37 = NOT STARTED. NVIDIA/NIM = NOT PRESENT.
Cumulative live calls = 1 used / 4 remaining (L2 not consumed).

## Next
Narrow independent acceptance of the backend wiring. Only after PASS is
Stage-2C-B1 (the privileged OS-real run) authorized.
