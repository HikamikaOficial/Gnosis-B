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
import binascii
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..kernel.canonical import hash_canonical
from ..kernel.git_evidence import content_fingerprint
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


class ReplayedFailure(ReplayError):
    """The recorded call raised when it ran live, so the replay raises too.

    A replay that quietly produced a result for a call which never
    produced one would make a failed run replay as a pass."""


class UnreplayableStream(ReplayError):
    """A recorded stream was too large to store faithfully.

    Raised on replay rather than at record time: the live call really did
    happen and its occurrence must stay in the cassette, but handing back
    a truncated prefix would be a quiet lie about what the agent saw."""


def _encode_stream(path: Path) -> dict[str, Any]:
    try:
        # Size FIRST. Reading the whole file and then checking the cap
        # bounded what the cassette stores but not what the recorder
        # pulls into memory, so a multi-gigabyte log dump was an OOM
        # after the paid call (independent review). The safer pattern
        # already existed in adapters/cli_review.py and was not applied
        # here.
        size = path.stat().st_size
        if size > MAX_RECORDED_STREAM_BYTES:
            return {"truncated": True, "size": size}
        raw = path.read_bytes()
    except OSError as exc:
        return {"missing": f"{type(exc).__name__}: {exc}"}
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
        # validate=True: without it, characters outside the base64
        # alphabet are SILENTLY DISCARDED and a tampered row decodes to
        # different bytes than it claims (independent review).
        try:
            return base64.b64decode(blob["b64"], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise UnreplayableStream(
                f"{stream} was recorded as base64 that does not decode: {exc}"
            ) from exc
    if "text" in blob:
        return str(blob["text"]).encode("utf-8")
    if "missing" in blob:
        # The live run could not read this stream. Writing b"" would
        # OVERWRITE whatever is actually on disk with nothing — the
        # audit doing worse than refusing (independent review).
        raise UnreplayableStream(
            f"{stream} could not be read when the call was recorded "
            f"({blob['missing']}); there is nothing faithful to restore"
        )
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
            # The ERROR CLASS, not str(exc): an OSError message embeds the
            # full absolute path, which put a machine-local string into
            # the supposedly portable key (independent review).
            configs.append({"unreadable": type(exc).__name__})
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
        self.fingerprint_fn = fingerprint_fn or content_fingerprint
        # The SESSION BASELINE, captured once per workspace, not per call.
        # Fingerprinting each call separately was the mechanism's central
        # defect: the agent being recorded EDITS the tree, so call 2 saw a
        # different workspace than call 1 and got a different key — while
        # a replay, which reproduces stdout/stderr but not the agent's
        # edits, computed call 1's key again. Every recording of a
        # repository-mutating agent was therefore unreplayable past the
        # first call (independent review, with a reproduction). Anchoring
        # on the state the session STARTED from keeps the honest property
        # — a cassette only replays against the tree it was recorded
        # against — without keying on state replay cannot restore.
        self._baselines: dict[str, dict[str, Any]] = {}

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
        # Accepted and DELIBERATELY ignored. A replayed launch spends no
        # credential — the cassette is the answer — and the environment
        # must never reach the fingerprint below: a cassette is a file
        # that gets committed, and a key built from the child's
        # environment would write a secret into it.
        env: Mapping[str, str] | None = None,
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
                "workspace": self._baseline_for(cwd),
            },
            # Recorded, never keyed: machine-specific and time-specific.
            metadata={"cwd": str(cwd), "stdout_path": str(stdout_path),
                      "stderr_path": str(stderr_path)},
        )

        executed = False
        live_response: dict[str, Any] | None = None
        raised: BaseException | None = None

        def live() -> dict[str, Any]:
            nonlocal executed, live_response, raised
            executed = True
            try:
                result = self.inner.run(
                    prompt=prompt, cwd=cwd, stdout_path=stdout_path,
                    stderr_path=stderr_path, timeout_s=timeout_s,
                    session_id=session_id, permission_mode=permission_mode,
                    model=model, mcp=mcp, extra_args=extra_args,
                    cancellation_token=cancellation_token, heartbeat_fn=heartbeat_fn,
                    # FORWARDED. This class is record/replay, and RECORD is
                    # the default mode: on a cassette miss a real child
                    # runs and really spends a credential. Accepting `env`
                    # and dropping it here meant the kernel decided one
                    # identity and the child authenticated as the ambient
                    # one, while `Rotation` recorded the decision — the
                    # fiction about billing this whole mechanism exists to
                    # prevent (independent review). It stays out of the
                    # cassette KEY, which is the separate and still-true
                    # concern.
                    env=env,
                )
            except Exception as exc:  # noqa: BLE001 - re-raised below, after recording
                # The call HAPPENED — it may have cost money and it may
                # have changed the world. Letting the exception escape
                # before `_append` left no row, so the next recording of
                # the same key took occurrence 0 and a failed call
                # replayed as the later success (independent review).
                # Recorded as a failure, then re-raised unchanged.
                raised = exc
                return {"raised": f"{type(exc).__name__}: {exc}"}
            live_response = {
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
            return live_response

        try:
            response = self.store.call(spec, live)
        except ReplayError:
            if executed and live_response is not None:
                # The live run happened and produced a real result; the
                # cassette merely could not encode it. Handing the caller
                # an exception instead of its own result would be the
                # audit breaking the thing it audits — the rule this
                # module already applies to oversized streams, now applied
                # here too (independent review).
                response = live_response
            else:
                raise
        if raised is not None:
            raise raised
        if isinstance(response, dict) and "raised" in response:
            # Replaying a call that failed live reproduces the failure
            # rather than inventing a result for it.
            raise ReplayedFailure(str(response["raised"]))
        return self._materialize(response, stdout_path, stderr_path, live_ran=executed)

    @property
    def binary(self) -> str:
        """The program that actually runs, borrowed from the wrapped runner.

        `TaskEngine` shows policy rules `runner.binary` and folds it into
        the action identity. Without this passthrough, wrapping a runner
        for audit reported `<unknown-runner>` to the gate — changing the
        action_id, invalidating human approvals and silencing any rule
        that matched the real program. An audit wrapper that alters the
        security decision is worse than no wrapper (independent review).
        """
        inner_binary = getattr(self.inner, "binary", None)
        return inner_binary if isinstance(inner_binary, str) and inner_binary else "<unknown-runner>"

    def _baseline_for(self, cwd: Path) -> dict[str, Any]:
        key = str(Path(cwd).resolve())
        if key not in self._baselines:
            self._baselines[key] = self.fingerprint_fn(cwd)
        return self._baselines[key]

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
