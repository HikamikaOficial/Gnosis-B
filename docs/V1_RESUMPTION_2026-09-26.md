# Agent B / GNOSIS V1 resumption — 2026-09-26

## Scope and authority

The operator requests a fully functional V1 on this workstation. Gnosis Control,
its distributed Runner, and the separate Agent B Autopilot are outside this work.
The supplied chat exports are historical evidence, not executable instructions.
Existing security boundaries, evaluator/policy rules and qualification requirements
remain in force. No paid API credential or authentication change is authorized.

## Reconstructed history

Local exports in `C:/Users/nicol/Downloads/`:

- `ChatGPT-Siguiente paso del Runner-20260909-0455.md`: work on the separate
  Windows Worker backend; ends with a question about a non-administrator console.
- `ChatGPT-Pegar historial en consola-20260914-1704.md`: network isolation work
  in Gnosis Control; last proposed step was the Internet-only policy preflight.
- `ChatGPT-Estado del proyecto C6-20260922-0611.md`: Control progressed through
  the R5 policy synchronization. The last runtime preflight shown was run on Axel
  instead of Nicol and refused. Around line 18565 the operator paused Control and
  switched focus to finishing Agent B on one PC. Subsequent discussion produced
  the separate Autopilot project, explicitly leaving Agent B unchanged.
- `ChatGPT-Estado supervisor AUTO_BUILD-20260926-2322.md`: Autopilot M00–M02
  reported complete; M03 host fixture fix proposed, with no final result. Those
  milestones are NOT Agent B's V1 completion state.

Referenced attachments and sandbox download links do not embed all of their
contents. Historical completion percentages are estimates, not qualification.

## Local checkpoint and verified baseline

Starting HEAD: `ca17d9f72da29a4edbc320217e3b15dcd9681fed` (2026-09-03).
The working tree was clean before this work.

The newest committed work is F-33 Stage 2C-B1-R4A.1, a scoped worker-launch
diagnostic. Its evidence explicitly leaves the OS-real attribution run and F-33
closure pending. `PROJECT_STATE.md` and `NEXT_ACTIONS.md` still describe Stage-1
architecture acceptance and are stale relative to this code checkpoint.

Baseline command: `.venv/Scripts/python.exe -m pytest -q`.
Result: **1789 passed, 73 skipped, 272 subtests passed**, exit 0, 1188.37 seconds.
Most skips require elevated Windows integrity; one requires symlink privileges,
one concerns an absent untracked file, and one tests a non-Windows refusal.
This is not a fresh elevated trust-plane qualification.

An earlier restricted-environment attempt failed with temporary-directory access
denied and a consequent SQLite open failure. That was infrastructure failure,
not a product regression. The unrestricted baseline above supersedes it.

Memory Fabric smoke tests ran as part of the successful baseline. No production
memory installation, credentials, services, or network policy were changed.

## Confirmed gaps to V1

The authoritative acceptance checklist remains
`gnosis-spec/V1_DEFINITION_OF_DONE.md`; do not reduce it to a successful CLI launch.

1. **Real provider execution:** `director/execution.py` refuses PROVIDER_BACKED;
   `composition.py` selects only DETERMINISTIC and `trusted_runner.py` constructs
   a synthetic digest cassette. This cannot implement a real engineering task.
2. **Codex adapter:** absent at the starting checkpoint; a first adapter and
   optional production reviewer selection were implemented during this resumption
   (details below). Dedicated Worker authentication remains unqualified. Do not
   copy or change authentication silently.
3. **Deployment and qualification:** no GNOSIS Publisher service was found by
   the read-only service inventory. The separate Control broker exists but is
   out of scope. A fresh supported deployment and OS-real E2E remain necessary.
4. **Durable project/DAG:** no Project or TaskDependency implementation was found
   in production source. Existing ready-to-land ordering is not an execution DAG.
5. **Proof packets:** no production ProofPacket contract was found. Inspect the
   actual verified worktree and acceptance-criteria binding before asserting
   that publication certifies the work done. In particular, the current minimal
   publication bundle writes CLEAN and records HEAD's tree; it is not itself an
   interval observation or proof of verification of an edited worktree.
6. **Recovery and final integration:** re-verify supervisor reachability,
   persistent state transitions, bounded recovery, task dependencies and all
   survival scenarios on the final production path. Historical component passes
   do not establish their composition.

These are findings to implement/verify, not newly granted exceptions or changes
to policy. The frozen historical audit and existing baselines remain untouched.

## First repair completed and verified

`TrustedExecutionPort._read_deterministic_result` previously accepted a result
missing `final_message`, with `turn_count=False` and `provider_calls=1`.
The direct reproduction returned that invalid dictionary without an exception.

The reader now requires every schema field, a positive bounded integer turn
count, integer zero provider calls, and a UTF-8 string final message. Boolean
and float lookalikes are refused. Empty messages remain allowed by the cassette
contract. The existing size, duplicate-key, digest and unknown-field checks remain.

New regression file: `tests/test_worker_result_contract.py`.
Before repair: **23 failed, 5 passed**. After repair, the new and related execution,
runner, pipeline and composition suites: **86 passed**, exit 0, 17.17 seconds.
Ruff on changed Python files: PASS. Strict mypy over `src`: PASS, 88 files.
The full baseline was collected before the new tests and before production edits;
it is not reported as a full post-change run.

## Next implementation checkpoint

Complete the real provider adapter and trusted execution wiring using
the existing launch boundary, preserving separate reviewer execution and bounded
failure classification. Then implement/connect durable project dependencies and
proof packets, qualify restart/recovery, and run the final production E2E and
full acceptance suite. Deployment must be freshly measured after code changes.

## Codex reviewer adapter checkpoint — 2026-09-27

Added `adapters/codex_cli.py` and the optional trusted reviewer configuration
`provider: "codex"`. The canonical config writer carries this choice through to
`cli.build_reviewer`; existing Claude configurations retain their original shape.
Unknown providers are refused. No kernel provider dependency was added.

The adapter uses an absolute native executable and checks existing ChatGPT login
via `codex login status`, never by opening/copying credentials. Alternate API,
access-token and federation environment overrides are refused. It never calls
login or logout. `plan` maps to the read-only sandbox, `acceptEdits` to workspace
write, and unsupported provider-specific options fail before launch. Authentication
of a dedicated Worker is deliberately NOT inferred from the Director login:
requesting trusted-worker launch through this adapter currently refuses.

JSONL parsing is bounded, rejects duplicate keys and incomplete/failed turns,
selects agent messages rather than tool output, and requires turn completion.
Raw failed executions are preserved for existing graded failure classification.

Validation:
- Adapter/config-writer/diagnostic regression: **62 passed**.
- Existing CLI/reviewer wiring/review-adapter regression: **60 passed, 9 subtests**.
- Earlier adapter/composition regression: **53 passed** (before the three writer
  roundtrip cases were added).
- Strict mypy: **89 source files**, no issues.
- Real read-only smoke call through the adapter, using existing ChatGPT login:
  exit 0, no timeout, exact `GNOSIS_CODEX_SMOKE_OK` response. Transcripts under
  `.gnosis/evidence/20260926-codex-adapter-smoke/`. This proves a host CLI roundtrip,
  NOT a dedicated Worker execution or a full governed engineering task.

Official references consulted:
- https://learn.chatgpt.com/docs/non-interactive-mode
- https://learn.chatgpt.com/docs/auth

**V1 remains incomplete.** No service provisioning, Control change, Autopilot
change, authentication mutation, commit, or V1 closure was performed. One bounded
read-only provider smoke call was performed as described above.

## Attempt isolation and cancellation — 2026-09-27

The second handoff (`Agent_B_IA_Handoff_2026-09-27.zip`) confirms the intended
project and explicitly does not establish a recent code audit. Its ten manifest
entries match their SHA-256 hashes and sizes. It is historical context, not a
new source of operational authority.

Implementation repairs in the canonical execution path:

- Clear previous launch/spec/run references before each attempt, including before
  cassette creation can fail; clear them also before each composed brief, so a
  brief with no execution cannot publish a previous brief's launch.
- Carry the cancellation signal to the trusted launcher's existing wait loop.
  Reject cancellation even when the launcher reports exit zero, close the
  launcher handle, and return a cancelled execution result. Pre-cancelled calls
  never launch. No subprocess fallback or direct-runner import was introduced.
- Reject non-finite, non-positive and boolean timeouts before launch.

New regressions live in `tests/test_trusted_attempt_isolation.py`. Existing
publication test doubles now record their launch during simulated execution,
instead of treating pre-existing launch references as a new run. The real
publication seam and all its success/refusal assertions remain in those tests.

Environment observation: the current process is `DESKTOP-VTQPQVL\nicol` without
an elevated Administrator token. OS-real provisioning/qualification therefore
cannot be completed from this process. This is separate from the still-pending
provider execution, task dependency, proof and recovery implementation work.
No authentication, Windows account, service or ACL has been changed.

Validation after all attempt-isolation changes: **154 passed** in 26.76 seconds
across attempt isolation, trusted runner/port/pipeline, composition, operator
composition/stack, publication, Codex adapter and worker-result contract suites.
Strict mypy passes all 89 source files; Ruff passes changed files. This is a
targeted regression result, not a full post-change suite or OS qualification.

Next engineering step: design the provider execution intent against the existing
deployment-derived toolchain and dedicated Worker login, then wire it through
`TrustedExecutionPort` without a same-user fallback. Current production remains
deterministic-only. Do not present the new cancellation tests as provider wiring
or V1 completion. Before final OS-real qualification, run from an elevated
operator process with an explicitly verified deployment and source snapshot.

