# F-33 Stage 2C-B1-R3E.1 — Canonical Production Operator-Config Writer

Closes the R3E acceptance blocker (`FAIL — HARNESS-ONLY RELEASE PLUMBING`). The
operator-configuration construction is promoted into the canonical production surface
`gnosis.director.composition`; the B1 OS-real driver now DELEGATES to it (no
independent schema); and a writer-level test + writer→reader roundtrip prove
`deployment.release_id == layout.release_id`. R3E reader contract, R3D, F-17,
Publisher/pipe all unchanged.

## Acceptance blocker closed
R3E: the only operator-config writer was `scripts/run_f33_stage2c_b1_osreal.py`
(harness), and no test proved the writer emits `release_id`. R3E.1 fixes both.

## Config archaeology → chosen module
`src/gnosis/director/composition.py` is the canonical production composition root
(it already owns `TrustedDeploymentInputs`/`AttributionInputs`/`OperatorInputs`/
`ProductionCompositionConfig`/`PublicationCompositionInputs` and the builders `cli.py`
imports). The operator-config writer belongs here — no parallel schema created.

## Canonical writer
`gnosis.director.composition.build_operator_config(inputs: OperatorConfigInputs) ->
dict`, plus `OperatorConfigInputs` (trusted structured inputs) and
`OPERATOR_CONFIG_SECTIONS` (the shared section contract). It **serializes** trusted
values (establishes no trust); `deployment.release_id` is taken verbatim from
`inputs.layout.release_id`.

## Mandatory field inventory (emitted, reader-consumed)
`deployment{code_base,state_base,work_base,release_id,worker_username,trust_root}` ·
`attribution{reviewer_id,policy_actor}` · `operator{director_root,repo_path}` ·
`publication{trust_state_root,evidence_root,repository_id,service_name,pipe_name}` ·
`verifier{name,command}` · `reviewer{binary}`. Test asserts all sections + the
deployment sub-fields, and that `OPERATOR_CONFIG_SECTIONS == cli._REQUIRED_CONFIG`
(anti-drift).

## Authoritative inputs / release provenance
`OperatorConfigInputs.layout` is the authoritative `DeploymentLayout`;
`release_id = layout.release_id` — no fallback, no hardcode, no environment, no cwd,
no brief/work, no checkout (CWM/§5 mutants + `test_writer_ignores_environment`).

## Writer trust boundary
The writer does not establish trust; it serializes deployment-authority-controlled
composition values. Protected config location, R3D effective identity, ComposedRecord
v2, and startup self-observation are untouched.

## Harness disposition / B1 driver migration
`scripts/run_f33_stage2c_b1_osreal.py:build_operator_config` retains its signature
(callers/tests use it) but now **delegates** to
`composition.build_operator_config(OperatorConfigInputs(...))` — it owns NO
config-construction logic (only maps its trusted Stage-2C-B scalars). One writer.

## Product API completeness (§26)
A future production entrypoint can build the operator config using ONLY
`from gnosis.director.composition import OperatorConfigInputs, build_operator_config`
— no `scripts/` import. **YES.**

## Tests (`tests/test_stage2cb_b1_r3e1.py`, 7)
- Writer emits `release_id` from layout (`B1`, `R42`) — the REAL writer, not a manual
  dict (the §32 gap now closed).
- All required sections + deployment sub-fields present; writer/reader contract match.
- Writer ignores an env var of the same name.
- **Writer→reader roundtrip** (`B1`, `R42`): config built by the canonical writer,
  fed to `cli.build_operator_composition`, reconstructs `releases\<rid>\runtime`
  (never `releases\current`) — stronger than testing each side alone.
- Driver delegation: driver output carries `layout.release_id` and the driver imports
  + calls the canonical writer (no local schema).

## CWM1–CWM10 (`mutation_harness_cwm.py`, `cwm.txt`)
**7/7 behavioral CAUGHT**: CWM1 omit release_id, CWM2 hardcode "B1", CWM3 substitute
"current", CWM6 env source, CWM7 writer/reader field-name drift (roundtrip),
CWM4 harness bypass, CWM10 reader restores "current". **3 STRUCTURAL** (documented):
CWM5 (no brief param), CWM8 (single-layout source; = CWM2/3 via roundtrip), CWM9 (no
second writer; driver delegates). No meaningful survivor.

## Freeze / scope
Changed: `src/gnosis/director/composition.py` (**purely additive** — new writer +
inputs + section constant; no `-` lines), `scripts/run_f33_stage2c_b1_osreal.py`
(delegation), new `tests/test_stage2cb_b1_r3e1.py`. **`cli.py` UNCHANGED since R3E**
(reader contract preserved, diff 0). **R3D UNCHANGED** (`gnosis_deployment.py`/
`operator_stack.py` diff 0 since `b2602ca`). **F-17 UNCHANGED**
(provisioner/layout/winapi/observers diff 0). Publisher/client/pipe unchanged
(`freeze.txt`).

## Gates
- R3E.1 7 passed. Targeted (R3E.1+R3E+R3D+cli+driver+gnosis_deployment+composition):
  101 passed, 9 subtests, exit 0. CWM 7/7; RIM 6/6; R3E reader + R3D + EIM/DDM/NPM/
  ADM/DM guards intact.
- Full suite: `full_suite.txt` (`PYTEST_EXIT_CODE` direct; known work_queue flake
  governed separately).
- `mypy --strict src` Success, 88 files; ruff (changed) clean.

## Outcome
One authoritative production operator-config contract, shared by the
production-equivalent B1 route and the deployed operator, with the release_id emission
proven by test. Ready for narrow independent R3E.1 acceptance, then ONE fresh B1
OS-real qualification. Do NOT run B1; do NOT change R3D/F-17/reader/topology.
