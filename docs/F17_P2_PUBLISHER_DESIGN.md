# F-17 P2 Trusted Publisher Service — Design & Probe Plan

**Status:** DESIGN ONLY. No service installed. No persistent Windows change made.
This document is for operator review BEFORE any authorization to provision.
**F-17 stays OPEN.**

The seventh/eighth reviews selected **P2 (minimal service-SID publisher)** as the
target and **P1 (Director-High)** as fallback/interim. This designs the P2
primitive and a reversible probe plan, and — per the operator's TCB correction —
keeps the Trusted Computing Base **minimal**: the Worker plane (Claude, Codex,
dev-python, Git, Node, pytest, repos, worktrees, generated code, tests,
engineering tools) is **NOT** in the TCB.

The single guarantee P2 must deliver:

```text
Worker SID cannot obtain Publisher authority.
```

NOT "an administrator/SYSTEM cannot compromise the service" — that is T4, out of
scope (see §19–20).

---

## 0. Grounding (read-only, this machine, 2026-08-27)

Real data used to ground the SDDL / SID / privilege design (no changes made):

- `sc qsidtype W32Time` → UNRESTRICTED; `sc qprivs W32Time` → a **reduced** privilege
  set (SeAudit, SeChangeNotify, SeCreateGlobal, SeSystemTime, SeImpersonate),
  proving per-service privilege reduction via `sc privs` is real and enforced.
- `sc sdshow W32Time` →
  `D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)(A;;CCLCSWLOCRRC;;;IU)(A;;CCLCSWLOCRRC;;;SU)(A;;CCLCSWRPLOCRRC;;;LS)(A;;CCSWWPLORC;;;LS)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;S-1-5-80-3169285310-…)`
  — the exact ACE shape for the service object: SYSTEM/Admins control, the
  per-service SID control, interactive/service users read/query only.
- `NT SERVICE\TrustedInstaller` resolves to `S-1-5-80-956008885-…` — the
  `S-1-5-80-<hash(name)>` per-service SID mechanism is present, so
  `NT SERVICE\GnosisTrustedPublisher` has a deterministic, computable SID.

---

## 1. Service identity — SELECTED: standalone Virtual Service Account

| Option | What it is | Verdict |
|---|---|---|
| **A. Virtual Service Account** `NT SERVICE\GnosisTrustedPublisher` | Per-service managed account; primary identity = the service SID `S-1-5-80-<hash>`; auto-managed secret; **no interactive logon**; **not shared** with any other service; own minimal profile, no shared registry hive. | **SELECTED** |
| B. LocalService + service SID | The per-service SID still isolates the DACL, but `NT AUTHORITY\LocalService` is a **shared** account used by many OS services; shared profile/temp and a shared registry hive enlarge the surface; presents anonymous creds on the network. | Rejected (shared surface) |
| C. Other minimal built-in | No built-in gives a dedicated, non-shared identity with a computable per-service SID that A does not already give. | No advantage |
| `LocalSystem` | Fully privileged, SID = SYSTEM. | **Refused** — excessive; would put the publisher in T4; no inevitable need shown. |
| Interactive admin account | Interactive logon + admin group. | **Refused** — excessive, interactive, non-minimal. |

**Why A:** it yields a dedicated SID owned by nothing else on the machine, so
every DACL that names it isolates by *this* service alone; the worker (a
different SID) has no path to it; no password we manage or could leak.

`obj= "NT SERVICE\GnosisTrustedPublisher"` (no password) is the provisioning form
that creates the virtual account. Final name may change.

---

## 2. Service SID type — DESIGN: `SERVICE_SID_TYPE_RESTRICTED` (probe is the decider)

Not chosen by the safer-sounding name; chosen by token behavior and compat.

