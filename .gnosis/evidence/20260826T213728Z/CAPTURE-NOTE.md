# F-17 Dedicated-Worker Toolchain Qualification — capture note

Reversible OS-real probe. Proves the full Gnosis worker toolchain runs from a
RELOCATED, RX-only (worker-non-writable) root OUTSIDE the operator profile,
under a dedicated non-admin worker user, and that the worker cannot poison the
toolchain or reach operator credentials.

## What ran
- Toolchain root: `C:\ProgramData\GnosisWorkerToolchainProbe` (disposable copies of
  python 3.12.14 + venv site-packages, claude.exe, codex.ps1 + @openai/codex, gnosis pkg).
  ACL: `/inheritance:r` + Administrators:F, SYSTEM:F, Usuarios:(OI)(CI)RX — allowlist,
  no DENY. Node and Git are the shared Program Files installs (read-only to Users).
- Worker: local standard user `GnosisWorkerProbe` (group Usuarios only, admin=False),
  launched via CreateProcessWithLogonW (no handle inheritance). Crypto-random SecureString
  password, never materialized as plaintext; account deleted in rollback.
- Worktree/scripts under `C:\ProgramData\GnosisWorkerTCprobe` (worker-granted), OUTSIDE
  the operator profile `C:\Users\nicol` (which is not traversable by the worker).

## Result (worker view, from TOOLCHAIN-RESULTS.txt)
- Toolchain write-denial: python/claude/codex/gnosis/node all WRITE-DENIED (UnauthorizedAccessException).
- Python: 3.12.14; stdlib imports OK; `import gnosis.kernel.canonical` OK; pytest `1 passed in 0.03s`.
- Node v24.19.0; Git commit PASS; Claude 2.1.246 STARTUP PASS; Codex-cli 0.148.0 STARTUP PASS
  (both startup-only, --version, no login/provider request — missing-auth is EXPECTED ISOLATION).
- Import poisoning: worker planted evilmod.py in its CWD; trusted import from RX-only ToolRoot
  stayed TRUSTED_IMPORT_STILL_CLEAN.
- Credential isolation: operator `.claude` / `.codex` / `.ssh` ABSENT-from-worker.

## Hygiene notes
- `pycache_in_toolchain_after = True` = pyc PRE-EXISTING from the venv site-packages copy +
  an admin self-test; worker writes to the toolchain are all denied, so pytest ran without
  caching bytecode into the RX root. RX-only does not break pytest.
- Secret scan: only match is the SecureString VARIABLE reference `-Password $secure` in the
  orchestrator (no value). No password/token/key value in any artifact.

## Reversibility
Full rollback verified: no Gnosis* users / services / scheduled tasks / Win32 profiles;
toolchain root and probe dir deleted; no operator/production ACL changed (real paths were
only read/copied-from). HEAD unchanged. This probe does NOT close F-17.
