# GNOSIS Next Actions — Nicol workstation

1. **HUMAN:** run `codex login` (ChatGPT auth) so independent Codex review becomes available. Verify with `codex login status`.
2. Finish Tier-S repository archaeology → `docs/research/REFERENCE_REPOSITORY_FINDINGS.md` (in progress; workflow fan-out over the 26 local Tier S/S+ clones).
3. Decide and execute the layout reconciliation ADR: real code in `gnosis/` vs pack scaffold `src/gnosis/` (git mv + pyproject packaging + tests green, or explicitly retire the scaffold).
4. Write ADR for the M4 memory-provider selection criteria (embedder benchmark for m3, supersession-cost question for zmem, per MEMORY_FABRIC.md §benchmark).
5. Restart Claude Code once so the `.mcp.json` memory servers (zerker-memory, m3-memory) attach; smoke one MCP tool call each.
6. Resume kernel build sequence (MASTER_AUTONOMOUS_BUILD_DIRECTIVE Phase 1+) — gates are open once archaeology lands.
7. Optional, evidence-gated: Graphify benchmark vs Sverklo/CodeGraph (only per MEMORY_FABRIC.md rule, after GNOSIS-Bench exists).
8. Consider upstream bug reports (with operator approval): zmem Windows diagnostic crash; m3 `--database` provisioning gap.
9. Operator decision: delete or relocate the unrelated `security-audit/` leftovers.
