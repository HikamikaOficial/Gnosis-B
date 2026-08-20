# ADR-0007 — Worktree lifecycle with provenance-gated destruction (Directive 5)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_worktree.py` (22 tests, incl. TestWorktreeDirective5);
  suite green; mypy strict clean; adversarial review pre-commit (outcome
  recorded below before commit).
- Source: `docs/research/REFERENCE_REPOSITORY_FINDINGS.md` §5 (AWF
  idempotent removal, cezar autosave discipline, orca BranchMode.Created
  gate + hostile resume headers, grit preserve-on-failure, bernstein
  refuse-on-mismatch).

## Decision

`gnosis.kernel.worktree.WorktreeManager` is rewritten around five rules:

1. **Provenance gate on destruction.** The creation-time handle marker
   (`.<task_id>.worktree.json`, outside the checked-out tree) is the
   proof the kernel minted a worktree. `remove()` refuses — regardless
   of `force` — when the marker is absent (`WorktreeProvenanceError`),
   when the presented handle disagrees with the marker
   (`WorktreeCorruptStateError`), or when git does not register the
   directory as a worktree. `delete_branch` only ever deletes inside the
   `gnosis/` namespace, never a protected branch (`main`/`master`/
   `develop`/`trunk`) nor the source repo's current branch, and demands
   `force` for unmerged history.
2. **Idempotent creation with reattach paths.** Intact worktree →
   returns the existing handle (contract change: the old duplicate-create
   error is gone, the test was updated deliberately). Marker without
   directory → reattach on the surviving branch (committed work
   preserved). Kernel-namespace branch without marker or directory →
   adopted, not deleted.
3. **Unregistered directories are recoverable work.** Neither `create()`
   nor `remove()` ever deletes a directory git does not register; both
   hard-abort telling the operator to inspect/move it.
4. **Reason-tagged autosave that refuses poisoned states.**
   `autosave(handle, reason)` commits `gnosis-autosave(<task_id>):
   <reason>` and refuses mid-merge/mid-rebase, unmerged paths, and
   leftover conflict markers (`WorktreeAutosaveRefusedError` with a
   machine-readable tag): losing a recovery point beats poisoning the
   branch.
5. **Resume state is hostile input.** Task ids are shape-checked
   (`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`) before any path or ref is
   built — closing the path-traversal hole the previous version had via
   `worktrees_root / task_id`. Handle markers are cross-checked (minted
   branch name, path containment under the manager's root, source-repo
   identity); corrupt state (`WorktreeCorruptStateError`) is distinct
   from absent state (`WorktreeAbsentError`), and both hard-abort.

## Review outcome and repairs (2026-08-20, pre-commit)

Multi-agent adversarial review: 14 raw findings, 13 confirmed (several
with empirical reproductions in throwaway repos), 1 refuted with its
assumption recorded per L-0004. All confirmed defects repaired before
commit:

1. **Destruction order (major).** `remove()` destroyed marker+worktree
   before branch deletion could fail, orphaning the minted branch and
   dead-ending the documented retry. Now worktree → branch → marker: the
   provenance record is the last thing destroyed, and a branch-deletion
   refusal leaves a retryable, reattachable state (test pins marker
   survival + successful retry).
2. **Autosave gate holes (2 majors, same root).** Bare `diff --check`
   missed staged markers (the `git add` + `merge --quit` escape) and
   untracked remnants; the sequencer gate missed cherry-pick/revert/
   bisect — the verifier even reproduced autosave silently *concluding a
   cherry-pick*. Now: `--cached` check, bounded untracked-file marker
   scan, and all six sequencer states refused with distinct tags — each
   pinned individually.
3. **Detached-HEAD autosave (major).** A recovery commit on no ref became
   unreachable after remove(). Autosave now refuses (`off-branch`) unless
   HEAD is the minted branch.
4. **`force` conflation (major).** Discarding uncommitted files and
   destroying unmerged branch history are now two flags (`force`,
   `force_delete_branch`).
5. **Repo-global prune collateral (minor).** Targeted unregistration
   first; global `prune` only as fallback, documented as accepted V1
   collateral on this single-root workstation.
6. **Corrupt-state classification (2 minors).** Wrong-typed marker fields
   now classify as `WorktreeCorruptStateError` instead of leaking bare
   `TypeError`s; `_TASK_ID_RE` anchors with `\Z` (a trailing-newline id
   no longer passes shape validation).
7. **Coverage (5 findings).** Path/source_repo tamper cross-checks, the
   dir-gone idempotent removal branch, remove()'s unregistered-directory
   refusal, the autosave refusal matrix, and commit-preservation across
   the no-marker adoption path are each pinned by dedicated tests
   (tests/test_worktree.py grew 22 → 33).

Refuted (assumption on record): `_delete_minted_branch` guard coverage —
refutation holds only while it stays a private helper called exclusively
after `_validate_handle` pinned the branch name.
