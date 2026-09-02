# F-33 Stage 2C-B1-R3B — Deployment-Identity Delta Instrumentation

Harness/test/evidence only. Gate-preserving diagnostics that name WHICH F-17 identity
component changed between the trusted provision-time observation and the fresh
canonical-launch re-observation. **No remediation; no trust-gate change; no
F-17/topology/ACL/Publisher/runtime/service change; no provider call. `src/gnosis`
diff = NONE.**

## R3A carry-in
`F-17 DIGEST PRODUCERS = SAME` · `SELF-REFERENTIAL DIGEST = ABSENT` ·
`ACL METADATA IN DIGEST = YES` · observer arg/algorithm divergence RULED OUT ·
`RUNTIME DIGEST DELTA COMPONENT = NOT-PROVEN` (only the mismatch error string was
captured). Leading family: real mutation inside the observed identity set.

## Files changed
`scripts/identity_delta.py` (new: recorder + pure diff), `scripts/stage2cb.py`
(orchestrator captures provision snapshot; `FakeObserved.to_dict` test-double),
`scripts/run_f33_stage2c_b1_osreal.py` (launch snapshot + trace), new
`tests/test_stage2cb_b1_r3b.py`. **`src/gnosis` = NONE**, F-17 unchanged,
Publisher/client unchanged, Stage probes unchanged.

## Provision-snapshot provenance (authoritative)
The orchestrator captures `InstallResult.observed` immediately after
`base = base_provision()` (`stage2cb.py`), i.e. **the exact object whose `.digest()`
became `base.deployment_digest = record.f17_deployment_digest`**. Not a later
re-observation.

## Launch-snapshot provenance (authoritative)
`make_real_reobserve` records the **same `identity` object** whose `.digest()` is
returned to the trust gate (`recorder.record_launch(identity); return
identity.digest()`). Exactly one observation feeds both the gate and the recorder
(guarded by `test_reobserve_records_the_gate_observation` / DDM8).

## Proof the same observations feed the gate
- Provision: `_handle["install"].observed` is the F-17 install's own observed
  identity; its digest is the trusted record's f17 digest.
- Launch: the single `identity` built in `make_real_reobserve` is both recorded and
  digested for the gate. No second re-observation (DDM8 CAUGHT).

## Diagnostic storage — outside the observed set
The recorder is **pure/in-memory**; the delta travels only in the driver's `trace`
dict → stdout. **Nothing is written to disk at all**, so it cannot live inside
trust_root/runtime_root/any store, and cannot itself create the digest delta. The
module contains no `open`/`write`/`mkdir`/`Path(` (structural test + DDM3 CAUGHT).

## Observed-identity field inventory & secret-safety
`TrustPlaneDeploymentIdentity.to_dict()` carries: `schema`; `package`
(paths+sizes+SHA-256, no contents); `runtime` (exe path/size/digest); `runtime_tree`
(paths+sizes+SHA-256); `service` (name/account/image_path/start_type/service_sid/
sid_type/required_privileges/security_descriptor); `trust_root`/`runidentity_store`/
`anchorstore` (path + canonical security descriptor); `pipe_policy`. **No file
contents, credentials, tokens, or DPAPI plaintext.** SDDLs are SIDs/ACEs only. The
full to_dicts are safe; SDDLs are additionally reduced to per-subcomponent
fingerprints in the delta.

## Component diff (§7) + manifest (§8) + SDDL (§9) + service (§10) + path (§11)
`classify_identity_delta(provision, launch)` marks every top-level component
UNCHANGED/CHANGED (never stops at the first). For tree components (`package`,
`runtime_tree`) it emits `added` / `removed` / `changed` canonical relative paths.
For security descriptors (`service`, stores) it emits a safe fingerprint delta
(owner/group/control/dacl-fingerprint/label-fingerprint) → distinguishes
FILE/TREE-CONTENT from SECURITY-DESCRIPTOR mutation. It compares observed absolute
`path`s (PATH_IDENTITY_CHANGED) and the `service` component separately.