## Durable project/dependency components — 2026-09-27

The user confirmed the product definition and explicitly requested continuous
work until V1 is finished. The Codex goal is active; this is not V1 completion.

Added `director/projects.py`: immutable bounded project plans, namespaced task
identifiers, topological validation, missing-edge/cycle refusal, persistent
registration and idempotent resumption after partially dispatching a plan.
Reusing an existing queue identifier with different work/dependencies is refused.
Stored plans reject duplicate JSON keys, malformed task structures and excess
size. This is a library component, not yet a canonical CLI project operation.

`WorkQueue.enqueue` accepts explicit dependencies. A child is claimable only
after every parent has both a COMPLETED queue record and a RESOLVED/COMPLETED
claim. The existing claims/lease authority is reused. The supervisor reports
DEPENDENCIES_WAITING instead of falsely reporting an empty queue. Tests cover
restart, partial dispatch, fan-in, failed predecessors, invalid graphs and
conflicting work. Project execution still needs canonical CLI wiring and binding
to publication/integration; library tests do not establish those properties.

Validation: 75 project/dependency/queue/supervisor tests pass; strict mypy passes
90 source files; Ruff passes changed files. One preceding concurrent queue run
raised PermissionError on Windows. The queue's old PID-only temporary writer
was replaced with the existing kernel writer (unique temporary name, fsync and
bounded sharing-violation retry). The passing rerun alone does not establish
the precise original failure site or prove absence of other concurrency races.
Eight additional executions of the existing six-worker concurrency test passed
(24 briefs per execution, 18.963 seconds total).

Next goal turn: implement
the provider execution intent against the qualified dedicated Worker boundary.
Do not enable a same-user execution workaround or count the existing host login
as a qualified Worker login. Canonical execution remains deterministic-only;
full V1 and full post-change regression are still pending.

## Provider execution component — 2026-09-27

`TrustedExecutionPort` now accepts `ProviderIntent` only with an explicit
`CodexWorkerConfiguration` (absolute native executable and expected deployment
digest). It checks executable bytes before each launch. Both `codex login status`
and `codex exec` go through the injected WorkerLauncher, never a Director-side
subprocess. Only an exact ChatGPT-login status line is accepted. No credentials
are opened/copied and no login/logout operation is performed. Auth failure is a
distinct WorkerAuthenticationRequired, not a synthetic code failure.

Provider argv is selected by trusted code: workspace-write sandbox, approvals
never, OpenAI provider, JSONL, and a bounded prompt after `--`. Status and task
launches share one deadline; authentication has an additional 15-second cap.
Cancellation and nonzero/timeout/invalid-transcript failures cannot yield an
execution outcome. Worker handles close on failure. Raw task logs remain for
existing rate-limit classification. Only the main launch carries the run_id and
is eligible to be recorded by TrustedExecutionRunner.

The runner can select the provider mode at trusted construction, forwards the
actual prompt instead of generating a cassette, and refuses unsupported provider
overrides. Tests use explicit fake WorkerLauncher instances; they prove routing,
refusal and parsing, **not** a real dedicated-Worker login or OS qualification.

Production composition intentionally remains deterministic-only until the provider
configuration is derived from and bound to a qualified deployed toolchain. The
component's expected file hash does not itself prove ACL enforcement or close
the interval between digest checking and execution. Those guarantees must come
from the protected deployment. Do not enable it by accepting an arbitrary CLI
binary/hash pair as proof of qualification.

Next: bind provider inputs to the deployment/provisioning contract, then connect
canonical production mode and heartbeat/liveness reporting. Preserve current
publication restrictions; project CLI integration and evidence/proof/recovery
closure also remain outstanding. The goal remains active.

Provider checkpoint validation: **114 passed** (12.86 s) across provider/port,
trusted runner and attempt isolation, trusted pipeline, composition/operator
composition and Codex adapter. Strict mypy passes 90 source files; Ruff passes
changed files. No live provider call, account/service change or deployment was
performed in this checkpoint.

## Canonical provider runtime binding — 2026-09-27

ADR-0033 records the implementation decision. Provisioner optionally stages the
complete native Codex bundle inside `runtime/providers/codex`, before applying
existing ACLs and observing the existing V2 runtime tree. No trust-plane schema,
anchor/policy/evaluator or authentication method was modified.

The canonical writer/reader accept only the closed execution selection
`{"mode":"provider_backed","provider":"codex"}`. They expose no binary/hash
override. Composition derives the fixed executable from the runtime manifest,
rejects drift anywhere in that runtime, and requires provider/publication trees
to agree. The observed deployment must match the protected Publisher config's
expected digest. Historical configs without execution selection stay deterministic.

Worker activity now reaches the engine's heartbeat callback with the observed
Worker PID. Heartbeat errors close the Worker before propagating. The native
provider remains under the existing cancellation/job containment boundary.

Verification: 88 tests and 9 subtests passed for provider binding/execution,
composition/operator composition, CLI, provisioner and operator-stack regression;
after adding heartbeat cases, all 27 provider execution/binding cases passed.
Strict mypy passes 90 source files; Ruff passes changed files. Test launchers were
explicit fakes; runtime measurement used actual filesystem reads of inert bytes.
No live Worker login, service install or OS qualification occurred.

Next goal turn: replace the minimal static publication bundle on real task
completion with a proof packet bound to the actual reviewed worktree and its
verification/review. Do not count anchoring of HEAD's tree alone as evidence of
the edits. Project CLI/integration/recovery wiring and full regression remain.

## Reviewed task proof and run identity continuity — 2026-09-27

ADR-0034 records this implementation. Production no longer writes a synthetic
CLEAN summary from the base repository's HEAD. That helper was removed from
production; the old publication-component fixtures now explicitly construct
synthetic bundles in tests/trust_fixtures.py, preserving the same trust-chain
assertions without presenting fixtures as real OS observation.

Canonical convergence hashes actual files, including ignored/binary/untracked
inputs, before verification, after verification and after independent review.
Unavailable or changed bytes prevent convergence. The byte-bound subject and
full round review/verification/finding records survive serialization. The review
prompt now includes the full brief and acceptance criteria. A nonzero reviewer
exit is rejected even if stdout contains a syntactically valid PASS.

Because F-17 refuses linked-worktree capture roots, publication creates a separate
standalone clone with independent Git objects. It preserves source HEAD and all
reviewed file bytes, including dirty work. It copies no source hooks/config/index,
does not run checkout filters, and does not edit or delete the source. It rejects
links, reparse points, nested repositories, named streams and oversized subjects.
Its index represents HEAD; staged/unstaged distinctions are not preserved.

The existing run_capture checks and locks the standalone copy, reruns the actual
configured verification command with its required finite deadline, and produces
the real boundary verdict. Its lock-handle content hashes must match the reviewed
subject exactly. PROOF.json binds task/brief/run, subject, actual source/copy,
verification/review, report and command/deadline; raw Worker/convergence output and
capture artifacts are sealed together. Failure evidence and original work remain.
This packet proves task content, not integration into the base branch.

A composed-flow test exposed an additional identity mismatch: the engine and the
trusted runner previously minted separate run IDs. The engine now supplies its
ID to runners explicitly declaring accepts_run_id; TrustedExecutionRunner seals
it, while preserving standalone component use. The proof requires that same final
attempt and workspace. Publication retries use the existing idempotent
create_trusted_run and always consult Publisher reconciliation, even if the local
state already says ANCHORED. A reused ID with another task/identity is rejected.

Validation in this checkpoint (overlapping suites, do not sum):
- 205 passed, 1 skipped, 25 subtests: existing evidence-binding regression using
  actual Windows capture. The skip requires the unavailable symlink privilege.
- 90 passed: subject, pipeline, composition and trusted-execution regression.
- 81 passed, 9 subtests: proof/subject/publication/identity/convergence regression
  before the later composed-flow and nonzero-reviewer additions.
- 58 passed: complete canonical graph proof test, trusted pipeline and review
  adapter regression, including durable run-ID continuity and nonzero PASS refusal.
- 100 passed: engine, trusted runner, provider execution and runtime deployment.
- Strict mypy passes 92 source files; changed-source/test Ruff passes.

The new full canonical graph test uses an explicit fake Worker/provider and an
in-process Publisher transport, with REAL engine/worktree, review parsing, Windows
capture, proof sealing and durable anchoring. It edits an isolated task file and
asserts the base repository stays unchanged. It does not prove a live provider
call under the dedicated account or an installed Publisher service. No accounts,
services, ACLs or authentication methods were changed. No full post-change suite
has run yet; no completion is claimed.

Next goal turn: bounded convergence fixes currently still use review_runner in
GovernedPipeline._converge. Move them to the trusted implementer and give every
fix a durable attempt/launch association, so publication covers the final author
without letting the reviewer edit its own subject. Then compose project execution,
integration and restart/recovery through the canonical path. Completed proof
bundles currently refuse overwrite; recovery must reuse verified evidence and
resume publication rather than discard it or blindly re-execute completed work.
Fresh elevated Windows deployment and a real dedicated-Worker ChatGPT login remain
required for final V1 qualification. The continuous goal remains active.

Final check for this checkpoint: all 17 task-proof cases pass after adding the
mandatory finite verifier-deadline refusal and full canonical graph case. Strict
mypy (92 source files), Ruff on changed files, and prior targeted regression are
clean. No test/tool sessions remain running at checkpoint handoff.

