# GNOSIS Next Actions — Nicol workstation

1. ~~codex login~~ DONE ("Logged in using ChatGPT"). When quota resets (2026-08-20): smoke `codex exec --sandbox read-only --json` once, then run the parked adversarial review over the kernel-hardening commits (843a72e, 1e176a9) via the codex-adversarial-reviewer flow.
2. **Adapter milestone, 1 of 4 done** (ADR-0013; suite 462/462). The PolicyEngine is wired to `before_agent_run` and reachable from `DirectorOrchestrator`. Next, in order: (a) `InteractionStore` into `ClaudeCodeCLIRunner` so real runs record/replay; (b) `ConvergenceLoop` onto real reviewer/fixer adapters; (c) the hold/park plane and `boot_sweep` under a scheduler. Directive 9's rule governs: a mechanism nothing calls is a parallel fiction, so prefer wiring over documenting — and per L-0006, wiring it to the kernel primitive is not enough, it must be exercised from the outermost production entry point. Also deferred by decision: per-epoch worktrees (rejected for V1); RunStore-internal token verification (multi-process worker milestone); the M4 memory-provider benchmark (ADR-0003 criteria).
3. Optional lint polish: 20 pre-existing ruff residuals repo-wide (BLE001/PLW1510/TRY004/UP046-47), none in files touched by ADR-0011..0013 — whitelist with per-line noqa+reason or fix, when touching those files anyway. mypy strict is at zero for src/gnosis.
4. M4 memory-provider selection criteria written (ADR-0003); execute the M4 benchmark itself when memory adapters become the active milestone.
5. Restart Claude Code once so the `.mcp.json` memory servers (zerker-memory, m3-memory) attach; smoke one MCP tool call each.
6. Resume kernel build sequence (MASTER_AUTONOMOUS_BUILD_DIRECTIVE Phase 1+) — gates are open once archaeology lands.
7. Optional, evidence-gated: Graphify benchmark vs Sverklo/CodeGraph (only per MEMORY_FABRIC.md rule, after GNOSIS-Bench exists).
8. Consider upstream bug reports (with operator approval): zmem Windows diagnostic crash; m3 `--database` provisioning gap.
9. Operator decision: delete or relocate the unrelated `security-audit/` leftovers.
