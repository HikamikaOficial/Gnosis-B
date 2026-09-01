# F-33 Stage 2C-PACK-R2 — Mandatory Composed-Identity Enforcement — Final Evidence

Result: **PASS (pending final independent enforcement review).** F-33 remains
**OPEN**; Stage 2C-PACK **READY FOR FINAL INDEPENDENT ACCEPTANCE**; **Stage 2C-B
NOT RESUMED**. No provider/live calls, no OS provisioning. F-17 trust + historical
provisioner byte-stable.

## Prior re-acceptance FAIL (the one blocker)
> COMPOSED DEPLOYMENT IDENTITY EXISTS BUT IS NOT AN UNBYPASSABLE PRODUCTION GATE

R1 defined and could *check* the composed identity (`verify()`), but `provision()`
returned a launchable artifact without verifying, `verify()` was orphaned from the
provision→launch path, and the deployed operator could not self-verify. R2 makes
the composed identity an **unbypassable gate at three points**.

## Starting state
- Starting HEAD (R1 evidence commit): `97abcb7e99d7ef03f40cd85dfd13d54951b37da5`
- Accepted base before R1: `900370e20b38c37e14ec171bfd70e3df13e9b28d`
- R2 implementation commit A: `bde0e3e` · `src/gnosis` tree
  `df0522c4c91fa0530501f02d85f0ab1e0ec5f1f9`

## Preserved (not redesigned)
One canonical composed provisioner; one authoritative production `gnosis.trust`
tree (TRUST COPY COUNT = 1); application cannot overwrite F-17 trust; measured
operator entry; canonical deterministic Worker image; source-checkout
independence; `-I -B` canonical launch; application-tree measurement; domain-
separated composed identity; historical F-17 byte stability. B1 and B3 not
reopened.

## Root of trust: the trusted composed record (NOT APPLICATION.json)
- **Location:** `Path(layout.state_base) / "GNOSIS_COMPOSED.json"` — the F-17
  STATE base (ProgramData; protected, inheritance-stripped, worker-denied by the
  Stage-8 ACL matrix), **OUTSIDE** the application tree under
  `code_release_base/publisher/gnosis` that it authenticates. Derived from the
  layout's existing public `state_base`; **`layout.py` is byte-unchanged**.
- **Why trusted:** its authority is the deployment-authority ownership of that
  location (Admin/SYSTEM; Stage-2C-B will pin the ACL and give the Director read-
  only), NOT a self-hash. No cryptographic authenticity is claimed beyond that
  contract; an Admin/SYSTEM/deployment-authority compromise remains out of the
  existing threat model. `APPLICATION.json` lives inside the measured tree, so a
  coherent tamper of both app bytes and the local manifest is internally
  consistent — it can therefore NEVER be the root of trust.
- **Content (schema `gnosis.composed_record.v1`, non-secret, deterministic):**
  schema, `f17_deployment_digest`, `application_tree_digest`,
  `composed_deployment_digest`, `package_root`, `operator_entry_relpath`,
  `worker_image_relpath`. No credentials, no DPAPI, no provider secrets, no
  mutable work state.
- **Atomicity:** `_atomic_write_json` writes a temp file in the same directory,
  `flush()`+`os.fsync()`, then `os.replace` — a partial/truncated record can never
  be observed as valid. `read_composed_record` parses fail-closed (schema, exact
  key set, no duplicate keys via `object_pairs_hook`, 64-hex digests, bounded
  size, internal composed-digest consistency).

## Gate 1 — PROVISION TIME (`GnosisDeploymentProvisioner.provision`)
Order: F-17 `base_provision()` → `deploy_operator_stack` (stages the measured
self-verifying entry that bakes in the trusted-record path) → `verify_application_
tree` → `measure_application_tree` (re-measure from bytes) → derive composed digest
→ **atomically write the trusted record** → **final `verify(comp)` re-reads the
record from disk and re-verifies the whole composition** → only then return. Any
failure fails closed and rolls the F-17 base back (`_rollback_or_unknown`; a
failing rollback raises "unknown state"). No valid-looking record is ever left
pointing at an incomplete deployment.

## Gate 2 — PRE-LAUNCH (`GnosisDeploymentProvisioner.canonical_launch`)
The ONE supported production launch. Immediately before process creation:
1. read the trusted composed record (fail-closed);
2. **re-observe** the current F-17 deployment identity via the injected
   `reobserve_f17` (production wires it to
   `gnosis.trust.deployment.observe_deployment(...).digest()` — a FRESH
   observation, never the in-memory provisioning digest; no F-17 code changed);
