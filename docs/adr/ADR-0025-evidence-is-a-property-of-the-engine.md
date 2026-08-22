# ADR-0025 — No DONE without evidence is a property of the engine, not of governed runs

- Status: ACCEPTED
- Date: 2026-08-22
- Repairs: **F-34** (`docs/V1_TRACEABILITY_AUDIT.md`), the one finding the
  earlier independent reviews did not have.
- Evidence, round 3 (this unit): `.gnosis/evidence/20260822T162729Z/` —
  **822 passed** (60 subtests), mypy strict clean over 55 files, ruff at
  the 19-finding baseline exactly (0 added). Captured against a CLEAN
  code tree at commit `1591aa7`, tree
  `67d2bb9cecb4fbe3764e765d87252f35845eb125`;
  `f34-round2-tree-binding.json` records `content_fingerprint()` around
  the run and asserts `git status --porcelain -- src tests scripts
  pyproject.toml` was empty at both ends. Mutation transcript:
  `mutation-check.f34-round2.txt`; the two reproductions replayed against
  the repaired tree: `reproduction-replay.f34-round2.txt`.
- Evidence, round 1: `.gnosis/evidence/20260822T005432Z/` — **781 passed** (12 subtests), mypy strict
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
- Independent review: **TWO rounds, both FAIL PARCIAL.**
  Round 1 (Codex, 2026-08-22) found the invariant was a property of one
  caller rather than of the state authority; repaired in `6c4859a`.
  Round 2 (2026-08-22) found the repaired authority still had a public
  `state` attribute, and the engine's REPORT still printing a pass for
  evidence the authority had rejected; repaired in this unit. Both
  addenda are below. A **third** independent review is outstanding: this
  unit is delivered for it, not declared closed by it. The first version
  of this ADR shipped self-reviewed and said so; L-0041 puts that channel
  at roughly one finding in four, and two consecutive PARTIALs on the same
  unit are what the missing three-quarters looks like.
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

---

## Second independent review addendum — 2026-08-22: **FAIL PARCIAL**

The repair in `6c4859a` was re-reviewed independently and returned FAIL
PARCIAL again. `transition()` and `complete()` held: neither can be made
to produce an unevidenced COMPLETED. Two defects of the SAME closure
survived, and they are worth reading together, because they are the same
mistake at two altitudes — **the repair was made where the check is, not
where the outcome is produced or where it is reported.**

### Finding 1 — a gate on the doors, with the field left public

```python
sm = TaskStateMachine(TaskState.VERIFYING)
sm.state = TaskState.COMPLETED
```

Terminal COMPLETED. `completion_evidence` still `None`. No exception, no
ledger entry, nothing to audit. Three rounds of hardening had gone into
the constructor, `transition()` and `complete()` — and the attribute they
all guard was a plain public field that anybody could assign.

`completion_evidence` was writable the same way, in both directions: a
task that never earned a DONE could be handed evidence, and a task that
did could be stripped of it, leaving a COMPLETED that cannot say what
proved it.

**Repair.** `_state` and `_completion_evidence` are the storage; `state`
and `completion_evidence` are read-only properties with no setter. Only
`transition()` and `complete()` write. `RunStateMachine` got the same
treatment — no run state is evidence-gated, so that is consistency rather
than a second gate, but "the state of a state machine is not publicly
writable" should be a property of the module and not of whichever class a
reviewer happened to probe.

**The guarantee, stated with its limits.** What is now guaranteed is a
property of the PUBLIC API: no sequence of public attribute assignments
and public method calls reaches COMPLETED without a passing
`VerificationResult`. It is **not** tamper-proofing. `sm._state = ...`,
`object.__setattr__`, `sm.__dict__` and monkeypatching all still work, and
Python offers no way to stop them worth the cost. The threat this closes
is the realistic one — an agent, a refactor, or a caller taking the cheap
route by accident. An adversary executing inside the process has already
won for reasons no property decorator addresses. The module docstring and
the tests both say this in those words; asserting more would be the same
overclaim this ADR has now had to retract twice.

### Finding 2 — the gate refused the evidence and the report printed it as a pass

