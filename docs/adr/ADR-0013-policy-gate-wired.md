# ADR-0013 — The policy engine gates a real intervention point (adapter milestone, 1/4)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_engine.py::TestPolicyGate` (27 tests),
  `tests/test_director_orchestrator.py::TestPolicyGatedOrchestrator`
  (6 tests); suite 488/488; mypy strict clean; ruff clean on every file
  this ADR touches. **Dual adversarial review, and both rounds found the
  headline invariant false** — see the two addenda below.
- Builds on: ADR-0011 (the engine), ADR-0009 (worktree-scoped execution),
  ADR-0012 (typed failures).

## Context

ADR-0011 delivered a fail-closed policy engine and said plainly that it
was not wired to anything. Directive 9's review then established the
rule the hard way: **a mechanism nothing calls is a parallel fiction**.
Of the four unwired mechanisms, the policy engine was the one whose
absence is a *security* gap rather than a dormant capability, so it goes
first.

## Decision

`TaskEngine.execute_task(policy=, approvals=, policy_actor=)` consults
the policy engine at a declared intervention point, `before_agent_run`,
**before any process that could act on the repository or on the agent's
behalf**. The exact wording matters: two successive reviews falsified
the stronger phrasing this ADR used to carry (see both addenda), and the
kernel legitimately runs read-only `git` probes first because computing
the identity of the action being judged is part of judging it.

The point is evaluated **at every stage that changes the action**, and
every verdict is recorded:

- `stage="pre_context"`, before anything reads the repository and before
  the worktree is minted;
- `stage="final_prompt"`, after kernel-generated context has been
  prepended, because the prompt that actually runs is not the prompt the
  first verdict judged;
- `stage="attempt_N"`, before each retry, because a retry is a fresh
  launch and the MCP config and the workspace can both have changed
  since the first verdict.

### What the rules actually see

`agent_run_intent()` builds the structured intent explicitly rather than
parsing the CLI argv: the prompt is an argv operand, and running a whole
prompt through the path resolver would produce nonsense paths and an
unbounded snapshot. Rules get the binary, the flags, the **MCP config
paths as resolved operands** (they decide which tools the agent can
reach), and `cwd` = the task's worktree. The prompt is identified by
`prompt_sha256` in the payload — which still binds an approval to the
exact prompt without inlining it.

### What each verdict does

- `ALLOW` / `WARN`: the run proceeds, and the verdict is appended to the
  run's ledger as `policy.decision`. An allowed action is evidence too,
  not just a refused one.
- `DENY` / `ESCALATE` (unapproved) / `TRANSFORM`: no child is ever
  launched. `TRANSFORM` is refused here deliberately — this intervention
  point has no way to rewrite an agent invocation, and a gate that
  silently ignores a mitigation it cannot apply is worse than one that
  stops.
- An `ESCALATE` becomes `ALLOW` only with an approval bound to the exact
  `action_id`; changing the prompt changes the identity, so an approval
  never transfers (pinned by test).

### A refusal is durable evidence

`_refused_outcome` opens a run, records `policy.decision` and a
classification carrying the **policy's own reason code**, marks the run
`CANCELLED` (it never started, and `PENDING → FAILED` is not a legal
transition) and reports `ESCALATION_REQUIRED`. A denial that
left no trace would be indistinguishable from a task nobody attempted —
and the reason code flowing into the taxonomy is exactly the Directive 9
contract, now composing across both units.

### A refusal leaves no workspace behind

This took two rounds. Self-review first found a `DENY` still minting
`gnosis/<task_id>` and a worktree, and fixed it by *cleaning up* after
the refusal. Codex then pointed out that cleaning up after a side effect
is not the same as not having it: `git worktree add` had already run, a
branch had already existed, and on a denied action neither should ever
have happened.

So the ordering changed instead. The first verdict now precedes creation
entirely — rules are told where the agent *would* run via
`planned_path()` and `planned_branch()`, which create nothing. Cleanup
survives for the later stages, where a refusal genuinely can arrive
after the workspace exists, and it removes **only a workspace this call
created**: a reattached worktree may hold a previous attempt's work.
Cleanup stays best-effort — a refusal that cannot tidy up is still a
refusal, and forcing removal is what ADR-0007 forbids.

### Reachable from the entry point briefs actually travel through

`DirectorOrchestrator(policy=, approvals=, policy_actor=)` threads the
gate into `_execute_brief`, so a refusal becomes a durable
`ESCALATED` brief record plus a file in `escalations/`. Gating only the
kernel primitive would have reproduced the exact failure Directive 9
named. An `ApprovalStore` passed without a `PolicyEngine` is refused at
construction: it reads as governed, authorises nothing, and would let
everything through.

