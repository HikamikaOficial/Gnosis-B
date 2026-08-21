# ADR-0018 — Landing reviewed work: verified merges, not textual ones

- Status: ACCEPTED
- Date: 2026-08-21
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `.gnosis/evidence/20260821T013040Z/`;
  `tests/test_integration.py` (22 tests),
  `tests/test_pipeline.py::TestLandingTheWork` (4); 615 passed; mypy
  strict clean over 50 files.
- Independent review: **done, 2026-08-21, verdict FAIL** — Codex,
  read-only. Eight findings, two critical; all repaired or corrected.
  See the addendum.
- Builds on: ADR-0007 (worktree lifecycle), ADR-0008 (convergence),
  ADR-0017 (the pipeline that produces reviewed work).

## Context

ADR-0017 left a converged brief with reviewed work sitting on
`gnosis/<task_id>` and nothing to land it. The constitution states the
problem rather than the solution:

    15. Worktree != solución completa a conflictos.
    16. Textual merge != semantic integration.

A worktree isolates *while* work happens; it says nothing about what
happens when two isolated results meet. And `git merge` answers one
question — "can these edits be combined without overlapping?" — which is
not the question anyone has.

## Decision

**Integration is verified after the merge, in the merged tree, and the
target only moves if that passes.** Everything else is arrangement:

- The **target branch is named**, not inferred. Without that, integration
  advanced whatever the repo happened to have checked out — an operator's
  feature branch, or a detached HEAD — while reporting that the shared
  branch had landed work (addendum 1).
- The merge happens in a **throwaway staging worktree**, never in the
  operator's checkout. A merge about to be discarded must not pass
  through a tree a human is looking at. Staging trees a crashed process
  left registered are swept under the lock before a new one is made.
- The target advances by **fast-forward to an already-verified commit**,
  so no observer ever sees a broken shared branch. `--ff-only` alone
  guarantees ancestry, not sameness — a writer that rewound the ref to an
  ancestor would be silently overwritten — so the base is **re-read
  immediately before the advance** and must be unchanged (addendum 4).
- A **checkpoint ref** (`refs/gnosis/checkpoints/<task_id>/<base_sha>`,
  carrying the base so re-integrating a task id cannot overwrite an
  earlier rollback point) is written
  before anything moves, so "undo this" is a named ref rather than an
  operator reconstructing a sha (rule 14). The kernel produces the
  rollback *command* and never runs it: undoing an integration is an
  irreversible act on shared state and belongs to a human.
- Conflicts are **typed and carry their paths**. `MERGE_CONFLICT` is
  already in the taxonomy; "merge failed" is not actionable.
- Integration is serialized by a lock **anchored in the repository's git
  dir**, not in a configurable directory — two integrators pointed at one
  repo with different roots would otherwise take different locks and
  serialize nothing.
- Moving the shared branch can be gated at **its own intervention
  point**, `before_integration`. An operator approving "let this agent
  run" has not approved "and then move main", and folding those into one
  identity would make the second invisible inside the first. The gate is
  asked **after** the agent's uncommitted work is committed, so the
  identity it approves is the change set that will actually land
  (addendum 2). Like every gate here it is opt-in
  (`integration/shared_branch_gate = PROMPT_ONLY`).

### The test that justifies the module

`test_a_clean_merge_that_breaks_the_tree_does_not_land` demonstrates rule
16 instead of asserting it. Two tasks fork from the same base — the only
situation where this can arise. A renames `greet` to `salute` and updates
its own caller; B adds a new caller of `greet`. Git reports **zero
conflicts**. The merged tree raises `ImportError`. The branch does not
move.

### Refusals before anything is touched

Not converged; source repo dirty (merging into a dirty checkout mixes
uncommitted human work with agent work, and rollback could not tell them
apart afterwards); nothing changed; refused by policy.

### Landing is opt-in

`GovernedPipeline(integrator=...)`. Without one, a converged brief still
reports COMPLETED with its work on the branch — prepared, not executed,
per the constitution's rule on irreversible acts — and the report says
`integration: NOT ATTEMPTED` so nobody can read landing into the
silence. With one, converged
work that fails to land reports `ESCALATION_REQUIRED` rather than
COMPLETED: a report describing an intention instead of an outcome is the
failure mode this whole project keeps circling.

## Known limitations (stated, not implied)

