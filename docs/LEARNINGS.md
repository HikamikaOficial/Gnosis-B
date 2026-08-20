# GNOSIS Validated Learnings

Only durable, evidence-backed learnings belong here.

Format:

## L-XXXX — Title
- Status: VERIFIED / PROVISIONAL / STALE
- Evidence:
- Scope:
- Lesson:
- Operational consequence:
- Revalidation condition:

## L-0001 — uv tool shims on Windows break self-re-exec'ing CLIs
- Status: VERIFIED
- Evidence: `.gnosis/lab/memory/results/m3-memory-2026.8.19.16/SCORECARD.md` (python -v trace)
- Scope: any Python CLI that re-execs itself via `sys.orig_argv`/`sys.executable` (m3's UTF-8 relaunch), installed via `uv tool install` on Windows.
- Lesson: the re-exec resolves to the base interpreter without the tool venv → `ModuleNotFoundError` for the tool's own package.
- Operational consequence: `PYTHONUTF8=1` is set user-wide and pinned in `.mcp.json`/tests; any future tool showing "installed but ModuleNotFoundError on itself" gets checked for a self-relaunch first.
- Revalidation condition: uv changes shim/trampoline behavior, or m3 removes the import-time re-exec.

## L-0002 — Windows: closing races between dying children and tempdir cleanup are a recurring class
- Status: VERIFIED
- Evidence: our own `tests/test_cli_runner.py` teardown fix (commit 1f282b9) and zmem 0.1.17's identical crash in `doctor.check_eval → eval.run_eval` (WinError 32 on `memory.sqlite`).
- Scope: any code that deletes a directory while a just-killed process or an unclosed SQLite handle may still hold a file in it.
- Lesson: POSIX allows unlinking open files, Windows does not; tests/tools written on Linux hit this only here.
- Operational consequence: bounded-retry cleanup in our tests; treat third-party diagnostic crashes of this shape as diagnostic-only before downgrading the tool itself (`zmem audit health` is the working Windows probe).
- Revalidation condition: zmem fixes eval.py handle lifetime upstream.

## L-0004 — A refuted review finding is not a dead finding
- Status: VERIFIED
- Evidence: ADR-0006 "Review outcome" §6 — the shared-FileLock finding was refuted by an adversarial verifier ("single-threaded usage"), then proven true days—hours later when the heartbeat pump introduced the second thread and tests crashed exactly as the original reviewer predicted.
- Scope: any adversarial find→refute pipeline.
- Lesson: refutation verdicts encode the *current* usage assumptions; a design change can resurrect a refuted finding. Runtime evidence (a failing test) outranks a verifier's reasoning.
- Operational consequence: refuted findings are recorded with the assumption that killed them (here: "no same-process concurrency"); when that assumption changes, re-check the graveyard before shipping.
- Revalidation condition: standing rule; no expiry.

## L-0003 — m3 `--database` flag does not provision fresh databases
- Status: VERIFIED
- Evidence: `.gnosis/lab/memory/results/m3-memory-2026.8.19.16/SCORECARD.md` (zero tables + "no pending migrations" on a fresh file).
- Scope: m3-memory ≤ 2026.8.19.16.
- Lesson: migration bookkeeping is per-install, not per-target-file; `--database` on a fresh path yields an unmigrated, unusable DB.
- Operational consequence: state isolation only via `M3_MEMORY_ROOT`/`M3_ENGINE_ROOT`/`M3_CONFIG_ROOT` (ADR-0001 §3); guarded by `tests/integration/test_memory_fabric_smoke.py`.
- Revalidation condition: upstream makes `--database` run migrations against the target file.

## L-0005 — "It runs before X" is a claim about the whole call path, not about the line above X
- Status: VERIFIED
- Evidence: ADR-0013 addendum finding 1. The policy gate was placed immediately before `cli_runner.run()` and the ADR claimed no child existed before the verdict. `_gather_code_intelligence_context` had already shelled out ~120 lines earlier, so a DENIED action still launched kernel subprocesses against the repository.
- Scope: any invariant of the form "nothing happens before the check".
- Lesson: the check is only as early as the *earliest side effect* on the path, and side effects hide inside helpers whose names sound read-only ("gather", "context", "inspect"). Placement is verified by asserting the collaborator recorded **zero** calls, not by reading the ordering.
- Operational consequence: gate-placement invariants get a test that counts calls on every subprocess-spawning collaborator, not just the one being gated.
- Revalidation condition: standing rule; no expiry.

## L-0006 — Wiring a mechanism to a primitive is not wiring it to production
- Status: VERIFIED
- Evidence: ADR-0012 review finding 1 (the taxonomy nothing imported), then ADR-0013 finding 2 one milestone later — the gate reached `TaskEngine` but `DirectorOrchestrator`, the path every real brief travels, never accepted a `policy`. The identical mistake, caught by the identical review question.
- Scope: any capability added to a kernel primitive that has a higher-level entry point.
- Lesson: knowing the rule ("a mechanism nothing calls is a parallel fiction") did not prevent repeating it, because the primitive's tests were green and felt like proof. The question that catches it is "which caller does a real request come through, and does *that* one pass it?".
- Operational consequence: a wiring milestone is not done until a test exercises it from the outermost production entry point.
- Revalidation condition: standing rule; no expiry.

## L-0007 — Writing the test for a repair is how you find the defect next to it
- Status: VERIFIED
- Evidence: ADR-0013 finding 7. Mapping `policy_gap` to `NEEDS_HUMAN` was the repair; asserting `penalizes_agent is False` then failed, exposing a pre-existing hole — `NEEDS_HUMAN` was missing from `_NON_PENALIZING`, so any operator rule-set gap counted against agent quality (constitution rule 7).
- Scope: any repair whose test asserts a *consequence* rather than the changed value.
- Lesson: asserting the changed field would have passed and hidden it. Assert what the change is *for*.
- Operational consequence: repair tests assert downstream consequences, not the edited field.
- Revalidation condition: standing rule; no expiry.
