# GNOSIS Durable Decisions

## D-001 — Agent intelligence is not authority
The deterministic kernel owns state transitions, gates and promotion.

## D-002 — External repositories are read-only research sources
Original vendor repos are not modified. Experiments use isolated copies/workspaces.

## D-003 — Claude Code + Codex are first-class V1 adapters, not permanent kernel dependencies
Provider/model independence is architectural.

## D-004 — Fable 5 is the primary construction model where available
Use high capability for architecture/long-horizon work. Routine subagents may use smaller models when this preserves quota without hurting evidence.

## D-005 — Memory is layered and non-authoritative
Auto-memory/subagent memory assist construction; project truth remains Git/SPEC/ADR/tests/source.

## D-006 — Self-improvement is evidence-gated
No live self-promotion. Candidate→eval→regression→shadow→promotion/rejection.

## D-007 — Reviews are read-only
A judge cannot modify what it judges.

## D-008 — V1 must work with FakeAgents
Kernel tests must not require real LLM calls.

## D-009 — No automatic paid-API fallback
Claude/Codex adapters prefer official locally authenticated subscription CLIs.

## D-010 — No dangerous permission bypass
Autonomy comes from structured permissions/policies/sandbox, not disabling safeguards.

## D-011 — Nicol Windows path is the project source of truth
`C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi` is the canonical editable project location on the target machine. WSL may be used as auxiliary runtime, not as a second divergent editable copy.

## D-012 — GNOSIS uses a Memory Fabric, not one memory database
M3 provides broad/cross-agent recall. ZMem provides governance/trust/lineage/receipts. Both live behind GNOSIS-owned adapters.

## D-013 — No blind memory dual-write
Raw events stay in GNOSIS durable state. Searchable summaries can enter M3; durable high-authority memories are proposed to ZMem governance. Injection is deduplicated/freshness-checked.

## D-014 — Graphify is a structural-memory candidate, not a required memory authority
It must beat alternatives on GNOSIS-Bench before becoming a dependency.

## D-015 — Obsidian is an optional human mirror
Runtime correctness cannot depend on the Obsidian app or an Obsidian plugin.

## D-016 — Resource paths are resolved by Git origin
All canonical links are kept in `resources/repositories.json`; agents should not depend on guessed folder names.

## D-017 — Memory engine isolation is environment-pinned, and engines install from copies
External memory engines are installed as isolated `uv tool` environments built from copies (originals stay read-only). m3 state isolation uses `M3_MEMORY_ROOT`/`M3_ENGINE_ROOT`/`M3_CONFIG_ROOT`, never `--database` (broken upstream). zmem hermetic use goes through standalone `--db`. Details/evidence: ADR-0001.

## D-018 — The policy gate is reachable from the Director entry point, and evaluated twice
Briefs pass through `DirectorOrchestrator`, so that is where a gate has to be enableable; a refusal lands as an `ESCALATED` brief record plus an `escalations/` file. The intervention point is evaluated before anything reads the repository (`pre_context`) and again after kernel context is prepended (`final_prompt`), because the prompt that runs is not the prompt the first verdict judged. An `ApprovalStore` without a `PolicyEngine` is refused at construction. Details/evidence: ADR-0013.

## D-019 — Action identity and cassette identity are the same problem, solved once
Both a policy approval and a replay cassette must answer "is this the same call?". Both now key on content rather than paths: `workspace_fingerprint()` (HEAD + branch + hash of dirty state) and content hashes of MCP configs, shared from `kernel/git_evidence.py`. Consequence accepted deliberately: an approval granted against one tree state does not carry to another, including a retry after an attempt modified the tree. Details/evidence: ADR-0013, ADR-0014.

## D-020 — What cannot be enforced is recorded in the enforcement matrix, never implied away
Rule bodies are in-process operator code and can act before returning a verdict (`policy/rule_purity = IGNORED`); the launch gate is opt-in until a default rule set exists (`policy/agent_launch_gate = PROMPT_ONLY`, with `policy.ungoverned` ledger events and `require_policy=True` available now). Python cannot enforce purity; the matrix is where that stops being a silent assumption. Details/evidence: ADR-0013 Codex addendum.

## D-021 — Provider translation lives in `gnosis/adapters/`, and the kernel never imports it
A new top-level package holds everything provider-specific (prompt shapes, output envelopes, payload parsing). The rule that makes "provider-neutral by adapters" checkable rather than aspirational is one-directional: `adapters/` imports `kernel/`, never the reverse. Details/evidence: ADR-0015.