- **"Semantic integration" is exactly as good as the verifier.** What is
  mechanically guaranteed is the ORDERING —
  `integration/verified_before_landing = HARD` — that nothing lands which
  did not run the configured check and pass. What that check *notices* is
  outside the kernel: `integration/semantic_correctness = IGNORED`. A
  command that exits zero without reading the merged files lets a broken
  tree land and the kernel cannot tell. The test suite here had to be
  widened to import *every* module before it could see its own semantic
  conflict, which is the lesson in miniature.
- **`changed_paths` is a signal, not ownership.** Rule 15 asks for
  semantic ownership; this records which paths a task touched relative to
  its base, which is what a future scheduler needs to *start* reasoning
  about overlap. Disjoint paths do not imply compatibility — the module's
  own headline test is two tasks touching disjoint paths.
- **No cross-task ordering.** Integrations serialize, and each verifies
  against whatever landed before it, but nothing decides which of several
  ready tasks should land first, or notices that landing A will certainly
  break B.
- **A crash between the fast-forward and the return loses the result
  record**, though not the effect: the merge commit and the checkpoint
  ref are both durable, so an operator can reconstruct what happened.
- **Branch cleanup is not done here.** A landed `gnosis/<task_id>` branch
  survives integration. ADR-0007 deliberately governs destruction, and
  deleting a branch whose work just landed is a decision this ADR does
  not make.
- **The gate is opt-in**, like every other gate in this system, until a
  default rule set exists. Recorded as
  `integration/shared_branch_gate = PROMPT_ONLY`.

## Codex review addendum (2026-08-21, independent, verdict FAIL)

Eight findings. Transcript:
`.gnosis/lab/kernel-reviews/codex-review-2026-08-21-integration.jsonl`.

1. *(critical, repaired)* **There was no designated target branch.** The
   integrator merged into whatever the source repo had checked out — an
   operator's feature branch, or a detached HEAD — and reported
   INTEGRATED. `target_branch` is now named at construction, must be a
   real branch, and must be the one checked out; anything else is
   `WRONG_TARGET` before a single write.
2. *(critical, repaired)* **The approval could authorise a different tree
   than the one that landed.** The policy snapshot was taken *before*
   `autosave`, so it described only what was already committed, while
   autosave then committed the agent's uncommitted files too: a rule
   allowing `safe.py` could authorise an action that also landed
   `restricted.py`. The gate now runs after autosave, on the final change
   set. Autosave writes only to the task's own branch, which is inert if
   the gate then refuses.
3. *(major, claim corrected)* The module prose said integration "is
   gated"; the gate is optional. Corrected in place, and the matrix
   already said `PROMPT_ONLY`.
4. *(major, repaired)* **`--ff-only` guarantees ancestry, not sameness.**
   A non-cooperating writer that rewound the ref to an ancestor of the
   verified merge would be silently overwritten. The base is re-read
   under the lock immediately before the advance and must match.
5. *(major, repaired)* **Checkpoint refs were mutable and their failure
   was ignored.** Re-integrating a task id overwrote its earlier rollback
   point, so a stored result's rollback command could reset to the wrong
   commit; and a failed `update-ref` still returned a ref name. The ref
   now carries the base sha, and a failed write aborts — no checkpoint
   means no rollback, and proceeding without one trades the guarantee for
   nothing.
6. *(major, repaired)* **A crash left a staging worktree registered
   forever**, because the `finally` only runs on a normal unwind. A sweep
   under the integration lock clears them, the same shape as ADR-0016's
   boot sweep.
7. *(major, claim corrected)* **`post_merge_verification = HARD` was
   false.** The kernel guarantees that a command ran and exited zero, not
   that the tree is correct. Split into two claims that are each true:
   `verified_before_landing = HARD` (ordering) and
   `semantic_correctness = IGNORED` (meaning).
8. *(major, repaired)* **COMPLETED could be read as "it landed".** With
   no integrator configured, a converged brief reported COMPLETED and the
   report said nothing about integration. It now states
   `integration: NOT ATTEMPTED (no integrator configured)` and the next
   step names the task branch. COMPLETED still means "done and
   independently verified" — the report just no longer lets a reader
   infer landing from silence.

**Found by self-review before the verdict:** the integration lock was
keyed on a configurable directory rather than the repository, so two
integrators pointed at one repo with different roots would have taken
different locks and serialized nothing; and `_discard` used
`--force` without checking provenance, which rule 27 distinguishes from
disposing of a scratch tree the kernel itself minted.
