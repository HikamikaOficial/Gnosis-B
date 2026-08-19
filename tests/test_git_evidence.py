import subprocess
import tempfile
import unittest
from pathlib import Path

from gnosis.kernel.git_evidence import capture_git_evidence


class TestGitEvidence(unittest.TestCase):
    def test_non_repo_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence = capture_git_evidence(Path(tmp))
            self.assertFalse(evidence.is_repo)

    def test_real_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "a.txt").write_text("hello")
            subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

            evidence = capture_git_evidence(repo)
            self.assertTrue(evidence.is_repo)
            self.assertIsNotNone(evidence.head_sha)
            self.assertEqual(evidence.status_porcelain, "")

            (repo / "a.txt").write_text("changed")
            dirty = capture_git_evidence(repo)
            self.assertIn("a.txt", dirty.status_porcelain)


if __name__ == "__main__":
    unittest.main()
