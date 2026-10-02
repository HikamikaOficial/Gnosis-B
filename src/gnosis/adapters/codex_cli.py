"""Codex CLI adapter using existing ChatGPT login, bounded JSONL and sandboxing.

No login/logout, credential copy, API client, or paid-key fallback is performed.
Provider details stay outside the kernel. Production trusted-worker wiring must
still supply its qualified launcher; this adapter alone is not that qualification.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from gnosis.runner.capture import ExecutionResult
from gnosis.runner.claude_cli_runner import (
    DEFAULT_TIMEOUT_S,
    CancellationToken,
    CLIRunner,
    McpRunnerConfig,
)

MAX_TRANSCRIPT_BYTES = 8 * 1024 * 1024
_AUTH_OVERRIDES = frozenset({
    "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN",
    "OPENAI_FEDERATION_RULE_ID", "OPENAI_IDENTITY_TOKEN_FILE",
})


class CodexConfigurationError(ValueError):
    """The requested invocation cannot preserve this adapter's contract."""


class CodexOutputInvalid(ValueError):
    """The transcript does not prove that a complete turn returned a message."""


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CodexOutputInvalid("duplicate JSON key in Codex event")
        result[key] = value
    return result


def parse_codex_transcript(path: Path) -> dict[str, Any]:
    """Normalize a completed Codex turn to the existing review-message envelope.

    Raw JSONL remains on disk. Tool output and reasoning are never treated as
    the agent's final response. Incomplete, failed and malformed turns are refused.
    """
    with path.open("rb") as stream:
        raw = stream.read(MAX_TRANSCRIPT_BYTES + 1)
    return parse_codex_transcript_bytes(raw)


def parse_codex_transcript_bytes(raw: bytes) -> dict[str, Any]:
    """Parse already captured bytes without reopening a Worker-controlled path."""
    if len(raw) > MAX_TRANSCRIPT_BYTES:
        raise CodexOutputInvalid("Codex transcript exceeds its byte bound")
    try:
        lines = raw.decode("utf-8").splitlines()
        completed = False
        message: str | None = None
        thread_id: str | None = None
        for line in lines:
            if not line.strip():
                continue
            event = json.loads(line, object_pairs_hook=_unique_keys)
            if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                raise CodexOutputInvalid("Codex event is not a typed object")
            if completed:
                raise CodexOutputInvalid("unexpected event after turn completion")
            kind = event["type"]
            if kind in {"turn.failed", "error"}:
                raise CodexOutputInvalid("Codex reported a failed turn")
            if kind == "thread.started":
                value = event.get("thread_id")
                if not isinstance(value, str) or not value:
                    raise CodexOutputInvalid("Codex thread identifier is absent")
                thread_id = value
            elif kind == "item.completed":
                item = event.get("item")
                if not isinstance(item, dict):
                    raise CodexOutputInvalid("Codex item is not an object")
                if item.get("type") == "agent_message":
                    text = item.get("text")
                    if not isinstance(text, str):
                        raise CodexOutputInvalid("Codex agent message is not text")
                    text.encode("utf-8")
                    message = text
            elif kind == "turn.completed":
                completed = True
        if not completed or message is None or not message.strip():
            raise CodexOutputInvalid("Codex turn has no completed final message")
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CodexOutputInvalid("Codex transcript is malformed") from exc
    return {"result": message, "provider": "codex", "thread_id": thread_id}


class CodexCLIRunner:
    """Compatible with the existing engine and read-only review adapter.

    Unsupported Claude-specific options fail before launch instead of silently
    changing their meaning. Authentication is inspected through `login status`,
    never by opening the credential store. Model selection remains optional.
    """

    def __init__(self, binary: str, cli_runner: CLIRunner | None = None) -> None:
        path = Path(binary)
        if not path.is_absolute() or not path.is_file():
            raise CodexConfigurationError("Codex requires an existing absolute executable")
        if os.name == "nt" and path.suffix.lower() != ".exe":
            raise CodexConfigurationError("Use the native codex.exe, not a shell shim")
        self.binary = str(path)
        self._cli_runner = cli_runner or CLIRunner()

    def build_argv(
        self, prompt: str, *, permission_mode: str = "plan", model: str | None = None,
    ) -> list[str]:
        modes = {"plan": "read-only", "acceptEdits": "workspace-write"}
        if permission_mode not in modes:
            raise CodexConfigurationError("unsupported Codex permission mode")
        argv = [self.binary, "exec", "--json", "--color", "never", "--sandbox",
                modes[permission_mode], "-c", 'approval_policy="never"',
                "-c", 'model_provider="openai"']
        if model is not None:
            if not model.strip():
                raise CodexConfigurationError("model must not be empty")
            argv.extend(["--model", model])
        argv.extend(["--", prompt])
        return argv

    def _check_auth(self, env: Mapping[str, str]) -> None:
        if any(name.upper() in _AUTH_OVERRIDES and value for name, value in env.items()):
            raise CodexConfigurationError("alternate authentication environment is refused")
        status = subprocess.run(
            [self.binary, "login", "status"], env=dict(env), capture_output=True,
            text=True, timeout=15, check=False,
        )
        if status.returncode != 0 or not any(
            line.strip().lower() == "logged in using chatgpt"
            for line in (status.stdout + "\n" + status.stderr).splitlines()
        ):
            raise CodexConfigurationError("an existing ChatGPT login is required")

    def run(
        self, prompt: str, cwd: Path, stdout_path: Path, stderr_path: Path,
        timeout_s: float = DEFAULT_TIMEOUT_S, session_id: str | None = None,
        permission_mode: str = "plan", model: str | None = None,
        mcp: McpRunnerConfig | None = None, extra_args: Sequence[str] | None = None,
        cancellation_token: CancellationToken | None = None,
        heartbeat_fn: Callable[[int], None] | None = None,
        env: Mapping[str, str] | None = None,
        launcher: Any = None, require_trusted_launch: bool = False,
        launch_id: str | None = None, run_id: str | None = None,
    ) -> ExecutionResult:
        if session_id or mcp is not None or extra_args:
            raise CodexConfigurationError("resume, MCP overrides and extra flags are unsupported")
        # The launcher's worker has a different authentication store. Until its
        # auth preflight is implemented inside that boundary, do not attest the
        # Director's login as the Worker's login.
        if launcher is not None or require_trusted_launch:
            raise CodexConfigurationError("trusted Codex worker authentication is not qualified")
        argv = self.build_argv(prompt, permission_mode=permission_mode, model=model)
        child_env = dict(os.environ if env is None else env)
        self._check_auth(child_env)
        result = self._cli_runner.run(
            argv, cwd=cwd, stdout_path=stdout_path, stderr_path=stderr_path,
            timeout_s=timeout_s, cancellation_token=cancellation_token,
            heartbeat_fn=heartbeat_fn, env=child_env,
        )
        if not result.succeeded:
            # Preserve raw failure text for the kernel's graded rate-limit
            # classifier. Do not turn an unverified provider message into a
            # structured rate-limit claim or a success envelope.
            return result
        try:
            payload = parse_codex_transcript(stdout_path)
        except OSError as exc:
            raise CodexOutputInvalid("Codex transcript could not be read") from exc
        return replace(result, parsed_json=payload)
