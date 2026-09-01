# F-33 Stage 2C-PACK-R1 — Canonical Composed Deployment Remediation — Final Evidence

Result: **QUALIFIED.** F-33 remains **OPEN**; Stage 2C-PACK **READY FOR INDEPENDENT RE-ACCEPTANCE**;
**Stage 2C-B NOT RESUMED**. No provider calls, no OS provisioning; F-17 trust + historical
provisioner byte-stable.

## Prior acceptance blockers (remediated)
- **B1** no canonical composed provisioner → **GnosisDeploymentProvisioner** added (consumes the F-17
  Provisioner; no probe glue).
- **B2** duplicate/unbound `gnosis.trust` deployed + executed by the Director → **ONE authoritative
  F-17-owned trust tree**; the application deploys no trust bytes.
- **B3** `operator_entry.py` outside the measured manifest → **entry now measured** by the application
  tree digest.

## Live-call ledger (unchanged)
`L1 = USED (reachability/JSON PASS)`. Cumulative **1 used / 4 remaining**. This slice: **0**.

## Identity / tree
- Starting HEAD (pre-R1): `900370e20b38c37e14ec171bfd70e3df13e9b28d`
- Commit A: `0760ef4` · `src/gnosis` tree `d28721c90cbbc9dca6c8330de7e68c43df531951`.

## F-17 package topology (before/after)
- F-17 canonical package root = `code_release_base/publisher` (contains `gnosis/__init__.py` +
  `gnosis/trust/`; runtime `python._pth` puts `..\publisher` on the path → `import gnosis` resolves
  there). The Publisher service entry imports `gnosis.trust.publisher_service` from it.
- **After R1:** the application modules (director, the rest of kernel, runner, adapters, contracts)
  are deployed into the SAME `publisher/gnosis/` package, adjacent to F-17's `gnosis/trust/`.

## Chosen one-trust-tree architecture
- The production import closure (64 modules) is split deterministically:
  **F-17-PROVIDED = 19** (the trust-plane sub-closure: the 14 `gnosis.trust.*` the Director needs —
  incl. `orchestration`, `deployment`, `worker_launcher`, `launch_spec` — plus `gnosis/__init__`,
  `gnosis/kernel/{__init__,canonical,atomic_io,file_lock}`); **APPLICATION-PROVIDED = 45**.
- The full trust closure is handed to the **UNMODIFIED** F-17 `Provisioner` as `publisher_files`
  (`f17_publisher_files`); `publisher_files` is construction config, so **no F-17 impl change** is
  required to make the one tree contain every trust module the Director imports.
- The application deployer refuses any `gnosis/trust/*` path (ownership guard) and refuses to
  overwrite any existing (F-17-owned) file. Director/Publisher/Worker therefore import ONE
  authoritative trust tree.

## F-17 byte-stability
`git diff HEAD~1..HEAD -- src/gnosis/trust` = **NONE**; `provisioner.py`/`layout.py`/`winapi.py` =
**byte-stable (0)**. Only `operator_stack.py` (rewritten) + new `gnosis_deployment.py` changed.

## Application closure V2
- APPLICATION-PROVIDED = 45 modules + the measured `operator_entry.py`. Contains **no** `gnosis/trust/*`
  path (verified). Trust overwrite/ownership prevented at both manifest-build and deploy time.

## Canonical package root / entry / worker image
- Package root: `canonical_package_root(layout) = code_release_base/publisher`.
- Operator entry: `<pkg>/operator_entry.py`, delegates EXACTLY to `gnosis.director.cli:main`,
  `sys.path = [pkg]`, launched `<runtime> -I -B <entry>` — and **measured** in the manifest.
- Worker image: `<pkg>/gnosis/director/deterministic_worker.py` (measured; no checkout fallback).

## Composed provisioner
- Symbol: `gnosis.provision.gnosis_deployment.GnosisDeploymentProvisioner.provision() -> ComposedDeployment`.
- Flow: run/consume F-17 base (`base_provision`; privileged in prod, fixtured in tests) → deploy the
  operator stack into the canonical root → compute the composed identity → return one typed result.
  App failure after base → fail closed + roll the base back (no half-composed deployment).
- `verify()` fails closed on application-tree mismatch, composed-identity mismatch, or `-I` missing.

## Composed deployment identity
- `composed_deployment_digest(f17_deployment_digest, application_tree_digest)` — additive, domain-
  separated (`gnosis.composed_deployment.v1`); binds both surfaces. No F-17 RunIdentity/Anchor/
  PublicationState/deployment-digest semantics changed. Enforced at `verify()` (startup).

## Trust provenance (proven, checkout excluded)
Director `gnosis.trust.run_identity.__file__` and `gnosis.trust.orchestration.__file__`, plus
`gnosis.director.cli/composition/deterministic_worker`, all resolve under the ONE package root
`<pkg>` — no second application-owned authority-adjacent trust implementation, no source-checkout
paths. CWD-shadow (`-I`) resistance proven.

## Tests / gates
- operator_stack primitives: **12 passed**. Composed RPK1–RPK20: **12 passed** (incl. one-tree
  provenance + no-checkout + shadow smokes). Total R1 targeted: **24 passed**.
- Applied mutants **RPKM2/4/5/6/7/9/12 = 7/7 CAUGHT**. Structural/folded: RPKM1 (composed API exists),
  RPKM3 (= RPKM2), RPKM8 (worker path package-relative), RPKM10 (rollback-failure → "unknown state"),
  RPKM11 (= RPKM4).
- Full suite (authoritative): see `full_suite.txt`.
- `mypy --strict src`: **Success, 88 source files**. Ruff: changed files clean; baseline untouched.

## Guards
- Provider calls: **0**. OS provisioning: **NONE**. `src/gnosis/trust/*` diff: **NONE**. Historical
  F-17 provisioner: **UNCHANGED**. Production replay route: **UNREACHABLE** (excluded from closure).
  F-37: NOT started. NVIDIA/NIM: NOT present.

## Next
Re-run the independent Stage-2C-PACK acceptance review against this remediation; on PASS, resume
Stage 2C-B (fresh OS-real composed `gnosis run` E2E via `GnosisDeploymentProvisioner` + bounded live
reviewer; **remaining budget = 4**).
