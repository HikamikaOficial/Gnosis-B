# F-33 Stage 2C-B1-R3A — F-17 Deployment-Digest Mismatch Archaeology

READ-ONLY. No OS provisioning, no provider call, no implementation change. Objective:
understand the two F-17 digests and what could make them differ between
provision-time and canonical-launch-time. **No remediation.**

## Chronology (preserved)
1. R2C fixed the pipe observer. 2. The OS-real run proved the Publisher pipe READY.
3. The run then failed at the canonical-launch F-17 re-observation gate. 4. The gate
failed closed before Worker launch. 5. Cause of the digest delta remains UNPROVEN.
Not described as an F-17 implementation regression (no evidence for that).

## Both digest producers
- **Provision-time**: `Provisioner._observe` (`src/gnosis/provision/provisioner.py:418-431`)
  builds `DesiredDeploymentConfig(trust_root=lay.trust_root,
  runtime_executable=lay.runtime_executable, runtime_root=lay.runtime_root,
  runidentity_store=lay.runidentity_root, anchorstore=lay.anchors_root,
  service_name=config.service_name)` → `observe_deployment(...).digest()`. This is
  `InstallResult.deployment_digest` → `base.deployment_digest` →
  `record.f17_deployment_digest`.
- **Launch-time**: `make_real_reobserve` (`scripts/run_f33_stage2c_b1_osreal.py:116-128`)
  builds `DesiredDeploymentConfig` from the **same six** `cfg.layout` fields and calls
  the **same** `observe_deployment(...).digest()`.

## Same or different observer → SAME
Both call the identical canonical function `gnosis.trust.deployment.observe_deployment`
with `DesiredDeploymentConfig` from the **same layout-derived fields**. No
`expected_manifest` participates in the digest (it only verifies). → **observer
argument/algorithm divergence RULED OUT**; the delta is a real change in observed
reality, not an observer artifact. (Determinism contract — same bytes → same digest —
is covered by the deployment/provisioner suites, 118 passed.)

## What the F-17 digest measures (`TrustPlaneDeploymentIdentity.to_dict`)
`schema` · `package` = trust-tree file manifest (path+size+sha256 over trust_root
bytes) · `runtime` (exe) · `runtime_tree` (runtime_root file manifest) · **`service`**
= service **config**+security-descriptor (`observe_service` uses `QueryServiceConfigW`,
NOT running state/PID) · **`trust_root`/`runidentity_store`/`anchorstore`** =
`observe_path_security` → each directory's own path + **canonical SDDL** (owner/group/
DACL/mandatory-label), NOT its children · `pipe_policy`.

## Key structural facts
- **ACL METADATA IN DIGEST = YES**: the digest includes the service's security
  descriptor and each observed directory's SDDL. Any SDDL change to trust_root /
  runidentity_store / anchorstore / the service flips the digest.
- **observe_service is config-only**: STOPPED→RUNNING (`service_start`) does NOT
  change the service component. → "service running state" candidate **RULED OUT**.
- **SELF-REFERENTIAL DIGEST = ABSENT**: the composed/trusted record is
  `state_base/GNOSIS_COMPOSED.json` (`composed_record_path`, gnosis_deployment.py:126-130),
  outside the trust tree; and the stores are observed as directory-SDDL only (not
  children), so writing the record does not change any hashed component.
- **path/ACL vs contents**: `package`/`runtime_tree` hash file **contents+set** under
  trust_root/runtime_root; the stores contribute **directory SDDL only**.

## Timeline between the two observations (actual stages)
`base_provision` (F-17 install → **f17 digest recorded**) → `composed_deployment` →
`trusted_record` (writes GNOSIS_COMPOSED.json to state_base) → `acls` (marker; ACLs
applied during F-17 install) → `service_start` (STOPPED→RUNNING; Publisher
`recover_at_startup` runs) → `pipe_ready` → **canonical_launch reobserve (compare)**.

## Mutator archaeology (each intervening stage vs the observed set)
- **composed_deployment** — AMBIGUOUS: if it writes/relocates any file into
  `trust_root`/`runtime_root`, or changes an observed directory's SDDL, `package`/
  `runtime_tree`/store-SDDL move. Leading candidate; not proven from source alone.
- **trusted_record persistence** — PROVABLY OUTSIDE observed set (state_base).
- **acls** — applied during F-17 install, before the digest; MUTATES OUTSIDE the
  window (unless composition re-ACLs — see above).
- **service_start / Publisher `recover_at_startup`** — AMBIGUOUS: could create/modify
  files or directory SDDLs under the trust/state tree on first start; content writes
  into the store dirs would NOT change the digest (dir-SDDL only), but a write into
  trust_root, or an SDDL/owner change on an observed directory, would.
- **pipe_ready (R2C, WaitNamedPipeW)** — PROVABLY READ-ONLY (no handle, no write).

## Root-cause candidates (evidence-based)
| # | Candidate | Classification |
|---|---|---|
| A | Real mutation inside observed set (trust_root bytes / observed dir SDDL) by composed_deployment or Publisher startup | **STRONGLY SUPPORTED** (leading) |
| D | ACL/security-metadata mutation of an observed dir/service | **PLAUSIBLE** (ACLs are in the digest) |
| B | Self-referential trusted-record mutation | **DISFAVORED** (record in state_base; stores are dir-SDDL only) |
| C | Service startup running-state in observe_service | **RULED OUT** (config-only) |
| E | Observer argument divergence | **RULED OUT** (identical layout fields) |
| F | Observer algorithm divergence | **RULED OUT** (same `observe_deployment.digest()`) |
| G | Nondeterministic enumeration/canonicalization | **DISFAVORED** (canonical/sorted; determinism suites pass) |
| H | Wrong/stale record identity | **DISFAVORED** (single run; deterministic composed_record_path) |

## Stage-8 ordering (§18)
Stage-8 qualified the composed flow under Program Files/ProgramData. Whether Stage-8
performed the fresh re-observation before vs after the same mutation classes now in B1
is **not established from source here** and is **not** claimed as root cause.

## Digest values / manifests
The OS-real run persisted only the mismatch **error string** — NOT the two full
digests or their component manifests. **RUNTIME DELTA NOT RECOVERABLE FROM CURRENT
EVIDENCE.** → **RUNTIME DIGEST DELTA = NOT-PROVEN.**

## Verdict → CASE B (design minimal instrumentation; do not remediate)
Root cause not provable statically. Minimum future diagnostic (ONE OS-real run),
**harness-only, gate-preserving**: capture, around BOTH observations, the observed
identity's `to_dict()` (or per-component sub-digests: package manifest, runtime_tree
manifest, service dict, each store's path+SDDL, pipe_policy), and on mismatch emit the
exact differing component(s) + added/removed/changed manifest entries. Both objects are
already reachable in the harness (`InstallResult.observed` via `make_base_provision`'s
handle; the reobserved identity in `make_real_reobserve`) **without touching
`src/gnosis`**.

MUST NOT (§22-24): accept the mismatch; recompute/update the trusted digest; move or
disable the gate; exclude files to pass; alter deployment/ACL/Publisher/F-17. The
existing fail-closed gate remains authoritative until the delta is understood.
