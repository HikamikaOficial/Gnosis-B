# GNOSIS — Complete project state report

**Generated:** 2026-08-21 · **Commit:** `edec96e` · **Branch:** `master` · **Commits:** 59
**Purpose:** a full, verified picture of the project for an external model to reason about and propose improvements.

Every number here was measured at generation time, not recalled. Where something is unverified it says so. No credentials, secrets or private data are included.

---

## 1. What GNOSIS is

A **local, deterministic, multi-agent engineering kernel**. Agents (Claude Code, Codex, others) propose work; a kernel authorises state transitions, gates, permissions, integration and promotion. The governing principle, from the project constitution:

```
LLM intelligence != system authority
```

The product is provider-neutral through adapters. Claude Code is currently the primary building agent but **is not GNOSIS**.

### Stack

Python 3.12+, `uv`, **stdlib only** (no runtime dependencies), typed throughout (mypy strict), asyncio where needed, SQLite reserved for V1 persistence, pytest, ruff, Git CLI as architecture, JSON/JSONL for interchange, OpenTelemetry-compatible event model.

### Non-negotiable constitution (30 rules, abbreviated)

The rules that most shape the code:

| # | Rule |
|---|---|
| 2 | No task reaches `DONE` without evidence |
| 3 | Task != session |
| 4 | Critical state survives any agent |
| 5 | All retries are classified before repeating |
| 6 | `RATE_LIMITED` != `FAIL_CODE` (a shut window is a park) |
| 7 | `FAIL_INFRA` never penalises agent quality |
| 8 | No loop is unbounded |
| 9 | A reviewer does not modify what it judges |
| 10 | `INDEPENDENT BEFORE INTERACTION` for critical decisions |
| 11 | `EVIDENCE BEFORE CONSENSUS` |
| 13 | Least privilege, deny-by-default for sensitive actions |
| 14 | Git is architecture: checkpoints, worktrees, provenance, rollback |
| 16 | Textual merge != semantic integration |
| 18 | Memory != Truth |
| 20 | Repeatable discoveries become test/policy/invariant/skill |
| 21 | No GNOSIS improvement promotes without beating baseline/regression |
| 25 | Subscription credentials are not an improvised API |
| 26 | No silent fallback to paid APIs |
| 27 | No `git reset --hard`, `clean -fdx`, force-push or mass deletion as shortcuts |
| 28 | Never alter tests to make broken code pass |
| 29 | Never suppress exceptions or gates to "finish" |
| 30 | Simplicity is a security property |

---

## 2. Current measured state

| Metric | Value |
|---|---|
| Tests | **760 collected, 760 passing** |
| Source | At the 2026-08-21 report checkpoint: 13,669 lines across 55 tracked `.py` files under `src/gnosis/` (48 excluding `__init__.py`) |
| Tests | 11,788 lines |
| mypy strict | **clean, 55 files** |
| ruff | 19 findings, all pre-existing, ratcheted against a baseline (build fails if it rises) |
| ADRs | 24 |
| Durable learnings | 43 (`docs/LEARNINGS.md`) |
| Recorded decisions | 36 (`docs/DECISIONS.md`) |
| Enforcement-matrix rows | 20 |
| Latest evidence bundle | `.gnosis/evidence/20260821T174016Z/` |

### Module inventory (largest first)

