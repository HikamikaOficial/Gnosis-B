# F-33 Stage 2C-PACK — Canonical Operator-Stack Deployment — Final Evidence

Result: **QUALIFIED.** F-33 remains **OPEN**; **Stage 2C-B PENDING RE-RUN**. No provider calls, no
OS provisioning; F-17 trust implementation unchanged; historical F-17 provisioner byte-stable.

## Blocker provenance (why this slice exists)
Stage-2C-B found (code-verified) that the F-17 `Provisioner._deploy_code` deploys only the runtime +
trust-plane package, NOT the `gnosis.director` operator stack that `gnosis.director.cli:main` and the
deterministic Worker image require — so a real `gnosis run` could not execute from a real deployment.
This slice adds the operator-stack deployment layer WITHOUT touching the historical F-17 provisioner.

## Identity / tree
- Starting HEAD (pre-2C-PACK): `bc25f4818416547dcb3aef7096d03cb3003e84df`
- Commit A: `d2537b6ef60046e60b1433b6664404eaceb0f0c4` · `src/gnosis` tree `ec4d1c6bebcb36b0ff021a93875c2b0a6e998168`
- New Stage-2C-PACK source/tree identity (distinct from prior stages).

## Prior L1 normalization (carried forward, unchanged)
`LIVE REVIEWER REACHABILITY / JSON FORMAT = PASS (L1, 1 external call)`;
`LIVE REVIEWER GOVERNANCE/SEMANTIC = NOT EXECUTED`; `FRESH COMPOSED DEPLOYMENT = NOT CREATED`;
`REAL WORKER E2E / REAL PUBLISHER = NOT EXECUTED`; `ROLLBACK = N/A (nothing provisioned)`.
`LIVE_PROVIDER_CALLS_USED_SO_FAR = 1` (this slice added 0).

## Historical F-17 provisioning surface
Qualified F-17 provisioning surface = `gnosis/provision/{provisioner.py, layout.py, winapi.py}` +
`scripts/probe_stage8_provisioning.py`. **This slice changes none of them** (`git diff HEAD --
provisioner.py layout.py` = 0). Architecture: `Provisioner` remains the trust-plane/runtime
provisioner; `operator_stack` is a narrow additive Gnosis-B application-deploy layer above it.

## Files
- Created: `src/gnosis/provision/operator_stack.py`, `tests/test_operator_stack.py`, evidence bundle.
- Modified: **none** (`trust/*` NONE; historical provisioner/layout byte-stable).

## Dependency closure
- Method: deterministic AST closure from `gnosis.director.cli` + `gnosis.director.deterministic_worker`,
  resolving RELATIVE imports (`from ..kernel.x import y`) — the bulk of the code base — to absolute
  names, plus each module's parent-package `__init__`.
- Complete closure: **64 production `gnosis.*` modules** — director 11 (incl. cli/composition/
  publication/publisher_client/trusted_runner/execution/deterministic_worker), kernel 24, trust 14,
  runner 6, adapters 3 (incl. `cli_review`), contracts 3, provision 2, top `__init__` 1.
- Excluded by construction: tests, docs, scripts, `.venv`, `.git`, `ReplayingCLIRunner`
  (`runner/replay_runner.py`), `director/orchestrator.py` — none are imported by the production entry.

## Operator application manifest
- Symbol: `operator_stack.build_application_manifest(source_root) -> ApplicationManifest`
  (deterministic; per-file sha256; one canonical `tree_digest`). Repo-controlled (code), no operator
  input, no arbitrary source paths. Written into the deployment as `APPLICATION.json`.

## Deploy architecture
- Symbol: `operator_stack.deploy_operator_stack(source_root, app_root) -> DeployedApplication`.
- Layout: `application_root_for(layout) = code_release_base/app` (additive; no new root, layout.py
  unchanged). Separation preserved: runtime/trust vs application vs mutable work/secrets.
- Director-readable path: `<app>/gnosis/**`. Worker-readable image path:
  `<app>/gnosis/director/deterministic_worker.py` (bound deterministically; Worker ACLs applied in 2C-B).
- Isolated entry: `operator_entry.py` inserts ONLY the deployed app root on `sys.path` and delegates
  EXACTLY to `gnosis.director.cli:main`; run under `-I` (no CWD/PYTHONPATH/site/checkout).
- Atomic: stage → per-file measure → activate (`replace`); any failure leaves no valid app root.

## Integrity / isolation
- Source==deployed digest equality verified (`verify_application_tree`); one-byte tamper, missing and
  unexpected `.py` detected. Traversal/destination-escape rejected (`_assert_inside`).
- Source-checkout independence PROVEN: the deployed tree imports `gnosis.director.composition/cli/
  deterministic_worker` under `-I` with the checkout unreachable (cwd neutral) → `IMPORT_OK`.
- CWD shadow resistance PROVEN: a malicious `gnosis/__init__.py` in CWD does not win under `-I`.

## Tests / gates
- Packaging PK1–PK15: **17 passed** (closure completeness, no dev/test surfaces, replay-unreachable,
  deterministic manifest, traversal rejected, source==deployed, tamper/missing/unexpected detection,
  worker-image location, entry delegates to canonical main, app tree does not touch trust tree,
  no-checkout import, CWD-shadow resistance, empty-source fail-closed, layout, entry isolation).
- Applied packaging mutants **PKM1/2/5/7/8/9/10 = 7/7 CAUGHT**. Structural/NA: PKM3/PKM4 (entry
  isolation — `sys.path.insert(0, app_root)` + `-I`, covered by the entry-content + isolation tests);
  PKM6 (arbitrary worker path — n/a, closure-driven).
- Full suite (authoritative): **1639 passed, 1 skipped, 285 subtests, exit 0** (`full_suite.txt`; one earlier run hit the known pre-existing test_work_queue concurrency flake — kernel/trust diff 0, independent of this provision-only slice — green on the clean rerun).
- `mypy --strict src`: **Success, 87 source files**. Ruff: changed files clean; baseline untouched.

## Artifact measurement (packaging, NOT the final composed deployment measurement)
files/modules = **64**; bytes = **898,051**; tree digest = `2819e62a183ed7fc5842d0d6b0e0ea6a3d83bb446d7ff892dc193183ae7d4cbc`.
This measures the operator-application bytes; the F-17 trust/deployment digest is a separate, unchanged
layer. The final composed deployment measurement (F-17 trust identity + this application tree identity)
belongs to Stage 2C-B.

## Guards
- Provider calls this slice: **0**. OS provisioning: **NONE**. `src/gnosis/trust/*` diff: **NONE**.
  Historical F-17 provisioner: **UNCHANGED**. F-37: NOT started. NVIDIA/NIM: NOT present.
  Production replay route: UNREACHABLE (excluded from the manifest).

## Next
Re-authorize **Stage 2C-B** against the new composed deployment tooling: a composed provisioner that
consumes the F-17 `Provisioner` (trust plane) AND `deploy_operator_stack` (operator stack), then the
fresh OS-real `gnosis run` E2E + bounded live reviewer (**remaining budget = 4**; do not reset).
