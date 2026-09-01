# GNOSIS Project State

**Status:** PHASE -1 COMPLETE; NINE KERNEL-HARDENING DIRECTIVES IMPLEMENTED; ADAPTER MILESTONE COMPLETE; INTEGRATION MILESTONE COMPLETE; RESULTS LAND ON THE SHARED BRANCH; MULTI-WORKER PLANE (QUEUE + BUDGET + ORDERING); RE-REVIEW AS EVIDENCE; WORKER SUPERVISION; THE PROBE HAS A CALLER; MULTI-CREDENTIAL ROTATION
**Target machine:** Nicol
**Phase:** 1 — Kernel hardening per archaeology directives
**Last update:** 2026-09-01 (**F-28: RESOLVED / PARTIALLY VALID** by independent decision — a historical audit finding flagged the repo-root untracked `PROJECT_REPORT.md` vs the tracked `docs/PROJECT_REPORT.md` as a byte-identical duplicate with silent-divergence risk. Proven: both exist (tracked vs untracked), byte-identical at the archaeology checkpoint, no enforced synchronization. Not proven: the "operator edits the untracked copy" subclaim (PROJECT_REPORT is a one-off external-review snapshot, absent from the durable-state docs; no tool/instruction edits it). Authority recorded: live state = `PROJECT_STATE`/`NEXT_ACTIONS`; `docs/PROJECT_REPORT.md` = authoritative versioned snapshot; the root copy = non-authoritative untracked artifact, retained unchanged under the current qualified state (no permanent-existence requirement created). Docs-only; neither PROJECT_REPORT file, `.gitignore`, nor the evidence-binding test touched; historical FAIL/MEDIA retained; current severity BAJA; no runtime defect; F-14 and F-17 remain CLOSED. Prior: **F-27: RESOLVED** by independent decision — the root `README.md` (a frozen M0/M1 artifact that materially misrepresented current architecture/tooling) was modernized README-only (Option B) and passed two rounds of adversarial independent review: modernization `1ec2ff8` → first review FAIL (Issue A: external-LLM/runtime dependency semantics too broad vs the wired `claude`-CLI execution path; Issue B: F-17 claim dropped ADR-0031's `historical-evidence` qualifier) → remediation `9dd35f8` → second review PASS WITH NON-BLOCKING NOTES → closure. The README now states current architecture at overview depth, Python >= 3.12, the pytest workflow, the `claude`-CLI provider-backed execution dependency, adapter-boundary provider-neutrality, the `src/gnosis/` layout, and the bounded F-17 "authoritative historical-evidence publication" claim (production-equivalent qualification under the documented contract, not a live deployment); no NVIDIA/NIM, no perpetual counts. Historical FAIL/ALTA retained; current RESOLVED, no blocking consequence; non-blocking README quality debt kept in the review history. Docs/state-only; no source/README-byte/pyproject change; F-14 and F-17 remain CLOSED. Prior: **F-26: RESOLVED / STALE / NOT A CONTRADICTION** by independent decision — a historical audit finding read "seventeen findings left open" vs "15" as an internal count contradiction; archaeology proved they are the **same 47-finding review episode at different checkpoints** (17 = immediate post-review residual per the ADR-0022/0023/0024 addenda 7+4+6; 15 = after two of those seventeen were resolved — concurrent `recover()`/L-0042 and unpaced crash recovery, already named in this doc's §"Review debt paid"), not a same-scope arithmetic conflict. Current live tracked state is already reconciled to 15, enumerated in the tracked `docs/PROJECT_REPORT.md` §8; no live count changed, no new perpetual total introduced, historical 17 records left intact. Historical FAIL/MEDIA retained; current severity BAJA; no runtime-security defect; no source/ADR/DECISIONS change; F-14 and F-17 remain CLOSED. Prior: **F-25: RESOLVED / NOT A CONTRADICTION** by independent decision — a historical audit finding conflated **review coverage** (a qualifying review exists per unit) with **review assurance / channel strength** (its independence/depth); the two `NEXT_ACTIONS` passages address different axes and unit sets and are both true, so it is not closed as a valid-contradiction-fixed. Docs-only: the unbounded "no unreviewed unit remains" universal was checkpoint-qualified to its ADR-0013…ADR-0016 milestone/2026-08-21 scope; the authoritative clarification lives once in the F-25 audit row. Historical FAIL/ALTA retained; current severity BAJA; no runtime-security defect; no source/pyproject/ADR change; F-14 and F-17 remain CLOSED. Prior: **F-24: RESOLVED** by independent decision — a live "Target-machine gates" item kept "Kernel implementation (Phase 1 continuation) begins after archaeology" unchecked although its "begins" criterion had long been satisfied; the gate is now `[x]` recording only that implementation BEGAN after archaeology (earliest evidence ADR-0004; corroborated by later milestones and the F-14/F-17 trust plane), NOT full kernel completion. Docs-only; no kernel/source/pyproject change; F-14 and F-17 remain CLOSED. Prior: **F-23: RESOLVED** by independent decision — an M0→M3 "Inherited baseline" note presented a resolved package-layout conflict as current/pending; it now states the historical→current transition (ADR-0002 moved the code to `src/gnosis/` keeping the `gnosis` import namespace). Canonical source layout is `src/gnosis/` (import package `gnosis`); no root production `gnosis/` tree; ADR-0002 is the canonical decision. Docs-only; no source/pyproject/import change; F-14 and F-17 remain CLOSED. Prior: **F-22: RESOLVED** by independent decision — a stale "Known open items" caveat that claimed Codex login was still pending contradicted the same doc's checked authentication gate (login 2026-08-19) and `NEXT_ACTIONS` "codex login DONE" (review executed 2026-08-20); the caveat now states the checkpoint-qualified reality (setup/login complete and exercised; login not a pending gate; credential/quota are separate operational state, rate-limited at the recorded checkpoint, reset 2026-09-20). No live-credential claim invented; no login/logout/provider-call/credential inspection; docs-only; F-14 and F-17 remain CLOSED. Prior: **F-21: RESOLVED / STALE** by independent decision — the historical stale-top-level-date contradiction (an earlier "Last update" value than the body's completed work; details in the audit) no longer exists; this document now has one "Last update" field (2026-08-31, unchanged by this closure) representing the latest tracked state update, corrected incidentally by later F-17/F-15–F-20 work; the drift-prone manual-field risk is recorded as process debt; docs-only; F-14 and F-17 remain CLOSED. Prior: **F-20: RESOLVED** by independent decision — the stale "mypy strict clean (47 files)" milestone fragment was replaced with a checkpoint-qualified, evidence-referenced result (`mypy --strict src` clean, no issues in 79 source files, F-17 final qualification, tree `06cdf00`, 2026-08-31; provenance ADR-0031); docs-only; historical FAIL/MEDIA retained in the audit (the 47-vs-55 inconsistency preserved); the co-located "760 tests" figure was not touched; next open register item F-21 (Last-update date; appears already current) NOT started; F-14 and F-17 remain CLOSED. Prior: **F-19: RESOLVED** by independent decision — the stale "## Suite status" count (164+3=167) was replaced with a checkpoint-qualified, evidence-referenced status (F-17 final qualification, tree `06cdf00`: 1510 passed / 1 skipped / 291 subtests / exit 0; 1511 collected); docs-only; historical FAIL/ALTA retained in the audit, current severity MEDIA; next open roadmap item F-20 (stale mypy file count) NOT started; F-14 and F-17 remain CLOSED. Prior: **F-18: RESOLVED / STALE** by independent decision — the historical "evidence drift" finding was a documentary/provenance mismatch (a wrong human citation in the untracked `PROJECT_REPORT.md`), not a runtime integrity flaw; the authoritative tracked state is clean (49/49 cited bundles exist; bundles self-record their real identity; F-17 closure docs cite consistently); docs-only closure in `docs/V1_TRACEABILITY_AUDIT.md`; residual is the untracked out-of-scope `PROJECT_REPORT.md` (left to the operator); next open roadmap item F-19 (Eje 4 documentary drift) NOT started; F-14 and F-17 remain CLOSED. Prior: **F-16: RESOLVED / STALE** by independent decision — the historical "capture order" finding is superseded; `run_capture` establishes a trusted PRE identity before the first command (`:1401`), a PREPARED identity after locking inputs (`:1415`) with a drift gate, POST after (`:1439`), complete interval observation, and fail-closed on unavailable identity; docs-only closure in `docs/V1_TRACEABILITY_AUDIT.md`; next open roadmap item F-18 (evidence drift) NOT started; F-14 and F-17 remain CLOSED. Prior: **F-15: RESOLVED / STALE** by independent decision — the historical "unused primitive" finding is superseded; `content_fingerprint` is wired into the capture production path (`capture_evidence.py`→`run_capture`→PRE/POST fingerprint→`SUMMARY.json`) and used by engine/integration/cli_review/replay_runner/evidence_capture; docs-only closure in `docs/V1_TRACEABILITY_AUDIT.md`; next open roadmap item F-16 (capture order) NOT started; F-14 and F-17 remain CLOSED. **F-17: CLOSED by independent decision** — qualified production tree `06cdf00`, final evidence/state commit `871792f` (0 production files changed), closure record ADR-0031; Stages 1–8 PASS/CLOSED, Final F-17 Qualification PASS, F-17 CLOSED, F-14 remains CLOSED; claim: under the qualified Windows/Git-2.55.x-files/Python-runtime/deployment contract a compromised Worker cannot cause an authoritative publication the trusted plane did not authorize, unsupported/ambiguous conditions fail closed; next open roadmap item F-15 (unused primitive) NOT STARTED. Prior: **F-17 FINAL QUALIFICATION: `PASS` at `06cdf00`** — exact-tree qualification of the completed composition: structural 5/5 adversarially verified (one production authoritative path, V2-only, worker-unreachable fault seam, 15-module closure, no dynamic loading), OS-real all-pass (S5 + S7 26 + S6 49 + S8 140), directed 613, fresh-checkout 475 with proven extraction-provenance, full suite GREEN 1510/exit-0, mutation union all-die except the non-relevant survivor S6M22 (worker-unreachable redundant early verify; authoritative gate enforces + tested) and 7 stale-anchor not-applied; evidence `.gnosis/evidence/20260831T025855Z-f17-final-qualification/` root `f27a5f8a…`; DO NOT mark F-17 CLOSED without independent decision; F-14 not reopened; **F-17 STAGE 8 (PRODUCTION PROVISIONING): `PASS` at `77c639a`, awaiting independent review** — provisioning realizes the Stages 1-7 boundaries in reproducible fail-closed Windows OS state; probe 140/140 OS-real, mutation 21/21, fresh-checkout requalification 475; ADR-0030; F-14 not reopened; final F-17 qualification NOT yet authorized; F-34 closed; **F-14 CLOSED by independent review #12** — the historical flaky event stays an evidence note and is NOT reopened; **F-17 STAGES 1–4 CLOSED by independent review (`ad06b09`, `c45c547`, `b3c0feb`, `2b865f2`); F-17 IMPLEMENTATION — STAGE 5 REMEDIATION (TRUSTED DEDICATED-WORKER LAUNCHER): `PASS`, and its ONE blocking review finding (D3) is now REPAIRED: `STAGE 5 D3 HARDENING: PASS`; and the FINAL blocking finding (WORKER PROFILE ENVIRONMENT POISONING) is now REPAIRED at `328930c`: `STAGE 5 ENVIRONMENT HARDENING: PASS` — STAGE 5 CLOSED by independent review at `7022fdd`; **F-17 IMPLEMENTATION — STAGE 6 (PRODUCTION PUBLISHER + TRUSTED PIPELINE WIRING): `PASS`, STAGE 6 CLOSED by independent review at `3e5a2e2`; **F-17 IMPLEMENTATION — STAGE 7 (UNKNOWN .GIT FAIL-CLOSED ENFORCEMENT): `PASS`, awaiting independent review before Stage 8.** Every `.git` administrative surface is now classified closed-world (`gnosis.kernel.git_surface`) into TRUST_SENSITIVE / CONTENT_OR_BOOKKEEPING / UNKNOWN, with `UNKNOWN -> MACHINERY_UNQUALIFIED -> fail closed` as the only catch-all, order-independent by construction, no broad refs/** or objects/** rule. A git backend/version gate (2.55.x, `files`; reftable rejected OS-real) runs first, and the classifier is connected to publication: `build_anchor_record` and `authorize_publishable` refuse any boundary verdict but CLEAN (ABSENT included), the trust plane gaining zero new imports (publisher closure still 15). Mutation 19/19; OS-real git matrix 26/26; Stage 6 composition regression 49/49; full suite 1483 passed / 261 subtests GREEN first run; isolated fresh checkout 280 passed with import provenance PROVED. HEAD `5f2d704`, ADR-0029.** The parts qualified in Stages 1-5 are now ONE executable path, ending at a **Restricted Service-SID Publisher** whose entire request surface is `PUBLISH <run_id>`. RunIdentity **v2** binds the sealed `launch_spec_digest`; deployment identity **v2** binds the runtime as a TREE of **3434 files** rather than one `python.exe`, with the runtime root declared. The publisher's TCB was measured AFTER A REAL PUBLICATION (the dependency was a lazy import a static graph could not see): **14 -> 11 modules**, the evidence-capture stack ABSENT, service closure **15 modules**. **OS-real composition 49/49** with verified rollback; **mutation 34/34 caught**; full suite **1438 passed / 156 subtests**; isolated fresh checkout **362 passed** with the import PROVED. The probe found two production defects no in-process test could - an AnchorStore that rewrote the very descriptor `deployment_digest` binds, and a service that could not read its own code - and four defects in the CHECKING itself, all recorded in `stage6_findings.txt`. HEAD `27a3a3c`, ADR-0028.** **ENVIRONMENT**: after D3 the bootstrap held the WORKER's profile environment and forwarded `os.environ`; under T2 a previous run can persist variables into its own `HKCU\Environment`. The child's environment is now built by a **CLOSED ALLOWLIST** (`unknown variable = DENIED`) — 14 variables, OS facts asked of the OS via `GetSystemDirectoryW` / `GetUserProfileDirectoryW`, `PATH` **built not inherited**, profile paths validated inside the Worker's real profile root component-wise, sealed overlay restricted to a closed name set guarded **at import**, and `environment_policy_version` bound into `launch_spec_digest`. Proved OS-real **cross-run**: 22/22 poisoned variables persisted in the registry, **0 reached the logical child**. Probe 77/77, mutation 38/38, directed 75, fresh checkout 264, full suite GREEN on the detached run (the one red run was the PRE-EXISTING work-queue flake, attributed by measurement 4/20 on BOTH trees).** **D3**: the launcher called `LogonUserW` + `LoadUserProfileW`, making **SeBackup + SeRestore** a permanent requirement — *reachable is not authorized*. Measured OS-real instead of argued: with `LOGON_WITH_PROFILE`, `lpEnvironment = NULL` already yields the **Worker's own profile** environment (USERPROFILE/APPDATA the Worker's, Director sentinel ABSENT), so both APIs, `CreateEnvironmentBlock`, `PROFILEINFOW`, `CREATE_UNICODE_ENVIRONMENT` and `userenv.dll` were **removed**. The determinism variables now ride in the **sealed** spec (credential-shaped names refused, bounded, applied **before** the seal). **Direct proof**: a disposable Director child removed both privileges from its own token (24→22) and the trusted launch **still succeeded** — same SID, Medium, contained, exit 0, profile correct, sentinel absent. Enforced by an AST test refusing every privilege-requiring API. OS-real probe **68/68**, mutation **30/30**, full suite **1353 passed / 99 subtests**, fresh checkout 186 passed, mypy clean (68 files). **TCB terminology frozen: project-source Trust Plane ~4295 LOC PLUS trusted Python runtime ~62 MB / 3434 files — neither quotable without the other.** Deployment-binding debt recorded for Stage 6/8: `deployment_digest` does not yet cover the trusted bootstrap/runtime artifacts. D3 HEAD `b729b92`; evidence `.gnosis/evidence/20260828T033211Z/`. Gate-1's STOP was upheld and **candidate B authorized**: the payload no longer travels on the transport. A **264-character** transport command (bootstrap path + spec path + digest, budget 512, cap 1024) carries a **sealed LaunchSpec** whose **12264-character logical argv** is re-created **element by element** by a bootstrap already running under the Worker SID — `logical argv before == logical argv after`, compared as VECTORS across 14 edge cases, with `%VAR%`/`$VAR` arriving as literals (the positive proof no shell is involved). The seal has **two independent controls**: an ACL that makes the launch root Worker-READ-only (write/delete/rename/WRITE_DAC/takeown all measured DENIED from inside the worker) and a `launch_spec_digest` derived from the **re-read bytes** and carried **on the command line, not in the file**. **No handle crosses the boundary at all** — the bootstrap opens its own endpoints, `STARTF_USESTDHANDLES` is never set (AST-asserted). **Creation order is the security property**: `CREATE_SUSPENDED` → verify SID/integrity/non-admin/no-dangerous-privilege → job (`KILL_ON_JOB_CLOSE`, no breakaway) → `AssignProcessToJobObject` → `IsProcessInJob` → **only then** `ResumeThread`; the verdict was **extracted into a pure function** so every refusal is a unit test. **E1/H1/D1 REPAIRED and measured OS-real**: a Director sentinel is ABSENT from the worker environment (its own profile + a two-name allowlist), stdin is DEVNULL and not a console, and a grandchild froze after job termination with **0 worker processes** left. **DPAPI is machine binding, NOT launcher binding** — the ACL is the authorization boundary; missing/empty/corrupt/truncated blobs all fail closed. **NO SAME-USER FALLBACK**, tested and mutated. **OS-real probe 59/59 with verified rollback**; cross-process attacks Worker→Director all DENIED; python/git/claude all rc=0 under the worker. **Two of our own bugs are on the record**: a UTF-16 secret decode that ate half a code unit, and a probe password generator with a fixed literal prefix that our own secret scan caught — while the probe's plaintext check scanned for that same prefix, so check and defect propped each other up. **Seven mutants survived the first run** (including one that satisfied the old job-flag assertion by ORing BREAKAWAY onto it); after repair **25/25 caught**. **A real provisioning finding**: `claude.exe` lives in the Director's profile and is unreachable by a dedicated worker — **Stage 8 must relocate the toolchain**. TCB +3 allowlist entries, Trust Plane 3005→4295 LOC, the bootstrap's own closure **8 modules**, plus the 62 MB runtime reported not hidden. Directed 56; **full suite 1346 passed / 98 subtests, exit 0**; mypy strict clean (68 files). Impl HEAD `6494eb6` (+`35656e4`); evidence `.gnosis/evidence/20260827T223817Z/`. Stage 6 NOT started. The review put the runner audit **before** the Windows primitive so this could be found without building on a disqualified foundation; it was, and **nothing was built on it** — no launcher, no worker account, no DPAPI blob, no ACL, no production source change. `build_argv` puts the **whole prompt in argv** (CASE B): measured worst case **12128 characters** against `CreateProcessWithLogonW`'s documented **1024** cap, and even the smallest real production prompt (1023) exceeds it. The payload was not truncated, the prompt was not split, and the API was not silently adopted. Minimal-solution candidates, none implementable under Stage 5's authority: **(A)** prompt to stdin (documented in `claude 2.1.247` as a pipe/`--input-format text` channel, but qualifying it needs a **provider call** and it changes `ExecutionResult.command` provenance); **(B) RECOMMENDED** a trusted <1024-char bootstrap that reconstructs the exact argv from a Director-written file and execs the real CLI **as itself** — changes neither Claude semantics nor the privilege set, at the cost of a new TCB component and an **integrity-load-bearing** payload file; **(C)** `CreateProcessWithTokenW` (reachable — Director holds `SeImpersonatePrivilege` ENABLED; `SeAssignPrimaryTokenPrivilege` ABSENT so `CreateProcessAsUserW` is not), rejected here because reachability is not authorization and it forecloses the preferred broker model. **Three primitive-independent findings audited anyway, all UNMET in production TODAY**: **E1** the Worker inherits the Director's **entire** environment (62 vars, 9 credential-shaped by name; no allowlist); **H1** the Worker **inherits the Director's stdin** (live probe: fd 0, `isatty=True`); **D1** **no Job Object** and cancel/timeout kill only the direct child — **proven by live probe**, a grandchild kept running after cancellation (`'9' → '16'`): `WORKER DESCENDANT CONTAINMENT GAP`. The first descendant probe reported "contained" and was **wrong** (`write(...) or sleep(...)` short-circuits); corrected, re-run and recorded — L-0061 from the probe side. Until a launcher exists the Worker still runs **as the Director**, so every property depending on `owner_worker_sid` being an OS-observed SID is contractual, not enforced. Evidence `.gnosis/evidence/20260827T211722Z/`. Stage 4 stays CLOSED and its guarantees stand. **NO WINDOWS PRODUCTION WIRING** — nothing installed. Stage 4 closes the crash window Stage 3 declared (`PUBLISHABLE` → anchor written → CRASH → state not yet `ANCHORED`): there is now exactly **ONE authoritative commit point — the durable, re-read, ledger-verified committed watermark**. The ledger holds CANDIDATES and a record's presence proves nothing; the watermark says what is COMMITTED; `PublicationState.ANCHORED` is the **CONSEQUENCE** of that commit and never a second authority — recovery may **complete** it, never **manufacture** it, and an `ANCHORED` state with no commit behind it fails closed rather than being repaired by fabricating the anchor. A **genesis watermark** (`committed_seq = -1`) is written before anything can be appended, so the absence of a watermark means only "not under the durable protocol" and is REFUSED; a watermark is **never** inferred from the ledger's last record. The watermark carries `schema`/`committed_seq`/`committed_record_digest` and nothing else — chain hash, `run_identity_digest`, `deployment_digest` and `run_id` were evaluated and rejected as duplicates the record digest already binds. Recovery matrix A–J explicit with E/F/G/H/J failing closed; tail truncation bounded to ONE uncommitted record **or** ONE partial line, never both; committed history never cut. F0–F9 injected into **REAL process kills** (`os._exit`, no cleanup/atexit/buffer flush): **NO POINT PRODUCES A FALSE ANCHORED**, and every point recovers to exactly one record, a verifying chain and `ANCHORED` against it. Guarantee scope stated honestly: **process/service crash GUARANTEED; power loss and storage failure BEST EFFORT, EXPLICITLY BOUNDED** (no directory fsync on Windows; a journalled rename is not a proof). `FileLock` is trusted-writer coordination, **not** a security boundary against a worker. **Four mutants survived the first run**; three were real coverage gaps (a retry answered from the ledger head, an unrepaired tail never exercised because the default repairs, a watermark-flush assertion satisfied by the state file's flush) and the fourth was an unreachable guard now pinned by a direct contract test — 21/21 after repair, with Stage-3 17/17 and authority 13/13 re-run against the refactored source. TCB **+1** (`trust.publication`, 834 LOC) by explicit diff; `kernel.atomic_io` 37 → 82 inside its existing grant; **`trust.deployment` (1052 LOC) still NOT in the publisher's closure**. Directed 72 passed; fresh checkout of `8b58509` 161 passed; **FULL SUITE 1290 passed / 101 subtests, exit 0**; mypy strict clean (65 files). Impl HEAD `8b58509`; evidence `.gnosis/evidence/20260827T192210Z/`. Stage 5 NOT started. Stage 3's property still holds: **knowing a `run_id` is NOT enough to produce `ANCHORED`**. Reused rather than invented: `TaskClaim.epoch` as the generation (no nonce), `RunStore`'s `mkdir(exist_ok=False)` as the run-id locus, `hash_canonical` as the only hash, `atomic_io`+`file_lock` reused. `RunIdentity` **extended in place** (+tree_identity, owner_worker_sid, deployment_digest, epoch). **`PublicationState` is a new primitive because `RunState` lives in the run directory the WORKER CAN WRITE** — `NOT_PUBLISHABLE → PUBLISHABLE → ANCHORED`, monotonic, `PUBLISHABLE` only via a trusted transition, `ANCHORED` only while naming a confirmed AnchorRecord. Immutable identity and monotonic state kept apart (`transition()` carries no identity); every update a **compare-and-set**, closing the delete-and-recreate/ABA route. **`gnosis.anchor.v2`** = v1 + `deployment_digest` + `run_identity_digest`; V1 stays readable under its historical contract with a **byte-identical digest** and can never satisfy a bound verification; no silent upgrade. **A mutant (RM13) survived and the model changed**: the V1 guard was refusing by coincidence, so the distinction became a type (`AnchorNotDeploymentBound`). Also closed: `publish_anchor` no longer **adopts** the bundle's tree identity, it **cross-checks** it. TCB `TRUST_ALLOWLIST` **+3** by explicit diff; `trust.anchor` closure 522→715 and still imports neither `trust.deployment` nor `trust.run_identity`; Trust Plane 2295 LOC. `deployment_digest` is **binding, not provenance**. Validation: directed **209**, fresh checkout identical, mutation **17/17 CAUGHT**, **FULL SUITE 1218 passed / 72 subtests GREEN**, mypy clean (64 files), ruff clean, negative control + secret scan clean. Impl HEAD `a6dd6aa`, evidence `20260827T144629Z`. Stages 4-8 NOT started. **F-17 IMPLEMENTATION — STAGE 2 (TRUST-PLANE DEPLOYMENT IDENTITY): `PASS`, awaiting independent review before Stage 3. NOTHING INSTALLED** — no publisher service, no Worker account, no DPAPI secret, no production AnchorStore/RunIdentity store, no engine/runner change, no pipeline wiring, no unknown-`.git`, no `AnchorRecord` schema change; the OS-real tests observe only pre-existing objects (a temp dir, this interpreter, an EXISTING service read-only) and leave nothing behind. New **`src/gnosis/trust/deployment.py` (1052)**: `TrustPlaneDeploymentIdentity` over the trust-package manifest, runtime, service, trust-root/RunIdentity-store/AnchorStore descriptors and deployed pipe policy; `deployment_digest = hash_canonical(...)` (ADR-0004, no competing hash). **Observed ≠ desired, structurally**: `DesiredDeploymentConfig` gives only WHERE to look, `compare_with_desired` is the sole reader of intention, version/commit/tree come from the DEPLOYED `PACKAGE.json`, and an expected manifest can only REFUSE a deployment — proved by test 12, test 13 and a structural sentinel test. Manifest deterministic (code-point order, OS-resolved case, no mtime/order/locale, **no file excluded**); bytes hashed THROUGH the handle whose resolved path was taken; runtime bound by BYTES (a one-byte-different copy of this interpreter reports the same version and yields a different identity); service read via explicit Win32 with the SID asked of Windows; **SD canonicalization parses the BINARY descriptor, normalizes representation and PRESERVES ACE ORDER** (sorting would lose ACL semantics; declared cost is false drift, never false match); junction-out-of-root and UNC fail closed; **13/13 drift cases**, canonical-DACL matrix A–F, and every missing-state path fail closed. **`AnchorRecord` NOT extended — deliberate STOP** (binding `deployment_digest` needs Stage 3/6 to supply it; an always-empty field would affect no guarantee). **TOCTOU declared, not solved**: hashing is detection/binding, ACL/SID is prevention. TCB: `trust.deployment` enters `TRUST_ALLOWLIST` by explicit diff, closed-world tests now cover EVERY entry point, **`trust.anchor` closure UNCHANGED at 522 LOC** (the publisher's trusted closure did not grow) while the Trust Plane grew to 1574; zero third-party. Also freezes Stage 1's residual risk as an enforced rule: no dynamic import/`exec`/`eval`/plugin discovery in the Trust Plane (test + mutant DM11). Validation: directed **98**, fresh checkout of `27e181d` **98**, mutation **11/11 CAUGHT**, mypy clean (63 files), ruff clean on all new/changed, negative control + secret scan (0 findings), and **the FULL SUITE GREEN TWICE (1167/73 over `e648784`, 1168/74 over `27e181d`, zero failures)** — which corroborates, without proving, the Stage-1 environmental classification of the one non-green run, so that adjudication stays open. Impl HEAD `27e181d`, evidence `20260827T043242Z`. Stages 3–8 NOT started. **F-17 STAGE 1 — INDEPENDENT-REVIEW HARDENING APPLIED (closed-world TCB boundary); Stage 2 still NOT authorized.** The Stage-1 review returned `APPROVE_WITH_ONE_FINDING`: the trust-plane boundary was a BLACKLIST of worker-plane name substrings — wrong polarity for a TCB, and measured to have admitted **28 of the 56** non-TCB internal `gnosis.*` modules in silence (`kernel.credentials`, `kernel.ledger`, `kernel.memory_router`, `transport.mcp_transport` among them). Inverted to **closed-world**: `DEFAULT = NOT ALLOWED`, property `loaded gnosis module ∉ TRUST_ALLOWLIST → TEST FAIL`, 6 justified entries with `kernel.authority` deliberately excluded (the Trust Plane must never depend back on its own facade). Name-independence proven by a uuid-generated predicate test **and** by creating a REAL new `gnosis.*` module on disk and importing it for real into the plane's process. A hole in the model itself was found and closed: a **lazy function-body import is invisible to any load-time closure**, so an AST scan of `src/gnosis/trust/**` now refuses undeclared internal imports at any nesting level (`DEFERRED_TCB_EXPANSION` declares the one legitimate lazy dependency, `kernel.evidence_capture` via the `verify=` seam). Mutation **13/13 CAUGHT** with new **AM12** (module-level) and **AM13** (lazy bypass); measured on an isolated copy, AM12 **SURVIVED the old model** and AM12′ (`kernel.credentials` into `trust.launch`) went entirely undetected. **TCB size claim corrected — three measured metrics: static functional slice 265 LOC; runtime trusted closure at LOAD time 522 LOC (`trust.launch` is trusted code, not "conceptually unused"); runtime trusted closure at PUBLISH time 3966 LOC** — the security-relevant one, because the lazy `verify_bundle` import adds `evidence_capture`+`git_evidence`+`input_lock`+`write_observer` (+3444) and that code recomputes the digest that gets anchored; **recorded, not reduced** (reduction is Stage-6 work). **Production source UNCHANGED** (diff = `tests/test_trust_boundary.py` + `scripts/mutation_check_authority.py`); directed **33/33**, mypy clean (62 files), ruff clean with the mutation script at its exact committed 6-ISC004 baseline; evidence `20260827T033547Z`. Debt registered: the facade's `_bundle_*` private re-exports (pinned by a test, removal decided at closure), the publish-time closure reduction, and the still-**NOT GREEN** `229 passed / 1 failed` full run (F-14 fixture deliberately not repaired). Prior stage: **STAGE 1 (TRUST-PLANE SPLIT): `PASS`.** Structural split (behavior unchanged): authoritative anchor+launch primitives → `src/gnosis/trust/{anchor,launch}.py`; `kernel/authority.py` now a re-export facade (one impl, no `ProbeAnchorStore` in src); `require_high` → `launch.assert_publisher_identity` (explicit future-gate locus, not weakened); canonical/verify_bundle not duplicated. 26/26 directed tests, **11/11 mutants CAUGHT**, mypy clean (62 files), ruff clean on new files, TCB load-closure = canonical+trust.* only (zero forbidden worker modules, guarded by a boundary test). Impl HEAD `7d9d075`, evidence `20260827T023738Z` (digest `b2eaf40d…`); one F-14 test hit a git-env flaky under load (passes isolated, not a split regression — full run not declared GREEN). Stages 2–8 (deployment identity, RunIdentity/PUBLISHABLE, durability, worker launcher, publisher wiring, unknown-git, provisioning) NOT started. **F-17 PRODUCTION WIRING & CLOSURE — DESIGN `APPROVE_WITH_ONE_BLOCKING_DESIGN_FINDING`; blocker fixed; spec FROZEN; authorized for staged implementation** (`docs/F17_PRODUCTION_WIRING_AND_CLOSURE.md`, grounded file:line; ADR-0027 tenth addendum). Tenth-review corrections (docs-only): unknown-`.git` reworked to a total single-valued `classify(path)` (KNOWN_TRUST_SENSITIVE→judged / KNOWN_CONTENT_OR_BOOKKEEPING→counted-where-qualified / UNKNOWN→`MACHINERY_UNQUALIFIED` fail-closed) with most-specific-wins precedence (no `refs/**`/`objects/**`→benign; `objects/info/**` never payload) + backend/version precondition + 11-test plan; launch-credential contract corrected (no "never cleartext"; no-plaintext-at-rest guarantees + DPAPI lifecycle, all fail-closed; reworded stop condition); deployment identity from OBSERVED queries + canonicalized SDs; deployment-drift matrix A–H + composition extensions; NO same-user `Popen` fallback. Earlier design highlights: trust-plane split `trust/{anchor,launch}.py` with `require_high`→`assert_publisher_identity` (OS-enforced boundary; in-process = DiD), `TrustPlaneDeploymentIdentity` bound into each anchor, `RunIdentity`+owner_worker_sid(from launcher-observed SID)/deployment_digest/PUBLISHABLE gate, run-id uniqueness reused from `RunStore.create_run`, worker launch = DPAPI+`CreateProcessWithLogonW` at the `claude_cli_runner.py:97` boundary, durable-ordering watermark (A/B crash guaranteed, C best-effort, storage out of scope) + 9-point fault matrix, §14 unknown-`.git` fail-closed (replacing the `evidence_capture.py:806-810` COUNT), clean-local-NTFS closure proving the end-to-end composition; DESIGN ONLY, no wiring; **F-17 stays OPEN**. **F-17 P2 SERVICE-SID PUBLISHER PROBE: `QUALIFIED — RESTRICTED SERVICE SID`** (2026-08-27, operator-authorized, reversible, rolled back) — a RESTRICTED virtual-account service (`NT SERVICE\GnosisTrustedPublisherProbe`, SeChangeNotify-only, worker no ACE on the service object) with a pure-ctypes SCM host (**no P2A gap**) ran the ~460-line TCB from a relocated RX-only trust root; OS-real token confirms service-SID restricting + minimal privileges; the full attack matrix (worker = distinct non-admin SID) is DENIED, legit publish → ANCHORED, pipe squatting refused (FIRST_PIPE_INSTANCE), crash never yields a false ANCHORED (watermark recovery); design in `docs/F17_P2_PUBLISHER_DESIGN.md`; evidence `20260826T234424Z` (digest `4cfb6371…`); **F-17 stays OPEN**; **F-17 DEDICATED-WORKER TOOLCHAIN QUALIFICATION: `QUALIFIED`** — full toolchain (python+pytest+gnosis import, node, git, claude 2.1.246, codex-cli 0.148.0) runs from a RELOCATED RX-only root as a dedicated non-admin worker, worker cannot write/poison any of it, operator credentials absent; evidence `20260826T213728Z` (digest `b23dc24a…`); rolled back clean; **F-17 stays OPEN — production wiring, §14, fresh FULL capture pending**; **F-17: A/B APPROVED, C the sole blocker. Fifth review built the Windows-MIC authority boundary; sixth review proved the three bypass blockers OS-real — A (no handle inheritance) satisfied, B (High-labelled code readable-not-writable) mechanism proven BUT the real `src/` is still worker-writable (must be High-labelled in the wiring), C (identity is a Director parameter) design proven. F-17 stays OPEN: label the trusted-code root High, wire the Medium launch + RunIdentity source into the engine/runner, §14, and a fresh FULL run_capture (env-blocked)**; the stale lines below are F-19..F-32, still open)

