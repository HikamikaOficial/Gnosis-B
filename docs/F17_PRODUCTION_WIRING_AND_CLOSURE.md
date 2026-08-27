# F-17 Production Wiring & Closure — Design Specification

**Status:** DESIGN ONLY. No production wiring, no service install, no capture in
this round. For independent review BEFORE implementation. **F-17 stays OPEN.**

Builds on the qualified primitives: dedicated-worker security boundary
(`20260826T210100Z`), toolchain (`20260826T213728Z`), and the **P2 restricted
service-SID publisher** (`20260826T234424Z`, HEAD 0633f93). This specifies how the
qualified primitives move into the real runtime and how closure is proven.

---

## 0. Frozen architecture (not relitigated)

Dedicated non-admin **Worker user** · **RESTRICTED service-SID Trusted Publisher**
· **NTFS ACL/SID primary boundary** · **semantic named-pipe IPC** · **minimal Trust
Plane** · **MIC only as defense-in-depth**. P1 (Director-High) is no longer the
production architecture; AppContainer is out of F-17. These are settled; only new
evidence reopens them.

---

## 2. Service integrity (not a blocker)

The T2 guarantee comes from **separate Worker SID + NTFS DACL + restricted service
token**, NOT from the publisher being Medium or High. The probe observed the
service token at **High integrity** — the OS default for a service. Lowering it to
Medium buys **no concrete security property** here: the worker is already a
different SID and is DACL-denied on every trust object regardless of the
publisher's IL; MIC is only DiD in this model. Therefore:

> **service integrity != primary security boundary.**

Decision: **keep the qualified configuration** (do not spend F-17 lowering a
cosmetic IL). The T2 guarantee comes from **different SID + DACL + RESTRICTED service
token + protected trust plane**; High is **documented as an observed characteristic
of the service token, not the root of security**. `DEPLOYMENT.json` records the
observed integrity as data, and closure treats it as observed, not as a gate.
Optional later-round DiD (Medium via a lowered token) is neither required nor a
closure gate. T3/T4 remain out of scope.

---

## 3. Trust-plane module split

Do **not** ship `ProbeAnchorStore` (the probe subclass whose only purpose was to
skip the old same-user-MIC check). The production split:

**`src/gnosis/trust/anchor.py`** — the publisher's slice:
`AnchorRecord`, `AnchorStore`, `publish_anchor`, `verify_anchored_bundle`,
`RunIdentity` (+ `owner_worker_sid`, §6), recovery/watermark (§13). Moved verbatim
from today's `kernel/authority.py:246-425` **except** the precondition change below.

**`src/gnosis/trust/launch.py`** — the launcher's slice:
worker identity + launch + token/SID verification + boundary checks. Absorbs the
MIC/token primitives from `kernel/authority.py` (`run_at_integrity:182`,
`lowered_primary_token:156`, `label_high_no_write_up:223`, `assert_integrity:209`,
`process_integrity:139`). Under the frozen P2 model these are **defense-in-depth**,
not the boundary.

The publisher imports **only** `trust/anchor.py` (+ `canonical`, `bundle_verify`,
`pipeserver`, `scmhost`, `publisher`, `tokendump`) — never `launch.py`, never the
engine. Two disjoint TCB slices, each with a narrower compromise consequence.

**`require_high` — evaluated semantically, not turned off.** Today
`AnchorStore.__init__` (`authority.py:287-298`) has two same-user-MIC preconditions:
the `require_high` guard (`:294`, raises unless the process is High integrity) and an
**unconditional** `label_high_no_write_up(root)` (`:298`, relabels the dir High via
`icacls` — which a RESTRICTED, non-elevated service cannot do). Both belong to the
**old** boundary (High publisher vs Medium worker, same user). Under P2 the
authoritative boundary is **OS-enforced by a different mechanism** — a distinct
RESTRICTED **service SID** + the NTFS DACL — so:

- Replace the `require_high` guard with **`assert_publisher_identity()`**: fail
  closed unless the current process token's user SID equals the **expected trusted
  publisher service SID** (from `DEPLOYMENT.json`) AND `is_token_restricted` is true.
  This is the in-process consistency check appropriate to the new model.
- **Remove the runtime `label_high_no_write_up` call** from `AnchorStore.__init__`.
  The MIC High label (if kept as DiD) and the NTFS DACL are applied **at
  provisioning** by the trusted maintenance principal — never by the RESTRICTED
  service at runtime (it cannot relabel, and the DACL, not MIC, is the boundary).

**Principle (must be stated in the ADR):** the real boundary is **OS-enforced**
(service SID ≠ worker SID + NTFS DACL + restricted token, kernel-checked); every
in-process check (`assert_publisher_identity`, chain verification, head binding,
deployment self-check) is **fail-closed consistency / defense-in-depth**, not the
root of trust. Never `require_high = False` as a bare toggle.

## 4. Trust-plane package (what deploys)

Deploy root (code, immutable): **`C:\Program Files\Gnosis\Trust\`**
State root (mutable, protected): **`C:\ProgramData\Gnosis\Trust\`**

```
C:\Program Files\Gnosis\Trust\
  runtime\            dedicated python 3.12.x (python.exe + Lib + DLLs; NO site-packages)
  publisher\
    main.py                         entry (console|service), -I -S hardened
    gnosis\kernel\canonical.py      VERBATIM from repo (the one hash contract)
    gnosis\trust\anchor.py          AnchorRecord, AnchorStore, publish, verify, recovery  (§3)
    gnosis\trust\launch.py          worker identity + launch + token/SID verification     (§3)
    gnosis\trust\bundle_verify.py   minimal manifest re-derivation (hashlib+canonical)
    gnosis\trust\scmhost.py         pure-ctypes SCM host
    gnosis\trust\pipeserver.py      named-pipe server (frozen policy, §12)
    gnosis\trust\publisher.py       publication protocol + IPC handler
    gnosis\trust\tokendump.py       token self-audit (startup evidence)
    DEPLOYMENT.json                 TrustPlaneDeploymentIdentity (§5)
