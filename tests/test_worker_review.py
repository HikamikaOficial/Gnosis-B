import json
from pathlib import Path
from unittest.mock import patch

import pytest

from gnosis.director.worker_review import WorkerClaudeReviewer
from gnosis.trust.worker_launcher import LaunchedWorkerIdentity, WorkerLaunchFailed


class Launcher:
    def __init__(self, *, timeout=False, fail=False):
        self.timeout = timeout
        self.fail = fail
        self.closed = False
        self.spec = None
        self.identity = LaunchedWorkerIdentity(1, "worker-sid", "Medium", False, (),
            "a" * 64, "b" * 64, 150, True)

    def launch(self, spec):
        self.spec = spec
        Path(spec.stdout_path).write_text(json.dumps({"result": "review response"}))
        Path(spec.stderr_path).write_text("diagnostic")
        return self

    def wait(self, timeout_s, **kwargs):
        if self.fail:
            raise RuntimeError("wait failed")
        return 0, self.timeout, False

    def close(self):
        self.closed = True


def reviewer(tmp_path, launcher):
    return WorkerClaudeReviewer(binary=tmp_path / "claude.exe", launcher=launcher,
        output_root=tmp_path / "worker", guard=lambda: None)


def test_review_is_contained_and_evidence_retained(tmp_path):
    launcher = Launcher()
    runner = reviewer(tmp_path, launcher)
    stdout, stderr = tmp_path / "evidence/out", tmp_path / "evidence/err"
    with patch("subprocess.Popen", side_effect=AssertionError("Director spawn forbidden")):
        result = runner.run("Review this", tmp_path, stdout, stderr)
    assert launcher.closed
    assert result.succeeded
    assert result.parsed_json == {"result": "review response"}
    assert result.launch["observed_worker_sid"] == "worker-sid"
    assert Path(launcher.spec.stdout_path).is_relative_to(tmp_path / "worker")
    assert result.stdout_path == str(stdout)
    assert stdout.read_text() == Path(launcher.spec.stdout_path).read_text()
    assert launcher.spec.argv[-2:] == ("--permission-mode", "plan")


@pytest.mark.parametrize("options", [{"permission_mode": "acceptEdits"},
    {"env": {"ANTHROPIC_API_KEY": "forbidden"}}, {"extra_args": ["--dangerously-skip-permissions"]},
    {"timeout_s": float("inf")}, {"timeout_s": 0}])
def test_overrides_refused_before_launch(tmp_path, options):
    launcher = Launcher()
    with pytest.raises(ValueError):
        reviewer(tmp_path, launcher).run("Review", tmp_path, tmp_path / "out", tmp_path / "err", **options)
    assert launcher.spec is None


def test_missing_boundary_never_falls_back(tmp_path):
    with pytest.raises(WorkerLaunchFailed):
        reviewer(tmp_path, None).run("Review", tmp_path, tmp_path / "out", tmp_path / "err")


@pytest.mark.parametrize("fail", [False, True])
def test_timeout_or_wait_failure_closes_job_and_retains_diagnostics(tmp_path, fail):
    launcher = Launcher(timeout=True, fail=fail)
    runner = reviewer(tmp_path, launcher)
    if fail:
        with pytest.raises(RuntimeError, match="wait failed"):
            runner.run("Review", tmp_path, tmp_path / "out", tmp_path / "err")
    else:
        result = runner.run("Review", tmp_path, tmp_path / "out", tmp_path / "err")
        assert result.timed_out and not result.succeeded
    assert launcher.closed
    assert (tmp_path / "err").read_text() == "diagnostic"
