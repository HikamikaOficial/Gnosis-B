import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from gnosis.director.execution import (
    ExecutionOutcome,
    TrustedExecutionError,
    WorkerAuthenticationRequired,
    WorkerExecutionCancelled,
    WorkerExecutionFailed,
)
from gnosis.director.trusted_runner import TrustedExecutionRunner


class OutputPort:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.paths: list[Path] = []

    def execute(self, mode: Any, intent: Any, **kwargs: Any) -> ExecutionOutcome:
        self.paths.append(intent.stdout_path)
        intent.stdout_path.write_bytes(b"raw result")
        intent.stderr_path.write_bytes(b"raw diagnostic")
        intent.stdout_path.with_name(intent.stdout_path.name + ".auth").write_bytes(b"login status")
        if self.failure:
            raise self.failure
        return ExecutionOutcome(0, {"result": "done"}, {}, spec=None, launched=None)


@pytest.mark.parametrize("failure", [None, WorkerExecutionFailed("exit 1"),
                                     WorkerExecutionCancelled("cancelled")])
def test_staging_retains_success_failure_and_cancel(tmp_path: Path, failure: Exception | None) -> None:
    port = OutputPort(failure)
    runner = TrustedExecutionRunner(port, workspace=tmp_path / "work",
                                    output_workspace=tmp_path / "work" / "outputs")  # type: ignore[arg-type]
    out, err = tmp_path / "protected" / "stdout", tmp_path / "protected" / "stderr"
    result = runner.run("task", tmp_path, out, err, run_id="run-staging")
    assert result.succeeded is (failure is None)
    assert result.cancelled is isinstance(failure, WorkerExecutionCancelled)
    assert result.stdout_path == str(out)
    assert out.read_bytes() == b"raw result"
    assert err.read_bytes() == b"raw diagnostic"
    assert out.with_name("stdout.auth").read_bytes() == b"login status"
    assert port.paths[0].is_relative_to(tmp_path / "work" / "outputs")
    journal = json.loads(out.with_name("stdout.staging.json").read_text())
    assert journal["stdout"] == str(port.paths[0])
    assert journal["run_id"] == "run-staging"


def test_authentication_exception_keeps_raw_and_does_not_fallback(tmp_path: Path) -> None:
    port = OutputPort(WorkerAuthenticationRequired("login required"))
    runner = TrustedExecutionRunner(port, output_workspace=tmp_path / "outputs")  # type: ignore[arg-type]
    with pytest.raises(WorkerAuthenticationRequired):
        runner.run("task", tmp_path, tmp_path / "stdout", tmp_path / "stderr")
    assert (tmp_path / "stdout").read_bytes() == b"raw result"
    assert len(port.paths) == 1


def test_existing_attempt_is_preserved_and_not_relaunched(tmp_path: Path) -> None:
    port = OutputPort()
    runner = TrustedExecutionRunner(port, output_workspace=tmp_path / "outputs")  # type: ignore[arg-type]
    out, err = tmp_path / "stdout", tmp_path / "stderr"
    assert runner.run("task", tmp_path, out, err).succeeded
    assert not runner.run("different task", tmp_path, out, err).succeeded
    assert out.read_bytes() == b"raw result"
    assert len(port.paths) == 1


def test_redirected_output_cannot_be_copied_into_protected_records(tmp_path: Path) -> None:
    secret = tmp_path / "private"
    secret.write_bytes(b"must not be copied")

    class RedirectPort(OutputPort):
        def execute(self, mode: Any, intent: Any, **kwargs: Any) -> ExecutionOutcome:
            result = super().execute(mode, intent, **kwargs)
            intent.stdout_path.unlink()
            os.link(secret, intent.stdout_path)
            return result

    runner = TrustedExecutionRunner(RedirectPort(), output_workspace=tmp_path / "outputs")  # type: ignore[arg-type]
    output = tmp_path / "retained" / "stdout"
    result = runner.run("task", tmp_path, output, output.with_name("stderr"))
    assert not result.succeeded
    assert not output.exists()
    assert runner.last_spec is None
    assert secret.read_bytes() == b"must not be copied"


def test_preserves_exact_bytes_parsed_before_staging_changes(tmp_path: Path) -> None:
    class CapturedPort(OutputPort):
        def execute(self, mode: Any, intent: Any, **kwargs: Any) -> ExecutionOutcome:
            result = super().execute(mode, intent, **kwargs)
            captured = intent.stdout_path.read_bytes()
            intent.stdout_path.write_bytes(b"changed after parsing")
            return replace(result, captured_stdout=captured)

    runner = TrustedExecutionRunner(CapturedPort(), output_workspace=tmp_path / "outputs")  # type: ignore[arg-type]
    out = tmp_path / "retained" / "stdout"
    result = runner.run("task", tmp_path, out, out.with_name("stderr"))
    assert result.succeeded
    assert out.read_bytes() == b"raw result"


def test_actual_process_death_then_fresh_runner_retains_staged_output(tmp_path: Path) -> None:
    child = r'''
import os, sys
from pathlib import Path
from gnosis.director.trusted_runner import TrustedExecutionRunner
root = Path(sys.argv[1])
class KilledPort:
    def execute(self, mode, intent, **kwargs):
        intent.stdout_path.write_bytes(b"partial before crash")
        intent.stderr_path.write_bytes(b"diagnostic before crash")
        os._exit(77)
runner = TrustedExecutionRunner(KilledPort(), output_workspace=root / "outputs")
runner.run("task", root, root / "protected" / "stdout",
           root / "protected" / "stderr", run_id="run-killed")
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    killed = subprocess.run([sys.executable, "-c", child, str(tmp_path)],
                            env=env, capture_output=True, timeout=30, check=False)
    assert killed.returncode == 77, killed.stderr
    out, err = tmp_path / "protected" / "stdout", tmp_path / "protected" / "stderr"
    assert not out.exists()
    port = OutputPort()
    restarted = TrustedExecutionRunner(port, output_workspace=tmp_path / "outputs")  # type: ignore[arg-type]
    assert restarted.recover_outputs(out, err, run_id="run-killed") == (out, err)
    assert out.read_bytes() == b"partial before crash"
    assert err.read_bytes() == b"diagnostic before crash"
    assert restarted.recover_outputs(out, err, run_id="run-killed") == ()
    assert restarted.last_spec is None
    assert not port.paths


@pytest.mark.parametrize("change", ["run_id", "stdout"])
def test_recovery_refuses_wrong_attempt_or_outside_staging(tmp_path: Path, change: str) -> None:
    out, err = tmp_path / "stdout", tmp_path / "stderr"
    runner = TrustedExecutionRunner(OutputPort(), output_workspace=tmp_path / "outputs")  # type: ignore[arg-type]
    assert runner.run("task", tmp_path, out, err, run_id="run-original").succeeded
    journal = out.with_name("stdout.staging.json")
    record = json.loads(journal.read_text())
    record[change] = "run-other" if change == "run_id" else str(tmp_path / "private")
    journal.write_text(json.dumps(record))
    with pytest.raises(TrustedExecutionError):
        runner.recover_outputs(out, err, run_id="run-original")
    assert out.read_bytes() == b"raw result"
