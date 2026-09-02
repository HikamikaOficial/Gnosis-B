# F-33 Stage 2C-B1-R2A — Publisher Startup / Pipe-Failure Diagnostics

Result: **PASS (pending narrow acceptance).** The B1 harness now emits structured
Publisher-pipe-failure diagnostics so the NEXT OS-real run can establish the actual
mechanism instead of a generic "pipe not ready". **Diagnostics/evidence plumbing
only — no OS provisioning, no provider calls, no topology/behavior/timeout change,
no `src/gnosis`/F-17 change.**

## Starting baseline / prior blocker
- HEAD: `609c25f5518bbaafcf8c49414fb130c9a529a916`.
- Second B1 OS-real run (pre-R2A): composed deployment + provision gate + ACLs +
  service create/start PASSED, canonical pipe name confirmed, automatic
  rollback/cleanup PASS, residual NONE — but `publisher pipe not ready` with only a
  boolean; **the failure mechanism was not establishable** (temp-path hypothesis
  unproven). See `second_run_trace_note.json`.

## §1 Publisher startup call graph (what must succeed before the pipe exists)
`sc create <svc> binPath="<runtime> -I -B <service_entry> <config.json>" obj=NT
SERVICE\<svc>` → service process launches (runs as the virtual service account) →
runtime imports `gnosis.trust.publisher_service` → `ServiceConfig.load(config.json)`
(schema check) → `recover_at_startup` → `PipeServer(config.pipe_name, sddl,
handler)` → `serve_forever()` → `CreateNamedPipeW(name)`. Any of these can fail with
only "pipe not ready" visible pre-R2A.

## §2/§3 Structured readiness result (exposed)
`WindowsRealOperations.pipe_ready` now records the full readiness diagnostics from
the (unchanged) `wait_pipe_ready`: `terminal_reason ∈ {ready, service-died, timeout,
observation-error}`, `expected_pipe`, `timeout_s`, `poll_interval_s`, `poll_count`,
`elapsed_s`, `service_running_observed`, `pipe_seen`, `observation_error`. Exposed
via `last_readiness()` and surfaced in `OrchestrationResult.pipe_readiness` +
the driver trace. Readiness DECISION and 15s timeout are unchanged.

## §4/§5 Service post-mortem (read-only, before rollback)
`service_postmortem(service_name, config)` (WindowsRealOperations) gathers, before
rollback: `scm_state` (from `sc query`), `service_running_observed`,
`service_exit_code` (Win32_EXIT_CODE), `effective_command` (F-17 `service_imagepath`,
non-secret), `runtime_exe_exists`/`service_entry_exists`/`config_path_exists`,
`deployment_root`, and `access_contract` (a read-only `icacls` probe: PASS if all
present required objects grant the service identity, FAIL if a present object omits
it, UNKNOWN if unparseable). SCM start-ack is recorded separately from process
health (`SCM START = ACCEPTED` vs `SERVICE RUNNING OBSERVED` vs `PIPE CREATED`).

## §9 Root-cause classifier
`classify_publisher_failure(readiness, postmortem)` → one of: RUNTIME EXECUTION
FAILURE / PUBLISHER CONFIGURATION FAILURE / DEPLOYMENT-ANCESTOR ACCESS FAILURE /
SERVICE PROCESS EARLY EXIT / SERVICE PROCESS START FAILURE / PIPE SERVER
INITIALIZATION FAILURE / READINESS OBSERVATION FAILURE / READY / AMBIGUOUS. It
**never** concludes an access/topology cause from a path string — only from an
observed `access_contract == "FAIL"` (guarded by a test + DM5).

## §6/§7 Access & Stage-8 topology comparison (read-only; NO change made)
- Current B1 root: `C:\Users\<user>\AppData\Local\Temp\gnosis-2cb-b1-<run_id>`
  (code/state/work all under one **user-profile temp** ancestor).
- Stage-8 qualified roots: `CODE_BASE=C:\Program Files\GnosisStage8Probe\Trust`,
  `STATE_BASE=C:\ProgramData\GnosisStage8Probe\Trust`,
  `WORK_BASE=C:\ProgramData\GnosisStage8Probe\Work` (Program Files + ProgramData,
  world-traversable, code/state on **different** system ancestors).