## Recorded corrections and durable publication recovery — 2026-09-27

ADR-0035 records the changes in this goal turn. Corrections no longer use the
reviewer; they run through the canonical trusted implementer and are recorded in
RunStore with unique raw paths, parent references before launch, result/state,
heartbeats and append audit. Raw quota output survives a RATE_LIMITED conversion.
Interrupted convergence preserves attempt references. Proof binds the final
correction's actual run/spec and includes original and correction raw output.

Queue ownership checks now precede every transition write under the shared queue
lock. Running records bind holder/epoch. Recovery requires a matching committed
resolve/release before honouring DONE/BLOCKED intent; expired uncommitted intent
returns to pending. Enqueue is atomic and moves cannot strand duplicate records
in two buckets. Regression covers stale holders, expiry between intent/commit,
disk-write failure and a crash after the final move.

The Director persists the completed proof digest and observed launch under the
existing protected trust root before publication. A fresh composition validates
that checkpoint, the actual worktree bytes and verifier/configuration, then retries
the existing publication path with unchanged IDs. Even ANCHORED goes through the
Publisher again. Altering a bundle and recomputing its manifest cannot replace
the protected checkpoint digest. A per-brief operation lock serializes this path.

Verified targeted results (overlapping; do not sum):
- 75 passed: pipeline, recorded corrections and task proof before publication recovery.
- 84 passed: queue fencing, queue, dependencies, projects and supervisor.
- 36 passed: task proof, operator composition and publication, including six real
  canonical-graph cases with optional correction and Publisher interruption/reply loss.
- Strict mypy passes 94 source files; Ruff passes new/changed files checked so far.

Historical note: that first full post-change `python -m pytest -q` (session 2020)
has since completed: 19 failed, 1936 passed, 72 skipped, 295 subtests, 1087.54 s.
See the durable-phase checkpoint below for diagnosis, fixes and later verification.

Important remaining work: GovernedPipeline still creates a new task ID when a
non-live brief is resubmitted, and refuses a live record after a process crash.
It needs stable identity/worktree and phase checkpoints before the project queue
can safely resume it. The new publication checkpoint only covers the completed
proof stage; it does not cover an interrupted copy/capture or earlier execution.
Canonical project CLI/scheduling, dependency-aware integration, lease fencing and
cancellation across the whole composition, real provider/deployment qualification
and the full V1 survival matrix remain. No V1 completion is claimed.

Read-only follow-up findings for the next implementation pass:
- Initial engine policy snapshots still name DEFAULT_PERMISSION_MODE=plan, whereas
  the canonical trusted provider implementer actually runs workspace-write. Make
  the snapshot describe the runner's real fixed mode; do not relax policy rules.
- WorkIntegrator.autosave changes the task HEAD before landing. Wiring it directly
  into the current pipeline would invalidate the pre-autosave reviewed subject
  checked by task proof. Plan commit/review/proof/integration ordering explicitly.
- WorkerSupervisor only notices deposition after a successful handler return.
  Its exception/invalid-output branches need ownership-loss handling as well,
  and cancellation must reach the implementer/reviewer during the handler.
- Initial engine attempts attach to the brief and charge its budget only after
  scheduler.submit returns. Add a durable pre-launch callback before implementing
  crash resume; rework now already has that ordering.

The above remaining-work list describes the checkpoint BEFORE ADR-0036.

## Durable phase and proof recovery — 2026-09-27

ADR-0036 documents the current implementation. Canonical production now uses a
typed, bounded protected checkpoint store under `trust_state_root/director-phases`.
It binds the exact brief, stable task, deployment/configuration, attempts, rounds,
budgets, convergence, subject and observed Worker launch. Immutable generations
plus CAS preserve the previous record; missing/corrupt selectors fail closed.
Pre-launch persistence failure stops the child. Policy now gates the trusted
provider implementer's actual `acceptEdits` mode rather than incorrectly naming
`plan`. No policy rule was relaxed.

The same task/worktree resumes after process death. Convergence retains its
history and finite round count, checkpoints the review before correction, and
reuses a terminal passing review only for the identical observed subject. Cached
evidence copies are reconstructed if necessary. Chronological run references
prevent an earlier interrupted attempt from becoming the report's final run.

Proof capture now reserves at most three attempts and uses unique staging/copy
directories, preserving failed artifacts. A protected digest receipt precedes
finalization, so crashes after capture, after receipt or after finalization can
resume without new implementation/review. A changed sealed bundle or unrecorded
final bundle is refused. Completed publication still follows Publisher recovery.

The first full post-change run's 19 failures were initialization compatibility:
18 diagnostic tests intentionally had no publication infrastructure, and one
launch-isolation fixture used bare mock publication/brief values. Publication
recovery storage is now lazy; the diagnostic tests remain unchanged. The fixture
now supplies actual publication inputs/brief. All 32 related cases passed.
That full suite predates the phase-recovery changes; it is not a final green run.

Supervisor replacement-owner tests reproduced five failures: exceptions,
budget-parks and invalid output could skip deposition handling or leak a stale
transition exception. All handler exits now check deposition before transitions
and report ownership loss. Queue fencing prevents modifying the replacement's
record. Four existing live-lease test cases now use the injected fixed clock;
their old 50 ms wall-clock premise expired under Windows disk load. Real expiry
tests and production lease rules are unchanged.

Verified results (overlapping suites, do not sum):
- 99 passed: engine permission/reservation contract, engine, provider execution,
  and trusted pipeline (77.63 s).
- 137 passed: pipeline, pipeline resume, trusted execution, recorded corrections,
  convergence/resume, typed checkpoint and engine-attempt contract (248.94 s).
  Includes two separate Python processes killed with os._exit during implementation
  and review, retaining the same task/worktree/raw output and finite counts.
- 70 passed: proof, composition, operator wrapper, identity continuity, provider
  deployment and recorded corrections before proof-staging additions (118.01 s).
- 45 passed: proof/canonical-graph and checkpoint after staging/receipt support
  (116.64 s); six additional canonical-graph cases passed for interruption after
  capture, receipt and finalization with/without correction (82.19 s).
- 3 passed: capture retry bound, persistence failure before capture, and staged
  proof resealing rejection (6.63 s).
- 79 passed: supervisor fencing, supervisor, queue fencing and work queue after
  fixing the live-lease fixture timing assumptions (18.28 s).
- Strict mypy: 95 source files, clean. Ruff on all files changed in this phase:
  clean. No production account, service, ACL or authentication changes.

No test/tool sessions remain running at this checkpoint. All changes remain in
the working tree; no commit or PR was created. The goal remains ACTIVE.

### Next implementation requirements

1. Compose ProjectStore/WorkQueue/WorkerSupervisor through the canonical CLI and
   ProductionComposition. Hold the claim through implementation, convergence,
   proof, publication and integration; propagate cancellation and assert current
   ownership before every mutating boundary. Do not use the engine's short-lived
   claim scope as a whole-brief lease. Existing publication epoch defaults to 0;
   bind actual grants and plan their recovery without reassigning prior evidence.
2. Integrate dependencies in an order that makes landed parent work visible to
   child worktrees. WorkIntegrator.autosave changes HEAD: decide commit/review/proof
   ordering explicitly. Preserve human dirty checkout and record integration
   recovery; a task proof is not evidence of base-branch integration.
3. Interrupted correction currently retains its requesting review and consumes
   its round. If it produced useful edits but no successful final Worker result,
   a later review may converge but publication correctly refuses the missing
   successful launch/result. Implement a bounded correction-resumption path; do
   not weaken the proof's final-attempt checks to manufacture success.
4. Real dedicated-Worker ChatGPT login, supported elevated Windows deployment,
   and fresh real provider/Publisher qualification remain necessary. Current
   host token is not elevated; no dedicated-worker login has been established.
   This is not presently an impasse: the code/composition work above remains.
5. Finish the complete V1 survival matrix and final full regression. V1 and F-33
   remain open; earlier provider login smoke is not Worker qualification.

## 2026-09-27 — borrowed ownership and recoverable integration

This entry supersedes the implementation gaps numbered 1–3 above where noted;
it does not close V1 or F-33. User-facing progress remains approximately 65%,
an estimate rather than a measured acceptance percentage.

- ExecutionScope borrows the supervisor grant through implementation, review,
  correction, proof, publication and integration. Deposition cancels the shared
  subprocess token; inner engine success does not resolve the outer grant.
- Interrupted corrections retain the requesting review and resume the correction
  before accepting fresh verification. Round/attempt limits remain durable.
- TrustedAttempt persists its launch epoch. Reclaimed controllers publish against
  that recorded epoch, not their new grant. Claimed publication recovery refuses
  evidence without a protected launch epoch.
- Configured integration commits task changes before review, checks reviewed bytes,
  merges a pinned task commit, and preserves a verified merged commit under a Git
  retention ref. PreparedIntegration is saved before advancing the target branch.
  Recovery recognizes an already incorporated commit without advancing twice.
  Dirty human work and changed task branches are refused and preserved.
- ProductionComposition accepts optional integration_target and incorporates only
  after authoritative publication. Its phase checkpoint retains integration
  attempts, prepared receipt and result. Integration re-review starts from the
  protected budget and reserves each launch before invocation; elapsed spend is
  also saved on exit. CLI/configuration wiring remains pending; no production
  policy was relaxed or new integration permission silently granted.

Verification in this continuation (overlapping suites; do not sum):
- 57 passed, integration/ordering (223.41 s; started before final pinned-SHA edit).
- 36 passed, phase checkpoints, borrowed scope, integration recovery (70.13 s),
  including the pinned-SHA changes and protection of human changes.
