# GNOSIS Project State

**Status:** PHASE -1 COMPLETE; NINE KERNEL-HARDENING DIRECTIVES IMPLEMENTED; ADAPTER MILESTONE COMPLETE (4/4)
**Target machine:** Nicol
**Phase:** 1 — Kernel hardening per archaeology directives
**Last update:** 2026-08-20

## Kernel hardening (post-Phase -1)

Archaeology Directives 1–5 are implemented, each unit adversarially
reviewed (multi-agent workflow + refutation verify) with all confirmed
findings repaired pre- or immediately post-commit:

- ADR-0004: `kernel.canonical` single hash contract; hash-chained
  `RunLedger` with fail-closed full-chain verification; frozen transition
  tables (commit 843a72e).
- ADR-0005: `kernel.lease` fenced expiring leases, NO STALE WRITE
  test-enforced (1e176a9).
- ADR-0006: `kernel.claims` durable CAS claims + `WorkAuthority` +
  `GrantHeartbeatPump`; engine write paths fenced (ed32fa2 + repairs in
  2c50a8c). Includes the first independent **Codex** adversarial review
  (FAIL verdict, 3 findings verified true and fixed — notably the
  no-verifier INVALID DONE gate). Raw transcript:
  `.gnosis/lab/kernel-reviews/`.
- ADR-0007: provenance-gated worktree lifecycle (8ec4bfd; 13/14 review
  findings confirmed and repaired, incl. destruction reordering and the
  autosave conflict-gate holes).
- ADR-0008: `kernel.convergence` review-convergence loop (ac76d89; dual review Codex+workflow, 9/9 findings confirmed and repaired — incl. verification flip-detection and strict consecutive-evidence stalemate counting; also fixed two latent git_evidence bugs).
- ADR-0009: governed execution isolation (0efd12a) — worktree-scoped
  execution for governed runs, ownership enforced at the run-store
  boundary, governance-aware orchestrator. Closes the ADR-0006/0007
  structural follow-ups. Dual review: 19 findings, all repaired (incl. a
  heartbeat-pump leak that made a task permanently unreclaimable).
- ADR-0010: strict replay + write-ahead intent (65cef20) — occurrence-aware
  strict-by-default replay and an intent journal that makes rewind safety a
  query. Dual review: 19 findings, all true, all repaired (two criticals
  reproduced: a string mode silently downgraded strict replay to a live
  call; unserializable metadata destroyed the row for a call that happened).
- ADR-0011: fail-closed policy engine + falsifiable enforcement matrix
  (c64b8da, repairs c26f84b). Dual review: 24 findings, all true — a one-
  character quote bypassed every path rule, and an unserializable payload
  made the gate raise instead of deny.
- ADR-0012: typed failure taxonomy wired end-to-end (9d963aa) — graded
  classification, RATE_LIMITED as a credential-scoped park state,
  recovery-as-reconcile. Codex found it was UNWIRED; fixed by wiring the
  engine's retry decision onto the classification, not by documenting it.
- L-0004: a refuted review finding resurrected as a real bug (shared
  FileLock instances) — refutation assumptions are now recorded.

## Adapter milestone (COMPLETE)

The four mechanisms that existed but nothing called. Directive 9's rule
governs the order of work here: **prefer wiring over documenting**.

- [x] **PolicyEngine → a real intervention point** (ADR-0013). The gate
  runs at `before_agent_run` before any process that could act on the
  repository or on the agent's behalf, again after kernel context is
  prepended, and again before every retry; refusals are durable evidence
  (`policy.decision` + classification + `escalations/` file). Enableable
  from `DirectorOrchestrator`, the path real briefs travel. **Two
  independent reviews, and both found the headline invariant false**: the
  workflow review (21 findings, adjudicated by hand after the verify
  phase died on quota) caught code intelligence shelling out before the
  gate and no production path being able to enable it; Codex then caught
  `git worktree add` still running first, retries riding the first
  attempt's authorization, and the identity not binding the workspace.
  All repaired. What cannot be enforced (rule purity, the opt-in gate) is
  recorded in the enforcement matrix rather than implied away. See
  L-0005..L-0010, D-018..D-020.
- [x] **`InteractionStore` → the real CLI runner** (ADR-0014).
  `ReplayingCLIRunner` records and replays actual runs byte-exact,
  reproducing the stdout/stderr files the engine reads, and is reachable
  from `recording_orchestrator()`. **Independent review returned FAIL
  with 8 reproducible defects**, all repaired — the critical one being
  that the cassette key was computed from the tree the recorded agent
  itself mutates, so no recording of a repo-mutating agent replayed past
  its first call (L-0012). The review also caught the test that "proved"
  the wiring using a stand-in incapable of exhibiting the failure
  (L-0013), and the evidence line being self-reported prose — hence
  `scripts/capture_evidence.py` and D-023.
- [x] **`ConvergenceLoop` → real reviewer/fixer adapters** (ADR-0015).
  New `gnosis/adapters/` package (nothing in `kernel/` imports it, which
  is what makes provider-neutrality checkable). Rule 9 is enforced twice
  at two honest strengths: edit tools withheld (the provider's promise)
  AND a before/after workspace fingerprint that refuses a reviewer which
  moved the tree (the kernel's evidence, recorded as SANDBOX_APPROX
  because detection is not prevention). An unreadable review raises
  rather than becoming a verdict nobody gave; an unreadable FIX report is
  inconclusive rather than `cannot_fix`, because `cannot_fix` ends the
  loop. **Codex review 2026-08-21: FAIL, 8 findings, all repaired** —
  including a rule-9 bypass reachable with nothing but an accent in a
  filename (`git status` C-quotes non-ASCII paths, and the failure to
  read one was stored as a *stable* value), an object quoted in prose
  parsing as a verdict, and duplicate JSON keys resolving in the
  author's favour. The earlier self-review found 3 real defects and
  missed these 8 — see L-0016.
- [x] **Hold/park plane + `boot_sweep` under a scheduler** (ADR-0016).
  `TaskScheduler` consults holds before a launch (a refusal PARKS, never
  fails), places a durable hold when a run classifies RATE_LIMITED, and
  sweeps stranded runs at boot. Self-review found `probe()` was inert —
  a PROBE row could never narrow an ACCOUNT hold under the
  most-restrictive rule — so the store now separates observations (which
  compete) from decisions (which supersede, with a reason). No
  independent review: both channels are unavailable.

Suite: **559 tests, all passing**; mypy strict clean (47 files); ruff at
the recorded backlog baseline (19 pre-existing findings in untouched
files, ratcheted down from 20; `.gnosis/state/lint_baseline.json` fails the run if it rises).
Captured transcript, not prose: `.gnosis/evidence/20260820T235355Z/`.

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
- [x] Codex CLI installed (0.148.0) and authenticated ("Logged in using ChatGPT", 2026-08-19 evening). Usage quota exhausted until 2026-08-20; adversarial review parked as RATE_LIMITED until then.
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
