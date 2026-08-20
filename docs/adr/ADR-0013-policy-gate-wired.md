# ADR-0013 — The policy engine gates a real intervention point (adapter milestone, 1/4)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_engine.py::TestPolicyGate` (18 tests),
  `tests/test_director_orchestrator.py::TestPolicyGatedOrchestrator`
  (3 tests); suite 462/462; mypy strict clean; ruff clean on every file
  this ADR touches. See the workflow addendum below — the first version
  of this ADR was reviewed and several of its claims were false.
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
**before any child process exists at all** — see addendum finding 1 for
why that phrasing is deliberately stronger than the original.

The point is evaluated **twice**, and both verdicts are recorded:

- `stage="pre_context"`, before anything reads the repository;
- `stage="final_prompt"`, after kernel-generated context has been
  prepended, because the prompt that actually runs is not the prompt the
  first verdict judged.

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

### A refusal undoes the workspace it minted

Self-review found the gate leaving its own side effect: a `DENY` still
minted `gnosis/<task_id>` and a worktree, because the kernel creates the
workspace before asking (rules are told where the agent *would* run,
which needs the real path). Verified, then fixed — a refusal now removes
the workspace through ADR-0007's provenance-gated `remove()`, and **only
one this call created**: a reattached worktree may hold a previous
attempt's work, so it is never touched. Cleanup is best-effort; a
refusal that cannot tidy up is still a refusal, and forcing removal is
what ADR-0007 forbids.

### Reachable from the entry point briefs actually travel through

`DirectorOrchestrator(policy=, approvals=, policy_actor=)` threads the
gate into `_execute_brief`, so a refusal becomes a durable
`ESCALATED` brief record plus a file in `escalations/`. Gating only the
kernel primitive would have reproduced the exact failure Directive 9
named. An `ApprovalStore` passed without a `PolicyEngine` is refused at
construction: it reads as governed, authorises nothing, and would let
everything through.

### Opt-in at this milestone

A run without a `policy` behaves exactly as before. The gate is not yet
mandatory because no default rule set exists; making it mandatory is the
right end state and belongs with the rule-authoring work.

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
