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
- Independent review: **NOT DONE.** Codex is rate-limited (reset reported
  2026-09-20) and direction has reserved the review of this unit for
  itself, over the synchronised folder. This ADR ships self-reviewed and
  says so; L-0041 measures that channel at roughly one finding in four.
- Scope: **F-34 only.** F-01..F-33 and F-35..F-42 are untouched and
  remain open. Nothing here closes them.

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

This is **defence in depth, not the guarantee**. Requirement: the
guarantee lives at the lowest point that can authorise a DONE. It does —
in `completion_is_evidenced`. If a future caller bypasses the
orchestrator entirely, the engine still refuses.

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
