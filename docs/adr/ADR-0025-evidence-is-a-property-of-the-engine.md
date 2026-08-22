# ADR-0025 — No DONE without evidence is a property of the engine, not of governed runs

- Status: ACCEPTED
- Date: 2026-08-22
- Repairs: **F-34** (`docs/V1_TRACEABILITY_AUDIT.md`), the one finding the
  earlier independent reviews did not have.
- Evidence: `.gnosis/evidence/20260822T005432Z/` — **781 passed** (12 subtests), mypy strict
  clean over 55 files, ruff at the 19-finding baseline exactly. Captured
  against a CLEAN code tree at commit `29d3666`, tree
  `cf7a26577c4d1bdeca7829c0d83d330dbf0f65b6`; `f34-tree-binding.json` in
  that bundle records `content_fingerprint()` before and after the run
  and asserts `git status --porcelain -- src tests scripts pyproject.toml`
  was empty at both ends. Mutation transcript: `mutation-check.f34.txt`
  in the same bundle.
- Tests: `tests/test_no_invalid_done.py` (21 tests, 9 subtests), plus
  `tests/test_engine.py::TestTaskEngineWorkAuthority::test_verifier_required_with_authority`
  (rewritten) and
  `tests/test_director_orchestrator.py::TestGovernedOrchestrator::test_governed_failure_fails_the_brief_without_aborting_the_batch`
  (provocation replaced).
- Independent review: **DONE 2026-08-22 by Codex, verdict FAIL PARCIAL.**
  The reachable production defect was genuinely closed; the claim that
  the invariant lived at the lowest point that authorises COMPLETED was
  false, and is corrected below. See the addendum, and commit `6c4859a`
  for the repair. The first version of this ADR shipped self-reviewed and
  said so; L-0041 puts that channel at roughly one finding in four, and
  this is what the missing three-quarters looks like.
- Scope: **F-34 only.** Of the 43 items in the frozen audit, 6 are PASS
  (F-06, F-09, F-11, F-29b, F-41, F-42) and 36 remain open and untouched.
  Nothing here closes any of them.

## Context

The constitution's second rule is absolute: *no Task reaches `DONE`
without evidence.* The engine appeared to enforce it. It did not.

The check lived inside a conditional:

```python
if authority is not None:
    if not worker_id:
        raise ValueError(...)
    if verifier is None:
        raise ValueError("a WorkAuthority-governed task requires a verifier: ...")
```

and the transition read:

```python
verification_passed = verification_result.passed if verification_result else True
task_sm.transition(TaskState.COMPLETED if verification_passed else TaskState.FAILED)
```

Two facts turn that into a reachable defect rather than a stylistic one.

**First**, `DirectorOrchestrator` — the entry point D-018 designates as
*"the path real briefs travel"* — defaults `authority` to `None` and
`run_pending(verifier=...)` to `None`. It has a `require_policy` opt-in
for the policy gate and had no equivalent for evidence.

**Second**, `... else True` does not mean "no verifier configured". It
means **absence of evidence is success**. A brief whose agent exited 0
became `TaskState.COMPLETED` → `ReportStatus.COMPLETED` →
`BriefRecordState.COMPLETED`, with `verification` reading "No verifier
supplied." — a DONE whose own report states that nothing was checked.

The failure is reproducible in four lines:

```python
DirectorOrchestrator(director_root, run_store, repo_path).run_pending()
# CLI exits 0 -> verification_passed = True -> COMPLETED, nothing proved
```

This is the project's own recurring shape at a new level. L-0035 says
enforce a rule against the party the rule is *about*; here the rule was
enforced against a *mode*, so it was simply off in the other mode. The
previous fix (a Codex INVALID DONE finding) had correctly identified that
a bare exit code is not evidence — and then attached the remedy to the
governed branch, where the reviewer happened to be looking.

## Decision

### The predicate is the authority, and it has a name

```python
def completion_is_evidenced(verification: VerificationResult | None) -> bool:
    return isinstance(verification, VerificationResult) and verification.passed is True
```

`kernel/engine.py` transitions to `TaskState.COMPLETED` in exactly one
place, and that place now calls this. Three refusals, each load-bearing:

- **`None`** — the regression itself. Nobody checked is not a pass.
- **Anything that is not a `VerificationResult`** — `Verifier` is an ABC,
  but duck-typing costs nothing and mypy cannot see past a declared
  return type (L-0039). A stand-in that answers `None`, or a string, must
  not be able to mint a DONE the kernel cannot read.
- **A `passed` that is not exactly `True`** — `bool` IS an `int` in
  Python. `failures.py` already had to learn this for exit codes; the
  flag that closes a task deserves the same care.

