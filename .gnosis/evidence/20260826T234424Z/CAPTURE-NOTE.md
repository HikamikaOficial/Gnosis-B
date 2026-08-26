# F-17 P2 SERVICE-SID PUBLISHER PROBE — capture note

Operator-authorized (HEAD 4ceb667 design + mandatory review corrections),
reversible OS-real probe. F-17 stays OPEN. No production wiring; no service
survives; no real-path ACL changed.

## What ran
- Trust code root `C:\Program Files\Gnosis\TrustProbe\` (disposable copy of a
  dedicated python 3.12.14 runtime + the ~460-line TCB package); ACL allowlist:
  Administrators:F, SYSTEM:F, service SID:(OI)(CI)RX; worker: NO ACE.
- Mutable trusted state `C:\ProgramData\Gnosis\TrustProbe\` (anchors, runidentity,
  bundles, config); ACL: Administrators:F, SYSTEM:F, service SID:F; worker: NO ACE.
- Worker work dir `C:\ProgramData\Gnosis\P2Work\` (worker RW) for the attack scripts.
- Service `GnosisTrustedPublisherProbe`, virtual account `NT SERVICE\GnosisTrustedPublisherProbe`,
  SID type RESTRICTED, privileges reduced to SeChangeNotifyPrivilege, service-object
  DACL = SYSTEM+Admins full, worker NO ACE. Demand-start.
- Disposable non-admin worker `GnosisP2Worker` (group Usuarios), launched via
  CreateProcessWithLogonW (no handle inheritance), crypto-random SecureString
  password (never materialized), deleted in rollback.
- Named pipe `\.\pipe\GnosisTrustedPublisherProbe`, FILE_FLAG_FIRST_PIPE_INSTANCE,
  PIPE_REJECT_REMOTE_CLIENTS; SDDL grants the worker 0x0012019B (read+write-data,
  NOT FILE_CREATE_PIPE_INSTANCE / not GENERIC_WRITE).

## Result = P2 PROBE RESULT: QUALIFIED — RESTRICTED SERVICE SID
OS-real effective token (token-dump embedded in PROBE-RESULTS.txt): user SID = the
service SID; is_token_restricted=true with the service SID in the restricting list;
privileges_present = SeChangeNotifyPrivilege only; integrity High (services default;
the boundary is the DACL-by-SID + write-restricted token, MIC is defense-in-depth).

Attack matrix (worker = distinct non-admin SID): legitimate PublishCompletedRun(run_A)
-> ANCHORED seq=0; duplicate -> ALREADY_ANCHORED; cross-run (run owned by another SID)
-> owner-mismatch; unknown/malformed/oversized -> rejected; worker create-pipe ->
DENIED; worker writes to service binary / trust python / anchor code / RunIdentity /
AnchorStore / shadow-module -> ALL DENIED; worker sc change-config/stop/delete ->
ERROR 5; worker OpenProcess(publisher, VM_WRITE/DUP_HANDLE/CREATE_THREAD/VM_OPERATION/
CREATE_PROCESS) -> ALL DENIED err=5. Pipe squatting: worker pre-created the pipe while
the service was down; the service refused (FIRST_PIPE_INSTANCE failed, "refuse to
attach") and did NOT connect to the worker pipe. Crash consistency: an unconfirmed
ledger record beyond the committed watermark was truncated by the trusted recovery on
restart, and the committed ANCHORED record survived -> never a false ANCHORED.

## SCM host
P2A: a pure-ctypes SCM host (StartServiceCtrlDispatcher / ServiceMain / control
handler / SetServiceStatus) — no pywin32 (keeps the TCB minimal). The service reached
RUNNING, reported status, and stopped cleanly (~360 ms). NO P2A SCM HOST GAP.

## Reversibility
Full rollback verified: no Gnosis* services / users / profiles / scheduled tasks /
files / pipe; no real-path ACL changed; HEAD unchanged (4ceb667). p2_cleanup.ps1 is
the idempotent safety net.

## Hygiene
Secret scan clean: no password/credential/key value. The worker password was a
runtime SecureString ("Aa1!" is a static 4-char complexity seed prefixed to 24
crypto-random chars; the account is deleted). Evidence carries SIDs, SDDL, privilege
names, exit/error codes only. The copied gnosis/kernel/{canonical,authority}.py are
VERBATIM from the repo (HEAD 4ceb667) and are not duplicated in this bundle.
