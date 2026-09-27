from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from gnosis.trust.check_executor import CheckExecutionUnavailable, WorkerCheckExecutor


class Launcher:
    def __init__(self, *, timed_out=False, cancelled=False, wait_error=False):
        self.spec = None
        self.closed = False
        self.timed_out = timed_out
        self.cancelled = cancelled
        self.wait_error = wait_error

    def launch(self, spec):
        self.spec = spec
        Path(spec.stdout_path).write_bytes(b"worker output")
        Path(spec.stderr_path).write_bytes(b"worker diagnostic")
        return self

    def wait(self, timeout_s, *, is_cancelled):
        assert timeout_s == 3
        assert not is_cancelled()
        if self.wait_error:
            raise RuntimeError("wait failed")
        return 7, self.timed_out, self.cancelled

    def close(self):
        self.closed = True


def executor(root, launcher, guard=lambda: None):
    return WorkerCheckExecutor(launcher=launcher, runtime=Path(sys.executable),
        output_root=root / "worker", evidence_root=root / "protected",
        guard=guard, is_cancelled=lambda: False)


def test_worker_execution_preserves_result_and_never_runs_as_caller(tmp_path):
    launcher = Launcher()
    boundary = executor(tmp_path, launcher)
    with patch("subprocess.run", side_effect=AssertionError("local subprocess")):
        result = boundary.execute([sys.executable, "-c", "pass"], cwd=tmp_path,
            timeout_s=3, env={"SECRET": "never-forward", "MYPY_CACHE_DIR": "cache"})
    assert result.returncode == 7
    assert result.stdout == "worker output"
    assert result.stderr == "worker diagnostic"
    assert launcher.closed
    settings = json.loads(launcher.spec.argv[5])
    assert Path(settings["MYPY_CACHE_DIR"]).is_relative_to(tmp_path / "worker")
    assert settings["PYTHONDONTWRITEBYTECODE"] == "1"
    assert settings["PYTEST_ADDOPTS"] == "-p no:cacheprovider"
    assert "never-forward" not in repr(launcher.spec)
    assert (tmp_path / "protected" / launcher.spec.run_id / "stdout").read_bytes() == b"worker output"


@pytest.mark.parametrize("mode", ["timeout", "cancel", "wait_error"])
def test_job_is_closed_on_unsuccessful_wait(tmp_path, mode):
    launcher = Launcher(timed_out=mode == "timeout", cancelled=mode == "cancel",
                        wait_error=mode == "wait_error")
    expected = subprocess.TimeoutExpired if mode == "timeout" else RuntimeError
    with pytest.raises(expected):
        executor(tmp_path, launcher).execute([sys.executable, "-c", "pass"],
                                             cwd=tmp_path, timeout_s=3)
    assert launcher.closed
    assert (tmp_path / "protected" / launcher.spec.run_id / "stdout").read_bytes() == b"worker output"
    assert (tmp_path / "protected" / launcher.spec.run_id / "intent.json").is_file()


@pytest.mark.parametrize("deadline", [None, 0, -1, float("inf"), float("nan"), True])
def test_unbounded_deadline_refused_before_launch(tmp_path, deadline):
    launcher = Launcher()
    with pytest.raises(CheckExecutionUnavailable):
        executor(tmp_path, launcher).execute([sys.executable], cwd=tmp_path, timeout_s=deadline)
    assert launcher.spec is None


def test_stale_scope_cannot_launch(tmp_path):
    launcher = Launcher()
    def stale():
        raise RuntimeError("stale claim")
    with pytest.raises(RuntimeError, match="stale claim"):
        executor(tmp_path, launcher, stale).execute([sys.executable], cwd=tmp_path, timeout_s=3)
    assert launcher.spec is None


def test_transport_wrapper_preserves_argv_and_cache_settings(tmp_path):
    # Tests wrapper behavior under the test user, not Windows SID isolation.
    launcher = Launcher()
    code = "import os,sys; print(repr(sys.argv[1:])); print(os.environ['MYPY_CACHE_DIR']); sys.exit(9)"
    args = [sys.executable, "-c", code, "space and quote '\"", ""]
    executor(tmp_path, launcher).execute(args, cwd=tmp_path, timeout_s=3,
                                        env={"MYPY_CACHE_DIR": "assigned-cache"})
    result = subprocess.run(launcher.spec.argv, cwd=tmp_path,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 9
    expected_cache = str(Path(launcher.spec.stdout_path).parent / "mypy")
    assert result.stdout.splitlines() == [repr(args[3:]), expected_cache]


def test_recovery_cannot_capture_an_active_executor(tmp_path):
    from gnosis.trust.check_recovery import recover_check_outputs

    class ActiveLauncher(Launcher):
        def launch(self, spec):
            launched = super().launch(spec)
            assert recover_check_outputs(evidence_root=tmp_path / "protected",
                output_root=tmp_path / "worker", runtime=Path(sys.executable)) == ()
            assert not (tmp_path / "protected" / spec.run_id / "stdout").exists()
            return launched
    launcher = ActiveLauncher()
    result = executor(tmp_path, launcher).execute([sys.executable], cwd=tmp_path, timeout_s=3)
    assert result.returncode == 7
    assert (tmp_path / "protected" / launcher.spec.run_id / "stdout").is_file()