Naming it is not decoration. The defect was **one word inside an
expression**. A named predicate with its own tests makes restoring that
word a visible edit to a documented invariant rather than a diff nobody
reads twice.

### The refusal moved to the first statement of `execute_task`

Unconditional, and before anything is spent: no claim acquired, no
worktree minted, no policy verdict consumed, and above all **no agent
launched**. Refusing there is free. Refusing after the child has run
costs a launch and leaves a half-finished task somebody has to recover.

`verifier` also lost its default. `verifier: Verifier` with no `= None`
makes mypy name every omission at the call site instead of letting it
surface later as a green run that proved nothing. The runtime `None`
check remains for callers that arrive through `**kwargs` (the scheduler
does), where the type checker cannot help.

### The Director refuses before consuming work

`run_pending` resolves `verifier or self.verifier` and raises if both are
absent — **before** `list_pending()`, so no brief is claimed out of the
inbox, no `BriefRecord` is created and nothing has to be recovered. A
`verifier` may now also be given at construction, so an operator can
configure evidence once rather than remembering it per call.

This is **defence in depth, not the guarantee**. If a future caller
bypasses the orchestrator entirely, the engine still refuses.

> **CORRECTED 2026-08-22.** This section originally continued: *"the
> guarantee lives at the lowest point that can authorise a DONE. It does
> — in `completion_is_evidenced`."* That was false when it was written.
> `completion_is_evidenced` was a function the ENGINE called;
> `TaskStateMachine.transition()` still walked `VERIFYING -> COMPLETED`
> for any caller at all. The guarantee lived one level above the thing
> that produces the outcome. See the addendum.

### A verifier that answers nothing is recorded, not coerced

`evidence_missing` distinguishes "the check failed" from "no check was
produced". The first is evidence and its stderr excerpt is worth
reporting; the second is the absence of evidence, and the report says so
in those words. The ledger gets a `task.verification_result` event either
way, so a run that produced nothing is auditable rather than silent —
the same rule `ConvergenceLoop` applies to an unreadable review.

## Consequences

### Accepted

**Every caller must now supply a verifier.** Fifty test call sites and
one production path were updated. That is the cost of the parameter
having lied, and it is paid once. The fixtures were given a **real**
check — `CommandVerifier` spawning a child process and reading the exit
code the OS reports — not a stub that returns `passed=True` without
looking, which is the fixture mistake L-0013 was earned on.

**Two tests were rewritten rather than adjusted**, because their
provocation was the defect:

- `test_verifier_required_with_authority` asserted the governed-only
  refusal. It now pins the unconditional refusal *and* that nothing was
  claimed or leased before it fired.
- `test_governed_failure_fails_the_brief_without_aborting_the_batch`
  provoked a mid-batch engine exception by withholding a verifier. That
  route no longer reaches the engine, so the provocation moved to another
  precondition of the same class — a `WorktreeManager` rooted on a
  different repository than the brief names. The behaviour under test is
  unchanged.

Neither was weakened to keep an unsafe path green (rule 28).

### Not fixed here, and stated rather than implied

- `GovernedPipeline` is unchanged: it already required a verifier at
  construction and derives COMPLETED from `ConvergenceOutcome.CONVERGED`,
  which is verification **and** an independent review. It also remains
  **inert** — F-33, still open.
- `RunState.SUCCEEDED` still means only "the child exited 0". That is the
  correct meaning for a *run*, and nothing today reads it as a task
  completion — but anything that started to would be wrong, and no
  mechanism prevents it.
- The **quality** of the evidence is the operator's. The kernel now
  guarantees that a check ran and passed; it does not and cannot
  guarantee the check was worth running. A `CommandVerifier` wrapping
  `true` satisfies this gate. That is the honest boundary, and it is why
  F-36 (`ProofPacket`: acceptance criteria mapped to evidence) matters
  and stays open.
- No enforcement-matrix row changed. The matrix describes adapter
  restrictions; "no DONE without evidence" is a kernel invariant, and it
  belongs in the invariant suite that F-13 says does not yet exist.

## Mutation check, with the artifact captured

Open finding 15 says a mutation check that leaves no captured output is
testimony, not evidence. So the mutant was run and recorded:
`completion_is_evidenced` was replaced with the exact regression,
`return verification.passed if verification else True`. Result: **11
failures across all three heights** — the predicate, the engine and the
Director entry point — then restored and re-verified green. The captured
transcript is beside the evidence bundle as
`mutation-check.f34.txt`.

## Files