```
1018  kernel/engine.py                 task execution, fencing, gates, retries
 945  kernel/policy.py                 fail-closed policy engine + enforcement matrix
 800  director/pipeline.py             GovernedPipeline: brief -> implement -> converge -> land
 766  kernel/scheduler.py              hold/park plane, probe, rotation-aware submit
 761  kernel/failures.py               typed failure taxonomy, holds, classification
 699  kernel/integration.py            verified merges, staging worktree, re-review
 650  kernel/replay.py                 record/replay cassettes, content fingerprints
 530  director/work_queue.py           durable queue, fenced claims, recovery
 506  kernel/worktree.py               worktree lifecycle, provenance-gated destruction
 495  kernel/claims.py                 durable CAS claims, epochs, heartbeat pump, sweep
 452  kernel/convergence.py            signal AND evidence loop, stalemate, gate ledger
 355  director/supervisor.py           worker loop: pacing, circuit breakers, authority line
 354  runner/gated_runner.py           every launch gated, held, budgeted, credential-bound
 350  kernel/ordering.py               cross-task landing order, stale-review detection
 347  runner/replay_runner.py          cassette-backed CLI runner
 309  kernel/memory.py                 memory layers
 301  adapters/cli_review.py           real reviewer/fixer adapters
 291  director/orchestrator.py         DirectorOrchestrator, recording_director()
 280  kernel/credentials.py            credential identity, kinds, pool, binding
 236  kernel/lease.py                  fenced expiring leases
 233  kernel/git_evidence.py           git-derived proof
 227  runner/claude_cli_runner.py      subprocess launch, capture, timeout, env binding
 214  kernel/ledger.py                 hash-chained append-only ledger
 213  adapters/review_payload.py
 212  kernel/budget.py                 durable per-brief budget
 206  kernel/memory_reference.py
 191  kernel/code_intelligence_adapters.py
 163  kernel/code_intelligence.py
 147  runner/liveness.py               process fingerprints, is_alive
```

---

## 3. Architecture

### Two-plane ownership

Work ownership is split deliberately, because one mechanism could not answer both questions:

- **`ClaimStore`** — durable compare-and-set claims with fencing **epochs**. Survives restarts. Answers "who owns this task, and is this writer's epoch current?"
- **`LeaseStore`** — ephemeral fenced leases with TTL. Answers "is the owner still alive?"
- **`WorkAuthority`** — combines both. `acquire`, `release`, `resolve`, `assert_current`, `sweep`.
- **`GrantHeartbeatPump`** — background renewal for a grant's whole lifetime.

Invariant: **NO STALE WRITE.** Every durable mutation re-proves ownership immediately before writing (`assert_current`). A deposed worker raises rather than writing.

### Hold / park plane (rate limits)

- `RateLimitHold` rows in an append-only JSONL log, keyed per **credential**.
- Scopes: `ACCOUNT` (blocks everything) and `PROBE` (admits exactly one named run).
- `HoldRegistry.reconcile(records, now)` is a **pure rebuild** from durable rows — idempotent, order-independent.
- Damage fails **shut**: an unreadable row denies rather than admitting.
- **Probe**: when the kernel is about to act on its own *estimated* window, one launch is let through to test it, claimed under a compare-and-set. A probe **suspends** the hold it covers rather than replacing it, so an abandoned probe hands the credential back rather than opening it.

### Policy engine

- Fail-closed with reserved `runtime_error:` / `policy_gap:` namespaces.
- Approvals bound to a **sha256 action identity**, so an approval covers one action, not a class.
- **`EnforcementMatrix`** — a machine-checked honesty table stating how each restriction is *actually* enforced: `HARD` / `SANDBOX_APPROX` / `PROMPT_ONLY` / `IGNORED`. Tests pin it exactly, so a level cannot drift silently.

### Convergence loop

"Converged" means **two** pieces of evidence: deterministic verification **AND** an independent review. Tri-state rounds, stalemate fingerprints, a nothing-lost gate ledger, and typed `EvidenceFailure`. Non-blocking findings are gated, not lost.

### Integration (landing)

Staging worktree → merge → **verify the merged tree** → fast-forward to the already-verified commit. A review expires when the base moves; a stale review is replaced by a **new verdict against the merged tree**, not waived. Checkpoint refs under `refs/gnosis/checkpoints/<task_id>/<base_sha>`.

### Multi-worker plane

