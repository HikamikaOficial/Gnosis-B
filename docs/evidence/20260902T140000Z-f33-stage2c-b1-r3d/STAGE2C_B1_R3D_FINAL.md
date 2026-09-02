# F-33 Stage 2C-B1-R3D — Effective Composed Deployment Identity

Implements the R3C-accepted Option B. Three distinct identities — immutable base
F-17 provenance, closed-world application identity, and the **effective** whole-root
identity of the final executable one-tree — bound into one composed digest and
freshly verified before spawn. No topology change; no trust-gate weakening; F-17
(provisioner/layout/winapi/canonical observers) unchanged.

## Trust model (three identities)
- **`f17_deployment_digest`** — base F-17 provenance (pre-application). Historical
  meaning retained; never overwritten, never redefined to mean the final tree.
- **`application_tree_digest`** — closed-world F-33 application/operator manifest.
- **`effective_deployment_digest`** (R3D) — the whole-root identity of the FINAL
  executable one-tree, from the canonical whole-root observer, measured AFTER the
  application tree is deployed.

## Composed binding (§2)
`composed_deployment_digest = SHA256(canonical{schema=gnosis.composed_deployment.v2,
f17_deployment_digest, application_tree_digest, effective_deployment_digest})` —
domain-separated, binds ALL THREE. Any omitted/mismatched operand fails to reproduce
it (EIM1/EIM9/EIM10).

## Schema / legacy (§3, §20)
`COMPOSED_RECORD_SCHEMA = gnosis.composed_record.v2`; the record carries the new
`effective_deployment_digest` key. `read_composed_record` enforces the exact v2 key
set, v2 schema tag, 64-hex on all four digests, and internal consistency of the
3-operand binding. **A v1 / legacy record (missing effective, or old schema) fails
closed — no silent migration, no auto-upgrade** (test_legacy_v1_record_fails_closed,
test_missing_effective_rejected, test_wrong_schema_right_keys_rejected). The baked
startup verifier's `_COMPOSED_RECORD_SCHEMA` is bumped to v2 in `operator_stack.py`
(it still consumes only `application_tree_digest`).

## Provision order (§4)
`provision()`: F-17 base → `deploy_operator_stack` (app tree into the one-tree root)
→ verify + re-measure application → **observe effective whole-root (post-app)** →
bind `H(base, application, effective)` → persist v2 record → final `verify()` (reads
record back, checks base + application + effective + binding). The effective
observation is textually after deploy and asserted post-deploy
(test_effective_measured_after_app_deploy).

## No "trust whatever is there" (§5)
The application bytes are authenticated by the existing closed-world APPLICATION.json
+ source verification in `deploy_operator_stack` BEFORE they enter the tree; the
effective observation records the identity of an already-verified assembly. An
attacker's bytes never become trusted merely by being observed.

## Canonical-launch predicate (§6, §7)
Before spawn, `canonical_launch` verifies, from the trusted record: (a) fresh
whole-root observation == `effective_deployment_digest` (NOT the pre-application base
— that was the R3A/R3C collision); (b) fresh application identity == recorded; (c)
operator entry + canonical worker image are measured manifest files present on disk;
(d) recomputed `H(record.base, fresh application, fresh effective)` ==
`composed_deployment_digest`; (e) `-I` isolation. The base provenance is retained as
a bound operand (documented, immutable). No single check replaces the others.

## Unexpected file / substrate / application mutation (§8-§11, §25)
Any change to the executable trust_root — an injected/extra importable file, a
substrate-file replacement, or an application-file mutation — changes the fresh
whole-root effective identity and/or the application identity, and always the
composed binding → fail closed (test_whole_root_change_refused,
test_application_tamper_still_refused, test_coherent_app_tamper_caught_by_record).
No exclusions, no "known app prefix" bypass — the observer still measures EVERY file
(F-17 `observe_trust_package` unchanged).

