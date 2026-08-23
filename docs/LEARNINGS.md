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

## L-0032 — A green test over an interleaving that never happened is worse than no test
- Status: VERIFIED
- Evidence: ADR-0023 self-review finding 5. A threaded test asserted that six racing schedulers produce exactly one probe. It passed — and it still passed with the single-winner guard mutated away, because `probe_is_due` refused the second caller long before the contested append. The race the test was named after never occurred in any run.
- Scope: any concurrency test; any test of a guard that sits behind an earlier, cheaper check.
- Lesson: threads plus a barrier do not create contention, they create the OPPORTUNITY for it. If an earlier check can short-circuit the callers, they never reach the step under test and the assertion passes for the wrong reason. Drive the contended step directly: let every caller pass the earlier check BEFORE the barrier, then race only on the step whose property is claimed. And prove it by mutation — a concurrency test that survives deleting the mechanism it tests is documentation, not evidence.
- Operational consequence: `test_racing_claims_produce_exactly_one_probe` plus a deterministic `test_a_caller_past_the_due_check_is_still_refused_by_the_claim`; both fail when the guard is removed.
- Revalidation condition: standing rule; no expiry.

## L-0033 — Fixing "nothing calls it" by adding a caller nothing reaches
- Status: VERIFIED
- Evidence: ADR-0023 self-review finding 1. `probe()` had no caller, so one was wired into `TaskScheduler.submit()` — which nothing in the pipeline uses. Agents are launched through `GatedAgentRunner`, which gates on `admits()` directly. The repair would have been the original defect wearing the repair's clothes: a second mechanism, correct in isolation, sitting on a path no production caller takes.
- Scope: any "wire this up" task; any protocol with more than one implementation of the calling side.
- Lesson: before adding a caller, find out who consumes the thing TODAY — grep the interface, not the implementation. A gate has as many entry points as there are callers of its protocol, and adding capability to one of them fixes exactly that one. The test that closes it must live where the real path is, not where the mechanism is.
- Operational consequence: `claim_probe` is on the `HoldGate` protocol; the gated runner claims a probe per LAUNCH, not per task or stage.
- Revalidation condition: standing rule; no expiry.

## L-0034 — Ask whether the mechanism CAN exist before designing how it should behave
- Status: VERIFIED
- Evidence: ADR-0024. Before designing rotation I checked the launch path and found `subprocess.Popen(argv, cwd=..., stdout=..., stderr=...)` — no `env`. The child inherited the parent environment, so no launch could run as a different identity under any design. Everything above it — pool, ordering, holds per credential, provenance — would have been a decision plane with nothing underneath.
- Scope: any feature whose value depends on an effect at a boundary the code does not yet cross (a subprocess, a network call, a filesystem the tool owns).
- Lesson: the first question is not "how should this behave" but "can the effect happen at all, and how would I know". Design started at the top would have produced a complete, tested, reviewable mechanism whose every assertion passed and whose child process authenticated as somebody else. The check costs one grep of the launch site.
- Operational consequence: `env` threaded through `CLIRunner`, `ClaudeCLIRunner`, `TaskEngine.execute_task` and `_execute_guarded`; `Credential.environment` raises rather than returning the ambient set.
- Revalidation condition: standing rule; no expiry.

## L-0035 — Enforcing a boundary against the kernel is not enforcing it against the agent
- Status: VERIFIED
- Evidence: ADR-0024 self-review finding 2. Rotation bound the selected credential into the child's environment and left every OTHER credential's source variable in place. `CredentialPool.select` refused to cross into a metered key — while the child launched on a subscription seat could read `METERED_TOKEN` out of its own environment and spend it directly. Every test of the boundary passed.
- Scope: any policy whose subject is an agent or a child process rather than the code that decides.
- Lesson: ask who the rule is ABOUT. A rule about spending is about the party that can spend, and a gate the kernel obeys while the agent retains the capability is a gate against the wrong party — an agent does not have to defeat the check, only to ignore it. Least privilege (rule 13) is what closes it: the child receives the identity it was given and nothing else, so the boundary holds even against a child that never consults it.
- Operational consequence: `CredentialPool.launch_environment` strips every pool source variable before binding the chosen credential.
- Revalidation condition: standing rule; no expiry.