## Component digest hierarchy (§12)
`result().component_digests` gives a diagnostic-only stable digest per component for
both sides. These are labels only and **never** replace the authoritative F-17
deployment digest.

## Timing/order markers (§13)
The stage order is already recorded in `res.stages`:
`base_provision(T0 provision identity) → composed_deployment(T1) → trusted_record(T2)
→ acls(T3) → service_start(T4/T5) → pipe_ready(T6) → reobserve/compare(T7/T8)`. R3B
adds no fabricated timestamps.

## Optional intermediate snapshots (§14/§15)
NOT added (kept minimal). `observe_deployment` is read-only, but intermediate
snapshots are deferred to avoid complexity; the two mandatory snapshots (provision +
launch) are sufficient to establish the DELTA. The MUTATOR boundary can be added
later if the delta alone does not localise it.

## Difference classifications (§16)
Taxonomy: `PACKAGE_CONTENT_CHANGED`, `RUNTIME_CONTENT_CHANGED`,
`SERVICE_SECURITY_CHANGED`, `STORE_SECURITY_CHANGED`, `PATH_IDENTITY_CHANGED`,
`PIPE_POLICY_CHANGED`, `MULTIPLE_COMPONENTS_CHANGED`, `NO_STRUCTURAL_DELTA_FOUND`,
`DIFF_UNAVAILABLE`. DELTA (what changed) is kept strictly separate from MUTATOR
(which stage caused it) — R3B establishes the DELTA only.

## Tests (`tests/test_stage2cb_b1_r3b.py`, 16)
Package-change (§18), runtime-change (§19), service-SDDL (§20), store-SDDL (§21),
path-change (§22), multi-delta both-surfaced (§23), identical→NO_STRUCTURAL_DELTA
(§24), DIFF_UNAVAILABLE; recorder authoritative-object + digests_match-reflects-reality
+ snapshot-failure-swallowed + no-filesystem-IO; **gate-preservation**: a raising
recorder still returns the authoritative digest (§25/§26); and single-observation
wiring (DDM8).

## DDM1–DDM8 — all CAUGHT (`mutation_harness_ddm.py`, `ddm.txt`)
DDM1 launch-as-both-sides; DDM2 digests_match-lies; DDM3 write-inside-observed-root;
DDM4 hide-additional-delta; DDM5 ignore-SDDL; DDM6 ignore-content-manifest; DDM7
diagnostics-failure-bypass; DDM8 reobserve-twice-wrong-object. **8/8 CAUGHT.**

## Regression / gates
- R3B: 16 passed. Targeted (R3B+R2C+R2B+R2A+R1+driver+backend+publisher): 199 passed,
  80 subtests, exit 0. F-17 (provisioner/layout/gnosis_deployment/deployment_identity):
  118 passed. NPM 8/8, ADM 6/6, DM(R2B) 6/6 (R2A/R2B/R2C truthfulness intact).
- Full suite: `full_suite.txt` (`PYTEST_EXIT_CODE` direct; known work_queue flake
  governed separately — a red run stays red).
- `mypy --strict src` Success, 88 files; ruff (changed) clean.

## Freeze
`src/gnosis` = NONE; `trust/*` = NONE; `publisher_client.py`/`pipe_server.py`
UNCHANGED; historical provisioner/layout/winapi + Stage probes UNCHANGED (`freeze.txt`).

## Trust gate preserved
The comparison `observed_f17 != record.f17_deployment_digest` (`gnosis_deployment.py`)
is **unchanged**; R3B never updates the recorded digest, never moves/relaxes the gate,
never launches on mismatch, never excludes components. Diagnostics are best-effort
(swallowed) so they can neither break nor bypass the gate.

## Outcome / next
Ready for ONE OS-real diagnostic run on the instrumented baseline to identify the
EXACT real identity delta (which component[s] differ). After that evidence, stop for
independent review before designing any remediation. Do NOT change ACLs/topology/
gate/trusted-digest.
