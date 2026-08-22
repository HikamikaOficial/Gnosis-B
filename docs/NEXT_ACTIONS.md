# GNOSIS Next Actions — Nicol workstation

1. ~~codex login~~ DONE; quota confirmed restored 2026-08-20 and the parked policy-gate review was run (FAIL, 7 findings, all adjudicated — transcript in `.gnosis/lab/kernel-reviews/codex-review-2026-08-20-policy-gate.jsonl`). ~~Codex RATE_LIMITED until 2026-09-19~~ **RESOLVED 2026-08-21**: the operator re-ran `codex login` and quota returned. The parked review of the convergence adapters ran immediately (FAIL, 8 findings, all repaired — ADR-0015 addendum 2); the scheduler review ran too (FAIL, 9 findings, all repaired — ADR-0016 addendum). **Both review debts are now paid; no unreviewed unit remains.** Historical note, kept because the failure mode will recur: **Codex reported a month-long reset** (reported reset "Sep 19th, 2026 2:52 AM" — a month, not a day; it ran out mid-review of the replay wiring, transcript `.gnosis/lab/kernel-reviews/codex-review-2026-08-20-replay-runner.jsonl`). Per rule 6 this is a park, not a failure: and the internal reviewer subagents separately died with "out of usage credits", so for a stretch there was no independent review channel at all and two units (ADR-0015, ADR-0016) shipped self-reviewed. L-0016 measures what that cost: the self-review of ADR-0015 found 3 real defects and missed 8, including a rule-9 bypass reachable with an accent in a filename. When a channel is down, units still ship — but the ADR says so, and the debt goes here. Still parked for Codex: the replay-wiring review it could not finish, and the earlier kernel-hardening commits (843a72e, 1e176a9).
2. **Adapter milestone COMPLETE** (ADR-0013..0016; 552 tests). All four mechanisms Directive 9 found unwired now have production callers: the policy gate (reachable from `DirectorOrchestrator`), record/replay (`recording_orchestrator()`), convergence (`CliReviewer`/`CliFixer`), and the hold/park plane (`TaskScheduler`). ~~Next: integration~~ **DONE** (ADR-0017): `GovernedPipeline` runs a brief through schedule → implement → converge → report, with every agent launch gated. ~~Next: integration of results~~ **DONE** (ADR-0018): `WorkIntegrator` lands converged work by fast-forward to an already-verified merge on a named branch. ~~Next: multi-worker plane~~ **PART 1 DONE** (ADR-0019): durable queue with fenced claims, crash recovery, and a durable per-brief budget. ~~Next: cross-task ordering~~ **DONE** (ADR-0020). ~~Next: worker supervision and backoff~~ **DONE** (ADR-0022, self-reviewed only). ~~Next: `probe()` having an automatic caller~~ **DONE** (ADR-0023). ~~Next: multi-credential rotation~~ **DONE** (ADR-0024) — with it the ADR-0016 residuals are closed. **Next, by decision: pay down the review debt.** Three consecutive units (ADR-0022, 0023, 0024) shipped self-reviewed because Codex refuses on a usage limit, and they touch ownership, spending and credentials — exactly what rule 10 says needs independent judgement. Directive 9's rule governs: a mechanism nothing calls is a parallel fiction, so prefer wiring over documenting — and per L-0006, wiring it to the kernel primitive is not enough, it must be exercised from the outermost production entry point. Also deferred by decision: per-epoch worktrees (rejected for V1); RunStore-internal token verification (multi-process worker milestone); the M4 memory-provider benchmark (ADR-0003 criteria).
3. Optional lint polish: 20 pre-existing ruff residuals repo-wide (BLE001/PLW1510/TRY004/UP046-47), none in files touched by ADR-0011..0013 — whitelist with per-line noqa+reason or fix, when touching those files anyway. mypy strict is at zero for src/gnosis.
4. M4 memory-provider selection criteria written (ADR-0003); execute the M4 benchmark itself when memory adapters become the active milestone.
5. Restart Claude Code once so the `.mcp.json` memory servers (zerker-memory, m3-memory) attach; smoke one MCP tool call each.
6. Resume kernel build sequence (MASTER_AUTONOMOUS_BUILD_DIRECTIVE Phase 1+) — gates are open once archaeology lands.
7. Optional, evidence-gated: Graphify benchmark vs Sverklo/CodeGraph (only per MEMORY_FABRIC.md rule, after GNOSIS-Bench exists).
8. Consider upstream bug reports (with operator approval): zmem Windows diagnostic crash; m3 `--database` provisioning gap.
9. Operator decision: delete or relocate the unrelated `security-audit/` leftovers.