## L-0036 — A mechanism nobody calls can be one level BELOW the one you checked
- Status: VERIFIED
- Evidence: ADR-0022 addendum finding 1. `WorkQueue.recover()` had production callers, was tested, and was cited in two ADRs as the crash-recovery story. It asks the claims plane whether a claim is still ACTIVE — and `WorkAuthority.sweep()`, the only thing that ages a dead worker's claim OUT of ACTIVE, had no caller anywhere in `src/`. Every test of the path swept by hand, so the suite was green over a mechanism nothing invoked. A killed worker's brief stayed ACTIVE for ever and sat in `running/` where no scan looks: the exact ghost rule 4 forbids.
- Scope: any recovery, expiry, GC or reconciliation story that depends on a second mechanism changing state in the background.
- Lesson: checking that YOUR mechanism has a caller is not enough — check that everything it depends on to change state does too. The tell is a test that sets up the precondition by hand: if the suite has to call `sweep()` itself for `recover()` to do anything, then in production nothing calls `sweep()`. Treat "the test arranges the precondition" as the question "who arranges it in production?", and answer it with a grep rather than an assumption.
- Operational consequence: `WorkerSupervisor.run()` sweeps before recovering; the ordering is documented as the recovery story rather than a detail.
- Revalidation condition: standing rule; no expiry.

## L-0037 — A safety mechanism whose failure mode is MORE open than its absence is worse than absent
- Status: VERIFIED
- Evidence: ADR-0023 addendum finding 1. The probe narrowed an estimated ACCOUNT hold to a one-run PROBE lease, and the `narrow` row DESTROYED the row it replaced. When the probing run died, the lease expired into nothing: no hold, every queued run admitted, and no second probe possible because `probe_is_due` needs an ACCOUNT hold to narrow. Without the probe the credential would have stayed shut until its window ended.
- Scope: any mechanism that takes custody of protective state — a lease over a lock, a narrowing over a hold, a transaction over a guard.
- Lesson: ask what the state is when the mechanism FAILS, not only when it succeeds, and compare it against not having the mechanism at all. If the answer is "more permissive", the design is inverted regardless of how well the happy path reads. Custody must be suspension, not replacement: keep the thing you covered so it governs again when you let go. The ADR had this as a Known limitation — described optimistically as "two launches may overlap" — so the gap was not unknown, it was understated, and an understated gap survives review as easily as a hidden one.
- Operational consequence: a `narrow` row suspends; `HoldRegistry.reconcile` lets a live PROBE govern and the suspended hold govern again on expiry.
- Revalidation condition: standing rule; no expiry.

## L-0038 — An identity is only unforgeable if it is unguessable
- Status: VERIFIED
- Evidence: ADR-0023 addendum finding 5. Probe admission rested entirely on matching `probe_holder`, and the holder was the task id — or `task:stage:1`. Any process holding the task id could assert it, and asserting it WAS the admission. The ADR argued "a claim any caller could make was the original defect; an exact identity is not that", which is true only while the identity cannot be constructed by the caller.
- Scope: any capability, lease, token or admission keyed on a string the holder is told to present.
- Lesson: an exact-match check converts a guessable name into a bearer token. Either the name must be unguessable, or admission must require proving you won the allocation. Deriving the identity from data the caller already has (a task id, a stage, a counter) fails both. Minting a secret inside the allocation and returning it keeps attribution — prefix with the caller's name — while making the win the only way to hold it.
- Operational consequence: `claim_probe` mints `f"{run_id}:{secrets.token_hex(8)}"` and returns it; callers use the returned holder, never the name they passed.
- Revalidation condition: standing rule; no expiry.