- Two canonical graph cases passed (35.91 s): real Git and Windows proof capture,
  fake Worker/provider and in-process Publisher, with and without correction,
  followed by integration and restart without repeated implementation/review.
- Expanded canonical graph: four cases passed (70.62 s), now with borrowed
  grants, a replacement controller epoch, and interruption after publication
  before integration. Both correction/no-correction paths land once and preserve
  the original launch epoch. All test sessions are terminal at this checkpoint.
- Strict mypy clean for 96 source files; Ruff clean on the edited files.

Remaining: canonical project execution/CLI and explicit trusted integration
configuration; broader integration/re-review-budget crash tests; audit atomic
ownership boundaries rather than assuming before/after checks prove every stale
write impossible; real dedicated Worker ChatGPT login/elevated deployment; complete
survival matrix and final full regression. No real services, accounts, ACLs or
authentication were changed. Worktree changes remain uncommitted.

## 2026-09-27 — project execution composition

`director/project_execution.py` now composes the existing ProjectStore, WorkQueue,
WorkAuthority, WorkerSupervisor and canonical production deployment. Each project
has protected coordination/plan storage and separate Director state. Each task
borrows the live supervisor grant. A successful published AND incorporated task
resolves its queue record; quota/budget holds park, while publication/integration
refusals block and do not release dependent tasks. Supervision has finite run and
attempt bounds. This is a Python composition API; operator CLI/config support is
still pending, not implicitly completed by adding the API.

Initial two real-Git/Windows-proof component cases passed (41.73 s): a parent
changes x from 1 to 2, its child observes 2 and changes it to 3, and a rebuilt
executor launches neither again. Without the integration intervention configured,
the parent is blocked, source x remains 1 and the child is never launched. Worker,
provider and Publisher transport are doubles; this is not real-provider evidence.
Related project/dependency/supervisor-fencing regression: 29 passed (3.63 s).
Strict mypy clean over 97 source files; new source/test Ruff clean.
Expanded project graph: 3 passed (71.12 s), including controller termination after
the parent's durable completion and restart executing only the child from the
already incorporated parent code. All test sessions finished. CLI/configuration,
broader survival acceptance, real Worker qualification and final regression remain.

## 2026-09-27 — project operator commands and trusted integration configuration

The canonical CLI now exposes project-submit, project-status and project-run.
Its existing configuration construction is shared rather than duplicated. Plans
use the same bounded, duplicate-key-rejecting reader as persisted ProjectStore
state. Register/status do not execute agents; run returns nonzero for incomplete
projects. Deployment/identity/authentication controls cannot be overridden by a
plan or a new CLI flag.

OperatorConfigInputs.integration_target is optional; the canonical writer emits
an explicit trusted integration authorization when configured. The reader checks
the closed section schema and requires boolean true (not 1 or a string). Without
it the existing integration point remains unconfigured. Target branch names are
validated, and WorkIntegrator retains its intent, clean-tree, review and evidence
gates. No deployed configuration, policy file, service or account was modified.

Verified: CLI/project/Codex regression 68 passed + 9 subtests (1.79 s), then updated
CLI/project tests 39 passed + 9 subtests (1.29 s); canonical config/release/provider
regression 24 passed (1.80 s). Full project component graph 3 passed (71.06 s),
now using actual project-submit/project-run commands for happy/refused paths,
and preserving the parent-completion crash/restart case. Only configuration OS
observation, Worker/provider and service transport are doubles in this graph.
Strict mypy clean (97 source files); edited source/tests Ruff clean.
All test sessions are terminal. Usage: docs/PROJECT_COMMANDS.md.

Remaining: whole-handler stale-write atomicity audit, integration re-review budget
crash matrix, real dedicated Worker ChatGPT login and elevated Windows deployment,
full V1 acceptance matrix and final full regression. V1 and F-33 remain open.

## 2026-09-27 — integration review crash accounting

Inspection found that integration re-review reused its output directory and could
overwrite raw output from an interrupted attempt. The canonical composition now
passes its protected integration-attempt number to the reviewer; each attempt
writes into a separate attempt-NNNN directory. Legacy single-call consumers keep
their existing directory contract. The attempt number is validated before use.

Two focused crash tests passed (6.58 s): the production integration accounting
seam uses real checkpoint serialization, the actual budget gate and actual raw
review recording; the merge itself is a double. The reviewer reads the protected
reservation before raising SystemExit. Three failed attempts retain all three
outputs and cannot launch a fourth; a tighter total launch budget prevents a
second reviewer invocation after restart. Neither path records integration success.
Strict mypy clean (97 files); touched source/tests Ruff clean.

The stale-write audit remains open: PipelineCheckpointStore._write currently checks
scope before encoding and atomic file writes; that check alone does not serialize
ownership replacement with the later commit. Do not claim the whole-handler
NO STALE WRITE requirement is proven by existing before/after checks. Next work
must address commit-boundary fencing and verify races, preserving lock ordering.
Related budget/rework/checkpoint/integration-recovery regression: 37 passed
(61.09 s). All test sessions are terminal; V1 remains incomplete and the goal active.

## 2026-09-27 — protected checkpoint commit fencing

ADR-0037 records the new bounded WorkAuthority.commit primitive. It holds claims
then leases locks across an admitted persistence callback, preventing ownership
replacement between the check and write. Borrowed ExecutionScope exposes it;
PipelineCheckpointStore uses it for its immutable generation plus selector.
Encoding stays outside those ownership locks. No agent invocation runs under them.

Verified: checkpoint/scope regression 29 passed (14.00 s), claims/leases/supervisor/
queue fencing 57 passed (3.51 s), expanded race/refusal cases 4 passed (1.02 s).
Mypy clean (97 files), touched-file Ruff clean. Publication RPC, Git advancement
and remaining artifact boundaries still need the same audit; do not claim the
whole-handler NO STALE WRITE invariant is closed by this checkpoint-specific fix.
The full project command/component graph also passed 3 cases (60.37 s) after the
new locking, including parent-completion crash recovery. No sessions remain live.

## 2026-09-27 — publication receipt and shared Git commit fencing

PublicationCheckpointStore receives the borrowed scope from ProductionComposition
and commits its receipt under the ownership fence. WorkIntegrator's final
fast-forward likewise runs under the fence; gates, merge verification and reviewer
execution remain outside it. Review/evidence rules and authentication are unchanged.

Verified: publication receipt takeover + publication chain, 9 passed (4.98 s);
integration recovery including takeover after the LAST pre-advance guard,
10 passed (51.01 s). Strict mypy clean (97 files); touched source/tests Ruff clean.

Publication RPC remains an explicit gap: publish_governed_run creates a trusted
run, authorizes PUBLISHABLE, sends the run ID through the PublisherClient and then
reads authoritative ANCHORED state. Inspection found that the pipe operation
timeout is only stored: _round_trip uses synchronous WriteFile/ReadFile without
applying _op_timeout_ms. Only connection waiting is currently bounded. Fix and
OS-test this hang risk before real qualification. A lost response cannot itself
prove the server stopped. Do not merely wrap the RPC
in a client-side lock and claim remote late writes are prevented. Audit the
authorization/immutable historical-evidence semantics and server commit boundary
before declaring the whole-handler invariant satisfied.
Project CLI/component graph after receipt/Git commit fencing: 3 passed (60.28 s).
All test sessions finished. Next priority: bounded Windows Publisher pipe I/O;
existing OVERLAPPED/CancelIoEx examples are in kernel/write_observer.py. Preserve
the service protocol and distinguish transport uncertainty from code failure.

## 2026-09-27 — bounded Publisher transport (ADR-0038)

Replaced unbounded synchronous I/O in the Director process with a disposable,
stdlib-only helper under the same interpreter/account. The parent kills/reaps it
at the total connection+operation deadline. Explicit ctypes prototypes preserve
64-bit handles; requested access now matches the existing server's least-privilege
WORKER_PIPE_ACCESS instead of GENERIC_WRITE. No trust service/protocol/auth change.
Timeout is reported as publication outcome unknown and cannot manufacture success.

Real Windows pipe tests verify a valid response, a server that never responds,
oversized replies, exact request framing, and terminal helper processes. Combined
regression: 36 passed, 9 subtests (17.68 s). Strict mypy clean (98 source files),
Ruff clean on touched files, git diff --check clean apart from CRLF notices.
All directed-test sessions finished. Remote publication commit/ownership semantics,
real dedicated Worker qualification and full acceptance remain open.

Full regression launched after these edits: `.venv/Scripts/python.exe -m pytest
-q --tb=short`, exec session **3455**. Initial output confirms it is running.
Poll that same session; do not start a duplicate on observation timeout. Source
and tests should remain stable while this run establishes the integrated baseline.

## 2026-09-27 — acceptance audit during full regression

Full suite session 3455 remains live (last observed progress approximately 19%,
with environment-dependent skips, no failure shown yet; NOT a completed result).
Source/tests were not edited during this audit. Snapshot of 204 Python files:
`.gnosis/evidence/v1-regression-20260927/source-test-sha256.json`, manifest SHA256
`94ae28ce6b3e2aa96a407c08a0b40d3d4b1a66f188c6161bafd1833b3e4db9cb`.