```

**Excluded from the TCB (stay worker-plane):** Claude, Codex, engine, planner,
scheduler, policy, runner, adapters, plugins, the work repo, general tests, and all
development dependencies.

**Measured dependency graph (see §5 of the P2 design, re-verified):** the
publisher's runtime import closure is **canonical.py + the trust package**, stdlib
only (hashlib, json, ctypes, re, os, pathlib, threading, dataclasses) — it never
imports `evidence_capture`/`git_evidence`/`input_lock`/`write_observer` (3444 lines
avoided via the injected `verify=`), nor the engine. Total gnosis TCB code ≈ 460
lines + the dedicated runtime.

---

## 5. Deployed-artifact identity (`TrustPlaneDeploymentIdentity`) — NEW, mandatory

Evidence must prove **the actual trusted deployment**, not merely "source code
somewhere in Git". A `DEPLOYMENT.json` is written under the trust root at
provisioning by the trusted maintenance principal and bound into every anchor.

**Built from OBSERVED state, not desired config (hardening).** Every field is
produced by a **real system query after deployment** — the running service's actual
account/SID/SID-type, the actual on-disk file hashes, the actual security descriptors
read back from the OS — never from the provisioning script's intended values. A
deployment whose *observed* state drifts from what was intended is caught because the
identity reflects reality. Before hashing, every **security descriptor is
canonicalized** (parse SDDL → normalize ACE order/flags/SID form → re-serialize a
canonical form) so the digest does not depend on incidental `icacls`/`sc` CLI output
formatting, ACE ordering, or locale.

Binds, at minimum (each value **observed**):

| field | value |
|---|---|
| `source_commit` / `source_tree` | the repo commit + tree the package was built from |
| `package_version` | monotonic trust-plane package version string |
| `file_hashes` | SHA-256 of **every** deployed file under `publisher\` (map path→hash), one root digest over the map |
| `runtime_identity` | python.exe hash + `sys.version` + platform tag |
| `service_name` | production service name |
| `service_imagepath` | exact ImagePath string |
| `service_sid` | `S-1-5-80-<hash>` |
| `service_sid_type` | must equal `RESTRICTED` |
| `service_object_dacl` | canonical SDDL of the service object |
| `trust_root_acl` | canonical SDDL/owner of `Program Files\Gnosis\Trust` |
| `runidentity_store_acl` | canonical SDDL of the RunIdentity store |
| `anchorstore_acl` | canonical SDDL of the AnchorStore dir |
| `pipe_policy_version` | pipe name + SDDL + flags (FIRST_INSTANCE, REJECT_REMOTE) hash |

**Property:** at publish time the publisher records the current
`deployment_digest` into the `AnchorRecord`; at closure, the fresh capture asserts
the running deployment's re-computed identity **equals** the recorded one. A bundle
that verifies but was produced by a different deployment is caught. The publisher
also **self-checks** the subset it can observe (its own `file_hashes`, service SID,
SID type, is_restricted, trust-root readable-not-writable) at startup and fails
closed on mismatch — DiD; the authoritative binding is the recorded digest in the
anchor + the closure assertion.

---

## 6. RunIdentity — authoritative creation

`owner_worker_sid` is APPROVED. It must be populated from the **OS-real identity the
trusted launcher observes**, never from a worker-supplied name/env/bundle/IPC/config.

Flow (in `trust/launch.py`, run by the Director):

1. the Director launches the worker (§9/§10) and holds the worker **process handle**;
2. `OpenProcessToken(worker_process, TOKEN_QUERY)` → `GetTokenInformation(TokenUser)`
   → the worker's **exact user SID**;
3. validate it equals the configured expected worker SID (fail closed otherwise);
4. create the trusted `RunIdentity` and store the **SID** (not the account name).

The **SID is the authoritative value.** Final `RunIdentity` schema (extends
`authority.py:341-351`), written only by the Director to the RunIdentity store
(worker WRITE-denied):

```
RunIdentity{ task_id, run_id, repository_id, head_sha, bundle_path,
             owner_worker_sid,            # exact TokenUser SID observed at launch
             deployment_digest,           # the trust-plane deployment it belongs to (§5)
             lifecycle: "PUBLISHABLE" }    # trusted publish gate (§7)
