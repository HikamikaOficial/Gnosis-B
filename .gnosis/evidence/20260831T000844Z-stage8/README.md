# F-17 Stage 8 — production provisioning, OS-real qualification evidence

Implementation commit: **77c639a** (`F-17 Stage 8: production provisioning,
qualified OS-real`), on top of the provisioning library `54b6a69`. Authoritative
starting HEAD for the stage: `ad32bba` (Stage 7 closed).

Everything here was produced against **disposable, production-equivalent** OS
state — the real `C:\Program Files` / `C:\ProgramData` ancestors and the real
Windows security model, with disposable leaf names (`GnosisStage8Probe`,
service `GnosisPubS8Probe`, account `GnosisWkrS8`) — and **rolled back**. No
permanent install was left behind.

## Files

- `stage8_probe.txt` — `scripts/probe_stage8_provisioning.py`, OS-real:
  **ALL 140 CHECKS PASSED**, both roots removed on rollback. Sections:
  A clean install; A/B OS state + deployment identity (RESTRICTED service SID,
  DPAPI blob, every protected root exists with no broad principal, digest
  stable + version-bound); C import provenance (deployed runtime, `import
  gnosis` under the deployed publisher, no `site-packages`, `python._pth`
  disables site); D adversarial ACL matrix as the provisioned worker
  (WRITE/DELETE/RENAME/WRITE_DAC/WRITE_OWNER denied on every protected
  category, credential blob unreadable, positive controls succeed);
  E composition smoke (Director → worker → publisher → Anchor v2 ANCHORED, and
  fail-closed on a non-CLEAN boundary verdict at both the trusted gate and the
  service); F1 idempotence; F2 update / failed-update / rollback; F3 uninstall
  + OS post-check.
- `stage8_mutation.txt` — `scripts/mutation_check_stage8.py`: baseline green,
  **21/21 mutants CAUGHT, 0 survived**, restored green.
- `stage8_fullsuite.txt` — `pytest tests/`: **1509 passed, 1 skipped, 263
  subtests passed**, `1 failed`. The lone failure is the known
  `test_work_queue.py::...test_recovery_never_takes_a_brief_from_a_live_worker`
  lease-timing flake (`StaleLeaseError` under the 18-minute load); it **passes
  in isolation** and is in `kernel/lease`/`work_queue`, untouched by Stage 8.
- `stage8_fresh_checkout.txt` — `scripts/fresh_checkout_check.py` against commit
  `77c639a`: preflight proved `import gnosis` resolved to the **extraction**
  (git-archive from the object DB), not the working tree; then **475 passed,
  1 skipped, 143 subtests passed**. This corrected methodology supersedes the
  historical fresh-checkout assertions, which imported the working tree via the
  venv's editable `.pth` and so measured nothing.

## Static analysis

- `mypy --strict src`: clean (79 source files).
- `ruff`: clean over the Stage 8 surface.
- Provision unit suite: 27 (`tests/test_provision_layout.py`,
  `tests/test_provisioner.py`).

## Defects found OS-real and fixed (all in this stage)

1. Maintenance principal resolved by the localized name
   `BUILTIN\Administrators` → `ERROR_NONE_MAPPED` on non-English Windows.
   Fixed: use the well-known SID `S-1-5-32-544`.
2. Service ran without `-B`, so first import wrote `__pycache__/*.pyc` into the
   measured trust root and drifted the deployment digest. Fixed: ImagePath uses
   `-I -B`.
3. Hardened service DACL omitted change-config/delete even for Administrators,
   locking maintenance out of its own service (`sc config rc=5 ACCESS_DENIED`).
   Fixed: SY+BA full service control, worker absent.
4. `DEPLOYMENT.json` was written into the measured trust root after observation.
   Fixed: moved to the (unmeasured) state base.

## Trust boundary / TCB note

Provisioning is trusted MAINTENANCE code. It is NOT imported by the publisher
runtime — the publisher import closure is unchanged (15 modules). The trusted
computing base is unchanged in kind: `project-source Trust Plane ~LOC` plus the
`trusted Python runtime ~62 MB / 3434 files`. F-14 is not reopened.
