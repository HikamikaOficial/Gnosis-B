"""Trusted execution port (F-33 Stage 2A).

The single Director-side abstraction through which the canonical production
composition (Stage 2B) will run one already-governed unit of agent work. It
exists to guarantee, structurally, that every governed launch traverses the
qualified F-17 Worker-launch boundary and never a plain subprocess.

Contract (ADR-0032 §9, §10):

- It accepts an already-authorized execution intent (policy/lease decisions have
  already happened upstream) plus a **bounded** execution mode.
- The image (executable + argv) is chosen ENTIRELY by this trusted code from the
  mode; the caller/operator never supplies an executable, module, or shell
  command. Unknown modes fail closed.
- It builds a `LaunchSpec` and invokes ONLY `WorkerLauncher.launch(spec)`. There
  is no `subprocess`, no PATH search, no plain-`cli_runner` fallback, and no
  same-user path here.
- It treats the Worker's stdout as UNTRUSTED input and validates it before
  returning; a non-zero exit, timeout, or malformed result fails closed.

Stage 2A implements the `DETERMINISTIC` mode (the in-Worker replay entry,
provider-free). `PROVIDER_BACKED` is a recognised bounded mode whose full wiring
is deferred (Stage 2B); requesting it here fails closed rather than falling back
to any unqualified path.
"""

from __future__ import annotations

import enum
import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from gnosis.director import deterministic_worker
from gnosis.trust.launch_spec import LaunchSpec

# H1 — the Worker's stdout is UNTRUSTED. The deterministic result is a single
# small JSON object; a compromised or buggy Worker must not be able to stream an
# unbounded payload into trusted Director memory. Read at most this many bytes
# and fail closed past it. Comfortably above a legitimate bounded result yet far
# below anything that could exhaust memory.
MAX_RESULT_BYTES = 1 << 16  # 64 KiB

# The CLOSED result schema: exactly these keys, nothing else (a Worker cannot
# smuggle extra fields the Director might later trust).
_ALLOWED_RESULT_KEYS = frozenset({
    "schema", "ok", "cassette_sha256", "turn_count", "final_message",
    "provider_calls",
})


def _reject_dup_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """H3 — refuse duplicate keys in the Worker's result JSON rather than
    silently keeping json's last-wins value, so a Worker cannot hide a second
    value under a repeated key."""
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise WorkerResultInvalid(f"duplicate key in Worker result: {key!r}")
        seen.add(key)
    return dict(pairs)


class ExecutionMode(enum.Enum):
    """The closed set of execution modes the port will select an image for."""

    DETERMINISTIC = "deterministic"
    PROVIDER_BACKED = "provider_backed"


class TrustedExecutionError(Exception):
    """Base for every fail-closed refusal in the trusted execution port."""


class ExecutionModeError(TrustedExecutionError):
    """The requested execution mode is unknown or not available here."""


class WorkerExecutionFailed(TrustedExecutionError):
    """The Worker timed out or exited non-zero."""


class WorkerResultInvalid(TrustedExecutionError):
    """The Worker's output did not satisfy the expected bounded contract."""


class _LaunchedWorker(Protocol):
    identity: Any

    def wait(self, timeout_s: float, *, poll_interval_s: float = ...,
             is_cancelled: Any = ...) -> tuple[int, bool, bool]: ...

    def close(self) -> None: ...


class WorkerLauncherPort(Protocol):
    """The exact boundary this port depends on — structurally identical to
    `gnosis.trust.worker_launcher.WorkerLauncher`. Declared here as a Protocol
    so production injects the real trusted launcher and tests inject an explicit
    fake, and so there is exactly one place the choice is made."""

    def launch(self, spec: LaunchSpec) -> _LaunchedWorker: ...


@dataclass(frozen=True)
class DeterministicIntent:
    """An already-authorized deterministic execution request.

    Every path is made absolute before it enters the sealed `LaunchSpec`. The
    cassette is DATA the deterministic Worker entry validates; it cannot select
    an image or mode (see `deterministic_worker`)."""

    cassette_path: Path
    cwd: Path
    stdout_path: Path
    stderr_path: Path
    launch_id: str | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class ExecutionOutcome:
    exit_code: int
    result: dict[str, Any]
    launch: dict[str, Any] | None
    # F-33 Stage 2B.2: the TYPED trusted-launch artefacts, surfaced additively so
    # the publication seam can bind a RunIdentity (`create_trusted_run` needs the
    # full `LaunchedWorkerIdentity` and the sealed `LaunchSpec`, not the bounded
    # summary dict). `launch` above is retained unchanged for existing consumers.
    launched: Any | None = None
    spec: LaunchSpec | None = None