## L-0039 — A wrapper that duck-types an interface will silently drop what you add to it
- Status: VERIFIED
- Evidence: ADR-0024 addendum finding 1. `env` was threaded through `CLIRunner`, `ClaudeCLIRunner`, `TaskEngine.execute_task` and `_execute_guarded`, and `ReplayingCLIRunner` — which duck-types the same `run()` — accepted the parameter and did not pass it on. RECORD is its default mode, so a cassette miss ran a real child that spent a real credential as the ambient identity while the audit trail recorded the credential the kernel had chosen. mypy cannot see it: the wrapper's signature is compatible, it just forgets.
- Scope: any parameter added to an interface with more than one implementation, especially security state (an identity, a token, a sandbox flag, a timeout).
- Lesson: adding a parameter to a protocol is not the change — forwarding it in every implementation is. Enumerate the implementations by grepping for the method name, not the class, and add a test that asserts each one forwards. A wrapper that accepts and drops is worse than one that raises, because the caller's decision is recorded as having taken effect.
- Operational consequence: `ReplayingCLIRunner.live()` forwards `env`; a pipeline test asserts a recording runner reaches the child with the binding and keeps the secret out of the cassette.
- Revalidation condition: standing rule; no expiry.

## L-0040 — Enforce a rule against the party the rule is about
- Status: VERIFIED
- Evidence: ADR-0024 addendum finding 5, extending L-0035. `CredentialPool.select` refused to cross into a metered key without authorisation, and `launch_environment` stripped the pool's declared source variables — but an operator's AMBIENT `ANTHROPIC_API_KEY`, declared by no credential, stayed in the environment of a child launched on a subscription seat. The agent did not need to defeat the check; it could ignore it and read the key.
- Scope: any policy whose subject is an agent, a child process or a user rather than the code that decides.
- Lesson: after building the decision, ask what CAPABILITY the subject retains. A decision plane that the subject can route around is documentation. And a deny-list is not deny-by-default: closing the names you thought of leaves the ones you did not, so the honest move is to close what you can, say it is a list rather than a boundary, and record the level accordingly.
- Operational consequence: `SENSITIVE_ENVIRONMENT_VARIABLES` is stripped from every bound launch; `credentials/ambient_isolation` is declared SANDBOX_APPROX, not HARD.
- Revalidation condition: standing rule; no expiry.

## L-0041 — Self-review finds about a quarter of what an independent pass finds
- Status: VERIFIED
- Evidence: measured on three consecutive units. Self-review claimed 3, 6 and 5 defects (14 total). Independent review of the same three units found 19, 13 and 15 (47), including six criticals none of the self-reviews saw — and two of the criticals were MISDESCRIPTIONS inside the self-reviews' own output, where the gap had been noticed and stated optimistically. Consistent with L-0016, which measured 3 found against 8 missed on ADR-0015.
- Scope: any decision about whether to ship a unit without an independent verdict.
- Lesson: self-review is worth doing and is not a substitute; the ratio is roughly one in four and the miss is concentrated in exactly the claims the author is most confident about. When the usual reviewer is unavailable, a same-family agent in a clean context still found six criticals — a weaker channel is not the same as no channel, and shipping unreviewed should be the last option rather than the first fallback. Record which channel reviewed, because the strength of the claim depends on it.
- Operational consequence: ADR-0022/0023/0024 carry addenda naming the channel and separating repaired findings from still-open ones.
- Revalidation condition: re-measure when a Codex review runs against a unit that also had a same-family review.

## L-0042 — An atomic move proves the file was there, not that it was the same file
- Status: VERIFIED
- Evidence: ADR-0022 addendum. `recover()` raced `claim()`, and the first repair was to move the record with `path.replace` — the single-winner the claim path already used. A concurrency test written for that fix found something worse: recovery had listed `running/`, read the record and decided, and by the time it moved, a different worker had recovered the SAME brief, claimed it, and re-created a file at that exact path. `replace` succeeded, because a file was there. It was somebody else's live work, and the move left an ACTIVE grant over a record sitting in `pending/` for anyone to take.
- Scope: any compare-and-set built on a filesystem path, a key name, or any other stable address rather than on the value at it.
- Lesson: `replace`/`rename` is atomic about the OPERATION, not about identity. It answers "was something here?" and the question was "is this still the thing I read?". Where the address can be recycled by a legitimate actor, a move is not a CAS: the guard must be a lock held across read-decide-write, or a version compared at mutation time — the shape `ClaimStore.reclaim_if` already uses in this kernel.
- Operational consequence: `WorkQueue` serialises `recover()` and `claim()` on one lock, taken before the claims plane so the ordering is fixed. The evidence is a mutual-exclusion test; the multi-threaded one passes with the lock removed and is labelled a smoke test (L-0032).
- Revalidation condition: standing rule; no expiry.