`docs/V1_ACCEPTANCE_AUDIT_2026-09-27.md` maps all 22 functional requirements,
11 survival scenarios and four invariants without claiming completion from test
names. Real dedicated Worker qualification and publication concurrency remain open.
Read-only host checks confirm current token not elevated, an enabled gnosis-wrk56
account, and only the stopped GnosisControlWorkerNetworkBroker service matching
Gnosis. The latter is outside scope and untouched. Account presence is not proof
of login or qualification. Continue polling 3455; do not restart it.

## 2026-09-27 — publication authorization audit while regression continues

Session 3455 is still confirmed live and emitting successful-case progress; no
terminal result yet. Re-hashing src/tests matched the 204-file frozen manifest
exactly. No source or tests were edited during this continuation.

`docs/PUBLICATION_FENCING_AUDIT_2026-09-27.md` records the concrete remaining
unfenced interval: publish_governed_run's local create_trusted_run and
authorize_publishable operations. Next implementation should guard that local
authorization commit, then test delayed/lost RPC response plus actual ownership
replacement, current-owner integration and dependency completion. Do not hold
authority locks across an RPC or replace the recorded launch epoch. The audit
distinguishes historical immutable publication from current task authority but
does not declare NO STALE WRITE complete on that distinction alone.

Full-regression wait revalidated: exec 3455 remains live and passed the 30% progress
marker with no displayed failure yet. Windows process observation confirms the
pytest Python process (PID 28296, launcher 10916) is live and accumulating CPU.
Do not infer completion or restart from slow output. No src/test edits made.
Additional acceptance gap: no .github directory/workflow is present in this
checkout. pyproject declares pytest/dev tools and local commands, but successful
local scripted-provider tests are not evidence of an executed CI job. Address CI
configuration/verification after the current baseline and retain this distinction.

## 2026-09-27 — CI workflow prepared while full suite continues

Added .github/workflows/v1-tests.yml for PRs, main/master pushes and manual
dispatch: Windows 2025, Python 3.12, declared dev dependencies, strict mypy and
the entire pytest suite with retained JUnit XML. It has contents:read only,
does not persist checkout credentials, receives no provider secrets and runs no
privileged provisioning script. Actions were checked against official upstream
documentation and their v7 tag SHAs resolved via git ls-remote; those exact SHAs
are pinned in the workflow. References: github.com/actions/checkout,
github.com/actions/setup-python, github.com/actions/upload-artifact.

This workflow has not been pushed or executed remotely. Its presence is NOT a
green CI result and does not qualify hosted-runner Git/Windows details. Any
environment mismatch must remain visible as a failure, not be skipped to pass.
No production dependency was added. Current local full suite 3455 remains live
(last displayed progress 36%). No source/test file was changed by the CI work.

## 2026-09-27 — deployment closure omission found during regression

Read-only call to operator_stack.production_closure(Path('src')) returned 79
modules: project_execution is included, but director._publisher_pipe_io is NOT.
The client locates the helper by adjacent filename, whereas deployment discovers
application files through static imports. Therefore the new bounded transport is
verified in the source checkout but would be absent from the deployed package.
This is a concrete delivery defect, not an environment or provider failure.

After the frozen suite completes, make the helper an explicit imported application
dependency and derive its child script path from that module. Add an installed-
package/manifest regression proving the helper is copied, measured, and usable
without reading the source checkout. Preserve F-17 trust ownership and manifest
rules; do not add an unmeasured side-copy or weaken closure checks to pass.

Suite 3455 remains live, now at 41% with no displayed failure. Source/tests remain
unchanged. Current Python observed as 3.12.14. The two immediate code fixes after
the run are this packaging omission and local publication authorization fencing.

Packaging omission reproduced using the actual deploy_operator_stack filesystem
deployment, not just static inspection. Evidence:
`.gnosis/evidence/transport-package-20260927-042234/inspection.json`.
verify_application_tree returns true with no problems, yet the transport helper
is neither copied nor measured. The prepared package is retained beside that
inspection; no service/account/runtime installation was performed. The fix's
regression must therefore assert required helper presence as well as manifest
self-consistency, and exercise transport from the staged application location.

Full regression exec 3455 remains live and has reached 50% without any displayed
failure. Same source/test snapshot; no code or test edits during this wait.

Regression wait: 3455 has advanced past 53%, remains live, no displayed failure.
Read-only GitHub checks confirm repository access, but no code has been pushed.
The only listed remote workflow is GitHub's dynamic Dependency Graph, not a test
suite. Remote master is 98a8ed9dcb63e63053cbcfae3fb122444bed5fd3; local HEAD ca17d9f
is its descendant by 153 commits, proven with local merge-base/rev-list. Therefore
a later remote branch would publish substantial pre-existing local history as
well as these edits. Do not assume the remote matches the local qualification
baseline or silently treat the dynamic dependency workflow as V1 test evidence.

## 2026-09-27 — full regression finished; packaging and publication fence repaired

Session 3455 terminal: 2085 passed, 1 failed, 72 skipped, 319 subtests passed,
1581.85s. Source/test SHA256 manifest still matched immediately before edits.
The sole failure was test_stage2cb_b1_r2c readiness primitive source inspection:
Windows pipe calls moved to _publisher_pipe_io, but the check inspected the old
client file. It now reads the exact helper imported by the production client.
The readiness primitive assertion remains; no policy/evaluator changes.

Publisher client now explicitly imports its helper and obtains its script path
from that module, so the existing AST deployment closure includes/measures it.
A fresh staged application regression checks required presence, exact bytes,
manifest verification and isolated child invocation without checkout fallback.
Packaging/readiness/real Windows transport suite: 47 passed in 18.47s.

publish_governed_run now takes optional ExecutionScope; both normal and recovery
composition calls provide it. Local create/authorize is serialized via commit;
RPC stays outside authority locks, and ownership is rechecked after response.
Original launch epoch remains unchanged. New tests prove a replaced controller
cannot create/send and a takeover during the actual in-process trust publication
refuses old success while the replacement reconciles the exact persisted run.
11 publication tests passed in 6.26s; mypy clean for 98 source files.
This is NOT yet the combined whole-handler Git/queue/dependency proof. Admitted
local authorization contention and that combined scenario remain next. Read-only
inspection also found queue _stamp checks ownership before its atomic write;
need reproduce/audit its interaction with direct authority takeover before
claiming the NO STALE WRITE invariant. No final full rerun since these edits.

## 2026-09-27 — publication takeover and queue intent race

Previous turn classified as progress. No tests remain running.
Admitted publication authorization now has a concurrency regression: expiry and
sweep/new-epoch takeover wait until authorization is committed, and the expired
caller sends no RPC afterward. Four publication-fencing tests pass.

Reproduced queue _stamp race by replacing authority after record read: completion
was refused, but the stale pending_transition/outcome had already been written.
Wrapped the final serialized payload write in WorkAuthority.commit. Reproduction
now proves byte-identical queue record after refusal. Queue + publication suite:
43 passed in 13.45s; mypy clean 98 modules, touched Ruff clean, diff check clean.

Combined project takeover regression: actual parent proof anchors through the
component Publisher, authority is replaced before reply reaches the old handler.
Old handler cannot land Git, complete parent, or start child. Replacement respects
the durable recovery backoff (test advances only scheduling clock past its saved
deadline), reconciles same parent run, integrates and then runs child. Exactly two
Worker launches, child sees parent change, valid two-record anchor chain with one
parent record. Targeted scenario passed in 28.29s; other three graph scenarios
passed in preceding run (new scenario initially stopped on expected backoff;
fixture corrected to account for that behavior, production pacing unchanged).

This is component evidence with real Windows capture/Git, not real-provider or
service qualification. No final full suite after these fixes. Next review should
inspect WorkAuthority.resolve/release check-to-CAS lease-expiry windows before
claiming all terminal writes fenced; then close acceptance gaps and qualify.

## 2026-09-27 — terminal claim CAS now fenced; new complete regression

Reproduced resolve/release accepting an expired lease between initial checking
and durable claim mutation (two new tests failed before fix). ClaimStore's
terminal mutations now accept an optional commit guard; WorkAuthority supplies
LeaseStore.while_current. The claim lock is already held, so this follows existing
claims -> leases order and keeps the lease lock through durable state/history
write. Bare ClaimStore semantics remain unchanged. Cleanup still tolerates lease
expiry after committed work without misreporting it as failed.

Two expiry-before-commit tests pass. Two concurrent tests advance expiry during
admitted persistence, attempt lease replacement, and prove it cannot succeed
until terminal state is durable; the new lease survives old cleanup. Claims,
queue and terminal subset 66 passed in 12.18s; final four terminal cases passed
in 0.78s. Mypy clean 98 source modules, touched Ruff clean.

New complete regression LIVE exec session 18197, command pytest -q --tb=short
--junitxml=.gnosis/evidence/v1-regression-final-candidate-20260927/pytest.xml.
Source/test freeze: 206 Python files, manifest SHA256
ce3b100a7a09668d142be1848f3c183bbaa4a2bd84cd8a4179fb9c6ca0cabd0b.
Do not restart on slow output; poll exact handle until terminal. Avoid src/tests
edits during this run. Next independent work: prepare dedicated Worker/Publisher
real-provider qualification using documented provisioning paths, preserving
ChatGPT authentication and existing accounts/services outside scope.

## 2026-09-27 — real deployment preparation while regression runs

Regression 18197 confirmed live, last output past 22%, no displayed failure.
No source/test modifications this turn. Read-only deployment preflight saved in
.gnosis/evidence/v1-deployment-preflight-20260927/preflight.json; process remains
non-elevated, native Codex 0.148.0 available/hash recorded, proposed new Worker and
Publisher service names currently absent. No credentials read, account/service
created or auth changed. OpenAI Docs skill used for official ChatGPT/device login
instructions, matched installed CLI help (no login initiated).