With a `VerificationResult(passed=1)`:

```text
TaskState.FAILED
ReportStatus.PARTIAL
verification=("malformed: PASSED",)
problems_encountered=()
```

Every line of that is defensible on its own and together they are a lie.
The authority did its job — `passed is True` is False for `1`, so the task
did NOT complete. Then the report, reading the same field with
`"PASSED" if verification_result.passed else "FAILED"`, printed a pass for
the evidence the kernel had just thrown out, and the problems list was
empty because `not 1` is False. A human reading that report sees a suite
that passed, a partial result, and no problems. The ledger recorded
`to_dict()` verbatim, so the audit trail said `passed: 1` too.

Rule 2 is about what a task may CLAIM, and **a report is a claim.** An
invariant enforced at the gate and contradicted at the printer is worse
than one enforced nowhere, because the contradiction is invisible: the
gate is right, so the tests of the gate are green.

**Root cause: two independent readings of one field.** The predicate
asked `passed is True`. The report asked `if passed`. Nothing forced them
to agree, and for every ordinary bool they did — which is why this
survived a suite, a mutation check and a review.

**Repair: one reader, three answers.**

```python
def verification_verdict(result: object) -> VerificationVerdict:  # PASSED | FAILED | MALFORMED
```

`MALFORMED` is the value that was missing. A verification attempt has
three outcomes, not two: it passed, it failed, or it produced something
that states no verdict at all. Collapsing the third into either of the
others invents a verdict nobody gave — and the two mistakes are not
symmetrical to an operator, who needs to know whether to debug their code
or their verifier.

- `completion_is_evidenced` is now *defined as* `verdict is PASSED`, so
  the predicate and the report cannot drift apart by construction.
- `TaskEngine` computes the verdict once and DERIVES the ledger entry,
  the report's verification lines and the problems list from it.
- A rejected result is reported as `"<name>: REJECTED — invalid evidence,
  no verdict recorded"` plus the reason. The word the reproduction
  printed does not appear anywhere in the report, and a test asserts that
  over the whole report, not just the field.
- The ledger records `passed: false`, `verdict: "MALFORMED"` and the
  explanation at the top level, with the rejected object preserved
  verbatim under `rejected_result`. Rejecting evidence is not a licence to
  discard it; what must not happen is a reader scanning for `passed` and
  finding the `1`.
- `passed=0` is treated the same way. A falsy non-bool says no more than a
  truthy one, so reporting it as FAILED would invent a verdict too.
- `director/pipeline.py::_verification_line` carried the identical
  `'PASS' if result.passed else 'FAIL'` and now reads the shared verdict.
  Same finding, second report surface — not a new one.

`VerificationResult` was deliberately NOT given constructor validation
that rejects a non-bool `passed`. It would close the shape at the source,
and it would also make the reproduction unconstructible, delete two
existing tests that the review required be preserved, and turn a
deserialised ledger row into an exception at read time instead of a
classifiable MALFORMED. The rendering layer has to be correct regardless;
that is where the fix belongs.

### Mutation check

Six mutants, each restoring exactly one half of the repair, captured in
`.gnosis/evidence/20260822T162729Z/mutation-check.f34-round2.txt`. Targeted suite:
`tests/test_state_machine.py` + `tests/test_no_invalid_done.py`, baseline
71 passed / 57 subtests.

| Mutant | Result |
|---|---|
| M1 `state` is a writable attribute again (the literal reproduction) | **10 red** |
| M2 `completion_evidence` is writable again | **2 red** |
| M3 the report reads `passed` for truthiness again | **3 red** |
| M4 the ledger records the rejected result verbatim again | **3 red** |
| M5 the problems list says nothing about rejected evidence | **1 red** |
| M6 the shared verdict itself reads truthiness | **20 red** |

None survived; the tree was restored and re-verified green.

### Evidence

