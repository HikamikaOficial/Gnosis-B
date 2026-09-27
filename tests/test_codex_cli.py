"""Codex adapter contract tests; no provider calls or authentication mutations."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from gnosis.adapters.codex_cli import (
    CodexCLIRunner,
    CodexConfigurationError,
    CodexOutputInvalid,
    parse_codex_transcript,
)
from gnosis.runner.capture import ExecutionResult


def write_events(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")


def success_events() -> list[dict[str, object]]:
    return [
        {"type": "thread.started", "thread_id": "thread-123"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "command_execution", "text": "wrong"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "answer"}},
        {"type": "turn.completed", "usage": {"input_tokens": 10}},
    ]


def test_only_agent_message_is_returned(tmp_path: Path) -> None:
    transcript = tmp_path / "out.jsonl"
    write_events(transcript, success_events())
    assert parse_codex_transcript(transcript) == {
        "result": "answer", "provider": "codex", "thread_id": "thread-123",
    }


@pytest.mark.parametrize("events", [
    [], success_events()[:-1], success_events()[:3] + success_events()[-1:],
    success_events() + [{"type": "turn.failed"}],
    [{"type": "error", "message": "quota"}],
    [{"type": "turn.failed", "error": {"message": "quota"}}],
    [{"type": "item.completed", "item": None}],
    [{"type": "item.completed", "item": {"type": "agent_message", "text": False}}],
])
def test_incomplete_or_failed_turn_is_never_a_success(
    tmp_path: Path, events: list[dict[str, object]],
) -> None:
    transcript = tmp_path / "out.jsonl"
    write_events(transcript, events)
    with pytest.raises(CodexOutputInvalid):
        parse_codex_transcript(transcript)


@pytest.mark.parametrize("blob", [
    b'not json', b'[]', b'\xff', b'{"type":"turn.failed","type":"turn.completed"}',
])
def test_invalid_jsonl_is_rejected(tmp_path: Path, blob: bytes) -> None:
    transcript = tmp_path / "out.jsonl"
    transcript.write_bytes(blob)
    with pytest.raises(CodexOutputInvalid):
        parse_codex_transcript(transcript)


def test_transcript_read_is_bounded(tmp_path: Path) -> None:
    transcript = tmp_path / "out.jsonl"
    transcript.write_bytes(b" " * 65)
    with (patch("gnosis.adapters.codex_cli.MAX_TRANSCRIPT_BYTES", 64),
          pytest.raises(CodexOutputInvalid, match="byte bound")):
        parse_codex_transcript(transcript)


@pytest.fixture
def runner(tmp_path: Path) -> CodexCLIRunner:
    executable = tmp_path / "codex.exe"
    executable.touch()
    return CodexCLIRunner(str(executable), cli_runner=Mock())


@pytest.mark.parametrize("mode,sandbox", [("plan", "read-only"), ("acceptEdits", "workspace-write")])
def test_permissions_translate_without_bypass(
    runner: CodexCLIRunner, mode: str, sandbox: str,
) -> None:
    argv = runner.build_argv("--dangerously-bypass-approvals-and-sandbox", permission_mode=mode)
    assert argv[argv.index("--sandbox") + 1] == sandbox
    assert argv[-2] == "--"  # a prompt beginning with '-' is never an option
    assert 'approval_policy="never"' in argv
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv[:-1]


def test_unknown_permission_mode_is_refused(runner: CodexCLIRunner) -> None:
    with pytest.raises(CodexConfigurationError):
        runner.build_argv("task", permission_mode="bypassPermissions")


@pytest.mark.parametrize("name", ["OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN",
                                "OPENAI_FEDERATION_RULE_ID", "OPENAI_IDENTITY_TOKEN_FILE"])
def test_alternate_auth_is_refused_without_reading_or_printing_secrets(
    runner: CodexCLIRunner, name: str,
) -> None:
    with patch("gnosis.adapters.codex_cli.subprocess.run") as process:
        with pytest.raises(CodexConfigurationError) as error:
            runner._check_auth({name: "sentinel-secret"})
        assert "sentinel-secret" not in str(error.value)
        process.assert_not_called()


@pytest.mark.parametrize("status", ["Not logged in", "Logged in using an API key"])
def test_wrong_auth_never_calls_login_or_logout(runner: CodexCLIRunner, status: str) -> None:
    with patch("gnosis.adapters.codex_cli.subprocess.run") as process:
        process.return_value = Mock(returncode=0, stdout="", stderr=status)
        with pytest.raises(CodexConfigurationError):
            runner._check_auth({})
        assert process.call_args.args[0] == [runner.binary, "login", "status"]


def test_chatgpt_login_is_accepted(runner: CodexCLIRunner) -> None:
    with patch("gnosis.adapters.codex_cli.subprocess.run") as process:
        process.return_value = Mock(returncode=0, stdout="", stderr="Logged in using ChatGPT")
        runner._check_auth({})


def test_failure_preserves_timeout_and_raw_output_for_classification(
    runner: CodexCLIRunner, tmp_path: Path,
) -> None:
    expected = ExecutionResult((runner.binary,), 1, False, False, 1.0,
                               str(tmp_path / "out"), str(tmp_path / "err"), "start", "end")
    with patch.object(runner, "_check_auth"), patch.object(runner._cli_runner, "run") as call:
        call.return_value = expected
        assert runner.run("task", tmp_path, tmp_path / "out", tmp_path / "err") is expected


def test_success_exposes_normalized_message(runner: CodexCLIRunner, tmp_path: Path) -> None:
    out = tmp_path / "out"
    write_events(out, success_events())
    expected = ExecutionResult((runner.binary,), 0, False, False, 1.0,
                               str(out), str(tmp_path / "err"), "start", "end")
    with patch.object(runner, "_check_auth"), patch.object(runner._cli_runner, "run") as call:
        call.return_value = expected
        result = runner.run("task", tmp_path, out, tmp_path / "err")
    assert result.succeeded
    assert result.parsed_json is not None
    assert result.parsed_json["result"] == "answer"


def test_trusted_worker_cannot_borrow_director_auth(runner: CodexCLIRunner, tmp_path: Path) -> None:
    with patch.object(runner, "_check_auth") as auth:
        with pytest.raises(CodexConfigurationError):
            runner.run("task", tmp_path, tmp_path / "out", tmp_path / "err",
                       require_trusted_launch=True)
        auth.assert_not_called()


def test_production_reviewer_can_select_codex_without_a_provider_call(
    runner: CodexCLIRunner,
) -> None:
    from gnosis.director.cli import build_reviewer
    with patch("gnosis.adapters.codex_cli.subprocess.run") as process:
        reviewer = build_reviewer({"provider": "codex", "binary": runner.binary})
        assert isinstance(reviewer, CodexCLIRunner)
        process.assert_not_called()


def test_unknown_production_reviewer_is_refused(runner: CodexCLIRunner) -> None:
    from gnosis.director.cli import OperatorError, build_reviewer
    with pytest.raises(OperatorError, match="unsupported"):
        build_reviewer({"provider": "unqualified", "binary": runner.binary})


@pytest.mark.parametrize("provider", ["claude", "codex", "unknown"])
def test_canonical_config_writer_preserves_provider_selection(
    runner: CodexCLIRunner, tmp_path: Path, provider: str,
) -> None:
    from gnosis.director.cli import build_reviewer
    from gnosis.director.composition import (
        CompositionError,
        OperatorConfigInputs,
        build_operator_config,
    )
    from gnosis.provision.layout import DeploymentLayout
    from gnosis.runner.claude_cli_runner import ClaudeCodeCLIRunner

    layout = DeploymentLayout(code_base=str(tmp_path / "code"),
                              state_base=str(tmp_path / "state"),
                              work_base=str(tmp_path / "work"), release_id="test")
    inputs = OperatorConfigInputs(
        layout=layout, worker_username="worker", trust_root=layout.trust_root,
        reviewer_binary=runner.binary, reviewer_id="test-reviewer",
        policy_actor="test-operator", director_root=str(tmp_path / "director"),
        repo_path=str(tmp_path), trust_state_root=layout.state_base,
        evidence_root=str(tmp_path / "evidence"), repository_id="test",
        service_name="test-service", pipe_name=r"\\.\pipe\test",
        verifier_name="test-verifier", verifier_command=("test-verifier",),
        reviewer_provider=provider,
    )
    if provider == "unknown":
        with pytest.raises(CompositionError):
            build_operator_config(inputs)
    else:
        config = build_operator_config(inputs)
        reviewer = build_reviewer(config["reviewer"])
        expected = CodexCLIRunner if provider == "codex" else ClaudeCodeCLIRunner
        assert isinstance(reviewer, expected)
        if provider == "claude":
            assert config["reviewer"] == {"binary": runner.binary}
