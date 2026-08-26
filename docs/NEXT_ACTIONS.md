# GNOSIS Next Actions — Nicol workstation

0-XI. **F-17 P2 TRUSTED PUBLISHER SERVICE — DESIGN & PROBE PLAN PREPARED, AWAITING OPERATOR AUTHORIZATION (2026-08-27). DESIGN ONLY; no service installed.** Full design + reversible probe plan in **`docs/F17_P2_PUBLISHER_DESIGN.md`**. Selections: service identity = **standalone Virtual Service Account** `NT SERVICE\GnosisTrustedPublisher` (dedicated per-service SID, not LocalService-shared, not LocalSystem, not interactive-admin); **SID type = RESTRICTED** (write-restricted token; probe is the decider, fall back to UNRESTRICTED only if a required access is infeasible); privileges = **SeChangeNotify only** (all dangerous ones stripped/justified-absent, no impersonation — caller SID via `GetNamedPipeClientProcessId`+`OpenProcessToken(QUERY)`); worker has **no ACE** on the service object (can't change config/ImagePath/binary/DACL/delete/start/stop); trust code → `C:\Program Files\Gnosis\Trust\` (RX to SVC, worker no ACE), mutable state (AnchorStore+RunIdentity) → `C:\ProgramData\Gnosis\Trust\` (DACL by SID, MIC High as DiD). **TCB MEASURED & MINIMIZED:** publisher import closure = **4 gnosis modules (~460 lines: canonical 53 + authority anchor-slice + extracted `bundle_verify` ~40 + entry/IPC ~120) + a dedicated python runtime** — NOT `src/`+`.venv`; importing `verify_bundle` from `evidence_capture` would drag in **3444 lines** of capture machinery (evidence_capture+git_evidence+input_lock+write_observer) the publisher does NOT need, avoided via the existing injectable `verify=` seam (`authority.py:386`). Decision **P2A (python on trusted runtime, reuse reviewed authority.py/canonical.py verbatim)** over a native reimpl (which would be a second implementation of the hash core). IPC = one-verb named pipe `PublishCompletedRun(run_id)` (no path/bytes/digest/HEAD fields); authz = caller-SID ∈ allowed-workers ∧ RunIdentity[run_id].owner==caller (no cross-run publish); pipe SD grants worker connect+r/w-message only (no FILE_CREATE_PIPE_INSTANCE), server uses FIRST_PIPE_INSTANCE (anti-squat) + REJECT_REMOTE. Startup = demand-start + idle self-stop (minimal residency). Failure = two-phase watermark → **never a false ANCHORED**; idempotency key run_id. Threat: defeats **T2**; **T3/T4 excluded** — the guarantee is exactly `Worker SID cannot obtain Publisher authority`, NOT "admin/SYSTEM can't compromise". 24-item attack matrix specified. **Operator approvals required to run the probe: create/delete a virtual-account service (`sc create/sidtype/privs/sdset/delete`), create/delete a disposable trust root + state dirs + worker user, set their ACLs, start the service on demand, send test IPC. All reversible, disposable, no real-path ACL change. Do NOT install the service, do NOT wire, do NOT §14, do NOT fresh-capture until authorized.** F-17 OPEN.

0-X. **F-17 DEDICATED-WORKER TOOLCHAIN QUALIFICATION — RUN (operator-authorized) → `TOOLCHAIN RESULT: QUALIFIED`. F-17 stays OPEN.** Reversible probe executed and fully rolled back. The feasibility probe qualified the security boundary but left the toolchain untested relocated; this closes that. Disposable non-admin `GnosisWorkerProbe` (group `Usuarios`, `CreateProcessWithLogonW`, no handle inheritance) ran the FULL toolchain from a RELOCATED root `C:\ProgramData\GnosisWorkerToolchainProbe` (python 3.12.14 + venv site-packages, claude.exe, codex.ps1 + `@openai/codex`, gnosis pkg) with allowlist ACL `/inheritance:r` + Admins:F + SYSTEM:F + Usuarios:(OI)(CI)**RX** (node/git = shared Program Files). **Worker: all five binaries WRITE-DENIED; python + `import gnosis` + pytest `1 passed`; node v24.19.0; git PASS; claude 2.1.246 STARTUP PASS; codex-cli 0.148.0 STARTUP PASS (--version only, no login = EXPECTED ISOLATION); import poisoning → TRUSTED_IMPORT_STILL_CLEAN; operator `.claude`/`.codex`/`.ssh` ABSENT-from-worker.** Required worker-writable locations = worktree/CWD + temp + git repo (all outside the operator profile); trust plane stays RX. Hygiene: `pycache=True` pre-existing (worker writes denied ⇒ RX-only does not break pytest); secret-scan clean. Full rollback: no Gnosis* users/services/tasks/profiles, root+probe-dir deleted, no production ACL changed, HEAD unchanged. Evidence `.gnosis/evidence/20260826T213728Z/` (`verify_bundle` ok, digest `b23dc24a…`, anchored in ADR-0027). **P2 (service SID) publisher = DESIGN ONLY, not installed.** **NEXT (still to review/authorize): publisher P1 (Director High) vs P2 (service SID); production wiring of the worker-user launch + High-labelled trust plane (`src/`+interpreter) + AnchorStore/RunIdentity/publisher; §14 unknown-`.git`; fresh FULL run_capture. Do NOT close F-17.**

0-IX. **F-17 DEDICATED-WORKER FEASIBILITY PROBE — RUN (operator-authorized) → `PROBE RESULT: DEDICATED-WORKER QUALIFIED` (security). F-17 stays OPEN.** Reversible probe executed and fully rolled back (disposable non-admin `GnosisWorkerProbe`, SecureString password, `C:\ProgramData` infra; POST-FLIGHT clean, HEAD unchanged). As the dedicated worker (distinct SID, Medium IL): **token holds only SeShutdown/SeChangeNotify/SeUndock/SeIncreaseWorkingSet/SeTimeZone — NO SeDebug/SeBackup/SeRestore/SeTakeOwnership/SeImpersonate even present** (the decisive win over Candidate A). NTFS ACL: worktree RW; tcb_write/runid_write/anchor(all: create/delete/rename/change_dacl/take_owner/lower_label) DENIED. Cross-process OpenProcess(High Director, all 5 rights) DENIED err=5. Credential isolation: operator secrets NOT ACCESSIBLE (no profile traverse). Git PASS (shared); **Python/Claude/Codex NOT ACCESSIBLE (operator-profile-bound → COMPAT COST: relocate the toolchain outside the operator profile for a dedicated worker; codex needs node/npm).** Evidence `.gnosis/evidence/20260826T210100Z/` (`verify_bundle` ok, digest `40e8d81d…`). **NEXT (still to review/authorize): (1) decide publisher P1 (Director High) vs P2 (service SID); (2) design the trust-plane + toolchain relocation outside the operator profile + per-profile credential provisioning; (3) production wiring of the worker-user launch + AnchorStore/RunIdentity/publisher; (4) §14 unknown-`.git`; (5) fresh FULL run_capture. No wiring/§14/capture yet. Do NOT close F-17.**

0-VIII. **F-17 DEDICATED-WORKER FEASIBILITY PROBE — PLAN PREPARED, AWAITING OPERATOR AUTHORIZATION (2026-08-26).** Architecture APPROVED (dedicated non-admin worker user + trusted publisher + NTFS ACL by SID primary + MIC DiD). The exact probe is specified in **`docs/F17_DEDICATED_WORKER_PROBE_PLAN.md`** (user `GnosisWorkerProbe` in group `Usuarios` only; ACL matrix; launcher alternatives; feasibility + credential + network + cross-process + token-privilege test plans; P1 Director-High vs P2 service-SID publisher; TCB package; exact reversible OS changes; rollback; risks; operator approvals). **NOT executed** — it creates a local Windows account (needs operator approval; the auto-mode classifier blocks user creation). Read-only recon done: git in Program Files (shared), venv/claude/codex under nicol's profile (worker needs RX or a toolchain copy), `.claude`/`.codex`/`.gitconfig` are per-profile (worker isolated). **Operator approvals required:** create/delete a non-admin user; launch processes as it; grant RX on toolchain OR copy a minimal toolchain; start Claude/Codex binaries (startup only, no provider calls); accept the rollback. **Do NOT wire, do NOT create the user, do NOT implement §14, do NOT fresh-capture until authorized.** F-17 OPEN.

0-VII. **F-17 SEVENTH REVIEW / AUTHORITY BOUNDARY REQUALIFICATION (2026-08-26) — research/design, no wiring. SELECTED: dedicated non-admin WORKER user + trusted PUBLISHER principal; NTFS ACL (by SID) PRIMARY; MIC defense-in-depth.** OS-real finding: the current Medium worker is a lowered elevated token that **retains all 24 admin privileges** and shares the Director's SID; MIC gates their use (enable SeDebug/SeRestore/SeTakeOwnership at Medium → err 1300; `OpenProcess(High Director, VM_WRITE)` → DENIED err 5), but same-user Medium→High is NOT a Microsoft-recognised boundary ⇒ **Candidate A = defense-in-depth, not a boundary.** Candidate B (dedicated user) = different SID → NTFS-ACL isolation (recognised boundary) + native minimal privileges; **its OS-real probe was BLOCKED (auto-mode classifier refuses local-user creation)** so B's toolchain/credential compat is UNVERIFIED here. C (service SID) = publisher add-on; D (AppContainer) = impractical, rejected. **NEXT (GATED — needs operator approval): provision a non-admin worker user and run the B feasibility probe (Git/Python/Claude/Codex/credentials/networking/cleanup under a separate profile) BEFORE any wiring.** Then: lay a minimal trust plane on a worker-non-writable root; wire the worker-user launch + High RunIdentity store + AnchorStore/publisher; §14; fresh FULL run_capture. Keep the MIC lab as defense-in-depth. ADR-0027 seventh-review addendum. Do NOT close F-17; do NOT wire yet.

0-VI. **F-17 SIXTH REVIEW / three bypass blockers (2026-08-26) — proven OS-real; F-17 stays OPEN.** **A (handle inheritance): SATISFIED** — `CreateProcessWithTokenW` does not inherit handles (Director's inheritable WRITE handle → worker got ERROR_INVALID_HANDLE). **B (publisher code integrity): mechanism proven (High-labelled code is readable-not-writable by a Medium worker) but the REAL `src/gnosis/kernel/authority.py` is currently Medium-writable — the closure wiring MUST label the trusted-code root (`src/` package + `.venv` interpreter) High NO_WRITE_UP.** **C (RunIdentity): design proven** — `publish_anchor` takes identity as a parameter, never adopts it from the bundle; wiring must source `RunIdentity` from High Director state. Added `assert_integrity()` (fail-closed on wrong integrity). 18 tests; 8 mutants (AM1–AM8) 0 survived; mypy clean; ruff baseline. Evidence `.gnosis/evidence/20260826T184603Z/` (digest `5b2b4c68…`). **NEXT (closure): (1) High-label the trusted-code root; (2) wire the Medium launch + a High RunIdentity registration into `kernel/engine`+`runner/*` + build store/publisher; (3) §14 unknown-`.git`; (4) fresh FULL `run_capture` (env-blocked). No fresh full capture ⇒ do NOT close F-17.** ADR-0027 sixth-review addendum. Do NOT close F-17.

0-V. **F-17 FIFTH REVIEW / OS AUTHORITY BOUNDARY (2026-08-26) — the real Windows-enforced boundary is BUILT and demonstrated OS-real; F-17 stays OPEN pending two closure steps.** `src/gnosis/kernel/authority.py`: AnchorStore labelled **High NO_WRITE_UP**; publisher/Director **High** (elevated); worker launched at **Medium** (`run_at_integrity` — token IL lowered + `CreateProcessWithTokenW`, `SeImpersonatePrivilege` held). OS-real matrix (`git-authority-audit.txt`): Medium worker + children **DENIED** on write/create/delete/rename/DACL/label/owner/shell-child/python-child/raise-integrity (winerr 1314); High publisher **ALLOWED** → `worker ∩ anchor = ∅` by kernel authority, not role/path. MIC chosen over separate-user/restricted-SID/JobObject/broker (minimal). `AnchorRecord`+`publish_anchor` (recomputes digest, binds head, confused-deputy-safe)+`verify_anchored_bundle` (authoritative, fail-closed). Defeats **T2**; not T3/T4 (declared). 13 tests; 7 mutants (AM1–AM7) 0 survived; mypy clean; ruff baseline. Evidence `.gnosis/evidence/20260826T181515Z/` (digest `0dfbeb85…`). **NEXT (closure): (1) wire the Medium-integrity launch into `kernel/engine` + `runner/*` and build the AnchorStore+publisher in the pipeline (touches every launch + ADR-0009 — needs a fresh capture to validate); (2) implement §14 (unknown `.git` → fail closed); (3) a fresh FULL `scripts/capture_evidence.py` that publishes+verifies against the anchor. Env currently blocks the full capture (slow volume + long-run cap). Per the review, no fresh full capture ⇒ do NOT close F-17.** ADR-0027 fifth-review addendum. Do NOT close F-17; do NOT start F-15/F-16/F-18.

0-IV. **F-17 FOURTH REVIEW (2026-08-26) — A APPROVED, B PROVISIONALLY APPROVED, C BLOCKING → `TRUST ANCHOR AUTHORITY SEPARATION NOT YET AVAILABLE`. F-17 stays OPEN; NO production code changed.** The trust anchor must separate by AUTHORITY (`worker_write_authority ∩ anchor_write_authority = ∅`), not pathname. Investigation (subagent + `kernel/policy.py` enforcement matrix, `runner/claude_cli_runner.py:97`, `adapters/cli_review.py:49`, `kernel/ledger.py:5`): **no enforced OS boundary exists** — the worker is a same-OS-user `subprocess.Popen` with full filesystem write and arbitrary shell; worktree/reviewer isolation is `SANDBOX_APPROX` (cwd only, detection not prevention). The proposed `source_repo.parent/.gnosis-anchors` sibling ledger is a CONVENTION, not authority (a same-user worker writes it) → **refused, not built** (review §8: do not build a false separation). Against T2 an enforced anchor needs NEW infra: a distinct OS user / restricted-integrity token + ACL (or sandbox / mediating service), OR the deferred cryptographic authenticity root. F-17 today defeats T1 and gives tamper-evidence vs a non-same-user actor, NOT T2. Also formalized (review §14): unknown trust-sensitive `.git` surface must FAIL CLOSED (not counted) within the declared git scope (files backend, loose refs, git 2.55.x) — implementation deferred to closure. **Next action: NOT "write the anchor file" — it is an AUTHORITY MILESTONE: give the worker genuinely lower filesystem authority than the anchor store (separate OS user / restricted token + ACL, or a mediating service the worker can't bypass), OR adopt the crypto authenticity root; only then can `ANCHORED`/`verify_anchored_bundle` exist without a false promise. Then re-attempt the anchor and produce fresh evidence. This is a decision for the operator (new infra / scope).** ADR-0027 fourth-review addendum. Do NOT close F-17; do NOT start F-15/F-16/F-18.

0-III. **F-17 THIRD REVIEW DONE (2026-08-26) — BLOCKER A repaired (`ff37069`), B satisfied, C a reported gap. F-17 stays OPEN pending an independent re-review.** BLOCKER A: `git_resolution_faithful()` (start gate, `MACHINERY_REDIRECTED`, exit 11) + `_is_git_resolution_redirect()` (interval judge, `MACHINERY_MUTATED`, exit 9) judge the `.git` surfaces that redirect object/ref/ancestry resolution — refs/replace (loose/packed/raw packed-refs edit), alternates, http-alternates, grafts, shallow, config.worktree, commondir. `packed-refs -> inert` refuted OS-real. F-14 byte-binding untouched (NOT a reopen). BLOCKER B: no in-worktree caller of `run_capture`; linked worktree already fails closed; arbitrary external gitdir refused — no code. BLOCKER C: TRUST ANCHOR GAP — no existing primitive gives `worker ∩ anchor = ∅`; minimal anchor-ledger-outside-the-tree primitive proposed, unbuilt, no crypto. 15 tests; 56 mutants (0 survived); OS-real audit `git-resolution-audit.txt`; capture over `ff37069` BOUND/CLEAN/evidence_valid (pytest 1075 passed; only failure is the pre-existing work-queue flake, not F-17). Evidence `.gnosis/evidence/20260826T074918Z/` (`verify_bundle` ok, digest `ed3aef48…`). **Environment note: the full 90k-input `run_capture` bundle could not be freshly committed this session (slow synced disk + long-run cap); the completed capture's SUMMARY is in the bundle; reproduce with a warm cache via `scripts/capture_evidence.py` detached.** **Next action: hand F-17 (BLOCKERS A/B/C) to an independent re-review.** Do NOT close F-17. Do NOT start F-15/F-16/F-18.

0. **CURRENT UNIT — F-17 (tamper-evidence), repaired, PENDING first independent review (ADR-0027).** Not closed. The evidence bundle now carries `MANIFEST.sha256.json` (SHA-256 of every file + a `bundle_digest`), re-derivable by `verify_bundle()`, fail-closed on any post-capture edit; a cryptographic signature is a declared out-of-scope limitation. The F-14 `.git/` residual is folded in: a hook (`.git/hooks/**`, not `.sample`) or `.git/config` written during the capture is `MACHINERY_MUTATED` (exit 9), caught in the interval so an ABA is caught; ordinary git bookkeeping stays counted (measured: normal capture ~37 machinery events, 0 judged). 179 directed tests, forty-seven mutants, mypy clean, ruff baseline. **Next action: hand F-17 to an independent review.** No F-14 contract changed. Do NOT start F-15/F-16/F-18.

0c. **CONTEXT RESET CHECKPOINT (2026-08-26): read `docs/HANDOFF_F17_2026-08-26.md` FIRST.** Full handoff for the F-17 third review — HEAD `d3f9d14`, the five F-17 commits, the current bundle and its external anchor, the definitions ladder, the three operator-dictated BLOCKERS (A: git machinery classification incl. packed-refs; B: Gnosis-managed worktrees; C: where `expected_digest` lives), accepted vs pending decisions, residual risks, standing constraints and the working method. No production code changed when it was written.

0b. **F-17 second review (2026-08-26): APPROVE_WITH_FINDINGS — both blockers addressed, pending re-review.** BLOCKER 1: worktree/submodule/separate-git-dir captures now fail closed (`MACHINERY_UNOBSERVABLE`, exit 10) via `git_topology_eligible`; a real bypass was reproduced OS-real. BLOCKER 2: `verify_bundle(expected_digest=…)` checks the bundle against the external root of trust (git commit + digest in ADR-0027); signature out of scope. 189 tests, fifty mutants. **Next: hand F-17 to re-review.** Do NOT start F-15/F-16/F-18.

1. ~~codex login~~ DONE; quota confirmed restored 2026-08-20 and the parked policy-gate review was run (FAIL, 7 findings, all adjudicated — transcript in `.gnosis/lab/kernel-reviews/codex-review-2026-08-20-policy-gate.jsonl`). ~~Codex RATE_LIMITED until 2026-09-19~~ **RESOLVED 2026-08-21**: the operator re-ran `codex login` and quota returned. The parked review of the convergence adapters ran immediately (FAIL, 8 findings, all repaired — ADR-0015 addendum 2); the scheduler review ran too (FAIL, 9 findings, all repaired — ADR-0016 addendum). **Both review debts are now paid; no unreviewed unit remains.** Historical note, kept because the failure mode will recur: **Codex reported a month-long reset** (reported reset "Sep 19th, 2026 2:52 AM" — a month, not a day; it ran out mid-review of the replay wiring, transcript `.gnosis/lab/kernel-reviews/codex-review-2026-08-20-replay-runner.jsonl`). Per rule 6 this is a park, not a failure: and the internal reviewer subagents separately died with "out of usage credits", so for a stretch there was no independent review channel at all and two units (ADR-0015, ADR-0016) shipped self-reviewed. L-0016 measures what that cost: the self-review of ADR-0015 found 3 real defects and missed 8, including a rule-9 bypass reachable with an accent in a filename. When a channel is down, units still ship — but the ADR says so, and the debt goes here. Still parked for Codex: the replay-wiring review it could not finish, and the earlier kernel-hardening commits (843a72e, 1e176a9).
2. **Adapter milestone COMPLETE** (ADR-0013..0016; 552 tests). All four mechanisms Directive 9 found unwired now have production callers: the policy gate (reachable from `DirectorOrchestrator`), record/replay (`recording_orchestrator()`), convergence (`CliReviewer`/`CliFixer`), and the hold/park plane (`TaskScheduler`). ~~Next: integration~~ **DONE** (ADR-0017): `GovernedPipeline` runs a brief through schedule → implement → converge → report, with every agent launch gated. ~~Next: integration of results~~ **DONE** (ADR-0018): `WorkIntegrator` lands converged work by fast-forward to an already-verified merge on a named branch. ~~Next: multi-worker plane~~ **PART 1 DONE** (ADR-0019): durable queue with fenced claims, crash recovery, and a durable per-brief budget. ~~Next: cross-task ordering~~ **DONE** (ADR-0020). ~~Next: worker supervision and backoff~~ **DONE** (ADR-0022, self-reviewed only). ~~Next: `probe()` having an automatic caller~~ **DONE** (ADR-0023). ~~Next: multi-credential rotation~~ **DONE** (ADR-0024) — with it the ADR-0016 residuals are closed. **Next, by decision: pay down the review debt.** Three consecutive units (ADR-0022, 0023, 0024) shipped self-reviewed because Codex refuses on a usage limit, and they touch ownership, spending and credentials — exactly what rule 10 says needs independent judgement. Directive 9's rule governs: a mechanism nothing calls is a parallel fiction, so prefer wiring over documenting — and per L-0006, wiring it to the kernel primitive is not enough, it must be exercised from the outermost production entry point. Also deferred by decision: per-epoch worktrees (rejected for V1); RunStore-internal token verification (multi-process worker milestone); the M4 memory-provider benchmark (ADR-0003 criteria).
3. Optional lint polish: 20 pre-existing ruff residuals repo-wide (BLE001/PLW1510/TRY004/UP046-47), none in files touched by ADR-0011..0013 — whitelist with per-line noqa+reason or fix, when touching those files anyway. mypy strict is at zero for src/gnosis.
4. M4 memory-provider selection criteria written (ADR-0003); execute the M4 benchmark itself when memory adapters become the active milestone.
5. Restart Claude Code once so the `.mcp.json` memory servers (zerker-memory, m3-memory) attach; smoke one MCP tool call each.
6. Resume kernel build sequence (MASTER_AUTONOMOUS_BUILD_DIRECTIVE Phase 1+) — gates are open once archaeology lands.
7. Optional, evidence-gated: Graphify benchmark vs Sverklo/CodeGraph (only per MEMORY_FABRIC.md rule, after GNOSIS-Bench exists).
8. Consider upstream bug reports (with operator approval): zmem Windows diagnostic crash; m3 `--database` provisioning gap.
9. Operator decision: delete or relocate the unrelated `security-audit/` leftovers.

## Current unit: the traceability audit

`docs/V1_TRACEABILITY_AUDIT.md` (frozen at `83ae84e`) carries 42 findings.
`docs/V1_COMPLIANCE_MATRIX.md` is the LIVING matrix — a row changes only
when an ADR with captured evidence backs it.

- **F-34 CLOSED (2026-08-22), fourth independent review PASS.**
  ADR-0025 (`29d3666`) closed the reachable production route; an
  independent Codex review returned **FAIL PARCIAL** because the state
  authority itself still admitted `VERIFYING -> COMPLETED` with no
  evidence, and `6c4859a` closed that. A **second** independent review
  returned **FAIL PARCIAL** again: `state`/`completion_evidence` were
  still public attributes (`sm.state = TaskState.COMPLETED` reached a
  terminal DONE past every guard), and the engine's report printed
  `PASSED` for a `VerificationResult(passed=1)` the authority had just
  rejected. Both repaired in this unit — private storage behind read-only
  properties, and `verification_verdict()` as the single reader of
  `passed` with a third answer, MALFORMED, that the ledger, the report
  and the completion predicate all derive from. Six mutants captured,
  none survived. Evidence `.gnosis/evidence/20260822T162729Z/` (822
  passed, 60 subtests, clean tree at `1591aa7`). A **third** independent
  review then returned **FAIL CRÍTICO**: `CompositeVerifier` read its
  members with `all(r.passed for r in results)` and returned a fresh
  `VerificationResult(passed=True)`, so a `passed` of `1` reached
  `TaskState.COMPLETED` and `ReportStatus.COMPLETED` with every strict
  reader downstream behaving correctly — and `CompositeVerifier("empty",
  [])` passed on `all([]) is True`, having run nothing. The three readers
  listed below as "candidate findings" were still live. Repaired in this
  unit: `MalformedEvidence` makes "states no verdict" a TYPE that
  `verification_verdict` classifies MALFORMED by construction;
  `Verifier.run` returns `Evidence`, so mypy enumerates the readers;
  `CompositeVerifier` refuses an empty collection at construction and
  never converts a malformed member into a verdict; `ConvergenceLoop`,
  `WorkIntegrator`, `cli_review` and `GovernedPipeline` each fail closed
  with a differentiable reason. Nine mutants, none survived, and the
  mutation check is now a committed script
  (`scripts/mutation_check.py`). Evidence
  `.gnosis/evidence/20260822T181937Z/` (874 passed, 60 subtests, clean
  tree at `9c6064c`). A **fourth** independent review then read code
  `9c6064c` against evidence `f02e18e` and returned **PASS**: both
  critical reproductions fail closed, the empty composite raises
  `EmptyCompositeError` at construction, convergence, integration, the
  pipeline and `cli_review` all decide on the strict verdict, and no
  productive reader of `.passed` decides outside `verification_verdict()`
  — verified by the reviewer's own run (249 tests, 39 subtests targeted),
  not by the author's transcript. No new findings in scope. **F-34 is
  closed**, by the rule that a finding closes when an independent review
  returns without findings. Nothing about F-34 remains to do.

- **F-14 repaired (ADR-0026), NOT closed — awaiting a FIRST independent
  review.** The evidence script recorded HEAD and `git status`, which is
  a state and a name: two different dirty trees touching the same files
  produced a byte-identical bundle. It now takes the tree's content
  identity (`content_fingerprint()`, the primitive the repo already had
  and this surface was the last not to use) before the first check and
  again after the last, writes both complete fingerprints into
  `SUMMARY.json`, and refuses to call itself evidence if they differ or
  if either could not be taken — whatever the tests said. Four outcomes
  stay distinct with four exit codes: checks failed (1), tree mutated
  (2), identity unavailable (3), lint debt within the recorded baseline
  (0, and not a failure). The bundle is built outside the repository and
  published after the post fingerprint, so it cannot appear in its own
  identity.

- **First independent review (Codex, 2026-08-23): FAIL CRÍTICO — equal
  endpoints are not a stable interval.** A check that changed a covered
  file, read the change and restored the bytes, size and timestamps
  produced `evidence_valid: true`: two fingerprints prove two instants,
  and the checks run between them. None of the 36 tests could have caught
  it, because every mutation they make is still visible at the post
  fingerprint. Repaired: `kernel/write_observer.py` streams every change
  under the tree (`ReadDirectoryChangesW`), armed BEFORE the pre
  fingerprint and closed AFTER the post one behind a delivery barrier —
  a written marker the observer must SEE, since notifications arrive in
  order and a timer is exactly what the finding refuted. A covered input
  written during the run is `INPUTS_MUTATED` (exit 4) whatever the
  endpoints say; a stream that overflowed or could not be armed is
  `UNOBSERVED` (exit 5), never "nothing happened". Caches are redirected
  out of the tree rather than forgiven inside it.

- **Second independent review (2026-08-23): FAIL CRITICO PROVISIONAL — a
  write can decline to be observed.** The barrier proves the delivery of
  notifications Windows generated, not that every modification generated
  one. Reproduced against the shipped code before changing anything, and
  committed as `scripts/probe_f14_boundary.py`: a raw write with an open
  handle DOES notify (held), but a write through a memory-mapped view
  notifies nothing, so a check consumed mutated bytes and the bundle
  reported `CLEAN` / `evidence_valid: true` / exit 0. Repaired by
  prevention rather than by patching the case: `kernel/input_lock.py`
  holds every covered input open with `FILE_SHARE_READ` for the duration
  of the checks, so Windows refuses write, writable mapping, delete and
  rename to everything else — 718 inputs locked in 6.17 s here. What
  cannot be locked in advance (paths that do not exist yet) stays the
  observer's job. If any covered input cannot be protected, nothing runs:
  `UNPROTECTED`, exit 6.

- **Third independent review (2026-08-23): repair accepted, closure on
  hold.** Four adversarial questions, all answered by measurement. A
  writable section with no file handle behind it still refuses the lock
  (four shapes, error 32, capture runs nothing). Every protected handle
  now records `FILE_ID_INFO` and is verified to still resolve to its own
  path; reparse points are refused and a hard link to a covered input is
  refused by the share mode itself. The identity that matters is taken
  AFTER the locks are in place, so the acquisition window cannot hide a
  change — `PREPARATION_DRIFT`, exit 7, nothing runs. And the volume is
  probed rather than assumed, UNC refused. 733 inputs locked and
  identified in 0.45 s.

- **Fourth independent review (2026-08-23): FAIL DE ALCANCE — the
  accepted domain was wider than the demonstrated one.** No new finding
  against the architecture. `_SUPPORTED_FILESYSTEMS` held
  `{"NTFS", "ReFS"}` and the boundary had only ever run on NTFS: no ReFS
  volume here, no probe run on one, no evidence bundle containing the
  string, and the two tests naming it admitted it as an alternative in an
  assertion that always resolved by NTFS. Narrowed to `{"NTFS"}`, with
  ReFS moved to `_CANDIDATE_FILESYSTEMS` and refused with its own reason
  before any input is opened. **The demonstrated domain is Windows +
  local + `fixed` + `NTFS`.** To add ReFS: run the probe and the suite on
  a real ReFS volume, land that bundle, then move the string — in that
  order. 87 tests, 7 subtests; twenty-one mutants, none survived (MF21
  puts ReFS back and the suite goes red).

- **Fifth independent review (2026-08-23): FAIL PARCIAL — ALTA. One
  fail-open path, in the place claiming the strongest guarantee.** A
  covered input that is a DIRECTORY — a submodule gitlink — was reopened
  with `FILE_FLAG_BACKUP_SEMANTICS`, appended to the handle list and
  never identified: it counted as locked, never reached `identities`, and
  the outcome could still say `enforced: true` against the module's own
  published line. Declined rather than extended: directory-like covered
  inputs are refused before any open, the retry is gone, no path appends
  a handle without identifying it, and the invariant `locked ==
  identified` is asserted in the producer, re-checked in the consumer and
  recorded in the bundle as `protection.fully_identified`. The ancestor
  reparse point is closed by requiring every object's
  `VolumeSerialNumber` to be the root's. 94 tests, 7 subtests;
  twenty-two mutants, none survived (MF22 restores the defect in three
  edits at once).

- **Sixth independent review (2026-08-24): FAIL PARCIAL — ALTA. The lock
  held the object and not the path.** The reparse check looked at the
  target and never at the chain used to reach it. Measured: a junction
  above a covered input was removed and recreated against another
  directory on the same volume WHILE a handle on the object was held, and
  the lexical path then read the other directory; restoring it made the
  tree look untouched. `classify_observation` also forgave every
  directory event because the path was a directory again at the end —
  precisely the trace that attack leaves. Refused rather than supported:
  `reparse_in_chain()` walks the root's own chain once and every
  directory between the root and each covered input, and one reparse
  point anywhere means `UNPROTECTED`, exit 6, zero checks; the classifier
  forgives only `modified` on a directory. 103 tests, 7 subtests;
  twenty-four mutants, none survived (MF23 and MF24, one per half). The
  probe is ten cases in four groups.

- **Seventh independent review (2026-08-24): FAIL PARCIAL — "git ignores
  it" was being used as authority.** `content_fingerprint` does not
  enumerate ignored files, `covered_paths` did not add them, and
  `classify_observation` forgave whatever `git check-ignore` accepted;
  together that reads as "ignored ⇒ cannot affect the result". Reproduced
  first: a check read `MALICIOUS` from an ignored file inside a bundle
  that said CLEAN / evidence_valid true / all_passed true. Repaired with
  three declared classes — INPUT by default (everything git enumerates,
  ignored included), OUTPUT declared, OUT_OF_SCOPE declared and any event
  there a violation — and `git check-ignore` removed as an authority.
  Measured: 2,944 inputs in 2.3 s, against 90,237 and 1,218 s if the
  nested clones are expanded; `.venv` (2,130 files) is now an INPUT. 118
  tests, 19 subtests; twenty-five mutants, none survived.

- **Eighth independent review (2026-08-25): FAIL ALTO — covered, locked
  and identified is not byte-bound.** The review used this unit's own
  residual risk no. 3 as the finding. Object identity (`FILE_ID_INFO`:
  WHICH file), temporal stability (the lock: it did not change while the
  checks ran) and cryptographic content identity (WHAT was in it) are
  three separate guarantees, and holding two read like holding three:
  nearly 2,000 of the 2,958 inputs were `.venv`, inside the boundary by
  object and outside it by content. Repaired by hashing every input
  THROUGH the handle that holds it (`SetFilePointerEx` + `ReadFile`, not
  a second open by path), a `content_digest` deliberately distinct from
  `identity_digest`, a `fully_bound` invariant asserted at the producer
  and re-checked at the consumer with its own failure wording, and
  `input-manifest.json` in the bundle so a third party re-derives the
  claim from the files. `.venv` stays an INPUT (option A) because the
  measurement said so: 2,958 files / 99.4 MB in 2.39 s warm, against a
  TOOLCHAIN class whose version-based provenance cannot separate two
  toolchains with equal nominal versions and different bytes.
  **OUT_OF_SCOPE is deleted from the code**, not emptied: the "prove no
  check can consume it" model was tested and failed — a directory handle
  with `FILE_SHARE_NONE` blocks *listing* and does not block opening the
  files inside it by path — so the price is paid instead, measured at
  88,424 files and 2.4 GB, 1,170 s to hash cold. Pre-existing content
  under a declared OUTPUT root is hashed into `outputs_at_start`, so it
  cannot be an anonymous prior input. 127 tests; twenty-nine mutants,
  none survived; captured on `de74053` as
  `.gnosis/evidence/20260825T011601Z/` over 90,245 byte-bound inputs,
  boundary CLEAN, exit 0.

- **Ninth independent review (2026-08-25): FAIL CRÍTICO PROVISIONAL -
  NTFS named data streams.** A path is `::$DATA` plus any number of named
  streams, each openable as `path:name`, each readable by a check, none
  of them visible to git or to a handle on the main stream. Reproduced
  first: main stream untouched, `probe.txt:gnosis-f14` flipped ALLOW ->
  DENY, the check read different bytes, and both bundles carried
  identical `identity_digest` AND `content_digest`, both `evidence_valid`
  true. The main-stream handle also left the named stream writable and
  deletable, and directories carry streams git never enumerates.
  Repaired with option (A): every stream gets its own handle, its own
  identity (`owner-id:file-id:name:length`, because one file id covers
  every stream of a file) and its own digest read through that handle;
  `FindFirstStreamW` enumerates and a failure to enumerate is a refusal;
  a second detector compares the inventory before and after, because no
  share mode prevents a NEW stream - measured, including
  `FILE_SHARE_NONE` - giving `STREAMS_MUTATED` and exit 8; the disk is
  walked for the 83 directories holding no input; `outputs_at_start`
  hashes pre-existing OUTPUT streams. 148 tests; thirty-five mutants,
  none survived; captured on `42f461b` as
  `.gnosis/evidence/20260825T043839Z/` over 90,261 inputs, zero named
  streams present in this tree, boundary CLEAN, exit 0.

- **Tenth independent review (2026-08-25): F-14.10, the directory
  named-stream A->B->A.** A named stream created and deleted on a
  DIRECTORY inside the interval leaves both inventories identical; the
  lock cannot pre-open a stream that does not exist; and the observer
  forgave the only event a directory produced, `modified <dir>` (an entry
  move produces it too). Reproduced first, through `run_capture` against
  `git archive 8dd621c`: `pkg:secret` and a stream on the repo root
  itself, created->read->deleted, boundary CLEAN, evidence_valid true,
  exit 0. Repaired by observing the transient with no elevation: the
  recursive observer now requests the stream notify filters and maps
  actions 6/7/8, so `added_stream`/`removed_stream` on any covered path is
  STREAMS_MUTATED (exit 8); reading a stream emits `modified_stream`,
  which is NOT a violation (measured: the capture reads every locked
  stream to hash it, and a write to a locked stream is refused); the
  root's own streams are invisible to its recursive watch, so a second
  non-recursive watch on the parent covers them, failing closed if the
  parent is unwatchable. The USN journal corroborates but needs admin, so
  it is not a dependency. `fully_identified`/`fully_bound` are documented
  as snapshot properties, not interval claims (`scope_note`). 156 tests;
  forty mutants, none survived.

- **Eleventh independent review (2026-08-25): F-14.11, auditing CLEAN over
  COMPLETE.** An audit, not a repair: is there an unobserved window
  between the real boundary start and capture end, especially via a
  memory mapping made before the boundary? No new bypass found. Measured
  on real NTFS: a mapped write is silent to ReadDirectoryChangesW (even on
  flush), so the lock, not the observer, is the defence -- it fails closed
  (ERROR_SHARING_VIOLATION) for any live writable mapping on a file or a
  stream and refuses a new one while holding the input, so run_capture
  with a mapping alive returns UNPROTECTED, exit 6. Lifecycle confirmed:
  watch armed before the boundary, ordered barrier drained before any
  verdict (no start/end race); overflow / failed watch / unwatchable
  parent -> UNOBSERVED, never CLEAN; the `modified_stream` tolerance is
  now a demonstrated invariant (a locked stream admits no modification
  route); COMPLETE formally defined and separated from the snapshot
  booleans (`complete_note`). Only production change: that advisory
  string. 166 tests; forty-two mutants, none survived.

- **Twelfth independent review (2026-08-25): APPROVED / CLOSE F-14.**
  **F-14 is CLOSED** within the declared formal contract. Implementation
  `1672a8a`, evidence `cd6d1b5`, bundle
  `.gnosis/evidence/20260825T135642Z/`, closure in ADR-0026 and the
  compliance matrix. The declared limitations are preserved and not
  softened (snapshot-scoped `fully_identified`/`fully_bound`; `COMPLETE`
  limited to the supported mechanism; fail-closed on overflow/observer
  failure/unwatchable parent; conditional `modified_stream` tolerance;
  Windows+local+fixed+NTFS scope; `.git/` counted-not-judged is F-17).
  **No further F-14 action.** F-15..F-18 remain open and untouched; do not
  start F-15 until instructed.

- **Observed overlap with F-15..F-18, none of them marked repaired:**
  F-15's suggested correction is what this script now does, but the
  finding covers the evidence surface and one script changed; F-16's
  ordering defect no longer affects the binding, though the command list
  is unchanged and `git-status.stdout.txt` is still post-suite; F-17 now
  has HEAD, the status digest and both identities inside `SUMMARY.json`
  and still has **no hash chain and no signature**; F-18 is untouched.
  The addendum adds one more, also unclaimed: writes under `.git/` are
  counted and not judged, so a hook installed mid-capture is outside this
  boundary and inside F-17's.

- **A pre-existing flaky test, found while checking the baseline and
  deliberately not repaired here:**
  `test_work_queue.py::TestACrashedWorkerLosesNothing::`
  `test_recovery_never_takes_a_brief_from_a_live_worker` fails about 1
  run in 5. `_short_lived()` sets a 50 ms lease TTL and this test needs
  the lease alive across `recover()`, `running_ids()` and `complete()` —
  four file-locked JSON round-trips on Windows — while its neighbours
  sleep 150 ms precisely to let it expire. It is a timing defect in the
  test, not in the queue. Repairing it means making it deterministic
  (inject the clock, or give this one test its own TTL), which is a
  change to `tests/` that no F-14 evidence should carry. **Next unit that
  touches the work queue, or a standalone one by direction.**
- **The three truthy readers round 2 deferred are now REPAIRED**, not
  deferred again: `kernel/convergence.py` (one verdict per round, the
  flip memo holds verdicts, malformed verification is a typed evidence
  failure), `kernel/integration.py` (landing gated on
  `verification_verdict(...) is PASSED`, with `VERIFICATION_INVALID` as
  its own outcome) and `adapters/cli_review.py`
  (`verification_prompt_line`, three answers). L-0048 records why naming
  them and deferring them was not enough.
- **The count, so no living document repeats it wrong again:** the frozen
  audit holds **43 items** (F-01..F-42 plus F-29b). **6 are PASS** and are
  not defects (F-06, F-09, F-11, F-29b, F-41, F-42); **1 is closed**
  (F-34); **36 are open**. History of this count, because it has been
  wrong twice: one version said 41, counting the PASS items and F-34 as
  work; one said "1 closed (F-34)" before the third review reopened it;
  one said "0 closed, 37 open", correct while F-34 was reopened. The live
  count is **6 PASS · 1 closed · 36 open**. Direction sets the order;
  nothing outside F-34 was touched in any of the four passes,
  deliberately.

- **What the closure does NOT cover**, named here so the next unit does
  not inherit a false floor: **F-36** (no `ProofPacket`); **F-14..F-18**
  (`capture_evidence.py` still records `git status` after the suite and
  never imports `content_fingerprint()` — all four F-34 rounds worked
  around it with an external tree binding, which makes the workaround a
  finding rather than a method); the **`PYTHONUTF8=1` precondition** that
  the suite depends on and nothing in the repo enforces; and **F-33** with
  the thirteen capabilities still inert.

The ones this project's own history says will cost the most:

1. **F-33 — no production entry point.** `GovernedPipeline` is the only
   path that requires verification AND an independent review, and nothing
   constructs it. Thirteen of twenty-two V1 capabilities are correct as
   modules and unreachable as a program. Probably a milestone, not a
   repair.
2. **F-35 — `WorkAuthority.sweep()`'s only caller is `WorkerSupervisor`,
   which nothing constructs.** The repair for "nothing calls it" was a
   caller nothing reaches (L-0033, again). V1 nº19 is still inert.
3. **F-07 / F-08 — the two DURABLE state planes validate nothing.**
   `RunStore.update_state` and `BriefRecordStore.update` write any state
   with no transition table; `RunStateMachine` has no production caller.
   The only validated plane is the one that dies with the process.
4. **F-14..F-18 — the evidence script does not bind bytes.**
   `content_fingerprint()` already exists, is used in four production
   modules, and `capture_evidence.py` does not import it; it also records
   `git status` AFTER the suite. ADR-0025 worked around this with an
   external `f34-tree-binding.json` rather than repairing it, because the
   unit was scoped to F-34.
5. **F-01..F-04 — there is no task DAG.** V1 nº2 and nº3 have no
   implementation; `kernel/ordering.py` orders already-converged tasks
   for landing, which is a different problem.
6. **F-19..F-32 — documentation drift**, including contradictions inside
   this very file (sections 1 and 2 below), the stale 164-test line in
   `PROJECT_STATE.md`, and a `README.md` describing a project twenty ADRs
   ago.

Also still open, from the earlier reviews: the 15 findings listed in
`PROJECT_REPORT.md §8`.

## Exact next command

```bash
cd "C:/Users/nicol/Desktop/Claude Code Proyectos/GnosisAgentAi"
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/capture_evidence.py
```

That script now fails closed rather than producing an unattributable
transcript: exit 2 if the endpoints differ, exit 3 if the identity could
not be taken, exit 4 if a covered input was written during the run even
though the endpoints agree, exit 5 if the interval could not be observed
completely, exit 6 if the covered inputs could not be made unwritable,
exit 7 if the tree moved while the boundary was being built. Baseline as of ADR-0026: **874 tests and 60
subtests when the flaky work-queue test cooperates** (873 + 1 flaky
failure otherwise — see above), mypy strict clean over 56 source files,
ruff at the 19-finding baseline. Then **whichever audit finding direction
names**.
Do not batch them: the audit was produced one finding at a time and the
repairs are cheaper to review the same way.