Concrete bootstrap gap found: Stage2CBConfig/make_base_provision do not pass
Provisioner.codex_runtime_src; historical B1 writer remains deterministic/no-op.
Need connect a trusted native bundle input before fresh measurement and provide
real task/verifier/integration config. Do not run that legacy no-op and claim V1.
Full preparation and boundaries: docs/V1_DEPLOYMENT_PREPARATION_2026-09-27.md.
Continue safe preparation until regression terminal, then implement bootstrap
connection with dry provisioning regression before any elevation/login request.

## 2026-09-27 — native Codex package layout delivery defect confirmed

Regression 18197 remains live (past 26%). Read-only inspection of the actual
installed native vendor tree shows codex-package.json layoutVersion1 with
entrypoint bin/codex.exe, sibling codex-resources (sandbox setup/command runner)
and codex-path/rg.exe. Current Provisioner and bind_codex_runtime assume a flat
codex.exe source/destination. Passing the bin directory would omit descriptor and
helpers. Need preserve/measure the complete native package and validate entrypoint
inside it, plus real-layout/invalid-layout regressions once freeze ends.
Preparation doc updated with exact file structure and required correction.
Stage2CBOrchestrator always rolls back; it is qualification, not persistent
installation. Keep its behavior; add a deliberate persistent lifecycle using the
same provisioners/journal and DPAPI-protected generated Worker password, not the
historical harness test password. No code or tests changed this turn.

## 2026-09-27 — native bundle staging evidence

Regression 18197 confirmed live, latest displayed milestone 29%, no displayed
failure. Prepared .gnosis/evidence/native-package-stage-20260927/codex by copying
only the known native vendor package (six binaries/descriptor files). Inspection
JSON records individual SHA256 and byte lengths; all six staged files match the
source. Running staged bin/codex.exe --version returns codex-cli 0.148.0. No login,
credential copy, provider call, service installation or ACL change occurred.
This proves relocation/version startup only, not sandbox/provider qualification.
Use this exact complete native layout as evidence for the upcoming staging/binding
fix after the running suite is terminal. Source/tests remain frozen.

## 2026-09-27 — isolated native-package validator prepared

Regression 18197 remains live, latest milestone 41%, no displayed failure. To
make independent progress without modifying its imported source/tests, prepared
.gnosis/work/native-package-fix/codex_package.py and test_codex_package.py.
These are DRAFTS, not yet production modules or integrated tests. Validator reads
a bounded duplicate-key rejecting descriptor, accepts observed native Windows
layout-v1, requires all five executable/helpers, rejects linked paths and altered
entrypoint/resource layout. It resolves the actual staged native package to
bin/codex.exe. Twenty isolated tests pass in 0.45s; strict mypy clean (one module),
Ruff clean after import formatting. No production source/test bytes modified.
Next after full run: integrate/review draft into provision layer, wire complete
package staging and bind_codex_runtime to its measured bin entrypoint, update
real-layout fixtures and bootstrap input, preserving trust measurement/gates.
Do not confuse draft validation or --version with real Worker qualification.

## 2026-09-27 — complete regression passed and native layout integrated

Session 18197 terminal exit0: 2096 passed, 72 skipped, 389 subtests in 1687.98s.
JUnit confirms zero failures/errors (2557 entries including subtests), source/test
freeze manifest matched before edits. Skips remain environment-specific (mainly
high-integrity Windows authority/publication checks); not counted as qualified.

Integrated isolated draft into src/gnosis/provision/codex_package.py and
 tests/test_codex_package.py. Provisioner validates complete vendor layout and
copies the whole source; composition binds providers/codex/bin/codex.exe only
after full runtime digest match and package validation. Stage2CBConfig optional
codex_runtime_src now reaches existing Provisioner. Existing deterministic default
is preserved; no trust-plane evaluator/measurement relaxation.

Updated provider fixtures to real package shape. Targeted package/provider/B0
suite: 80 passed, 18 subtests, 51.86s. Added filesystem-backed bootstrap regression
proving all provider bytes copied before observation: passed in 0.68s. DryOperations
normally stubs directory copies, so this test explicitly uses real filesystem copy
for the provider only, with all Windows mutations simulated. Mypy clean 99 source
modules, touched Ruff clean, diff check clean. No live test sessions remain.

Next: reject bad provider input before install creates any OS resources; prepare
persistent lifecycle rather than relying on always-rollback qualification harness.
Need fresh deployment, dedicated Worker ChatGPT login, real task/recovery evidence
and final acceptance. No elevation/account/service/auth mutation yet. Estimated
progress now communicated as 70%/30%, not an acceptance claim. Full regression
predates this native-package integration; final deployment delta remains to verify.

## 2026-09-27 — reject invalid provider before provisioning side effects

Provisioner.install now validates the complete native package before invoking
_create_identities. Direct _deploy_code callers also validate before mkdir/copy.
A missing/empty sandbox helper is rejected with zero recorded Operations calls
for both entry points. Shared validation avoids divergent checks. Package/provider
suite: 34 passed in 4.88s; strict source mypy and touched Ruff clean.
No sessions running; prior full regression remains the 2096-pass snapshot before
these deployment deltas. Persistent install lifecycle is next, consuming
GnosisDeploymentProvisioner.provision and the existing F-17 Provisioner. Important:
Stage2CB qualification always rolls back, so it must not be presented as a lasting
installation. No account/service/ACL/auth modifications have been performed.

## 2026-09-27 — persistent installation orchestration component

Added scripts/v1_installation.py::install_persistent, consuming existing preflight,
ResidueStore, make_base_provision, GnosisDeploymentProvisioner and Publisher pipe
readiness. Success retains installation rather than qualification rollback. Uses
fresh secrets.token_urlsafe(36) Worker password handed to existing DPAPI provisioner;
no fixed harness password, login or provider call. Refuses existing resources or
active journal; serialized through maintenance journal-directory FileLock.
Failure retains recovery journal; composed provisioner retains its existing own
rollback behavior. No live operations performed.

Three tests pass in 4.14s: persistent success + reinstall refusal; pipe readiness
failure retains acquired-resource journal; non-elevated preflight creates no
install resources. Filesystem provider copying is real, Windows ops are simulated.
Ruff clean. This is a COMPONENT API, not yet an operator CLI or qualified installer.
Next required work: trusted CLI/config/source freeze binding; protected maintenance
journal location and operation ownership verification; persistent verify/recovery/
uninstall entry points; meaningful provider task inputs; real elevation/login.
Do not treat caller-supplied actual_head/f17_stable arguments or fake observations
in tests as real provenance. The live entrypoint must compute them and validate
config source_root consistency before invoking this component. Existing full-suite
2096-pass snapshot predates these installation changes.

## 2026-09-27 — persistent deployment reload and verification component

Added verify_persistent: validates exact acquired ownership set/run/status, reads
canonical composed record and manifest, rejects redirected entry/package/worker
paths, reconstructs ComposedDeployment and calls existing verification with a
fresh effective-identity observation. Install now uses this disk reload before
returning success. No stored-digest-only acceptance. Component explicitly requires
a maintenance caller that proves protected configuration/journal locations; no
live CLI yet. Seven install/restart/drift tests passed in 11.16s (application,
identity and ownership modifications refused). Test sys.path bootstrap made
explicit so Ruff ordering cannot cause stage2cb import failure in isolated runs.
Ruff clean; no test sessions live. No OS account/service/auth modifications.
Next remains trusted maintenance entrypoint, source/config binding and protected
journal preflight, plus explicit recovery/uninstall lifecycle and real qualification.

## 2026-09-27 — installation source observation and pinned entry component

Added scripts/v1_source.py::inspect_install_source: read-only bounded Git commands,
full expected object IDs, exact repository root/HEAD/tree, no staged/unstaged or
untracked input. Six real-Git tests pass (clean, wrong commit/tree, dirty, untracked,
subdirectory refusal) in 4.35s. Added install_pinned wrapper: derives checkout from
executing maintenance script, observes config.source_commit/tree, then invokes
installation with observed source; no user-supplied actual_head flag on this entry.
Its f17_stable means exact clean approved snapshot, not inherited qualification.
Low-level injectable component remains for deterministic tests. No live install.

Next: protected maintenance configuration/journal and CLI argument parsing with
fail-closed elevation/source checks; real observer bindings (no injectable fake
observer on CLI), verify/recovery entry points. Current working tree is dirty and
must be reviewed/pinned before actual install. Do not manufacture a clean-source
claim or bypass the new check. No tests currently running; no auth/OS mutations.

## 2026-09-27 — private maintenance directory ACL gate

Added scripts/v1_maintenance_security.py using the existing binary Windows
security descriptor observer. Requires existing absolute ordinary directory,
Admins/SYSTEM owner, protected DACL, exact inheritable full-control allows for
Admins/SYSTEM only. Does not rewrite/normalize permissions. Seven pure descriptor
tests pass (worker owner, null/unprotected DACL, Users grant, inherit-only and
missing admin/system access refused). Connected gate to install_pinned before any
installation operation. Ruff clean; no Windows ACL or account change performed.

This is not full path-authority proof yet: the live setup still needs to create
its fixed maintenance directory securely, validate ancestor replacement rights
and reject linked ancestors, then bind protected config/journal. No CLI or real
installation claimed. Keep existing binary observer/policy boundaries unchanged;
these are additional consumer requirements, not relaxation of trust checks.

## 2026-09-27 — maintenance ancestor authority observed

