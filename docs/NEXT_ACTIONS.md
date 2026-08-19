# GNOSIS Next Actions — Nicol workstation

1. **HUMAN:** run `codex login` (browser OAuth with the ChatGPT account; consumes no quota — can be done today). Codex usage quota is exhausted until 2026-08-20; independent Codex review is parked as RATE_LIMITED until the reset, then verify with `codex login status` and a `codex exec --sandbox read-only` smoke.
2. Read `docs/research/REFERENCE_REPOSITORY_FINDINGS.md` §"Architecture directives" before any kernel work — 9 evidence-backed rules (canonical-JSON hash primitive, hash-chained journal, frozen transition allow-list, claims+leases two-plane, provenance-gated worktree destruction, review convergence, strict replay, fail-closed policy, typed failure taxonomy) and the open questions section.
3. Optional lint polish: ~15 deliberate ruff residuals in src (BLE001/PLW1510/etc.) and ~20 in tests — whitelist with per-line noqa+reason or fix, when touching those files anyway. mypy strict is at zero for src/gnosis.
4. Write ADR for the M4 memory-provider selection criteria (embedder benchmark for m3, supersession-cost question for zmem, per MEMORY_FABRIC.md §benchmark).
5. Restart Claude Code once so the `.mcp.json` memory servers (zerker-memory, m3-memory) attach; smoke one MCP tool call each.
6. Resume kernel build sequence (MASTER_AUTONOMOUS_BUILD_DIRECTIVE Phase 1+) — gates are open once archaeology lands.
7. Optional, evidence-gated: Graphify benchmark vs Sverklo/CodeGraph (only per MEMORY_FABRIC.md rule, after GNOSIS-Bench exists).
8. Consider upstream bug reports (with operator approval): zmem Windows diagnostic crash; m3 `--database` provisioning gap.
9. Operator decision: delete or relocate the unrelated `security-audit/` leftovers.