## Record mix-and-match / substitution (§12-§14)
A record mixing operands from different deployments, or mutating only the effective
or composed digest, cannot reproduce the 3-operand binding →
`read_composed_record` rejects (test_effective_substitution_inconsistent,
test_mix_and_match_operands_rejected). The record's authority remains its
deployment-authority-owned location (unchanged trust model).

## TOCTOU / ordering (§15)
The fresh effective observation occurs in the existing pre-spawn window immediately
before process creation (`canonical_launch`); no new mutable post-verification window
is introduced; `spawn` is the final statement.

## Path / SDDL / service (§16, §17)
The effective identity uses the SAME canonical whole-root observer
(`observe_deployment` → full `TrustPlaneDeploymentIdentity`, incl. paths, security
descriptors, service and runtime), never a content-only package hash. F-17 observer
unchanged.

## Mutation matrix — EIM1-EIM14 (`mutation_harness_eim.py`, `eim.txt`)
**6/6 applied behavioral mutants CAUGHT**: EIM1 (omit effective from binding), EIM2
(reuse base as effective), EIM4 (accept old schema), EIM6 (skip record app check),
EIM7 (skip effective check), EIM9 (skip composed-consistency check). **8 STRUCTURAL**
(documented, not silently claimed): EIM3 (reorder — asserted by test), EIM5 (no
record write in canonical_launch), EIM8/EIM11 (extra-file/substrate = EIM7 whole-root
mechanism), EIM10 (= EIM1 formula), EIM12 (= EIM6/measure), EIM13 (spawn is last),
EIM14 (observer is injected production `observe_deployment`, not a gnosis_deployment
mutation). The composed binding is the single authoritative check binding all three
identities; the message-asserting behavioral tests make each defense-in-depth layer
independently detectable.

## Positive + reproduction (§23, §24)
Positive: base A ⊗ application B ⊗ effective C → bind → fresh A/B/C valid →
`canonical_launch` PASS (test_valid_effective_launch_passes). Reconciliation of the
historical bug: an observer returning the pre-application base digest is now REFUSED
(test_launch_not_held_to_pre_app_base) — the launch operand is the effective identity.

## Change surface / freeze
Changed: `src/gnosis/provision/gnosis_deployment.py`,
`src/gnosis/provision/operator_stack.py` (schema constant) — F-33 composition only.
`scripts/{stage2cb,run_f33_stage2c_b1_osreal}.py` (observe_effective wiring), tests.
**Historical F-17 UNCHANGED**: `provisioner.py`, `layout.py`, `winapi.py`,
`trust/deployment.py` (canonical observers), Stage-5/6/7/8 probes — all diff = 0
(`f17_freeze.txt`). Publisher/client unchanged. Trust gate NOT weakened (it is
strengthened: the launch operand now matches reality and binds three identities).

## Tests / gates
- R3D: 14 passed. gnosis_deployment: 29 passed. Targeted (R3D+R3B+gnosis_deployment
  +R2A/B/C+R1+driver+backend+publisher): 242 passed, 80 subtests, exit 0.
- F-17 regression (provisioner + layout + deployment_identity): 89 passed.
- EIM 6/6 behavioral CAUGHT; DDM 8/8; NPM 8/8; ADM 6/6; DM 6/6 (all prior
  truthfulness/observation/identity-delta guards intact).
- Full suite: `full_suite.txt` (`PYTEST_EXIT_CODE` direct; known work_queue flake
  governed separately).
- `mypy --strict src` Success, 88 files; ruff (changed) clean.

## Qualification impact (§29)
Preserved: 2A, 2B.1/2, 2C-A, B0, B1-PRE0, B1-R1, R2A/B/C, R3A/B (verified by the
targeted + full regression). Requalified (bounded): the composed-record / provision /
canonical-launch semantics (schema v2 + 3-operand binding + effective predicate) —
exactly the composed identity ADR-0032 requires to be freshly measured.

## Outcome
Ready for independent final acceptance, then a fresh OS-real composed qualification.
Do NOT run B1 yet. No trusted-digest overwrite, no gate move, no topology change.
