# F-33 Stage 2C-B1-R4A.1 — Scoped Worker-Launch Diagnostic Surface

Replaces R4A's broad `problems` forwarding (which R4A acceptance FAILED as a
potential reviewer/provider/evidence leak) with a MINIMAL, DEDICATED, reason-scoped
field that exposes ONLY the single authoritative `WorkerLaunchFailed` attribution line
(failing WinAPI call/stage + native winerr). **No F-17 change, no pipeline change, no
WorkerLauncher change, no governance-semantic change, no OS-real execution.**

## R4A acceptance blocker being closed
R4A set `OperatorOutcome.problems = work.report.problems_encountered` and printed it in
the operator record. `problems_encountered` is a GENERAL governance/evidence channel:
its fallback producer `pipeline._problem_lines(convergence)` emits `finding.description`
(reviewer/provider-derived) and evidence `failure.message`. A post-review BLOCKED
outcome therefore forwarded reviewer/provider content through R4A's field →
`PROBLEMS OUTPUT SAFETY = FAIL`.

## Change (F-33 director only, additive)
- `composition.py`: `OperatorOutcome.problems` (tuple) **removed**; replaced by
  `worker_launch_diagnostic: str | None = None`. New module helper
  `_worker_launch_diagnostic(work)` + constants `_WORKER_LAUNCH_REASONS`,
  `_WORKER_LAUNCH_DIAG_MAX = 512`. `_finish` non-COMPLETED branch sets
  `worker_launch_diagnostic=_worker_launch_diagnostic(work)`; the no-launch (COMPLETED)
  branch no longer carries any problems field.
- `cli.py`: record key `"problems"` **removed**; replaced by
  `"worker_launch_diagnostic": outcome.worker_launch_diagnostic`.

## Exact activation gate (§5) — reason/type-bound
`_worker_launch_diagnostic` returns None unless `work.reason_code` is EXACTLY in
`{"pipeline_error:WorkerLaunchFailed", "pipeline_error:WorkerIdentityMismatch"}`
(the launcher exception class family; `WorkerIdentityMismatch` is a `WorkerLaunchFailed`
subclass). NOT `status == BLOCKED`, NOT `startswith("pipeline_error:")`, NOT any
substring of problem text. Proven by `test_other_pipeline_error_does_not_activate`
(§14), `test_false_positive_text_not_activated` (§18), WSD2, WSD3.

## Source-line selection (§6/§7) — single line, no reconstruction
Given the reason gate, the prefix is derived from the authoritative type
(`reason_code.split(":",1)[1] + ": "`) and the FIRST `problems_encountered` line with
that prefix is returned — the exact line the pipeline recorded as
`f"{type(exc).__name__}: {exc}"`. Never the whole list, never a convergence finding,
evidence message, or reviewer string. The Director invents/parses NO API, winerr
meaning, process-created state, or credential cause. Proven by
`test_multiple_problems_selects_only_launcher_line` / `_launcher_line_second` (§17),
`test_wrong_prefix_within_family_yields_none`, WSD1, WSD4, WSD8, WSD9.

## Bounded output (§8/§9)
`_WORKER_LAUNCH_DIAG_MAX = 512`. Every legitimate launcher message is short (winerr
forms ~55 chars; the longest legitimate case — a `WorkerIdentityMismatch` listing the
full dangerous-privilege set — stays well under 512). An over-cap line is REJECTED
(returns None) rather than truncated, so a trailing native winerr is never silently
dropped. Single string, no list, no traceback, no stdout/stderr/env dump. Serialized
by the existing `json.dumps` (no ad-hoc escaping). Proven by
`test_overlong_line_rejected_not_truncated`, `test_boundary_line_exposed`.

## WorkerLaunchFailed raise-site secret-safety re-audit (§10) — all SAFE
Every production raise site in frozen `worker_launcher.py`:
- `_winfail` (325) / CreateProcessWithLogonW (717-718) / AssignProcessToJobObject,
  OpenProcessToken, IsProcessInJob, ResumeThread, CryptProtectData (via `_winfail`):
  `"<WinAPI> failed (winerr N)"` — **SAFE** (API name + native code only).
