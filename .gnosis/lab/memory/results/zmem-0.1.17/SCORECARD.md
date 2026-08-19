# zmem 0.1.17 revalidation scorecard (Nicol workstation, 2026-08-19)

Fresh clone `external/repositories/zmem` @ `84ffd2de` (v0.1.17; the
M3-milestone evidence was v0.1.16 from the reference corpus). Installed
as an isolated uv tool from a copy; all commands below executed for real
against the project workspace (`zmem init` at repo root, `.zerker/`).

## Re-confirmed on 0.1.17 (matches the 0.1.16 scorecard)

- `remember` (system) → active, trust 0.9; `propose` (agent) →
  quarantined, trust 0.5. Default `search`/`inject` exclude quarantine.
- `inject` receipt: Merkle proof root + per-memory leaves + `action_id`
  (`inject_pre_revoke.json` here).
- Revocation: post-revoke `inject` returns only the surviving fact;
  `why act_62c07ebd66f84400` still shows the revoked memory shaping the
  earlier action, labeled `[semantic/revoked]`
  (`why_pre_revocation_action.txt` here).
- `audit health`: healthy=true, honest "lexical signals only" limitation
  (`zmem_audit_health.json` here).
- Still no automatic supersession reachable from the CLI: two same-label
  contradictory facts both stayed active until explicitly revoked.

## New findings on this machine (Windows 11)

1. **`zmem status`/`zmem doctor` crash with WinError 32** at
   `doctor.check_eval → eval.run_eval → TemporaryDirectory.cleanup`:
   the eval helper's SQLite handle is still open when the temp dir is
   removed (POSIX tolerates that; Windows does not). Deterministic,
   diagnostic-only — every core memory command works. Use `audit health`
   as the Windows health probe.
2. **Standalone `--db <path>` mode works without `init`** and without
   registering anything in `~/.zmem/workspaces.json` — used by
   `tests/integration/test_memory_fabric_smoke.py` for hermetic tests.

## Verdict

ADOPT-COMPLEMENT-track for the governance role, unchanged. Windows
diagnostic crash is worth an upstream report but does not affect the
memory plane itself.