- `WorkQueue` — durable directories (`pending/ running/ done/ blocked/`), fenced claims, `not_before` backoff, `max_attempts`, operator-only `requeue`.
- Transition intent is **stamped on the record before the claims-plane call**, so a crash between the two writes leaves recovery finishing the decision rather than reversing it.
- `recover()` and `claim()` **serialise on one queue lock** — an atomic `replace` was not enough (see L-0042).
- `BudgetStore` — durable per-brief launch/time budget that survives resumption.
- `WorkerSupervisor` — the worker loop: sweeps, recovers, claims, paces, and is deliberately limited in what it may decide.

### Credentials

A credential set is a **privilege boundary, not a pool**. `CredentialKind` = `SUBSCRIPTION | METERED | LOCAL`. METERED is never selected without explicit authorisation. A credential **names** the environment variables its value lives in — the kernel never holds a secret. Binding **raises** rather than inheriting the ambient environment. The child's environment is stripped of every pool source variable and a named list of ambient provider variables.

### Failure taxonomy (20 types)

`PASS, FAIL_CODE, FAIL_TEST, FAIL_REVIEW, FAIL_SECURITY, FAIL_ARCHITECTURE, FAIL_PERFORMANCE, FAIL_POLICY, FAIL_INFRA, RATE_LIMITED, TIMEOUT, AGENT_CRASH, INVALID_AGENT_OUTPUT, STALEMATE, STALE_LEASE, MERGE_CONFLICT, CONTEXT_ERROR, DEPENDENCY_ERROR, NEEDS_HUMAN, UNCLASSIFIED`

With **graded evidence** (structured > semi-structured > prose) — the weakest evidence must not produce the harshest hold.

---

## 4. The enforcement matrix — what is actually enforced

This is the project's honesty table. It is data, tested exactly, and it is the single most useful artifact for judging what GNOSIS really guarantees.

| Adapter / restriction | Level | Meaning |
|---|---|---|
| `claims/no_stale_write_after_deposition` | **HARD** | mechanically enforced |
| `file_lock/single_writer` | **HARD** | mechanically enforced |
| `policy/deny_by_default` | **HARD** | mechanically enforced |
| `replay/no_network_in_strict_replay` | **HARD** | mechanically enforced |
| `integration/verified_before_landing` | **HARD** | mechanically enforced |
| `credentials/billing_boundary` | **HARD** | selection only |
| `worktree/shared_repo_isolation` | SANDBOX_APPROX | cwd scope; an absolute path escapes |
| `convergence/reviewer_read_only` | SANDBOX_APPROX | tree fingerprint, not process bound |
| `convergence/reviewer_independence` | SANDBOX_APPROX | |
| `credentials/no_ambient_fallback` | SANDBOX_APPROX | depends on every wrapper forwarding `env` |
| `credentials/ambient_isolation` | SANDBOX_APPROX | deny-list, not allow-list |
| `policy/agent_launch_gate` | PROMPT_ONLY | opt-in until a default rule set exists |
| `integration/shared_branch_gate` | PROMPT_ONLY | opt-in |
| `policy/rule_purity` | IGNORED | a rule body is unsandboxed operator code |
| `worktree/orphaned_child_termination` | IGNORED | |
| `convergence/verifier_execution` | IGNORED | |
| `integration/semantic_correctness` | IGNORED | textual merge != semantic integration |
| `integration/rereview_provenance` | IGNORED | an injected callable can fabricate a PASS |
| `credentials/child_honours_the_binding` | IGNORED | cannot verify the CLI authenticates with it |
| `credentials/declared_kind_is_true` | IGNORED | a declared kind is trusted |

**Six HARD, five SANDBOX_APPROX, two PROMPT_ONLY, seven IGNORED.**

---

## 5. Definition of Done (V1) and honest coverage

Source: `gnosis-spec/V1_DEFINITION_OF_DONE.md`. V1 is done only when automated tests prove GNOSIS can *repeatedly*:

| # | Capability | Status |
|---|---|---|
| 1 | create a durable project/task | implemented |
| 2 | represent task dependencies | implemented (`kernel/ordering.py`) |
| 3 | detect ready tasks | implemented |
| 4 | claim task with lease/fencing token | implemented, adversarially reviewed |
| 5 | reject stale writes | implemented, HARD in matrix |
| 6 | create isolated worktree | implemented, SANDBOX_APPROX |
| 7 | invoke FakeClaude/FakeCodex in CI | implemented (fakes throughout tests) |
| 8 | invoke real Claude/Codex adapters | implemented (`adapters/cli_review.py`) |
| 9 | capture structured/raw outputs | implemented |
| 10 | classify rate limits separately from code failures | implemented, adversarially reviewed |
| 11 | handle malformed agent output with bounded repair | implemented |
| 12 | timeout/cancel hung subprocess | implemented |
| 13 | execute deterministic verification | implemented |
| 14 | execute read-only review | implemented, SANDBOX_APPROX |
| 15 | run bounded rework | implemented (convergence loop) |
| 16 | create a proof packet | implemented (`scripts/capture_evidence.py`, git evidence) |
| 17 | refuse `DONE` when evidence is absent | implemented |
| 18 | survive kernel restart with work preserved | implemented |
| 19 | recover after worker crash | implemented — **repaired 2026-08-21, was inert** |
| 20 | avoid infinite loops | implemented (circuit breakers) |
| 21 | append-oriented audit events | implemented (hash-chained ledger) |
| 22 | preserve Git integrity | implemented |

### Survival suite — the gap

The DoD requires **deliberate** tests for 11 scenarios. Directories `tests/chaos/`, `tests/recovery/`, `tests/security/`, `tests/unit/` **exist and are empty**. `tests/integration/` contains only the memory-fabric smoke test.

| Scenario | Coverage (grep-level, needs a real audit) |
|---|---|
| worker kill | present in ~10 files |
| kernel restart | ~8 files |
| stale lease | ~4 files |
| **repeated identical failure** | **0 files — appears absent** |
| **no-diff loop** | **0 files — appears absent** |
| malformed JSON | ~6 files |
| timeout | ~49 files |
| rate limit simulation | ~13 files |
| reviewer disagreement | ~6 files |
| merge conflict | ~5 files |
| **invalid state transition** | **0 files — appears absent** |

> These counts are keyword greps and may contain false negatives. A line-by-line audit is pending.

### The four invariants

`NO LOST WORK` · `NO INVALID DONE` · `NO STALE WRITE` · `NO INFINITE LOOP`

There is **no single test suite asserting these four by name**. They are implied across many tests. Making them explicit and named is an obvious improvement.

---

## 6. The largest structural gap

**There is no production entry point.**

- No CLI, no `__main__`, no `[project.scripts]`.
- `grep -rn "TaskScheduler(\|GovernedPipeline(\|CredentialPool(" src/` returns **nothing**. Every one of these is constructed only in tests.
- `WorkerSupervisor` is referenced nowhere outside its own module and its tests.

Consequence: several `HARD` matrix rows are *real but inert* — the mechanism is correct and nothing in production instantiates it. This is the project's own recurring failure pattern ("a mechanism nothing calls is a parallel fiction") at the level of the program rather than the module.

---

## 7. Review discipline and what it has cost

Every milestone follows: implement → verify → capture evidence → **independent adversarial review** → reproduce each finding → repair → re-verify → ADR with review addendum → commit.

**Independent review has returned FAIL on every unit reviewed.** That is not a sign of a broken process; it is the process working.

### Measured self-review reliability (L-0041)

| Unit | Self-review found | Independent review found |
|---|---|---|
| ADR-0015 | 3 | 11 (8 missed) |
| ADR-0022 | 3 | 19 |
| ADR-0023 | 6 | 13 |
| ADR-0024 | 5 | 15 |