## F-17 Stage 8 — provisioning realizes the boundaries (`PASS`, awaiting independent review)

Implementation `77c639a` on top of the provisioning library `54b6a69`;
authoritative starting HEAD `ad32bba` (Stage 7 closed). Turns the qualified
architecture into reproducible, fail-closed Windows OS state: a dedicated
non-admin worker, a RESTRICTED-SID service, the ACL matrix (worker denied on
every trusted root; writable set = `{work}`; the authoritative `bundles` root
worker-denied — Stage 7 R5 realized in ACLs), a DPAPI credential blob, a
relocated runtime with `python._pth`, a relocated toolchain, and the deployment
descriptors — then OBSERVES the result before activating. Code is versioned
(`releases\<id>`); state is stable; update stages beside the running release,
verifies independently, then flips the ImagePath; a failed verify never flips;
rollback flips back. The provisioner is pure-testable behind an `Operations`
protocol and is NOT imported by the publisher runtime (closure still 15).

Four defects found OS-real and fixed: the maintenance principal resolved by the
localized name `BUILTIN\Administrators` (`ERROR_NONE_MAPPED` on non-English
Windows) → well-known SID; the service ran without `-B` so first import drifted
the deployment digest via `__pycache__` in the measured trust root → `-I -B`;
the hardened service DACL locked maintenance out of its own service → SY+BA full;
`DEPLOYMENT.json` written into the measured trust root after observation → moved
to the state base.

