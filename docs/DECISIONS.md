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
