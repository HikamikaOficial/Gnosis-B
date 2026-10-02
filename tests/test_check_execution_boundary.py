"""Both verification consumers must honor an assigned execution boundary."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from gnosis.kernel.check_execution import CheckExecutionUnavailable
from gnosis.kernel.evidence_capture import CheckCommand, CheckOutcome, _run_check
from gnosis.kernel.verification import CommandVerifier, MalformedEvidence


class RecordingExecutor:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure

    def execute(self, argv, *, cwd, timeout_s, env=None):
        self.calls.append((tuple(argv), cwd, timeout_s, env))
        if self.failure is not None:
            raise self.failure
        return subprocess.CompletedProcess(argv, 7, "worker stdout", "worker stderr")


@pytest.mark.parametrize("proof", [False, True])
def test_assigned_executor_is_used_without_local_process(tmp_path: Path, proof: bool):
    boundary = RecordingExecutor()
    argv = (sys.executable, "-c", "raise AssertionError('must not run locally')")
    with patch("subprocess.run", side_effect=AssertionError("local process launched")):
        if proof:
            result = _run_check(tmp_path, CheckCommand("check", argv, timeout_s=4),
                                tmp_path, 0, {"MYPY_CACHE_DIR": "cache"}, boundary)
            assert result.outcome is CheckOutcome.FAILED
            assert (tmp_path / "check.stdout.txt").read_text() == "worker stdout"
            assert (tmp_path / "check.stderr.txt").read_text() == "worker stderr"
        else:
            result = CommandVerifier("check", argv, timeout_s=4, executor=boundary).run(tmp_path)
            assert result.passed is False
            assert result.stdout_excerpt == "worker stdout"
        assert result.exit_code == 7
    assert boundary.calls[0][:3] == (argv, tmp_path, 4)
    assert len(boundary.calls) == 1


@pytest.mark.parametrize("proof", [False, True])
def test_boundary_refusal_never_falls_back(tmp_path: Path, proof: bool):
    boundary = RecordingExecutor(RuntimeError("isolation unavailable"))
    argv = (sys.executable, "-c", "pass")
    with (patch("subprocess.run", side_effect=AssertionError("unsafe fallback")),
          pytest.raises(RuntimeError, match="isolation unavailable")):
        if proof:
            _run_check(tmp_path, CheckCommand("check", argv, timeout_s=4),
                       tmp_path, 0, executor=boundary)
        else:
            CommandVerifier("check", argv, executor=boundary).run(tmp_path)
    assert len(boundary.calls) == 1


@pytest.mark.parametrize("proof", [False, True])
def test_boundary_timeout_is_failed_evidence(tmp_path: Path, proof: bool):
    argv = (sys.executable, "-c", "pass")
    boundary = RecordingExecutor(subprocess.TimeoutExpired(argv, 4, output="partial"))
    with patch("subprocess.run", side_effect=AssertionError("unsafe fallback")):
        if proof:
            result = _run_check(tmp_path, CheckCommand("check", argv, timeout_s=4),
                                tmp_path, 0, executor=boundary)
            assert result.outcome is CheckOutcome.FAILED
            assert (tmp_path / "check.stdout.txt").read_text() == "partial"
        else:
            result = CommandVerifier("check", argv, timeout_s=4, executor=boundary).run(tmp_path)
            assert result.passed is False
            assert result.stdout_excerpt == "partial"
    assert len(boundary.calls) == 1


def test_infrastructure_failure_does_not_blame_candidate(tmp_path):
    boundary = RecordingExecutor(CheckExecutionUnavailable("Worker unavailable"))
    result = CommandVerifier("check", [sys.executable], executor=boundary).run(tmp_path)
    assert isinstance(result, MalformedEvidence)
    assert "infrastructure unavailable" in result.reason


def test_worker_timeout_retains_byte_output_excerpt(tmp_path):
    boundary = RecordingExecutor(subprocess.TimeoutExpired([sys.executable], 4, output=b"partial"))
    result = CommandVerifier("check", [sys.executable], executor=boundary).run(tmp_path)
    assert result.passed is False
    assert result.stdout_excerpt == "partial"
