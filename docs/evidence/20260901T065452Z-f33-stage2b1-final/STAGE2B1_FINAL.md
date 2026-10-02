# F-33 Stage 2B.1 — Canonical Production Composition — Final Evidence

Result: **PASS (Stage 2B.1 QUALIFIED)** — F-33 remains **OPEN**; **Stage 2B.2 NOT AUTHORIZED**;
operator entry and publication success path remain **NOT IMPLEMENTED**.

## Stage-2A honesty correction (carried forward)
- Applied/behavioral mutants **A2–A8 CAUGHT**; **A1/A9** are structural-guard catches (not applied
  behavioral mutants); **SURVIVED = 0** (A4b's first-pass "SURVIVED" was a `.pyc` cache artifact,
  corrected to CAUGHT on isolated re-run). Historical raw evidence unchanged.
- First OS-real pipeline probe run left read-only `.git` objects in the temporary probe root; the
  account + DPAPI blob cleanup succeeded, the residue was subsequently removed, the superseded
  bundle discarded, and the final qualification rollback was clean. Provenance preserved.

## Identity / tree
- Starting HEAD (pre-2B.1): `b39946c9030bed25a830a581242a0e08a03d9ec5`
- Commit A (composition + tests): `3bdef0e63b6177462e669c37404725f28783e895`
- `src/gnosis` tree at Commit A: `78e3b281b0e4d2d2616bd1e547c68c43cbf5c716` (new Stage-2B.1
  identity; historical F-17 digest and the Stage-2A tree identity are NOT reused). Final composed
  deployment measurement remains **Stage 2C**.

## Canonical factory
- Path/symbol: `src/gnosis/director/composition.py` → `build_production_composition(config) -> GovernedPipeline`.
- Files created: `src/gnosis/director/composition.py`, `tests/test_composition.py`. Files modified: **none**
  (additive slice; `pipeline.py`/`engine.py`/`src/gnosis/trust/*`/`pyproject.toml` diff = NONE).

## Canonical dependency graph
`build_production_composition` →
`GovernedPipeline(director_root, scheduler, repo_path, verifier, policy, review_runner, policy_actor,
reviewer_id, worktrees)` where
`scheduler = TaskScheduler(engine, run_store, holds, credential)` and
`engine = TaskEngine(run_store, cli_runner = TrustedExecutionRunner)` and
`TrustedExecutionRunner(TrustedExecutionPort(launcher = TrustedWindowsWorkerLauncher, python_executable))`.

## Trusted-runtime binding (deployment-derived)
- `python_executable` is bound to `DeploymentLayout.runtime_executable`, measured/validated by the
  existing `trust.deployment.observe_runtime` qualification contract (byte-measured, absolute,
  OS-resolved). No PATH lookup, no operator flag, no environment override; a relative or
  non-interpreter path fails closed. `trusted_deployment_from_layout` consumes the existing
  `DeploymentLayout` + persisted `config.json` (`ServiceConfig.authorized_worker_sid`) — no second
  trusted-runtime registry.
- **Disclosure (§8):** F-17 does not persist a single manifest bundling every launcher input; the
  factory consumes the existing artifacts (`DeploymentLayout`, `config.json`/`ServiceConfig`,
  `observe_runtime`). The runtime binding contract itself is present, so this is NOT
  `TRUSTED RUNTIME BINDING CONTRACT MISSING`; bundling all launcher inputs into one persisted
  manifest is a deployment-tooling improvement for Stage 2B.2, not a 2B.1 blocker.

## Attribution (mandatory, §17)
- `reviewer_id` / `policy_actor` required and **non-placeholder**; rejects at least `"claude-cli"`
  and `"agent://unattributed"`, plus empty/whitespace. Sourced from `AttributionInputs` (trusted
  config), never Worker output or brief.
- Identity floor preserved: implementer is always the fresh internal `TrustedExecutionRunner`, and
  the factory additionally refuses `review_runner is implementer` at construction (defence in depth,
  on top of the GovernedPipeline `is` gate). No stronger underlying-principal contract claimed (§10).

## Startup fail-closed matrix (tests C1–C10, all pass)
C1 invalid/relative deployment runtime · C2 missing worker credential blob · C3 missing verifier ·
C4 same implementer/reviewer object · C5 empty reviewer_id · C6 empty policy_actor ·
C7 placeholder reviewer_id · C8 placeholder policy_actor · C9 unsupported execution mode ·
C10 invalid repo path. No weaker fallback on any.

## Tests / gates
- Targeted (composition + F-33 slice): **69 passed, 8 subtests**.
- Full suite (authoritative rerun): **1579 passed, 1 skipped, 267 subtests, exit 0** (`full_suite.txt`).
  An earlier run of the same suite showed **one** failure in the pre-existing FLAKY concurrency test
  `tests/test_work_queue.py::TestConcurrentRecovery::test_a_brief_never_ends_up_in_two_directories_at_once`
  (a timing-sensitive recovery test); it passed 6/6 in isolation and the clean authoritative rerun
  above has it green. It is independent of this additive-only slice (zero existing production files
  modified — a new unimported module cannot affect it).
- `mypy --strict src`: **Success, 83 source files**.
- Ruff: all changed files **clean**; pre-existing baseline findings in unrelated files untouched (§31).

## Applied-mutant sweep (B1–B9) — 9/9 CAUGHT
Behavioral (killer test): B1 legacy runner instead of trusted → positive · B2 arbitrary executable
(skip measurement) → C1 · B3 missing verifier → C3 · B4 same impl/reviewer → C4 · B5 placeholder
reviewer → C7 · B6 placeholder policy_actor → C8 · B7 accept missing worker-launch infra → C2 ·
B9 unsupported mode → C9.
Structural guard (reported separately): B8 reference `DirectorOrchestrator` → AST import/name/attr
guard (strengthened to catch import aliases, not only Names).

## OS-real composition construction (§32)
**Deferred with explanation.** At composition-construction time no Worker is launched, so there is
no additional OS-real property beyond Stage 2A: the deployment-derived runtime binding is already
exercised via `observe_runtime` over a real interpreter in unit tests, and the actual launch through
this exact `TrustedExecutionRunner → TrustedExecutionPort → F-17 launcher` seam was OS-real-qualified
in Stage 2A (bundles `…-f33-stage2a-osreal`, `…-f33-stage2a-pipeline`). Full composed OS-real E2E is
deferred to Stage 2B.2 / 2C.

## Guards
- Provider calls: **0**. F-17 `src/gnosis/trust/*` implementation diff: **NONE**.
- `[project.scripts]` / operator CLI: **NOT IMPLEMENTED**. Publication seam / ANCHORED success path:
  **NOT IMPLEMENTED**.
- No F-35–F-40 implemented or depended upon.

## Deferred (unchanged from Stage 2A + this stage)
Stage 2B.2: operator CLI (`gnosis run`/`submit`, `[project.scripts]`), publication seam
(`authorize_publishable → Publisher → anchor → ANCHORED`), a persisted bundled deployment/launcher
manifest. Stage 2C: final composed deployment measurement/digest. Beyond F-33 (if accepted):
stronger underlying implementer/reviewer principal identity contract.
