# F-33 Stage 2A — Final Qualification Evidence

Result: **PASS (Stage 2A QUALIFIED)** — F-33 remains **OPEN** by policy; **Stage 2B NOT AUTHORIZED**.

## Identity / tree
- Starting HEAD (pre-slice): `08543cbae14356e246bd0020b98879e1b42cac73`
- Commit A (integration + hardening + tests + probe): `93c70b3ab26e585aa47f43b42fb46cfb508eae17`
- `src/gnosis` tree object at Commit A: `7808facd2a30c28d2f99001dca50fb2a9c164d47`
- This is a **new Stage-2A tree identity**; the historical F-17 deployment digest and the
  port-only Stage-2A identity are NOT reused. Final *composed* deployment measurement
  (canonical operator composition) is **deferred to Stage 2C** (Stage 2B owns the
  composition root).

## Integration (how the pipeline reaches the seam)
- New `TrustedExecutionRunner` (`src/gnosis/director/trusted_runner.py`) implements the
  engine's duck-typed `cli_runner.run(...) -> ExecutionResult` and routes ONLY through
  `TrustedExecutionPort.execute(DETERMINISTIC)`.
- Realized **by dependency injection** (ADR-0032 §5 intent): injected as
  `TaskEngine.cli_runner`, the governed path is
  `GovernedPipeline._implement -> scheduler.submit -> TaskEngine.execute_task ->
  cli_runner.run -> TrustedExecutionPort.execute -> WorkerLauncher.launch -> Worker`.
- `pipeline.py`, `engine.py`, `pyproject.toml`, `src/gnosis/trust/*` are **unchanged** by
  this slice (diff = NONE): the seam is additive; the composition root that makes the
  trusted runner the sole default is Stage 2B.

## Seam hardening
- H1 bounded Worker stdout (`MAX_RESULT_BYTES`, fail closed past it).
- H2 CLOSED deterministic cassette schema (`{schema, turns[{message}]}`; unknown top-level
  AND nested keys rejected; turn/message bounds).
- H3 duplicate-JSON-key rejection (cassette + result parsing).
- H4 expected-cassette-digest binding (Director digests the sealed bytes before launch and
  requires the Worker's self-reported digest to equal it; TOCTOU -> fail closed). Closed
  result schema rejects unknown result keys.

## Governance semantics (preserved)
- Verifier still REQUIRED through the trusted seam (P6).
- `implementer is reviewer -> fail closed` identity floor intact (P7).
- DirectorOrchestrator NOT the canonical route (P8).
- Worker output classified UNTRUSTED: never manufactures verification / review / authority /
  publication / ANCHORED / deployment identity (P5).

## Tests
- New + integration (targeted): **52 passed, 8 subtests** — `test_execution_port.py`,
  `test_deterministic_worker.py`, `test_trusted_runner.py`, `test_pipeline_trusted_execution.py`.
- Regression subset (pipeline/engine/scheduler/worker_launcher/director_orchestrator):
  **251 passed, 1 skipped** (non-Windows refusal path).
- Full suite: **1562 passed, 1 skipped, 269 subtests, exit 0** (545s).
- `mypy --strict src`: **Success, 82 source files**.
- Ruff: all changed files **clean**; 19 pre-existing baseline findings in unrelated files
  left untouched (§26).

## Applied-mutant sweep (A1–A9) — 10/10 CAUGHT
Behavioral / logic mutants (caught by behavioral negative tests):
- A2 swallow port failure (failed result -> exit 0) — CAUGHT
- A3 accept oversized Worker stdout — CAUGHT
- A4a accept unknown top-level cassette key — CAUGHT
- A4b accept unknown NESTED turn key (authority smuggle) — CAUGHT
  (initial harness run showed a false SURVIVED from a `.pyc` bytecode-cache artifact between
  rapid mutate→restore cycles; isolated re-run with pycache cleared proved CAUGHT.)
- A5 accept duplicate JSON cassette key — CAUGHT
- A6 skip expected cassette digest comparison — CAUGHT
- A7 accept malformed (extra-field) Worker result — CAUGHT
- A8 allow governed completion after trusted failure — CAUGHT (pipeline P4)

Structural-guard mutants (reported separately; caught by AST/structural tests):
- A1 bypass port via `import subprocess` in the runner — CAUGHT (P3 AST guard)
- A9 route through DirectorOrchestrator (reference) — CAUGHT (P8 structural guard)

## OS-real pipeline-through-port qualification
Probe: `scripts/probe_f33_stage2a_pipeline_composition.py` (does NOT call `port.execute`
directly — drives `engine.cli_runner` = the integrated `TrustedExecutionRunner`).
Evidence: `docs/evidence/20260901T061539Z-f33-stage2a-pipeline/`.
- COMPOSE: `engine.cli_runner IS TrustedExecutionRunner` — PASS
- RUN #1 (`engine.cli_runner.run` over the REAL boundary): succeeded; observed SID ==
  disposable Worker SID `…-1038` (≠ Director `…-1000`); non-admin; contained in job;
  provider_calls = 0 — PASS
- RUN #2 (`engine.execute_task` governed verdict via the seam): `TaskState.COMPLETED` — PASS
- RUN #3 (integrated seam propagates a REAL Worker failure): FAILED / fail-closed — PASS
- F-17 implementation diff: NONE
- Temporary Worker rollback: **PASS** (account absent, probe root removed, DPAPI blob absent,
  no residue). Provider calls = 0.

M5 note (evidence honesty): the sealed `LaunchSpec -> seal/digest -> WorkerLauncher ->
bootstrap` path was **exercised OS-real**; a tamper-negative mutant was **not applied in these
F-33 probes** (`OS-REAL PATH EXERCISED — TAMPER NEGATIVE NOT APPLIED IN F-33 PROBE`).
Historical F-17 tamper evidence exists separately and is not re-claimed as newly executed.

## Disclosed deferred debt
Stage 2B (composition):
- canonical operator entry / `[project.scripts]`
- production composition root (default-inject the trusted runner)
- publication seam (`authorize_publishable` / `Publisher` / anchor / ANCHORED)
- `python_executable` binding to deployment/config (`STAGE-2B COMPOSITION BINDING REQUIREMENT`)
- mandatory production non-placeholder attribution gate (not created in Stage 2A →
  `PLACEHOLDER ATTRIBUTION GATE: DEFERRED TO STAGE 2B COMPOSITION`)
- PROVIDER_BACKED execution mode (deterministic route is sufficient for Stage 2A)

Beyond F-33 (if accepted): stronger underlying implementer/reviewer principal identity
contract (NEW IDENTITY CONTRACT).

Stage 2C: final composed deployment measurement.
