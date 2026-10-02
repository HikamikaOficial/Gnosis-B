"""F-17 Stage 7 — the Git backend/version gate and the closed fail-opens.

The classifier and the resolution gates were qualified against one Git contract:
the `files` ref backend, version 2.55.x. Anything else must fail closed, and a
probe that cannot answer must not read as "all clear". These tests pin both.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gnosis.kernel import git_evidence
from gnosis.kernel.git_evidence import (
    git_backend_and_version_qualified,
    git_resolution_faithful,
)

WINDOWS_ONLY = unittest.skipUnless(sys.platform == "win32", "Windows-only")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=False, encoding="utf-8", errors="replace")


def _files_repo(root: Path) -> Path:
    repo = root / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "one")
    return repo


class _StubGit:
    """Replace _run_git so a specific probe's (rc, out) can be dictated."""

    def __init__(self, responses: dict[tuple[str, ...], tuple[int, str]],
                 default: tuple[int, str] = (0, "")):
        self.responses = responses
        self.default = default

    def __call__(self, repo_path: Path, args: list[str]) -> tuple[int, str]:
        return self.responses.get(tuple(args), self.default)


class TestTheBackendVersionGate(unittest.TestCase):
    def test_the_real_repo_is_qualified(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _files_repo(Path(tmp))
            ok, reason = git_backend_and_version_qualified(repo)
            self.assertTrue(ok, reason)

    def test_a_reftable_backend_is_rejected(self):
        # git 2.55 can create a reftable repo; the gate must refuse it because
        # the .git surface catalogue does not describe .git/reftable/*.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "rt"
            repo.mkdir()
            created = _git(repo, "init", "-q", "--ref-format=reftable")
            fmt = _git(repo, "rev-parse", "--show-ref-format").stdout.strip()
            if created.returncode != 0 or fmt != "reftable":
                self.skipTest("this git cannot create a reftable repo")
            ok, reason = git_backend_and_version_qualified(repo)
            self.assertFalse(ok)
            assert reason is not None
            self.assertIn("reftable", reason)

    def test_an_old_version_is_rejected(self):
        stub = _StubGit({("--version",): (0, "git version 2.40.1.windows.1")})
        original = git_evidence._run_git
        try:
            git_evidence._run_git = stub  # type: ignore[assignment]
            ok, reason = git_backend_and_version_qualified(Path("."))
        finally:
            git_evidence._run_git = original  # type: ignore[assignment]
        self.assertFalse(ok)
        assert reason is not None
        self.assertIn("2.40", reason)

    def test_a_patch_release_in_the_family_is_accepted(self):
        stub = _StubGit({
            ("--version",): (0, "git version 2.55.7.windows.2"),
            ("rev-parse", "--show-ref-format"): (0, "files"),
        })
        original = git_evidence._run_git
        try:
            git_evidence._run_git = stub  # type: ignore[assignment]
            ok, reason = git_backend_and_version_qualified(Path("."))
        finally:
            git_evidence._run_git = original  # type: ignore[assignment]
        self.assertTrue(ok, reason)

    def test_a_broken_git_fails_closed(self):
        stub = _StubGit({("--version",): (127, "git executable not found")})
        original = git_evidence._run_git
        try:
            git_evidence._run_git = stub  # type: ignore[assignment]
            ok, _ = git_backend_and_version_qualified(Path("."))
        finally:
            git_evidence._run_git = original  # type: ignore[assignment]
        self.assertFalse(ok)

    def test_an_unreadable_ref_format_fails_closed(self):
        stub = _StubGit({
            ("--version",): (0, "git version 2.55.0"),
            ("rev-parse", "--show-ref-format"): (129, "unknown option"),
        })
        original = git_evidence._run_git
        try:
            git_evidence._run_git = stub  # type: ignore[assignment]
            ok, reason = git_backend_and_version_qualified(Path("."))
        finally:
            git_evidence._run_git = original  # type: ignore[assignment]
        self.assertFalse(ok)
        assert reason is not None
        self.assertIn("ref-storage", reason)


class TestResolutionProbesFailClosed(unittest.TestCase):
    """A FAILED probe is UNKNOWN, not 'all clear' — the closed fail-opens."""

    def _run_with(self, responses):  # type: ignore[no-untyped-def]
        stub = _StubGit(responses, default=(0, ""))
        original = git_evidence._run_git
        try:
            git_evidence._run_git = stub  # type: ignore[assignment]
            return git_resolution_faithful(Path("."))
        finally:
            git_evidence._run_git = original  # type: ignore[assignment]

    def test_a_failed_replace_probe_fails_closed(self):
        ok, reason = self._run_with({
            ("rev-parse", "--is-inside-work-tree"): (0, "true"),
            ("for-each-ref", "--format=%(refname)", "refs/replace"): (1, "boom"),
        })
        self.assertFalse(ok)
        assert reason is not None
        self.assertIn("replace refs", reason)

    def test_a_failed_shallow_probe_fails_closed(self):
        ok, reason = self._run_with({
            ("rev-parse", "--is-inside-work-tree"): (0, "true"),
            ("for-each-ref", "--format=%(refname)", "refs/replace"): (0, ""),
            ("rev-parse", "--is-shallow-repository"): (1, "boom"),
        })
        self.assertFalse(ok)
        assert reason is not None
        self.assertIn("shallow", reason)

    def test_a_clean_repo_is_faithful(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _files_repo(Path(tmp))
            ok, reason = git_resolution_faithful(repo)
            self.assertTrue(ok, reason)


if __name__ == "__main__":
    unittest.main()
