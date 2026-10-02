from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trust_fixtures as tf

from gnosis.kernel.convergence import (
    ConvergenceLoop,
    ConvergenceOutcome,
    ConvergencePolicy,
    FixReport,
    ReviewReport,
    ReviewVerdict,
)
from gnosis.kernel.git_evidence import git_topology_eligible
from gnosis.kernel.subject import SubjectUnavailable, copy_subject, observe_subject
from gnosis.kernel.verification import VerificationResult


def _pass() -> VerificationResult:
    return VerificationResult("check", True, 0, 0.1, "", "")


def test_mixed_ownership_subject_and_copy_keep_config_isolation(tmp_path: Path, monkeypatch) -> None:
    from gnosis.kernel import subject

    repo = tf.git_repo(tmp_path / "repo")
    original = subprocess.run
    forced = dict(os.environ, GIT_TEST_ASSUME_DIFFERENT_OWNER="1",
                  GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    baseline = original(["git", "rev-parse", "HEAD"], cwd=repo, env=forced,
                        capture_output=True, text=True)
    assert baseline.returncode != 0 and "dubious ownership" in baseline.stderr
    calls = []

    def different_owner(argv, **kwargs):
        env = kwargs["env"]
        assert env["GIT_CONFIG_GLOBAL"] == os.devnull
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert "GIT_DIR" not in env
        assert "safe.directory=*" not in argv
        calls.append(argv)
        return original(argv, **{**kwargs, "env": {**env, "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}})

    monkeypatch.setenv("GIT_DIR", str(tmp_path / "wrong"))
    monkeypatch.setattr(subject.subprocess, "run", different_owner)
    expected = observe_subject(repo)
    copied = copy_subject(repo, tmp_path / "copy", expected)
    assert observe_subject(copied) == expected
    assert calls


def test_subject_binds_binary_ignored_and_untracked_bytes(tmp_path: Path) -> None:
    repo = tf.git_repo(tmp_path / "repo")
    (repo / "binary.bin").write_bytes(b"\x00one")
    (repo / ".gitignore").write_text("ignored.dat\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "binary"], cwd=repo,
                   check=True, capture_output=True)
    (repo / "ignored.dat").write_bytes(b"one")
    (repo / "café.txt").write_text("one", encoding="utf-8")
    first = observe_subject(repo)
    for name in ("binary.bin", "ignored.dat", "café.txt"):
        prior = observe_subject(repo)
        (repo / name).write_bytes(b"\x00two")
        assert observe_subject(repo).digest() != prior.digest()
    assert set(dict(first.files)) == {"code.py", "binary.bin", ".gitignore",
                                       "ignored.dat", "café.txt"}


def test_linked_worktree_exports_to_independent_git_copy(tmp_path: Path) -> None:
    repo = tf.git_repo(tmp_path / "repo")
    work = tmp_path / "work"
    subprocess.run(["git", "worktree", "add", "-b", "task", str(work)], cwd=repo,
                   check=True, capture_output=True)
    (work / "code.py").write_text("x = 2\n")
    (work / "new.txt").write_text("actual uncommitted work")
    (work / "empty").mkdir()
    expected = observe_subject(work)
    copy = copy_subject(work, tmp_path / "copy", expected)
    assert observe_subject(copy) == expected == observe_subject(work)
    assert not git_topology_eligible(work)[0]
    assert git_topology_eligible(copy)[0]
    assert not (copy / ".git" / "objects" / "info" / "alternates").exists()
    assert (repo / "code.py").read_text() == "x = 1\n"
    assert (work / ".git").is_file()


def test_changed_subject_is_never_copied_as_reviewed(tmp_path: Path) -> None:
    repo = tf.git_repo(tmp_path / "repo")
    expected = observe_subject(repo)
    (repo / "code.py").write_text("x = 2\n")
    with pytest.raises(SubjectUnavailable, match="changed before"):
        copy_subject(repo, tmp_path / "copy", expected)
    assert not (tmp_path / "copy").exists()


@pytest.mark.parametrize("destination", ["source", "inside", "existing"])
def test_copy_never_overwrites_or_nests(tmp_path: Path, destination: str) -> None:
    repo = tf.git_repo(tmp_path / "repo")
    target = {"source": repo, "inside": repo / "copy", "existing": tmp_path / "existing"}[
        destination]
    if destination == "existing":
        target.mkdir()
        (target / "precious.txt").write_text("keep")
    with pytest.raises(SubjectUnavailable):
        copy_subject(repo, target, observe_subject(repo))
    if destination == "existing":
        assert (target / "precious.txt").read_text() == "keep"


def test_nested_repo_is_not_silently_omitted(tmp_path: Path) -> None:
    repo = tf.git_repo(tmp_path / "repo")
    tf.git_repo(repo / "nested")
    with pytest.raises(SubjectUnavailable, match="nested"):
        observe_subject(repo)


@pytest.mark.skipif(os.name != "nt", reason="NTFS streams")
def test_named_stream_is_refused_instead_of_lost_in_copy(tmp_path: Path) -> None:
    repo = tf.git_repo(tmp_path / "repo")
    Path(str(repo / "code.py") + ":hidden").write_text("hidden input")
    with pytest.raises(SubjectUnavailable, match="streams"):
        observe_subject(repo)


@pytest.mark.parametrize("phase", ["verify", "review"])
def test_mutation_during_round_blocks_completion(tmp_path: Path, phase: str) -> None:
    repo = tf.git_repo(tmp_path / "repo")

    def verify():
        if phase == "verify":
            (repo / "code.py").write_text("x = 2\n")
        return _pass()

    def review(index):
        if phase == "review":
            (repo / "code.py").write_text("x = 2\n")
        return ReviewReport(ReviewVerdict.PASS, reviewer="independent")

    result = ConvergenceLoop(ConvergencePolicy(max_rounds=1), verify, review,
                             lambda request: FixReport(), lambda: "weak-unchanged",
                             subject_fn=lambda: observe_subject(repo)).run()
    assert result.outcome is ConvergenceOutcome.ROUNDS_EXHAUSTED
    assert result.rounds[-1].subject is None
    assert not result.rounds[-1].evidence_ok
    assert any(f.error_type == "SubjectChanged" for f in result.evidence_failures)


def test_passing_round_persists_verification_review_and_subject(tmp_path: Path) -> None:
    repo = tf.git_repo(tmp_path / "repo")
    result = ConvergenceLoop(
        ConvergencePolicy(max_rounds=1), _pass,
        lambda index: ReviewReport(ReviewVerdict.PASS, reviewer="independent"),
        lambda request: FixReport(), lambda: "old-stat",
        subject_fn=lambda: observe_subject(repo)).run()
    assert result.outcome is ConvergenceOutcome.CONVERGED
    record = result.to_dict()["rounds"][-1]
    assert record["fingerprint"] == observe_subject(repo).digest()
    assert record["subject"]["files"]["code.py"]
    assert record["verification"]["verdict"] == "PASSED"
    assert record["review"]["reviewer"] == "independent"
