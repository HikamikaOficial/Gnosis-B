# F-17 DEDICATED-WORKER FEASIBILITY PROBE — plan (awaiting operator authorization)

Architecture APPROVED (ADR-0027 seventh review): dedicated non-admin worker
user + trusted publisher principal; NTFS ACL by SID PRIMARY; MIC defense-in-depth;
explicit handle policy; minimal semantic IPC; minimal TCB. F-17 stays OPEN.

**This probe is NOT executed yet.** It creates a local Windows account, so it
needs operator authorization. Everything below is design only. Read-only recon
already done (Windows 11, Spanish locale; `nicol` = `S-1-5-21-1160728320-3593568380-93362170-1000`).

## 1. Local-user design

- Name: `GnosisWorkerProbe` (disposable, recognisable).
- Local, **non-admin**, password auto-generated in-memory for the probe only.
- Groups: **only `Usuarios`** (Users, `S-1-5-32-545`) — the default for a new
  local user. Explicitly NOT: `Administradores`, `Operadores de copia de
  seguridad` (Backup Operators → SeBackup/SeRestore), `Usuarios avanzados`
  (Power Users), `Operadores criptográficos`, `Usuarios de administración
  remota`/`de escritorio remoto`, `Duplicadores`, or any privileged group.
- No logon rights beyond interactive/batch needed to launch it; no network
  logon rights granted.
- Flags: password never expires (probe lifetime only); account disabled/deleted
  at cleanup.

## 2. Proposed SID/group model

- Worker SID = the new account's SID (distinct from `…-1000`).
- Membership: `Usuarios` + the implicit `Authenticated Users` (S-1-5-11),
  `Everyone` (S-1-1-0), `INTERACTIVE`. These are what the ACL DENY/omission must
  account for (do not grant the worker via a broad `Users` allow on trusted
  objects).
- Trusted principal SID = P1 `nicol` (High) OR P2 a service SID (see §15/§16).

## 3. ACL matrix (exact)

Prefer a clean **allowlist** (grant only the worker SID what it needs; do not
grant `Users`/`Everyone` on trusted objects) over relying on explicit DENY;
add DENY only as belt-and-braces on the AnchorStore.

| object | worker SID | trusted principal | inheritance |
|---|---|---|---|
| worktree root | **Modify (RXWD)** | Read | (OI)(CI) |
| toolchain (venv python, claude, codex) | **Read&Execute** | R/RX | (OI)(CI), read-only |
| trusted-code / TCB package | **Read max, WRITE DENIED** | RX (owner) | (OI)(CI) |
| RunIdentity store | **no ACE (implicit deny) + explicit DENY write** | RW | (OI)(CI) |
| AnchorStore | **explicit DENY (WD,AD,WDAC,WO,DE)** | RW | (OI)(CI) |

Trusted principal gets only: RW on AnchorStore + RunIdentity, R on
worktree/evidence, RX on the TCB. No general grants.
Inheritance: containers use (OI)(CI) so new files inherit; the AnchorStore/TCB
must not have an inheritable worker-writable ACE from a parent (probe verifies
effective, not just explicit, ACLs via `icacls` and an access check).

## 4. Launcher alternatives (compare; implement none)

- **Probe:** `CreateProcessWithLogonW` (or `Start-Process -Credential`) — needs
  the password in memory for one launch; acceptable for a probe, **not** for
  production.
- **LogonUser + token lifecycle:** `LogonUser(LOGON32_LOGON_BATCH)` →
  `CreateProcessAsUserW` (needs SeAssignPrimaryTokenPrivilege, which the elevated
  Director holds? — audit; else CreateProcessWithTokenW with the logon token) →
  cache the token, not the password. Better for repeated launches.
- **Broker/service:** a small trusted launcher (P2 service) that holds launch
  authority and spawns workers on request over semantic IPC — no password in the
  worker plane at all. Preferred for production.
- Selection deferred to the results; production must not store a plaintext
  password (see §5).

## 5. Password / token lifecycle (no credential storage yet)

Production must NOT put a password in repo/JSON/source/persistent env/logs/
evidence. Options: (a) a token cached by a broker (LogonUser once, reuse the
token); (b) a gMSA/virtual service account (no password managed by us); (c) DPAPI
under the trusted principal if a secret is unavoidable. The probe uses a
transient in-memory password, zeroed after launch, never written.

