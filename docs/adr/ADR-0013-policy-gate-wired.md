# ADR-0013 — The policy engine gates a real intervention point (adapter milestone, 1/4)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_engine.py::TestPolicyGate` (11 tests); suite
  451/451; mypy strict clean; ruff clean.
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
the policy engine at a declared intervention point,
`before_agent_run`, **before any repository-writing child exists**.

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
`FAIL_POLICY` classification carrying the **policy's own reason code**,
marks the run FAILED and reports `ESCALATION_REQUIRED`. A denial that
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

### Opt-in at this milestone

A run without a `policy` behaves exactly as before. The gate is not yet
mandatory because no default rule set exists; making it mandatory is the
right end state and belongs with the rule-authoring work.

## Known limitations (stated, not implied)

- Only ONE intervention point is gated: launching an agent. The tool
  calls that agent then makes are not gated — that needs the sandbox
  boundary, and the enforcement matrix already records
  `shared_repo_isolation` as `SANDBOX_APPROX`, not `HARD`.
- `permission_mode` and `model` are passed as the engine's defaults
  rather than threaded from the caller, so a rule cannot yet
  differentiate them. Threading them is trivial and belongs with the
  first real rule set that needs it.
- The remaining three adapter-milestone wirings (`InteractionStore` into
  the CLI runner, `ConvergenceLoop` onto real reviewers, holds under a
  scheduler) are untouched here.

## Test-suite note

One intermittent failure was observed in
`test_autosave_refuses_each_sequencer_state_individually` during a full
run, not reproducible in five subsequent runs (3/3 isolated, 2/2 full).
Its shape — creating and deleting marker files inside `.git` on Windows
while git reads them — matches the L-0002 timing class. Recorded rather
than dismissed; if it recurs it gets chased properly.
