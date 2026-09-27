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
- The mode is fixed by trusted construction, never by a task. Production
  composition still defaults to the qualified deterministic mode; a configured
  provider runner forwards the real prompt to the port's dedicated Worker path.
- The deterministic Worker's output is UNTRUSTED data. This adapter only reports
  it (as `parsed_json`); it never turns it into governance authority. The
  pipeline's verifier and review gates remain the authorities on completion.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from gnosis.director import deterministic_worker as dw
from gnosis.director.execution import (
    DeterministicIntent,
    ExecutionMode,
    ProviderIntent,
    TrustedExecutionError,
    TrustedExecutionPort,
    WorkerAuthenticationRequired,
    WorkerExecutionCancelled,
    WorkerExecutionFailed,
    WorkerResultInvalid,
)
from gnosis.runner.capture import ExecutionResult
from gnosis.trust.run_identity import is_storable_run_id
from gnosis.trust.worker_output import read_worker_output, retain_worker_output

# A conservative ceiling on the deterministic replay token a prompt maps to, so
# the default cassette source can never build an oversize cassette.
_MAX_TOKEN_BYTES = 4096


class CancellationSignal(Protocol):
    def is_cancelled(self) -> bool: ...


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

    accepts_run_id = True

    def __init__(self, port: TrustedExecutionPort, *,
                 cassette_source: Callable[[str], bytes] = deterministic_cassette_source,
                 workspace: Path | None = None,
                 output_workspace: Path | None = None,
                 default_timeout_s: float = 1800.0,
                 mode: ExecutionMode = ExecutionMode.DETERMINISTIC) -> None:
        # `workspace` is a Worker-READABLE directory the trusted composition
        # supplies for the sealed cassette. It is deployment configuration, never
        # operator input. When omitted (component tests), the run's own cwd is
        # used.
        self._port = port
        self._cassette_source = cassette_source
        self._workspace = workspace
        self._output_workspace = output_workspace
        self._default_timeout_s = default_timeout_s
        if mode not in (ExecutionMode.DETERMINISTIC, ExecutionMode.PROVIDER_BACKED):
            raise ValueError("unsupported trusted execution mode")
        self._mode = mode
        # F-33 Stage 2B.2: the trusted-launch artefacts of the most recent
        # SUCCESSFUL execution, read by the publication seam to bind a
        # RunIdentity. UNTRUSTED Worker stdout is never among them.
        self.last_launched: Any | None = None
        self.last_spec: Any | None = None
        self.last_run_id: str | None = None
        self._captured_stdout: bytes | None = None

    @property
    def binary(self) -> str:
        # The engine records a runner's binary name for its launch snapshot.
        return f"trusted-execution-port:{self._mode.value}"

    def clear_launch(self) -> None:
        """Invalidate publication references before a new governed attempt."""
        self.last_launched = None
        self.last_spec = None
        self.last_run_id = None
        self._captured_stdout = None

    @property
    def default_permission_mode(self) -> str:
        return "acceptEdits" if self._mode is ExecutionMode.PROVIDER_BACKED else "plan"

    def run(self, prompt: str, cwd: Path, stdout_path: Path, stderr_path: Path,
            timeout_s: float | None = None,
            cancellation_token: CancellationSignal | None = None,
            **kwargs: Any) -> ExecutionResult:
        """Keep Worker-writable output separate from protected attempt records."""
        if self._output_workspace is None:
            return self._run(prompt, cwd, stdout_path, stderr_path, timeout_s,
                             cancellation_token, **kwargs)
        self.clear_launch()
        if kwargs.get("run_id") is None:
            kwargs["run_id"] = f"run-{uuid.uuid4().hex[:16]}"
        if not is_storable_run_id(kwargs["run_id"]):
            raise TrustedExecutionError("run_id must be a valid durable attempt identifier")
        stage = self._output_workspace / uuid.uuid4().hex
        stage.mkdir(parents=True, exist_ok=False)
        destinations = (Path(stdout_path), Path(stderr_path))
        staged = (stage / "stdout.log", stage / "stderr.log")
        started = datetime.now(UTC)
        result: ExecutionResult | None = None
        try:
            journal = destinations[0].with_name(destinations[0].name + ".staging.json")
            retain_worker_output(journal, json.dumps({
                "schema": "gnosis.worker-output-staging.v1", "run_id": kwargs.get("run_id"),
                "stdout": str(staged[0]), "stderr": str(staged[1])}).encode("utf-8"))
            try:
                result = self._run(prompt, cwd, *staged, timeout_s,
                                   cancellation_token, **kwargs)
            finally:
                # Retain partial/error/auth output even when the port raises.
                # Each unique stage remains available if capture itself fails.
                for source, target in zip(staged, destinations, strict=True):
                    for suffix in ("", ".auth"):
                        candidate = source.with_name(source.name + suffix)
                        destination = target.with_name(target.name + suffix)
                        captured = (self._captured_stdout if source == staged[0]
                                    and not suffix else None)
                        if captured is None and not candidate.exists():
                            if not suffix and result is not None and result.succeeded:
                                raise OSError("successful Worker has missing raw output")
                            continue
                        data = (captured if captured is not None else
                                read_worker_output(candidate, limit=16 * 1024**2))
                        # Never overwrite another attempt's retained evidence.
                        retain_worker_output(destination, data)
        except OSError:
            self.clear_launch()
            return self._failed(("trusted-execution-port", self._mode.value),
                                started, *destinations, timed_out=False)
        assert result is not None
        return replace(result, stdout_path=str(destinations[0]),
                       stderr_path=str(destinations[1]))

    def recover_outputs(self, stdout_path: Path, stderr_path: Path, *,
                        run_id: str) -> tuple[Path, ...]:
        """Retain abandoned staging as forensic data; never resume a success claim."""
        if self._output_workspace is None:
            return ()
        journal = stdout_path.with_name(stdout_path.name + ".staging.json")
        if not journal.exists():
            return ()  # Older or never-launched attempts have no staged output.
        try:
            record = json.loads(read_worker_output(journal, limit=16384))
            if (not isinstance(record, dict)
                    or set(record) != {"schema", "run_id", "stdout", "stderr"}
                    or record["schema"] != "gnosis.worker-output-staging.v1"
                    or record["run_id"] != run_id
                    or not is_storable_run_id(run_id)):
                raise ValueError("invalid staging attribution")
            sources = (Path(record["stdout"]), Path(record["stderr"]))
            parent = sources[0].parent
            if (parent.parent.absolute() != self._output_workspace.absolute()
                    or len(parent.name) != 32
                    or any(c not in "0123456789abcdef" for c in parent.name)
                    or sources != (parent / "stdout.log", parent / "stderr.log")):
                raise ValueError("staging paths are outside the assigned output area")
        except (ValueError, TypeError, KeyError) as exc:
            raise TrustedExecutionError("invalid protected output staging journal") from exc
        retained: list[Path] = []
        for source, target in zip(sources, (stdout_path, stderr_path), strict=True):
            for suffix in ("", ".auth"):
                candidate = source.with_name(source.name + suffix)
                destination = target.with_name(target.name + suffix)
                if destination.exists() or not candidate.exists():
                    continue
                data = read_worker_output(candidate, limit=16 * 1024**2)
                try:
                    retain_worker_output(destination, data)
                except FileExistsError:
                    continue  # Another recovery already retained it; never replace.
                retained.append(destination)
        return tuple(retained)

    def _run(self, prompt: str, cwd: Path, stdout_path: Path, stderr_path: Path,
            timeout_s: float | None = None,
            cancellation_token: CancellationSignal | None = None,
            **_kwargs: Any) -> ExecutionResult:
        """Execute one governed unit through the trusted seam.

        Extra keyword arguments (``permission_mode``, ``mcp``, ``model``,
        ``heartbeat_fn``, ``env`` …) are accepted for
        interface compatibility with the CLI runner and deliberately ignored:
        the deterministic seam takes no provider, permission or environment
        input — the image and mode are fixed by trusted code.
        """
        self.clear_launch()
        if self._mode is ExecutionMode.PROVIDER_BACKED:
            if any(_kwargs.get(key) for key in ("mcp", "model", "session_id", "extra_args", "env")):
                raise TrustedExecutionError("provider overrides are not supported by trusted Worker")
            if _kwargs.get("permission_mode", "acceptEdits") != "acceptEdits":
                raise TrustedExecutionError("trusted implementer requires workspace-write mode")
        cwd = Path(cwd)
        stdout_path = Path(stdout_path)
        stderr_path = Path(stderr_path)
        effective_timeout = timeout_s if timeout_s is not None else self._default_timeout_s

        workspace = self._workspace if self._workspace is not None else cwd
        workspace.mkdir(parents=True, exist_ok=True)
        # A run id sealed into the LaunchSpec, so the publication seam can bind
        # this exact sealed execution to a RunIdentity (spec.run_id == plan.run_id).
        run_id = _kwargs.get("run_id")
        if run_id is None:
            run_id = f"run-{uuid.uuid4().hex[:16]}"
        if not is_storable_run_id(run_id):
            raise TrustedExecutionError("run_id must be a valid durable attempt identifier")
        intent: DeterministicIntent | ProviderIntent
        command: tuple[str, ...]
        if self._mode is ExecutionMode.DETERMINISTIC:
            cassette_path = workspace / f"{run_id}-{uuid.uuid4().hex}.cassette.json"
            cassette_path.write_bytes(self._cassette_source(prompt))
            intent = DeterministicIntent(
                cassette_path=cassette_path, cwd=cwd,
                stdout_path=stdout_path, stderr_path=stderr_path, run_id=run_id)
            command = ("trusted-execution-port", "deterministic", str(cassette_path))
        else:
            intent = ProviderIntent(prompt=prompt, cwd=cwd, stdout_path=stdout_path,
                                    stderr_path=stderr_path, run_id=run_id,
                                    heartbeat=_kwargs.get("heartbeat_fn"))
            command = ("trusted-execution-port", "provider_backed")

        started = datetime.now(UTC)
        try:
            cancellation_args = (
                {"is_cancelled": cancellation_token.is_cancelled}
                if cancellation_token is not None else {})
            outcome = self._port.execute(
                self._mode, intent, timeout_s=effective_timeout,
                **cancellation_args)
        except WorkerAuthenticationRequired:
            # Requires operator login as the Worker, not a code-repair attempt.
            raise
        except WorkerExecutionCancelled:
            return self._failed(command, started, stdout_path, stderr_path,
                                timed_out=False, cancelled=True)
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
        # Record the TYPED trusted-launch artefacts for the publication seam.
        self.last_launched = outcome.launched
        self.last_spec = outcome.spec
        self.last_run_id = run_id
        self._captured_stdout = outcome.captured_stdout
        return ExecutionResult(
            command=command, exit_code=outcome.exit_code, timed_out=False,
            cancelled=False, duration_s=(ended - started).total_seconds(),
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            started_at=started.isoformat(), ended_at=ended.isoformat(),
            parsed_json=outcome.result, launch=outcome.launch)

    @staticmethod
    def _failed(command: tuple[str, ...], started: datetime, stdout_path: Path,
                stderr_path: Path, *, timed_out: bool,
                cancelled: bool = False) -> ExecutionResult:
        ended = datetime.now(UTC)
        return ExecutionResult(
            command=command, exit_code=None if timed_out else 1,
            timed_out=timed_out, cancelled=cancelled,
            duration_s=(ended - started).total_seconds(),
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            started_at=started.isoformat(), ended_at=ended.isoformat(),
            parsed_json=None, launch=None)