```

Optional binding to the existing ownership plane: the run's `task_id` is already
bound to a `holder` with a monotonic `epoch` in `claims.py` (`TaskClaim.holder`,
`.epoch`, `claims.py:78-112`). The wiring may set `holder = owner_worker_sid` so the
claims plane and the RunIdentity agree on the owning SID; the `epoch` supplies a
generation (§7). This reuses an existing primitive rather than inventing one.

## 7. Run lifecycle / publish authorization

There is today **no** `PUBLISHABLE`/`ANCHORED` state; `RunState`
(`state_machine.py:190`) is PENDING→RUNNING→SUCCEEDED/FAILED/…, persisted per run in
`RunMeta.state` (`run_store.py:40,104`), and `TaskState.COMPLETED` is evidence-gated
(`state_machine.py:145-187`). "Anchored" is a separate ledger record, not a state.

Add a **trusted publish gate** so that *worker owns run* does NOT imply *worker may
anchor it at any time*:

- The Director marks a run **publishable** only after the trusted terminal-success
  path (`RunState.SUCCEEDED` in the trusted `RunMeta`, and — where a task gate
  applies — `TaskState.COMPLETED` via the evidenced `complete()` route). It records
  `lifecycle="PUBLISHABLE"` in the trusted `RunIdentity` (Director-written; worker
  WRITE-denied).
- The publisher accepts `PublishCompletedRun(run_id)` **only if**
  `RunIdentity.lifecycle == PUBLISHABLE` **and** no anchor exists yet
  (`AnchorStore.lookup(run_id) is None`). Otherwise fail closed (`not-publishable` /
  `ALREADY_ANCHORED`). This prevents early-anchor and lifecycle confusion.
- The worker cannot drive this transition — it lives entirely in the trust plane.

Minimal generation/nonce: reuse the claims **`epoch`** (monotonic per task,
`claims.py`) as the generation; record it in the `RunIdentity` so a stale re-dispatch
cannot publish against a newer grant. No new nonce subsystem. Conceptual ladder
(names not binding): `DISPATCHED → RUNNING → PUBLISHABLE → ANCHORED`, realized as
`RunState` + the `lifecycle` marker + the `AnchorStore` record — not a fourth state
enum.

## 8. Run-id uniqueness

The guarantee already exists and is **referenced, not re-invented**:
`RunStore.create_run` (`run_store.py:77-79`) creates `runs/<run_id>/` with
`mkdir(exist_ok=False)` → a duplicate `run_id` raises `FileExistsError`. `run_id`
itself (`ids.py:18`) is ms-timestamp + 4 random bytes, so reuse within a RunStore is
prevented at creation.

Two defenses make a deleted-then-recreated run unable to have an **old** bundle read
as the **new** run's evidence:

1. the `AnchorStore` is append-only and `lookup(run_id)` is idempotent, so a run_id
   already anchored returns `ALREADY_ANCHORED` (no re-anchor);
2. `publish_anchor` binds the bundle's `head_sha`/tree to the trusted
   `RunIdentity.head_sha` (`authority.py:392-396`); an old bundle carrying a
   different head is rejected as cross-run/replay regardless of the id.

Closure asserts run_id uniqueness within the qualification RunStore domain; no new ID
primitive is introduced.

## 9. Worker production identity

The probe used a disposable account; production needs a persistent, provisioned one.

| item | production value |
|---|---|
| account | **persistent** local `GnosisWorker` (provisioned once by the maintenance principal, not per-run disposable) |
| kind | non-admin, group **Usuarios** only; admin=false |
| SID | recorded at provisioning into `DEPLOYMENT.json`; the authoritative owner value (§6) |
| privileges | native minimal (as the dedicated-worker probe qualified: SeShutdown/SeChangeNotify/SeUndock/SeIncreaseWorkingSet/SeTimeZone — no SeDebug/SeBackup/SeRestore/SeTakeOwnership/SeImpersonate) |
| profile | its own; the operator profile `C:\Users\<op>` is NOT traversable by it |
| worktree root | `C:\ProgramData\Gnosis\Work\<run_id>\` — worker RW (untrusted code runs here) |
| temp root | a per-worker temp under the worker profile |
| toolchain root | the qualified relocated RX-only toolchain (`20260826T213728Z`): python+pytest, node, git, claude, codex — worker execute, not write |
| credential isolation | operator `.claude`/`.codex`/`.ssh`/`.gitconfig` NOT accessible (proven) |

Per-run worktrees are created/destroyed by the Director (reusing the ADR-0007/0009
worktree lifecycle) under the worker-writable Work root; the trust plane is never
worker-writable. **Not implemented this round** — identity + roots are specified for
review.

## 10. Worker launch credential lifecycle

Today the only launch is a same-user `subprocess.Popen` (`claude_cli_runner.py:97`)
with no OS-user switch. Production must launch the worker **as the dedicated worker
SID** via **`CreateProcessWithLogonW`** (the API the probe qualified — no handle
inheritance).

**Credential contract (corrected).** `CreateProcessWithLogonW` requires the password
to exist **in cleartext in memory during the Windows call**, so we do NOT claim
"password never exists in cleartext". The guarantees are:

- **NO PLAINTEXT AT REST** · **NO PLAINTEXT IN REPOSITORY** · **NO PLAINTEXT IN
  SOURCE** · **NO PLAINTEXT IN JSON** · **NO PLAINTEXT IN PERSISTENT ENV** · **NO
  PLAINTEXT IN COMMAND LINE** · **NO PLAINTEXT IN LOGS** · **NO PLAINTEXT IN
  EVIDENCE**;
- the password may exist **transiently inside trusted-launcher memory** only for the
  duration of the logon primitive;
- **zeroization = BEST EFFORT** (the launcher zeroes its `SecureString`/unmanaged
  buffer after the call); we do NOT promise perfect physical removal of every memory
  copy the OS/CLR may have made.

Compromising the worker password is approximately **T2** (grants worker-level access,
NOT Trust-Plane access, which is DACL/SID-gated). **No general secrets manager / PKI
is introduced in F-17.**

**DPAPI lifecycle.**
- **scope**: `CRYPTPROTECT_LOCAL_MACHINE` = DPAPI protection **bound to the machine**.
  This alone does **NOT** mean "only the launcher/maintenance can decrypt" — any
  process on the machine that can **read** the blob could decrypt a LOCAL_MACHINE
  blob. The boundary that keeps the Worker out is the **NTFS ACL / SID** on the blob
  file, not DPAPI machine-scope. So `Worker cannot decrypt worker.dpapi` holds **only
  under the composition**: *Worker cannot READ the blob (ACL)* **+** *the blob is DPAPI
  machine-protected*. (DPAPI-NG / SID-or-SDDL cryptographic binding is a possible
  future alternative if we later need decrypt-authority bound cryptographically to a
  SID; NOT introduced now.)
- **who can decrypt**: any principal that can both run on this machine AND read the
  blob — restricted to the trusted launcher/maintenance principal **by the blob ACL**;
  the Worker cannot, because the ACL denies it read (no blob read → no decrypt);
- **blob location**: the trust state root, e.g. `C:\ProgramData\Gnosis\Trust\secrets\worker.dpapi`;
- **blob ACL**: `inheritance:r` + SYSTEM:F + maintenance/launcher principal:R; **Worker
  = DENIED** (no ACE);
- **rotation / reprovision**: the maintenance principal rotates the worker password
  and re-writes the blob atomically; a `credential_version` is recorded (not the
  secret) so a stale launch can be detected;
- **corrupt blob** → decrypt fails → **FAIL CLOSED** (no launch);
- **rotated password** (blob out of sync with the account) → logon fails →
  **FAIL CLOSED**;
- **decrypt failure** (any cause) → **FAIL CLOSED**.

The Worker never obtains: blob decrypt authority, the plaintext password, or the
trusted launcher's logon token.

Rejected alternatives (documented): gMSA (needs a domain; this is a workstation);
S4U logon (needs `SeTcbPrivilege`); storing a plaintext or reversibly-encoded
password in disk/config/argv/logs/persistent-env (violates the contract).

## 11. Publisher startup

**demand-start** for V1 (accepted). The trusted Director starts the publisher
(`StartService`, via its maintenance authority) when a run becomes PUBLISHABLE; the
worker is granted **no `SERVICE_START`** (§16 service DACL). An idle self-stop MAY be
kept **only if** it cannot interrupt an in-flight publish or a recovery — the publish
protocol (§13) must complete or the service must refuse to stop mid-append. No
service triggers, no complex lifecycle in V1.

## Wiring integration points (exact call sites; NOT changed this round)

- **Worker launch** — `runner/claude_cli_runner.py:97` (`CLIRunner.run`'s `Popen`).
  A `trust/launch.py` launcher replaces the same-user `Popen` with a
  `CreateProcessWithLogonW` launch as the worker SID, cwd = the per-run worktree
  under the Work root, env cleaned, trust plane RX. `exec_root` already threads
  through `engine.py:554`/`:1038` and the ADR-0009 worktree isolation; the launcher
  is injected at the `CLIRunner` boundary so both Path A (`engine.py:1038`) and Path
  C (`gated_runner.py:320`) go through it.
- **Publish** — the Director's post-run path (after `TaskEngine.execute_task`
  returns success and `WorkIntegrator` lands the work). The Director (trusted) runs
  the capture (`scripts/capture_evidence.py` → `run_capture`, `evidence_capture.py:1341`),
  marks `RunIdentity.lifecycle=PUBLISHABLE` (§7), then sends `PublishCompletedRun(run_id)`
  to the publisher, which anchors via `publish_anchor` (`authority.py:374`, today with
  **no production caller** — this is the greenfield wire-in).
- **AnchorStore precondition** — `authority.py:294-298` changes per §3
  (`assert_publisher_identity` replaces `require_high`; runtime relabel removed).

## 12. Named pipe (frozen)

Frozen from the P2 probe, do not rewrite: local only; `PIPE_REJECT_REMOTE_CLIENTS`;
`FILE_FLAG_FIRST_PIPE_INSTANCE`; exact Worker-SID ACE granting `0x0012019B`
(read+write-data/attrs/EA, read-control, synchronize) with **no** `GENERIC_WRITE`
and **no** `FILE_CREATE_PIPE_INSTANCE`; one semantic verb `PublishCompletedRun(run_id)`;
bounded run_id; no path/digest/head/tree from the worker; squatting → fail closed
(the server refuses to attach). Production changes only: the pipe **name** (§16) and
the worker SID (§9). The client requests only `ReadData,WriteData,Synchronize`.

---

## 13. Watermark / crash durability contract

Declared scope for V1 closure: **A (process crash) and B (service crash) are
guaranteed; C (OS crash / power loss) is a best-effort target, explicitly bounded.**

The probe demonstrated LOGICAL recovery (an unconfirmed record beyond the committed
watermark is truncated on restart; a committed ANCHORED record survives). That
covers A/B. For **C**, mere `write()`/`re-read()` is NOT durable across power loss;
the design adds an explicit **durable ordering** protocol (the operator's preferred
option, adopted because it is not a disproportionate unit):

1. build `AnchorRecord`;
2. append the line to the ledger;
3. **`FlushFileBuffers`** on the ledger handle (force to disk);
4. re-open + re-read + `verify_chain`;
5. write the new committed watermark to a temp file, `FlushFileBuffers` it, then
   **atomically replace** via `MoveFileEx(..., MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)`
   (or `ReplaceFileW`) so the watermark update is a single atomic, write-through op;
6. re-read the committed watermark;
7. only then return `ANCHORED`.

**Ordering invariant:** the ledger record is durably on disk (step 3) *before* the
watermark that confirms it (step 5). A crash between 3 and 5 leaves a durable but
**unconfirmed** record → recovery truncates it → no false ANCHORED. A crash after 5
leaves a durably committed record that survives.

**Honest bound:** with `FlushFileBuffers` + write-through atomic replace, the state
machine is correct across A/B and, on hardware honoring write-through, across C. We
do **not** claim protection against a lying disk cache or torn sectors below the FS;
that is a storage-layer assurance, declared out of scope, not silently assumed.

---

## 14. Crash / fault-injection matrix

Deterministic tests via controlled fault injection (a test seam that aborts the
publish at a named point — NOT a physical power cut; results are labeled
"fault-injection", never "power-loss OS-real"):

| # | injection point | expected after restart |
|---|---|---|
| 1 | before append | run not anchored; re-publishable; no ledger change |
| 2 | during append (short/partial final line) | recovery discards the partial; chain verifies; no false ANCHORED |
| 3 | after append, before ledger flush | record may be absent or present-unconfirmed; either way not ANCHORED until re-published |
| 4 | after ledger flush, before verify | present-unconfirmed (beyond watermark) → truncated |
| 5 | after verify, before watermark write | present-unconfirmed → truncated |
| 6 | during watermark write | atomic replace means old OR new watermark, never torn; if old → record unconfirmed → truncated |
| 7 | after watermark durable commit, before response | record committed → SURVIVES; duplicate retry → ALREADY_ANCHORED |
| 8 | restart (clean) | chain verifies; committed records intact |
| 9 | duplicate retry (any of the above) | idempotent by run_id; never a second append |

**Property proven:** `false ANCHORED = impossible within {process crash, service
crash}`, and — modulo the storage-layer caveat in §13 — under power loss on
write-through-honoring hardware.

---

## 15. Unknown-`.git` enforcement (frozen decision, minimal implementation)

`UNKNOWN != INERT` is frozen. **The current code does NOT satisfy it.** In
`classify_observation` (`evidence_capture.py:768-823`) the per-event loop, after the
two hardcoded tamper/redirect sets (`_is_git_machinery_tamper:172`,
`_is_git_resolution_redirect:212`), reaches:

```python
elif path == _GIT_DIR.rstrip("/") or path.startswith(_GIT_DIR):
    machinery += 1          # evidence_capture.py:806-810  <-- COUNTS the unknown
