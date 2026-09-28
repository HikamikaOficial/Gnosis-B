"""Provider calls and login inspection must both traverse the Worker boundary."""
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from gnosis.director.execution import (
    CodexWorkerConfiguration,
    ExecutionMode,
    ProviderIntent,
    TrustedExecutionError,
    TrustedExecutionPort,
    WorkerAuthenticationRequired,
    WorkerExecutionCancelled,
    WorkerExecutionFailed,
    WorkerResultInvalid,
)
from gnosis.director.trusted_runner import TrustedExecutionRunner
from tests.test_execution_port import _FakeIdentity


def configured(tmp_path: Path, *, status: str = "Logged in using ChatGPT",
               code: int = 0, cancelled: bool = False, timeout: bool = False,
               transcript: str | None = None):
    exe = tmp_path / "codex.exe"
    exe.write_bytes(b"fake executable never run")
    config = CodexWorkerConfiguration(exe, hashlib.sha256(exe.read_bytes()).hexdigest())
    handles = []
    specs = []

    def launch(spec):
        specs.append(spec)
        auth = spec.argv[1] == "login"
        content = "" if auth else (transcript if transcript is not None else "\n".join([
            json.dumps({"type": "item.completed", "item": {
                "type": "agent_message", "text": "implemented"}}),
            json.dumps({"type": "turn.completed"}),
        ]))
        Path(spec.stdout_path).write_text(content, encoding="utf-8")
        Path(spec.stderr_path).write_text(status if auth else "rate limit", encoding="utf-8")
        worker = Mock(identity=_FakeIdentity())
        worker.wait.return_value = (0 if auth else code,
                                   False if auth else timeout, False if auth else cancelled)
        handles.append(worker)
        return worker

    launcher = Mock()
    launcher.launch.side_effect = launch
    port = TrustedExecutionPort(launcher, tmp_path / "python.exe", codex=config)
    intent = ProviderIntent("implement the task", tmp_path, tmp_path / "out",
                            tmp_path / "err", run_id="run-provider")
    return port, intent, specs, handles, exe


def test_login_and_execution_both_use_sealed_worker_launch(tmp_path: Path) -> None:
    port, intent, specs, handles, _ = configured(tmp_path)
    result = port.execute(ExecutionMode.PROVIDER_BACKED, intent, timeout_s=60)
    assert len(specs) == 2
    assert specs[0].argv[1:] == ("login", "status")
    assert specs[0].run_id is None
    assert specs[1].run_id == intent.run_id
    assert specs[1].argv[-2:] == ("--", intent.prompt)
    assert "workspace-write" in specs[1].argv
    # On native Windows an unspecified sandbox implementation can downgrade
    # workspace-write to read-only, even though the Worker has filesystem access.
    assert 'windows.sandbox="unelevated"' in specs[1].argv
    assert "--dangerously-bypass-approvals-and-sandbox" not in specs[1].argv
    assert result.result["result"] == "implemented"
    assert result.spec == specs[1]
    for handle in handles:
        handle.close.assert_called_once()


@pytest.mark.parametrize("status", ["Not logged in", "Logged in using an API key", "",
                                  "Not logged in using ChatGPT"])
def test_worker_login_is_required_before_provider_call(tmp_path: Path, status: str) -> None:
    port, intent, specs, _, _ = configured(tmp_path, status=status)
    with pytest.raises(WorkerAuthenticationRequired):
        port.execute(ExecutionMode.PROVIDER_BACKED, intent, timeout_s=60)
    assert len(specs) == 1


@pytest.mark.parametrize("kwargs,error", [
    ({"code": 1}, WorkerExecutionFailed),
    ({"cancelled": True}, WorkerExecutionCancelled),
    ({"timeout": True}, WorkerExecutionFailed),
    ({"transcript": "not JSON"}, WorkerResultInvalid),
])
def test_provider_failure_never_produces_success(tmp_path: Path, kwargs, error) -> None:
    port, intent, _, handles, _ = configured(tmp_path, **kwargs)
    with pytest.raises(error):
        port.execute(ExecutionMode.PROVIDER_BACKED, intent, timeout_s=60)
    for handle in handles:
        handle.close.assert_called_once()


def test_executable_drift_refused_without_launch(tmp_path: Path) -> None:
    port, intent, specs, _, exe = configured(tmp_path)
    exe.write_bytes(b"modified")
    with pytest.raises(TrustedExecutionError, match="differs"):
        port.execute(ExecutionMode.PROVIDER_BACKED, intent, timeout_s=60)
    assert specs == []


def test_cancelled_before_auth_launch(tmp_path: Path) -> None:
    port, intent, specs, _, _ = configured(tmp_path)
    with pytest.raises(WorkerExecutionCancelled):
        port.execute(ExecutionMode.PROVIDER_BACKED, intent, timeout_s=60,
                     is_cancelled=lambda: True)
    assert specs == []


def test_runner_uses_real_prompt_and_records_only_main_launch(tmp_path: Path) -> None:
    port, intent, specs, _, _ = configured(tmp_path)
    runner = TrustedExecutionRunner(port, mode=ExecutionMode.PROVIDER_BACKED)
    result = runner.run(intent.prompt, intent.cwd, intent.stdout_path, intent.stderr_path)
    assert result.succeeded
    assert runner.last_spec == specs[1]
    assert runner.last_run_id == specs[1].run_id
    assert list(tmp_path.glob("*.cassette.json")) == []


def test_runner_auth_failure_is_not_a_code_failure(tmp_path: Path) -> None:
    port, intent, _, _, _ = configured(tmp_path, status="Not logged in")
    runner = TrustedExecutionRunner(port, mode=ExecutionMode.PROVIDER_BACKED)
    with pytest.raises(WorkerAuthenticationRequired):
        runner.run(intent.prompt, intent.cwd, intent.stdout_path, intent.stderr_path)
    assert runner.last_run_id is None


def test_provider_heartbeat_uses_observed_worker_pid(tmp_path: Path) -> None:
    port, intent, _, _, _ = configured(tmp_path)
    heartbeat = Mock()
    port.execute(ExecutionMode.PROVIDER_BACKED, replace(intent, heartbeat=heartbeat),
                 timeout_s=60)
    assert heartbeat.call_count == 2  # auth process and task process
    assert all(call.args == (_FakeIdentity().pid,) for call in heartbeat.call_args_list)


def test_heartbeat_failure_closes_worker_without_provider_launch(tmp_path: Path) -> None:
    port, intent, specs, handles, _ = configured(tmp_path)
    heartbeat = Mock(side_effect=RuntimeError("lease was lost"))
    with pytest.raises(RuntimeError, match="lease was lost"):
        port.execute(ExecutionMode.PROVIDER_BACKED, replace(intent, heartbeat=heartbeat),
                     timeout_s=60)
    assert len(specs) == 1
    handles[0].close.assert_called_once()
