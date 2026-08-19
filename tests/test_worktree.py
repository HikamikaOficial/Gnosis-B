import subprocess
import tempfile
import unittest
from pathlib import Path

from gnosis.kernel.worktree import WorktreeError, WorktreeManager


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

    def test_create_rejects_non_repo_source(self):
        not_a_repo = self.root / "plain_dir"
        not_a_repo.mkdir()
        manager = WorktreeManager(not_a_repo, self.root / "worktrees2")
        with self.assertRaises(WorktreeError):
            manager.create(task_id="TASK-X")

    def test_create_rejects_duplicate_task_id(self):
        self.manager.create(task_id="TASK-1")
        with self.assertRaises(WorktreeError):
            self.manager.create(task_id="TASK-1")

    def test_evidence_reflects_isolated_changes(self):
        handle = self.manager.create(task_id="TASK-1")
        (Path(handle.path) / "new_file.txt").write_text("hello", encoding="utf-8")

        worktree_evidence = self.manager.evidence_for(handle)
        source_evidence = subprocess_evidence = None
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


if __name__ == "__main__":
    unittest.main()
