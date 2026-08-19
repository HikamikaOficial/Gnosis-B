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