## L-0043 — A rule conditioned on a mode is switched off in every other mode
- Scope: any invariant whose enforcement sits inside `if <some mode is enabled>`.
- What happened: "no DONE without evidence" was enforced inside `if authority is not None`. An earlier independent review had found the INVALID DONE defect correctly, and the repair was attached to the branch the reviewer was looking at. The ungoverned branch — the default of the production entry point — kept `... if verification_result else True`, which reads "nobody checked" as "it passed".
- Why a green suite never showed it: every test that exercised the gate was a GOVERNED test. The ungoverned tests asserted COMPLETED and got COMPLETED, so they CONFIRMED the defect instead of exposing it. A fixture that expects the wrong answer is worse than a missing test, because it looks like coverage.
- Lesson: when a repair is placed inside a conditional, ask what the OTHER branch now guarantees. If the answer is "less", the rule was not repaired, it was scoped. Put the invariant at the lowest point that can authorise the outcome, give it a NAME and its own tests — the defect here was one word inside an expression — and let the modes above it be convenience rather than enforcement.
- Related: L-0035 (enforce a rule against the party it is about), L-0033 (fixing "nothing calls it" with a caller nothing reaches), L-0039 (a declared return type is not a runtime guarantee), L-0013 (a fixture incapable of exhibiting the failure).

## L-0044 — Check a superlative against the thing it names, not against the path you built
- Scope: any claim of the form "X is the only / the single / the lowest thing that can produce Y".
- What happened: ADR-0025 called `completion_is_evidenced` "the single authority for `TaskState.COMPLETED`". I verified it by grepping `TaskState.COMPLETED` across `src/`, finding one transition site, and confirming that site called the predicate. That proves something strictly narrower than the sentence: it proves the CURRENT PRODUCTION CALLER is guarded. The sentence named the state machine, and the state machine was never asked. An independent reviewer asked it in four lines — `CREATED -> PLANNED -> IN_PROGRESS -> VERIFYING -> COMPLETED` on a bare `TaskStateMachine` — and got COMPLETED with no evidence anywhere.
- The tell I walked past: `tests/test_state_machine.py::test_happy_path` ended with `sm.transition(TaskState.COMPLETED)` and ASSERTED it worked. A test that agrees with the defect is not missing coverage; it is coverage pointing the wrong way, and it sat in the file whose whole subject is the contract I was claiming.
- Lesson: to check "X is the only route to Y", do not enumerate the callers you know about. Go to the object that PRODUCES Y and try to produce it without X. If the attempt succeeds, the claim describes your callers rather than the system. Grep finds the callers that exist; the invariant exists for the caller somebody writes tomorrow, and grep cannot find that one.
- Corollary for documents: a superlative in an ADR is a testable assertion. Write the falsifier before writing the sentence, or write a weaker sentence.
- Related: L-0043 (a rule conditioned on a mode is off in every other mode), L-0033 (fixing "nothing calls it" with a caller nothing reaches), L-0032 (a green test over an interleaving that never happened), L-0016 / L-0041 (self-review finds about one in four).

## L-0045 — A guard on the methods is not a guarantee while the field is public
- Scope: any invariant implemented as a check inside the methods that mutate a piece of state.
- What happened: three rounds of hardening went into `TaskStateMachine` — the constructor refuses to start in COMPLETED, `transition()` refuses every evidence-gated target, `complete()` re-examines the `VerificationResult` it is handed. A second independent review then wrote `sm.state = TaskState.COMPLETED` and got a terminal COMPLETED with `completion_evidence` still `None`. Every door was locked and the wall was missing.
- Why the previous round missed it: L-0044 had just taught "go to the object that PRODUCES the outcome and try to produce it without X". I applied that to the METHODS, enumerating the routes I could name, and the destination itself was never asked. The reviewer did not need a route; they assigned the field.
- Lesson: after guarding the operations, ask what else can reach the same storage. If the answer is "a plain attribute", the guard is a convention. Make the storage private and expose it read-only, so the guarded methods are not merely the recommended route but the only one the public API offers.
- The honest limit, which must be written down at the same time: this buys a property of the PUBLIC API, not tamper-proofing. `_state`, `object.__setattr__` and `__dict__` still work; Python offers no way to stop them worth the cost, and claiming otherwise would be the same overclaim the previous round had to retract. The threat closed is the accidental one — an agent, a refactor, a caller taking the cheap route — not an adversary already executing in the process.
- Related: L-0044 (check a superlative against the thing it names), L-0043 (a rule conditioned on a mode is off in every other mode), L-0046.
- Revalidation condition: standing rule; no expiry.