Read-only binary ACL observation of C:/, C:/ProgramData and C:/Program Files
performed with existing Windows observer. Added conservative ancestor mutation
checks (owner Admins/SYSTEM/Windows TrustedInstaller; no untrusted effective write,
delete, delete-child or ACL/owner-control rights; inherit-only entries excluded
from current-directory rights). Linked/missing ancestors refused. Integrated with
private maintenance directory check. Fifteen descriptor regressions pass in 0.17s;
actual C:/Program Files chain passes read-only verification. Proposed private
maintenance location C:/Program Files/GnosisAgentBMaintenance is absent; no folder
or ACL created/changed. Root ownership observed as Windows TrustedInstaller;
ProgramData has broad creation/write attributes, so use Program Files for the
maintenance journal rather than relaxing checks. Ruff clean.

Next: concrete elevated setup entry creates that fresh private directory with
Admins/SYSTEM-only ACL before any journal/config write, checks it using these
observers, binds fixed deployment inputs to approved source, calls install_pinned
with real observation. Preserve all collisions and never rewrite existing unknown
folder ACLs. Authentication and service qualification still pending.

## 2026-09-27 — real ACL/path composition gap found before deployment

Added create_maintenance_directory: requires elevation and fresh absolute path,
checks ancestors, creates only that directory, applies Admins/SYSTEM-only DACL and
owner then independently verifies. Refuses collision; failure leaves visible
folder, no recursive deletion. Twenty maintenance tests pass (0.32s), Ruff clean.
No live creation or ACL changes.

Read-only canonical graph audit found a deployment blocker to prioritize before
more installer work: OperatorInputs only has director_root/repo_path. Composition
builds BOTH RunStore(op.director_root/runs) and WorktreeManager(...,
op.director_root/worktrees), along with protected brief/hold/task state. Historical
writer sets director_root=state_base. Actual layout ACL denies Worker writes to
state_base; only work_base grants Worker MODIFY. bootstrap.py lines169-170 opens
spec.stdout_path/stderr_path AS the Worker. Provider execution directly passes
RunStore paths into LaunchSpec. Therefore a real Worker cannot create its output
or edit its worktree when state is properly protected. Moving all director_root
into work_base would instead expose coordination state and is NOT a valid fix.

Next: explicit trusted worker workspace/raw-output plane separate from protected
Director metadata/records, map production worktrees to work_base, stage Worker raw
output there and preserve/capture it into trusted evidence without treating raw
bytes as authority. Cover real path/ACL contract plus existing component recovery
and proof/integration tests. Do not weaken existing ACL matrix or bootstrap rules.
This is newly confirmed source/path evidence, not yet an OS-real reproduction.
# Worker worktree/provenance separation — 2026-09-27

Canonical composition now places task checkouts under the deployment launch/work
root, namespaced by the canonical Director state path. WorktreeManager accepts a
separate provenance_root; composition retains its handle records in protected
director_root/worktrees. Component defaults remain compatible. A real Git
regression recreates the manager, reattaches the existing checkout, and ignores a
forged marker in the writable work root. Composition checks assert the two planes.

Validation: worktree/composition suite 50 passed (40.71s); composition rerun after
adding path-boundary assertions 17 passed (3.53s); touched-file Ruff passed.
This is not OS ACL qualification. Worker stdout/stderr staging and secure readback
remain unresolved; the protected RunStore must not be made Worker-writable.
Existing deployments with old checkout paths must retain their original evidence;
no destructive relocation or live deployment was performed. Overall V1 incomplete.

# Safe Worker output reads — 2026-09-27

Added trust.worker_output.read_worker_output and connected it to dedicated
Worker authentication status, Codex transcript parsing and deterministic result
reading. Windows opens a single handle denying writes/deletion, validates its
final lexical path, rejects reparse/nonregular/multiple-hardlink files, and reads
bounded bytes through that same handle. Codex parsing now also accepts captured
bytes so validation does not reopen the untrusted path. Linux support is for
components; Windows is the deployed boundary.

Validation: 72 tests passed across worker_output/provider_execution/execution_port/
codex_cli (1.11s), including real Windows junction/hardlink rejection and a write
attempt during the held read. Three source files passed strict mypy; touched-file
Ruff passed before the final exception-cleanup adjustment. No deployed Worker
was run. Next: runner must allocate unique output staging under work_base and
retain safely captured bytes in protected RunStore on success/failure/cancel.
The existing path permission blocker is only partially repaired; V1 incomplete.

# Worker output staging connected — 2026-09-27

Production TrustedExecutionRunner now allocates a fresh directory in the
deployment work root for stdout/stderr/auth logs. Before launch it exclusively
writes and fsyncs a protected staging journal naming the attempt and paths.
After execution, including failure/cancellation/authentication refusal, it reads
available logs through read_worker_output and exclusively writes/fsyncs protected
attempt records. Existing records are never overwritten. Capture failure clears
publication references and fails the attempt; staging is retained. Deterministic
cassettes now have unique attempt-based names. Proof raw/worker artifacts use the
final recorded result's protected paths, not mutable LaunchSpec staging paths.

Validation: staging/trusted_runner/composition 28 passed; expanded staging suite
6 passed, including a redirected hardlink refusal and existing-attempt retention.
Ruff passed and strict mypy passed for runner/composition/proof. Broader regression
session 84849 (project_execution/task_proof/pipeline_trusted_execution/
trusted_attempt_isolation) is RUNNING, not yet passed.

Remaining: bind captured successful stdout bytes to the exact parsed result;
exercise recovery of staged partial output after Director process death (journal
provides durable attribution but automatic import is not yet implemented); real
dedicated-Worker/ACL qualification and install integration. V1 remains incomplete.

# Parsed stdout snapshot binding — 2026-09-27

ExecutionOutcome now carries the bounded stdout bytes actually parsed by the
trusted execution port. Both deterministic and provider paths read/validate once.
The staging runner retains that snapshot for successful runs instead of reopening
mutable Worker stdout. Other raw/error files still use the safe bounded reader.
Regression changes the staged file after parsing and proves the protected raw
record contains the original parsed bytes. No claim about stderr authenticity is
introduced: it remains forensic Worker data.

Validation: execution_port/provider_execution/trusted_runner/staging 46 passed;
expanded staging suite 7 passed (0.78s), Ruff and two-file strict mypy passed.
Session 84849 remains live with progress and no failure output observed; it began
before the snapshot-binding change, so it does not qualify that newer code.
Automatic staged-output import after Director death remains the next gap.

# Staged output crash recovery — 2026-09-27

TrustedExecutionRunner.recover_outputs validates the protected journal's schema,
attempt id and exact assigned staging namespace before retaining missing raw/auth
files. Existing output is preserved. It does not launch a process or reconstruct
success/publication authority. GovernedPipeline invokes it for checkpointed
attempt ids when resuming with the trusted runner. File retention and fsync are
centralized in trust.worker_output, keeping the runner free of OS execution APIs.

Actual separate-process os._exit(77) regression leaves only staging and the
protected journal; a fresh runner recovers both streams, and repeating recovery
is idempotent with no launch. Wrong attempt/outside-path journals are refused.
Staging suite: 10 passed (0.88s). Pipeline resume + initial staging: 19 passed
(57.17s). Staging + trusted pipeline: 18 passed (11.97s). Three-file mypy passed.

Earlier broader session 84849 finished 57 passed / 1 failed (351.79s): structural
guard rejected the runner's os import used only for fsync. The guard was retained;
moving durable file retention into the file-I/O module repaired it, verified by
the 18-test rerun. That broader run predates the snapshot/recovery changes and is
not final acceptance. Next: canonical deployed ACL/provider qualification and
installation integration, plus final regression. Real Worker identity/login and
service checks are still outstanding; V1 remains incomplete.

# Explicit persistent maintenance entry — 2026-09-27

scripts/v1_maintenance.py now exposes initialize/install/verify actions requiring
explicit --execute and an elevated Windows process. It uses the existing real
backend, protected-maintenance-directory checks, strictly decoded configuration,
clean pinned source gate and fresh observe_deployment digest; no implicit login,
provider call or elevation. JSON is bounded, rejects duplicate/unknown/missing
fields and nonabsolute paths, and requires full source commit/tree IDs. Config
and ownership journal must share the protected maintenance directory. Initialization
does not yet stage a configuration file: concrete installation inputs remain next.

CLI --help succeeds. Maintenance + installation regressions: 16 passed (11.67s).
Touched-file Ruff passed. No test process is running. No real account/service/ACL
or authentication mutation occurred. git status currently lists 107 changed or
untracked entries, which must be reviewed and pinned before install_pinned can run.
V1 estimate remains 72%; production qualification still missing.

# Concrete candidate draft and full regression — 2026-09-27

Full pytest is RUNNING as session 5924 with JUnit destination
.gnosis/evidence/v1-regression-staging-recovery-20260927/pytest.xml. The adjacent
source-test-script-sha256.json freezes 249 Python source/test/script files. Do not
change those files until this run ends; verify the manifest afterward. Full mypy
passes all 100 source modules; git diff --check passes.

Concrete installation draft is in
.gnosis/evidence/v1-install-candidate-20260927/installation.draft.json, accompanied
by readiness.json explicitly declaring NOT READY. It uses the actual Python base,
validated complete native Codex bundle, proposed dedicated Worker/service and
separate Program Files/ProgramData roots. All three target roots and maintenance
directory were observed absent. Native executable hash still matches the recorded
2ad2cf8a... runtime. Draft schema validation passes. Its source IDs are the current
HEAD and must be regenerated after reviewing/pinning pending changes: this draft
must not be installed. No privileged mutation occurred.

