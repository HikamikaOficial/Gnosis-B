# F-33 Stage 2C-B1-R2B — Access-Diagnostic Truthfulness Remediation

Diagnostics/test/evidence only. **No topology / ACL / service-identity / runtime /
pipe / timeout / F-17 change; no OS provisioning; no provider calls.** Remediates
the sole R2A acceptance blocker: `ACCESS DIAGNOSTIC = OVERCLAIM`.

## R2A acceptance blocker (carried in)
`F-33 Stage 2C-B1-R2A FINAL ACCEPTANCE = FAIL`, sole blocker
`ACCESS DIAGNOSTIC = OVERCLAIM`: `_access_contract` emitted authoritative
`PASS`/`FAIL` from weak **leaf-object `icacls` substring** evidence — a generic
`NT SERVICE` substring (e.g. `NT SERVICE\TrustedInstaller`) yielded `PASS` for the
Publisher principal, a missing friendly name yielded `FAIL`, and leaf ACLs were
treated as proof of ancestor traversal. The docstring claimed "grant the service
identity R/RX" though the code verified no grant.

## §3 Old access-diagnostic semantics (removed)
`_access_contract(config) -> str`: for the 3 leaf objects (runtime exe, service
entry, config) ran `icacls`; returned `FAIL` iff neither `service_name` nor the
substring `"NT SERVICE"` appeared; else `PASS`; `UNKNOWN` only if `icacls` errored.
No ancestor test, no grant/deny parse, no principal resolution → authoritative
labels the evidence did not justify.

## §4 New access-diagnostic semantics (conservative)
`_access_contract(config) -> tuple[str, dict]` (aggregate + raw sub-signals):
- resolves the **intended** principal `NT SERVICE\<service>` and, best-effort
  read-only, its SID via F-17 `resolve_sid`;
- per existing leaf: `icacls`; records `intended-principal-present` /
  `-not-rendered` / `-denied` (a `(DENY)` ACE on a line naming the intended
  principal **or** its resolved SID);
- **`FAIL`** — emitted **only** on a proven `(DENY)` ACE for the intended principal
  (`verdict = DIRECTLY-DENIED`, `deny_semantics_proven = True`);
- **`PASS`** — **never emitted** by the real backend: leaf `icacls` cannot prove
  grant semantics or ancestor traversal, so a positive contract is not asserted;
- **`UNKNOWN`** — everything else, with sub-signals
  `intended_principal_rendered`, `leaf_acls_inspected`, `ancestors_tested=False`,
  `grant_semantics_proven=False`, `deny_semantics_proven`, `resolved_sid`.

Method self-labelled `ACL-BASED INFERENCE (leaf objects only)`. Uncertainty is
represented honestly; false certainty is not produced.

## §6 Ancestor scope
Only leaf objects are inspected; `ancestors_tested` is always `False` and no
full-deployment/ancestor-access `PASS` is ever claimed. A genuine ancestor-traversal
proof is deferred (would need a stronger, identity-specific check); until then the
honest value is `UNKNOWN`.

## §5/§7 Classifier contract (tightened)
`classify_publisher_failure` now reaches `DEPLOYMENT/ANCESTOR ACCESS FAILURE` only
via `_authoritative_access_failure(postmortem)`, which requires
`access_contract == "FAIL"` **and** (when a detail is present) a proven deny
(`deny_semantics_proven` / `DIRECTLY-DENIED`). `UNKNOWN`, weak ACL inference, a
missing friendly-name substring, or a temp-path can never drive an access failure.
When the service is not-running/died, runtime+config exist, access is not
authoritatively denied, **and the exit code is unknown**, the classifier now
returns `AMBIGUOUS` (it refuses to invent `SERVICE PROCESS START FAILURE` without an
authoritative discriminator). An authoritative exit code (0 → start failure, ≠0 →
early exit) still classifies as before.

## §8 access_contract PASS never excludes other causes
Because the producer never emits `PASS`, an access signal can no longer be used as a
decisive negative discriminator against runtime/config/DPAPI/startup causes.

## §9 Docstring / evidence correction
The inaccurate "grant the service identity R/RX" wording is removed; the producer
and this bundle describe only measured evidence. The historical R2A bundle is left
intact; this bundle records that **R2A's access diagnostic overclaimed PASS/FAIL**
and documents the correction.

## §10–§14 Direct tests (`tests/test_stage2cb_b1_r2b.py`, 11)
- **TrustedInstaller false-PASS** — `NT SERVICE\TrustedInstaller` present, Publisher
  absent → `UNKNOWN`, `intended_principal_rendered=False` (not PASS).
