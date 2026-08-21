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
