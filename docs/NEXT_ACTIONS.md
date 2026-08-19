# GNOSIS Next Actions — Nicol workstation

1. **HUMAN:** run `codex login` (browser OAuth with the ChatGPT account; consumes no quota — can be done today). Codex usage quota is exhausted until 2026-08-20; independent Codex review is parked as RATE_LIMITED until the reset, then verify with `codex login status` and a `codex exec --sandbox read-only` smoke.
2. Directives 1–3 are implemented (ADR-0004: kernel.canonical, hash-chained RunLedger, frozen transition tables; 183/183 tests). Next kernel unit: Directive 4 (durable claims + ephemeral fenced leases — extend file_lock/run_store with lease_id/holder/fencing_token per MASTER directive §Leases), then Directive 5 (provenance-gated worktree destruction in kernel.worktree).
3. Optional lint polish: ~15 deliberate ruff residuals in src (BLE001/PLW1510/etc.) and ~20 in tests — whitelist with per-line noqa+reason or fix, when touching those files anyway. mypy strict is at zero for src/gnosis.
4. M4 memory-provider selection criteria written (ADR-0003); execute the M4 benchmark itself when memory adapters become the active milestone.
5. Restart Claude Code once so the `.mcp.json` memory servers (zerker-memory, m3-memory) attach; smoke one MCP tool call each.
6. Resume kernel build sequence (MASTER_AUTONOMOUS_BUILD_DIRECTIVE Phase 1+) — gates are open once archaeology lands.
7. Optional, evidence-gated: Graphify benchmark vs Sverklo/CodeGraph (only per MEMORY_FABRIC.md rule, after GNOSIS-Bench exists).
8. Consider upstream bug reports (with operator approval): zmem Windows diagnostic crash; m3 `--database` provisioning gap.
9. Operator decision: delete or relocate the unrelated `security-audit/` leftovers.
