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