Across the last three units: **14 self-found vs 47 independently found**, including six criticals none of the self-reviews saw — and two criticals were *misdescriptions inside the self-review's own output*, where the gap had been noticed and stated optimistically.

**Ratio: self-review finds roughly one finding in four.**

### Review channel status

The usual reviewer is **Codex** (`codex exec --sandbox read-only --json`). It is **rate-limited until 2026-09-20**; re-authenticating does not restore it (the limit is on the plan, not the session). The last three units were reviewed by **independent same-family subagents in clean read-only contexts** — a weaker channel that shares blind spots a different model would not, recorded as such in each ADR header.

Rule 9 compliance was verified mechanically: the repository tree fingerprint was byte-identical before and after the reviews.

---

## 8. Open findings (15 remaining of 47)

Listed in each ADR's addendum. Ordered by consequence:

1. **`_resolve_probe` is check-then-act** (ADR-0023) — `supersede` drops every earlier row for the credential, so a provider hold placed between the read and the append is erased.
2. **The credential is absent from the policy action identity** (ADR-0024) — `agent_launch_snapshot` contains no credential, so an operator approval for a subscription launch is byte-identical to the same launch on a metered key.
3. **Cassettes and evidence store child streams unredacted** (ADR-0024) — `redact()` is never applied on the cassette path; a child echoing its environment writes a bound credential into a committed file. Existing patterns would not match a bare OAuth token anyway.
4. **No production entry point** (§6 above).
5. **Rotation provenance is never persisted** — `GatedAgentRunner.rotations` is an in-memory list nothing reads.
6. **`supervisor.queue.requeue(...)` is one attribute hop away** — the authority line is a docstring, and the test that "pins" it asserts a `hasattr`.
7. **Default circuit breakers are off** — `max_briefs` and `wall_clock_s` default to `None`.
8. **`_stamp`'s fallback is not neutral for BLOCK** — if the stamp no-ops, a block reverts to claim-status routing, which targets `pending`.
9. **No "max same failure" breaker** — rule 8 asks for it; park reasons are strings, not types.
10. **`WorkerSupervisor` has no production caller.**
11. **`wall_clock_s` bounds the loop, not a handler** — nothing can interrupt a call in progress.
12. **Unknown-window probe branch targets a state no production path produces.**
13. **`test_only_one_gated_launch_gets_through_the_guess` runs no gated launch** — its runner is constructed and never used.
14. **`frozen=True` over a mutable `Mapping`** in `Credential`.
15. **Mutation-check claims left no captured artifact** — they were run, but by this project's own bar a red run with no captured red output is not evidence.

---

## 9. Selected durable learnings (43 total)

The ones most likely to generalise:

- **L-0016 / L-0041** — self-review finds ~1 in 4 of what independent review finds; the miss concentrates in the claims the author is most confident about.
- **L-0032** — a green concurrency test over an interleaving that never happened is worse than no test. Threads + a barrier create the *opportunity* for contention, not contention. Prove it by mutation.
- **L-0033** — fixing "nothing calls it" by adding a caller nothing reaches. Grep the *interface*, not the implementation, to find who consumes a thing today.
- **L-0034** — ask whether the mechanism *can* exist before designing how it should behave. (`Popen` had no `env`, so no rotation was possible under any design.)
- **L-0035 / L-0040** — enforce a rule against the party the rule is *about*. A boundary the agent can route around is documentation.
- **L-0036** — a mechanism nobody calls can be one level *below* the one you checked. If a test arranges the precondition by hand, ask who arranges it in production.
- **L-0037** — a safety mechanism whose failure mode is *more open* than its absence is worse than absent.
- **L-0038** — an identity is only unforgeable if it is unguessable. An exact-match check turns a guessable name into a bearer token.
- **L-0039** — a duck-typed wrapper will silently drop what you add to an interface. mypy cannot see it.
- **L-0042** — an atomic move proves the file was *there*, not that it was the *same* file. `rename` is not a compare-and-set when the address can be recycled.
- **L-0028** — a safety check whose default is "off" is a hole with documentation.
- **L-0024** — a budget that resets on resumption is a budget in name only.