- credential unprotect (376-379): `"the worker credential could not be unprotected
  (winerr N); it is missing, corrupt, truncated, or was protected on another machine"`
  — **SAFE**; raised only when `CryptUnprotectData` FAILED, so NO plaintext exists;
  no blob bytes.
- `_require_windows` (330), job-containment (751), no-launcher/test-fake (774/778),
  transport-command budget (652): static text / counts / a class name — **SAFE**.
- `WorkerIdentityMismatch` (592/596/600/607): SIDs, integrity level,
  `BUILTIN\Administrators`, privilege-constant names — identity metadata, classified
  separately per §10 (**SAFE**, no secrets/credentials/provider/reviewer content).

The password (`secret`/`password`) is held only in ctypes buffers passed to the WinAPI
and `del`-ed; it is NEVER formatted into any exception message. **No eligible message
includes a password, credential blob, decrypted material, environment contents, user
brief, provider output, or reviewer output.** Result:
`SAFE TO EXPOSE AS WORKER-LAUNCH DIAGNOSTIC` (with SID/username/privilege-name identity
metadata possible only on the `WorkerIdentityMismatch` family).

## Behavioral privacy assurance (§11-§14, §34) — replaces the old structural WDM6
`tests/test_stage2cb_b1_r4a1.py` proves, behaviorally, that reviewer (§11), provider
(§12), and evidence-failure (§13) sentinels are None in the field AND absent from the
serialized CLI record; other pipeline errors (§14) do not activate. The R4A WDM6
"structural — passthrough adds no new source" claim is RETIRED; the blocker is closed
by direct negative tests.

## Positives (§15/§16) & governance (§19/§20/§23)
`test_createprocess_positive` (winerr 1326) and `test_job_assign_positive` (winerr 5)
surface the exact API + winerr with `work_status=BLOCKED`. Success → None (§19).
Governed BLOCKED preserved: `success=False`, no verifier/reviewer/publication,
`EXIT_WORK_FAILED` unchanged (§20). CLI record omits `problems`, includes only
`worker_launch_diagnostic` (§23).

## WSD1-WSD10 (`mutation_harness_wsd.py`, `wsd.txt`) — 9/9 behavioral CAUGHT
WSD1 broad-forward, WSD2 any-pipeline-error, WSD3 substring-activation, WSD4
concatenate-all, WSD5 drop-winerr, WSD6 drop-API, WSD7 break-BLOCKED, WSD8
reviewer-content, WSD9 evidence-message — all CAUGHT. WSD10 (modify F-17) structural,
caught by freeze (`worker_launcher.py` diff = NONE). No meaningful survivor.

## Freeze / scope (`freeze.txt`)
`worker_launcher.py`, `pipeline.py`, `deployment.py`, `layout.py`, `winapi.py`,
`gnosis_deployment.py`, `operator_stack.py` — diff **0 each**. R3E.1
`build_operator_config`/`OperatorConfigInputs` and R3E release_id reader — **untouched**
(0 matching diff lines). Changed: `composition.py`, `cli.py`, `tests/…r4a.py`
(retained attribution under the scoped field), new `tests/…r4a1.py`.

## Gates
- Targeted (R4A.1 + R4A + operator_composition): 28 passed, exit 0 (`targeted.txt`).
  With `test_pipeline`: 80 passed.
- Full suite: `full_suite.txt` (direct `PYTEST_EXIT_CODE`).
- `mypy --strict src` Success, 88 files; ruff (changed) clean (`static_gates.txt`).

## Offline / next
`OS provisioning = NONE`, `provider calls = 0`, `live Claude calls = 0`, ledger `1/5`.
The OS-real Worker-failure attribution run is NOT executed here; after independent
R4A.1 acceptance it may be authorized ONCE to capture the real
`WorkerLaunchFailed: <API> failed (winerr N)` while preserving BLOCKED and rollback.
Do NOT change F-17/R3D/reader/topology; do NOT close F-33.
