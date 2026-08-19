# GNOSIS Next Actions — Nicol workstation

1. ~~codex login~~ DONE ("Logged in using ChatGPT"). When quota resets (2026-08-20): smoke `codex exec --sandbox read-only --json` once, then run the parked adversarial review over the kernel-hardening commits (843a72e, 1e176a9) via the codex-adversarial-reviewer flow.
2. Directives 1–3 implemented (ADR-0004) and Directive 4 part one (ADR-0005: kernel.lease fenced lease plane; 194/194 tests). Next kernel units: Directive 4 part two (durable claims plane + wire assert_current/fencing into TaskEngine write paths), then Directive 5 (provenance-gated worktree destruction in kernel.worktree).
3. Optional lint polish: ~15 deliberate ruff residuals in src (BLE001/PLW1510/etc.) and ~20 in tests — whitelist with per-line noqa+reason or fix, when touching those files anyway. mypy strict is at zero for src/gnosis.
4. M4 memory-provider selection criteria written (ADR-0003); execute the M4 benchmark itself when memory adapters become the active milestone.
5. Restart Claude Code once so the `.mcp.json` memory servers (zerker-memory, m3-memory) attach; smoke one MCP tool call each.
6. Resume kernel build sequence (MASTER_AUTONOMOUS_BUILD_DIRECTIVE Phase 1+) — gates are open once archaeology lands.
7. Optional, evidence-gated: Graphify benchmark vs Sverklo/CodeGraph (only per MEMORY_FABRIC.md rule, after GNOSIS-Bench exists).
8. Consider upstream bug reports (with operator approval): zmem Windows diagnostic crash; m3 `--database` provisioning gap.
9. Operator decision: delete or relocate the unrelated `security-audit/` leftovers.