- **Friendly-name-absence false-FAIL** — intended principal not rendered, no deny →
  `UNKNOWN` (not FAIL).
- **Leaf-only** — intended principal `(RX)` on every leaf → `UNKNOWN`,
  `ancestors_tested=False`, `grant_semantics_proven=False` (no ancestor PASS).
- **Authoritative failure** — explicit `(DENY)` for the intended principal → `FAIL`,
  `verdict=DIRECTLY-DENIED`; also proven via resolved **SID**.
- **temp-path / icacls-error** → `UNKNOWN`, never FAIL.
- **UNKNOWN classifier** — `UNKNOWN` access + unknown exit → `AMBIGUOUS`, never
  access failure (also with a temp `deployment_root`).
- **Weak-FAIL gated** — `FAIL` with a non-authoritative detail does not drive access
  failure; a `DIRECTLY-DENIED` detail does.

## §15 Producer mutants ADM1–ADM6 — all CAUGHT (`mutation_harness_adm.py`)
ADM1 any-`NT SERVICE`→PASS; ADM2 friendly-name-absence→FAIL; ADM3 leaf-grant→full
ancestor PASS; ADM4 `UNKNOWN`→access root cause (classifier); ADM5 ignore explicit
deny; ADM6 temp-path→FAIL. **6/6 CAUGHT** (`adm.txt`).

## §16/§17 DIA & R2A diagnostic regression
DIA1–DIA7 remain valid; **DIA5 fixture updated** to inject an authoritative denial
(`verdict=DIRECTLY-DENIED`) per the new producer contract — the semantic requirement
(access FAIL → `DEPLOYMENT/ANCESTOR ACCESS FAILURE`) is unchanged. Readiness
`terminal_reason`/bounds, service state, exit code, effective command,
runtime/config existence, postmortem-before-rollback ordering, rollback-on-error,
canonical pipe, and automatic cleanup are all unchanged. DM1–DM6 re-anchored for the
R2B classifier (`mutation_harness_dm_r2b.py`) = **6/6 CAUGHT** (`dm_r2b.txt`). The
historical R2A DM harness reports `DM4: NOT APPLIED` because the weak
`access_contract == "FAIL"` line it targeted was replaced by the stronger
`_authoritative_access_failure` gate — an improvement, not a regression.

## §18 Topology hypothesis (unchanged)
`DEPLOYMENT TOPOLOGY ROOT CAUSE = NOT-PROVEN`; B1 user-temp vs Stage-8
Program Files/ProgramData remains `PLAUSIBLY INCOMPATIBLE`. No topology remediation.

## §19 Source freeze
Changed: `scripts/stage2cb.py`, `scripts/stage2cb_ops.py`, `tests/*` only.
`src/gnosis` diff = **NONE**; `src/gnosis/trust/*` = **NONE**;
`provisioner.py`/`layout.py`/`winapi.py` **UNCHANGED**; Stage-5/6/7/8 probes
**UNCHANGED** (`freeze_and_diff.txt`). No production/F-17 change was required.

## Tests / gates
- R2B: 11 passed. R2B+R2A+R1: 40 passed. Targeted (R2B+R2A+R1+driver+backend):
  109 passed, 18 subtests, exit 0 (`targeted.txt`).
- Publisher client/pipe/service: 56 passed, 62 subtests, exit 0.
- F-17 (provisioner + layout): 27 passed, exit 0 (`f17_regression.txt`).
- Full suite: 1778 passed, 1 skipped, 313 subtests; **1 failed** = the historical
  `test_work_queue.py::...::test_concurrent_workers_never_run_a_brief_twice`
  concurrency flake — `PYTEST_EXIT_CODE=1` is reported RED, not masked. Re-run in
  isolation **3/3 PASSED**; R2B touches no `work_queue` code (and no `src/gnosis`),
  so this is not an R2B regression (`full_suite.txt`, `full_suite_classification.txt`).
- `mypy --strict src`: Success, 88 files; ruff (changed): clean (`static_gates.txt`).

## Guards
`OS provisioning = NONE` · `provider calls = 0` · `live Claude calls = 0` ·
cumulative live calls = 1 / remaining 4 · topology root cause NOT-PROVEN.

## Outcome
Access diagnostic is now truthful: no false authoritative PASS/FAIL, no ancestor
overclaim, `UNKNOWN` honest, and the classifier cannot turn `UNKNOWN` into an access
root cause. **F-33 Stage 2C-B1-R2A is READY FOR FINAL RE-ACCEPTANCE.** B1 OS-real
diagnostic retry remains NOT authorized.