Qualified OS-real against disposable, production-equivalent roots and rolled
back (no permanent install): probe **140/140**; mutation **21/21 caught, 0
survived**; provision unit 27; `mypy --strict` clean (79); ruff clean; full
suite **1509 passed, 1 skipped, 263 subtests** (lone failure = the known
`work_queue` lease-timing flake, passes in isolation, untouched here);
corrected fresh-checkout requalification of the trust plane against `77c639a`
**475 passed, 1 skipped, 143 subtests**, import provenance proven to the
extraction. Evidence: `.gnosis/evidence/20260831T000844Z-stage8/`. ADR-0030.
F-14 not reopened; final F-17 qualification NOT yet authorized.

## F-17 — tamper-evidence of the evidence (ADR-0027, repaired, NOT closed)

**F-17 is repaired and PENDING its first independent review; it is NOT closed.** Selected after F-14 because the `.git/ counted-not-judged` residual was parked here, but the authoritative finding is broader: the evidence bundle was the least-protected part of the project — no hash-chain, no signature. Repair, all additive and touching no accepted F-14 contract:

- **Bundle tamper-evidence.** `write_bundle_manifest` writes `MANIFEST.sha256.json` last (covering `SUMMARY.json`): a SHA-256 of every bundle file plus one `bundle_digest`. `verify_bundle()` re-derives it and fails closed on any file added, removed or changed. HEAD/status were already inside `SUMMARY.json` from F-14's rounds. A cryptographic signature is a declared out-of-scope limitation (needs key management), not a faked guarantee.
- **`.git/` machinery judged.** A write to `.git/hooks/**` (not `.sample`) or `.git/config` during the capture is `MACHINERY_MUTATED` (exit 9) — code that runs on the next git op, or what a filter runs / where a push goes. Observed in the interval, so a hook create+delete ABA is caught; a before/after fingerprint is blind (measured). Ordinary git bookkeeping (index, refs, logs, objects) stays counted; a normal capture produces ~37 machinery events, 0 judged, and stays CLEAN.

179 directed tests; forty-seven mutants. No F-14 guarantee weakened; `MACHINERY_MUTATED` only adds a fail-closed verdict.

**Second review (2026-08-26): APPROVE_WITH_FINDINGS — both blockers addressed, pending re-review.** BLOCKER 1: a capture inside a linked worktree was bypassable (hooks/config/HEAD/index live outside the watched tree — reproduced OS-real returning CLEAN). `git_topology_eligible` refuses a worktree/submodule/separate-git-dir topology and `run_capture` fails closed with `MACHINERY_UNOBSERVABLE` (exit 10), running no checks; the standard repo stays eligible. BLOCKER 2: the in-bundle `bundle_digest` is self-consistency, not tamper-evidence; the external root of trust is the git commit plus the `bundle_digest` recorded in ADR-0027, checkable via `verify_bundle(expected_digest=…)`; a signature (authenticity) is out of scope. `.git` bookkeeping-counted is audited safe (a HEAD change -> binding TREE_MUTATED). 189 tests; fifty mutants. F-14 untouched.