## D-022 — A reviewer's read-only posture is claimed by the provider and verified by the kernel
Review agents run with edit tools withheld, and `CliReviewer` fingerprints the workspace either side of the run, refusing a reviewer that moved it — checked BEFORE its output is parsed. The matrix records `convergence/reviewer_read_only = SANDBOX_APPROX`: detection after the fact is not prevention, and the table says so. Details/evidence: ADR-0015.

## D-023 — Verification claims cite a captured transcript, not prose
`scripts/capture_evidence.py` writes `.gnosis/evidence/<utc-stamp>/` with each command's argv, exit code, duration and output, plus the HEAD it ran at, and exits non-zero if anything fails. ADRs cite that path instead of asserting "suite N/N; mypy clean", which an independent review correctly called self-reported and unbacked. Ruff's whole-repo run is scored against `.gnosis/state/lint_baseline.json`: the count may only go down, so a documented backlog cannot be confused with new debt and new debt cannot be added quietly. Details/evidence: ADR-0014.

## D-024 — A hold window reopens only by a recorded decision, never by a competing row
`HoldStore` carries two row kinds. A `hold` row is an OBSERVATION and competes by restrictiveness, so two sightings of a shut window can never relax each other through arrival order. A `supersede` row is a DECISION carrying a reason, and draws a line past which earlier rows for that credential no longer apply. Without the distinction, `probe()` was inert — a narrower PROBE row always lost to the ACCOUNT row it was meant to replace. It also gives an operator an auditable way to clear a hold reality has overtaken (a topped-up account) instead of editing a file. Details/evidence: ADR-0016.

## D-025 — A safety mechanism that cannot read its own state denies
`HoldStore.read()` returns holds AND whatever was unreadable, and `admits()` denies when anything is damaged. The original policy — skip the bad row, return the rest — was backwards: skipping a row opens the window that row described, so a single truncated line admitted work against a credential known to be shut. Related: an atomic state transition must fit in ONE durable line, because two lines in one append can be torn by a crash; `probe()` writes a single `narrow` row, and a test walks every byte-prefix of the log asserting none admits work. Details/evidence: ADR-0016 Codex addendum.

## D-026 — The gate covers every AGENT launch a brief causes, and says what it does not cover
Convergence launches a reviewer and a fixer per round — usually more agents than the implementation itself — so those run through `GatedAgentRunner`, which asks the hold plane and the policy engine before each launch and reports the result back to the hold plane afterwards. It uses `agent_launch_snapshot`, extracted from the engine so there is exactly one action identity rather than two that drift. Verifier subprocesses are deliberately outside the gate: a policy able to deny verification could switch off the evidence requirement that makes a DONE claim checkable. Recorded as `convergence/verifier_execution = IGNORED`. Details/evidence: ADR-0017.

## D-027 — A task closes on convergence, never on the implementer's opinion
`GovernedPipeline` derives the report status from the convergence outcome alone; the implementation's own verdict never sets it. Reviewer independence is enforced as far as the kernel can check it — the same runner object cannot implement and review — and recorded as `convergence/reviewer_independence = SANDBOX_APPROX`, because object identity is not mind identity. Details/evidence: ADR-0017.

## D-028 — Work lands only by fast-forward to an already-verified merge, on a named branch
`WorkIntegrator` merges in a throwaway staging worktree, runs the verifier on the MERGED tree there, re-reads the base under the lock, and only then fast-forwards a target branch named at construction. Failure means nothing moved, which is the cheapest rollback; a checkpoint ref carrying the base sha names the pre-integration state, and the kernel produces the rollback command without ever running it. The enforcement matrix splits the guarantee honestly: `verified_before_landing = HARD` (ordering is mechanical) and `semantic_correctness = IGNORED` (what the check notices is the operator's verifier, not the kernel's judgement). Details/evidence: ADR-0018.

## D-029 — The queue holds work; the claims plane holds ownership
`WorkQueue` never decides who owns a brief. Every worker scans the same `pending/` directory and `WorkAuthority.acquire`'s CAS lets exactly one through; a `ClaimConflictError` is the mechanism working. What the queue does own is reconciling its file state with the claims plane after a crash: `recover()` routes a record whose claim is RESOLVED to `done/` and anything else back to `pending/`, and `drain` calls it before the first claim. Rule 8's attempt cap lives here too, because parking is free and a budget cannot bound a loop that spends nothing. Details/evidence: ADR-0019.