### Opt-in at this milestone, but never silent

A run without a `policy` behaves exactly as before, because no default
rule set exists yet; making the gate mandatory belongs with the
rule-authoring work. Two things keep "opt-in" from meaning "invisible":
an ungoverned run appends `policy.ungoverned` to its own ledger, so an
auditor can prove which runs had no verdict; and
`DirectorOrchestrator(require_policy=True)` refuses at construction, so
an operator can have fail-closed today. The enforcement matrix carries
the honest level: `policy/agent_launch_gate = PROMPT_ONLY`.

## Known limitations (stated, not implied)

- Only ONE intervention point is gated: launching an agent. The tool
  calls that agent then makes are not gated — that needs the sandbox
  boundary, and the enforcement matrix already records
  `shared_repo_isolation` as `SANDBOX_APPROX`, not `HARD`.
- `permission_mode` and `model` are still the engine's defaults rather
  than caller-threaded, though rules now see their **values**
  (`--permission-mode=plan`, not a bare flag name) — which is the part
  that matters, since gating a launch without knowing whether it runs in
  `plan` or `bypassPermissions` gates nothing.
- The remaining three adapter-milestone wirings (`InteractionStore` into
  the CLI runner, `ConvergenceLoop` onto real reviewers, holds under a
  scheduler) are untouched here.

## Workflow review addendum (2026-08-20)

A multi-agent review (three lenses + refutation) returned 21 findings
against the first version of this ADR and its code. The verify phase
died on quota, so each raw finding was adjudicated by hand against the
source. The headline result is that **the ADR's central invariant was
false as written**.

1. *(critical)* "No child exists before the verdict" was **not true**:
   `_gather_code_intelligence_context` runs ~120 lines earlier and
   *shells out* — a denied action had already launched kernel
   subprocesses against the repository. The gate now runs first
   (`stage="pre_context"`), and the prompt is re-judged after context is
   prepended (`stage="final_prompt"`). Pinned by
   `test_no_child_runs_before_the_verdict_including_code_intelligence`,
   which asserts the provider recorded **zero** calls.
2. *(critical)* **No production path could enable the gate.**
   `DirectorOrchestrator` never accepted or forwarded `policy`, so every
   real brief ran ungated. This is Directive 9's lesson repeating itself
   one ADR later — fixed by wiring, not by documenting.
3. *(major)* A refused run was written as `RunState.FAILED` from
   `PENDING`, which the state machine does not permit; and an
   **unapproved `ESCALATE` was terminal `FAILED`**, when "approve, then
   resubmit" is precisely not terminal. Now `CANCELLED` +
   `TaskState.ESCALATED`.
4. *(major)* Rule-supplied `detail` was merged over the kernel's fields,
   so a rule could set `action_id` and forge the identity an operator
   thinks they are approving. The kernel's `action_id` is now written
   **last**, and rule detail is sanitised (a non-serialisable detail
   degrades to `_unencodable_detail` instead of killing the refusal
   path — `decide()` goes to lengths to be total, and the refusal that
   records it must be too).
5. *(major)* MCP configs were bound **by path only**, so an approval
   survived a rewrite of the very file that decides which tools the agent
   can reach. Each config is now fingerprinted by content hash.
6. *(major)* Flags reached the rules as bare names, so no rule could
   distinguish `--permission-mode=plan` from `bypassPermissions`.
7. *(major)* Engine faults and rule-set gaps were classified
   `FAIL_POLICY`, i.e. as the agent misbehaving. `is_runtime_error` now
   maps to `FAIL_INFRA` and `is_policy_gap` to `NEEDS_HUMAN` — and
   writing the test for it surfaced a **second, pre-existing** defect:
   `NEEDS_HUMAN` was not in `_NON_PENALIZING`, so a hole in the
   operator's rule set counted against agent quality. It is a routing
   verdict, never a judgement; fixed in `failures.py`.
8. *(minor)* `TRANSFORM` refusal and `intent.cwd` were asserted in prose
   only. Both are pinned by tests now.

**Refuted, with the assumption recorded:** findings that the gate should
also cover `resume`, that the worktree cleanup should be forced, and
that `policy_actor` should default to the process identity. The first
two contradict ADR-0007; the third would attribute an approval to the
kernel rather than to the worker it was granted to.

## Codex review addendum (2026-08-20, independent, post-repair)