**Third review (2026-08-26): BLOCKER A repaired (commit `ff37069`); B satisfied; C a reported gap. F-17 stays OPEN pending independent re-review.** BLOCKER A (git machinery classification): the classifier judged only hooks/config and COUNTED every other `.git` write, including the surfaces that redirect object/ref/ancestry RESOLUTION. Demonstrated OS-real (git 2.55) and in-code: a `refs/replace` ref — loose, packed, or a raw `packed-refs` edit — makes `git diff HEAD`/`status` report against a substituted tree with the original object bytes intact, so `content_fingerprint` (the binding) certifies a false identity with `identical:true`; `packed-refs -> inert` is refuted. Repair, additive: `git_resolution_faithful()` refuses an already-active redirection at capture start (`MACHINERY_REDIRECTED`, exit 11, nothing runs); `_is_git_resolution_redirect()` judges an in-interval write to a redirect surface (`MACHINERY_MUTATED`, exit 9), catching an ABA. grafts/shallow refused as a faithful-repo precondition (ANCESTRY, not shown to corrupt today's binding). F-14 byte-binding untouched — NOT a reopen. BLOCKER B (Gnosis-managed worktrees): F-17's `run_capture` has no in-worktree production caller; a linked worktree already fails closed; arbitrary external gitdir is refused (a `.git` file is not followed) — property already satisfied, no code. BLOCKER C (`expected_digest` home): no existing primitive gives `worker ∩ anchor = ∅` (every candidate is inside the worker-writable tree; even RunLedger has no external anchor) — reported as a TRUST ANCHOR GAP with a proposed minimal anchor-ledger-outside-the-tree primitive, unbuilt, no crypto. 15 new tests; 56 mutants (0 survived); OS-real audit; boundary CLEAN / evidence_valid over `ff37069`. Evidence `.gnosis/evidence/20260826T074918Z/` (bundle_digest `ed3aef48…`). ADR-0027 third-review addendum.

**Independent re-review + fourth review (2026-08-26): A APPROVED, B PROVISIONALLY APPROVED, C BLOCKING → `TRUST ANCHOR AUTHORITY SEPARATION NOT YET AVAILABLE`. F-17 stays OPEN; no production code changed.** The trust anchor must separate by AUTHORITY (`worker ∩ anchor = ∅`), not pathname. Reconstruction of Gnosis's real isolation (own enforcement matrix `kernel/policy.py:766`) shows there is **no enforced OS boundary**: the worker is a same-OS-user `subprocess.Popen` (`runner/claude_cli_runner.py:97`) with full filesystem write and arbitrary shell; worktree isolation and `reviewer_read_only` are `SANDBOX_APPROX` (cwd only; absolute path escapes; detection not prevention); `RunLedger` defers filesystem immutability (`kernel/ledger.py:5`). The proposed sibling-of-repo anchor is a **convention**, not authority — a same-user worker writes it — so it is **refused, not built** (per the review's §8). Against T2 (malicious same-user worker) an enforced anchor needs new infra: a distinct OS user / restricted-integrity token + ACL (or sandbox / mediating service), OR the deferred cryptographic authenticity root. F-17 today defeats T1 (accidental corruption) and gives tamper-evidence vs a non-same-user actor, but **not T2**. Also formalized (review §14): the unknown-`.git` contractual decision — an UNKNOWN trust-sensitive `.git` surface must fail closed (not counted) within the declared git scope (files backend, loose refs, git 2.55.x); implementation deferred to closure. **Next unit = the authority milestone (worker < anchor write authority), then re-attempt anchor + fresh evidence.** ADR-0027 fourth-review addendum. Do NOT close F-17.

**Fifth review (2026-08-26): OS AUTHORITY BOUNDARY built and demonstrated OS-real. F-17 stays OPEN (two closure steps remain).** The authority milestone is answered by Windows Mandatory Integrity Control: `src/gnosis/kernel/authority.py` labels the AnchorStore **High integrity NO_WRITE_UP** (`icacls /setintegritylevel (OI)(CI)High`), the Director/publisher runs **High** (elevated), and the worker is launched at **Medium** (`run_at_integrity`: token IL lowered to `S-1-16-8192` + `CreateProcessWithTokenW`, using the available `SeImpersonatePrivilege`). OS-real attack matrix (`git-authority-audit.txt`): a Medium worker and every child it spawns is **DENIED** write/create/delete/rename/change-DACL/lower-label/take-ownership/shell-child-write/python-child-write/raise-own-integrity (winerr 1314); the High publisher is **ALLOWED**. `worker ∩ anchor = ∅` by kernel-enforced process authority, not role/prompt/path — Medium keeps the worker's full toolchain (MIC chosen over separate-OS-user/restricted-SID/JobObject/broker as the minimal primitive). `AnchorRecord` + `publish_anchor` (recomputes the digest, binds the run head, confused-deputy-safe) + `verify_anchored_bundle` (authoritative digest, fail-closed). Threat: defeats **T2** (malicious same-user Medium worker); NOT T3/T4 (declared). 13 directed tests; 7 mutants (AM1–AM7), 0 survived; mypy clean (59 files); ruff baseline. Evidence `.gnosis/evidence/20260826T181515Z/` (`verify_bundle` ok, digest `0dfbeb85…`). **NOT DONE (closure): (1) wire the Medium launch into `kernel/engine`/`runner` + build the store/publisher in the pipeline; (2) a fresh FULL `run_capture` (env-blocked — 90k inputs on a slow volume exceed the long-run limit). Per the review, no fresh full capture ⇒ do NOT close F-17.** §14 (unknown `.git` → fail closed) lands with the same closure step. ADR-0027 fifth-review addendum.