## D-030 — A brief's budget is durable, per brief, and consulted before spending
`Budget` bounds wall clock and agent launches; `BudgetStore` keeps the running total keyed by brief id so a park/resume cycle cannot reset it. It is checked in `GatedAgentRunner` immediately before each launch — the last point at which refusing is free — and before the implementation phase, and a launch is counted before the child starts. Exhaustion is a PARK, never an agent failure. Tokens are deliberately not counted: the kernel shells out to a CLI and would be enforcing on an invented estimate. Details/evidence: ADR-0019.

## D-031 — A review expires when the tree it judged moves
Every planned landing carries `review_still_applies`, true only for a task that forked from the current head and lands first. `LandingCoordinator` refuses a stale-review landing by default and `GovernedPipeline` routes landings through it, so the gate is on the path real briefs take. Authority to land a stale-review task is per task id, never a global switch. Ordering itself prevents nothing: it reduces wasted rounds and reports staleness, and post-merge verification remains the only thing that decides. Details/evidence: ADR-0020.

## D-032 — An expired review is replaced by a verdict, not waived by a decision
`WorkIntegrator` derives staleness from the task's fork point against the target head, and when stale it runs an injected independent reviewer against the MERGED tree before the fast-forward — the tree that will actually land. The same `classify_findings` convergence uses decides what blocks, so a finding cannot block one and not the other. The reviewer is fingerprinted either side (rule 9), built per task and passed per call, and launched through `GatedAgentRunner` so it is gated, held and budgeted like every other launch. A per-task waiver remains, as the exception rather than the only route. What the kernel cannot check — that an injected callable really launched an independent agent — is recorded as `integration/rereview_provenance = IGNORED`. Details/evidence: ADR-0021.

## D-033 — A supervisor may do less, never more; and what it decided survives its own death
Worker supervision paces parks with a durable exponential `not_before` on the brief record, and bounds itself with rule 8's list: max attempts (the queue, exhausted briefs MOVE to `blocked/`), wall-time, per-brief budget, an invalid-output limit, plus a consecutive-park breaker. It may pace, stop and take work out of circulation — never clear an attempt count or resurrect a blocked brief, which are `requeue` and belong to an operator. Every transition stamps its intent on the record before the claims-plane call, so a crash in the two-write gap leaves recovery finishing the decision rather than reversing it. Shipped WITHOUT an independent review: Codex refused with a usage limit. Details/evidence: ADR-0022.

## D-034 — A guessed window is tested by one recorded launch, not by everyone at once
The kernel probes only its OWN estimates: a `window_estimated` hold within `lead_s` of elapsing, or an unknown window that never expires by itself. A provider-supplied window is never probed. The probe is a LEASE with its own TTL and never inherits the window it replaces; the claim is a compare-and-set under one lock, so exactly one caller wins; a launch that comes back clean supersedes the hold, because a successful probe nobody reads leaves every other run parked on an answered question. The caller lives on the `HoldGate` protocol so the path that actually launches agents reaches it, with a per-launch holder identity. Known gap, stated: after an estimated reset elapses the hold is gone and admission is open to everyone, so this is a mitigation inside the lead window, not a proof. Details/evidence: ADR-0023.

## D-035 — Rotation is an availability mechanism that may not make a billing decision
A credential is an identity with a KIND (SUBSCRIPTION / METERED / LOCAL), and rotation stays inside the primary's kind unless another is explicitly authorised: an exhausted seat is a reason to wait, not a reason to start billing (rules 25, 26, 13). Secrets never enter the kernel — a credential names the environment variables its value lives in, so nothing recordable can leak one. A credential that cannot be bound RAISES instead of inheriting the ambient environment, and the child receives only the identity it was given, so an agent cannot spend a key the kernel refused to select. Both launch paths rotate: the gated runner and the engine. What the kernel cannot check — that the CLI authenticates with the environment it was handed — was initially classified `credentials/child_honours_the_binding = PROMPT_ONLY`; **ADR-0024's independent-review addendum (finding 8, 2026-08-21) corrected the current enforcement level to `IGNORED`** (PROMPT_ONLY means asked-for-not-enforced, but nothing asks the CLI and no post-hoc check exists, so PROMPT_ONLY was one level too generous). The trusted binding is still applied independently — the child receives only the identity it was given and cannot spend a key the kernel refused to select — so `IGNORED` classifies the unverifiable *child self-claim*, not the binding itself. Details/evidence: ADR-0024 (and its independent-review addendum, finding 8); current value pinned in `src/gnosis/kernel/policy.py` and `tests/test_policy.py`, reported in `docs/PROJECT_REPORT.md` §4.

