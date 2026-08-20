"""Record/replay for real Claude Code CLI invocations (adapter milestone 2/4).

ADR-0010 built `InteractionStore` — occurrence-aware, strict-by-default
replay — and nothing called it. This module is the wiring: a decorator
that duck-types `ClaudeCodeCLIRunner.run()` and routes every invocation
through a cassette, so `TaskEngine(cli_runner=...)` and therefore
`DirectorOrchestrator` can record a real run and replay it later without
a model, a network, or a bill.

Three decisions carry the weight here:

**The key is content, never paths.** A cassette keyed on the absolute
worktree path would be unreplayable on another machine and would still
happily replay a recording made against a *different tree at the same
path*. The workspace is identified by what the agent can actually see —
HEAD, branch, and a hash of the dirty state — so the key is both
portable and honest. MCP configs are keyed by content hash for the same
reason a policy approval is (ADR-0013): the file decides which tools the
agent can reach, so a rewrite is a different action.

**Replay must reproduce the side effects the caller reads, not just the
return value.** The engine does not read `ExecutionResult.parsed_json`
alone; it reads the stdout/stderr *files* for evidence and for failure
classification. A replay that returned a result object without
materialising those files would look like a pass and classify like a
blank run.

**Output is stored byte-exact or not at all.** Streams are recorded as
text when they are valid UTF-8 and as base64 when they are not, so a
replayed run writes the same bytes the live run wrote. A stream too
large to record faithfully is marked, and replaying it raises instead of
silently handing back a truncated prefix — the same fail-closed rule
`InteractionStore` applies to a response it could not encode.
"""
from __future__ import annotations

import base64
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ..kernel.canonical import hash_canonical
from ..kernel.git_evidence import workspace_fingerprint
from ..kernel.replay import CallSpec, InteractionStore, ReplayError
from .capture import ExecutionResult
from .claude_cli_runner import (
    DEFAULT_TIMEOUT_S,
    CancellationToken,
    ClaudeCodeCLIRunner,
    McpRunnerConfig,
)

CLI_TOOL = "claude_code_cli"

# Per stream. A CLI turn's stdout is a JSON envelope; anything past this
# is a log dump that does not belong in a cassette.
MAX_RECORDED_STREAM_BYTES = 1_048_576


class UnreplayableStream(ReplayError):
    """A recorded stream was too large to store faithfully.

    Raised on replay rather than at record time: the live call really did
    happen and its occurrence must stay in the cassette, but handing back
    a truncated prefix would be a quiet lie about what the agent saw."""