- **RESTRICTED** adds the service SID to the token's **restricting-SID** list →
  a **write-restricted** token: *every* access check (read AND write) is
  evaluated twice — once against the enabled SIDs, once against the restricting
  set — so the process can touch **only** objects whose DACL explicitly grants
  the service SID. The publisher's entire legitimate footprint is exactly four
  objects (trust code root RX, RunIdentity store R, AnchorStore RW, its own
  pipe). Restricting the token to precisely that set is the strongest form of
  "minimum authority" and shrinks the blast radius of a *confused* publisher to
  nothing outside those four.
- **UNRESTRICTED** (what W32Time uses) is simpler but lets the publisher's
  identity reach anything its SID/groups can reach.

**Decision:** design for **RESTRICTED**. Cost, which the probe MUST verify: under
a write-restricted token the process can only start python and read its stdlib if
the **trust code root + the dedicated python runtime + RunIdentity + AnchorStore
+ the pipe** all grant the service SID (RX for code, RW for the ledger). The probe
(§19, tests 17–20 + a startup check) is the decider; **fall back to UNRESTRICTED
only if the probe shows a required access is infeasible under write-restriction**,
never for convenience.

---

## 3. Least privilege — enumerated

Target privilege set after `sc privs GnosisTrustedPublisher …`:

- **SeChangeNotifyPrivilege** — traverse-checking (effectively always present;
  needed to walk the trust paths). KEEP.
- *(only if the pipe is placed in the Global namespace)* SeCreateGlobalPrivilege
  — **avoided**: the pipe is a local `\\.\pipe\…` name; not needed.

**Explicitly NOT held / to be stripped** (justification: the publisher never does
the operation that would need them):

SeDebugPrivilege (never opens another process for write/inject),
SeImpersonatePrivilege (**does not impersonate the caller** — it reads the caller
SID via `GetNamedPipeClientProcessId` → `OpenProcess(QUERY_LIMITED)` →
`OpenProcessToken(TOKEN_QUERY)`; §12), SeBackup/SeRestore/SeTakeOwnership (never
bypasses DACLs / takes ownership), SeTcbPrivilege, SeAssignPrimaryTokenPrivilege,
SeCreateTokenPrivilege (never constructs or assigns tokens). It holds **no**
network / Claude / Codex / Git / SSH credentials — none are provisioned into its
account or environment.

If any dangerous privilege turns out to be structurally required, the design is
wrong and must be revised — not the privilege granted silently.

---

## 4. Service-object DACL — worker has ZERO access to the service

The worker cannot be allowed to touch the service object at all. Modeled on the
grounded W32Time SDDL, worker gets **no ACE** (default-deny by absence):

```text
D:(A;;CCLCSWRPWPDTLOCRSDRCWDWO;;;SY)      ; SYSTEM     — full (T4, management/recovery)
 (A;;CCLCSWRPWPDTLOCRSDRCWDWO;;;BA)      ; Admins     — full (T4)
 (A;;CCLCSWRPLOCRRC;;;<TRUSTED-MAINT-SID>) ; maint principal — query+start/stop for lifecycle
;  NO ACE for the Worker SID — no SERVICE_QUERY_STATUS, no anything
S:(ML;;NW;;;HI)                          ; High mandatory label (DiD)
```

By construction the worker is denied **SERVICE_CHANGE_CONFIG, SERVICE_START,
SERVICE_STOP, SERVICE_PAUSE_CONTINUE, WRITE_DAC, WRITE_OWNER, DELETE** and cannot
change **ImagePath, account, arguments, service binary/DLL, startup config,
failure actions, or the security descriptor** — it has no rights on the object.
Set with `sc sdset`. (SYSTEM/Admins retain full: that is T4, unavoidable and
declared, not a claimed boundary.)

---

## 5. Trust-plane location — semantics, not convenience