**Dedicated-worker feasibility probe (2026-08-26, operator-authorized, reversible, rolled back): `PROBE RESULT: DEDICATED-WORKER QUALIFIED` (security); compat cost = toolchain relocation. F-17 stays OPEN.** A disposable non-admin user (`GnosisWorkerProbe`, group `Usuarios` only) was created, probed, and deleted (password a runtime-only SecureString; probe infra under `C:\ProgramData`; full rollback, POST-FLIGHT clean, HEAD unchanged). As the dedicated worker (SID distinct, Medium integrity): **token privileges = only SeShutdown/SeChangeNotify/SeUndock/SeIncreaseWorkingSet/SeTimeZone — NO SeDebug/SeBackup/SeRestore/SeTakeOwnership/SeImpersonate even present** (vs the lowered-elevated MIC token that retained all 24 — the decisive difference). NTFS ACL by SID: worktree RW ALLOWED; tcb_write/runid_write DENIED; anchor create/delete/rename/change_dacl/take_owner/lower_label ALL DENIED. Cross-process OpenProcess(High Director, VM_WRITE/DUP_HANDLE/CREATE_THREAD/CREATE_PROCESS/VM_OPERATION) ALL DENIED err=5. Credential isolation: operator `.claude`/`.codex`/`.gitconfig`/`.ssh` NOT ACCESSIBLE (worker can't traverse the operator profile). Git PASS (Program Files, shared); Python/Claude/Codex NOT ACCESSIBLE (operator-profile-bound → must be relocated/shared for a worker; codex needs node/npm). Evidence `.gnosis/evidence/20260826T210100Z/` (digest `40e8d81d…`, verify_bundle ok). **NEXT: decide P1 (Director High) vs P2 (service SID) publisher, design the trust-plane relocation (toolchain + trust code outside the operator profile), then production wiring, §14, fresh capture — all still to review/authorize. Do NOT close F-17.**

**Seventh review (2026-08-26): AUTHORITY BOUNDARY REQUALIFICATION (research/design, no wiring). Selected architecture = dedicated non-admin WORKER user + trusted PUBLISHER principal; NTFS ACL (by SID) PRIMARY; MIC defense-in-depth. F-17 stays OPEN.** OS-real: `run_at_integrity` builds the Medium worker by lowering the elevated token WITHOUT stripping privileges — the worker shares the Director's SID and **retains all 24 admin privileges** (present-disabled: SeBackup/SeRestore/SeDebug/SeTakeOwnership). MIC gates their USE (enabling SeDebug/SeRestore/SeTakeOwnership at Medium fails err 1300; `OpenProcess(High Director, VM_WRITE)` DENIED err 5), so direct probes are blocked — BUT same-user Medium→High is NOT a Microsoft-recognised security boundary (UAC bypasses unserviced). ⇒ **Candidate A (same-user MIC) = DEFENSE-IN-DEPTH, not a boundary.** Candidate B (dedicated non-admin user) gives a different SID → NTFS-ACL isolation (a recognised boundary) + native minimal privileges; **its OS-real probe was BLOCKED by the auto-mode classifier (local-user creation needs operator authorization)**, so B's compat/feasibility (Git/Python/Claude/Codex/credentials under a separate profile) is unverified here. Candidate C (service/service-SID) = publisher-isolation add-on. Candidate D (AppContainer) = impractical for the toolchain, rejected. `RECOMMENDATION: PROCEED WITH DEDICATED-WORKER-USER + TRUSTED-PUBLISHER (NTFS ACL primary, MIC DiD)` — the feasibility/compat probe of B is the immediate GATED next step (needs operator approval to provision a user). No wiring/§14/fresh-capture this round. ADR-0027 seventh-review addendum. Do NOT close F-17.

**P2 service-SID publisher probe (2026-08-27, operator-authorized, reversible, rolled back): `P2 PROBE RESULT: QUALIFIED — RESTRICTED SERVICE SID`. F-17 stays OPEN.** The eighth review selected P2 (minimal service-SID publisher); this proves the primitive OS-real. A disposable RESTRICTED virtual-account service (`NT SERVICE\GnosisTrustedPublisherProbe`, `SERVICE_SID_TYPE_RESTRICTED`, privileges reduced to `SeChangeNotifyPrivilege`, service-object DACL = SYSTEM+Admins only / worker NO ACE) ran a **pure-ctypes SCM host** (StartServiceCtrlDispatcher/ServiceMain/SetServiceStatus — no pywin32, so **no `P2A SCM HOST GAP`**) hosting the ~460-line TCB from a relocated trust root (`C:\Program Files\Gnosis\TrustProbe`, RX-only; state in `C:\ProgramData\Gnosis\TrustProbe`, worker no ACE). **OS-real token verified from inside the service:** user SID = the service SID, `is_token_restricted=true` (service SID in the restricting list), `privileges_present=[SeChangeNotifyPrivilege]` only, integrity High (DiD; boundary = DACL-by-SID + write-restricted token) — RESTRICTED did NOT block startup/trust-read/RunIdentity-read/AnchorStore-append/pipe-create, so **no silent fallback to UNRESTRICTED**. **Attack matrix (worker = distinct non-admin SID `GnosisP2Worker`):** legit `PublishCompletedRun(run_A)` → ANCHORED seq=0; duplicate → ALREADY_ANCHORED; cross-run (owned by another SID) → owner-mismatch; unknown/malformed/oversized → rejected; worker create-pipe → DENIED; worker writes to service binary/trust python/anchor code/RunIdentity/AnchorStore/shadow-module → ALL DENIED; worker sc change-config/stop/delete → ERROR 5; worker OpenProcess(publisher, VM_WRITE|DUP_HANDLE|CREATE_THREAD|VM_OPERATION|CREATE_PROCESS) → ALL DENIED err 5. **Pipe squatting:** worker pre-created the pipe (service down); on start the service refused (`FIRST_PIPE_INSTANCE` failed, "refuse to attach"), did NOT attach. **Crash consistency:** an unconfirmed ledger record beyond the committed watermark was truncated by trusted startup recovery; the committed ANCHORED record survived → never a false ANCHORED. Authorization = pipe DACL (worker granted `0x0012019B`, NOT `FILE_CREATE_PIPE_INSTANCE`/GENERIC_WRITE) + `RunIdentity.owner_worker_sid`; no impersonation. Defeats **T2**; T3/T4 excluded (the guarantee is exactly `Worker SID cannot obtain Publisher authority`). Full rollback verified (no residual service/user/profile/task/file/pipe; no real-path ACL changed; HEAD unchanged). Evidence `.gnosis/evidence/20260826T234424Z/` (`verify_bundle` ok, digest `4cfb6371…`). **NEXT (still to review/authorize): production worker + publisher + trusted-RunIdentity wiring; §14; full validation; fresh FULL run_capture; authoritative anchor; final independent review. Do NOT close F-17.**

**Dedicated-worker TOOLCHAIN qualification (2026-08-26, operator-authorized, reversible, rolled back): `TOOLCHAIN RESULT: QUALIFIED`. F-17 stays OPEN.** The feasibility probe left the toolchain untested relocated; this probe closes that. A disposable non-admin worker (`GnosisWorkerProbe`, group `Usuarios`, admin=False, launched via `CreateProcessWithLogonW` — no handle inheritance) ran the FULL Gnosis toolchain from a RELOCATED root `C:\ProgramData\GnosisWorkerToolchainProbe` (disposable copies of python 3.12.14 + venv site-packages, claude.exe, codex.ps1 + `@openai/codex`, gnosis pkg) whose ACL is allowlist-only (`/inheritance:r` + Administrators:F + SYSTEM:F + Usuarios:(OI)(CI)**RX**, NO deny). Node/Git are the shared Program Files installs. Worktree/scripts under `C:\ProgramData\GnosisWorkerTCprobe`, OUTSIDE the operator profile `C:\Users\nicol` (worker-non-traversable). **Worker results:** toolchain write-denial — python/claude/codex/gnosis/node all **WRITE-DENIED** (UnauthorizedAccessException); python 3.12.14, stdlib imports OK, `import gnosis.kernel.canonical` OK, **pytest `1 passed in 0.03s`**; node v24.19.0; git commit PASS; **claude 2.1.246 STARTUP PASS**; **codex-cli 0.148.0 STARTUP PASS** (both `--version` only, no login/provider request — missing-auth = EXPECTED ISOLATION); import poisoning — worker planted `evilmod.py` in its CWD, trusted import from the RX-only ToolRoot stayed **TRUSTED_IMPORT_STILL_CLEAN**; credential isolation — operator `.claude`/`.codex`/`.ssh` **ABSENT-from-worker**. Hygiene: `pycache_in_toolchain_after=True` is pre-existing pyc from the site-packages copy + an admin self-test (all worker writes denied ⇒ pytest ran without caching into the RX root — RX-only does not break pytest); secret-scan clean (only a SecureString variable reference, no value). Full rollback verified: NO Gnosis* users/services/scheduled-tasks/Win32-profiles, toolchain root + probe dir deleted, no operator/production ACL changed, HEAD unchanged. Evidence `.gnosis/evidence/20260826T213728Z/` (`verify_bundle` ok, digest `b23dc24a…`). **P2 (service SID) publisher = DESIGN ONLY, not installed.** **NEXT (still to review/authorize): publisher P1 (Director High) vs P2 (service SID) decision; production wiring of the worker-user launch + High-labelled trust plane (`src/`+interpreter) + AnchorStore/RunIdentity/publisher; §14 unknown-`.git`; fresh FULL run_capture. Do NOT close F-17.**

**Sixth review (2026-08-26): the three bypass blockers proven OS-real; F-17 stays OPEN.** **BLOCKER A (privileged handle inheritance): SATISFIED** — the Director opened the anchor WRITE with an inheritable handle, but the Medium worker launched via `CreateProcessWithTokenW` got ERROR_INVALID_HANDLE (structural: that API does not inherit handles). **BLOCKER B (publisher code integrity): mechanism proven, real gap found** — High-labelled trusted code is readable/importable by a Medium worker but NOT writable; **however the product's own `src/gnosis/kernel/authority.py` is currently Medium-writable, so the closure wiring MUST label the trusted-code root (`src/` package + `.venv` interpreter) High NO_WRITE_UP** before the boundary is complete. **BLOCKER C (authoritative RunIdentity): design proven** — `publish_anchor` takes identity as a parameter and never adopts it from the bundle (only cross-checks the head); the wiring must source `RunIdentity` from High Director state. Added `assert_integrity()` (worker asserts Medium, publisher asserts High; fail-closed on the wrong level). 18 directed tests; 8 mutants (AM1–AM8) 0 survived; mypy clean; ruff baseline. Evidence `.gnosis/evidence/20260826T184603Z/` (digest `5b2b4c68…`). ADR-0027 sixth-review addendum. **Closure still needs: High-label the trusted-code root; wire the Medium launch + RunIdentity into engine/runner; §14; a fresh FULL run_capture (env-blocked). Do NOT close F-17.**


## Kernel hardening (post-Phase -1)

Archaeology Directives 1–5 are implemented, each unit adversarially
reviewed (multi-agent workflow + refutation verify) with all confirmed
findings repaired pre- or immediately post-commit:

- ADR-0004: `kernel.canonical` single hash contract; hash-chained
  `RunLedger` with fail-closed full-chain verification; frozen transition
  tables (commit 843a72e).
- ADR-0005: `kernel.lease` fenced expiring leases, NO STALE WRITE
  test-enforced (1e176a9).
- ADR-0006: `kernel.claims` durable CAS claims + `WorkAuthority` +
  `GrantHeartbeatPump`; engine write paths fenced (ed32fa2 + repairs in
  2c50a8c). Includes the first independent **Codex** adversarial review
  (FAIL verdict, 3 findings verified true and fixed — notably the
  no-verifier INVALID DONE gate). Raw transcript:
  `.gnosis/lab/kernel-reviews/`.
- ADR-0007: provenance-gated worktree lifecycle (8ec4bfd; 13/14 review
  findings confirmed and repaired, incl. destruction reordering and the
  autosave conflict-gate holes).
- ADR-0008: `kernel.convergence` review-convergence loop (ac76d89; dual review Codex+workflow, 9/9 findings confirmed and repaired — incl. verification flip-detection and strict consecutive-evidence stalemate counting; also fixed two latent git_evidence bugs).
- ADR-0009: governed execution isolation (0efd12a) — worktree-scoped
  execution for governed runs, ownership enforced at the run-store
  boundary, governance-aware orchestrator. Closes the ADR-0006/0007
  structural follow-ups. Dual review: 19 findings, all repaired (incl. a
  heartbeat-pump leak that made a task permanently unreclaimable).
- ADR-0010: strict replay + write-ahead intent (65cef20) — occurrence-aware
  strict-by-default replay and an intent journal that makes rewind safety a
  query. Dual review: 19 findings, all true, all repaired (two criticals
  reproduced: a string mode silently downgraded strict replay to a live
  call; unserializable metadata destroyed the row for a call that happened).
- ADR-0011: fail-closed policy engine + falsifiable enforcement matrix
  (c64b8da, repairs c26f84b). Dual review: 24 findings, all true — a one-
  character quote bypassed every path rule, and an unserializable payload
  made the gate raise instead of deny.
- ADR-0012: typed failure taxonomy wired end-to-end (9d963aa) — graded
  classification, RATE_LIMITED as a credential-scoped park state,
  recovery-as-reconcile. Codex found it was UNWIRED; fixed by wiring the
  engine's retry decision onto the classification, not by documenting it.
- L-0004: a refuted review finding resurrected as a real bug (shared
  FileLock instances) — refutation assumptions are now recorded.

## Adapter milestone (COMPLETE)

The four mechanisms that existed but nothing called. Directive 9's rule
governs the order of work here: **prefer wiring over documenting**.

- [x] **PolicyEngine → a real intervention point** (ADR-0013). The gate
  runs at `before_agent_run` before any process that could act on the
  repository or on the agent's behalf, again after kernel context is
  prepended, and again before every retry; refusals are durable evidence
  (`policy.decision` + classification + `escalations/` file). Enableable
  from `DirectorOrchestrator`, the path real briefs travel. **Two
  independent reviews, and both found the headline invariant false**: the
  workflow review (21 findings, adjudicated by hand after the verify
  phase died on quota) caught code intelligence shelling out before the
  gate and no production path being able to enable it; Codex then caught
  `git worktree add` still running first, retries riding the first
  attempt's authorization, and the identity not binding the workspace.
  All repaired. What cannot be enforced (rule purity, the opt-in gate) is
  recorded in the enforcement matrix rather than implied away. See
  L-0005..L-0010, D-018..D-020.
- [x] **`InteractionStore` → the real CLI runner** (ADR-0014).
  `ReplayingCLIRunner` records and replays actual runs byte-exact,
  reproducing the stdout/stderr files the engine reads, and is reachable
  from `recording_orchestrator()`. **Independent review returned FAIL
  with 8 reproducible defects**, all repaired — the critical one being
  that the cassette key was computed from the tree the recorded agent
  itself mutates, so no recording of a repo-mutating agent replayed past
  its first call (L-0012). The review also caught the test that "proved"
  the wiring using a stand-in incapable of exhibiting the failure
  (L-0013), and the evidence line being self-reported prose — hence
  `scripts/capture_evidence.py` and D-023.
- [x] **`ConvergenceLoop` → real reviewer/fixer adapters** (ADR-0015).
  New `gnosis/adapters/` package (nothing in `kernel/` imports it, which
  is what makes provider-neutrality checkable). Rule 9 is enforced twice
  at two honest strengths: edit tools withheld (the provider's promise)
  AND a before/after workspace fingerprint that refuses a reviewer which
  moved the tree (the kernel's evidence, recorded as SANDBOX_APPROX
  because detection is not prevention). An unreadable review raises
  rather than becoming a verdict nobody gave; an unreadable FIX report is
  inconclusive rather than `cannot_fix`, because `cannot_fix` ends the
  loop. **Codex review 2026-08-21: FAIL, 8 findings, all repaired** —
  including a rule-9 bypass reachable with nothing but an accent in a
  filename (`git status` C-quotes non-ASCII paths, and the failure to
  read one was stored as a *stable* value), an object quoted in prose
  parsing as a verdict, and duplicate JSON keys resolving in the
  author's favour. The earlier self-review found 3 real defects and
  missed these 8 — see L-0016.
- [x] **Hold/park plane + `boot_sweep` under a scheduler** (ADR-0016).
  `TaskScheduler` consults holds before a launch (a refusal PARKS, never
  fails), places a durable hold when a run classifies RATE_LIMITED, and
  sweeps stranded runs at boot. Self-review found `probe()` was inert —
  a PROBE row could never narrow an ACCOUNT hold under the
  most-restrictive rule — so the store now separates observations (which
  compete) from decisions (which supersede, with a reason). No
  independent review: both channels are unavailable.

Suite: **760 tests, all passing**; mypy `--strict src` clean at the F-17
final-qualification checkpoint (qualified tree
`06cdf00ffb2eee4cd176b7d86b0c84beb764e45c`, 2026-08-31): **Success: no issues
found in 79 source files** — a checkpoint measurement, NOT a perpetual live
count (scope `src/gnosis` per `pyproject.toml`; reproduce with
`python -m mypy --strict src`; provenance `ADR-0031` and
`.gnosis/evidence/20260831T025855Z-f17-final-qualification/`); ruff at
the recorded backlog baseline (19 pre-existing findings in untouched
files, ratcheted down from 20; `.gnosis/state/lint_baseline.json` fails the run if it rises).
Captured transcript, not prose: `.gnosis/evidence/20260821T174016Z/`.

## Integration milestone (COMPLETE)

`GovernedPipeline.run_brief` (ADR-0017) is the path a real request takes
through the whole kernel: schedule (hold plane) → implement (policy gate,
worktree isolation, retries, typed classification) → converge (verify →
independent review → fix, bounded, with every reviewer and fixer launch
behind the same gate) → one `EngineerReport` whose status can only say
COMPLETED if convergence converged.

**Codex review: FAIL, 7 findings, all repaired** — two critical. Nothing
enforced that the reviewer was independent of the implementer
(`reviewer_id` was a label, and the test fixture used one agent for
both), and a crashing fixer stranded an already-consumed brief with no
report. Self-review separately found a rule 6 violation created purely by
composition: a rate limit hit by a review round never reached the hold
plane, so the next round launched into the same shut window. See L-0019.

## Integration of results (COMPLETE)

`WorkIntegrator` (ADR-0018) lands a converged task's worktree on a
**named** target branch, and only ever by fast-forward to a commit whose
MERGED tree already passed the verifier — the answer to constitution
rule 16. The headline test demonstrates the rule instead of asserting
it: two tasks fork from one base, one renames a function and updates its
own caller, the other adds a caller of the old name; git reports zero
conflicts and the merged tree raises ImportError, so nothing lands.

**Codex review: FAIL, 8 findings, all repaired or corrected** - two
critical. There was no designated target branch (it merged into whatever
was checked out, including a detached HEAD, while reporting the shared
branch had landed work), and the policy snapshot was taken before
`autosave`, so an approval for one path could authorise landing another.
The matrix's `post_merge_verification = HARD` was itself false and is
now two true claims: `verified_before_landing = HARD` (ordering) and
`semantic_correctness = IGNORED` (meaning). See L-0021, L-0022.

## Multi-worker plane (queue + budget)

`WorkQueue` (ADR-0019) is durable pending work whose OWNERSHIP is
delegated to the claims plane: every worker scans the same directory and
`WorkAuthority.acquire`'s CAS lets exactly one through. Proven by 6 real
threads racing on 24 briefs. `Budget` is the circuit breaker rule 8 named
and nothing implemented — wall clock and agent launches, durable per
brief.

**Codex review: FAIL, 7 findings, all repaired** - two critical. A crash
after the file move stranded a brief forever (found by self-review
first); and the FIX for it was itself wrong in one case, returning
already-completed work to `pending` to be re-executed. Also: a stale
grant could hand out work the worker no longer owned, and the budget was
per INVOCATION rather than per brief, so a park/resume cycle launched
agents without limit while each run looked bounded. See L-0023.

## Cross-task ordering (ADR-0020)

`plan_landings` orders converged tasks, and its real output is
`review_still_applies`: "converged" is verification AND an independent
review, and when the target moves only the verification gets re-run.
`LandingCoordinator` refuses a stale-review landing by default and the
pipeline routes landings through it.

**Codex review: FAIL, 9 findings, all repaired** - three critical. The
sharpest: `preview` returned the target's head as a task's base, so
"the base is stale" was structurally impossible to detect through the
module's own data path, and every test passed because they fed the
planner synthetic bases (L-0026). The pipeline also bypassed the
coordinator entirely, and a plan could be honoured after its head moved.

## Re-review as evidence (ADR-0021)

L-0027 said a review expires when its tree moves, and left only a
waiver. Now the integrator DERIVES staleness (fork point vs target head)
and runs an independent reviewer against the MERGED tree before the
fast-forward, using the same blocking rule convergence uses. Both halves
of convergence are re-established against the tree that lands.

**Codex review: FAIL, 5 findings, all repaired or recorded** - two
critical. `require_rereview` was a caller flag defaulting to False, so
the public API landed expired reviews silently (L-0028); and the
re-review was neither budgeted nor its refusals caught, while a comment
claimed otherwise. Self-review separately caught the pipeline assigning
the reviewer onto the shared integrator, which would have recorded every
later task's re-review under the first task's name (L-0029).

## Worker supervision and backoff (ADR-0022)

`drain` was a generator with no worker, no restart and no pacing.
`WorkerSupervisor` claims, runs, paces parks with a DURABLE exponential
`not_before`, and bounds itself against rule 8's full list. The design
question was authority, not retry: it may pace, stop and take work out of
circulation; it may not clear an attempt count or resurrect a blocked
brief.

**Shipped WITHOUT an independent review** — Codex refused with a usage
limit (reset reported 2026-09-20). The first unit since ADR-0016 with a
weaker evidence claim, and the ADR says so at the top. Self-review found
four defects, three repaired: a crash between the claims-plane call and
the file move ERASED a block decision and dropped a park's backoff
(L-0030), and a handler returning `None` was silently treated as a park
(L-0031). The first two are mutation-checked.

## The probe has a caller (ADR-0023)

ADR-0016 built `probe()` and invoked it from nowhere. Reproduced first:
an ACCOUNT hold on a window the kernel GUESSED admits nobody while it
stands and every queued resume one second after it elapses — and the
evidence that it was a guess vanishes with the hold, so the moment a
caller would want to probe there is nothing left to probe. So the probe
is claimed BEFORE the guess elapses, by exactly one caller (a
compare-and-set under one lock), with its own TTL rather than the window
it replaces, and a clean launch supersedes the hold.

**Shipped WITHOUT an independent review** — Codex still refuses on a
usage limit, re-checked at the start of this unit. Two units of review
debt now. Self-review found six defects; the one that mattered was that
the new caller went into `submit()`, which the pipeline never uses —
fixing "nothing calls it" with a caller nothing reaches (L-0033). A
concurrency test also passed with its guard mutated away, because the
race it was named after never occurred (L-0032).

## Multi-credential rotation (ADR-0024)

The last ADR-0016 residual. The scope was set by one check made BEFORE
designing anything: `Popen` was called without `env`, so no launch could
run as a different identity under any design — everything above it would
have been a decision plane with nothing underneath (L-0034).

A credential set is a **privilege boundary, not a pool**. Rules 25 and 26
are about crossing one, so the boundary is data the kernel checks:
rotation stays inside the primary credential's KIND unless another kind
is explicitly authorised, and an exhausted seat parks rather than
starting to bill. Secrets never enter the kernel — a credential names the
variables its value lives in.

**Shipped WITHOUT an independent review** (Codex usage limit) — three
units of debt now. Self-review found five defects, two critical: the
launch could not bind a credential at all, and once it could, the child
still had every OTHER credential's secret in its environment, so an agent
could spend the key the kernel had refused to select (L-0035).

## Review debt paid: three FAILs, 47 findings (2026-08-21)

Codex is rate-limited until 2026-09-20, so ADR-0022, ADR-0023 and
ADR-0024 had shipped self-reviewed. Rather than add a fourth unreviewed
unit they were reviewed by independent read-only agents in clean
contexts — a weaker channel than a different model, and each ADR header
says so.

**All three returned FAIL.** 47 findings against the 14 the self-reviews
had found; six criticals none of them saw (L-0041). The worst was not in
the new code at all: `WorkAuthority.sweep()` had **no production caller**,
so every recovery claim in this repo that depends on a claim ageing out
of ACTIVE was inert, and the suite was green because every test swept by
hand (L-0036). The second worst was a probe whose failure mode left the
credential MORE open than not probing at all (L-0037).

28 findings repaired and verified; 15 still open and listed in the
addenda rather than carried silently. The two closed since: concurrent
`recover()` — where the obvious fix was wrong and a test caught it
(L-0042) — and unpaced crash recovery. Rule 9 verified mechanically: the
tree fingerprint was identical before and after the reviews.

## Traceability audit, and F-34 — repaired four times, CLOSED on the fourth review (ADR-0025, 2026-08-22)

A read-only audit of the whole V1 surface — `docs/V1_TRACEABILITY_AUDIT.md`,
frozen at commit `83ae84e` and never edited afterwards — produced 42
findings. It refuted two of `PROJECT_REPORT.md`'s own claims (the
"repeated identical failure" and "no-diff loop" scenarios ARE tested;
"invalid state transition" is tested too, but only on the one state plane
that does not survive the process), and it found one defect no previous
review had.

**F-34.** The constitution's second rule — no task reaches DONE without
evidence — was enforced inside `if authority is not None`. The default
`DirectorOrchestrator` supplies no authority, so on the path D-018 calls
"the path real briefs travel" the rule was off, and the transition read
`verification_result.passed if verification_result else True`. That does
not mean "no verifier configured"; it means ABSENCE OF EVIDENCE IS
SUCCESS. Two lines produced a COMPLETED brief that had proved nothing.

Now: `TaskStateMachine.complete()` is the single authority for
`TaskState.COMPLETED` — `completion_is_evidenced` is the predicate it
applies, and calling it "the authority" was the round-1 overclaim
(L-0044); `execute_task` refuses a verifier-less task before it
launches anything; `run_pending` refuses before it consumes a brief.
`tests/test_no_invalid_done.py` is the first suite in this repo named
after one of the four invariants, and the mutation check that proves it
bites is CAPTURED (`mutation-check.f34.txt`) rather than asserted —
restoring the old expression turns 11 tests red across all three heights.

Evidence: `.gnosis/evidence/20260822T005432Z/` — **781 passed**, mypy
strict clean over 55 files, ruff at the 19-finding baseline exactly,
captured against a CLEAN code tree at `29d3666` (tree `cf7a2657`), with
`f34-tree-binding.json` recording `content_fingerprint()` before and
after the run.

**Four independent reviews: three FAILs, then a PASS.** Round 1 (Codex,
FAIL PARCIAL): the state machine itself walked
`VERIFYING -> COMPLETED` for anybody who asked, so the invariant was a
property of one caller. Round 2 (FAIL PARCIAL): `state` and
`completion_evidence` were public attributes, and the engine's report
printed `PASSED` for a `VerificationResult(passed=1)` the authority had
just refused. Round 3 (**FAIL CRÍTICO**): `CompositeVerifier` read its
members with `all(r.passed for r in results)` and returned a brand-new,
well-formed `VerificationResult(passed=True)` — so every strict reader
downstream was correct about evidence that had been laundered one frame
earlier — and `CompositeVerifier("empty", [])` passed on `all([]) is
True`, a DONE minted by running no check at all. The three truthy readers
round 2 named and deferred (`convergence.py`, `integration.py`,
`cli_review.py`) were still live.

The repair makes the third verdict representable as a TYPE:
`MalformedEvidence`, which is not a `VerificationResult`, so
`verification_verdict` classifies it MALFORMED by construction.
`Verifier.run` returns `Evidence`, which is what let mypy — rather than a
grep — enumerate every production reader. `CompositeVerifier` refuses an
empty collection at construction, classifies members only by verdict, and
never converts a malformed member into a pass or into an ordinary
failure. `ConvergenceLoop`, `WorkIntegrator`, `cli_review` and
`GovernedPipeline` each fail closed on MALFORMED with a differentiable
reason. Nine mutants, none survived — and the mutation check is now a
committed script (`scripts/mutation_check.py`) rather than a hand-made
transcript, so the next reviewer can re-run it. Evidence:
`.gnosis/evidence/20260822T181937Z/` — **874 passed**, mypy strict clean
over 55 files, ruff at the 19-finding baseline exactly, captured against
a clean tree at `9c6064c` (tree `baca7d24`), with
`f34-round3-tree-binding.json` recording `content_fingerprint()` strictly
before and after the run.

**Round 4 (2026-08-22): PASS — and F-34 is CLOSED.** The fourth
independent review read code `9c6064c` against evidence `f02e18e` and
verified for itself, without accepting the author's transcript, that:
both critical reproductions fail closed (a composite with a member
returning `passed=1` produces `MalformedEvidence` and the engine finishes
FAILED / PARTIAL with the problem recorded); an empty composite raises
`EmptyCompositeError` at construction; convergence, integration, the
pipeline and `cli_review` all decide on the strict verdict; and **no
productive reader of `.passed` decides outside `verification_verdict()`**
— the claim rounds 1, 2 and 3 each made and each got wrong at a different
height, now checked and empty. 249 tests and 39 subtests, targeted,
passed in the reviewer's own run. No new findings in scope.

F-34 closes by the rule this project set for itself and then had to apply
against its own earlier closure: a finding is resolved when an
independent review returns without findings, not when it looks resolved.
It is **1 of 43** — the frozen audit has 6 PASS items, 1 closed finding
and **36 open**. L-0044..L-0048 record the mechanisms; the process change
that made round 4 cheap is `scripts/mutation_check.py`, committed with
its mutants as data so a reviewer re-runs the claim instead of reading
it.

**Not closed, and named so the closure of one row is not read as the
closure of the surface around it:** F-36 (there is no `ProofPacket`),
F-14..F-18 (`capture_evidence.py` still does not bind bytes — all four
rounds worked around it with an external tree binding, and a workaround
repeated four times is a finding, not a method), the `PYTHONUTF8=1`
environment precondition that nothing in the repo enforces, and F-33 with
the thirteen capabilities that remain correct as modules and unreachable
as a program.

**Scope discipline: F-34 only.** The other 36 open findings are
untouched across all four passes — 43 items in the frozen audit, of which
6 are PASS and not defects (F-06, F-09, F-11, F-29b, F-41, F-42) and 1 is
now closed (F-34). That
includes the documentation drift THIS FILE still carries
(F-19..F-32: the stale 164-test line and mypy file count below, the
resolved-vs-pending Codex contradiction, the `src/gnosis/` "empty
scaffold" claim ADR-0002 already settled) and the absence of a production
entry point (F-33). The living matrix is `docs/V1_COMPLIANCE_MATRIX.md`;
this unit changed exactly one of its rows.

**Independent review: DONE, verdict FAIL PARCIAL (Codex, 2026-08-22).**
The reachable production route was genuinely closed. What was NOT closed
— and what ADR-0025 and the V1 matrix both overdeclared — is that the
invariant sat at the lowest point authorising COMPLETED: a bare
`TaskStateMachine` still walked `VERIFYING -> COMPLETED` with no evidence,
and `test_happy_path` asserted that it did. `6c4859a` moves the gate into
the state authority: `transition()` refuses `COMPLETED` outright and
`complete(verification)` validates a real `VerificationResult`, never a
caller-supplied flag. Evidence `.gnosis/evidence/20260822T142519Z/` —
800 passed on a clean tree at `6c4859a`, two mutants captured. See
ADR-0025's addendum and L-0044.

**Second independent review: FAIL PARCIAL again (2026-08-22).** The
gated methods held; two defects of the same closure did not.
(1) `state` and `completion_evidence` were still PUBLIC attributes, so
`sm.state = TaskState.COMPLETED` reached a terminal DONE with no
evidence, past every guard — a lock on each door and no wall (L-0045).
(2) With a `VerificationResult(passed=1)` the authority correctly refused
the DONE and the REPORT of that same task printed
`verification=("malformed: PASSED",)` with an empty problems list,
because the predicate read `passed is True` and the printer read
`if passed` — two independent readings of one field (L-0046). Both are
repaired: the storage is private behind read-only properties, and
`verification_verdict()` is now the single reader, with a third answer
(MALFORMED) that the ledger, the report and the completion predicate all
derive from. Six mutants captured, none survived. Evidence
`.gnosis/evidence/20260822T162729Z/` — 822 passed (60 subtests) on a
clean tree at `1591aa7` (tree `67d2bb9c`), mypy strict clean, ruff at the
19-finding baseline with nothing added. A third independent review was
outstanding at that point; it ran, returned FAIL CRÍTICO, and its repair
and the fourth review's PASS are recorded above. Named and NOT repaired
at the time, as candidates for that third review — all three were in fact
repaired in `9c6064c` and verified by round 4: the
same truthy read of `passed` remains in `kernel/convergence.py` (3
sites), `kernel/integration.py` and `adapters/cli_review.py`, which are
decision logic in other subsystems; none can forge a COMPLETED, but
"cannot forge a DONE" is weaker than "cannot be misread".

## F-14 — the evidence surface binds bytes, over an interval whose inputs cannot be written (ADR-0026 + two addenda, 2026-08-23)

`scripts/capture_evidence.py` recorded HEAD and `git status --porcelain`.
Status is a state and a NAME: two different dirty trees that touch the
same files produce a byte-identical bundle, and `git diff --stat` gives
the same counts for any same-length edit. Nothing in a bundle said WHICH
bytes passed the suite. The audit's receipt for that is the bundle this
project cited as proof of "760 tests passing": HEAD `92fe18ab`, four ` M`
paths, contents unrecoverable. Agreement with a later commit is an
inference from the commit, not a proof from the evidence.

The primitive was already here and this was the last surface not using
it. `probe_tree_identity()` wraps `content_fingerprint()` — HEAD, the
patch against it, and the sha256 of every untracked file's bytes per path
— and the identity is taken BEFORE the first check and again immediately
AFTER the last. Both complete fingerprints go into `SUMMARY.json`. Two
identical available fingerprints, or the capture is not evidence: a tree
that moved is `TREE_MUTATED` (exit 2) and a probe that could not answer
is `IDENTITY_UNAVAILABLE` (exit 3), both fail closed whatever the tests
said, and an unavailable PRE identity means nothing runs at all. Failed
checks (exit 1) and lint debt within the recorded baseline (exit 0) stay
distinct from both, because the operator response differs. The bundle is
built outside the repository and published after the post fingerprint, so
evidence cannot invalidate itself by existing. `all_passed` is gated on
the binding, with the ungated fact kept beside it as
`checks_all_zero_exit` — L-0046 applied to this surface before someone
had to find it again.

All four ADR-0025 rounds wrote an external `tree-binding.json` by hand
around this script. That workaround is now unnecessary.

**First independent review (Codex, 2026-08-23): FAIL CRÍTICO.** The
identity was right at both ends and the claim built on them was not. Two
fingerprints prove the tree was the same at two INSTANTS; the checks run
in the INTERVAL. A check that changed a covered file, read the change and
restored the bytes, the size and the timestamps produced
`evidence_valid: true` — and the 36 tests could not have caught it, since
every mutation they make is still visible at the post fingerprint, so all
of them are found by an endpoint comparison and none exercises
change -> read -> restore.

Nothing sampled closes that: polling, `mtime`, `git status` and a third
fingerprint are all samples of a moment, and a transient change lives
between moments. So the interval got its own authority.
`kernel/write_observer.py` streams every change under the tree from
`ReadDirectoryChangesW` — name, directory, attributes, size, last write,
creation, security — armed BEFORE the pre fingerprint and closed AFTER
the post one, so both endpoints sit inside the observed window. A stream
that could have missed something is not a clean stream: an overflowed
kernel queue fails closed, and rather than waiting out a timer for the
tail, `stop()` writes a barrier file and blocks until it OBSERVES that
barrier — notifications arrive in order, so seeing it proves everything
earlier was already delivered. Two new outcomes with their own exit
codes: `INPUTS_MUTATED` (4) for a covered input written during the run
whatever the endpoints say, and `UNOBSERVED` (5) for an interval that
could not be watched completely. `evidence_valid` is now the conjunction.

Legitimate writes stop being false positives by being moved rather than
forgiven: `PYTHONPYCACHEPREFIX`, `MYPY_CACHE_DIR`, `RUFF_CACHE_DIR` and
`PYTEST_ADDOPTS=-p no:cacheprovider` send every cache to a scratch
directory outside the tree. What remains is judged by rule, and writes
under `.git/` are COUNTED as machinery rather than judged, because git
rewrites its index while merely reading the tree.

**Second independent review (2026-08-23): FAIL CRITICO PROVISIONAL.** The
barrier proves that the notifications Windows GENERATED were delivered;
it proves nothing about whether every modification generated one. Size
and last-write notifications are documented as arriving when a change
reaches storage or the cache, and a write made through a memory-mapped
section is weaker still. Both reproductions were built and run against
the shipped code before anything changed, and they are committed as
`scripts/probe_f14_boundary.py`, driven by pipe handshakes with no sleeps
in the ordering.

A held: an independent process keeping a raw write handle open across the
whole capture, never flushing, still produced `modified: a.txt` —
`INPUTS_MUTATED`, exit 4. **B broke it:** the same through a writable
mapping notified NOTHING, the check demonstrably read the mutated bytes,
PRE equalled POST, and the bundle finished `CLEAN` / `evidence_valid:
true` / exit 0.

The repair is a category change, not a patch. A mechanism that reports
writes cannot be the whole boundary when a write can decline to be
reported, so **the covered inputs stop being writable**:
`kernel/input_lock.py` holds every one of them open with `GENERIC_READ`
and a share mode of `FILE_SHARE_READ`, and Windows then refuses any other
open asking for write or delete — which is also the only way to obtain a
writable mapping. Measured here: **718 covered inputs locked in 6.17 s**.
Prevention and observation cover each other's blind spots by
construction: prevention for content written into a file that exists,
observation for creating, deleting and renaming a path, which are
directory operations no cache can defer. If any covered input cannot be
locked — another process already holds it open for writing — nothing runs
at all: `UNPROTECTED`, exit 6.

**Third independent review (2026-08-23): repair accepted, closure on
hold.** Four adversarial questions, all answered by running something.
(A) A writable section keeps the file object alive with its original
access, so a view with no handle behind it still refuses the lock —
verified in four shapes, `ERROR_SHARING_VIOLATION` every time, capture
runs nothing. (B) The protected handle and the identified object were
never tied together: every handle now records `FILE_ID_INFO` (volume
serial plus 128-bit file id), is verified to still resolve to its own
path, and the map goes into the bundle as `input-identities.json`;
reparse points are refused outright and a hard link to a covered input is
refused as a property of the share mode rather than by a check. (C) The
acquisition window was uncovered: the identity that matters is now taken
AFTER the inputs are unwritable and must equal the pre-check one, else
`PREPARATION_DRIFT`, exit 7, and nothing runs. (D) The guarantee is no
longer extrapolated: drive type and filesystem are probed against a
whitelist, a UNC path is refused as a redirector, and the answer is
recorded in the bundle.

Measured: 733 covered inputs locked, identified and path-verified in
0.45 s. **Demonstrated on Windows, local volume, `fixed`, NTFS — and, after the fourth review, declared on exactly that and nothing wider.**

**Fourth independent review (2026-08-23): FAIL DE ALCANCE.** No new
finding against the architecture. One confirmed defect, and not in the
mechanism: the domain the code ACCEPTED was wider than the domain anyone
had DEMONSTRATED. `_SUPPORTED_FILESYSTEMS` held `{"NTFS", "ReFS"}` while
the boundary had only ever run on NTFS — no ReFS volume on this machine,
no probe run on one, no evidence bundle containing the string, and the
two tests that named it admitted it as an alternative in an assertion
that always resolved by NTFS. L-0053 says exactly this and was written in
the same commit as the violation; writing a lesson down is not applying
it.

Narrowed: `_SUPPORTED_FILESYSTEMS = {"NTFS"}`, with ReFS moved to
`_CANDIDATE_FILESYSTEMS` and refused with its own reason — "nobody has
run it there" is a different fact from "it cannot work there" — before a
single input is opened. The route back is signposted and is not a code
change first: run the probe and the suite on a real ReFS volume, land the
bundle, then move the string.

**The demonstrated domain: Windows, local volume, `fixed`, `NTFS`. ReFS
is a candidate extension pending real validation, not a guarantee.**

**Fifth independent review (2026-08-23): FAIL PARCIAL — ALTA.** The main
repair and the evidence over the real tree were accepted. One fail-open
path remained, in the place claiming the strongest guarantee: a covered
input that is a DIRECTORY — a submodule gitlink — made `CreateFileW` fail
with ERROR_ACCESS_DENIED, was reopened with `FILE_FLAG_BACKUP_SEMANTICS`,
appended to the handle list and never passed to `_identify`. It counted
towards `locked_inputs`, never reached `identities`, and the outcome
could still say `enforced: true` — while every bundle carried this
module's own line, "every protected handle is recorded by FILE_ID_INFO".
A handle on a submodule's directory also proves nothing about the bytes
inside it that a check would read.

Declined rather than extended. A directory-like covered input is refused
BEFORE any open, by its attributes rather than by the error it happens to
produce; the `FILE_FLAG_BACKUP_SEMANTICS` retry is gone from `acquire`
(the flag survives only in `volume_serial_of`, which opens the root,
reads and closes); and there is now no path that appends a handle without
identifying it. The invariant is asserted rather than argued: the
producer refuses when handles and identities disagree, the consumer
refuses such an outcome whatever `enforced` says, and the bundle records
`protection.fully_identified`.

The ancestor reparse point is closed by the same data: the
`VolumeSerialNumber` inside `FILE_ID_INFO` must equal the root's, so a
junction or mount point above a covered path cannot put the input on a
volume that was never demonstrated. Read once and cached — per-input it
cost 7.4 s, cached 0.66 s for 761 inputs.

**Sixth independent review (2026-08-24): FAIL PARCIAL — ALTA.** The
reparse check asked whether the TARGET was a reparse point and never
whether the PATH used to reach it could be redirected. Measured on this
machine: `repo\linked -> dirA`, lock enforced over `dirA\under.py`,
then `rmdir linked` and `mklink /J linked dirB` both SUCCEEDED while a
handle on the object was held, and `repo\linked\under.py` read
`SWAPPED-B`. Restoring the junction made the tree look untouched. A
junction is a directory entry: holding the file protects the file, not
the name, and the volume serial cannot see it because both directories
are on the same NTFS volume. The second half was in
`classify_observation`, which forgave every directory event — added,
removed, renamed — purely because the path was a directory again by the
time it looked, which is exactly what a junction removed and recreated
leaves behind.

Refused rather than supported. `reparse_in_chain()` walks from the drive
down and returns the first component that can redirect; an unreadable
component counts as one. It runs over the repository root and all its
ancestors once, and over every directory between the root and each
covered input, cached. One reparse point anywhere refuses the capture
before a check runs. The classifier now forgives exactly one thing about
a directory, `modified`, because its timestamp moves when its entries
move; creating, removing or renaming one is judged like anything else.
Cost of the chain walk: 775 inputs locked, identified and checked in
0.52 s warm.

**Seventh independent review (2026-08-24): FAIL PARCIAL.** Three places
assumed git-ignored files were outside the boundary —
`content_fingerprint` does not enumerate them, `covered_paths` did not
add them, and `classify_observation` forgave whatever `git check-ignore`
accepted. Together that is "ignored ⇒ cannot affect the result", and it
is false: a `.env`, a local config, a database, a fixture, or the
interpreter and tools in `.venv` are all ignored and all real inputs.
Reproduced before anything changed: a check read `MALICIOUS` out of an
ignored file and the bundle reported CLEAN, evidence_valid true,
all_passed true, exit 0.

Repaired with three declared classes and a conservative default. INPUT
(covered, locked, identified) is everything git can enumerate — tracked,
untracked AND ignored — that is not declared otherwise. OUTPUT is a
declared root the checks legitimately write. OUT_OF_SCOPE is a declared
root the evidence claims nothing about, is not locked, and where any
event is a VIOLATION rather than an allowance. `git check-ignore` is not
consulted anywhere any more, and both lists are recorded in the bundle.

The policy was measured, not guessed: covering everything ignored with
the nested clones expanded is 90,237 paths and 1,218 s to lock, against
2,944 paths and 2.3 s as declared. 2,130 of those inputs are `.venv` —
the toolchain is now inside the boundary rather than outside it by
accident. The measurement also found `.zerker/memory.sqlite` held open by
the ZMem server, which is why an OUTPUT class is a necessity rather than
a convenience.

**Eighth independent review (2026-08-25): FAIL ALTO.** The review took
this unit's own residual risk no. 3 and made it the finding: an ignored
INPUT was covered, locked and identified by object, and its BYTES were
nowhere in the evidence. Three guarantees had been running under one
word. A file id says WHICH object. A lock says the object did not change
while the checks ran. Neither says WHAT was in it, and F-14's sentence is
about bytes. Nearly 2,000 of the 2,958 inputs were `.venv` — the
interpreter and the tools that produced the result — inside the boundary
by object and outside it by content.

Every input is now hashed through the handle that holds it:
`handle_digest()` seeks the locking handle to zero and reads it with
`ReadFile`, so the bytes hashed cannot be a second, different object
opened by the same path. `LockOutcome.content_digests` is the per-file
map, `content_digest` is the aggregate and is deliberately a different
number from `identity_digest`, and `fully_bound` (`locked ==
len(content_digests)`) is asserted at the producer, where an unreadable
handle is a refusal, and re-checked at the consumer, where an
enforced-but-unhashed lock is UNPROTECTED with its own wording.
`input-manifest.json` ships the map so a third party re-derives the claim
from the files instead of believing the summary.

`.venv` stays an INPUT and is bound by the same rule — option (A), chosen
on a measurement: the whole input set is 2,958 files and 99.4 MB, hashed
in 2.39 s warm. A fourth TOOLCHAIN class with version-based provenance
would have been more machinery for a weaker guarantee, since two
toolchains can report identical nominal versions and differ in bytes.

OUT_OF_SCOPE is deleted from the code rather than emptied. Of the two
admissible models, "prove no check can consume it" was tested and failed:
a directory handle opened with `FILE_SHARE_NONE` blocks *listing* the
directory and does not block opening files inside it by path. So the
class is bound instead, at the measured price of 88,424 files and 2.4 GB
— 1,170 s to hash cold, 1,218 s to lock cold. `covered_paths` now expands
the directory entries git reports for nested clones instead of leaving
them to be refused. Whatever already exists under a declared OUTPUT root
when a capture begins is hashed into `outputs_at_start`, so a file
planted there and read by a check is named rather than anonymous.

Captured on `de74053` as `.gnosis/evidence/20260825T011601Z/`: 90,245
inputs locked, identified AND byte-bound, `fully_bound` true, boundary
CLEAN, `evidence_valid` true, exit 0, with `identity_digest ec4dbb5c…`
and `content_digest 55d64f5b…` as two different numbers over the same
files. A 301-entry sample of `input-manifest.json` re-hashed 301 of 301.
The bundle is ~28 MB, and later captures hash earlier bundles as inputs.

**Ninth independent review (2026-08-25): FAIL CRÍTICO PROVISIONAL.**
NTFS named data streams. A path is not a sequence of bytes: it is
`::$DATA` plus any number of named streams, each openable as `path:name`,
each readable by an ordinary `open()`, none of them visible to
`git ls-files`, to `Path.read_bytes`, or to a handle on the main stream.
Reproduced before anything changed: with `probe.txt::$DATA` untouched and
`probe.txt:gnosis-f14` flipped from ALLOW to DENY, a check read different
bytes and both bundles carried identical `identity_digest` and
`content_digest`, both `evidence_valid` true. The same run showed the
main-stream handle left the named stream writable AND deletable, and that
directories carry streams too.

Repaired by option (A). Every named stream of every covered INPUT, and of
every directory up to the repository root, gets its own handle, its own
identity and its own digest read through that handle. The identity is
`owner-id:file-id:name:length`, because `FILE_ID_INFO` returns the same
file id for every stream of a file - so only the content digest separates
two same-length contents, and there is a test that demonstrates exactly
that rather than asserting around it. Enumeration is `FindFirstStreamW`,
and a path whose streams cannot be enumerated is a refusal.

No share mode prevents a NEW stream being created, on a file or a
directory, including `FILE_SHARE_NONE` - measured. So there is a second
detector that does not depend on the observer: the inventory is taken
with the boundary up and again after the checks, and anything that
appeared, vanished or changed length is `STREAMS_MUTATED`, exit 8. That
is what covers directories, because a stream write on one arrives as
`modified <dir>` and the classifier forgives exactly that event.

The disk is walked for the 83 directories that hold no input at all,
excluding `.git/` and declared OUTPUT roots. `outputs_at_start` hashes
pre-existing OUTPUT streams. Cost: ~56 s per capture.

Captured on `42f461b` as `.gnosis/evidence/20260825T043839Z/`: 90,261
inputs, boundary CLEAN, `evidence_valid` true, exit 0, `identity_digest
eb7af0e4…`, `content_digest 3568d3ef…`. Named streams found in this tree:
**zero**, on inputs and on the 250 pre-existing OUTPUT files alike, which
is review item 8's answer — the machinery reports none and flags nothing.
The capability is shown by the before/after attack transcripts and the
tests, not by the repository happening to contain a specimen.

**Tenth independent review (2026-08-25): F-14.10, the directory
named-stream A->B->A.** A named data stream created and deleted on a
DIRECTORY during the interval leaves both inventories identical, the lock
cannot pre-open a stream that does not exist, and the observer forgave the
one event a directory produces (`modified <dir>`, because an entry move
produces it too). Reproduced before any change, through `run_capture`
against an export of `8dd621c`: `pkg:secret` -- and a stream on the
repository root itself -- created, read (`ALLOW`) and deleted, boundary
CLEAN, evidence_valid true, exit 0.

Repaired by observing the transient, with no elevation. The recursive
write observer now requests the stream notify filters and maps actions
6/7/8, so an `added_stream`/`removed_stream` on any covered path is
STREAMS_MUTATED (exit 8). Measured before it was built: the stream flags
make a directory stream create arrive as `added_stream`, which an entry
move never produces; reading a stream emits `modified_stream`, so that
action is not a violation (the capture reads every locked stream to hash
it, and a write to a locked stream is refused). The repository root's own
streams are invisible to its own recursive watch, so a second
non-recursive watch on the parent covers exactly that directory, with its
own barrier; if the parent is unwatchable the observation is INCOMPLETE
(fail closed), never CLEAN. The USN change journal records the ABA but
needs an admin volume handle, so it corroborates and is not a dependency.

`fully_identified` and `fully_bound` are now documented, in the code and
in the bundle (`scope_note`), as properties of the lock-time SNAPSHOT and
never of the interval: the interval guarantee is a CLEAN verdict over a
COMPLETE observation, which now sees stream transitions on directories.

**Eleventh independent review (2026-08-25): F-14.11, auditing CLEAN over
COMPLETE.** Not a repair — an audit for an unobserved window between the
real start of the boundary and the real end of the capture, memory-mapped
writes named as the crux. No new bypass was found. Measured on real NTFS:
a mapped write changes bytes immediately and ReadDirectoryChangesW reports
nothing (not even on flush), so the observer is not the defence; the lock
is, by failing closed for any live writable mapping (ERROR_SHARING_VIOLATION
under every share mode, file and named stream), and refusing a new mapping
while it holds the input. run_capture with a live mapping returns
UNPROTECTED, exit 6, running no check. Copy-on-write coexists with the read
lock but never touches the file.

The lifecycle was read from the code, not assumed: the watch is armed
before the boundary and the ordered barrier is drained before any verdict,
so there is no start race and no end race. Overflow, an unarmed or failed
watch, or an unwatchable parent all yield UNOBSERVED, never CLEAN. The
`modified_stream` tolerance is now a demonstrated invariant: a locked
stream admits no overwrite, truncate, delete, second writable handle or
mapping. COMPLETE is formally defined -- no event from the supported
mechanism was lost -- and separated in the evidence (`complete_note`) from
the snapshot booleans, so nothing claims "every filesystem modification was
observed". The only production change is that one advisory string.

**F-14 is CLOSED.** The twelfth independent review (2026-08-25) returned
APPROVED / CLOSE F-14 within the declared formal contract, after ten
repairs and an eleventh-round audit: tested (166 directed, 1040 full
suite) and mutation-checked (forty-two mutants, none survived). Ten
reviews found a defect; the eleventh found no new bypass; the twelfth
accepted the state. Implementation `1672a8a`, evidence `cd6d1b5`, bundle
`.gnosis/evidence/20260825T135642Z/`, closure recorded in ADR-0026 and
`docs/V1_COMPLIANCE_MATRIX.md`.

The closure preserves, and does not soften, the declared limitations:
`fully_identified`/`fully_bound` are snapshot properties, not interval
claims; `COMPLETE` is limited to the supported observation mechanism;
fail-closed on overflow / observer failure / unwatchable parent; the
`modified_stream` tolerance is conditional on revalidation if the platform
or a write route changes; the scope is Windows + local + fixed + NTFS;
`.git/` counted-not-judged belongs to F-17; and F-15..F-18 remain open and
untouched.

**Overlap recorded, not claimed:** F-15 (the unused primitive) is what
this script now uses; F-16 (capture order) no longer affects the binding
though the command list is unchanged; F-17 now has HEAD, the status
digest and both identities inside `SUMMARY.json` but still **no hash
chain and no signature**; F-18 is untouched. None of them are marked
repaired. The addendum adds one more overlap, also unclaimed: `.git/`
writes are counted and not judged, so a hook installed during a capture
is outside this boundary and inside F-17's.

**Round nine measured the flakiness instead of describing it.** The
family is wider than the single test named below:
`test_concurrent_workers_never_run_a_brief_twice` and
`test_a_brief_never_ends_up_in_two_directories_at_once` both fail with
`PermissionError(13)` on concurrent file operations. Isolated and run in
alternation on the same machine, they failed 5 times in 20 against a
pristine export of HEAD `43bc232` and 3 times in 20 against the
round-nine tree. None of the twelve `gnosis` modules they import is one
this unit changed.

**The baseline was not green at the start of this unit, and not because
of it.** The full suite at `aea62b0` returned 1 failed, 873 passed:
`test_work_queue.py::TestACrashedWorkerLosesNothing::`
`test_recovery_never_takes_a_brief_from_a_live_worker`. The fixture
`_short_lived()` sets a 50 ms lease TTL, and that test needs the lease
alive across four file-locked round-trips while its neighbours sleep
150 ms precisely to let it expire. Reproduced at 1 failure in 5 runs in
isolation; mypy clean, ruff at the 19 baseline in the same run. A
pre-existing flaky test, left alone because this unit is scoped to F-14
and because making a test deterministic is a change to `tests/` that no
F-14 evidence should carry.

## Fixed locations

- Project: `C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi`
- External repositories: `C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi\external\repositories`

## Inherited baseline (pre-pack milestones, committed M0→M3)

The repo already contains a working kernel baseline built in an earlier
session: `gnosis/` package (state machine, ledger, leases via file locks,
worktrees, CLI runner, verification, recovery, code-intelligence wiring,
memory contract + router) with a 164-test suite, plus milestone evidence
in `docs/M*.md` and `.gnosis/lab/*/results/`. The v0.3 environment pack
was extracted on top of that baseline (commit 8955932). At this M0→M3
inherited baseline the implementation lived in a top-level `gnosis/` package
while the v0.3 constitution named `src/gnosis/`, then an empty scaffold — an
active layout conflict AT THAT TIME. **ADR-0002 subsequently resolved it** by
moving the implementation to `src/gnosis/` (`git mv gnosis src/gnosis`, history
preserved) while keeping the Python import namespace `gnosis` unchanged. The
current canonical source layout is therefore **`src/gnosis/`** (filesystem source
path; Python import package `gnosis`, via `pythonpath = ["src"]` and wheel
`packages = ["src/gnosis"]`); there is **no root production `gnosis/` source
tree**, and `src/gnosis/` is the populated implementation, not a scaffold.
ADR-0002 (ACCEPTED) is the canonical layout decision.

## Target-machine gates

- [x] Bootstrap executed (doctor/inventory state present).
- [x] Claude Code Fable 5 + Ultracode validated (this session runs on it).
- [x] Codex CLI installed (0.148.0) and authenticated ("Logged in using ChatGPT", 2026-08-19 evening). Usage quota exhausted until 2026-08-20; adversarial review parked as RATE_LIMITED until then.
- [x] External repos inventoried: 27/130 resolved locally (all Tier S/S+ except the license-blocked one; report: `.gnosis/state/clone_report.json`).
- [x] M3 installed/configured/smoke-tested (uv tool, PYTHONUTF8=1, env-pinned roots; ADR-0001).
- [x] ZMem installed/configured/smoke-tested (uv tool; governance loop revalidated on 0.1.17).
- [x] Cross-session Memory Fabric test passed (`tests/integration/test_memory_fabric_smoke.py`, 3/3; docs/research/MEMORY_FABRIC_STATUS.md).
- [x] Tier S architecture archaeology completed: 23 repos analyzed (10 deep + 3 group sweeps, 14 agents, read-only) → `docs/research/REFERENCE_REPOSITORY_FINDINGS.md` (summary table, 9 kernel architecture directives, contradictions/open questions, per-repo findings with evidence labels).
- [x] Initial ADRs confirmed (ADR-0001; D-017; L-0001..L-0003).
- [x] Kernel implementation (Phase 1 continuation) began after archaeology — this
  "begins" gate is satisfied. The gate was a legitimate forward-looking item when
  written (pre-implementation); the Tier-S archaeology (above) completed first,
  Phase-1 kernel implementation subsequently began, and the checklist simply was
  not reconciled afterward. Earliest evidence: the post-archaeology Phase-1 kernel
  hardening starting at ADR-0004 (canonical hashing + chained ledger). Subsequent
  implementation/hardening is tracked by the authoritative Phase-1 kernel
  milestones/ADRs; later F-14/F-17 trust-plane work corroborates that
  implementation continued. This records that implementation BEGAN, not that all
  kernel work is complete.

## Suite status

- Latest qualified full-suite checkpoint — **F-17 final qualification**, qualified
  production tree `06cdf00ffb2eee4cd176b7d86b0c84beb764e45c`, 2026-08-31:
  **1510 passed, 1 skipped, 291 subtests, exit 0 — GREEN** (directed 613 passed;
  isolated fresh-checkout 475 passed).
- Suite size at that checkpoint / current unchanged test tree: **1511 collected
  tests** (`.venv/Scripts/python.exe -m pytest tests/ --collect-only -q`).
- Exact qualification counts and provenance: `ADR-0031` and
  `.gnosis/evidence/20260831T025855Z-f17-final-qualification/`. These are
  checkpoint-qualified measurements, NOT a perpetual invariant; the live suite
  size is derivable via `pytest --collect-only`.

## Known open items / caveats

- Codex CLI setup/login is complete: tracked state records authentication on
  2026-08-19 (see the "Target-machine gates" item) and an independent
  policy-gate review executed on 2026-08-20 (`NEXT_ACTIONS`). Login is therefore
  NOT a pending setup gate. Live credential validity and quota are operational
  state and may change independently — at the recorded quota checkpoint usage
  was reported exhausted with reset scheduled for 2026-09-20; that condition is
  a rate-limit, and must NOT be interpreted as "login pending".
- Docker absent (LOW; sandbox/integration later).
- cass_memory_system: never clone/copy/analyze — license bars Anthropic-affiliated use.
- zmem 0.1.17 `status`/`doctor` crash on Windows (diagnostic-only; use `audit health`).
- m3 embedding tier unconfigured (FTS fallback); `m3 setup` deliberately not run.
- Bernstein clone required `core.longpaths=true` (now set globally).
- `security-audit/` contains non-GNOSIS leftovers (Minecraft-skin audit logs, 16MB) — gitignored, awaiting operator decision to delete/move.
- MCP servers for both engines are declared in `.mcp.json`; they attach on next Claude Code session approval.
