# F-33 Stage 2C-B1-R4A — Worker-Launch Failure Attribution

Diagnostics/attribution only. Surfaces the governed report's `problems_encountered`
(which already carries the F-17 failing call/stage + native winerr) through the
operator result, so a future OS-real run attributes the exact `WorkerLaunchFailed`.
**No F-17 change, no pipeline change, no remediation, governed BLOCKED preserved.**

## OS-real failure being attributed
R3E.1 run reached the real Worker-launch frontier: `work_status=BLOCKED`,
`detail="…(pipeline_error:WorkerLaunchFailed)"`, `operator_exit=3`. The Worker launch
was attempted but produced no running Worker.

## WorkerLaunchFailed archaeology (§3)
`src/gnosis/trust/worker_launcher.py:111` `class WorkerLaunchFailed(AuthorityUnavailable)`
(subclass `WorkerIdentityMismatch`). It stores NO separate winerr field, but **every
raise site embeds the failing call + native winerr in the message**, e.g.
`f"CreateProcessWithLogonW failed (winerr {ctypes.get_last_error()})"` (line 718),
`f"{call} failed (winerr {get_last_error()})"` (325), credential-unprotect (376/377),
identity (774/778), Job assign via `_winfail`/`AssignProcessToJobObject` (745).

## Exact launch stages (§4)
Per the launcher docstring/ops: `1 CreateProcessWithLogonW(…, CREATE_SUSPENDED)` →
credential unprotect → … → `8 AssignProcessToJobObject` → resume/identity check.
`CreateProcessWithLogonW` "needs no special privilege" (line 53); `LoadUserProfileW`
is deliberately NOT used (SeBackup/SeRestore dependency removed). Each failure raises
`WorkerLaunchFailed` with the failing API + winerr in the message.

## Info-loss point (§5)
`WorkerLaunchFailed(msg with winerr)` → `pipeline.py:257-259` catches it and calls
`_finish(BLOCKED, reason_code="pipeline_error:WorkerLaunchFailed",
problems=(f"{type(exc).__name__}: {exc}",))` → the winerr survives in
`PipelineOutcome.report.problems_encountered`. → `composition._finish` (non-COMPLETED
branch) built `OperatorOutcome(reason=…reason_code…)` and **dropped
`problems_encountered`** (OperatorOutcome had no `problems` field) → cli printed only
`detail`. **Classification: ERROR DETAIL PRESERVED (F-17 message + pipeline
`problems_encountered`) BUT NOT REPORTED (dropped at composition/cli).**

## Existing-evidence recovery (§6)
The last run's operator stdout carries only the summary (`reason`, no `problems`), so
the actual winerr is **not recoverable** from existing artifacts (composition dropped
it before printing; the deployment rolled back). → a diagnostic + one future OS-real
run are needed.

## Static root cause (§9) — NOT-PROVEN
The launch uses `CreateProcessWithLogonW` (logon as the worker + create process). The
exact winerr (e.g. 1326 bad-password / 1385 logon-type-denied / 1327 restriction / 2
missing-exe / 267 bad-cwd) is what distinguishes credential/privilege/path causes; it
is not statically derivable and was not captured. F-17's real launch is qualified "by
the OS-real probe" (not unit mocks), and the B1 composed-deployment launch input is
NOT identical to that probe — so the failure **does not yet contradict** F-17
qualification. → `STATIC ROOT CAUSE = NOT-PROVEN`.

## Minimal diagnostic (F-33 only, additive)
- `composition.OperatorOutcome` += `problems: tuple[str, ...] = ()`.
- `composition._finish` populates `problems=work.report.problems_encountered` in the
  governed-not-COMPLETED and no-launch branches (the failure paths).
- `cli._run` record += `"problems": list(outcome.problems)`.
The surfaced message contains the **failing call (stage)** and the **native winerr**
(§12/§13) verbatim; process-created vs post-create-failed is ENCODED in WHICH call
failed (§14). No token/privilege/credential/Job field is added because the F-17
message already names the failing operation and winerr — deeper capture would require
touching frozen F-17 (§23), which is NOT done.

## Governed BLOCKED preserved (§21) / no side effect (§22) / secrets (§29)
`success`/`work_status`/exit-code semantics are unchanged (the decision derives from
`work.status`); the diagnostic is a pure attr read that grants no privilege, retries
nothing, alters no LaunchSpec/ACL/token, and forwards `problems` verbatim (adds no new
source), so it cannot introduce credential material (`test_secret_safety…`).

## Tests (`tests/test_stage2cb_b1_r4a.py`, 6)
Stage+winerr surfaced; verbatim (no transform); governed BLOCKED preserved; empty
default; secret-safety; cli record includes `problems` with unchanged
`EXIT_WORK_FAILED`.

## WDM1–WDM10 (`mutation_harness_wdm.py`, `wdm.txt`)
**4/4 behavioral CAUGHT**: WDM1 drop native code, WDM2 transform/truncate, WDM4 hide
winerr in record, WDM8 skip governed-BLOCKED. **6 STRUCTURAL** (documented): WDM3
process-created encoded in the call name, WDM5 pure-read cannot suppress the decision,
WDM6 verbatim-passthrough adds no secret source, WDM7 no retry/fallback, WDM9 never
touches LaunchSpec, WDM10 F-17 freeze (worker_launcher.py diff 0). No meaningful
survivor.

## Freeze / scope
Changed: `src/gnosis/director/composition.py` + `src/gnosis/director/cli.py` (F-33
director), new `tests/test_stage2cb_b1_r4a.py`. **F-17 UNCHANGED** incl.
`worker_launcher.py` diff **0**. **R3D UNCHANGED** (`gnosis_deployment`/`operator_stack`
diff 0). **R3E reader UNCHANGED** (release_id/validator/DeploymentLayout untouched — 0
diff lines). **R3E.1 writer UNCHANGED** (`build_operator_config`/`OperatorConfigInputs`
untouched — the change is to `OperatorOutcome`/`_finish`). `pipeline.py` diff 0.
Publisher/pipe diff 0. (`freeze.txt`)

## Gates
- R4A 6 passed. Targeted (R4A+cli+composition+R3E.1+R3E+driver): 64 passed, 9
  subtests, exit 0. WDM 4/4; CWM/RIM/R3D guards intact.
- Full suite: `full_suite.txt` (`PYTEST_EXIT_CODE` direct; known work_queue flake
  governed separately).
- `mypy --strict src` Success, 88 files; ruff (changed) clean.

## Outcome / next
The worker-launch failure is now attributable: one OS-real diagnostic run on this
baseline will report `WorkerLaunchFailed: <failing call> (winerr N)` in the operator
`problems`, pinpointing the mechanism (credential / logon-type / path / privilege /
Job). Only after that winerr is captured may a remediation be designed. Do NOT change
F-17/R3D/reader/topology; do NOT close F-33.