- **Code / immutable binaries + dedicated python runtime + TCB package** →
  `C:\Program Files\Gnosis\Trust\` (Program Files is Users-RX, admin-write by
  default → worker cannot write). DACL: service SID **RX**, Admins/SYSTEM full,
  worker **no ACE**, `inheritance:r`.
- **Mutable protected state (AnchorStore ledger, RunIdentity store)** →
  `C:\ProgramData\Gnosis\Trust\` (machine-wide mutable state) with a **tightened**
  DACL (ProgramData's default grants `Users:write` via inheritance — that is
  removed: `inheritance:r`, then explicit ACEs only).

Rationale is the Windows semantic split (executables in Program Files, machine
mutable state in ProgramData), not disk convenience.

---

## 6. AnchorStore & RunIdentity locations + ACLs

- **AnchorStore** → `C:\ProgramData\Gnosis\Trust\anchors\anchors.jsonl`
  DACL: service SID **append+read** (`FILE_APPEND_DATA|FILE_READ_DATA`),
  TRUSTED-MAINT full (recovery), SYSTEM/Admins full (T4), worker **no ACE**.
  MIC: High `NO_WRITE_UP` retained as defense-in-depth. Under P2 the **primary**
  boundary is the DACL by service SID (the worker is a different SID), not MIC.
- **RunIdentity store** → `C:\ProgramData\Gnosis\Trust\runidentity\<run_id>.json`
  DACL: TRUSTED DIRECTOR principal **create/update** (lifecycle owner), service SID
  **read**, worker **no write** (worker may not even need read), SYSTEM/Admins full.

**Wiring note (not this unit):** `AnchorStore.__init__`'s current
`require_high` MIC gate (`authority.py:294`) must become "require the trusted
publisher principal" so ownership is by SID, with MIC as DiD.

---

## 7. RunIdentity — the confused-deputy defense

The Director (trusted) writes a `RunIdentity` when it **dispatches** a run:
`{task_id, run_id, repository_id, head_sha, bundle_path, owner_worker_sid}`
(the current `RunIdentity` dataclass at `authority.py:342` + one field:
`owner_worker_sid`). The publisher reads it by `run_id`.

Over the wire the worker may say only, conceptually, **`run_id X appears
complete`**. The publisher takes `task_id / repository_id / head_sha /
bundle_path / owner` **from the trusted store**, never from the worker. This is
exactly what `publish_anchor` already enforces (`authority.py:374` —
identity is a parameter, the digest is recomputed, the bound head is
cross-checked); P2 sources that `identity` from the RunIdentity store instead of
from any caller input.

---

## 8. TCB dependency graph — MEASURED

Runtime import closure on this repo (2026-08-27), `sys.modules` diff:

```text
Path A  import gnosis.kernel.authority + gnosis.kernel.canonical
        → gnosis modules loaded: 4
          gnosis (__init__, 3 lines, 0 imports)
          gnosis.kernel (__init__, empty)
          gnosis.kernel.authority   (424 lines)
          gnosis.kernel.canonical   ( 53 lines)
        stdlib only: hashlib, json, ctypes, subprocess, sys, dataclasses, pathlib, typing

Path B  import gnosis.kernel.evidence_capture.verify_bundle
        → ADDS 4 modules, 3444 lines of CAPTURE machinery the publisher does NOT need:
          evidence_capture (1487) + git_evidence (393) + input_lock (936) + write_observer (628)
```

**The publisher must NOT take Path B.** `verify_bundle`'s job in the publish
protocol is only to **re-derive the bundle manifest digest** and compare it to the
recorded/expected digest — logic that depends solely on `hashlib` + `canonical`
(`sha256_hex`, `hash_canonical`) with **zero** dependency on
git_evidence/input_lock/write_observer. `publish_anchor`/`verify_anchored_bundle`
already accept an injectable `verify=` callable (`authority.py:386,415`) — the
seam is in place.

**Minimal publisher TCB (gnosis code):**

```text
canonical.py                         53 lines   (the one hash contract)
authority.py  (anchor slice)        ~250 lines  (AnchorRecord/AnchorStore/RunIdentity/
                                                 publish_anchor/verify_anchored_bundle/
                                                 _bundle_head_sha/_bundle_content_digest/assert_integrity)
