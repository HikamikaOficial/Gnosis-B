# GNOSIS Project State

**Status:** PHASE -1 GATES SUBSTANTIALLY PASSED — Tier-S archaeology in progress
**Target machine:** Nicol
**Phase:** -1 — Environment + Resource Inventory + Memory Fabric
**Last update:** 2026-08-19 (autonomous Phase -1 execution session)

## Fixed locations

- Project: `C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi`
- External repositories: `C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi\external\repositories`

## Inherited baseline (pre-pack milestones, committed M0→M3)

The repo already contains a working kernel baseline built in an earlier
session: `gnosis/` package (state machine, ledger, leases via file locks,
worktrees, CLI runner, verification, recovery, code-intelligence wiring,
memory contract + router) with a 164-test suite, plus milestone evidence
in `docs/M*.md` and `.gnosis/lab/*/results/`. The v0.3 environment pack
was extracted on top of that baseline (commit 8955932). Note the layout
conflict pending decision: real code lives in `gnosis/`, the v0.3
constitution names `src/gnosis/` (currently an empty scaffold).

## Target-machine gates

- [x] Bootstrap executed (doctor/inventory state present).
- [x] Claude Code Fable 5 + Ultracode validated (this session runs on it).
- [~] Codex CLI installed (0.148.0) — **NOT authenticated; needs human `codex login`**.
- [x] External repos inventoried: 27/130 resolved locally (all Tier S/S+ except the license-blocked one; report: `.gnosis/state/clone_report.json`).
- [x] M3 installed/configured/smoke-tested (uv tool, PYTHONUTF8=1, env-pinned roots; ADR-0001).
- [x] ZMem installed/configured/smoke-tested (uv tool; governance loop revalidated on 0.1.17).
- [x] Cross-session Memory Fabric test passed (`tests/integration/test_memory_fabric_smoke.py`, 3/3; docs/research/MEMORY_FABRIC_STATUS.md).
- [x] Tier S architecture archaeology completed: 23 repos analyzed (10 deep + 3 group sweeps, 14 agents, read-only) → `docs/research/REFERENCE_REPOSITORY_FINDINGS.md` (summary table, 9 kernel architecture directives, contradictions/open questions, per-repo findings with evidence labels).
- [x] Initial ADRs confirmed (ADR-0001; D-017; L-0001..L-0003).
- [ ] Kernel implementation (Phase 1 continuation) begins after archaeology.

## Suite status

- 164 unit/contract tests + 3 memory-fabric integration tests, all passing
  (`uv run --no-project --with pytest --with pytest-asyncio python -m pytest tests/`).

## Known open items / caveats

- Codex login pending (human-only step) — until then no independent Codex review.
- Docker absent (LOW; sandbox/integration later).
- cass_memory_system: never clone/copy/analyze — license bars Anthropic-affiliated use.
- zmem 0.1.17 `status`/`doctor` crash on Windows (diagnostic-only; use `audit health`).
- m3 embedding tier unconfigured (FTS fallback); `m3 setup` deliberately not run.
- Bernstein clone required `core.longpaths=true` (now set globally).
- `security-audit/` contains non-GNOSIS leftovers (Minecraft-skin audit logs, 16MB) — gitignored, awaiting operator decision to delete/move.
- MCP servers for both engines are declared in `.mcp.json`; they attach on next Claude Code session approval.