def _encode_stream(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return {"missing": f"{type(exc).__name__}: {exc}"}
    if len(raw) > MAX_RECORDED_STREAM_BYTES:
        return {"truncated": True, "size": len(raw),
                "sha256": hash_canonical(base64.b64encode(raw).decode("ascii"))}
    try:
        return {"text": raw.decode("utf-8")}
    except UnicodeDecodeError:
        # Not decodable: keep the bytes rather than a lossy approximation,
        # so a replayed run writes what the live run wrote.
        return {"b64": base64.b64encode(raw).decode("ascii")}


def _decode_stream(blob: dict[str, Any], stream: str) -> bytes:
    if blob.get("truncated"):
        raise UnreplayableStream(
            f"{stream} was {blob.get('size')} bytes at record time, over the "
            f"{MAX_RECORDED_STREAM_BYTES}-byte cassette limit; this occurrence "
            "cannot be replayed faithfully"
        )
    if "b64" in blob:
        return base64.b64decode(blob["b64"])
    if "text" in blob:
        return str(blob["text"]).encode("utf-8")
    # The live run could not read the stream either; reproduce that.
    return b""


def mcp_fingerprint(mcp: McpRunnerConfig | None, cwd: Path) -> dict[str, Any] | None:
    if mcp is None:
        return None
    configs = []
    for raw_path in mcp.config_paths:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        try:
            configs.append({"sha256": hash_canonical(candidate.read_text(encoding="utf-8"))})
        except OSError as exc:
            configs.append({"unreadable": str(exc)})
    return {"configs": configs, "strict": mcp.strict}


class ReplayingCLIRunner:
    """Duck-types `ClaudeCodeCLIRunner.run()`, through an `InteractionStore`.

    Drop-in wherever a runner is accepted (`TaskEngine(cli_runner=...)`),
    which is what makes replay reachable from the Director path rather
    than from tests only.
    """

    def __init__(
        self,
        store: InteractionStore,
        inner: ClaudeCodeCLIRunner | Any | None = None,
        fingerprint_fn: Callable[[Path], dict[str, Any]] | None = None,
    ) -> None:
        self.store = store
        self.inner = inner if inner is not None else ClaudeCodeCLIRunner()
        # Injectable so a caller can supply a cheaper or stricter identity
        # (and so a non-git workspace is a decision, not a crash).
        self.fingerprint_fn = fingerprint_fn or workspace_fingerprint

    def run(
        self,
        prompt: str,
        cwd: Path,
        stdout_path: Path,
        stderr_path: Path,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        session_id: str | None = None,
        permission_mode: str = "plan",
        model: str | None = None,
        mcp: McpRunnerConfig | None = None,
        extra_args: Sequence[str] | None = None,
        cancellation_token: CancellationToken | None = None,
        heartbeat_fn: Callable[[int], None] | None = None,
    ) -> ExecutionResult:
        spec = CallSpec(
            tool=CLI_TOOL,
            params={
                "prompt": prompt,
                "session_id": session_id,
                "permission_mode": permission_mode,
                "model": model,
                "mcp": mcp_fingerprint(mcp, cwd),
                "extra_args": list(extra_args) if extra_args else [],
                # A shorter deadline can turn a success into a timeout, so
                # it determines the response and belongs in the key.
                "timeout_s": timeout_s,
                "workspace": self.fingerprint_fn(cwd),
            },
            # Recorded, never keyed: machine-specific and time-specific.
            metadata={"cwd": str(cwd), "stdout_path": str(stdout_path),
                      "stderr_path": str(stderr_path)},
        )

        executed = False

        def live() -> dict[str, Any]:
            nonlocal executed
            executed = True
            result = self.inner.run(
                prompt=prompt, cwd=cwd, stdout_path=stdout_path, stderr_path=stderr_path,
                timeout_s=timeout_s, session_id=session_id, permission_mode=permission_mode,
                model=model, mcp=mcp, extra_args=extra_args,
                cancellation_token=cancellation_token, heartbeat_fn=heartbeat_fn,
            )
            return {
                "command": list(result.command),
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "cancelled": result.cancelled,
                "duration_s": result.duration_s,
                "started_at": result.started_at,
                "ended_at": result.ended_at,
                "parsed_json": result.parsed_json,
                "stdout": _encode_stream(stdout_path),
                "stderr": _encode_stream(stderr_path),
            }

        response = self.store.call(spec, live)
        return self._materialize(response, stdout_path, stderr_path, live_ran=executed)

    def _materialize(
        self, response: dict[str, Any], stdout_path: Path, stderr_path: Path,
        live_ran: bool,
    ) -> ExecutionResult:
        """Write the streams the caller will read, then rebuild the result.

        Done on the recording path too, not just on replay: the whole
        point of a cassette is that both runs observe the same bytes, and
        a round trip that only happens in one direction is exactly how
        "deterministic replay" turns out to be false later.

        The one exception is a stream too large to record. Replaying it
        must fail closed, but the run that *produced* it succeeded and its
        real output is already on disk — refusing to hand back a live
        run's own stdout would be the gate breaking the thing it audits.
        """
        for path, blob, name in (
            (stdout_path, response["stdout"], "stdout"),
            (stderr_path, response["stderr"], "stderr"),
        ):
            try:
                payload = _decode_stream(blob, name)
            except UnreplayableStream:
                if live_ran:
                    continue
                raise
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        return ExecutionResult(
            command=tuple(response["command"]),
            exit_code=response["exit_code"],
            timed_out=response["timed_out"],
            cancelled=response["cancelled"],
            duration_s=response["duration_s"],
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            started_at=response["started_at"],
            ended_at=response["ended_at"],
            parsed_json=response["parsed_json"],
        )
