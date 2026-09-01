"""Trusted execution runner (F-33 Stage 2A integration seam).

This is the adapter that connects the governed pipeline's execution to the
OS-real-qualified `TrustedExecutionPort`. It implements the SAME duck-typed
runner interface the `TaskEngine` calls — ``run(prompt, cwd, stdout_path,
stderr_path, ...) -> ExecutionResult`` — exactly like `ClaudeCodeCLIRunner` and
`GatedAgentRunner`, so a production composition can inject it as the engine's
``cli_runner``. Every governed implementation launch then flows:

    GovernedPipeline -> scheduler.submit -> TaskEngine.execute_task
        -> engine.cli_runner.run   (this adapter)
            -> TrustedExecutionPort.execute(DETERMINISTIC, ...)
                -> WorkerLauncher.launch(sealed LaunchSpec)
                    -> F-17 bootstrap -> deterministic Worker

Trust properties:

- There is exactly ONE execution route here: `TrustedExecutionPort.execute`.
  There is NO `subprocess`, NO PATH search, NO same-user path and NO fallback to
  the old direct CLI runner. A port failure becomes a FAILED `ExecutionResult`,
  never a silent success and never a retry down an unqualified path.
- Stage 2A wires only the `DETERMINISTIC` mode (provider-free, OS-real
  qualified). `PROVIDER_BACKED` remains deferred to Stage 2B; this adapter does
  not select it.
- The deterministic Worker's output is UNTRUSTED data. This adapter only reports
  it (as `parsed_json`); it never turns it into governance authority. The
  pipeline's verifier and review gates remain the authorities on completion.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gnosis.director import deterministic_worker as dw
from gnosis.director.execution import (
    DeterministicIntent,
    ExecutionMode,
    TrustedExecutionError,
    TrustedExecutionPort,
    WorkerExecutionFailed,
    WorkerResultInvalid,
)
from gnosis.runner.capture import ExecutionResult

# A conservative ceiling on the deterministic replay token a prompt maps to, so
# the default cassette source can never build an oversize cassette.
_MAX_TOKEN_BYTES = 4096


def deterministic_cassette_source(prompt: str) -> bytes:
    """Default trusted cassette source: map a run request deterministically to a
    bounded, CLOSED-schema cassette. This is Stage-2A qualification scaffolding —
    a real Stage-2B replay source would resolve a RECORDED cassette for the task.
    The prompt is reduced to a bounded digest so the cassette is always small and
    never carries free-form or authority-shaped content."""
    token = "deterministic-replay:" + hashlib.sha256(
        prompt.encode("utf-8")).hexdigest()
    cassette = {
        "schema": dw.CASSETTE_SCHEMA,
        "turns": [{"message": token[:_MAX_TOKEN_BYTES]}],
    }
    return json.dumps(cassette, separators=(",", ":")).encode("utf-8")


class TrustedExecutionRunner:
    """Runs governed work through `TrustedExecutionPort` and nowhere else."""

    def __init__(self, port: TrustedExecutionPort, *,
                 cassette_source: Callable[[str], bytes] = deterministic_cassette_source,
                 workspace: Path | None = None,
                 default_timeout_s: float = 1800.0) -> None:
        # `workspace` is a Worker-READABLE directory the trusted composition
        # supplies for the sealed cassette. It is deployment configuration, never
        # operator input. When omitted (component tests), the run's own cwd is
        # used.
        self._port = port
        self._cassette_source = cassette_source
        self._workspace = workspace
        self._default_timeout_s = default_timeout_s

    @property
    def binary(self) -> str:
        # The engine records a runner's binary name for its launch snapshot.
        return "trusted-execution-port:deterministic"

    def run(self, prompt: str, cwd: Path, stdout_path: Path, stderr_path: Path,
            timeout_s: float | None = None, **_kwargs: Any) -> ExecutionResult:
        """Execute one governed unit through the trusted seam.

        Extra keyword arguments (``permission_mode``, ``mcp``, ``model``,
        ``cancellation_token``, ``heartbeat_fn``, ``env`` …) are accepted for
        interface compatibility with the CLI runner and deliberately ignored:
        the deterministic seam takes no provider, permission or environment
        input — the image and mode are fixed by trusted code.
        """
        cwd = Path(cwd)
        stdout_path = Path(stdout_path)
        stderr_path = Path(stderr_path)
        effective_timeout = timeout_s if timeout_s is not None else self._default_timeout_s

        workspace = self._workspace if self._workspace is not None else cwd
        workspace.mkdir(parents=True, exist_ok=True)
        cassette_path = workspace / f"{stdout_path.stem}.cassette.json"
        cassette_path.write_bytes(self._cassette_source(prompt))

        intent = DeterministicIntent(
            cassette_path=cassette_path, cwd=cwd,
            stdout_path=stdout_path, stderr_path=stderr_path)

        started = datetime.now(UTC)
        command = ("trusted-execution-port", "deterministic", str(cassette_path))
        try:
            outcome = self._port.execute(
                ExecutionMode.DETERMINISTIC, intent, timeout_s=effective_timeout)
        except WorkerExecutionFailed as exc:
            # A non-zero exit or a timeout inside the trusted Worker. Surface it
            # as a FAILED result; never a success, never a fallback.
            timed_out = "timed out" in str(exc)
            return self._failed(command, started, stdout_path, stderr_path,
                                timed_out=timed_out)
        except (WorkerResultInvalid, TrustedExecutionError) as exc:  # noqa: F841
            # Malformed/oversize/tampered Worker output, or any other fail-closed
            # refusal from the port. It CANNOT become a successful completion.
            return self._failed(command, started, stdout_path, stderr_path,
                                timed_out=False)

        ended = datetime.now(UTC)
        return ExecutionResult(
            command=command, exit_code=outcome.exit_code, timed_out=False,
            cancelled=False, duration_s=(ended - started).total_seconds(),
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            started_at=started.isoformat(), ended_at=ended.isoformat(),
            parsed_json=outcome.result, launch=outcome.launch)

    @staticmethod
    def _failed(command: tuple[str, ...], started: datetime, stdout_path: Path,
                stderr_path: Path, *, timed_out: bool) -> ExecutionResult:
        ended = datetime.now(UTC)
        return ExecutionResult(
            command=command, exit_code=None if timed_out else 1,
            timed_out=timed_out, cancelled=False,
            duration_s=(ended - started).total_seconds(),
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            started_at=started.isoformat(), ended_at=ended.isoformat(),
            parsed_json=None, launch=None)
