# GNOSIS Validated Learnings

Only durable, evidence-backed learnings belong here.

Format:

## L-XXXX — Title
- Status: VERIFIED / PROVISIONAL / STALE
- Evidence:
- Scope:
- Lesson:
- Operational consequence:
- Revalidation condition:

## L-0001 — uv tool shims on Windows break self-re-exec'ing CLIs
- Status: VERIFIED
- Evidence: `.gnosis/lab/memory/results/m3-memory-2026.8.19.16/SCORECARD.md` (python -v trace)
- Scope: any Python CLI that re-execs itself via `sys.orig_argv`/`sys.executable` (m3's UTF-8 relaunch), installed via `uv tool install` on Windows.
- Lesson: the re-exec resolves to the base interpreter without the tool venv → `ModuleNotFoundError` for the tool's own package.
- Operational consequence: `PYTHONUTF8=1` is set user-wide and pinned in `.mcp.json`/tests; any future tool showing "installed but ModuleNotFoundError on itself" gets checked for a self-relaunch first.
- Revalidation condition: uv changes shim/trampoline behavior, or m3 removes the import-time re-exec.

## L-0002 — Windows: closing races between dying children and tempdir cleanup are a recurring class
- Status: VERIFIED
- Evidence: our own `tests/test_cli_runner.py` teardown fix (commit 1f282b9) and zmem 0.1.17's identical crash in `doctor.check_eval → eval.run_eval` (WinError 32 on `memory.sqlite`).
- Scope: any code that deletes a directory while a just-killed process or an unclosed SQLite handle may still hold a file in it.
- Lesson: POSIX allows unlinking open files, Windows does not; tests/tools written on Linux hit this only here.
- Operational consequence: bounded-retry cleanup in our tests; treat third-party diagnostic crashes of this shape as diagnostic-only before downgrading the tool itself (`zmem audit health` is the working Windows probe).
- Revalidation condition: zmem fixes eval.py handle lifetime upstream.

## L-0004 — A refuted review finding is not a dead finding
- Status: VERIFIED
- Evidence: ADR-0006 "Review outcome" §6 — the shared-FileLock finding was refuted by an adversarial verifier ("single-threaded usage"), then proven true days—hours later when the heartbeat pump introduced the second thread and tests crashed exactly as the original reviewer predicted.
- Scope: any adversarial find→refute pipeline.
- Lesson: refutation verdicts encode the *current* usage assumptions; a design change can resurrect a refuted finding. Runtime evidence (a failing test) outranks a verifier's reasoning.
- Operational consequence: refuted findings are recorded with the assumption that killed them (here: "no same-process concurrency"); when that assumption changes, re-check the graveyard before shipping.
- Revalidation condition: standing rule; no expiry.

## L-0003 — m3 `--database` flag does not provision fresh databases
- Status: VERIFIED
- Evidence: `.gnosis/lab/memory/results/m3-memory-2026.8.19.16/SCORECARD.md` (zero tables + "no pending migrations" on a fresh file).
- Scope: m3-memory ≤ 2026.8.19.16.
- Lesson: migration bookkeeping is per-install, not per-target-file; `--database` on a fresh path yields an unmigrated, unusable DB.
- Operational consequence: state isolation only via `M3_MEMORY_ROOT`/`M3_ENGINE_ROOT`/`M3_CONFIG_ROOT` (ADR-0001 §3); guarded by `tests/integration/test_memory_fabric_smoke.py`.
- Revalidation condition: upstream makes `--database` run migrations against the target file.

## L-0005 — "It runs before X" is a claim about the whole call path, not about the line above X
- Status: VERIFIED
- Evidence: ADR-0013 addendum finding 1. The policy gate was placed immediately before `cli_runner.run()` and the ADR claimed no child existed before the verdict. `_gather_code_intelligence_context` had already shelled out ~120 lines earlier, so a DENIED action still launched kernel subprocesses against the repository.
- Scope: any invariant of the form "nothing happens before the check".
- Lesson: the check is only as early as the *earliest side effect* on the path, and side effects hide inside helpers whose names sound read-only ("gather", "context", "inspect"). Placement is verified by asserting the collaborator recorded **zero** calls, not by reading the ordering.
- Operational consequence: gate-placement invariants get a test that counts calls on every subprocess-spawning collaborator, not just the one being gated.
- Revalidation condition: standing rule; no expiry.

## L-0006 — Wiring a mechanism to a primitive is not wiring it to production
- Status: VERIFIED
- Evidence: ADR-0012 review finding 1 (the taxonomy nothing imported), then ADR-0013 finding 2 one milestone later — the gate reached `TaskEngine` but `DirectorOrchestrator`, the path every real brief travels, never accepted a `policy`. The identical mistake, caught by the identical review question.
- Scope: any capability added to a kernel primitive that has a higher-level entry point.
- Lesson: knowing the rule ("a mechanism nothing calls is a parallel fiction") did not prevent repeating it, because the primitive's tests were green and felt like proof. The question that catches it is "which caller does a real request come through, and does *that* one pass it?".
- Operational consequence: a wiring milestone is not done until a test exercises it from the outermost production entry point.
- Revalidation condition: standing rule; no expiry.

## L-0007 — Writing the test for a repair is how you find the defect next to it
- Status: VERIFIED
- Evidence: ADR-0013 finding 7. Mapping `policy_gap` to `NEEDS_HUMAN` was the repair; asserting `penalizes_agent is False` then failed, exposing a pre-existing hole — `NEEDS_HUMAN` was missing from `_NON_PENALIZING`, so any operator rule-set gap counted against agent quality (constitution rule 7).
- Scope: any repair whose test asserts a *consequence* rather than the changed value.
- Lesson: asserting the changed field would have passed and hidden it. Assert what the change is *for*.
- Operational consequence: repair tests assert downstream consequences, not the edited field.
- Revalidation condition: standing rule; no expiry.

## L-0008 — A claim that has been falsified twice should be restated, not re-asserted more carefully
- Status: VERIFIED
- Evidence: ADR-0013. "No child process exists before the verdict" was falsified by the workflow review (code intelligence shells out), repaired, re-asserted — and falsified again by Codex (`git worktree add` runs before the gate and creates a branch).
- Scope: absolute invariants in ADRs and docstrings.
- Lesson: the second falsification was not bad luck; the claim was the wrong shape. An absolute over "any process" invites a counterexample from every helper on the path. The invariant that survives names the property that matters — *no process that could act on the repository or on the agent's behalf* — and states the deliberate exception (read-only probes that compute the identity being judged).
- Operational consequence: when a review falsifies an invariant, fix the code AND ask whether the invariant is stated in a form that can be true. Re-asserting a repaired absolute is how the same review lands twice.
- Revalidation condition: standing rule; no expiry.

## L-0009 — Cleaning up after a side effect is not the same as not having it
- Status: VERIFIED
- Evidence: ADR-0013. A DENY minted `gnosis/<task>` plus a worktree; the first repair removed them afterwards, which passed review. Codex then noted the branch had still existed and the subprocess had still run — the fix was ordering (`planned_path()`/`planned_branch()` describe the workspace without creating it), not compensation.
- Scope: any gate whose subject needs an identity that seems to require the resource first.
- Lesson: "create, ask, undo on refusal" leaves a window where the forbidden thing existed, and it fails whenever cleanup can fail (which ADR-0007 guarantees it can, since it refuses to force). If a decision needs a name, give it a *planned* name.
- Operational consequence: gates get planned-identity accessors instead of provisioning-then-rollback.
- Revalidation condition: standing rule; no expiry.

## L-0010 — Gate once, and the second attempt runs on the first attempt's authority
- Status: VERIFIED
- Evidence: ADR-0013 Codex finding 2. The verdict was taken before the retry loop; the CLI re-reads its MCP config from disk on every launch, so a config rewritten after approval was consumed with no new decision.
- Scope: any authorization taken outside a loop that launches something inside it.
- Lesson: an approval is for one launch, not for a task. Where the authorized inputs are re-read at launch time (config files, working trees, environment), a single pre-loop verdict is a TOCTOU hole by construction.
- Operational consequence: the gate runs per attempt, and the action identity includes the workspace, so a material change re-escalates instead of riding the earlier decision.
- Revalidation condition: standing rule; no expiry.

## L-0011 — `git status` is a change detector only for files that were clean
- Status: VERIFIED
- Evidence: ADR-0015 self-review, reproduced directly. With `code.py` already modified, a reviewer rewriting it left `git status --porcelain` (" M code.py") and `git diff --stat` ("1 insertion(+), 1 deletion(-)") byte-identical. The rule-9 tamper check saw nothing.
- Scope: any before/after comparison built on porcelain status or diff stat.
- Lesson: status reports a file's *state class*, not its content, and stat reports counts, not bytes. Both are stable across arbitrary edits to an already-dirty file — which during a fix→review cycle is every file that matters.
- Operational consequence: tamper detection uses `content_fingerprint` (hash of the full `git diff HEAD` patch plus each untracked file's bytes). Identity/keying keeps the cheap `workspace_fingerprint`; the two are deliberately different functions with different jobs.
- Revalidation condition: standing rule; no expiry.

## L-0012 — Key a recording on the state the session started from, never on state the recorded actor changes
- Status: VERIFIED
- Evidence: ADR-0014 independent review, finding 1, with a reproduction. The cassette fingerprinted the workspace per call; the recorded agent edits the repository; so call 2's key was derived from call 1's edits, and a replay — which restores stdout but not those edits — computed call 1's key again and missed.
- Scope: any content-addressed record/replay whose key includes ambient state the recorded actor can mutate.
- Lesson: a replay restores what it recorded, and nothing else. Any input to the key that the actor itself moves is unreproducible by construction, so the key must anchor on the session's starting state. This preserves the honest property (a cassette only replays against the tree it was recorded against) while removing the impossible one.
- Operational consequence: `ReplayingCLIRunner` caches one baseline fingerprint per workspace; two tests pin both directions — multi-call replay works, and a different starting tree still misses.
- Revalidation condition: standing rule; no expiry.

## L-0013 — A stand-in that cannot exhibit the failure makes the test a decoration
- Status: VERIFIED
- Evidence: ADR-0014 review. The end-to-end test claimed to prove production wiring, but its fake runner wrote only to stdout paths deliberately placed OUTSIDE the repository — so the one behaviour that broke (an agent mutating the tree between calls) could not occur in the test at all. It passed while the mechanism was broken for its only real user.
- Scope: any test whose double stands in for a component with side effects.
- Lesson: ask what the real component DOES that the double does not, then ask whether the failure being guarded against lives in that gap. A double simpler than the thing it replaces is fine; a double missing the exact behaviour under test is a decoration.
- Operational consequence: doubles for the agent runner mutate the repository (`_MutatingRunner`), because that is what the agent does.
- Revalidation condition: standing rule; no expiry.

## L-0014 — Refusing to read damaged evidence destroys more evidence than it protects
- Status: VERIFIED
- Evidence: ADR-0014 review finding 4, reproduced. The cassette raised on any interior unreadable row. A crash leaves a torn tail; one more append moves that tear off the last line; the next load then refused the entire file, losing every intact fsync'd row — a survivable crash turned into total loss.
- Scope: append-only evidence stores with strict parsing.
- Lesson: strictness has to be aimed at the thing that can produce a WRONG answer, not at the thing that produces a missing one. Skipping an unreadable row can only cause a miss, and a miss already fails closed; refusing the whole file causes certain, total loss. The integrity check that matters is the one on sequence (occurrence contiguity), which still catches a row genuinely lost from the middle.
- Operational consequence: `InteractionStore` skips and reports damaged rows (`store.damaged`) and keeps the contiguity check as the hard error.
- Revalidation condition: standing rule; no expiry.

## L-0015 — An audit wrapper that changes the security decision is worse than no wrapper
- Status: VERIFIED
- Evidence: ADR-0014 review finding 2. Wrapping the CLI runner for record/replay dropped `.binary`, so the policy gate saw `<unknown-runner>` instead of `claude` — a different `action_id`, human approvals silently invalidated, and every rule matching the real program silenced.
- Scope: any decorator placed around a component whose attributes feed a security or identity decision.
- Lesson: "drop-in replacement" is a claim about every attribute the collaborators read, not just the method being wrapped. Observability layers are exactly where this bites, because they are added late and assumed inert.
- Operational consequence: the wrapper passes `binary` through, pinned by a test.
- Revalidation condition: standing rule; no expiry.

## L-0016 — Self-review finds real defects and still misses most of them
- Status: VERIFIED
- Evidence: ADR-0015. Self-review found 3 real defects (one critical). The independent Codex pass over the SAME repaired code then found 8 more, including a rule-9 bypass reachable with nothing but an accent in a filename, and falsified one of the self-review addendum's own claims ("bounded at MAX_AGENT_MESSAGE_CHARS" — the production runner read the whole file first).
- Scope: any unit shipped without independent review.
- Lesson: the ratio is the point. Self-review is not worthless — it caught a critical — and it is not a substitute: an author red-teams the design they already hold in their head, so the misses cluster exactly where their model is wrong. A unit reviewed only by its author should be labelled as such in its ADR, and the label should be treated as a debt, not a footnote.
- Operational consequence: ADRs carry an explicit "Independent review" line; unreviewed units are listed in NEXT_ACTIONS as debt and reviewed as soon as a channel reopens.
- Revalidation condition: standing rule; no expiry.

## L-0017 — A failure recorded as a constant is a blind spot, not a gap
- Status: VERIFIED
- Evidence: ADR-0015 Codex finding 3, reproduced. `content_fingerprint` could not read a C-quoted path (`?? "caf\303\251.txt"`) and stored `unreadable: <errno message>`. That string never changed, so the file it stood for could be rewritten freely while the tamper check compared equal.
- Scope: any fingerprint, hash or comparison that substitutes a placeholder when it cannot read its input.
- Lesson: a placeholder makes the failure *invisible to the comparison*, which is worse than the read failing loudly — the check keeps reporting "unchanged" for exactly the input it cannot see. Either read it properly or make the placeholder itself unstable/fatal.
- Operational consequence: `-z` porcelain removes the quoting entirely; where a read can still fail, the recorded value must carry something that changes (or the probe must fail closed, as `probe_failed` does).
- Revalidation condition: standing rule; no expiry.

## L-0018 — Fail-open is a direction, and it repeats across a whole module
- Status: VERIFIED
- Evidence: ADR-0016 Codex review. Five separate critical findings in one small module, all the same shape: a damaged row read as "no hold"; an under-specified supersede row erasing every hold; a two-row probe transition leaving a durable gap; a PROBE admitting by scheduler id rather than run id; readers not taking the writer's lock. Each was written independently, weeks apart in reasoning, and every one leaned the same way.
- Scope: any module implementing a restriction (holds, gates, quotas, locks).
- Lesson: fail-open is not a bug you fix one at a time — it is an author's default under uncertainty. Every branch that answers "I am not sure" gets resolved toward *proceed*, because proceeding is what the surrounding code is for. The countermeasure is to enumerate the "I am not sure" branches deliberately and check each one's direction, rather than to review them for correctness individually.
- Operational consequence: for restriction mechanisms, tests assert the DENY direction on every degraded input — missing file, torn line, hostile value, partial write — and `test_a_probe_never_leaves_the_credential_open_between_two_rows` walks every byte-prefix of the durable log.
- Revalidation condition: standing rule; no expiry.

## L-0019 — A rule can be satisfied by every part and violated by the composition
- Status: VERIFIED
- Evidence: ADR-0017 self-review, reproduced. The engine classified rate limits and parked (rule 6). The scheduler placed durable holds. The convergence adapters parsed agent output strictly. Compose them and a rate limit hit by a REVIEW round produced unreadable text, which the parser correctly called `InvalidReviewOutput`, which the loop correctly filed as an evidence failure — and no hold was ever placed, so the next round launched into the same shut window. Every part behaved as specified.
- Scope: any rule that holds at a boundary, in a system with more than one boundary.
- Lesson: a per-component invariant does not aggregate. The rule "a rate limit parks" was implemented where launches were known to happen, and the composition created new launch sites whose results nobody classified. The question that finds these is not "does each part obey the rule?" but "enumerate every place the rule's trigger can now occur, and check each one".
- Operational consequence: `GatedAgentRunner` classifies every launch it makes and reports it to the hold plane (`TaskScheduler.observe`), so the trigger is handled wherever a launch happens rather than wherever it happened to be handled first.
- Revalidation condition: standing rule; no expiry.

## L-0020 — A test fixture that takes a shortcut can hide the absence of the rule it should exercise
- Status: VERIFIED
- Evidence: ADR-0017 Codex finding 1. `GovernedPipeline` had no check that the reviewer was independent of the implementer, and every test passed one `_Agent` as both — the exact degenerate case rule 10 forbids. Seventeen tests, all green, none capable of noticing.
- Scope: any fixture that shares one double across roles a rule says must differ.
- Lesson: the shortcut in the fixture WAS the missing requirement, written down in test form. Sharing a double across two roles quietly asserts the roles are interchangeable; if a rule says they are not, the fixture has already contradicted it. This is the same shape as L-0013 (a double that cannot exhibit the failure), one level up: there the double was too simple, here it was too shared.
- Operational consequence: fixtures give separate doubles to roles a rule distinguishes, and the constructor refuses the shared case so a future fixture cannot reintroduce it silently.
- Revalidation condition: standing rule; no expiry.

## L-0021 — Name the thing you are about to write to
- Status: VERIFIED
- Evidence: ADR-0018 Codex finding 1. `WorkIntegrator` merged into whatever ref the source repo had checked out — an operator's feature branch, or a detached HEAD — and reported INTEGRATED either way. Every test passed because every test left the repo on its default branch.
- Scope: any component that writes to a resource it locates implicitly (current branch, current directory, default database, active profile).
- Lesson: "the current X" is an input the caller did not supply and cannot see in the call. It reads as a sensible default and behaves as an unbounded one — the write lands wherever ambient state points, and the success report is indistinguishable from the correct case. Naming the target turns a silent mis-write into a refusal.
- Operational consequence: `target_branch` is fixed at construction, must be a real branch, and must still be the checked-out one at merge time; anything else is `WRONG_TARGET` before a single write.
- Revalidation condition: standing rule; no expiry.

## L-0022 — A gate must see the final state, not the state at the time it was asked
- Status: VERIFIED
- Evidence: ADR-0018 Codex finding 2. The `before_integration` policy snapshot was built from the committed branch diff, and `autosave` then committed the agent's uncommitted files before the merge — so a rule allowing `safe.py` could authorise an action that also landed `restricted.py`.
- Scope: any authorization computed before a step that can still change what is being authorized.
- Lesson: an approval binds an identity, and the identity has to be of the thing that will actually happen. Ordering is part of the security property, not an implementation detail: "gate, then finalise" authorises a draft. The fix was moving the gate after the commit, which is safe precisely because that commit writes only to the task's own branch and is inert if the gate then refuses.
- Operational consequence: the integration gate runs after `autosave`, on the final change set, and a test asserts the snapshot contains the previously-uncommitted paths.
- Revalidation condition: standing rule; no expiry.

## L-0023 — Delegating a guarantee still leaves you the state you kept beside it
- Status: VERIFIED
- Evidence: ADR-0019, findings 1 and 2. `WorkQueue` deliberately delegated OWNERSHIP to the claims plane, which is correct and was the right call. But it kept its own file state (`pending/`, `running/`) alongside, and the lease TTL reclaims a claim without touching files — so a killed worker's brief sat in `running/` with ownership free and the record unreachable, which is the ghost rule 4 forbids. The repair then had to read the claim's OUTCOME, not just its liveness: routing a RESOLVED record back to `pending` would have re-executed finished work.
- Scope: any component that delegates an invariant to another subsystem while keeping derived or parallel state of its own.
- Lesson: delegation moves the decision, not the consequences. The delegated authority answers its own question correctly and knows nothing about the state you kept; the reconciliation between them is yours, and it needs the authority's full answer (status/outcome), not just a boolean "is it still held".
- Operational consequence: `WorkQueue.recover()` reconciles file state against claim status on every worker start (`drain` calls it), and routes by status — RESOLVED to `done/`, anything else to `pending/`.
- Revalidation condition: standing rule; no expiry.

## L-0024 — A budget that resets on resumption is a budget in name only
- Status: VERIFIED
- Evidence: ADR-0019 finding 4. `BudgetLedger` was constructed fresh inside each `run_brief`, so a parked brief that was released and re-claimed started from zero launches. Repeating park/resume launched agents without limit while every individual invocation looked correctly bounded — and the module docstring said "tracks one brief's spend" when it tracked one invocation.
- Scope: any circuit breaker whose counter lives in memory while the thing it bounds can be resumed.
- Lesson: the unit a limit is expressed in must match the unit it is stored in. "Per brief" written in the docstring and "per invocation" in the constructor is not a naming slip — it is the whole mechanism, and the resumable path is exactly where it fails while looking healthy.
- Operational consequence: `BudgetStore` keeps the running total durably, keyed by brief id, and `ledger_for` seeds a resumed run with what the brief already spent.
- Revalidation condition: standing rule; no expiry.

## L-0025 — Bound the loop where the loop is, not where the cost is
- Status: VERIFIED
- Evidence: ADR-0019 finding 6. `drain` re-offers a released brief immediately, and the ADR claimed `Budget` was the bound on that. It is not: parking launches nothing and spends nothing, so a caller that parks every time spins forever with a perfectly healthy budget.
- Scope: any retry/re-offer loop justified by a limit that counts something the loop does not consume.
- Lesson: check what the loop actually spends. A limit on money does not bound a loop that is free; rule 8 lists max attempts SEPARATELY from wall-time and budget for exactly this reason, and the separation is not redundancy.
- Operational consequence: `WorkQueue` carries `max_attempts`, durable on the record, and an exhausted brief is reported in `skipped` rather than silently passed over forever.
- Revalidation condition: standing rule; no expiry.

## L-0026 — A mechanism can be structurally unable to answer its own question
- Status: VERIFIED
- Evidence: ADR-0020 Codex finding 1. `WorkIntegrator.preview` returned the SOURCE repo's current head as a task's `base_sha`, so `base_sha == head` was true by construction. The whole ordering mechanism exists to detect "the target moved since this was reviewed", and through its own data path that condition could never be true. Every unit test passed because they fed the planner synthetic bases and never went through `preview`.
- Scope: any predicate computed from a value the caller also supplies as the comparison target.
- Lesson: testing the pure function proves the logic and proves nothing about whether the inputs can ever take the shape the logic distinguishes. The question to ask of a new predicate is not "does it compute correctly" but "can the real data path produce both answers" — and the way to find out is one end-to-end test through the real reader, not more cases fed by hand.
- Operational consequence: `preview` reports `git merge-base <head> <branch>`, and a test drives the whole path (fork, advance the branch, plan) asserting STALE_BASE actually fires.
- Revalidation condition: standing rule; no expiry.

## L-0027 — Convergence is two pieces of evidence and only one of them survives a base move
- Status: VERIFIED
- Evidence: ADR-0020. "Converged" means deterministic verification passed AND an independent review passed (ADR-0008). Integration re-runs the verification on the merged tree; nothing re-runs the review. So after the target moves, half the guarantee is re-established and half is assumed — and nothing said so until this milestone.
- Scope: any composite guarantee whose parts have different lifetimes.
- Lesson: when a claim is a conjunction, ask what invalidates each half separately. A review is evidence about a specific tree, so it expires when the tree changes; a test run can be repeated, so it does not. Treating the conjunction as one durable fact keeps the weaker half alive past its evidence.
- Operational consequence: `review_still_applies` on every planned landing; the coordinator refuses a stale-review landing by default, and the pipeline routes landings through it.
- Revalidation condition: standing rule; no expiry.

## L-0028 — A safety check whose default is "off" is a hole with documentation
- Status: VERIFIED
- Evidence: ADR-0021 Codex finding 1. Re-review was gated by `require_rereview: bool = False` on `WorkIntegrator.integrate`, so the public API's default landed an expired review in silence. Every direct caller was one forgotten argument away from the exact failure the milestone existed to close, and the coordinator's correctness depended on it never forgetting.
- Scope: any protective condition expressed as a caller-supplied flag.
- Lesson: if the component can DERIVE the condition, it must — a flag makes the safe behaviour opt-in and distributes the obligation to every call site, where it will eventually be missed. The integrator knew the task's fork point and the target's head all along; asking the caller was a design choice, not a necessity. Callers should only be able to WAIVE, explicitly, which is a decision that leaves a trace.
- Operational consequence: `integrate` computes staleness itself; the parameter is `waive_stale_review` and defaults to False.
- Revalidation condition: standing rule; no expiry.

## L-0029 — Mutating shared state to carry per-call context crosses identities
- Status: VERIFIED
- Evidence: ADR-0021, found by self-review. The pipeline set `integrator.re_reviewer` once, guarded by `is None`. The reviewer closure captures `task_id` for its policy snapshot and its evidence directory — so after the first task, every later re-review would have been gated and recorded under the FIRST task's name.
- Scope: any per-call collaborator assigned onto a longer-lived object.
- Lesson: the assignment looks like configuration and behaves like a cache of the first caller. When the thing being assigned closes over per-call identity, sharing it silently reattributes work — and attribution is what a governance record is FOR, so the failure is invisible in behaviour and total in the audit trail.
- Operational consequence: the reviewer is passed per call (`integrate(..., re_reviewer=...)`), and the coordinator holds a FACTORY keyed by task rather than an instance.
- Revalidation condition: standing rule; no expiry.

## L-0030 — A transition that is two writes has a gap, and the gap reverses decisions
- Status: VERIFIED
- Evidence: ADR-0022 self-review finding 1, reproduced directly before the fix. `WorkQueue.block` released the claim and then moved the file; a crash between them left the record in `running/` with no live claim, and `recover()` — routing on claim status alone — returned it to `pending`. The decision that a human must look at the brief was erased by the mechanism whose job is not losing things. `release` lost its `not_before` the same way, falsifying "backoff is durable" precisely when the system was least healthy.
- Scope: any state change split across two stores — a plane call plus a file move, a database write plus a queue publish, a claim plus a ledger entry.
- Lesson: recovery routing on the OTHER store's status can only reconstruct what happened TO the record, never what the worker DECIDED. Stamp the intent on the record before the first call: then a crash leaves recovery finishing the decision rather than overruling it. The stamp must clear itself on arrival, or a later revival carries a marker from a past life and the next crash acts on a reason that expired.
- Operational consequence: `pending_transition` written by `_stamp` before every plane call; `recover()` routes on it first; `_move` and `requeue` clear it.
- Revalidation condition: standing rule; no expiry.

## L-0031 — An invalid output coerced into a valid one is an unbounded loop wearing a bound's clothes
- Status: VERIFIED
- Evidence: ADR-0022 self-review finding 3. The supervisor dispatched COMPLETED, then BLOCK, then `else: park`. A handler with a bare `return` — the commonest handler bug there is — returned `None`, landed in `else`, and became an indefinite pacing loop that read from the outside exactly like a system correctly waiting on a shut window. Rule 8 asks for an invalid-output limit; the code had a default branch instead.
- Scope: any dispatch whose final branch is an `else` rather than a rejection; any runtime handling of a value whose type annotation is a promise the runtime cannot enforce.
- Lesson: the dangerous default is the one that resembles healthy behaviour. A malformed output is not a quiet vote for the last option — its outcome is as unknown as an exception and deserves the same treatment. Two corollaries: check with `isinstance`, not equality, when the enum is a `str` enum (the string "PARK" compares equal to a member); and type the incoming value as `object`, because annotating it as the promised type makes the guard read as dead code and invites its deletion.
- Operational consequence: `StopReason.INVALID_OUTPUT`; a non-`Disposition` blocks the brief.
- Revalidation condition: standing rule; no expiry.