## D-036 — Review debt is paid with the strongest channel available, and the channel is recorded
Three units (ADR-0022/0023/0024) shipped self-reviewed because Codex was rate-limited. Rather than accumulate a fourth, they were reviewed by independent read-only agents in clean contexts — a weaker channel than a different model, recorded as such in each ADR header. All three returned FAIL: 47 findings, six critical, against 14 the self-reviews had found. Twenty-six are repaired and verified; seventeen are recorded as still open in the addenda rather than carried silently. Rule 9 was verified mechanically: the repository tree fingerprint was identical before and after the reviews. Details/evidence: ADR-0022/0023/0024 addenda, `.gnosis/evidence/20260821T170951Z/`.

## D-037 — The evidence gate belongs to the engine, not to a mode
`TaskEngine.execute_task` refuses a verifier-less task as its FIRST statement — before a claim, a worktree, a policy verdict or an agent launch — and `completion_is_evidenced` is the single authority for `TaskState.COMPLETED`, refusing `None`, refusing anything that is not a `VerificationResult`, and refusing a `passed` that is not exactly `True`. The previous check lived inside `if authority is not None`, which made constitution rule 2 a property of GOVERNED runs; the default `DirectorOrchestrator` supplies no authority, so on the path real briefs travel the rule was off and `verification_result.passed if verification_result else True` turned an absent verifier into a pass. `run_pending` also refuses before consuming a brief, but that is defence in depth, because a rule enforced only where callers remember it is documentation. **Corrected 2026-08-22:** this entry originally claimed the guarantee sat "at the lowest point that can authorise a DONE". It did not — see D-038. What the kernel still cannot judge is the QUALITY of the check — a verifier wrapping `true` satisfies this gate — which is why F-36 (`ProofPacket`) stays open. Details/evidence: ADR-0025.

## D-038 — COMPLETED is admitted by the state authority, never by a transition
`TaskState.COMPLETED` is in `EVIDENCE_GATED_STATES`, so `TaskStateMachine.transition()` refuses it outright; the only route is `complete(verification)`, which is handed the `VerificationResult` ITSELF — never a boolean — and re-examines it, because a flag computed by the caller puts the decision back in the caller and that is the arrangement that failed. Evidence authorises the CLAIM and not skipping the graph, so `complete()` still consults `TASK_TRANSITIONS`; and a machine cannot be constructed already COMPLETED, so the guarantee carries no asterisk. `FAILED` and `CANCELLED` are deliberately NOT gated: nobody has an incentive to forge a task that did not finish. This supersedes the part of D-037 that located the guarantee in `TaskEngine` — an independent Codex review (FAIL PARCIAL) reproduced `CREATED -> PLANNED -> IN_PROGRESS -> VERIFYING -> COMPLETED` on a bare state machine, with no evidence, while every F-34 test was green. Details/evidence: ADR-0025 addendum, L-0044.

## D-039 — Evidence that states no verdict is a TYPE, and `Verifier.run` may return it
`VerificationResult.passed` has two states and `verification_verdict()` has three, so any component that AGGREGATES evidence had nowhere to say "a member returned something I could not read". `CompositeVerifier` said "pass": `all(r.passed for r in results)` read a `passed` of `1` for truth and returned a brand-new, entirely well-formed `VerificationResult(passed=True)` — and `all([])` did the same for a composite with no members at all. Every strict reader downstream was then correct about an object computed from evidence the kernel refuses. `MalformedEvidence` makes the third state representable: a frozen dataclass with a `reason` and the raw member payloads, deliberately NOT a `VerificationResult` subclass, so `verification_verdict` classifies it MALFORMED by construction and its serialization carries no `passed` key to misread. `Verifier.run` is typed `-> Evidence`, which is what made mypy — rather than a grep — enumerate every production reader; the three that round 2 named and deferred (`convergence.py`, `integration.py`, `cli_review.py`) are repaired here, each in its own terms, and `GovernedPipeline` re-examines the evidence instead of inheriting the loop's conclusion. `VerificationResult.passed` is deliberately NOT validated at construction: making the reproduction unconstructible would move the guarantee into the constructor and leave consumers believing whatever arrives by any other route, so `passed=1` stays legal to build and stays refused by everything that decides. Details/evidence: ADR-0025 third addendum, L-0047, L-0048.