- `src/gnosis/kernel/engine.py` — `completion_is_evidenced`,
  `NO_EVIDENCE_PROBLEM`, the unconditional entry refusal, the required
  `verifier` parameter, the single guarded transition.
- `src/gnosis/director/orchestrator.py` — constructor `verifier`,
  `run_pending` refusing before consumption.
- `tests/test_no_invalid_done.py` — new.
- `tests/test_engine.py`, `tests/test_director_orchestrator.py`,
  `tests/test_replay_runner.py`, `tests/test_scheduler.py` — fixtures
  supply real verification.

---

## Independent review addendum — Codex, 2026-08-22: **FAIL PARCIAL**

The first version of this ADR shipped self-reviewed and said so. Direction
ran an independent Codex review over the synchronised folder and it
returned **FAIL PARCIAL**: the concrete F-34 route was closed and the
suite passed, but the order had required the invariant at the **lowest
point that authorises COMPLETED**, and this ADR had not put it there.

### The finding, reproduced

```python
sm = TaskStateMachine()
sm.transition(TaskState.PLANNED)
sm.transition(TaskState.IN_PROGRESS)
sm.transition(TaskState.VERIFYING)
sm.transition(TaskState.COMPLETED)     # -> COMPLETED, no evidence anywhere
```

`TASK_TRANSITIONS` listed `VERIFYING -> COMPLETED` and `transition()`
walked it for anyone who asked. `completion_is_evidenced` was therefore
never "the single authority for `TaskState.COMPLETED`" as the section
above claimed — it was the guard that **the current production caller
happened to carry**. Every sentence in this ADR asserting otherwise was
an overdeclaration, and the V1 matrix inherited it.

Worse, the suite AGREED with the defect:
`tests/test_state_machine.py::TestTaskStateMachine::test_happy_path`
ended with `sm.transition(TaskState.COMPLETED)` and asserted it worked.
A test that asserts the wrong answer is not missing coverage; it is
coverage pointing the wrong way, and it is why a green run said nothing
about this.

### What the review did NOT overturn

The reachable production defect was genuinely closed and stayed closed:
`TaskEngine.execute_task` still refuses a verifier-less task before it
launches anything, `DirectorOrchestrator.run_pending` still refuses
before consuming a brief, and every F-34 test still passes. The verdict
was PARTIAL for exactly that reason.

### The repair (commit `6c4859a`)

The invariant is now a property of `kernel/state_machine.py`:

- **`EVIDENCE_GATED_STATES`** — today `{COMPLETED}`. `transition()`
  refuses every target in it, raising `UnevidencedCompletionError`.
  `FAILED` and `CANCELLED` stay open on purpose: nobody has an incentive
  to forge a task that did not finish.
- **`complete(verification)`** is the only route to COMPLETED, and it
  takes the `VerificationResult` **itself, never a boolean**. A flag
  computed by the caller moves the decision back to the caller, which is
  precisely the arrangement that just failed. The object is re-examined
  by `completion_is_evidenced`, so a caller that miscomputed — or never
  computed — is refused rather than believed.
- **Evidence authorises the claim, not skipping the graph.**
  `complete()` still consults `TASK_TRANSITIONS`, so a passing result
  cannot carry a task that never verified into COMPLETED.
- **A machine cannot be CONSTRUCTED in COMPLETED.** Without this the
  guarantee carries an asterisk, and an unwritten asterisk is what this
  whole unit is repairing.
- **`completion_is_evidenced` moved** from `engine.py` to
  `state_machine.py`, beside the authority that applies it, and is
  re-exported so existing imports keep working. The engine now ASKS and
  handles the refusal; it no longer decides.
- **`UnevidencedCompletionError` subclasses `IllegalTransitionError`**,
  so anything already catching illegal transitions keeps failing closed,
  and it carries the same `allowed next:` tail (Directive 3).

Two tests changed rather than being adjusted around:
`test_happy_path` now goes through the only door there is, and
`test_illegal_transition_error_carries_allowed_next` uses an edge that is
illegal for GRAPH reasons, because COMPLETED is now refused for EVIDENCE
reasons before the table is consulted — a different verdict that has its
own test.

### Mutation check

Two mutants, both captured in `mutation-check.f34.txt`:

| Mutant | Result |
|---|---|
| Remove the `EVIDENCE_GATED_STATES` guard from `transition()` | **4 tests red** |
| Restore `return verification.passed if verification else True` | **23 tests red** |

### What this correction says about the process

The claim "the single authority" was checked against the path I had
written, not against the object the sentence named. That is L-0044, and
it is the second time in two units that a superlative in a document was
weaker than the code under it. The self-review channel did not catch it;
an independent reviewer reproduced it in four lines.