trust/bundle_verify.py (extract)    ~40 lines   (write_bundle_manifest re-derivation + verify_bundle,
                                                 lifted from evidence_capture:1228-1330, hashlib+canonical only)
publisher entry + IPC parser        ~120 lines  (§11 protocol, §12 authz)
─────────────────────────────────────────────
gnosis TCB total                    ~460 lines  + a dedicated python runtime
```

**Recommended refactor (wiring phase, flagged not built):** split
`authority.py` into `trust/launch.py` (the ctypes/MIC launch primitives —
`run_at_integrity`, `lowered_primary_token`, `CreateProcessWith*` — used by the
LAUNCHER, a *different* trusted component) and `trust/anchor.py` (the anchor slice
above). The publisher then excludes the launch/ctypes code entirely, shrinking its
slice further. Launcher-TCB and publisher-TCB are distinct slices of the trust
plane; both are trusted, but each has a narrower compromise consequence.

**Excluded from the TCB (stay Worker-plane):** engine, planner, scheduler, policy,
runner, the Claude/Codex adapters, evidence_capture/git_evidence/input_lock/
write_observer, and every development package. The objective — minimize *code whose
compromise defeats F-17* — is met: ~460 lines + runtime, not `src/` + `.venv`.

---

## 9. Python vs native wrapper — SELECTED: P2A (Python on a dedicated trusted runtime)

| | Approach | TCB | Verdict |
|---|---|---|---|
| **P2A** | Python service on a **dedicated trusted python runtime** in the trust root; reuses the reviewed, mutation-tested `authority.py`/`canonical.py` **verbatim**. | interpreter+stdlib (update surface) + ~460 reviewed lines | **SELECTED** |
| P2B | small native (C/Rust) service wrapper handling SCM + pipe + caller-SID, exec-ing a protected python publisher. | tiny native + python slice; splits the TCB | Reconsider only if P2A's SCM/pipe integration proves fragile in the probe |
| P2C | no resident service — a trigger/broker (scheduled task or service trigger) runs the python publisher on demand under the service account. | same code, lower residency | folded into §14 (startup) rather than a separate impl |

**Why P2A:** a native reimplementation would re-derive the canonical hash contract
in another language — a **second implementation of the trust core**, i.e. *more*
code whose compromise (or divergence from `canonical`) defeats F-17, contradicting
minimality. Reuse the already-reviewed logic. The interpreter's update surface is
the real cost, mitigated by pinning a dedicated runtime in Program Files
(worker-non-writable), recorded by version+hash (§16), and running it isolated
(§10). Revisit P2B only on concrete evidence that python SCM/pipe hosting is
unstable.

---

## 10. Import / DLL / environment hardening — only the surfaces this design uses

The service must not depend on any worker-controlled environment. Concrete design:

- **ImagePath** = absolute path to the trusted runtime with isolated flags:
  `"C:\Program Files\Gnosis\Trust\runtime\python.exe" -I -S "C:\Program Files\Gnosis\Trust\publisher\main.py"`.
  `-I` (isolated) implies `-E` (ignore all `PYTHON*` env vars) and `-s` (no
  user-site); `-S` disables site processing (no `sitecustomize`/`usercustomize`,
  no `.pth`). So **PYTHONPATH / PYTHONHOME / PYTHONSTARTUP / user-site / `.pth`**
  are all neutralized by construction.
- **sys.path** — under `-I -S`, sys.path = the runtime's own stdlib dirs only;
  `main.py` prepends the trust package dir by a **hard-coded absolute path** in the
  trust root, never from CWD/argv. `sys.path[0]` is never a worker-writable dir.
- **CWD** — services start with CWD=`System32`; `main.py` sets an explicit trust
  CWD (or relies on absolute paths everywhere; it uses no relative paths).
- **DLL search** — `python.exe` loads its DLLs from its own (Program Files,
  worker-RX) directory; ImagePath is absolute; ensure no worker-writable directory
  precedes it on the machine `PATH`. Optionally `SetDefaultDllDirectories`.
- **TEMP** — the service account's own profile temp, not the worker's.
- **Registry-backed settings** — none used by the publisher.

No open-ended "audit everything" pass — only the surfaces the selected design
actually touches.

---

## 11. IPC — a one-verb named pipe

- Transport: **named pipe** `\\.\pipe\GnosisTrustedPublisher` (local; message
  mode; `PIPE_REJECT_REMOTE_CLIENTS`).
- The **only** request: `PublishCompletedRun(run_id)` — one field, a bounded token
  (e.g. ≤128 chars, charset `[A-Za-z0-9._-]`). The reply is a small status
  (`ANCHORED | ALREADY_ANCHORED | REJECTED:<reason>`).
- The wire format has **no** field for path, bytes, expected digest, AnchorRecord,
  HEAD, or repository. There is nothing for the worker to forge; the publisher
  derives every fact from RunIdentity[run_id] (§7).

---

## 12. IPC authentication / authorization — no impersonation

On each connection the publisher:

1. `GetNamedPipeClientProcessId` → caller PID; `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`
   → `OpenProcessToken(TOKEN_QUERY)` → caller **user SID**. (No `SeImpersonate`,
   no impersonation of the caller.)
2. **caller SID ∈ allowed-worker-SID(s)?** else reject.
3. Parse the fixed schema; **malformed** → reject; **oversized** (> the byte cap,
   checked before parse) → reject.
4. `RunIdentity[run_id]` lookup; **unknown run** → fail closed.
5. **run ownership:** `RunIdentity[run_id].owner_worker_sid == caller SID`? else
   reject — *a worker cannot publish another worker's run* (cross-run confusion
   blocked even though multi-writer is out of scope).
6. **duplicate:** if already anchored (`AnchorStore.lookup(run_id)` hits) → return
   `ALREADY_ANCHORED` (idempotent, no second append).
7. **stale/replayed:** deterministic — a terminal run yields the same idempotent
   answer; never a second write.

---

## 13. Named-pipe security descriptor

Create the pipe with an explicit SD (owner = service SID):

```text
O:<SVC-SID>
D:(A;;FA;;;<SVC-SID>)                 ; service (server) — full
 (A;;0x0012019B;;;<WORKER-SID>)       ; worker — connect + read/write message only,
                                      ;   NO FILE_CREATE_PIPE_INSTANCE (0x4) → cannot squat/add instances