`codex exec --sandbox read-only --json` over the repaired gate returned
**FAIL, 7 findings**. Transcript:
`.gnosis/lab/kernel-reviews/codex-review-2026-08-20-policy-gate.jsonl`.
Five were reproducible defects; two were true statements about design
that the honest response is to *record*, not to pretend away.

1. *(critical, repaired)* **The headline invariant was false a second
   time.** The previous review moved the gate ahead of code intelligence;
   Codex found the gate still ran after `worktrees.create()`, and `git
   worktree add` is a child process that creates a branch and a
   directory. A DENIED governed action therefore still mutated the
   repository. Creation now happens *after* the verdict, and rules are
   told where the agent would run via `planned_path()` /
   `planned_branch()`. Pinned by a test asserting no branch and no
   directory exist after a DENY.
2. *(major, repaired)* **Only the first attempt was gated.** The verdict
   was taken once before the retry loop, so attempt 2 launched under
   attempt 1's authorization — and since the CLI re-reads its MCP config
   from disk, a config rewritten after the approval was consumed
   ungated. Every attempt now re-gates (`stage="attempt_N"`), and a
   refusal mid-retry exits as a refusal rather than as an agent failure.
3. *(major, repaired)* **The identity did not bind the workspace.** Same
   prompt, same paths, same actor ⇒ same `action_id`, even after HEAD
   moved. An approval for "run the migration" survived the tree changing
   underneath it. The snapshot now carries
   `workspace_fingerprint()` — HEAD, branch, and a hash of the dirty
   state. Consequence, stated deliberately: an escalation approved
   against one tree state does **not** carry to another, including a
   retry after an attempt modified the tree. That is the correct
   semantics for a human-approved action, and it is why the fingerprint
   is content rather than a path.
4. *(major, repaired)* **Only the last verdict was recorded.** The
   pre-context and final-prompt verdicts shared one slot, so what was
   authorized *before* repository-derived context existed was never
   auditable. All verdicts are appended now.
5. *(major, repaired)* **A refusal could die on its own evidence.**
   `_safe_detail` called `repr()` outside the protective `try`, so a
   rule detail whose `__repr__` raises killed the refusal path — the one
   path that exists to keep refusals alive. It is total now. The
   orchestrator also caught only an enumerated tuple of exceptions,
   leaving an already-consumed brief stranded `IN_PROGRESS`; it now
   records any failure as a visible `FAILED` brief carrying the
   exception type, and report/escalation files are written atomically so
   a poller never reads half a refusal.
6. *(major, recorded not repaired)* **The launch gate is opt-in**, so a
   default-constructed engine or orchestrator launches agents with no
   verdict. Making it mandatory needs a default rule set that does not
   exist yet. Two things changed instead: an ungoverned run appends
   `policy.ungoverned` to its own ledger, so silence is no longer
   indistinguishable from "nothing was asked"; and
   `DirectorOrchestrator(require_policy=True)` gives an operator
   fail-closed today. The matrix now carries
   `policy/agent_launch_gate = PROMPT_ONLY`.
7. *(major, recorded not repaired)* **Rules are not sandboxed.** A rule
   body is in-process operator code and can spawn a process or write the
   repository before returning its verdict. Python cannot enforce purity,
   and pretending otherwise is what the enforcement matrix exists to
   prevent: `policy/rule_purity = IGNORED`, with the note that the rule
   set is trusted configuration at kernel privilege.

**The invariant, restated precisely** — because "no child process at
all" has now been falsified twice and a claim that keeps being wrong
should stop being made: *no process that could act on the repository or
on the agent's behalf runs before the verdict.* The kernel does run
read-only `git` probes first, because computing the identity of the
action being judged is part of judging it. That is stated here rather
than discovered by a third reviewer.

## Repository-wide lint note

Earlier ADRs' "ruff clean" claims were scoped to the files under review.
A repo-wide run with this ruff version's broader default rule set
reports 20 findings in files untouched by this work (`TRY004`,
`BLE001`, `PLW1510`, `UP046/47` and similar). They are pre-existing, not
regressions, and are recorded here rather than silently absorbed into a
"clean" claim. Every file this ADR touches is clean.

## Test-suite note

One intermittent failure was observed in
`test_autosave_refuses_each_sequencer_state_individually` during a full
run, not reproducible in five subsequent runs (3/3 isolated, 2/2 full).
Its shape — creating and deleting marker files inside `.git` on Windows
while git reads them — matches the L-0002 timing class. Recorded rather
than dismissed; if it recurs it gets chased properly.