---

## 10. Deliberately deferred

- Per-epoch worktrees (rejected for V1).
- `RunStore`-internal token verification (waits for the multi-process worker milestone).
- M4 memory-provider benchmark (criteria written in ADR-0003; execute when memory adapters are the active milestone).
- Graphify benchmark (only after GNOSIS-Bench exists).

## Operator-only items (do not block V1)

- Restart Claude Code once so the `.mcp.json` memory servers attach.
- Decide what to do with unrelated `security-audit/` leftovers.
- Approve (or not) two upstream bug reports: zmem Windows diagnostic crash; m3 `--database` provisioning gap.
- 19 pre-existing ruff residuals, baselined.

## Hard security constraint

`https://github.com/Dicklesworthstone/cass_memory_system` carries an MIT licence with an OpenAI/Anthropic rider barring Anthropic and anyone acting under its direction from using, copying, benchmarking, testing or analysing it. It must never be cloned, copied, read or analysed. It is denylisted in `scripts/clone_tier_repositories.py`.

---

## 11. What "ready" requires — the remaining work

1. **Line-by-line DoD audit** producing a real coverage matrix (not greps).
2. **Close the 15 open findings.**
3. **Build the missing survival scenarios** and a suite that asserts the four invariants by name.
4. **Production entry point**: CLI + configuration, so the kernel is runnable and the HARD rows stop being inert.
5. **Wire the worker process.**
6. **Baseline/regression harness** (rule 21) so "improvement" is measurable.
7. **Operator runbook.**

### Improvements worth adding beyond the DoD

- **A `verify()` probe per HARD matrix row.** Today they are labels nobody falsifies; `EnforcementMatrix.verify()` exists but no probes are registered. This converts honesty claims into machine-checked invariants (rule 20).
- **A wrapper-contract test** asserting every duck-typed runner forwards security state (`env`, `binary`, sandbox flags). That defect has now occurred twice.
- **Redaction on the cassette and evidence paths**, plus patterns covering bare OAuth/session tokens.
- **Typed park reasons**, enabling the "max same failure" breaker rule 8 requires.
- **Credential in the policy action identity**, so approvals cannot be replayed across a billing boundary.
- **Captured mutation-check artifacts**, so "mutation-checked" is evidence rather than testimony.

---

## 12. How to reproduce this state

```bash
export PATH="$HOME/.local/bin:$PATH" PYTHONUTF8=1
cd "C:/Users/nicol/Desktop/Claude Code Proyectos/GnosisAgentAi"
uv run --no-project --with pytest --with mypy --with ruff python scripts/capture_evidence.py
```

Writes `.gnosis/evidence/<utc-stamp>/` containing argv, exit codes, full output for pytest / mypy / ruff / git, and a `SUMMARY.json` with `gates_clean` and `non_zero_exits` (ruff exits 1 while at baseline — the summary reports that explicitly rather than claiming `all_passed`).

### Key documents

| Path | Contents |
|---|---|
| `CLAUDE.md` | the operating constitution |
| `gnosis-spec/V1_DEFINITION_OF_DONE.md` | what "done" means |
| `gnosis-spec/GNOSIS_SYSTEM_BLUEPRINT.md` | system blueprint |
| `gnosis-spec/ARCHITECTURE_TARGET.md` | architecture target |
| `docs/PROJECT_STATE.md` | narrative state |
| `docs/NEXT_ACTIONS.md` | exact next step |
| `docs/DECISIONS.md` | 36 decisions |
| `docs/LEARNINGS.md` | 43 durable learnings |
| `docs/adr/` | 24 ADRs, each with its review addendum |