class TrustedExecutionPort:
    """Runs governed work through the F-17 Worker boundary and nowhere else."""

    def __init__(self, launcher: WorkerLauncherPort, python_executable: Path) -> None:
        # `python_executable` is the qualified, absolute interpreter of the
        # deployed runtime. It is trusted configuration, never operator input,
        # and never PATH-resolved.
        self._launcher = launcher
        resolved = Path(python_executable)
        if not resolved.is_absolute():
            raise TrustedExecutionError(
                f"python executable must be an absolute path; got {resolved!r}")
        self._python = resolved

    def execute(self, mode: ExecutionMode, intent: DeterministicIntent,
                *, timeout_s: float) -> ExecutionOutcome:
        """Dispatch on the bounded mode. Unknown/unavailable modes fail closed."""
        if mode is ExecutionMode.DETERMINISTIC:
            return self._execute_deterministic(intent, timeout_s=timeout_s)
        if mode is ExecutionMode.PROVIDER_BACKED:
            raise ExecutionModeError(
                "PROVIDER_BACKED execution is deferred to Stage 2B; the "
                "canonical composition does not select it in Stage 2A")
        raise ExecutionModeError(f"unknown execution mode {mode!r}")

    def _deterministic_argv(self, cassette_path: Path) -> tuple[str, ...]:
        """The image is derived HERE, from trusted code, never from the caller.

        `-I` isolates the interpreter (drops PYTHONPATH, user-site and CWD from
        `sys.path`); `-B` suppresses bytecode writes in the Worker. The module is
        addressed by its ABSOLUTE file path, so no module-name resolution can be
        redirected."""
        module_file = Path(deterministic_worker.__file__).resolve()
        return (
            str(self._python), "-I", "-B",
            str(module_file), str(cassette_path.resolve()),
        )

    def _expected_cassette_digest(self, cassette_path: Path) -> str:
        """H4 — the trusted Director digest of the EXACT bytes it is sealing.

        Computed here, before launch, over the cassette the port itself will
        name in the sealed argv. The Worker independently digests the bytes it
        reads and reports that hash; the result reader then requires the two to
        be equal. If anyone replaces the cassette between this read and the
        Worker's open (a TOCTOU), the Worker's bytes differ, the digests will
        not match, and the run fails closed — the self-reported hash is never
        trusted on its own."""
        try:
            with open(cassette_path, "rb") as handle:
                blob = handle.read(deterministic_worker.MAX_CASSETTE_BYTES + 1)
        except OSError as exc:
            raise TrustedExecutionError(
                f"could not read cassette to bind its digest: {exc}") from exc
        if len(blob) > deterministic_worker.MAX_CASSETTE_BYTES:
            raise TrustedExecutionError(
                "cassette exceeds the deterministic bound; refusing to launch")
        return hashlib.sha256(blob).hexdigest()

    def _execute_deterministic(self, intent: DeterministicIntent,
                               *, timeout_s: float) -> ExecutionOutcome:
        cassette_path = intent.cassette_path.resolve()
        expected_digest = self._expected_cassette_digest(cassette_path)
        argv = self._deterministic_argv(cassette_path)
        spec = LaunchSpec(
            launch_id=intent.launch_id or f"det-{uuid.uuid4().hex[:16]}",
            executable=str(self._python),
            argv=argv,
            cwd=str(intent.cwd.resolve()),
            stdout_path=str(intent.stdout_path.resolve()),
            stderr_path=str(intent.stderr_path.resolve()),
            run_id=intent.run_id,
        )
        launched = self._launcher.launch(spec)
        try:
            exit_code, timed_out, _cancelled = launched.wait(timeout_s)
        finally:
            identity = getattr(launched, "identity", None)
            launched.close()
        if timed_out:
            raise WorkerExecutionFailed(
                f"deterministic Worker timed out after {timeout_s}s")
        if exit_code != 0:
            raise WorkerExecutionFailed(
                f"deterministic Worker exited {exit_code} (fail closed)")
        result = self._read_deterministic_result(
            intent.stdout_path, expected_digest=expected_digest)
        launch_summary: dict[str, Any] | None = None
        if identity is not None:
            launch_summary = _summarise_identity(identity)
        return ExecutionOutcome(
            exit_code=exit_code, result=result, launch=launch_summary,
            launched=identity, spec=spec)

    @staticmethod
    def _read_deterministic_result(stdout_path: Path, *,
                                   expected_digest: str) -> dict[str, Any]:
        # H1 — bound the read: the Worker's stdout is untrusted; never read an
        # unbounded payload into trusted Director memory.
        try:
            with open(stdout_path, "rb") as handle:
                raw = handle.read(MAX_RESULT_BYTES + 1)
        except OSError as exc:
            raise WorkerResultInvalid(
                f"could not read Worker result: {exc}") from exc
        if len(raw) > MAX_RESULT_BYTES:
            raise WorkerResultInvalid(
                f"Worker result exceeds {MAX_RESULT_BYTES} bytes (fail closed)")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkerResultInvalid(
                f"Worker result is not valid UTF-8: {exc}") from exc
        try:
            parsed = json.loads(text.strip(), object_pairs_hook=_reject_dup_keys)
        except json.JSONDecodeError as exc:
            raise WorkerResultInvalid(
                f"Worker result is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise WorkerResultInvalid("Worker result must be a JSON object")
        # Closed result schema: exactly the known keys, nothing else.
        extra = set(parsed) - _ALLOWED_RESULT_KEYS
        if extra:
            raise WorkerResultInvalid(
                f"Worker result carries unknown keys (closed schema): {sorted(extra)}")
        if parsed.get("schema") != deterministic_worker.RESULT_SCHEMA:
            raise WorkerResultInvalid(
                "Worker result schema mismatch: "
                f"{parsed.get('schema')!r} != {deterministic_worker.RESULT_SCHEMA!r}")
        if parsed.get("ok") is not True:
            raise WorkerResultInvalid("Worker result did not report ok=true")
        digest = parsed.get("cassette_sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise WorkerResultInvalid("Worker result carries no valid cassette digest")
        # H4 — bind the self-reported digest to the Director-intended bytes.
        if digest != expected_digest:
            raise WorkerResultInvalid(
                "Worker cassette digest does not match the sealed cassette "
                "(fail closed): the executed bytes are not the intended bytes")
        return parsed


def _summarise_identity(identity: Any) -> dict[str, Any]:
    """A bounded, secret-free summary of the observed Worker identity."""
    fields = ("pid", "observed_sid", "integrity", "is_administrator",
              "contained_in_job", "launch_spec_digest")
    summary: dict[str, Any] = {}
    for name in fields:
        if hasattr(identity, name):
            summary[name] = getattr(identity, name)
    return summary