;  no ACE for anyone else
```

- **Squatting:** the server creates the first instance with
  `FILE_FLAG_FIRST_PIPE_INSTANCE`; if the name already exists (a squatter
  pre-created it) creation **fails closed** and the service refuses to run rather
  than attach to a hijacked pipe.
- **Remote:** `PIPE_REJECT_REMOTE_CLIENTS`.
- The worker's mask grants message read/write and connect but **not**
  `FILE_CREATE_PIPE_INSTANCE`, so it cannot create a competing server instance.

Future tests: unauthorized SID connect → denied; authorized worker → allowed;
worker-for-run-B publishes run-A → rejected (§12.5); malformed → rejected;
oversized → rejected; pre-created/squatted pipe → server refuses; impersonation
behavior = none (documented).

---

## 14. Startup model — minimal residency

Preference: **least residency**. Design = **demand-start** (`start= demand`),
started by the trusted Director when a run begins (or a **service trigger** on
first pipe access), with an **idle self-stop** after N seconds quiet. A permanently
resident service is not required — the guarantee (worker ≠ publisher authority) is
independent of residency, and a smaller resident window is a smaller target. Auto /
Auto-Delayed are rejected as unnecessarily resident for V1. Evaluate
`SERVICE_TRIGGER` vs Director-driven `StartService` in the probe; a broker-on-demand
(P2C shape) is acceptable if it gives the same guarantee stably.

---

## 15. Failure / recovery / idempotency — never a false `ANCHORED`

Publish order (commit point = the append):
recompute digest from bundle bytes → check bound head == RunIdentity head →
compute `(seq, prev)` → **append one record** → **re-read** → confirm. Only after
the confirmed re-read does the publisher answer `ANCHORED`.

- **Crash before append:** nothing written; the run is simply not anchored; the
  Director re-requests → idempotent.
- **Torn/partial final line:** append is a single `record+"\n"` write; NTFS does
  not guarantee atomicity for arbitrary lengths, so add a **two-phase watermark**:
  the committed sequence number is recorded (a `committed` marker) only after the
  confirming re-read. On startup, any ledger line **beyond** the watermark is
  treated as **not anchored** and truncated by the trusted-maintenance path; since
  such a record was never confirmed, the run is re-publishable → idempotent.
- **Duplicate request:** `lookup(run_id)` → `ALREADY_ANCHORED`, no second append.
- **Chain corruption:** `verify_chain()` false → `append` refuses (fail closed) →
  publisher returns `REJECTED`, never `ANCHORED`.

Idempotency key = `run_id`.

---

## 16. Update model (no signing yet)

- Trust-plane package updated **only by a trusted maintenance principal**
  (Admins/SYSTEM); worker-write denied by the Program Files DACL throughout.
- **Package identity/version recorded** — a `VERSION` file + the package's recorded
  content hash in a provisioning record.
- **Atomic replacement** — stage the new package in a sibling dir, stop the
  (demand) service, rename-swap, restart; the worker never has write during any
  window.
- Cryptographic authenticity (a signature over the package + verification at load)
  is **deferred** to a later phase — declared, not faked.

---

## 17. P2 threat model — defeats T2

**T2 (malicious / compromised Worker principal)** is defeated across every vector:

| Vector | Why it fails for the worker |
|---|---|
| filesystem (trust root, AnchorStore, RunIdentity, service binary) | worker has **no ACE** / DACL by service SID; worker is a different SID |
| process (open publisher for write/inject) | different SID + no SeDebug → `OpenProcess(VM_WRITE/…)` DENIED |
| service-control (config/binary/DACL/delete/start/stop) | worker has **no ACE** on the service object (§4) |
| IPC confused-deputy | publisher derives all facts from RunIdentity; worker supplies only `run_id`; SID + ownership checks (§12) |
| bundle forging | publisher **recomputes** the digest from bytes; a bundle whose bytes don't match its manifest fails; a bundle bound to another head is rejected |
| RunIdentity forging | worker cannot write the RunIdentity store |
| AnchorStore forging | worker cannot write the ledger; chain re-verified on every append |
| code poisoning | trust package worker-non-writable; python `-I -S` clean env; no worker-writable `sys.path` entry |

---

## 18. T3 / T4 — explicitly out of scope

- **T3** (trusted Publisher/Director compromised) — NOT claimed.
- **T4** (Administrator / SYSTEM / kernel compromise) — NOT claimed. SYSTEM/Admins
  hold full control of the service and stores by necessity (management/recovery);
  that is declared, not a boundary.

**The F-17 guarantee is exactly `Worker SID cannot obtain Publisher authority`.**
It is not, and must not be written as, "admin/SYSTEM cannot compromise the
service."

---

## 19. Feasibility probe plan (reversible — NOT executed this unit)

All on **disposable** copies and a **probe-suffixed** service; nothing touches a
real path or the real service.

1. **Provision** (throwaway):
   - trust code root `C:\Program Files\Gnosis\TrustProbe\` (disposable copies:
     dedicated python runtime + the ~460-line TCB package); ACL `inheritance:r` +
     service SID RX + Admins/SYSTEM full + worker no ACE.
   - state `C:\ProgramData\Gnosis\TrustProbe\{anchors,runidentity}\`; ACLs per §6.
   - worker: reuse the qualified disposable non-admin user pattern
     (`GnosisWorkerProbe`) to get a real distinct worker SID.
   - service: `sc create GnosisTrustedPublisherProbe binPath= "<runtime> -I -S <main.py>"
     type= own start= demand obj= "NT SERVICE\GnosisTrustedPublisherProbe"`;
     `sc sidtype … restricted`; `sc privs … SeChangeNotifyPrivilege`;
     `sc sdset …` with the §4 SDDL (worker no ACE).
   - pipe SD per §13.
2. **Startup check** (RESTRICTED decider): the write-restricted service actually
   starts, loads python from the trust root, reads RunIdentity, opens the ledger
   for append, and creates its pipe. If any required access is denied → record and
   fall back to UNRESTRICTED, re-run.
3. **Legitimate path:** an authorized worker-SID process sends
   `PublishCompletedRun(run_id)` for a run whose RunIdentity + a
   `verify_bundle`-clean bundle exist → expect `ANCHORED`, one chained record,
   re-read confirmed.
4. **Attack matrix** — run all 24 of §20.
5. **Teardown:** `sc stop` + `sc delete` (removes the service **and** its virtual
   account); delete `TrustProbe` dirs (Program Files + ProgramData); delete the
   worker probe user + profile; verify **zero residual** services / scheduled
   tasks / files / accounts / pipes; confirm **no real path ACL changed**; HEAD
   unchanged. POST-FLIGHT identical in spirit to the toolchain probe's clean
   rollback.

---

## 20. Attack matrix for the probe (expected results)

| # | Attempt (as the worker unless noted) | Expected | Enforced by |
|---|---|---|---|
| 1 | write service binary | DENIED | Program Files DACL, no worker ACE |
| 2 | replace service binary | DENIED | same |
| 3 | change service config | DENIED | service SDDL (no worker ACE) |
| 4 | change ImagePath | DENIED | service SDDL |
| 5 | change service DACL | DENIED | no WRITE_DAC for worker |
| 6 | delete service | DENIED | no DELETE for worker |
| 7 | write RunIdentity | DENIED | ProgramData DACL |
| 8 | write AnchorStore | DENIED | ProgramData DACL |
| 9 | connect IPC as authorized | ALLOWED (authorized only) | pipe SD + §12 |
| 10 | connect IPC as unauthorized SID | DENIED | pipe SD + caller-SID check |
| 11 | send arbitrary path | rejected / no such field | one-verb schema (§11) |
| 12 | send fake digest | rejected / no such field | schema; digest recomputed |
| 13 | send another worker's run_id | rejected | ownership check (§12.5) |
| 14 | stale / replayed request | deterministic idempotent | §12.6–7, §15 |
| 15 | poison publisher import | DENIED / no worker-writable import | `-I -S`, DACL |
| 16 | open publisher process w/ dangerous rights | DENIED | different SID, no SeDebug |
| 17 | publisher reads expected evidence | ALLOWED | trust DACL grants SVC read |
| 18 | publisher recomputes digest | REQUIRED (done) | protocol (§15) |
| 19 | publisher reads trusted RunIdentity | ALLOWED | RunIdentity DACL |
| 20 | publisher appends Anchor | ALLOWED | AnchorStore DACL |
| 21 | service crash during append | no false ANCHORED | watermark recovery (§15) |
| 22 | chain corruption | fail closed | `verify_chain` (§15) |
| 23 | missing RunIdentity | fail closed | §7/§12.4 |
| 24 | missing evidence | fail closed | verify recompute (§15) |

---

## 21. After P2 qualifies (NOT now)

production worker wiring → production publisher wiring → trusted RunIdentity
wiring → §14 unknown-`.git` → full validation → fresh FULL capture → authoritative
anchor → final independent review.

## 22. F-14 — CLOSED. Untouched by this design.

## 23. Scope

Not touched: F-15, F-16, F-18, M11.3, NVIDIA/NIM, multi-writer, self-evolution,
Assurance Program, external repos / `external/repositories/**`. No service
installed; no provider calls; no credentials copied.