## Current unit: the traceability audit

`docs/V1_TRACEABILITY_AUDIT.md` (frozen at `83ae84e`) carries 42 findings.
`docs/V1_COMPLIANCE_MATRIX.md` is the LIVING matrix — a row changes only
when an ADR with captured evidence backs it.

- **F-34 CLOSED (2026-08-22), fourth independent review PASS.**
  ADR-0025 (`29d3666`) closed the reachable production route; an
  independent Codex review returned **FAIL PARCIAL** because the state
  authority itself still admitted `VERIFYING -> COMPLETED` with no
  evidence, and `6c4859a` closed that. A **second** independent review
  returned **FAIL PARCIAL** again: `state`/`completion_evidence` were
  still public attributes (`sm.state = TaskState.COMPLETED` reached a
  terminal DONE past every guard), and the engine's report printed
  `PASSED` for a `VerificationResult(passed=1)` the authority had just
  rejected. Both repaired in this unit — private storage behind read-only
  properties, and `verification_verdict()` as the single reader of
  `passed` with a third answer, MALFORMED, that the ledger, the report
  and the completion predicate all derive from. Six mutants captured,
  none survived. Evidence `.gnosis/evidence/20260822T162729Z/` (822
  passed, 60 subtests, clean tree at `1591aa7`). A **third** independent
  review then returned **FAIL CRÍTICO**: `CompositeVerifier` read its
  members with `all(r.passed for r in results)` and returned a fresh
  `VerificationResult(passed=True)`, so a `passed` of `1` reached
  `TaskState.COMPLETED` and `ReportStatus.COMPLETED` with every strict
  reader downstream behaving correctly — and `CompositeVerifier("empty",
  [])` passed on `all([]) is True`, having run nothing. The three readers
  listed below as "candidate findings" were still live. Repaired in this
  unit: `MalformedEvidence` makes "states no verdict" a TYPE that
  `verification_verdict` classifies MALFORMED by construction;
  `Verifier.run` returns `Evidence`, so mypy enumerates the readers;
  `CompositeVerifier` refuses an empty collection at construction and
  never converts a malformed member into a verdict; `ConvergenceLoop`,
  `WorkIntegrator`, `cli_review` and `GovernedPipeline` each fail closed
  with a differentiable reason. Nine mutants, none survived, and the
  mutation check is now a committed script
  (`scripts/mutation_check.py`). Evidence
  `.gnosis/evidence/20260822T181937Z/` (874 passed, 60 subtests, clean
  tree at `9c6064c`). A **fourth** independent review then read code
  `9c6064c` against evidence `f02e18e` and returned **PASS**: both
  critical reproductions fail closed, the empty composite raises
  `EmptyCompositeError` at construction, convergence, integration, the
  pipeline and `cli_review` all decide on the strict verdict, and no
  productive reader of `.passed` decides outside `verification_verdict()`
  — verified by the reviewer's own run (249 tests, 39 subtests targeted),
  not by the author's transcript. No new findings in scope. **F-34 is
  closed**, by the rule that a finding closes when an independent review
  returns without findings. **Next action: the next audit finding, by
  direction** — nothing about F-34 remains to do.
