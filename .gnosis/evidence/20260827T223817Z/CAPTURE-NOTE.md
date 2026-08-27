# F-17 Stage 5 remediation (trusted dedicated-worker launcher) evidence

Gate-1 STOP upheld at `1133548`; **candidate B authorized**. Implementation at
HEAD `6494eb6`, with a follow-up secret-hygiene fix at `35656e4`.

**The blocker, and the shape of the answer.** `CreateProcessWithLogonW` caps
`lpCommandLine` at **1024 characters**; Gnosis's real logical command is
**~12128**. The answer is to stop carrying the payload on the transport at all:
the transport command is a bootstrap path, a spec path and a digest — **264
characters measured OS-real**, against a self-imposed **512 budget that is
enforced with a real refusal** — while the logical argv travels in a **sealed
LaunchSpec** and is re-created **element by element** by the bootstrap *already
running under the Worker SID*, then launched with an ordinary primitive whose
limit is ~32767.

    PROPERTY PROVEN:  logical argv before == logical argv after.

Compared as **vectors**, not as rendered command-line strings, across 14 edge
cases — spaces, quotes, backslashes, trailing backslashes, an **empty
argument**, Unicode, tabs, shell metacharacters and the real 12 kB payload —
directed and OS-real. `%VAR%` and `$VAR` arrive as **literals**, which is the
positive proof that no shell is anywhere on the path. Claude's invocation
semantics are unchanged.

**The seal, two independent controls.** *ACL*: the Worker may READ the launch
root and nothing else — create, write, delete, rename, WRITE_DAC and takeown all
measured **DENIED from inside the worker**. *DIGEST*: `launch_spec_digest`,
derived by the Director from the bytes it **re-read off disk**, carried **on the
command line and not inside the file**, because a value stored beside what it
protects proves only self-consistency (L-0059). A payload that parses to the
right meaning but is **not canonical** is refused too — something re-serialised
it after it was sealed. A NUL in an argument is refused rather than silently
truncated by the OS.

**No handle crosses the boundary.** `CreateProcessWithLogonW` goes through the
Secondary Logon service and inheritance across that is not assumable, so the
output *paths* travel in the spec and the bootstrap opens the endpoints
**itself, as the Worker**. `STARTF_USESTDHANDLES` is never set and the
STARTUPINFO handle fields are never assigned — asserted through the **AST**, so
the comment explaining the choice cannot be mistaken for the choice. The
handle-leak question therefore has a **structural** answer.

**Creation order is the security property.** `CREATE_SUSPENDED` →
`OpenProcessToken` → verify SID / integrity / non-admin / no dangerous privilege
→ create the job (`KILL_ON_JOB_CLOSE`, **no breakaway**) →
`AssignProcessToJobObject` → `IsProcessInJob` → **only then** `ResumeThread`.
Any failure terminates, closes every handle and raises. **Unverified Worker code
never begins execution.** The verdict was **extracted into a pure
`verify_worker_token`** so every refusal is a unit test rather than something
only a real Windows account could reach.

**The three live defects Gate 1 found are repaired, each measured.** **E1**: the
Worker's environment is its **own profile** plus a two-name allowlist — a
sentinel planted in the Director's environment is **absent**, no `CLAUDE_*`
crosses, USERPROFILE/APPDATA/USERNAME are the Worker's (before: the Director's
entire 62-variable environment). The first OS-real run showed USERPROFILE at the
**machine default**, because `CreateEnvironmentBlock` on a bare logon token
returns the default profile; loading the profile was the fix. **H1**: stdin is
**DEVNULL** — `GetConsoleMode` says *not a console*, and data written to the
bootstrap's stdin does not reach the logical command (before: fd 0 on the
Director's real console). `isatty()` still reports True because **NUL is a
character device on Windows**; that quirk is recorded, not papered over, after
the first assertion failed on it. **D1**: a Job Object with
`KILL_ON_JOB_CLOSE`; timeout and cancellation terminate **the job, not the root
PID**. OS-real, a grandchild's marker froze after termination and **zero** worker
processes remained.

**DPAPI, at its real strength.** `CRYPTPROTECT_LOCAL_MACHINE` is **machine**
binding, **not** launcher binding: anything on this machine that can read the
blob can unprotect it, and the NTFS ACL denying the Worker READ is the
authorization boundary. Missing, empty, corrupt and truncated blobs all fail
closed. Plaintext lives transiently in a **mutable buffer zeroized best-effort**
— copies the OS made inside `LogonUser` and seclogon are outside this process's
reach and are **not** claimed to be erased.

**Two of our own bugs, recorded rather than smoothed over.** Stripping trailing
NUL *bytes* from a UTF-16-LE secret ate half a code unit and produced an
undecodable buffer; NULs are now removed in **pairs**. And the probe's password
generator satisfied Windows complexity with a **fixed prefix**, putting a literal
password fragment in the repository — flagged by our own secret scan, not by
review — while the probe's plaintext check scanned for *that same prefix*, so the
check and the defect propped each other up. Every character now comes from
`secrets`, and the check scans for the **actual generated secret**.

**Seven mutants survived the first run and five tests exist because of them** —
the runner guard had no test at all; the admin and dangerous-privilege checks
were reachable only through ctypes (repaired by *extracting* the verdict); the
containment gate had no order assertion; **the breakaway mutant satisfied the old
flag assertion by ORing onto it**, so the check passed while containment was
gone; stdin inheritance had no behavioural test; the digest surfacing was
unasserted. After repair: **25/25 caught, 0 survivors**.

**A real provisioning finding, not a probe artefact.** `claude.exe` lives in the
**Director's profile** and is unreachable by a dedicated worker (first OS-real
run: `PermissionError`). The probe **relocates** it and it then runs — the
documented compat cost already priced in by the earlier qualification, and
**Stage 8 must perform that relocation for real**.

**No same-user fallback.** `WorkerLauncher` Protocol, `TrustedWindowsWorkerLauncher`
for production, an explicit test fake that is **refused** when the trusted launch
is required, and **no try/except around the launch** — with a test proving the
command does not run *at all* when the trusted launch is unavailable.
`ExecutionResult.command` keeps its historical **logical** meaning so replay and
cassettes are untouched; the transport is recorded in a new
`ExecutionResult.launch` and never merged into `command`.

OS-real probe **59/59 checks passed** with verified rollback (account deleted,
profile removed, root removed, no service/task/production ACL); directed **56
passed**; mutation **25/25**; **full suite 1346 passed / 98 subtests, GREEN**;
fresh checkout of `6494eb6` 179 passed; mypy strict clean over 68 source files;
ruff clean on every new and changed file; negative control and secret scan (0
findings).

TCB: `TRUST_ALLOWLIST` **+3** and `TRUST_ENTRY_POINTS` **+3** by explicit diff;
Trust Plane 3005 → 4295 LOC. **The bootstrap's own closure is eight modules** —
the number that matters most, because that code runs *as the Worker*. Also in the
TCB and **reported rather than hidden**: the 62 MB / 3434-file Python runtime the
bootstrap executes on, which must be Worker-RX and WRITE-DENIED.

Nothing production was created or modified: no production account, service, path
or ACL. F-14 remains **CLOSED**. Stage 6 NOT started. F-17 stays **OPEN**.
See `STAGE5-RESULTS.txt`.