## L-0046 — A report is a claim; an invariant the printer does not share is broken at the page
- Scope: any invariant whose subject is also rendered for a human — reports, ledgers, dashboards, CLI summaries.
- What happened: the state authority correctly REFUSED a `VerificationResult(passed=1)` — `passed is True` is False for `1`, so the task went to FAILED. The engine's report then rendered the same object with `"PASSED" if verification_result.passed else "FAILED"` and printed `verification=("malformed: PASSED",)`, with `problems_encountered=()` because `not 1` is False. The gate held and the page lied. The ledger recorded `to_dict()` verbatim, so the audit trail said `passed: 1` too.
- Why a green suite never showed it: the gate is right, so every test OF the gate passes. The contradiction only exists between two components, and nothing tested the pair. It survived a full suite, a captured mutation check and one independent review.
- Root cause, stated generally: **two independent readings of one field.** The predicate asked `passed is True`; the printer asked `if passed`. Nothing forced them to agree, and for every ordinary bool they did — which is exactly why the disagreement was invisible.
- Lesson: give the field ONE reader and derive every consumer from it. Where a value can be malformed, that reader needs a third answer — PASSED / FAILED / MALFORMED — because collapsing "states no verdict" into either of the other two invents a verdict nobody gave. To an operator the two mistakes are not interchangeable: one says debug your code, the other says debug your verifier.
- Corollary: rejecting evidence is not a licence to discard it. Keep the rejected object, quarantined under its own key, so the audit trail stays complete without a reader scanning for `passed` picking up the `1`.
- Related: L-0043 (enforced where the decision is made, not where it is published), L-0039 (a declared type is not a runtime guarantee), L-0045.
- Revalidation condition: standing rule; no expiry.

## L-0047 — An aggregator launders evidence when its carrier is narrower than its verdict
- Scope: any component that reads N judgements and emits one — composites, roll-ups, health summaries, quorum readers, CI status aggregators.
- What happened: L-0046 gave `passed` a single reader with three answers (PASSED / FAILED / MALFORMED) and every consumer derived its answer from it. A third independent review then ran `CompositeVerifier("composite", [child_with_passed_1])` and got `VerificationResult(passed=True)`. Every strict reader downstream was CORRECT — the composite really was a well-formed passing result. The malformed child had been erased one frame earlier by `all(r.passed for r in results)`, and `CompositeVerifier("empty", [])` passed on `all([]) is True` without running anything.
- Root cause, stated generally: **the verdict had three states and the carrier had two.** A `VerificationResult.passed: bool` cannot express "a member stated no verdict", so the aggregator's only options were to lie in one direction or the other. Truthiness picked the worse one. Giving the field one reader does not help if the aggregator must then re-encode that reader's answer into a field that cannot hold it.
- Why the previous round missed it: round 2 wrote "`CompositeVerifier` is safe by accident: `all()` returns a real bool". That is a statement about the RETURN TYPE, checked by reading the signature, and it is true. The question that mattered was what `all()` consumes, and one line of code would have falsified the reassurance.
- Lesson: when a tri-state judgement must survive aggregation, the aggregate needs a representation for every state — as a distinct TYPE where possible, so the classifier rejects it by construction rather than by anyone remembering to check. Widen the producer's declared return type at the same time: the type error is what enumerates the consumers, and enumerating them by hand is what missed three of them twice.
- Corollary: `all([])` is `True`. Any "everything passed" over a possibly-empty collection asserts success from nothing; validate non-emptiness where the collection is accepted, not where it is read.
- Related: L-0046 (one reader, three answers), L-0039 (a declared type is not a runtime guarantee), L-0045 (a guard on the methods with the field left public), L-0048.
- Revalidation condition: standing rule; no expiry.

