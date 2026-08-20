# ADR-0012 — Typed failure taxonomy, park states, recovery-as-reconcile (Directive 9)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_failures.py` (50 tests),
  `tests/test_engine.py::TestFailureTaxonomyWiring` (5 end-to-end tests);
  suite 440/440; mypy strict clean; dual adversarial review (Codex
  pre-commit, multi-agent workflow post-commit — see addendum).
- Source: `docs/research/REFERENCE_REPOSITORY_FINDINGS.md` §9 (cezar's
  evidence-ordered limit parsing, smithers' `waiting-quota` park state,
  ralphex's three-tier taxonomy, AWF's reason codes flowing to scheduler
  policy, symphony's distinct terminal reasons, beads' typed conflicts).
  Direct implementation of constitution rules 5–8.

## Decisions

### 1. Classification is graded, and the grade is the chain's to assign

`FailureClassifierChain` consults classifiers in descending
`EvidenceGrade` and stamps its **registered** grade on the result — a
classifier cannot promote its own evidence.

Grades, highest first: `STRUCTURED` (runner flags, exit zero),
`SEMI_STRUCTURED` (documented provider fields), `PROSE` (regex, last
resort), `LAST_RESORT` (a bare non-zero exit: real evidence that says
*something* failed but never *which*), `NONE`.

Prose outranks exactly one thing — the bare-exit-code classifier — and
never informative structured evidence; a higher-grade classifier
returning None means "I looked, and it is not this", which prose may not
overturn.

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

## Known limitation (stated, not implied)

The hold/park registry and `boot_sweep` have **no production caller**:
the engine consumes the classification (retry/park/escalate and the
durable run state), but placing durable holds and sweeping stranded
runs at boot needs the scheduler that does not exist yet. The
mechanisms are tested, not live — said plainly here because Directive
9's own lesson is that a mechanism nothing calls is a parallel
fiction.

## Workflow review addendum (2026-08-20, post-commit 9d963aa)

The multi-agent review (21 findings; 10 confirmed with reproductions, 11
refuted with assumptions recorded) landed after the commit above. All ten
are repaired here.

**The wiring was thinner than the commit message claimed.** I wired the
classification and said Directive 9 was end-to-end; the review found the
seam:

1. *(major)* `ClaudeCodeCLIRunner` parsed `parsed_json` **only on
   success**, so on every failed attempt `structured` was `{}` — making
   the structured rate-limit classifier unreachable in production and
   leaving prose, which can never supply a window, as the only rate-limit
   signal that could ever fire. Fixed: the runner parses on failure too,
   which is exactly where an error payload lives.
2. *(minor)* A `RATE_LIMITED` attempt was written to disk as
   `RunState.FAILED` — the park existed only in memory, so no scheduler
   could resume it and it read as an agent failure. `RunState` gained a
   non-terminal `RATE_LIMITED` state with `RATE_LIMITED → RUNNING`.
3. *(major)* `SchedulerAction.ESCALATE` had no output channel: it was
   collapsed into "stop retrying" and filed as a routine `PARTIAL`, even
   though `ReportStatus.ESCALATION_REQUIRED` already existed. Now used.
4. *(major)* The hold/park and boot-sweep half still has no production
   caller. Stated plainly rather than implied: it is exercised only by
   tests until the scheduler exists (see Known limitation).

**Classification hardening:**

5. *(major)* The prose regex matched ordinary text — a tool describing
   its own limiter, and (verified, self-referentially) GNOSIS's own
   failing test output, whose fixtures print the literal phrase. Now
   restricted to strong phrases (`limit reached/exceeded/hit`,
   `quota exceeded`, `too many requests`).
6. *(major)* A higher-grade classifier returning `None` was read as "no
   evidence" rather than "I looked, and it is not this", letting prose
   overturn structured evidence that positively described a different
   failure. Prose now stands down when structured evidence denies it.
7. *(major)* An absolute reset already in the past was accepted, parking
   until a moment that had passed. Rejected as no window.
8. *(major, the sharpest one)* **Confidence and consequence were
   inverted**: prose is the only classifier yielding no window, an
   unknown window outranks every known one, such a hold never expired,
   and `hold_from_classification` defaulted to ACCOUNT scope — so the
   *weakest* evidence produced the *harshest, permanent, credential-wide*
   hold. The verifier called it "a loaded gun". A hold built without a
   provider-supplied window now gets a bounded fallback
   (`UNKNOWN_WINDOW_FALLBACK_S`, 15 min) and is flagged
   `window_estimated`, so a false positive costs minutes, not forever.
9. *(minor)* Three docstrings and this ADR asserted "prose can never
   overrule an exit code" while the code deliberately ranks prose above
   the *bare* exit code. The code is right (otherwise real CLI rate
   limits would be dead code); the text was wrong and now states the
   real rule.
10. *(minor)* `boot_sweep`'s terminal-state guard was mutation-invisible
    — deleting it left the suite green. Pinned per state.

**Residual, accepted and stated:** prose classification of text that
legitimately contains a rate-limit phrase (GNOSIS's own test output being
the honest example) can still misroute one attempt. Its cost is now
bounded by the fallback window and by structured evidence taking
precedence; eliminating it entirely needs provider-attributed error
frames, which belongs with the adapter milestone.

Tests 41 → 50; suite 440/440.