## 6. Profile behaviour

A new user gets a fresh profile (`C:\Users\GnosisWorkerProbe`) on first
interactive/`LOGON_WITH_PROFILE` launch — separate `%USERPROFILE%`, `%APPDATA%`,
`.gitconfig`, `.claude`, `.codex`. This is the isolation we want AND the compat
cost (the worker starts with none of nicol's config/credentials).

## 7. Python feasibility plan

The Gnosis interpreter is `…\GnosisAgentAi\.venv\Scripts\python.exe` under
nicol's Desktop → **not readable by another user by default**. Probe: grant the
worker SID RX on the venv (and the repo's `src`), then verify: python starts,
imports `gnosis.*`, runs `pytest` in a disposable temp repo, writes
`__pycache__` only where allowed (trusted `src` is read-only → runs from `.py`,
no cache — verify it still imports). The WindowsApps `python.exe` stub is under
nicol's profile and irrelevant.

## 8. Git feasibility plan

`git.exe` is in `C:\Program Files\Git` → already RX for all users. Probe: `git
status`/`git diff`/`git commit` in a disposable repo as the worker (its own
`.gitconfig` in its profile; set `user.name/email` locally). `credential.helper`
is empty globally → a push would need a worker-scoped credential (see §11); the
probe does no push requiring the operator's credentials.

## 9. Claude feasibility plan

`claude.exe` is `C:\Users\nicol\.local\bin\claude.exe` (under nicol's profile) →
grant RX to the worker (or note relocation). Probe: **launch `claude --version`
/ startup only** under the worker — verify the binary starts under the identity;
it will find no `~/.claude` auth in the worker profile (expected). **No provider
calls.**

## 10. Codex feasibility plan

`codex` is `C:\Users\nicol\AppData\Roaming\npm\codex.ps1` (needs PowerShell +
node/npm, under nicol's profile). Probe: verify the launcher resolves + starts
under the worker (grant RX to the npm dir + node); no login, no provider calls.
Flag: a `.ps1` launcher pulls in node/npm resolution — record what the worker
needs.

## 11. Credential model

Per-profile by design: `.claude`, `.codex`, `.gitconfig`, Windows Credential
Manager, `.ssh` (absent here) all live in the user profile. The worker gets its
own → **isolation**. To let the worker USE a provider later, provision a
**worker-specific, minimum-scope, independently-revocable** credential in the
worker profile — never copy nicol's `.claude`/`.codex`/admin SSH/browser/global
secrets. The trusted publisher needs NO provider credentials.

## 12. Network model

A local `Usuarios` account has normal outbound connectivity; proxy/env is
per-user (fresh). No firewall changes this phase. Document only: outbound
allowed, no user-specific proxy inherited, no credential in network config.
Network isolation is a later phase unless needed to demonstrate the boundary.

## 13. Cross-process test plan (worker → Director)

From the worker, expect **DENIED** on `OpenProcess(Director,X)` for X in
{PROCESS_DUP_HANDLE, PROCESS_VM_WRITE, PROCESS_VM_OPERATION, PROCESS_CREATE_THREAD,
PROCESS_CREATE_PROCESS} and on `OpenProcessToken(Director)`. Audit no privileged
handle reaches the worker via stdin/stdout/stderr/pipes/process/thread/token
handles (launcher passes none; if IPC needs one, STARTUPINFOEX handle allowlist).

## 14. Token privilege test plan

Dump the worker's effective token: `whoami /user /groups /priv`, integrity level,
and a ctypes `TokenPrivileges` enumeration. **Assert PRESENT-set excludes**
SeDebug, SeImpersonate, SeTakeOwnership, SeBackup, SeRestore, SeTcb,
SeAssignPrimaryToken, SeCreateToken (a fresh standard user should not even hold
them — unlike the lowered-elevated MIC token which retains all 24). "not
Administrator" is not sufficient — check the actual privilege set.

## 15. P1 — Director-as-publisher design

Publisher = the existing elevated High `nicol` process. AnchorStore/RunIdentity
DACL grants `nicol` RW and denies the worker SID. Simplest; **but** keeps the
elevated TCB large (all of nicol's High authority is the publisher). Acceptable
interim; not TCB-minimal.

## 16. P2 — service-SID publisher design (preferred to investigate)

A minimal Windows service running as a **virtual service account**
(`NT SERVICE\GnosisPublisher`, its own service SID) or LocalService — **never
LocalSystem**. Determine: base account (virtual service account preferred, no
password); service SID for AnchorStore/RunIdentity/TCB ACLs; **minimal
privileges** (deny interactive logon; only what write+read needs); IPC = a named
pipe with a **semantic** contract (`AnchorPublishRequest{run_id}` → the service
reads its own RunIdentity, opens the derived bundle, `verify_bundle`, recomputes
the digest, writes the AnchorStore) — never `write(path,bytes)`; startup =
manual/triggered; recovery = restart policy; update = signed/ACL-protected TCB
package; trusted code under the service-SID-owned root. Publisher needs NO
Claude/Codex/Git/SSH credentials. Reduces the elevated TCB vs P1.

## 17. P1 vs P2 comparison

| | P1 Director High | P2 service SID |
|---|---|---|
| elevated TCB size | large (all High authority) | **minimal (service only)** |
| distinct principal for ACL | no (nicol) | **yes (service SID)** |
| password/secret | none (already running) | **none (virtual account)** |
| complexity | low | medium (service + IPC) |
| recommendation | interim | **target** |

## 18. TCB package proposal

`TRUST PLANE PACKAGE` = a minimal, worker-non-writable set: the trusted launcher,
RunIdentity store/reader, AnchorStore, evidence verifier (`verify_bundle`),
publisher, and a **dedicated trusted Python runtime** (a protected interpreter +
just these modules) — NOT all of `src/` + `.venv`. Location: a root owned by the
trusted principal with RX-only for the worker (e.g. `%ProgramData%\Gnosis\trust`
or a service-SID-owned dir), version/identity checked by a manifest the publisher
verifies at startup. `GNOSIS WORKER CODE` (Claude, Codex, work repos, generated
code, tests, dev tools) stays worker-owned/writable. Not a big refactor now — the
package boundary is the design; extraction happens at wiring.

## 19. Exact OS changes the probe WOULD make (all reversible)

1. Create local user `GnosisWorkerProbe` (net user / New-LocalUser), member of
   `Usuarios` only.
2. Create disposable dirs (worktree, anchor, runidentity, tcb, toolchain-copy or
   grants) under the scratchpad.
3. `icacls` grants/denies per §3 on those disposable dirs (and RX grants on the
   real venv/claude/codex paths — **or** copy a minimal toolchain into a probe
   dir to avoid touching real ACLs; prefer the copy to keep real paths untouched).
4. Launch processes as the worker (CreateProcessWithLogonW) — transient.
5. No service, no firewall, no credential storage, no changes to engine/runner/
   production/real repo security descriptors.

## 20. Rollback procedure (exact)

1. Kill any worker processes.
2. Delete the user: `net user GnosisWorkerProbe /delete` (and remove its profile
   dir `C:\Users\GnosisWorkerProbe` if created).
3. Remove all disposable probe dirs.
4. Revert any `icacls` grants made on REAL paths (venv/claude/codex) — recorded
   before/after, or avoided entirely by using toolchain copies.
5. Confirm no orphan user/service/task/credential remains
   (`Get-LocalUser gnosis*`, `Get-Service *Gnosis*`, `schtasks`).
6. Confirm real security descriptors unchanged.

## 21. Risks

- Provisioning a local user is a system-state change (operator approval).
- Granting the worker RX on toolchain under nicol's profile touches real ACLs —
  mitigate by copying a minimal toolchain into the probe dir instead.
- The worker profile creation writes `C:\Users\GnosisWorkerProbe` — removed at
  rollback.
- Claude/Codex startup under a new profile may prompt/behave differently — probe
  only tests binary startup, no provider calls.
- If cleanup is interrupted, a stray user/dir could remain — the probe script
  restores in a finally and the rollback checklist above verifies.

## 22. Operator approvals required (exact)

1. **Create/delete a local non-admin Windows user** `GnosisWorkerProbe`.
2. **Launch processes as that user** (CreateProcessWithLogonW) for the probe.
3. Either **grant the worker SID RX on the real venv/claude/codex paths** OR
   approve **copying a minimal toolchain** into a probe dir (recommend the copy).
4. Permit the probe to **start** the Claude/Codex binaries under the worker
   identity (startup only, **no** provider calls, no login).
5. Confirm the **rollback** (§20) is acceptable and complete.