3. re-load `APPLICATION.json` fail-closed and **re-measure the application tree
   from CURRENT bytes** (never `comp`'s in-memory digest);
4. verify the measured operator entry and canonical Worker image are measured
   manifest files present on disk;
5. recompute the composed digest from the re-observed F-17 digest + re-measured
   app digest;
6. compare against the trusted expected digest; also require the re-observed F-17
   digest and re-measured app digest to equal the record's;
7. fail closed on any mismatch;
8. only then return/execute `(<deployment-bound python>, "-I", "-B", <measured
   entry>, *operator_args)`.

The entry path, package root and interpreter come from the trusted `comp`/record
and the deployment-bound runtime — never from caller input. There is no parameter
to override the entry/root or disable verification (signature is exactly
`comp, reobserve_f17, spawn, operator_args`). `provision()` no longer returns an
unchecked argv; `launch_argv` is a convenience field, and the supported route is
`canonical_launch`.

## Gate 3 — STARTUP self-verification (measured `operator_entry.py`)
Before `from gnosis.director.cli import main`, using ONLY the stdlib and its own
measured bytes (it never imports the application package to verify that package):
parse `APPLICATION.json` fail-closed (schema, no duplicate keys, canonical
relpaths, bounded size/count, hex digests, no duplicate normalized paths);
re-measure every listed file against deployed bytes; recompute the canonical tree
digest; read the trusted composed record; **require the record's
`application_tree_digest` to equal the manifest tree digest** (so the local
manifest ALONE cannot authorize startup); require its own relpath to be measured.
On any failure it writes a diagnostic and `raise SystemExit(70)` — it does NOT
insert the package root or import gnosis. Only on success does it insert `_ROOT`
and delegate to `gnosis.director.cli:main`. Launch stays `python -I -B`. The
trusted-record path is baked into the measured entry (tamper-evident to Gate 2's
entry re-measurement).

## Coherent code+manifest tamper (the key negative)
E11 (tamper app + regenerate `APPLICATION.json`, record unchanged) and E12 (same
for the entry) and E13 (swap an internally-consistent release) are all REFUSED at
`canonical_launch` and at startup, because the external trusted record's expected
digest differs from the (coherently regenerated) local manifest. Self-consistency
of the tree + its own manifest is never sufficient.

## F-17 identity boundary
F-17 identity semantics unchanged: RunIdentity, deployment digest format, Anchor
V2, PublicationState, Publisher authorization. The composed identity is an
ADDITIVE deployment/startup gate. **F-17 Anchor V2 does NOT newly claim to bind
the F-33 composed deployment digest.** Publication traceability of the composed
digest is DEFERRED (no F-17 change was in scope); runtime/startup enforcement is
the blocker solved here.

## One trust tree & Worker image (preserved)
`TRUST COPY COUNT = 1`; no `gnosis.trust` in the application manifest; the startup
verifier requires no duplicated trust implementation. Canonical Worker image =
`<pkg>/gnosis/director/deterministic_worker.py`, measured; named in the trusted
record; obtained by Stage-2C-B from `comp.worker_image` / the record.

## Canonical-route bypass review (§25)
The deployed artifact contains no `gnosis` console script (the `[project.scripts]`
entry is a dev/editable-install convenience produced by pip/uv, not by the file-
copy production deployment); the only entry in the deployed tree is the self-
verifying `operator_entry.py`. A manual `python -c "import gnosis..."` is a Python
possibility, not an advertised production route, and is bounded by the Stage-2C-B
ACLs. No second canonical production route exists. (No STOP condition.)

## Tests / mutants / gates (recorded below)
- Targeted: `tests/test_operator_stack.py` + `tests/test_gnosis_deployment.py`.
- E1–E18 (+ extra byte-tamper startup case) — see `targeted.txt`.
- Applied mutants E-M1..E-M12 — see `## Mutation results` below and
  `mutants_r2.txt`.
- Full suite — see `full_suite.txt`.
- `mypy --strict src` = Success, 88 files. Ruff (changed files) = clean.

## Mutation results (E-M1..E-M12)
- **APPLIED / CAUGHT (6, all security-critical gates):** E-M3 (launch skips app
  re-measurement) → e6; E-M5 (launch reuses record F-17 digest, no re-observation)
  → e8; E-M6 (startup skips trusted-record comparison) → e15; E-M7 (startup
  imports cli.main before verification) → e16; E-M9 (startup ignores per-file byte
  tamper) → byte-tamper startup test; E-M10 (launch without `-I`) → e5.
- **SURVIVED — redundant defence-in-depth, NOT security-relevant (demonstrated):**
  E-M4 (launch skips the composed-digest comparison) survives only because the
  sibling `measured != record.application_tree_digest` check enforces the same
  binding; disabling BOTH makes e6/e11 slip — proving the gate is jointly load-
  bearing. E-M1/E-M2 (remove/soften the PROVISION-time final verify) survive
  because the security boundary is launch/startup: a tampered deployment returned
  by `provision()` is still refused at `canonical_launch`/startup (E-M3/E-M6/E-M7
  are load-bearing there).
- **STRUCTURAL / no injection point:** E-M8 (coherent tamper) folds into E-M3
  (launch) and E-M6 (startup); E-M11 (arbitrary composed-record path) — no path
  parameter exists; E-M12 (direct supported CLI bypass) — no separate CLI entry
  exists in the deployed artifact (folds into E-M7).
- **No security-relevant survivor.**

## Guards
Provider calls = 0. Live Claude calls = 0. OS provisioning = NONE.
`src/gnosis/trust/*` diff = NONE. Historical F-17 provisioner (`provisioner.py`,
`layout.py`, `winapi.py`) = UNCHANGED. Production replay route = UNREACHABLE
(`replay_runner`/`orchestrator` excluded from the closure). F-37 = NOT STARTED.
NVIDIA/NIM = NOT PRESENT. Cumulative live calls = 1 used / 4 remaining (L2 not
consumed).

## Next
Recommend a narrow, independent **Stage-2C-PACK-R2 final enforcement review**.
Only after an independent PASS may Stage-2C-B resume.