- Differences: ancestor ownership (user-profile vs system), service traversal
  (a restricted `NT SERVICE` account may lack traverse on a user-profile path),
  runtime/app location, code/state ancestor split.
- **Classification: `PLAUSIBLY INCOMPATIBLE`.** Per authorization, this is NOT
  turned into root cause. **DEPLOYMENT TOPOLOGY ROOT CAUSE = NOT-PROVEN.** The next
  OS-real diagnostic run (R2A-instrumented, behaviorally unchanged) must observe
  `access_contract` + `scm_state` + exit code to decide.

## §8 Local non-service execution diagnostic
Not run in this slice (would require constructing the service identity/environment
faithfully; a non-service local run would be `NOT AUTHORITATIVE`). Deferred to the
OS-real diagnostic run where the real service post-mortem is captured.

## §11 DIA1–DIA7 (+ guards) — all PASS
DIA1 service-dies→START FAILURE; DIA2 timeout+running→PIPE SERVER INIT; DIA3
observation-error→READINESS OBSERVATION FAILURE; DIA4 missing runtime→RUNTIME
EXECUTION FAILURE; DIA5 access FAIL→DEPLOYMENT-ANCESTOR ACCESS FAILURE; DIA6 missing
config→PUBLISHER CONFIGURATION FAILURE; DIA7 ready→READY. Plus early-exit→EARLY
EXIT; DM2-guard (timeout+not-running→START FAILURE); DM5-guard (temp path + access
PASS → NOT an access failure). Orchestrator capture test: pipe failure populates
`pipe_readiness` + `service_postmortem` + `publisher_failure_class` in the trace.

## §12 DM1–DM6 — all APPLIED / CAUGHT
DM1 collapse distinct failure→generic (DIA1); DM2 report RUNNING when stopped
(DM2-guard); DM3 omit exit-code influence (early-exit); DM4 report access PASS
without checking (DIA5); DM5 classify temp topology from path string (DM5-guard);
DM6 hide observation error (DIA3). **6/6 CAUGHT.**

## §13 R1/R1.1 regression (unchanged)
Canonical pipe `\\.\pipe\gnosis-s2cb-probe`; bounded readiness (15s/0.25s);
PBM1–PBM5 CAUGHT; automatic scaffold cleanup; RBM1/2/4 CAUGHT + RBM3 structural
(PBM/RBM harness: **8/8 applied CAUGHT, 1 structural**); failed-pipe automatic
residue NONE. The only R1 test touched was one brittle exact-string assertion on
the pipe error message, relaxed to a substring match (R2A enriches the message with
the failure class; behavior unchanged).

## Tests / gates
- R2A (`tests/test_stage2cb_b1_r2a.py`): 13 passed.
- Targeted (R2A + R1 + driver + backend + publisher client/pipe/service): 154
  passed, 80 subtests, exit 0.
- F-17 regression subset: 202 passed, 1 skipped, 53 subtests, exit 0.
- DM: 6/6 CAUGHT; PBM/RBM: 8/8 + 1 structural (regression).
- Full suite: see `full_suite.txt` (`PYTEST_EXIT_CODE` direct; known work_queue
  flake per historical policy).
- `mypy --strict src`: Success, 88 files. Ruff: clean.

## §10 Freeze
`src/gnosis` diff = NONE; `src/gnosis/trust/*` = NONE; `provisioner.py`/`layout.py`/
`winapi.py` UNCHANGED; Stage-5/6/7/8 probes UNCHANGED. No topology move, no ACL
loosening, no timeout increase, no DPAPI/Publisher-startup change. No BEHAVIOR
DEFECT discovered.

## Guards
`OS provisioning = NONE` · `provider calls = 0` · `live Claude calls = 0` ·
cumulative live calls = 1 / remaining 4 · F-37 NOT STARTED · NVIDIA/NIM NOT PRESENT.

## §18 Next step after R2A acceptance
ONE OS-real diagnostic retry using the newly-instrumented, behaviorally-unchanged
B1 path — its job is to answer WHY the Publisher never exposes the pipe (capture
`terminal_reason` + `scm_state` + `service_exit_code` + `access_contract`). Only
after that evidence may a topology/runtime/access remediation be authorized.