- **The three truthy readers round 2 deferred are now REPAIRED**, not
  deferred again: `kernel/convergence.py` (one verdict per round, the
  flip memo holds verdicts, malformed verification is a typed evidence
  failure), `kernel/integration.py` (landing gated on
  `verification_verdict(...) is PASSED`, with `VERIFICATION_INVALID` as
  its own outcome) and `adapters/cli_review.py`
  (`verification_prompt_line`, three answers). L-0048 records why naming
  them and deferring them was not enough.
- **The count, so no living document repeats it wrong again:** the frozen
  audit holds **43 items** (F-01..F-42 plus F-29b). **6 are PASS** and are
  not defects (F-06, F-09, F-11, F-29b, F-41, F-42); **1 is closed**
  (F-34); **36 are open**. History of this count, because it has been
  wrong twice: one version said 41, counting the PASS items and F-34 as
  work; one said "1 closed (F-34)" before the third review reopened it;
  one said "0 closed, 37 open", correct while F-34 was reopened. The live
  count is **6 PASS · 1 closed · 36 open**. Direction sets the order;
  nothing outside F-34 was touched in any of the four passes,
  deliberately.

- **What the closure does NOT cover**, named here so the next unit does
  not inherit a false floor: **F-36** (no `ProofPacket`); **F-14..F-18**
  (`capture_evidence.py` still records `git status` after the suite and
  never imports `content_fingerprint()` — all four F-34 rounds worked
  around it with an external tree binding, which makes the workaround a
  finding rather than a method); the **`PYTHONUTF8=1` precondition** that
  the suite depends on and nothing in the repo enforces; and **F-33** with
  the thirteen capabilities still inert.

The ones this project's own history says will cost the most:

1. **F-33 — no production entry point.** `GovernedPipeline` is the only
   path that requires verification AND an independent review, and nothing
   constructs it. Thirteen of twenty-two V1 capabilities are correct as
   modules and unreachable as a program. Probably a milestone, not a
   repair.
2. **F-35 — `WorkAuthority.sweep()`'s only caller is `WorkerSupervisor`,
   which nothing constructs.** The repair for "nothing calls it" was a
   caller nothing reaches (L-0033, again). V1 nº19 is still inert.
3. **F-07 / F-08 — the two DURABLE state planes validate nothing.**
   `RunStore.update_state` and `BriefRecordStore.update` write any state
   with no transition table; `RunStateMachine` has no production caller.
   The only validated plane is the one that dies with the process.
4. **F-14..F-18 — the evidence script does not bind bytes.**
   `content_fingerprint()` already exists, is used in four production
   modules, and `capture_evidence.py` does not import it; it also records
   `git status` AFTER the suite. ADR-0025 worked around this with an
   external `f34-tree-binding.json` rather than repairing it, because the
   unit was scoped to F-34.
5. **F-01..F-04 — there is no task DAG.** V1 nº2 and nº3 have no
   implementation; `kernel/ordering.py` orders already-converged tasks
   for landing, which is a different problem.
6. **F-19..F-32 — documentation drift**, including contradictions inside
   this very file (sections 1 and 2 below), the stale 164-test line in
   `PROJECT_STATE.md`, and a `README.md` describing a project twenty ADRs
   ago.

Also still open, from the earlier reviews: the 15 findings listed in
`PROJECT_REPORT.md §8`.

## Exact next command

```bash
cd "C:/Users/nicol/Desktop/Claude Code Proyectos/GnosisAgentAi"
PYTHONUTF8=1 .venv/Scripts/python.exe scripts/capture_evidence.py
```

Green baseline first (874 passed with 60 subtests as of `9c6064c`, mypy
strict clean over 55 files, ruff at the 19-finding baseline), then
**whichever audit finding direction names**.
Do not batch them: the audit was produced one finding at a time and the
repairs are cheaper to review the same way.

