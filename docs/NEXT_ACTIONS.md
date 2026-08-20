# GNOSIS Next Actions — Nicol workstation

1. ~~codex login~~ DONE ("Logged in using ChatGPT"). When quota resets (2026-08-20): smoke `codex exec --sandbox read-only --json` once, then run the parked adversarial review over the kernel-hardening commits (843a72e, 1e176a9) via the codex-adversarial-reviewer flow.
2. **All nine archaeology directives are implemented** (ADR-0004..0012; suite 431/431). Next milestone by decision: the **adapter milestone**, which is where three tracked mechanisms stop being islands — wire InteractionStore into ClaudeCodeCLIRunner (record/replay real runs), ConvergenceLoop onto real reviewer/fixer adapters, and the PolicyEngine into actual intervention points before tool execution. Directive 9 showed the pattern: a mechanism nothing calls is a parallel fiction, so prefer wiring over documenting. Also deferred by decision: per-epoch worktrees (rejected for V1); RunStore-internal token verification (multi-process worker milestone); the M4 memory-provider benchmark (ADR-0003 criteria).
3. Optional lint polish: ~15 deliberate ruff residuals in src (BLE001/PLW1510/etc.) and ~20 in tests — whitelist with per-line noqa+reason or fix, when touching those files anyway. mypy strict is at zero for src/gnosis.
4. M4 memory-provider selection criteria written (ADR-0003); execute the M4 benchmark itself when memory adapters become the active milestone.
5. Restart Claude Code once so the `.mcp.json` memory servers (zerker-memory, m3-memory) attach; smoke one MCP tool call each.
6. Resume kernel build sequence (MASTER_AUTONOMOUS_BUILD_DIRECTIVE Phase 1+) — gates are open once archaeology lands.
7. Optional, evidence-gated: Graphify benchmark vs Sverklo/CodeGraph (only per MEMORY_FABRIC.md rule, after GNOSIS-Bench exists).
8. Consider upstream bug reports (with operator approval): zmem Windows diagnostic crash; m3 `--database` provisioning gap.
9. Operator decision: delete or relocate the unrelated `security-audit/` leftovers.