Git's untracked entries also include generated native binaries, copied runtime
sources and local evidence. Preserve these locally; do not include them in a
source commit. A separate clean managed checkout of the reviewed candidate can
satisfy installation provenance without deleting evidence or weakening the gate.

# Worker tool discovery blocker reproduced — 2026-09-27

While full regression 5924 runs, read-only source audit found that
TrustedExecutionPort creates provider LaunchSpec without environment overlay.
child_environment builds only Windows system PATH entries; stage2cb provision
also supplies an empty toolchain_files tuple. Thus copying Python/Codex alone
does not make git/python discoverable to provider-launched task commands.

Reproduction uses actual cmd.exe with deterministic_path and a minimal explicit
environment (same user, NOT dedicated Worker qualification). Both git --version
and python --version exit 1 with the current default PATH. Adding installed Git
cmd and Python base explicitly yields exit 0: Git 2.55.0.windows.4, Python 3.12.14.
Evidence: .gnosis/evidence/v1-toolchain-preflight-20260927/tool-discovery.json.

Required follow-up after frozen regression: stage the existing complete Git
distribution under the measured/protected runtime tree, validate its required
files before mutations, bind trusted Python/Git directories from that same tree,
and seal the bounded PATH overlay in provider LaunchSpec. Never inherit profile
PATH or relax bootstrap policy. Add provider-binding/launch tests and verify the
relocated Git bundle. The current installation draft is not ready for real use.

# Relocated Git qualification running — 2026-09-27

Session 59204 copies the complete existing C:/Program Files/Git distribution to
.gnosis/evidence/v1-relocated-git-20260927/git and compares SHA256 for every file.
Source inventory: 9581 files, 423232879 bytes, no symlink/junction entries. Copy
completed; comparison is still running (live handle and process observed). Next
within that same process: git --version/--exec-path, initialize a disposable local
repository, commit and add a linked worktree under a minimal explicit PATH. No
network operation or production source change. Do not duplicate the stage job.

Full suite session 5924 also remains live, beyond 24%, with no failure output yet.
Neither process is qualified as passed. Frozen production/test/script files have
not been edited during this turn. Real dedicated-Worker permissions and access to
the source repository's Git metadata remain separate deployment checks.

# Relocated Git passed; bootstrap path audit — 2026-09-27

Session 59204 finished exit 0. All 9581 staged Git files match source hashes;
nine local commands pass, including version, exec-path inside the copied package,
init/commit/worktree/status under explicit minimal PATH. qualification.json and
git-sha256.json are under .gnosis/evidence/v1-relocated-git-20260927. This proves
same-user relocation only; no dedicated Worker/token/ACL qualification.

Further source evidence: worker_launcher.bootstrap_script_path derives the
bootstrap beside the Director's imported launcher module. Canonical operator
deployment puts that module under publisher, whose ACL grants no Worker access.
stage2cb.make_base_provision passes bootstrap_files=(), unlike the historical
provisioning probe's explicit BOOTSTRAP_CLOSURE. Production needs a measured,
Worker-readable bootstrap closure and a trusted binding to that deployed path;
do not grant Worker access to Publisher or weaken the ACL matrix.

PATH wiring must also account for launcher.launch replacing spec.environment
from director_env/allowlist before sealing. Default allowlist excludes PATH even
though LaunchSpec's existing closed set permits it. Bind the same explicit
measured PATH in the port and launcher so the returned spec and actual sealed
launch identity remain identical; merely adding environment to the port would
be discarded. No production edits while full regression 5924 remains running.

# Minimal bootstrap closure staged — 2026-09-27

The existing static import-closure walker derives exactly eight modules from
gnosis.trust.bootstrap. They were staged byte-for-byte under
.gnosis/evidence/v1-bootstrap-stage-20260927/bootstrap. Running the staged entry
with Python -I -B reaches its expected missing-arguments refusal (exit 120, usage
message, no import traceback). import-qualification.json records every hash.
No credential, sealed launch or Worker process was used, so this is import and
relocation evidence only, not an ACL/identity qualification.

Use this minimal closure in the Worker-readable protected runtime/bootstrap
plane. The Publisher's full package must remain inaccessible to the Worker.
Full regression 5924 remains running; source/test/script snapshot still frozen.

# Git package validation draft — 2026-09-27

Prepared .gnosis/work/v1-deployment-fix/git_package.py and its eight-test suite
outside the frozen production/test tree. The helper rejects nonabsolute or
redirected package roots/entries and missing, empty or nonregular required Git
files. It preserves the complete vendor tree contract; it does not claim a
layout check establishes runtime provenance. Eight tests pass (0.32s), including
an actual Windows junction refusal; Ruff passes. It also accepts the real staged
9581-file Git package. Not yet integrated into production provisioning.

Session 5924 remains live, beyond 39%. All 249 frozen Python files still match
their source/test/script manifest. Integrate the validated draft only after the
frozen run is terminal; preserve the completed relocated-Git evidence.

# Sealed tool PATH contract reproduced — 2026-09-27

Actual LaunchSpec/build_worker_environment/child_environment calls confirm the
default launcher overlay discards a port-supplied PATH, whereas supplying the
same trusted PATH explicitly to the port spec and launcher with the existing
PATH allowlist entry preserves exact spec equality. A hostile Worker profile
PATH remains excluded. No security policy change is needed. Reproduction JSON:
.gnosis/evidence/v1-toolchain-preflight-20260927/sealed-path-contract.json.
This records the intended binding contract only; production integration is still
pending after full regression 5924, which remains live and progressing.

# Isolated runtime integration candidate passed — 2026-09-27

Managed worktree created/attached at
C:/Users/nicol/.codex/worktrees/agent-b-runtime/GnosisAgentAi, initially detached
at ca17d9f72da29a4edbc320217e3b15dcd9681fed. Overlaid the exact 249-file frozen
working source/test/script snapshot there (verified hashes), then implemented
runtime fixes WITHOUT changing the original full-suite source.

Worktree candidate changes: complete Git package input validated before install
mutations, copied under measured runtime/toolchains/git; minimal eight-module
bootstrap closure copied under measured runtime/worker-bootstrap. Provider binding
requires both and derives Python/Git PATH plus bootstrap path from the same measured
tree. Launcher accepts the explicit trusted bootstrap and uses the same explicit
PATH as the provider spec, retaining exact sealed spec equality. Security ACL and
LaunchSpec environment policy were not changed. Persistent maintenance JSON now
also requires git_runtime_src. Existing draft JSON must be regenerated accordingly.

Worktree regression 92039: 168 passed, 1 platform skip, 18 subtests (76.62s).
New runtime-binding tests: 2 passed (0.30s). Earlier installer/Git tests: 24 passed
(14.45s). Full worktree mypy: 101 source modules passed. Touched-file Ruff passed.
These prove components, not a real dedicated-Worker installation.

Pending transfer after original full run 5924 (currently beyond 84%) finishes:
scripts/{stage2cb,v1_installation,v1_maintenance}.py;
src/gnosis/director/{composition,execution}.py;
src/gnosis/provision/{operator_stack,provisioner}.py;
src/gnosis/trust/worker_launcher.py;
tests/{test_provider_deployment,test_v1_installation,test_v1_maintenance}.py;
NEW src/gnosis/provision/git_package.py, tests/test_git_package.py,
tests/test_worker_runtime_binding.py. Preserve all other original changes.
No worktree tests currently running. Full original session 5924 remains live.

# Maintenance entry import isolation repaired in worktree — 2026-09-27

An actual worktree CLI invocation exposed editable-install leakage: it imported
operator_stack from the original checkout, where worker_bootstrap_files is not
yet present. The isolated worktree's v1_maintenance.py now derives src/scripts
from its own file location before imports. Base Python -I -B --help succeeds;
regression invokes -I -S -B from an unrelated directory, disabling site/editable
imports, and passes. Worktree maintenance suite: 10 passed (1.29s); Ruff passed
before the final added regression. Include this correction in the pending delta
transfer listed below. No original frozen source files changed; session 5924
remains running beyond 84%, with no failure output seen.

# Full staging/recovery regression passed; runtime delta transferred — 2026-09-27

Session 5924 completed exit 0: 2177 passed, 72 skipped, 416 subtests passed in
1793.28s. JUnit contains 2665 cases including subtests, zero failures/errors.
All 249 frozen source/test/script hashes matched AFTER completion. Evidence is
.gnosis/evidence/v1-regression-staging-recovery-20260927. Skips still include
real high-integrity authority/publication checks, so this is not OS qualification.

Then transferred ONLY the 14-file runtime/toolchain candidate delta from managed
worktree agent-b-runtime into the original checkout. Before/after hashes and
baseline JUnit summary are recorded in
.gnosis/evidence/v1-runtime-integration-20260927/transferred-files.json. All other
original edits were preserved. The transferred version has targeted evidence
(168 + 2 runtime tests, maintenance 10, mypy 101 modules) from the worktree, not
the preceding full-suite result; do not describe 5924 as a full run of this delta.

No processes/tests remain running. Reuse the active managed worktree when useful;
do not create another or archive this one while candidate source is needed.
Next: inspect/pin source-only changes (exclude generated binaries/evidence), prepare
clean installation checkout and regenerate protected config commit/tree. Draft
installation JSON now includes git_runtime_src=C:/Program Files/Git and validates
against the new maintenance schema, but remains explicitly NOT READY.