## L-0048 — A named finding that is deferred is a finding that recurs, and an unverified reassurance is worse than silence
- Scope: any review addendum that lists known-unrepaired defects, and any sentence of the form "X is safe because Y".
- What happened: round 2's addendum named three surviving truthy readers of `passed` (`convergence.py`, `integration.py`, `cli_review.py`), classified them honestly as "a candidate finding for the next review", and reassured the reader that `CompositeVerifier` was "safe by accident". Round 3 came back on exactly those four things. The reassurance was false and the three named readers were still live; the ADR had converted a defect into a sentence and then treated the sentence as a mitigation.
- What was right about it: naming them beat hiding them. The reviewer found them faster BECAUSE they were listed. The failure is not the honesty, it is the shape of what follows — a named defect with no owner, no bound and no test is documentation of a hole, not a closure of one.
- Lesson: when scope forces a defect to be left in place, write the FALSIFIER before the reassurance. Either add a test that fails today and is marked as expected-red, or state the exposure as a live claim ("a `passed` of `1` reaching this line lands a merged tree") rather than as a reassurance ("this cannot forge a DONE"). Never write "safe because <property of the type>" without running the case; the type is what you read, and the value is what arrives.
- Corollary for scope discipline: "repair this closure and start nothing else" is a correct instruction and it does not make the deferred items safe. The right artifact for a deferred defect is a ticket with a reproduction, not a paragraph.
- Related: L-0047 (the aggregator that laundered them), L-0044 (check a superlative against the thing it names), L-0016 / L-0041 (self-review finds about one in four).
- Revalidation condition: standing rule; no expiry.

## L-0049 — A name is not a content: an identity built from states and paths re-derives its claims from the thing it was supposed to prove
- Scope: any evidence, cache key, approval binding, audit record or "did this change?" check built on `git status`, file names, timestamps, sizes or diff stats.
- What happened: `capture_evidence.py` recorded HEAD and `git status --porcelain` and called the result evidence. Status prints `XY <path>`. Two different dirty trees that modify the same files produce a byte-identical bundle, and `git diff --stat` gives identical counts for any same-length edit. The bundle cited as proof of "760 tests passing" ran against a dirty tree at `92fe18ab`; the bytes it tested are unrecoverable from it. The same blindness had already been found twice in this repo — in the policy-approval key and in the rule-9 reviewer check — and `content_fingerprint()` was written to fix it. The evidence surface never adopted it.
- Root cause, stated generally: **an identity made of metadata answers "which files" and the question was "which bytes".** Every consumer then has to corroborate the evidence with something outside it — in this case the commit — which inverts what evidence is for.
- Lesson: when an artifact exists to prove a state, its identity must be content-addressed and must be part of the artifact. And check the repo before inventing one: the second and third occurrences of this bug were reachable by grep from the first.
- Corollary about workarounds: all four ADR-0025 rounds wrote an external `tree-binding.json` by hand around the broken script. A workaround performed once is pragmatism; performed four times it is the finding, and the fourth repetition is late to notice.
- Related: L-0011 (status is blind to content in the rule-9 check), L-0046, L-0047.
- Revalidation condition: standing rule; no expiry.

## L-0050 — An instrument that writes into what it measures reports on itself
- Scope: evidence capture, profilers, snapshot tools, audit writers, anything that records a system into a location the system contains.
- What happened: making the capture take a before/after fingerprint immediately exposed a second defect that the weaker check had hidden: `.gnosis/evidence/` is tracked, so a bundle written in place is an untracked change inside the tree the post fingerprint is about to read. Every capture would have reported that the tree moved, and would have been right about itself.
- Root cause, stated generally: **the measurement was inside the measured set.** A weak check tolerates that because it cannot see the artifact; a strong check cannot, and the failure looks like a false positive when it is the tool telling the truth about its own footprint.
- Lesson: build the artifact outside the observed boundary and move it in afterwards, with the boundary crossing named in the artifact itself (`covers`, here) rather than left for a reviewer to infer. Where the crossing cannot be avoided, state it; do not narrow the check until the artifact stops showing up.
- Corollary: a test that stages the bundle INSIDE the repository and asserts the capture invalidates itself is what keeps this from being re-broken by someone tidying the temp directory away.
- Related: L-0049, L-0011.
- Revalidation condition: standing rule; no expiry.

