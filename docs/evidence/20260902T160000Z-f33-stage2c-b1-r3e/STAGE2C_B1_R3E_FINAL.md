# F-33 Stage 2C-B1-R3E — Canonical Release-Id Plumbing

Smallest sound F-33-only correction so the deployed operator reconstructs the EXACT
authoritative deployment layout — including the real `release_id` — from the trusted
config. No `"current"` default on the production route, no hardcoding, arbitrary valid
release IDs, fail-closed on missing/invalid. R3D semantics, F-17, Publisher/pipe,
topology all unchanged.

## Historical OS-real failure (carry-in)
The R3D run launched the operator; it then failed in `cli.build_operator_composition`
→ `observe_deployment` → `_assert_executable_inside_runtime_root` →
`CreateFileW(...\code\releases\current\runtime)` winerr 3 (PATH_NOT_FOUND). The layout
was rebuilt without `release_id` (defaulting `"current"`) while the qualified release
was `B1`.

## Exact root cause
`cli.py:build_operator_composition` did `DeploymentLayout(code_base=dep["code_base"],
state_base=dep["state_base"], work_base=dep["work_base"])` — **`release_id` omitted →
default `"current"`** → `layout.runtime_root = code_base\releases\current\runtime`. The
trusted operator config's `deployment` section carried `code_base/state_base/work_base`
but not `release_id`.

## release_id data-flow (§3, §5)
- Origin: the B1 driver's `DeploymentLayout(..., release_id="B1")`
  (`run_f33_stage2c_b1_osreal.py`), staging code under `code_base\releases\B1\`.
- The driver's `build_operator_config` writes the trusted operator config's
  `deployment` section — it previously omitted `release_id`.
- `cli.build_operator_composition` reads that section to rebuild the layout — where
  `release_id` was lost.
- The composed record's `package_root` (`...\releases\B1\publisher`) and the R3D
  identities already bind the release *path*; but the operator's own layout
  reconstruction reads the operator config, not the composed record.

## Canonical authority (§4, §7)
The **trusted operator config's `deployment.release_id`**, written by deployment
authority and read through the protected production config path — the SAME authority
and artifact that already supplies `code_base/state_base/work_base` (equal trust
level, no new surface). It is explicit (not path-heuristic, §5), created by deployment
authority, worker-denied, uniquely identifies the release, agrees with the staged
paths, is checkout-independent, generalises to any release name, and is never
supplied by a brief/env/cwd/default (§6).

## Already bound by R3D? Schema change? (§8, §13, §14)
The release path is already indirectly bound in the R3D composed identity via
`package_root`/measured paths (`releases\B1`), and R3D `canonical_launch` verifies that
composition BEFORE the operator runs. So **no ComposedRecord v2 schema change is
required** — R3D binding untouched. R3E only plumbs the already-authoritative
`release_id` from the trusted config into the operator's own layout reconstruction.

## Fix (§8, §11, §12)
- `cli.py`: read `dep["release_id"]` (missing → existing `KeyError → OperatorError,
  EXIT_USAGE`; **no `"current"` fallback**), validate it against `_RELEASE_ID_RE =
  ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` (a single safe path segment — no dot/separator/
  drive/traversal), and pass it to `DeploymentLayout(..., release_id=release_id)`.
  Invalid → `OperatorError, EXIT_USAGE`.
- `run_f33_stage2c_b1_osreal.py` (harness config writer): add
  `"release_id": lay.release_id` to the `deployment` section.

## Self-observation preserved (§10)
`observe_deployment` is unchanged and still called; with the correct `release_id` the
runtime/package/identity resolve under `releases\B1\` and the self-verification
naturally passes. No skip, no PATH_NOT_FOUND catch-and-continue, no stale digest, no
alternate-release fallback.

## Validation (§20)
`DeploymentLayout` is frozen F-17 (`layout.py`, diff = 0) so validation lives in the
F-33 reader (`cli.py`). No prior release-id validator existed; the new regex is the
single canonical validator, rejecting empty / `..` / `/` / `\` / `C:` / spaces / `.` /
leading `-` / over-length.

## Tests (`tests/test_stage2cb_b1_r3e.py`, 5)
- Actual release `B1` reconstructs `...\releases\B1\runtime`, NOT `...\current\...`.
- Arbitrary releases (`R42`, `current`, `v2-3_x`) each reconstruct their own runtime
  root — no hardcoding.
- Missing `release_id` → `OperatorError` (EXIT_USAGE) and `cli.main` → EXIT_USAGE;
  never silently resolves `current`.
- Invalid release IDs (`""`, `..`, `a/b`, `a\b`, `C:x`, `a b`, `.`, `-lead`, `a.b`,
  65-char) → `OperatorError` (EXIT_USAGE).
- The value comes from the trusted config only — an env var of the same name does not
  influence it (checkout/env-independent).

## RIM1–RIM10 (`mutation_harness_rim.py`, `rim.txt`)
**6/6 behavioral CAUGHT**: RIM1 (omit release_id), RIM2 (hardcode "B1"), RIM3 (restore
"current" fallback), RIM5 (env override), RIM6 (cwd parse), RIM9 (accept traversal/
invalid). **4 STRUCTURAL** (documented): RIM4 (no brief-reading path exists), RIM7 (no
directory-probing/fallback loop), RIM8 (observe_deployment is essential and consumed
downstream), RIM10 (no source/checkout read — checkout-independence is structural). No
meaningful survivor.

## Freeze / scope
Changed production: `src/gnosis/director/cli.py` (F-33 director) ONLY. Harness:
`run_f33_stage2c_b1_osreal.py` (config writer). Tests: `test_stage2cb_b1_r3e.py`
(new), `test_cli.py` (config gains `release_id`). **Historical F-17 UNCHANGED**
(provisioner/layout/winapi/observers diff 0). **R3D UNCHANGED** (`gnosis_deployment.py`
+ `operator_stack.py` diff 0 since `b2602ca`). Publisher/client + pipe observer +
topology + ACL + schema unchanged (`freeze.txt`).

## Gates
- R3E 5 passed. Targeted (R3E+R3D+gnosis_deployment+cli+driver): 77 passed, 9
  subtests, exit 0. RIM 6/6; R3D/EIM, DDM/NPM/ADM/DM guards intact (prior evidence).
- Full suite: `full_suite.txt` (`PYTEST_EXIT_CODE` direct; known work_queue flake
  governed separately).
- `mypy --strict src` Success, 88 files; ruff (changed) clean.

## Outcome
The R3D-validated composed launch now reaches an operator that correctly self-observes
its own release. Ready for a fresh OS-real qualification (which should now pass the
operator's `build_operator_composition` and proceed to Worker/verifier/L2/publication).
Do NOT run B1; do NOT change R3D/F-17/topology/gate.
