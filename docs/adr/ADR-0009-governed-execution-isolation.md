# ADR-0009 — Governed execution isolation (ADR-0006 + ADR-0007 composition)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_engine.py` (TestGuardedRunStore,
  TestTaskEngineWorktreeIsolation), `tests/test_director_orchestrator.py`
  (TestGovernedOrchestrator); suite 282/282; mypy strict clean; dual
  adversarial review pre-commit (outcome below).
- Closes: the structural follow-ups recorded in ADR-0006's Codex
  addendum and NEXT_ACTIONS items (a)–(c).

## Decisions

### 1. The repository-writing child runs in the task's worktree

`TaskEngine.execute_task(worktrees=WorktreeManager)` mints/reattaches the
task's kernel-minted worktree (ADR-0007 semantics: idempotent, hostile-
input-validated, provenance-marked) and uses it as `exec_root` for the
CLI child, git evidence capture, code-intelligence gathering, and
verification. Ordering is ownership-then-workspace: the grant is
acquired before the worktree is touched, and the worktree creation lives
*inside* the try/finally that stops the heartbeat pump. The worktree
deliberately survives every outcome — success (holds the integrable
result branch), failure (bound to the unresolved claim), deposition
(holds the zombie's writes as recoverable evidence); removal belongs to
the future integration milestone. `repo_path` and the manager's source
repo must be the same repository, or the call is refused.

**What this is and is not (corrected after review).** The mechanism is
a **cwd scope**, not an OS-enforced sandbox. It redirects ordinary
relative-path work — which is what a deposed or slow child actually does
— away from the shared repo. It does *not* prevent an agent from writing
absolute paths, and it never claimed to prevent a hostile one: true
containment is Directive 8 (fail-closed policy + sandbox), and the
earlier "structurally out of reach" phrasing overstated this.

**Documented residuals**, both accepted for V1 and both narrower than a
fix would be cheap for:

- Successor and zombie share the task's ONE worktree. The window is
  bounded by pump cancellation + reclaim grace *only when the deposed
  worker is still running*; a suspended or stalled worker (the very
  cause of lease expiry) runs no pump, so its child is not cancelled
  until the process resumes. Blast radius stays the task's own branch,
  never the mainline. Per-epoch worktrees were considered and rejected
  for V1 (they fragment the task's branch history); the real fix is
  process-group/job-object child termination, which belongs with the
  sandbox work.
- A code-intelligence provider is pinned to the repository it was
  constructed for: only `index()` takes a path, so a provider built over
  the shared repo answers queries about the shared repo even in worktree
  mode. Construct the provider for the same tree, or accept that its
  context is shared-repo context.

### 2. Ownership is enforced at the run-store boundary

`_GuardedRunStore`/`_GuardedLedger` wrap every durable run-store write
the engine performs (create_run, update_state, heartbeat, ledger
appends) with the ownership guard, so a forgotten `guard()` call can no
longer stale-write; reads stay unfenced. The runner's heartbeat callback
catches the stale errors and cancels the child cooperatively instead of
raising inside the polling loop (which would leak the process).
Remaining raw-file writes in the run directory (result.json,
code_intelligence.json, pre/post git evidence) are namespaced by fresh
run_id and covered by ambient guards; true store-internal token
verification stays deferred to the multi-process worker milestone.

### 3. The orchestrator is governance-aware

`DirectorOrchestrator(authority=, worker_id=, worktrees=, lease_ttl_s=)`
passes the governance configuration through to every brief execution;
authority without worker_id is refused at construction. The inbox's
best-effort brief claim remains as brief-level dedup only — task
ownership authority is the claims/lease plane. The engine's
verifier-required evidence gate applies unchanged (a governed
orchestrator must be given a verifier at run_pending time).

## Review outcome and repairs (2026-08-20, pre-commit)

Dual adversarial review: Codex (FAIL, 3 findings) + multi-agent workflow
(3 lenses, 16 findings; its verify phase was cut short by quota, so the
findings were adjudicated manually against the code). After dedup, every
substantive finding was true and is repaired:

1. **Pump leak on worktree-creation failure (major; reported by four
   independent reviewers, one with a live reproduction).** `create()` ran
   between `pump.start()` and the try/finally, so any failure left the
   daemon renewing a dead worker's lease forever and the task
   permanently unreclaimable. Creation moved inside the try; pinned by
   `test_worktree_creation_failure_does_not_leak_the_pump`.
2. **Wrong-repository execution (major, Codex).** A manager whose source
   repo differed from `repo_path` silently executed, verified and
   reported against the *other* repository. Now refused.
3. **Governed-without-isolation (major, Codex).** The orchestrator
   (production entry point) now refuses `authority` without a
   `WorktreeManager`; the engine primitive stays flexible.
4. **Brief stranding (major).** Deposition, workspace failures and the
   verifier-gate ValueError are expected governed outcomes; they were
   escaping `run_pending`, aborting the batch and leaving the consumed
   brief IN_PROGRESS with no report. They now fail that brief durably and
   let the batch continue.
5. **Heartbeat callback too narrow (major).** Only `Stale*` was caught;
   a lock timeout or a transient Windows sharing violation (the L-0002
   class) escaped into the runner's poll loop and leaked the child.
   Nothing escapes now, and swallowed hiccups are recorded in the
   `run.attempt_finished` ledger event instead of vanishing.
6. **Raw evidence writes bypassed the boundary (minor).** result.json,
   code_intelligence.json and git pre/post now go through
   `_GuardedRunStore.write_evidence`.
7. **Coverage gaps (5 findings, each with a surviving mutant).** The
   verification cwd, the heartbeat callback path, the guarded-store
   routing (deposition during verification), the reattach assertion
   (marker equality proved nothing) and the repo-mismatch refusal are now
   each pinned by a dedicated test (engine tests 29 → 34).
8. **Overstated isolation claim + code-intelligence pinning** — corrected
   in §1 above rather than papered over.
