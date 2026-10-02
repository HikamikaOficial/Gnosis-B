# F-33 Stage 2C-B1 — Single OS-Real Diagnostic Run — Findings

Baseline HEAD `06b948a89ce73a0ebb76bdae3f6cb8e3dc6f483e`. ONE authorized OS-real
diagnostic execution, no remediation, no provider call. Result: the qualified
diagnostics **established the failure mechanism** — and it is NOT a proven Publisher
failure.

## Command
`PYTHONUTF8=1 .venv/Scripts/python.exe scripts/run_f33_stage2c_b1_osreal.py
--execute-os-real --confirm EXECUTE-F33-2CB1-OS-REAL --expected-head 06b948a…`

## What happened (evidence, `run_trace.json`)
- Stages reached: `base_provision → composed_deployment → trusted_record → acls →
  service_start`. Composed OS-real deployment + provision gate + ACLs + service
  create/start all succeeded (consistent with prior proven facts).
- **Service is RUNNING**: `scm_state=RUNNING`, `service_running_observed=true`,
  `service_exit_code=null` (the Publisher process did not exit).
- **Readiness terminated with `observation-error` on poll 1, elapsed 0.0s**:
  `pipe_seen=false`, `observation_error=true`, `poll_count=1`. The bounded readiness
  loop fail-closed on its **first** observation.
- Effective service command captured (non-secret): `"…\runtime\python.exe" -I -B
  "…\publisher\service_main.py" "…\state\config.json"`. Runtime, service entry, and
  config all exist.
- **Access diagnostic = UNKNOWN (honest)**: intended principal
  `NT SERVICE\GnosisPubS2CBProbe` resolved to SID
  `S-1-5-80-1811298702-…-893457846`, `intended_principal_rendered=true` on all three
  leaf objects, `ancestors_tested=false`, `grant_semantics_proven=false`,
  `deny_semantics_proven=false`. No authoritative denial; NOT reinterpreted as
  PASS/FAIL.
- `publisher_failure_class = READINESS OBSERVATION FAILURE`.
- L2 **not** consumed (failed before route/operator launch). Automatic rollback
  PASS; residual OS state **NONE** (`rollback_verification.txt`).

## Interpretation (evidence-bound; §6–§9)
The service is RUNNING and did not exit, yet the readiness probe **raised** on its
first poll — so `wait_pipe_ready` returned `observation-error` at t=0. The observation
method (`Path(r"\\.\pipe\gnosis-s2cb-probe").exists()`, from the R1 harness) throws on
a `\\.\pipe\…` path on this OS instead of returning True/False. **Therefore this run
never actually observed whether the Publisher exposed its pipe** — the "pipe not
ready" is, on this evidence, an **observation-method failure**, not a proven Publisher
initialization failure.

This reframes every prior B1 "publisher pipe not ready" result: with the qualified
diagnostics, the mechanism is `READINESS OBSERVATION FAILURE`, and whether the
Publisher genuinely created/served the named pipe is **UNDETERMINED**.

Per the qualified classifier and §7–§9 I do **not** invent a Publisher/access/pipe-init
diagnosis:
- `ACCESS CONTRACT = UNKNOWN` (not FAIL) — principal present, no deny, ancestors
  untested.
- Topology stays `PLAUSIBLY INCOMPATIBLE` — **DEPLOYMENT TOPOLOGY ROOT CAUSE =
  NOT-PROVEN**. Nothing here proves the temp topology is the cause.

## Root-cause classification
`PUBLISHER ROOT CAUSE = READINESS OBSERVATION FAILURE` (high confidence in the
mechanism: poll 1, elapsed 0.0, `observation_error=true`, service RUNNING).
**Limitation:** the run cannot conclude whether the pipe was actually exposed; that
requires a corrected observation method.

## No remediation performed
No topology / ACL / runtime / identity / pipe / timeout / DPAPI / Publisher / F-17
change. HEAD unchanged; `src/gnosis` diff = NONE; harness script hashes identical
pre/post. Evidence-only artifacts committed after the run.

## Exact next action (separately authorized; NOT done here)
Authorize a narrow **readiness-OBSERVATION fix** (harness/diagnostics only): replace
`Path(pipe_name).exists()` with a real named-pipe probe (e.g. a bounded
`CreateFileW`/`WaitNamedPipe` open that maps ERROR_FILE_NOT_FOUND → not-ready,
ERROR_PIPE_BUSY/success → ready), so the next OS-real run can positively determine
pipe availability. This is a diagnostic-observation correction — **not** a
topology/ACL/runtime/identity/timeout/F-17 change. Only after a corrected observation
can the true Publisher pipe state be established. Do NOT close F-33 on this run.
