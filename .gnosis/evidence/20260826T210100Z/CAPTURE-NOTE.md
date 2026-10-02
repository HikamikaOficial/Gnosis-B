# F-17 DEDICATED-WORKER FEASIBILITY PROBE — evidence

Executed under operator authorization; reversible; rolled back. A disposable
non-admin local user (GnosisWorkerProbe, group Usuarios only, NOT admin) was
created, probed, and deleted. Password was a runtime-only SecureString (never
in source/repo/logs/evidence). Probe infra under C:\ProgramData (disposable).

RESULT (as the dedicated worker user, SID distinct from the operator, Medium integrity):
- Token privileges: ONLY SeShutdown/SeChangeNotify/SeUndock/SeIncreaseWorkingSet/
  SeTimeZone. NO SeDebug/SeBackup/SeRestore/SeTakeOwnership/SeImpersonate — not
  even present (unlike the lowered-elevated MIC token which retained all 24).
- ACL: worktree write/create/delete ALLOWED; tcb_read ALLOWED, tcb_write DENIED;
  runid_read ALLOWED, runid_write DENIED; anchor create/delete/rename/change_dacl/
  take_owner/lower_label ALL DENIED (NTFS ACL by SID, not MIC).
- Cross-process: OpenProcess(High Director, {VM_WRITE,DUP_HANDLE,CREATE_THREAD,
  CREATE_PROCESS,VM_OPERATION}) ALL DENIED err=5.
- Credential isolation: operator .claude/.codex/.gitconfig/.ssh NOT ACCESSIBLE
  (the worker cannot traverse the operator profile).
- Toolchain: Git PASS (Program Files, shared). Python/Claude/Codex NOT ACCESSIBLE
  (operator-profile-bound) -> compat cost: the toolchain must be relocated/shared
  for a dedicated worker; codex NOT TESTED (needs node/npm).
- Rollback: user + profile + probe dirs removed; POST-FLIGHT clean; HEAD unchanged.
  (Note: the probe dir needed Remove-Item -Force for read-only git objects, done
  manually; the orchestrator should use -Force.)

Verdict: the dedicated-worker boundary is QUALIFIED on security. Compat cost:
toolchain relocation for the worker; per-profile credential provisioning.
No production wiring done. F-17 stays OPEN.
