import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from gnosis.kernel.worktree import (
    WorktreeAbsentError,
    WorktreeAutosaveRefusedError,
    WorktreeCorruptStateError,
    WorktreeError,
    WorktreeManager,
    WorktreeProvenanceError,
)


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
    (path / "README.md").write_text("root\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


class TestWorktreeManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        _init_repo(self.repo)
        self.manager = WorktreeManager(self.repo, self.root / "worktrees")

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_checks_out_isolated_branch(self):
        handle = self.manager.create(task_id="TASK-1")
        self.assertTrue(Path(handle.path).is_dir())
        self.assertEqual(handle.branch, "gnosis/TASK-1")
        self.assertTrue((Path(handle.path) / "README.md").exists())
        # The source repo's own working tree must be untouched.
        self.assertTrue((self.repo / "README.md").exists())

    def test_separate_provenance_survives_restart_and_ignores_worker_marker(self):
        work = self.root / "worker-area"
        records = self.root / "protected-records"
        manager = WorktreeManager(self.repo, work, provenance_root=records)
        handle = manager.create(task_id="TASK-separated")
        marker = records / ".TASK-separated.worktree.json"
        original = marker.read_bytes()
        (work / marker.name).write_text("forged worker record", encoding="utf-8")
        restarted = WorktreeManager(self.repo, work, provenance_root=records)
        self.assertEqual(restarted.load_handle("TASK-separated"), handle)
        self.assertEqual(restarted.create(task_id="TASK-separated"), handle)
        self.assertEqual(marker.read_bytes(), original)

    def test_create_rejects_non_repo_source(self):
        not_a_repo = self.root / "plain_dir"
        not_a_repo.mkdir()
        manager = WorktreeManager(not_a_repo, self.root / "worktrees2")
        with self.assertRaises(WorktreeError):
            manager.create(task_id="TASK-X")

    def test_create_is_idempotent_for_intact_worktree(self):
        # Directive 5: creation is idempotent with reattach paths. A second
        # create() of an intact worktree returns the original handle.
        first = self.manager.create(task_id="TASK-1")
        second = self.manager.create(task_id="TASK-1")
        self.assertEqual(first, second)

    def test_evidence_reflects_isolated_changes(self):
        handle = self.manager.create(task_id="TASK-1")
        (Path(handle.path) / "new_file.txt").write_text("hello", encoding="utf-8")

        worktree_evidence = self.manager.evidence_for(handle)
        from gnosis.kernel.git_evidence import capture_git_evidence
        source_evidence = capture_git_evidence(self.repo)

        self.assertTrue(worktree_evidence.is_repo)
        self.assertIn("new_file.txt", worktree_evidence.status_porcelain)
        # The uncommitted change in the worktree must not leak into the
        # source repo's own status.
        self.assertEqual(source_evidence.status_porcelain, "")

    def test_remove_cleans_up_clean_worktree(self):
        handle = self.manager.create(task_id="TASK-1")
        self.manager.remove(handle)
        self.assertFalse(Path(handle.path).exists())

    def test_remove_refuses_dirty_worktree_without_force(self):
        handle = self.manager.create(task_id="TASK-1")
        (Path(handle.path) / "dirty.txt").write_text("uncommitted", encoding="utf-8")
        with self.assertRaises(WorktreeError):
            self.manager.remove(handle)
        self.assertTrue(Path(handle.path).exists())  # preserved for debugging

    def test_remove_with_force_discards_dirty_worktree(self):
        handle = self.manager.create(task_id="TASK-1")
        (Path(handle.path) / "dirty.txt").write_text("uncommitted", encoding="utf-8")
        self.manager.remove(handle, force=True)
        self.assertFalse(Path(handle.path).exists())

    def test_load_handle_round_trips(self):
        created = self.manager.create(task_id="TASK-1", run_id="RUN-1")
        loaded = self.manager.load_handle("TASK-1")
        self.assertEqual(created, loaded)

    def test_list_worktree_paths(self):
        self.manager.create(task_id="TASK-1")
        self.manager.create(task_id="TASK-2")
        names = [p.name for p in self.manager.list_worktree_paths()]
        self.assertEqual(sorted(names), ["TASK-1", "TASK-2"])


class TestWorktreeDirective5(unittest.TestCase):
    """Directive 5: provenance-gated destruction, reattach paths, hostile
    resume input, reason-tagged autosave (ADR-0007)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        _init_repo(self.repo)
        self.manager = WorktreeManager(self.repo, self.root / "worktrees")

    def tearDown(self):
        self.tmp.cleanup()

    # -- hostile input ---------------------------------------------------

    def test_hostile_task_ids_rejected_before_any_git_action(self):
        for bad in ("../evil", "a/b", "a b", "", ".hidden", "-flag", "x" * 200):
            with self.assertRaises(WorktreeError, msg=bad):
                self.manager.create(task_id=bad)
        self.assertEqual(self.manager.list_worktree_paths(), [])

    def test_absent_and_corrupt_marker_are_distinct_errors(self):
        with self.assertRaises(WorktreeAbsentError):
            self.manager.load_handle("TASK-NONE")
        self.manager.create(task_id="TASK-1")
        self.manager._handle_marker("TASK-1").write_text("{not json", encoding="utf-8")
        with self.assertRaises(WorktreeCorruptStateError):
            self.manager.load_handle("TASK-1")

    def test_tampered_marker_branch_is_a_hard_abort(self):
        handle = self.manager.create(task_id="TASK-1")
        marker = self.manager._handle_marker("TASK-1")
        data = json.loads(marker.read_text(encoding="utf-8"))
        data["branch"] = "main"  # ref-shape / protected-floor violation
        marker.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(WorktreeCorruptStateError):
            self.manager.load_handle("TASK-1")
        with self.assertRaises(WorktreeCorruptStateError):
            self.manager.remove(handle, force=True)
        self.assertTrue(Path(handle.path).exists())  # nothing was destroyed

    # -- provenance-gated destruction --------------------------------------

    def test_remove_refuses_handle_without_marker(self):
        handle = self.manager.create(task_id="TASK-1")
        self.manager._handle_marker("TASK-1").unlink()
        with self.assertRaises(WorktreeProvenanceError):
            self.manager.remove(handle, force=True)
        self.assertTrue(Path(handle.path).exists())

    def test_remove_refuses_handle_disagreeing_with_marker(self):
        handle = self.manager.create(task_id="TASK-1")
        forged = replace(handle, run_id="RUN-FORGED")
        with self.assertRaises(WorktreeCorruptStateError):
            self.manager.remove(forged, force=True)
        self.assertTrue(Path(handle.path).exists())

    def test_remove_deletes_marker_and_optionally_branch(self):
        handle = self.manager.create(task_id="TASK-1")
        self.manager.remove(handle, delete_branch=True)
        self.assertFalse(Path(handle.path).exists())
        self.assertFalse(self.manager._handle_marker("TASK-1").exists())
        branches = subprocess.run(
            ["git", "branch", "--list", handle.branch], cwd=self.repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(branches, "")

    def test_remove_is_idempotent_when_directory_already_gone(self):
        handle = self.manager.create(task_id="TASK-1")
        self.manager.remove(handle)
        recreated = self.manager.create(task_id="TASK-1")
        self.assertEqual(recreated.branch, handle.branch)

    def test_delete_branch_refuses_unmerged_and_marker_survives_for_retry(self):
        handle = self.manager.create(task_id="TASK-1")
        wt = Path(handle.path)
        (wt / "work.txt").write_text("committed work", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=wt, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "wip"], cwd=wt, check=True, capture_output=True)
        with self.assertRaises(WorktreeError):
            self.manager.remove(handle, delete_branch=True)  # no force_delete_branch
        # Destruction order is worktree -> branch -> marker: on branch
        # refusal the provenance record survives, so both the retry and
        # the reattach path keep working (no orphaned minted branch).
        self.assertTrue(self.manager._handle_marker("TASK-1").exists())
        self.manager.remove(handle, delete_branch=True, force_delete_branch=True)
        self.assertFalse(self.manager._handle_marker("TASK-1").exists())
        branches = subprocess.run(
            ["git", "branch", "--list", handle.branch], cwd=self.repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(branches, "")

    def test_remove_handles_externally_deleted_directory(self):
        # Pins remove()'s directory-already-gone branch (previously never
        # executed by any test).
        import shutil as _shutil
        handle = self.manager.create(task_id="TASK-1")
        _shutil.rmtree(handle.path)
        self.manager.remove(handle, delete_branch=True, force_delete_branch=True)
        self.assertFalse(self.manager._handle_marker("TASK-1").exists())
        recreated = self.manager.create(task_id="TASK-1")  # fully clean regrant
        self.assertEqual(recreated.branch, handle.branch)

    def test_remove_refuses_unregistered_directory(self):
        handle = self.manager.create(task_id="TASK-1")
        subprocess.run(["git", "worktree", "remove", "--force", handle.path],
                       cwd=self.repo, check=True, capture_output=True)
        squatter = Path(handle.path)
        squatter.mkdir(parents=True)
        (squatter / "precious.txt").write_text("recoverable", encoding="utf-8")
        with self.assertRaises(WorktreeCorruptStateError):
            self.manager.remove(handle, force=True)
        self.assertTrue((squatter / "precious.txt").exists())

    def test_tampered_marker_path_and_source_repo_are_hard_aborts(self):
        # Pins the path/source_repo cross-checks individually (previously
        # only the branch field was tamper-tested; deleting the path check
        # enabled cross-task destruction).
        h1 = self.manager.create(task_id="TASK-1")
        h2 = self.manager.create(task_id="TASK-2")
        marker = self.manager._handle_marker("TASK-1")
        data = json.loads(marker.read_text(encoding="utf-8"))
        data["path"] = h2.path  # point TASK-1's marker at TASK-2's worktree
        marker.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(WorktreeCorruptStateError):
            self.manager.load_handle("TASK-1")
        with self.assertRaises(WorktreeCorruptStateError):
            self.manager.remove(h1, force=True)
        self.assertTrue(Path(h2.path).exists())  # the other task is intact

        data["path"] = h1.path
        data["source_repo"] = str(self.root / "elsewhere")
        marker.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(WorktreeCorruptStateError):
            self.manager.load_handle("TASK-1")

    def test_wrong_typed_marker_field_is_corrupt_state_not_typeerror(self):
        self.manager.create(task_id="TASK-1")
        marker = self.manager._handle_marker("TASK-1")
        data = json.loads(marker.read_text(encoding="utf-8"))
        data["task_id"] = 123
        marker.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(WorktreeCorruptStateError):
            self.manager.load_handle("TASK-1")

    def test_task_id_with_trailing_newline_is_rejected(self):
        with self.assertRaises(WorktreeError):
            self.manager.create(task_id="TASK-1\n")

    # -- reattach paths ------------------------------------------------------

    def test_reattach_recreates_missing_directory_on_surviving_branch(self):
        handle = self.manager.create(task_id="TASK-1")
        wt = Path(handle.path)
        (wt / "work.txt").write_text("recoverable", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=wt, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "wip"], cwd=wt, check=True, capture_output=True)
        # Simulate a crash that lost the checkout but not the marker/branch.
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                       cwd=self.repo, check=True, capture_output=True)
        self.assertFalse(wt.exists())
        reattached = self.manager.create(task_id="TASK-1")
        self.assertEqual(reattached, handle)
        self.assertTrue((Path(reattached.path) / "work.txt").exists())  # NO LOST WORK

    def test_unregistered_directory_is_never_deleted(self):
        squatter = self.root / "worktrees" / "TASK-1"
        squatter.mkdir(parents=True)
        (squatter / "precious.txt").write_text("recoverable work", encoding="utf-8")
        with self.assertRaises(WorktreeCorruptStateError):
            self.manager.create(task_id="TASK-1")
        self.assertTrue((squatter / "precious.txt").exists())

    # -- autosave -------------------------------------------------------------

    def test_autosave_tags_reason_and_returns_sha(self):
        handle = self.manager.create(task_id="TASK-1")
        wt = Path(handle.path)
        (wt / "progress.txt").write_text("half-done", encoding="utf-8")
        sha = self.manager.autosave(handle, reason="pre-timeout checkpoint")
        self.assertIsNotNone(sha)
        message = subprocess.run(
            ["git", "log", "-1", "--format=%s"], cwd=wt,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(message, "gnosis-autosave(TASK-1): pre-timeout checkpoint")

    def test_autosave_on_clean_tree_is_a_noop(self):
        handle = self.manager.create(task_id="TASK-1")
        self.assertIsNone(self.manager.autosave(handle, reason="nothing"))

    def test_autosave_refuses_each_sequencer_state_individually(self):
        # Pins each mid-operation refusal on its own (previously the
        # unmerged-paths check masked deletion of the MERGE_HEAD check and
        # rebase/cherry-pick/revert had zero coverage).
        handle = self.manager.create(task_id="TASK-1")
        wt = Path(handle.path)
        git_dir = Path(subprocess.run(
            ["git", "rev-parse", "--git-dir"], cwd=wt,
            capture_output=True, text=True, check=True,
        ).stdout.strip())
        if not git_dir.is_absolute():
            git_dir = (wt / git_dir).resolve()
        cases = [("MERGE_HEAD", "file", "mid-merge"),
                 ("rebase-merge", "dir", "mid-rebase"),
                 ("rebase-apply", "dir", "mid-rebase"),
                 ("CHERRY_PICK_HEAD", "file", "mid-cherry-pick"),
                 ("REVERT_HEAD", "file", "mid-revert"),
                 ("BISECT_LOG", "file", "mid-bisect")]
        for name, kind, expected_tag in cases:
            probe = git_dir / name
            if kind == "file":
                probe.write_text("deadbeef\n", encoding="utf-8")
            else:
                probe.mkdir()
            try:
                with self.assertRaises(WorktreeAutosaveRefusedError, msg=name) as ctx:
                    self.manager.autosave(handle, reason="mid-op probe")
                self.assertEqual(ctx.exception.reason_tag, expected_tag, msg=name)
            finally:
                if kind == "file":
                    probe.unlink()
                else:
                    probe.rmdir()

    def test_autosave_refuses_staged_conflict_markers(self):
        # The classic escape hatch: conflict, `git add`, `git merge --quit`
        # — bare `diff --check` sees nothing; `--cached` must catch it.
        handle = self.manager.create(task_id="TASK-1")
        wt = Path(handle.path)
        (wt / "clash.txt").write_text(
            "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> other\n", encoding="utf-8",
        )
        subprocess.run(["git", "add", "clash.txt"], cwd=wt, check=True, capture_output=True)
        with self.assertRaises(WorktreeAutosaveRefusedError) as ctx:
            self.manager.autosave(handle, reason="staged markers")
        self.assertEqual(ctx.exception.reason_tag, "conflict-markers")

    def test_autosave_refuses_untracked_conflict_remnants(self):
        handle = self.manager.create(task_id="TASK-1")
        wt = Path(handle.path)
        (wt / "clash.txt.orig").write_text(
            "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> other\n", encoding="utf-8",
        )
        with self.assertRaises(WorktreeAutosaveRefusedError) as ctx:
            self.manager.autosave(handle, reason="untracked remnant")
        self.assertEqual(ctx.exception.reason_tag, "conflict-markers")

    def test_autosave_refuses_detached_head(self):
        # A commit on a detached HEAD lands on no ref and becomes
        # unreachable after remove(): refuse instead.
        handle = self.manager.create(task_id="TASK-1")
        wt = Path(handle.path)
        subprocess.run(["git", "checkout", "--detach"], cwd=wt,
                       check=True, capture_output=True)
        (wt / "progress.txt").write_text("half-done", encoding="utf-8")
        with self.assertRaises(WorktreeAutosaveRefusedError) as ctx:
            self.manager.autosave(handle, reason="detached attempt")
        self.assertEqual(ctx.exception.reason_tag, "off-branch")

    def test_adopted_branch_without_marker_preserves_commits(self):
        # The no-marker adoption path must adopt, never recreate/shadow:
        # committed work survives a marker-less regrant.
        handle = self.manager.create(task_id="TASK-1")
        wt = Path(handle.path)
        (wt / "work.txt").write_text("survives adoption", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=wt, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "wip"], cwd=wt, check=True, capture_output=True)
        self.manager.remove(handle)  # branch survives, marker deleted
        adopted = self.manager.create(task_id="TASK-1")
        self.assertTrue((Path(adopted.path) / "work.txt").exists())

    def test_autosave_refuses_merge_conflict_state(self):
        handle = self.manager.create(task_id="TASK-1")
        wt = Path(handle.path)

        def git(*args: str, cwd: Path = wt) -> None:
            subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

        (wt / "clash.txt").write_text("ours\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-m", "ours")
        git("checkout", "-b", "gnosis/TASK-1-other", "HEAD~0")
        git("checkout", handle.branch)
        git("checkout", "gnosis/TASK-1-other")
        (wt / "clash.txt").write_text("theirs\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-m", "theirs")
        git("checkout", handle.branch)
        (wt / "clash.txt").write_text("ours-changed\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-m", "ours-changed")
        merge = subprocess.run(
            ["git", "merge", "gnosis/TASK-1-other"], cwd=wt,
            capture_output=True, text=True, check=False,  # failure is the point
        )
        self.assertNotEqual(merge.returncode, 0)  # real conflict established

        with self.assertRaises(WorktreeAutosaveRefusedError) as ctx:
            self.manager.autosave(handle, reason="mid-conflict attempt")
        self.assertIn(ctx.exception.reason_tag, {"mid-merge", "unmerged-paths"})


if __name__ == "__main__":
    unittest.main()