`.gnosis/evidence/20260822T162729Z/` — **822 passed, 60 subtests** (up from 800/27), mypy strict
clean over 55 source files, ruff at **19 findings against a baseline of
19**: this unit added no lint debt. Captured against a clean tree at
`1591aa7` (tree `67d2bb9c`), with `f34-round2-tree-binding.json`
recording the fingerprint around the run. Both reproductions from the
review were replayed against the repaired tree and the transcript is in
the bundle: the assignment raises `AttributeError` and leaves the machine
in VERIFYING with no evidence, and the `passed=1` engine run reports
`REJECTED — invalid evidence, no verdict recorded` with a populated
problems list and a ledger entry marked `MALFORMED`.

The pre-run half of the binding was recorded seconds AFTER
`capture_evidence.py` was launched rather than strictly before it. The
capture writes only into its own bundle directory and the suite runs in
temporary directories, so nothing under the code paths could have moved
in that window — but the ordering is stated in the JSON rather than
implied, because the whole subject of this ADR is claims that were
checked against something narrower than the sentence.

### Not repaired here, and named rather than implied

The same truthy read of `passed` remains in three places this unit did
not touch, because they are **decision** logic in other subsystems with
their own contracts and tests, and the review's instruction was to repair
this closure and start nothing else:

- `kernel/convergence.py:337` — `verification is not None and
  verification.passed` decides whether a round is `clean`;
  `:364` decides whether a fix is needed; `:359` stores the flag for the
  flip-detection guard.
- `kernel/integration.py:437` — `if not verification.passed` gates
  landing a merged tree.
- `adapters/cli_review.py:134` — selects what a reviewer is shown.

A `VerificationResult(passed=1)` reaching any of those would be read as a
pass. None of them can produce a `TaskState.COMPLETED` — the state
authority still refuses that independently — but "cannot forge a DONE" is
a weaker statement than "cannot be misread", and this ADR does not claim
the stronger one. `CompositeVerifier` is safe by accident: `all()` returns
a real bool.

This is offered as a **candidate finding for the next review**, not as
closed work.

### What this says about the process, again

L-0044 said: to check "X is the only route to Y", go to the object that
produces Y and try to produce it without X. Round 2 found that I applied
that to the METHODS and not to the FIELD — I hardened every route I could
name and left the destination writable. And the report defect is L-0043's
shape one more time: the rule was enforced where the decision is made and
not where the decision is *published*, so it was simply off in the second
place. Two new lessons are recorded: **L-0045** (a guard on the methods is
not a guarantee while the field is public) and **L-0046** (a report is a
claim; an invariant that the printer does not share is enforced at the
gate and broken at the page).

### Files

- `src/gnosis/kernel/verification.py` — `VerificationVerdict`,
  `verification_verdict()`, `MALFORMED_EVIDENCE_EXPLANATION`.
- `src/gnosis/kernel/state_machine.py` — read-only `state` /
  `completion_evidence` on both machines; `completion_is_evidenced`
  defined in terms of the shared verdict; the honest scope statement.
- `src/gnosis/kernel/engine.py` — one verdict per run, derived ledger
  payload (`_verification_ledger_payload`) and report lines
  (`_verification_report_lines`), `MALFORMED_EVIDENCE_PROBLEM`.
- `src/gnosis/director/pipeline.py` — `_verification_line` reads the
  shared verdict.
- `tests/test_state_machine.py` — `TestStateIsNotPubliclyWritable`
  (6 tests, 9 subtests).
- `tests/test_no_invalid_done.py` —
  `TestTheVerdictIsReadByIdentityNotTruthiness` (6 tests, 24 subtests) and
  `TestARejectedResultIsNeverReportedAsAPass` (10 tests), including the
  end-to-end `TaskEngine` run with `passed=1`.

---

## Third independent review addendum — 2026-08-22: **FAIL CRÍTICO**

The repair in `1591aa7` was re-reviewed independently and returned FAIL
CRÍTICO. The two previous repairs held: the state authority still refuses
an unevidenced COMPLETED, and the engine's report still refuses to print
a rejected result as a pass. The invariant was broken anyway, one level
up, and this round is the most serious of the three because the reviewer
did not need to defeat any of the guards — they went **around** them.

### The finding, reproduced

