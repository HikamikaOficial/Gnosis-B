# V1 acceptance audit — 2026-09-27

**Verdict: INCOMPLETE.** Scope is the unmodified
`gnosis-spec/V1_DEFINITION_OF_DONE.md`, excluding the separate Autopilot and Gnosis
Control. This document records evidence and gaps; it does not redefine acceptance.
Progress percentages communicated to the operator are estimates, not this audit.

**Verifier isolation update:** the b02f1cb installation candidate executes checks
under the Director identity and is not ready for privileged candidate execution.
The managed worktree now binds normal verification, proof recapture and merged
tree verification to WorkerCheckExecutor. Two complete component paths passed;
the wider regression passed 117 tests as session 23305. This does not establish actual
Windows account separation. See V1_VERIFIER_ISOLATION_2026-09-27.md for current
implementation and evidence. Original pinned-source full suite 47975 finished
with 2188 passed, 72 skipped and two failed untracked-directory subtests caused by
the preserved generated embedded test repositories. All 252 pinned file hashes
matched. This full run is not a pass; the current candidate requires its own full
run in the managed checkout. Subsequent recovery wiring passed 41 focused tests
and 22 packaging/restart tests, with no real Worker-account qualification yet.

Regression session 18197 passed: 2096 passed, 72 skipped, 389 subtests, 1687.98s.
The 206-file frozen manifest matched afterward; JUnit is in
.gnosis/evidence/v1-regression-final-candidate-20260927. Subsequent native-package
installation fixes have targeted evidence but not another full run. Prior run
3455 ended 2085 passed / 1 failed / 72 skipped; its source-inspection failure was
repaired and subsequent packaging/fencing regressions passed. Directed results are
recorded in V1_RESUMPTION_2026-09-26.md; test existence alone does not prove a pass.
A full local green run is recorded; dedicated-Worker production qualification
and final acceptance of subsequent deployment changes remain unproven.

## Functional requirements

| Requirement | Current evidence / limitation | Acceptance |
|---|---|---|
| Durable project/task | ProjectStore and phase checkpoints; project CLI graph survives parent completion/restart | Component evidence; full regression pending |
| Task dependencies | Immutable DAG validation and resolved-parent queue readiness | Component evidence |
| Detect ready tasks | Child launches only after parent publication and Git integration; refusal keeps child waiting | Component evidence |
| Lease/fencing claim | ClaimStore/LeaseStore/WorkAuthority, whole-handler supervisor heartbeat | Component evidence |
| Reject stale writes | Atomic phase/receipt/Git/queue-intent/terminal-claim commits; local publication authorization fenced; delayed-RPC project takeover/recovery passed | Component evidence; deployed qualification and remaining artifact audit pending |
| Isolated worktree | WorktreeManager, preserved task identity across restart, parent code visible to child | Component evidence |
| FakeClaude/FakeCodex in CI | Scripted reviewer/implementer and Codex JSONL/permission/login doubles; Windows GitHub workflow now added | Local suite evidence; hosted CI execution still not qualified |
| Real Claude/Codex when available | Host Codex login/smoke recorded earlier; native trusted runtime binding implemented | OPEN: dedicated Worker login and real canonical execution not qualified |
| Structured/raw outputs | RunStore, strict Worker contract, recorded corrections, separate integration review attempts | Component evidence; remaining artifact fencing audit |
| Rate limit versus code failure | Typed failure classifier/holds, engine quota parking, supervisor parks | Tests mapped; await current full result |
| Bounded malformed-output repair | CLI review adapter repair and Codex malformed JSONL rejection | Tests mapped; real-provider survival case outstanding |
| Hung subprocess timeout/cancel | CLI runner cancellation, borrowed cancellation, real unresponsive pipe test with terminated helper | Component evidence; fresh real Worker timeout/kill still outstanding |
| Deterministic verification | CommandVerifier and strict verification verdict at convergence/proof/integration | Component evidence |
| Read-only review | Reviewer permission mapping, subject/tamper checks, integration re-review | Component evidence; dedicated reviewer OS qualification outstanding |
| Bounded rework | Persisted round/launch/attempt limits; interrupted correction resumes before accepting verdict | Component evidence |
| Proof packet | Real Windows capture bound to reviewed bytes and sealed raw/convergence evidence | Component evidence; production account/service qualification missing |
| Refuse DONE without evidence | State-machine completion gate, publication reconciliation, integration prerequisite for project completion | Component evidence; full requirement audit not closed |
| Kernel restart preserves work | Separate Python os._exit implementation/review tests plus task/phase and project restart tests | Component evidence |
| Worker crash recovery | Partial outputs/task work survive separate process death; trusted launch/cancellation component cases | Partial: fresh dedicated Worker kill under deployed composition missing |
| No infinite loops | Durable retry/round/budget limits; bounded project supervisor; bounded pipe client | Component evidence; audit all remaining native/process waits |
| Append-oriented audit | Claim history, run ledger, immutable checkpoint generations and unique correction/re-review attempts | Partial: confirm every recovery path retains attributable records |
| Git integrity | Review-bound commit, pinned merge SHA, prepared retention ref, dirty-source and changed-branch refusal | Component evidence; real deployed project run missing |

