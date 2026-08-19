"""Claude CLI runner abstraction.

Gnosis never talks to the Anthropic API directly, no billing, no Agent
SDK dependency (see project CLAUDE.md). Instead it shells out to the
locally installed claude CLI exactly as a human operator would.
CLIRunner is the generic subprocess-with-timeout-and-capture primitive;
ClaudeCodeCLIRunner specializes it to Claude Code's -p/--print flags.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

from .capture import ExecutionResult

DEFAULT_TIMEOUT_S = 1800.0


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True)
class McpRunnerConfig:
    """Optional, explicit MCP server configuration for one Claude Code CLI
    invocation (M2.0). Disabled by default: pass None (the default
    everywhere it is accepted) and a run's argv is byte-for-byte what M0/M1
    already produced. Not tied to any specific MCP server implementation,
    `config_paths` are handed verbatim to `claude --mcp-config`, so this
    is how Gnosis exposes *any* local engineering tool (a code-intelligence
    server, or anything else) to a Claude Code session, without the kernel
    depending on which one. This is unrelated to, and does not implement,
    a ChatGPT/Director MCP transport (see gnosis.transport.mcp_transport).
    """

    config_paths: tuple[str, ...]
    strict: bool = False

    def __post_init__(self) -> None:
        if not self.config_paths:
            raise ValueError("McpRunnerConfig.config_paths must be non-empty")

    def to_dict(self) -> dict:
        return {"config_paths": list(self.config_paths), "strict": self.strict}


class CLIRunner:
    """Generic: run an argv, capture raw stdout/stderr to files, enforce a
    hard timeout, support cooperative cancellation via CancellationToken."""

    def __init__(self, poll_interval_s: float = 0.2):
        self.poll_interval_s = poll_interval_s

    def run(
        self,
        argv: Sequence[str],
        cwd: Path,
        stdout_path: Path,
        stderr_path: Path,
        timeout_s: float,
        cancellation_token: Optional[CancellationToken] = None,
        heartbeat_fn: Optional[Callable[[int], None]] = None,
        heartbeat_interval_s: float = 5.0,
    ) -> ExecutionResult:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now(timezone.utc).isoformat()
        start_monotonic = time.monotonic()

        with stdout_path.open("wb") as out_fh, stderr_path.open("wb") as err_fh:
            proc = subprocess.Popen(list(argv), cwd=str(cwd), stdout=out_fh, stderr=err_fh)

            timed_out = False
            cancelled = False
            last_heartbeat = 0.0
            while True:
                try:
                    proc.wait(timeout=self.poll_interval_s)
                    break
                except subprocess.TimeoutExpired:
                    elapsed = time.monotonic() - start_monotonic
                    if heartbeat_fn and (elapsed - last_heartbeat) >= heartbeat_interval_s:
                        heartbeat_fn(proc.pid)
                        last_heartbeat = elapsed
                    if cancellation_token is not None and cancellation_token.is_cancelled():
                        cancelled = True
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()
                        break
                    if elapsed >= timeout_s:
                        timed_out = True
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()
                        break

        ended_at = datetime.now(timezone.utc).isoformat()
        duration = time.monotonic() - start_monotonic

        return ExecutionResult(
            command=tuple(argv), exit_code=proc.returncode, timed_out=timed_out,
            cancelled=cancelled, duration_s=duration, stdout_path=str(stdout_path),
            stderr_path=str(stderr_path), started_at=started_at, ended_at=ended_at,
        )


class ClaudeCodeCLIRunner:
    """Invokes the local Claude Code CLI in non-interactive print mode."""

    def __init__(self, binary: str = "claude", cli_runner: Optional[CLIRunner] = None):
        self.binary = binary
        self._cli_runner = cli_runner or CLIRunner()

    def build_argv(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        permission_mode: str = "plan",
        output_format: str = "json",
        model: Optional[str] = None,
        mcp: Optional[McpRunnerConfig] = None,
        extra_args: Optional[Sequence[str]] = None,
    ) -> list[str]:
        argv = [self.binary, "-p", prompt, "--output-format", output_format]
        if session_id:
            argv += ["--session-id", session_id]
        if permission_mode:
            argv += ["--permission-mode", permission_mode]
        if model:
            argv += ["--model", model]
        if mcp is not None:
            argv += ["--mcp-config", *mcp.config_paths]
            if mcp.strict:
                argv.append("--strict-mcp-config")
        if extra_args:
            argv += list(extra_args)
        return argv

    def run(
        self,
        prompt: str,
        cwd: Path,
        stdout_path: Path,
        stderr_path: Path,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        session_id: Optional[str] = None,
        permission_mode: str = "plan",
        model: Optional[str] = None,
        mcp: Optional[McpRunnerConfig] = None,
        extra_args: Optional[Sequence[str]] = None,
        cancellation_token: Optional[CancellationToken] = None,
        heartbeat_fn: Optional[Callable[[int], None]] = None,
    ) -> ExecutionResult:
        argv = self.build_argv(
            prompt, session_id=session_id, permission_mode=permission_mode,
            model=model, mcp=mcp, extra_args=extra_args,
        )
        result = self._cli_runner.run(
            argv, cwd=cwd, stdout_path=stdout_path, stderr_path=stderr_path,
            timeout_s=timeout_s, cancellation_token=cancellation_token, heartbeat_fn=heartbeat_fn,
        )
        parsed_json = None
        if result.succeeded:
            try:
                text = stdout_path.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    parsed_json = json.loads(text)
            except (json.JSONDecodeError, OSError):
                parsed_json = None
        return ExecutionResult(
            command=result.command, exit_code=result.exit_code, timed_out=result.timed_out,
            cancelled=result.cancelled, duration_s=result.duration_s, stdout_path=result.stdout_path,
            stderr_path=result.stderr_path, started_at=result.started_at, ended_at=result.ended_at,
            parsed_json=parsed_json,
        )