```python
CompositeVerifier("composite", [verifier_returning_passed_1]).run(cwd)
# -> VerificationResult(name='composite', passed=True, exit_code=0)
# -> verification_verdict(...) is PASSED
# -> TaskState.COMPLETED, ReportStatus.COMPLETED, problems=()
```

```python
CompositeVerifier("empty", []).run(cwd)
# -> VerificationResult(name='empty', passed=True)     # all([]) is True
# -> TaskState.COMPLETED, ReportStatus.COMPLETED
```

Both were replayed against `9117b63` before any change and produced
exactly that. The second is the purer one: a DONE minted by running no
check at all.

What makes this different from rounds 1 and 2 is that **every strict
reader downstream was correct.** `verification_verdict` read the
composite's `passed` and found the object `True`. `completion_is_evidenced`
agreed. The report printed `PASSED` because the evidence really did say
so. The malformed child had been laundered out of existence one frame
earlier, by the one component that was supposed to be aggregating
evidence and was instead manufacturing it.

The mechanism is small and general: **the verdict has three states and
`VerificationResult.passed` has two.** A composite whose member returns
something unreadable has exactly two things it can say in that field, and
neither of them is true. `all(r.passed for r in results)` picked one, and
because `bool` IS an `int` in Python it picked the wrong one — silently,
for every truthy value, and unconditionally for the empty case.

Round 2's addendum said, in as many words:

> `CompositeVerifier` is safe by accident: `all()` returns a real bool.

**That sentence is retracted.** It is true about the composite's own
return type and false about everything that matters. `all()` does return
a real bool — computed by evaluating each member's `passed` for truth,
which is the exact defect the same addendum had just spent two pages
repairing elsewhere. The claim was written from the type and never
checked against a run; one line of code would have falsified it.

Round 2 also named three unrepaired truthy readers — `convergence.py`,
`integration.py`, `cli_review.py` — and deferred them as "a candidate
finding for the next review". They were still there. Naming a defect is
not bounding it, and the reviewer's instruction this round was explicit
that "`verification_verdict` is the only reader" remained false.

### The repair

**Evidence can now state no verdict, as a type.** `MalformedEvidence` is
a frozen dataclass carrying a `name`, a `reason` and the raw member
payloads. It is deliberately NOT a `VerificationResult` subclass:
`verification_verdict` classifies everything that is not a
`VerificationResult` as MALFORMED, so an instance of this type cannot be
read as a pass by the one function that decides — the property holds by
construction rather than by anyone remembering to check. Its `to_dict()`
has no `passed` key at all, so a reader scanning a payload for that field
finds nothing to misread rather than something to interpret correctly.

`Verifier.run` is therefore typed `-> Evidence`, not
`-> VerificationResult`. That is what turned the audit from a grep into a
type error: mypy named every production reader that had assumed the
narrow case, which is precisely the set of places rounds 1 and 2 had to
find by hand and twice found incompletely.

**`CompositeVerifier` refuses three things.** It refuses to exist with an
empty collection (`EmptyCompositeError`, raised in `__init__`, before
anything can run) and stores its members as a tuple, so a refusal that
held only until somebody called `.clear()` is not what was built. It
classifies every member with `verification_verdict` and nothing else. And
it refuses to convert a malformed member into a verdict — not into a pass
and not into an ordinary failure either, because a failing member says
the WORK is wrong while a malformed one says the VERIFIER is wrong, and
an operator sent to debug the first when it is the second will not find
anything. A nested composite cannot launder through a layer either.

**The three deferred readers are repaired, each in its own terms.**

- `ConvergenceLoop` reads the verdict once per round and derives all
  three of its former truthy reads from it. Malformed verification is
  treated as an evidence-collection failure — the round cannot converge,
  cannot count toward stalemate (a broken verifier is not a stuck repo),
  and is recorded as a typed `EvidenceFailure` with `error_type
  MalformedEvidence`. The flip-detection memo now stores verdicts rather
  than bools, so "the verifier was broken last round" can never be
  remembered as "it failed last round".