## L-0051 — Equality at two instants is not stability across the interval between them
- Scope: any before/after check used to license a claim about what happened in between — evidence capture, sandbox verification, "did the reviewer touch anything", cache validation, optimistic concurrency on content rather than on a version counter.
- What happened: ADR-0026 replaced a name-based identity with a content fingerprint taken before and after the checks, and called two equal fingerprints proof that the tree had not changed. An independent review wrote a check that modified a covered file, READ the modified bytes, then restored the bytes, the size and the timestamps. Both fingerprints matched, `evidence_valid` said true, and the suite had demonstrably run against different bytes for part of the interval. The 36 tests all passed and none of them could have failed: every mutation they made was still present at the second fingerprint, so all of them were caught by the endpoint comparison and none exercised change -> read -> restore.
- Root cause, stated generally: **an endpoint comparison is a sample, and a transient change lives between samples.** This is the ABA problem, and the standard answers apply: either make the window unobservable-by-construction (the mutation cannot happen), or observe the transitions rather than the states. Adding a third sample, shortening the interval, or reading `mtime` narrows the window without closing it, and produces a check that is wrong less often, which is worse than one that is wrong visibly.
- Lesson: when a claim is about an interval, the authority has to be a record of the interval. Where the platform can stream the transitions, stream them — and treat a stream that could have dropped anything (an overflowed queue, an undelivered tail, no mechanism at all) exactly as loudly as a detected violation, because "I saw nothing" and "I could not see" are different answers and only the first licenses the claim.
- Corollary on tails: proving delivery with a delay is a timer, and a timer is the thing being replaced. Write a barrier into the stream and wait to OBSERVE it; ordered delivery then does the proving.
- Corollary on false positives: the way to stop legitimate writes from tripping the mechanism is to redirect them out of the observed set, not to forgive them inside it. Every path left on the allow-list is a path an attacker may use, so the list should be short enough to read in one breath.
- Related: L-0049 (a name is not a content — the same surface, one level up), L-0046, L-0047.
- Revalidation condition: standing rule; no expiry.

## L-0052 — A mechanism that reports events cannot be a boundary when an event can decline to be reported
- Scope: any control built on notifications, hooks, audit streams or callbacks — filesystem watchers, syscall auditing, ORM change events, CDC pipelines, webhook-based reconciliation.
- What happened: L-0051 replaced an endpoint comparison with a write stream, and a barrier made the stream's delivery provable. An independent review then pointed at the other half of the sentence: the barrier proves that notifications the OS GENERATED were delivered, not that every modification generated one. Windows documents size and last-write notifications as detected when a change reaches storage or the cache, and modifications through a memory-mapped section as weaker still. Both reproductions were built before touching the design. A raw buffered write with the handle held open across the whole capture DID notify — the mechanism held. A write through a writable mapping notified nothing at all: the check read the mutated bytes, both fingerprints matched, and the bundle certified itself.
- Root cause, stated generally: **the authority was an observation channel, and a channel's completeness is a property of the platform, not of the code.** Proving that a channel was fully drained says nothing about what was put into it. Every "watch for X" control has this shape, and the question to ask of it is not "can I miss a message?" but "can the event happen without a message existing?"
- Lesson: where an event can occur without a notification, do not watch for it — make it impossible. Prevention and observation then partition the problem by failure mode rather than by convenience: prevention for the operations whose notification can be withheld, observation for the operations whose notification cannot (on this platform, directory-entry changes: create, delete, rename). Each half covers exactly the other's blind spot, and saying which half covers what is part of the design, not a footnote.
- Corollary on repairs: the tempting fixes here were a settle delay, a forced flush, or an exception for mapped files. All three treat the instance and leave the category, and the third would have documented the hole as a feature. When a reproduction shows the authority is the wrong KIND of thing, changing the authority is cheaper than defending it.
- Corollary on prevention: if the boundary cannot be established — here, a covered input another process already holds open for writing — refuse to run at all. A partially protected input set is not a protected one, and finding out after a nineteen-minute suite is worse than finding out in six seconds.
- Related: L-0051 (the interval, not the endpoints), L-0049, L-0050.
- Revalidation condition: standing rule. The platform-specific half — which operations notify reliably — must be re-measured, not assumed, on any new OS or filesystem.