## Required survival scenarios

| Scenario | Sources to inspect / evidence boundary |
|---|---|
| Worker kill | test_pipeline_resume real process death; test_provider_execution doubles; dedicated Worker kill remains open |
| Kernel restart | test_pipeline_resume, test_project_execution, test_integration_resume, test_task_proof |
| Stale lease | test_claims, test_queue_fencing, test_borrowed_scope, test_checkpoint_commit_fencing, test_terminal_commit_fencing; delayed-RPC takeover/recovery in test_project_execution |
| Repeated identical failure | test_retry, test_convergence bounded rounds/stalemate and durable budget tests |
| No-diff loop | test_convergence stalemate and done-without-change cases |
| Malformed JSON | test_codex_cli, test_cli_review_adapters, test_worker_result_contract |
| Timeout | test_cli_runner, test_provider_execution, test_publisher_transport_windows real hung server |
| Simulated rate limit | test_failures, test_engine quota parks, test_supervisor_fencing |
| Reviewer disagreement | test_cli_review_adapters PASS-with-blocking-finding, test_convergence uncertain/blocking verdicts |
| Merge conflict | test_integration.test_a_textual_conflict_is_typed_and_names_its_paths |
| Invalid transition | test_state_machine illegal transition and generic-completion bypass refusal |

## Invariants not yet closed

- NO LOST WORK: strong restart/raw retention evidence, but full deployed kill and
  crash matrix still required.
- NO INVALID DONE: project completion requires publication and integration;
  final requirement-by-requirement acceptance has not yet passed.
- NO STALE WRITE: atomic checkpoint/receipt/Git boundaries are covered. The
  Publisher authorizes and commits independently through a named-pipe request;
  client timeout does not prove server cancellation. Remaining boundaries open.
- NO INFINITE LOOP: explicit bounds exist and pipe hang was repaired; full suite
  and deployment tests are still needed to substantiate the system-wide claim.

## Read-only workstation observation

The current process token is not elevated. Service discovery found only
GnosisControlWorkerNetworkBroker (stopped), which is outside scope and was not
modified. Local user gnosis-wrk56 exists and is enabled; its existence is not
evidence of a qualified Worker, credentials, ChatGPT login or deployment. No
credentials were read and no account, ACL or service was changed in this audit.

The existing OS-real B1 driver checks source/HEAD, deployment prerequisites and
explicit execution confirmation before constructing its privileged backend. Its
historical deterministic no-op configuration is not proof of a real provider
implementing and integrating a project. Prepare the current qualification inputs
and resolve the actual elevation/login requirements before claiming deployment.
