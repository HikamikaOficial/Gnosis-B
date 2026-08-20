# ADR-0012 — Typed failure taxonomy, park states, recovery-as-reconcile (Directive 9)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_failures.py` (38 tests),
  `tests/test_engine.py::TestFailureTaxonomyWiring` (3 end-to-end tests);
  suite 431/431; mypy strict clean; dual adversarial review pre-commit.
- Source: `docs/research/REFERENCE_REPOSITORY_FINDINGS.md` §9 (cezar's
  evidence-ordered limit parsing, smithers' `waiting-quota` park state,
  ralphex's three-tier taxonomy, AWF's reason codes flowing to scheduler
  policy, symphony's distinct terminal reasons, beads' typed conflicts).
  Direct implementation of constitution rules 5–8.

## Decisions

### 1. Classification is graded, and the grade is the chain's to assign

`FailureClassifierChain` consults classifiers in descending
`EvidenceGrade` and stamps its **registered** grade on the result — a
classifier cannot promote its own evidence. Prose can enrich a gap; it
can never overrule an exit code.

Grades, highest first: `STRUCTURED` (runner flags, exit zero),
`SEMI_STRUCTURED` (documented provider fields), `PROSE` (regex, last
resort), `LAST_RESORT` (a bare non-zero exit: real evidence, but any
richer description of the same failure wins), `NONE`.

A signal with no evidence at all is `UNCLASSIFIED`, which **escalates
rather than retries**: repeating an action nobody understood is how a
loop becomes infinite (rule 8) and how a destructive call happens twice.

### 2. Reason codes flow unchanged, end to end

`TaskEngine` classifies **every attempt** before it can be repeated
(rule 5), appends `run.attempt_classified` to the hash-chained ledger,
and `should_retry` consults the classification rather than the exit
code. The same `reason_code` an operator reads in the ledger is the one
the scheduler acted on. `TaskExecutionOutcome.classification` exposes it
to callers so nobody re-derives it.

### 3. RATE_LIMITED is a park state (rules 6–7)

It never retries, never penalizes agent quality, and carries a durable
reset. Holds are credential-scoped: `ACCOUNT` blocks everything;
`PROBE` admits **only the named probing run** — `is_resume=True` alone
was an unconstrained claim every queued resume could make, producing the
stampede a probe exists to prevent. `FAIL_INFRA`, `STALE_LEASE`,
`DEPENDENCY_ERROR` and `UNCLASSIFIED` likewise never penalize the agent.

### 4. Recovery is reconcile

`HoldRegistry` holds no truth: `reconcile(records, now)` rebuilds
everything from durable rows, so a double pump or a restart lands in the
same state. Competing holds resolve by **restrictiveness, not iteration
order** (ACCOUNT over PROBE; an unknown window over a known one; the
later reset over the earlier). `boot_sweep` gives every stranded run a
disposition — and leaves terminal runs alone, because re-adopting
finished work is worse than the ghost the sweep exists to prevent.

## Review outcome and repairs (2026-08-20, pre-commit)

**Codex** (`exec --sandbox read-only --json`): FAIL, 6 findings, all
verified true and repaired:

1. *(critical)* **The taxonomy was unwired.** Nothing imported it: the
   engine retried on exit codes and `RecoveryManager` had its own reason
   strings. Directive 9 says *end-to-end*, so this was fixed by wiring,
   not by documenting: the engine now classifies every attempt, records
   it, and schedules on it.
2. *(critical)* `reconcile` kept the **first** competing hold, so an
   earlier reset could reopen a window a later record says is shut.
3. *(major)* `Retry-After` (relative seconds — the actual HTTP spelling)
   was discarded, leaving a hold with no window; and a hold with no
   window never expires, wedging a credential permanently. Conversely
   `reset_at=True` became `1.0` (reopen instantly) and `NaN` never
   expired. Relative delays are converted with an injected clock;
   non-finite and boolean values are rejected.
4. *(major)* `PROBE` holds admitted anyone claiming `is_resume`.
5. *(major)* `bool` is `int` in Python, so `exit_code=False` classified a
   **failed** process as `PASS` at structured grade. `FailureSignal`
   validates its own types now.
6. *(major)* `boot_sweep` never read `state` and could re-adopt a
   terminal run, re-executing completed work.

**Design correction both reviews raised:** with the original chain a bare
non-zero exit was `UNCLASSIFIED` → escalate, so **no ordinary code
failure ever retried** — a taxonomy that unusable is the first thing a
caller bypasses. A non-zero exit is now `FAIL_CODE` at `LAST_RESORT`
grade and retries within the existing attempt cap, while any richer
evidence (a rate-limit field, even a prose rate-limit line) still wins.

The multi-agent workflow review was still running when this landed; its
verdict is adjudicated as an addendum.
