"""A failed/cancelled attempt cannot reuse a previous publication identity."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from gnosis.director.execution import (
    DeterministicIntent,
    ExecutionMode,
    ExecutionOutcome,
    TrustedExecutionError,
    TrustedExecutionPort,
    WorkerExecutionCancelled,
    WorkerResultInvalid,
)
from gnosis.director.trusted_runner import TrustedExecutionRunner
from gnosis.runner.claude_cli_runner import CancellationToken


@pytest.mark.parametrize("failure", [WorkerResultInvalid("bad"), OSError("disk")])
def test_failed_attempt_discards_previous_identity(tmp_path: Path, failure: Exception) -> None:
    port = Mock()
    port.execute.return_value = ExecutionOutcome(0, {}, {}, launched=object(), spec=object())
    runner = TrustedExecutionRunner(port)
    args = ("task", tmp_path, tmp_path / "out", tmp_path / "err")
    assert runner.run(*args).succeeded
    assert runner.last_run_id is not None
    port.execute.side_effect = failure
    if isinstance(failure, OSError):
        with pytest.raises(OSError):
            runner.run(*args)
    else:
        assert not runner.run(*args).succeeded
    assert (runner.last_launched, runner.last_spec, runner.last_run_id) == (None, None, None)


def test_cancellation_reaches_launcher_and_cannot_be_success(tmp_path: Path) -> None:
    token = CancellationToken()
    worker = Mock()
    worker.identity = None

    def wait(timeout_s: float, *, is_cancelled: object) -> tuple[int, bool, bool]:
        token.cancel()
        assert callable(is_cancelled) and is_cancelled()
        return 0, False, True  # Even a zero exit is not success after cancellation.

    worker.wait.side_effect = wait
    launcher = Mock()
    launcher.launch.return_value = worker
    port = TrustedExecutionPort(launcher, Path(r"C:\qualified\python.exe"))
    runner = TrustedExecutionRunner(port)
    result = runner.run("task", tmp_path, tmp_path / "out", tmp_path / "err",
                        cancellation_token=token)
    assert result.cancelled and not result.succeeded
    assert result.parsed_json is None and runner.last_run_id is None
    worker.close.assert_called_once()


def test_pre_cancelled_request_never_launches(tmp_path: Path) -> None:
    launcher = Mock()
    port = TrustedExecutionPort(launcher, Path(r"C:\qualified\python.exe"))
    intent = DeterministicIntent(tmp_path / "absent", tmp_path,
                                 tmp_path / "out", tmp_path / "err")
    with pytest.raises(WorkerExecutionCancelled):
        port.execute(ExecutionMode.DETERMINISTIC, intent, timeout_s=5,
                     is_cancelled=lambda: True)
    launcher.launch.assert_not_called()


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), 0, -1, True])
def test_unbounded_timeout_never_launches(tmp_path: Path, timeout: float) -> None:
    launcher = Mock()
    port = TrustedExecutionPort(launcher, Path(r"C:\qualified\python.exe"))
    intent = DeterministicIntent(tmp_path / "absent", tmp_path,
                                 tmp_path / "out", tmp_path / "err")
    with pytest.raises(TrustedExecutionError, match="positive finite"):
        port.execute(ExecutionMode.DETERMINISTIC, intent, timeout_s=timeout)
    launcher.launch.assert_not_called()


def test_brief_without_execution_clears_previous_launch(tmp_path: Path) -> None:
    from gnosis.contracts.director_brief import BriefSource, DirectorBrief
    from gnosis.contracts.engineer_report import ReportStatus
    from gnosis.director.composition import ProductionComposition, PublicationCompositionInputs

    port = Mock()
    runner = TrustedExecutionRunner(port)
    runner.last_launched = object()
    runner.last_spec = object()
    runner.last_run_id = "previous-run"
    pipeline = Mock()
    pipeline.run_brief.return_value = Mock(status=ReportStatus.COMPLETED, task_id="new-task")
    publication = PublicationCompositionInputs(tmp_path / "trust", tmp_path / "evidence",
                                               Mock(), "repo", "pipe")
    composition = ProductionComposition(pipeline, runner, publication, Path.cwd(), Mock())
    outcome = composition.run_brief(DirectorBrief("brief-1", "test", "do task", BriefSource.MANUAL))
    assert not outcome.success
    assert outcome.run_id is None
    assert "no trusted launch" in outcome.reason
    port.execute.assert_not_called()