- `WorkIntegrator` gates the shared branch on `verification_verdict(...)
  is PASSED`. Malformed evidence fails closed under its own outcome,
  `VERIFICATION_INVALID`, which is deliberately not a synonym for
  `VERIFICATION_FAILED`: one sends a human to read the diff and the other
  says the diff is not the problem. Landing is the most irreversible
  action in the system and was the last place still guessing.
- `cli_review` builds its line through `verification_prompt_line`, which
  answers three ways. A fixer told "verification is currently FAILING"
  when the verifier is what broke will edit code that may be fine; before
  this, a `passed` of `1` printed nothing at all and the round looked
  clean.

**The Director re-examines rather than inherits.** `ConvergenceLoop`
already refuses to converge on malformed evidence, and `GovernedPipeline`
now independently refuses to derive `ReportStatus.COMPLETED` or
`BriefRecordState.COMPLETED` from a CONVERGED result whose final round
does not verify PASSED. That is the lesson of this ADR's own first
addendum applied to itself: an invariant enforced at exactly one end is a
property of that end. A CONVERGED result over zero rounds is refused for
the same reason `all([])` is — an outcome asserted with nothing behind
it. The contradiction is reported as ESCALATION_REQUIRED, not PARTIAL:
another round cannot repair two halves of the kernel disagreeing.

**What was deliberately NOT done.** `VerificationResult.passed` is not
validated in `__post_init__`. Making the reproduction unconstructible
would move the guarantee into the constructor and leave every consumer
believing whatever it was handed by any other route — a duck-typed
verifier, a deserialized ledger entry, a future dataclass with the same
shape. The reviewer asked for this explicitly, and it is the right call:
consumers must keep failing closed on malformed data, so the data has to
stay constructible. `passed=1` is still legal to build, still preserved
verbatim in `rejected_result` and in `MalformedEvidence.children`, and
still refused by everything that decides.

### Mutation check

Nine mutants, each restoring exactly one defect, run by
`scripts/mutation_check.py` — a committed script with the mutants
declared as data, so a fourth reviewer can re-run the claim rather than
read it. Targeted suite: `tests/test_no_invalid_done.py`,
`tests/test_verification.py`, `tests/test_convergence.py`,
`tests/test_integration.py`, `tests/test_pipeline.py`; baseline **203
passed / 39 subtests**.

| Mutant | Result |
|---|---|
| M1 `CompositeVerifier` reads `passed` for truthiness again (`all(r.passed …)`) | **red** |
| M2 an empty `CompositeVerifier` can be constructed again | **red** |
| M3 `all([]) is True` restored end to end (constructor AND `run` guards removed) | **red** |
| M4 a malformed member is collapsed into an ordinary FAILED | **red** |
| M5 `ConvergenceLoop` reads truthiness again and malformed evidence counts as collected | **red** |
| M6 `WorkIntegrator` lands on `if not verification.passed` | **red** |
| M7 the fixer prompt reads `not verification.passed` again | **red** |
| M8 `GovernedPipeline` derives COMPLETED from CONVERGED alone | **red** |
| M9 the shared verdict itself reads truthiness (round-2 mutant, kept) | **red** |

None survived; the tree was restored and re-verified green (203 passed).
The script exits non-zero if any mutant survives or if the baseline is
not green, so it cannot produce a clean transcript for an unguarded tree.

### Evidence

`.gnosis/evidence/20260822T181937Z/` — **874 passed, 60 subtests**
(up from 822/60), mypy strict clean over 55 source files, ruff at **19
findings against a baseline of 19**: this unit added no lint debt.
Captured against a clean tree at `9c6064c` (tree `baca7d24`), with
`f34-round3-tree-binding.json` recording `content_fingerprint()` before
AND after the run — `git status --porcelain -- src tests scripts
pyproject.toml` was empty at both ends, and unlike round 2 the `pre`
snapshot was taken strictly BEFORE the capture was launched.

The bundle carries three artifacts beyond the gate transcripts:

- `mutation-check.f34-round3.txt` — nine mutants, none survived.
- `reproduction-replay.f34-round3.txt` — the review's two reproductions
  replayed against the repaired tree. The composite answers
  `MalformedEvidence` (`verdict` MALFORMED, no `passed` key in its
  serialization at all, the child's `passed: 1` kept under `children`)
  and the engine finishes `TaskState.FAILED` / `ReportStatus.PARTIAL`
  with a populated problems list naming the member that broke it; the
  empty composite raises `EmptyCompositeError` at construction, so there
  is no object left on which `.run()` could be called.
- `f34-round3-tree-binding.json` — the binding described above.

Two things about the run are stated rather than implied. The mutation
check ran before the commit against the same working tree, with one
later change: the convergence warning-ordering fix — moving the
malformed-evidence warning after the fingerprint-unavailable check, so
neither can suppress the other through the text of a message — was
applied after the mutation run and before the commit. It touches no
mutant target, and `scripts/mutation_check.py` is committed so the check
can be re-run against the exact committed tree. And the suite is run with
`PYTHONUTF8=1`, this workstation's documented baseline (ADR-0001,
L-0003): without it, `tests/test_cli_review_adapters.py::TestCliReviewer::`
`test_a_reviewer_is_caught_editing_a_file_with_an_accent_in_its_name`
fails on this machine — and fails identically at `9117b63`, so it is an
environment precondition and not anything this unit changed.

### What this says about the process, a third time

The pattern across three rounds is now legible enough to name. Round 1
put the invariant in one caller. Round 2 put it in the methods and left
the field public, then printed a pass off evidence the gate had refused.
Round 3 put it in a single reader and then handed that reader's answer to
a component that could not carry it. Each round the repair was correct
and each round it was applied one level below where the outcome is
actually produced.

Two lessons are recorded. **L-0047**: an aggregator launders evidence
when its carrier is narrower than its verdict — a tri-state judgement
cannot survive a two-state field, and `all([])` asserts success from
nothing. **L-0048**: a named-and-deferred finding recurs, and an
unverified reassurance is worse than silence — round 2 wrote that the
composite was "safe by accident" from the return type without running the
case, and listed three live readers as a candidate finding instead of a
falsifier.

There is also a process change in this unit rather than only a note: the
mutation check is now a committed script, `scripts/mutation_check.py`,
with the mutants declared as data. The previous two rounds produced
transcripts by hand, so a fourth reviewer could read the claim but not
re-run it. It exits non-zero if any mutant survives, so it cannot produce
a clean transcript for an unguarded tree.

### Files

- `src/gnosis/kernel/verification.py` — `MalformedEvidence`, the
  `Evidence` union, `evidence_reason` / `evidence_name` /
  `evidence_payload`, `EmptyCompositeError`, and `CompositeVerifier`
  rebuilt around the verdict.
- `src/gnosis/kernel/state_machine.py` — `completion_is_evidenced` takes
  `object`, so evidence that states no verdict is refused by the same
  rule as any other non-result.
- `src/gnosis/kernel/engine.py` — rejected evidence is carried as itself
  (`MalformedEvidence`) rather than collapsed into "no evidence"; the
  ledger payload, the report lines and the problems list all derive from
  `evidence_reason`.
- `src/gnosis/kernel/convergence.py` — one verdict per round; malformed
  verification is a typed evidence failure; the flip-detection memo holds
  verdicts.
- `src/gnosis/kernel/integration.py` — `VERIFICATION_INVALID`; landing
  gated on `verification_verdict(...) is PASSED`.
- `src/gnosis/adapters/cli_review.py` — `verification_prompt_line`.
- `src/gnosis/director/pipeline.py` — `converged_on_valid_evidence`;
  `_status_for` re-examines rather than inherits.
- `scripts/mutation_check.py` — new, the mutants as data.
- `tests/test_no_invalid_done.py` —
  `TestACompositeCannotLaunderMalformedEvidence`,
  `TestTheEngineDoesNotCompleteOnACompositeVerifier`,
  `TestConvergenceRefusesMalformedEvidence`,
  `TestTheFixPromptTellsTheAgentWhichThingIsBroken`.
- `tests/test_pipeline.py` — `TestABriefDoesNotCompleteOnMalformedEvidence`.
- `tests/test_integration.py` — `TestMalformedEvidenceDoesNotLand`.
