# GNOSIS Next Actions — Nicol workstation

1. ~~codex login~~ DONE; quota confirmed restored 2026-08-20 and the parked policy-gate review was run (FAIL, 7 findings, all adjudicated — transcript in `.gnosis/lab/kernel-reviews/codex-review-2026-08-20-policy-gate.jsonl`). ~~Codex RATE_LIMITED until 2026-09-19~~ **RESOLVED 2026-08-21**: the operator re-ran `codex login` and quota returned. The parked review of the convergence adapters ran immediately (FAIL, 8 findings, all repaired — ADR-0015 addendum 2); the scheduler review ran too (FAIL, 9 findings, all repaired — ADR-0016 addendum). **Both review debts are now paid; no unreviewed unit remains.** Historical note, kept because the failure mode will recur: **Codex reported a month-long reset** (reported reset "Sep 19th, 2026 2:52 AM" — a month, not a day; it ran out mid-review of the replay wiring, transcript `.gnosis/lab/kernel-reviews/codex-review-2026-08-20-replay-runner.jsonl`). Per rule 6 this is a park, not a failure: and the internal reviewer subagents separately died with "out of usage credits", so for a stretch there was no independent review channel at all and two units (ADR-0015, ADR-0016) shipped self-reviewed. L-0016 measures what that cost: the self-review of ADR-0015 found 3 real defects and missed 8, including a rule-9 bypass reachable with an accent in a filename. When a channel is down, units still ship — but the ADR says so, and the debt goes here. Still parked for Codex: the replay-wiring review it could not finish, and the earlier kernel-hardening commits (843a72e, 1e176a9).
2. **Adapter milestone COMPLETE** (ADR-0013..0016; 552 tests). All four mechanisms Directive 9 found unwired now have production callers: the policy gate (reachable from `DirectorOrchestrator`), record/replay (`recording_orchestrator()`), convergence (`CliReviewer`/`CliFixer`), and the hold/park plane (`TaskScheduler`). ~~Next: integration~~ **DONE** (ADR-0017): `GovernedPipeline` runs a brief through schedule → implement → converge → report, with every agent launch gated. ~~Next: integration of results~~ **DONE** (ADR-0018): `WorkIntegrator` lands converged work by fast-forward to an already-verified merge on a named branch. ~~Next: multi-worker plane~~ **PART 1 DONE** (ADR-0019): durable queue with fenced claims, crash recovery, and a durable per-brief budget. ~~Next: cross-task ordering~~ **DONE** (ADR-0020). **Next, by decision: re-review as evidence** — a stale-review task can only be authorised by task id today, which records an operator's decision but not a new verdict. Representing re-review properly (a second independent verdict against the NEW tree, recorded like any other evidence) is what closes L-0027. After that: worker supervision and backoff, `probe()` having an automatic caller, and multi-credential rotation. Second priority: pay down the two independent-review debts (ADR-0015 and ADR-0016 shipped self-reviewed) as soon as a review channel reopens. Directive 9's rule governs: a mechanism nothing calls is a parallel fiction, so prefer wiring over documenting — and per L-0006, wiring it to the kernel primitive is not enough, it must be exercised from the outermost production entry point. Also deferred by decision: per-epoch worktrees (rejected for V1); RunStore-internal token verification (multi-process worker milestone); the M4 memory-provider benchmark (ADR-0003 criteria).
3. Optional lint polish: 20 pre-existing ruff residuals repo-wide (BLE001/PLW1510/TRY004/UP046-47), none in files touched by ADR-0011..0013 — whitelist with per-line noqa+reason or fix, when touching those files anyway. mypy strict is at zero for src/gnosis.
4. M4 memory-provider selection criteria written (ADR-0003); execute the M4 benchmark itself when memory adapters become the active milestone.
5. Restart Claude Code once so the `.mcp.json` memory servers (zerker-memory, m3-memory) attach; smoke one MCP tool call each.
6. Resume kernel build sequence (MASTER_AUTONOMOUS_BUILD_DIRECTIVE Phase 1+) — gates are open once archaeology lands.
7. Optional, evidence-gated: Graphify benchmark vs Sverklo/CodeGraph (only per MEMORY_FABRIC.md rule, after GNOSIS-Bench exists).
8. Consider upstream bug reports (with operator approval): zmem Windows diagnostic crash; m3 `--database` provisioning gap.
9. Operator decision: delete or relocate the unrelated `security-audit/` leftovers.

## Exact next command

```bash
export PATH="$HOME/.local/bin:$PATH" PYTHONUTF8=1
cd "C:/Users/nicol/Desktop/Claude Code Proyectos/GnosisAgentAi"
uv run --no-project --with pytest --with mypy --with ruff python scripts/capture_evidence.py
```

Green baseline first (662 passed, mypy clean, ruff at baseline), then
**re-review as evidence**. Read ADR-0020's Known limitations and L-0027:
a review is evidence about a specific tree and expires when that tree
moves, and today the only way past that is an operator authorising a
task id — a decision, not a verdict. The work is to run the independent
reviewer again against the merged-or-rebased tree and record the result
where convergence records its own.
