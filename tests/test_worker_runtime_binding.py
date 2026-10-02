from dataclasses import replace
from pathlib import Path

from gnosis.director.execution import ExecutionMode
from gnosis.trust.worker_launcher import build_transport_command, build_worker_environment
from tests.test_provider_execution import configured


def test_auth_and_task_keep_same_sealed_tool_environment(tmp_path: Path) -> None:
    port, intent, specs, _, _ = configured(tmp_path)
    assert port._codex is not None
    port._codex = replace(port._codex, trusted_path=(tmp_path, tmp_path / "git" / "cmd"))
    result = port.execute(ExecutionMode.PROVIDER_BACKED, intent, timeout_s=60)
    assert result.spec == specs[-1]
    for spec in specs:
        actual = replace(spec, environment=tuple(sorted(build_worker_environment(
            dict(port._codex.environment), frozenset({"PATH"})).items())))
        assert actual == spec
        assert dict(spec.environment)["PATH"] == f"{tmp_path};{tmp_path / 'git' / 'cmd'}"


def test_transport_uses_bound_readable_bootstrap(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime" / "python.exe"
    bootstrap = runtime.parent / "worker-bootstrap" / "gnosis" / "trust" / "bootstrap.py"
    command = build_transport_command(runtime, tmp_path / "spec.json", "a" * 64,
                                      bootstrap=bootstrap)
    assert str(bootstrap) in command
    assert "publisher" not in command
    assert "-I" in command