```

so **any** `.git/` surface not in the two enumerated sets is COUNTED as benign
bookkeeping (the `else: unknown → violation` branch at `:822-823` is only reached for
paths OUTSIDE `.git/`). The boundary can therefore return CLEAN with an unclassified
`.git` write present. That is precisely the "unknown is inert" bug the frozen
decision forbids.

### Corrected classifier contract (BLOCKER fix)

The earlier draft's allowlist was too broad: whole categories like `refs/` and
`objects/` are **NOT** benign — they contain trust-sensitive surfaces already
demonstrated (`refs/replace/**`, `objects/info/alternates`, `objects/info/http-alternates`).
A rule equivalent to `refs/** → benign` or `objects/** → benign` is **forbidden**,
even if an earlier condition happens to intercept some cases today.

**Every observed `.git` surface must terminate in exactly one class:**

| class | disposition |
|---|---|
| `KNOWN_TRUST_SENSITIVE` | **judged**; a mutation in the interval → violation / fail closed, per the existing F-17 contract |
| `KNOWN_CONTENT_OR_BOOKKEEPING` | counted/allowed **only** where its concrete semantics are qualified (its inability to alter identity within the contract is stated) |
| `UNKNOWN` | `MACHINERY_UNQUALIFIED` → **FAIL CLOSED** |

`UNKNOWN != INERT`.

### Classification precedence (robust to ordering)

The classifier must not let a trust-sensitive surface be swallowed by a benign
parent glob, **and must stay correct even if the branch order is changed**. So it is
NOT `if dangerous first … else broad-safe-glob …` (where accidentally swapping the
two branches would open a bypass). Instead: a **single `classify(path)` function**
that maps a path to exactly one class by **explicit, most-specific-wins semantic
rules**, with the benign class carrying **specific** entries, never a broad
subtree, and everything unmatched falling to `UNKNOWN`. Required invariants (asserted
by tests, §below):

- `classify(path)` is **total and single-valued** (every path → exactly one class);
- **no trust-sensitive path can match a benign rule** (e.g. `refs/replace/x` classifies
  `KNOWN_TRUST_SENSITIVE`, never via any `refs/…` benign entry);
- reordering the internal rule list does not change any classification (most-specific
  wins, not first-match).

### Surfaces whose existing classification is preserved (not re-audited)

`KNOWN_TRUST_SENSITIVE` (judged / fail-closed on mutation), keeping the third/fourth
-review conclusions intact: `HEAD`, ref content/resolution, `packed-refs`,
`refs/replace/**`, `config`, `config.worktree`, `commondir`, `hooks/*` (non-`.sample`),
`objects/info/alternates`, `objects/info/http-alternates`, `info/grafts`, `shallow`,
and the topology redirects already covered by `git_topology_eligible:56` /
`git_resolution_faithful:129` / `_is_git_resolution_redirect:212` /
`_is_git_machinery_tamper:172`. The new model reuses those predicates as the
`KNOWN_TRUST_SENSITIVE` rules — it must not invalidate their prior conclusions.

### Object database — payload vs resolution machinery

`objects/**` is **not** one class:
- **object payload / loose+pack storage** (`objects/<2hex>/<38hex>`, `objects/pack/*.{pack,idx}`)
  = `KNOWN_CONTENT_OR_BOOKKEEPING`, **documented reason**: object bytes are
  content-addressed and covered by the F-14 byte/content binding — a substituted or
  added object changes the tree/content digest the bundle is bound to, so it cannot
  alter the anchored identity without being caught by the existing binding, not by
  this classifier;
- **object-resolution machinery** (`objects/info/alternates`, `objects/info/http-alternates`,
  and any other `objects/info/**`) = `KNOWN_TRUST_SENSITIVE` (redirects resolution).
  `objects/info/**` NEVER inherits the payload class.

### Refs — split, never generic-benign

- ref content/resolution (`refs/heads/**`, `refs/tags/**`, `refs/remotes/**`, loose ref files,
  `packed-refs`) → affect resolution/identity → `KNOWN_TRUST_SENSITIVE` (mutation judged;
  packed-refs already a redirect surface);
- `refs/replace/**` → `KNOWN_TRUST_SENSITIVE` (the demonstrated substitution attack);
- ref **lock files** (`*.lock`), **reflogs** (`logs/**`) → `KNOWN_CONTENT_OR_BOOKKEEPING`
  only if their qualified semantics show they cannot alter the committed identity the
  bundle binds (documented); otherwise `UNKNOWN`.
- No rule says `refs/ = benign bookkeeping`.

### Index

`index` and `sharedindex.*`: the F-17 contract does **not** depend on the index (the
bundle binds the committed tree/HEAD via `content_fingerprint`, not the staging
index). They are classified `KNOWN_CONTENT_OR_BOOKKEEPING` with the **stated
property**: a write to the index cannot change the committed tree/HEAD/object bytes
that the anchor binds, so it cannot forge anchored identity. They are counted, not
judged — because that property holds, not because "benign" is a label.

### Backend / version precondition (unchanged from the draft, kept)

At capture start, alongside `git_topology_eligible:56` / `git_resolution_faithful:129`:
detect the backend + version; if not the qualified **files** backend + Git **2.55.x**
range (e.g. `reftable`, or a materially different backend/version) →
`MACHINERY_UNQUALIFIED` → **FAIL CLOSED** (a new non-zero exit joining 9/10/11 at
`evidence_capture.py:147-149`), nothing runs.

### Implementation locus

Replace the blanket `machinery += 1` catch-all at `evidence_capture.py:806-810` with
`classify(path)` dispatch: `KNOWN_TRUST_SENSITIVE` → the existing judged path;
`KNOWN_CONTENT_OR_BOOKKEEPING` → counted; `UNKNOWN` → violation / `MACHINERY_UNQUALIFIED`.
No re-audit of all of Git — only this classifier + the backend/version gate.

### Unknown-`.git` test plan (implemented in the wiring round, not now)

1. known benign bookkeeping write (index / a reflog) → CLEAN, **no false positive**;
2. `refs/replace/*` mutation → **judged** (violation);
3. `packed-refs` mutation → **judged**;
4. `objects/info/alternates` (and http-alternates) mutation → **judged**;
5. unknown top-level `.git/new-machinery` → **fail closed** (`MACHINERY_UNQUALIFIED`);
6. unknown nested path `.git/foo/bar` not in any rule → **fail closed**;
7. `reftable` backend → **NOT QUALIFIED** at the precondition;
8. unsupported material Git version → **NOT QUALIFIED**;
9. known ordinary object payload write (`objects/ab/cdef…`) → **no false positive**
   (covered by byte binding);
10. **broad-parent-cannot-swallow-child**: assert `classify("refs/replace/x")` and
    `classify("objects/info/alternates")` are `KNOWN_TRUST_SENSITIVE` even though
    `refs/…` / `objects/…` prefixes exist;
11. **classifier-ordering mutant**: shuffle the internal rule order → all
    classifications unchanged (a mutant that makes classification order-dependent or
    lets a benign rule shadow a sensitive path must die).

---

## 16. Production service config (no probe names)

| item | production value |
|---|---|
| service name | `GnosisTrustedPublisher` |
| account | virtual account `NT SERVICE\GnosisTrustedPublisher` |
| sidtype | `RESTRICTED` |
| privileges | `SeChangeNotifyPrivilege` only |
| start mode | `demand` (Director-started; §11) |
| ImagePath | `"C:\Program Files\Gnosis\Trust\runtime\python.exe" -I -S "C:\Program Files\Gnosis\Trust\publisher\main.py" service "C:\ProgramData\Gnosis\Trust\config.json"` |
| service-object DACL | `D:(A;;<full>;;;SY)(A;;<full>;;;BA)` — **worker: NO ACE** (no CHANGE_CONFIG/START/STOP/DELETE/WRITE_DAC/WRITE_OWNER) |
| failure/recovery | no auto-restart that could hide a fault; SCM restart policy = none for V1 (Director re-starts on demand) |
| trust root | `C:\Program Files\Gnosis\Trust` — `inheritance:r` + Admins:F + SYSTEM:F + service SID:(OI)(CI)RX; worker no ACE |
| state roots | `C:\ProgramData\Gnosis\Trust\{anchors,runidentity,bundles}` — Admins:F + SYSTEM:F + service SID:F; worker no ACE |
| pipe | `\\.\pipe\GnosisTrustedPublisher`, policy per §12 |

The worker is never granted any service-control right.

---

## 17. Update model (no signing in F-17)

- Update only by a **trusted maintenance principal** (Admins/SYSTEM); the worker is
  WRITE-denied on the trust root throughout every window.
- **Staged**: new package written to a sibling dir; new `DEPLOYMENT.json` computed.
- **Atomic / fail-safe swap**: stop the demand service → rename-swap the `publisher\`
  and `runtime\` dirs (or a version-dir + junction flip) → restart.
- **Package manifest/version** recorded (`package_version` + `file_hashes` in
  `DEPLOYMENT.json`); **rollback** = re-point to the previous version dir.
- The package is **NOT** called authenticated (no signature/PKI) — that is a later
  phase, declared.

---

## 18. Final qualification environment

Closure runs on a **clean local fixed NTFS qualification workspace — NOT synced**
(the sync/slow-volume constraint that blocked prior full captures is an environment
problem, solved by changing the environment, not the contract). Requirements:

- a dedicated root, e.g. `C:\GnosisQual\` on a fixed local NTFS volume (no
  OneDrive/Syncthing/network redirection);
- inside the **F-14 qualified domain** (files backend, git 2.55.x, the classified
  machinery);
- checked out at the **exact final commit**; built into the **exact final deployment
  artifacts** with production ACLs/config reproduced;
- **no reuse** of results from prior trees (fresh clone/checkout);
- guarantees are unchanged — only the physical execution volume changes.

The capture itself is `scripts/capture_evidence.py` → `run_capture`
(`evidence_capture.py:1341`), run by the **trusted Director** (not the worker) over
the qualification tree, producing the bundle that the publisher then anchors.

---

## 19. Final deployment verification (end-to-end composition)

Closure must prove, in **one** end-to-end run over the composed system (not each
piece having passed separately at some time):

worker process → correct Worker SID/token · worker toolchain → exact qualified
package hash · publisher service → exact RESTRICTED service SID · RunIdentity →
trusted + correct worker SID + publishable state · trust package → exact
`deployment_digest` · AnchorStore → protected (worker denied) · IPC → protected ·
git machinery → qualified · evidence → fresh capture · anchor → authoritative
(`verify_anchored_bundle` against the store) → fresh-checkout verification of the
bundle against its external anchor.

### End-to-end attack matrix (closure) — must all FAIL CLOSED, in the composed system

Base (worker = distinct non-admin SID against the live deployment): worker launches
its own publisher; worker forges/writes RunIdentity; worker publishes a
non-PUBLISHABLE run; worker publishes another SID's run; worker replaces the trust
package/binary; worker squats the pipe; worker writes AnchorStore/watermark; unknown
`.git` surface during capture; crash mid-publish; process/service attacks on the
publisher.

**Deployment-drift (identity must catch each):**

| | drift | expected |
|---|---|---|
| A | one byte of the trust package changed | deployment mismatch (`deployment_digest` ≠ observed) |
| B | service ImagePath changed | deployment mismatch / preflight reject |
| C | SID type RESTRICTED → UNRESTRICTED | precondition reject (`assert_publisher_identity`) |
| D | service-object DACL altered | deployment mismatch / preflight reject |
| E | AnchorStore ACL altered | reject |
| F | RunIdentity-store ACL altered | reject |
| G | pipe security policy altered | reject |
| H | a trust package different from the registered one runs | reject (observed hash ≠ recorded) |

**Composition extensions (each FAIL CLOSED):** wrong Worker SID; missing Worker
identity; Worker-launch credential decrypt failure; stale/rotated Worker credential;
Publisher service missing; Publisher SID type incorrect; Publisher identity
precondition false; `TrustPlaneDeploymentIdentity` mismatch; RunIdentity
non-PUBLISHABLE; run epoch/generation mismatch; **same-user `Popen` fallback
attempted**.

> **There is NO fallback to an ordinary `subprocess.Popen` under the Director
> identity.** A launcher that cannot launch the worker as the worker SID fails the
> run closed; it never degrades to same-user execution.

---

## 20. Closure validation sequence (executed in the IMPLEMENTATION round, not now)

directed tests → authority tests → F-14 regressions → P2 service tests →
crash/fault tests → unknown-git tests → full suite → mutation testing → mypy → ruff
→ boundary → evidence_valid → deployment identity → fresh FULL `run_capture` →
authoritative publication → `verify_anchored_bundle` → fresh-checkout verification →
independent review. All over the **exact final committed tree**.

## 21. Full-suite flaky policy

Do not fix the known work-queue flaky inside F-17. Aim for a fully green closure
run; if the known flaky reappears, record it exactly (test id + output) and do NOT
declare the run GREEN. A run containing any failure is not GREEN.

## 22. F-14

CLOSED. Nothing in the P2 probe requires a reopen.

## 23. Scope

No work on F-15/F-16/F-18, M11.3, NVIDIA/NIM, multi-writer, self-evolution,
Assurance Program, external integrations, or `external/repositories/**`. No
production wiring in this design round.

---

## 24. Implementation sequence (executed only if this design is approved)

Each step is independently reviewable; a step that cannot meet its stop condition
(§27) halts the sequence.

1. **Trust-plane module split** (§3): create `src/gnosis/trust/{anchor,launch,
   bundle_verify,pipeserver,scmhost,publisher,tokendump}.py`; move the anchor slice
   from `authority.py`; replace `require_high` with `assert_publisher_identity`;
   remove the runtime relabel. Keep `authority.py` re-exporting for compatibility
   until callers move. Tests + mutation on the moved code first (no behavior change).
2. **Deployment identity** (§5): `TrustPlaneDeploymentIdentity` + `DEPLOYMENT.json`
   writer/reader; `AnchorRecord` gains `deployment_digest`; publisher self-check.
3. **RunIdentity + lifecycle** (§6/§7): extend `RunIdentity` (owner_worker_sid,
   deployment_digest, lifecycle); Director writes it from the launcher-observed SID;
   publisher enforces PUBLISHABLE + owner.
4. **Durable publish protocol + watermark** (§13): implement the 7-step durable
   ordering in `trust/anchor.py`; fault-injection seam (§14).
5. **Trusted launcher** (§9/§10): `trust/launch.py` launches the worker as the
   worker SID via DPAPI-password + `CreateProcessWithLogonW`; inject at the
   `CLIRunner` boundary (`claude_cli_runner.py`), preserving ADR-0009 worktree
   isolation. This is the largest, highest-risk step.
6. **Publisher wiring** (§16/§11): the pipe server + SCM host as the production
   service; the Director's post-run path captures, marks PUBLISHABLE, and calls the
   publisher; `verify_anchored_bundle` at read time.
7. **Unknown-`.git` fail-closed** (§15): the two gates in `evidence_capture.py`.
8. **Provisioning + update tooling** (§16/§17): idempotent provision/teardown of the
   service, trust roots, ACLs, worker account; staged atomic update.

## 25. Commit / evidence sequence

Per step: implement → unit/integration tests → self-review → independent review
where it adds evidence → repair true findings → rerun → **fresh capture over the
committed tree** → checkpoint (commit + state update). Docs-and-code separated where
practical. No step is declared done without its evidence bundle verifying and, for
the closure, anchoring. Every ADR-0027 addendum records the exact commit + bundle
digest as the external anchor.

## 26. Rollback / recovery plan (for the wiring itself)

- All work on a branch off `master`; each step a revertible commit; no history
  rewrite.
- OS-side (service, accounts, ACLs, trust roots) is created by **idempotent
  provisioning scripts** with a matching **idempotent teardown** (the P2 probe's
  `p2_cleanup.ps1` pattern), so any environment change is fully reversible and
  verified by a residual check.
- The launcher change (step 5) is feature-gated: if the trusted launcher fails to
  start the worker as the worker SID, the run fails closed (no silent fall-back to
  same-user `Popen`) — but the *code path* can be reverted by the branch without
  touching a running system, since nothing is deployed until closure.
- The trust package supports atomic swap + rollback to the prior version (§17).

## 25b. Estimated production changes

- **New:** `src/gnosis/trust/` (~7 modules, ≈700–900 lines incl. the SCM host/pipe
  already prototyped in the probe); provisioning/teardown scripts; `DEPLOYMENT.json`
  schema; fault-injection test seam; directed + crash + unknown-git tests.
- **Modified:** `runner/claude_cli_runner.py` (launcher injection at the Popen
  boundary); a Director post-run hook (orchestrator/pipeline) to capture+publish;
  `kernel/evidence_capture.py` §15 gates; `kernel/authority.py` → thin re-export /
  moved into `trust/anchor.py` with the precondition change.
- **Unchanged contracts:** F-14 byte-binding; the canonical hash primitive; the
  named-pipe policy; the RunState/TaskState machines; the ADR-0009 worktree model.
- Rough scale: a multi-step milestone, not a single unit — the operator has framed
  the *next* round as possible implementation if this design is approved.

## 27. Exact stop conditions

Halt and return for review (do NOT push past any of these):

- the trusted launcher cannot launch the worker as the worker SID **without a
  persistent or exposed plaintext secret** — i.e. the only working solution needs the
  password in disk plaintext / config / argv / logs / persistent env (transient
  cleartext inside the launcher during the Windows logon call is expected and
  acceptable, §10) → `WORKER LAUNCH CREDENTIAL NOT QUALIFIED`;
- `assert_publisher_identity` cannot be made OS-real (the service token's SID/
  restricted state cannot be verified) → `PUBLISHER IDENTITY PRECONDITION NOT
  AVAILABLE`;
- durable ordering cannot be implemented within the declared A/B scope (§13) with a
  passing fault matrix (§14) → `DURABILITY CONTRACT NOT MET` (do not weaken the
  contract to pass);
- the unknown-`.git` fail-closed cannot be added without breaking a normal capture
  (false positives on benign bookkeeping) → `UNKNOWN-GIT ENFORCEMENT NOT QUALIFIED`;
- the fresh FULL capture cannot run green on the clean local NTFS workspace for a
  reason other than the known work-queue flaky → stop and report, do not declare
  GREEN;
- deployment identity cannot bind the actual running deployment → `DEPLOYMENT
  IDENTITY NOT BINDING`.

Any stop leaves F-17 OPEN with the exact blocker named.

## 28. Decisions requiring independent review before implementation

1. The `require_high` → `assert_publisher_identity` semantic replacement and the
   removal of the runtime `label_high_no_write_up` (§3) — is the OS-enforced
   boundary + in-process consistency the right contract, and is the ADR wording
   ("OS-enforced boundary; in-process = DiD") correct?
2. `RunIdentity.lifecycle=PUBLISHABLE` as the publish gate (§7) vs a richer state
   machine; and whether to bind `claims.holder = owner_worker_sid` / reuse the
   `epoch` as the generation.
3. The durability contract scope (§13): accept **A/B guaranteed + C best-effort on
   write-through hardware, storage layer out of scope**, or demand more?
4. The worker launch credential choice (§10): DPAPI + `CreateProcessWithLogonW` vs
   any objection to a machine-bound DPAPI blob at rest.
5. `TrustPlaneDeploymentIdentity` field set (§5) — is it sufficient and minimal?
6. The unknown-`.git` allowlist (§15) — is the benign-bookkeeping set correct and
   complete for the qualified git scope, without false positives?
7. Whether the closure's end-to-end composition proof (§19) is defined tightly
   enough to prove the *composition*, not the pieces.
8. Service integrity (§2): accept "keep High, it is not the boundary", or require
   Medium as extra DiD?
