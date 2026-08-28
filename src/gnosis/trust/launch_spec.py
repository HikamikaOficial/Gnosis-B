"""The sealed LaunchSpec: how a long logical command crosses a short transport.

WHY THIS EXISTS. `CreateProcessWithLogonW` is the only primitive that creates the
Director -> Worker-SID boundary without acquiring a privilege the trust plane has
not been granted, and its `lpCommandLine` is capped at 1024 characters. Gnosis's
real logical command is not: the measured default engine path is ~12128
characters, and even the smallest review prompt exceeds the whole cap. Stage 5's
Gate 1 recorded that as `WORKER LAUNCH COMMAND-LINE CONTRACT NOT QUALIFIED`.

The resolution is to stop carrying the payload on the transport at all:

    transport command   a SHORT bootstrap invocation, well under the cap, whose
                        only arguments are a path and a digest.
    logical command     the EXACT executable and argv Gnosis meant to run, read
                        by the bootstrap from this file, ALREADY under the
                        Worker SID, and launched there with an ordinary
                        creation primitive whose limit is ~32767.

    PROPERTY:  logical argv before  ==  logical argv after.

Nothing about Claude's invocation semantics changes: the argv vector is
reconstructed element by element, not re-parsed from a rendered string.

WHY IT IS SEALED. The file is read by a process running as the WORKER. If that
file could be rewritten between the Director writing it and the bootstrap reading
it, the Worker would be choosing its own argv — the confused-deputy the whole
boundary exists to prevent. Two independent controls, and both are required:

    ACL          the Worker may READ the launch root and nothing else. No
                 create, write, delete, rename, WRITE_DAC or WRITE_OWNER.
                 That is the PREVENTION, and it is the OS's job.
    DIGEST       the transport command carries the expected `launch_spec_digest`,
                 which the Director computed after re-reading its own write. The
                 bootstrap recomputes it from the bytes it actually read and
                 refuses on any mismatch. That is the DETECTION, and it is this
                 module's job.

The digest is on the COMMAND LINE, not in the file: a value stored beside the
thing it protects proves self-consistency and nothing else (L-0059). Here the
anchor is external to the payload by construction.

NO SECRETS. A LaunchSpec carries an executable, an argv, a working directory, an
identifier, and a SMALL SEALED ENVIRONMENT OVERLAY. It never carries a credential
or a token, and that is enforced rather than promised: the file is
Worker-READABLE by design, so a credential-shaped NAME is refused outright and
the overlay is bounded to a handful of determinism variables.

The Worker's real environment is NOT in here. `CreateProcessWithLogonW` with
LOGON_WITH_PROFILE and `lpEnvironment = NULL` builds it from the Worker's own
profile — measured OS-real, and the reason the launcher no longer calls
`LoadUserProfileW` and therefore no longer depends on SeBackup/SeRestore.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gnosis.kernel.atomic_io import atomic_write_bytes
from gnosis.kernel.canonical import canonical_json_bytes, hash_canonical
from gnosis.trust.launch import AuthorityUnavailable

LAUNCH_SPEC_SCHEMA = "gnosis.trust.launch_spec.v1"
SUPPORTED_LAUNCH_SPEC_SCHEMAS = frozenset({LAUNCH_SPEC_SCHEMA})

# A LaunchSpec is an executable, an argv and a path. The logical commands this
# project measures are ~12 kB; a megabyte is three orders of magnitude of head
# room and still a bound, which is the point: the bootstrap must never be handed
# an unbounded read on a file it does not fully control.
MAX_LAUNCH_SPEC_BYTES = 1_048_576

# A launch_id becomes a filename inside the trusted launch root, and it is also
# the only part of the transport command that varies per run. Anything that
# could climb out of the root is refused before it is joined to a path.
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")

_FIELDS = frozenset({"schema", "launch_id", "executable", "argv", "cwd",
                     "stdout_path", "stderr_path", "environment", "run_id"})

# The sealed environment overlay is for DETERMINISM, never for credentials. The
# LaunchSpec is Worker-READABLE by design, so anything placed in it is readable
# by the Worker — which is fine for `PYTHONUTF8=1` and fatal for a token. The
# rule is enforced rather than documented: a name that looks like a credential is
# refused outright, so "just this once" is not available to a future caller.
_CREDENTIAL_SHAPED = re.compile(
    r"(?i)(KEY|TOKEN|SECRET|PASS|PASSWD|CRED|AUTH|SESSION|COOKIE|OAUTH|BEARER"
    r"|PRIVATE|SIGNATURE|LICENSE)")
_SAFE_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_ENVIRONMENT_ENTRIES = 16
MAX_ENVIRONMENT_VALUE = 1024


class LaunchSpecInvalid(AuthorityUnavailable):
    """The LaunchSpec is not something a launch may be built from.

    A subclass of `AuthorityUnavailable` so every existing fail-closed handler
    already refuses it, and a distinct type because the operator response
    differs from a boundary that could not be established: this says the
    INSTRUCTION is malformed, not that the mechanism is unavailable.
    """


class LaunchSpecUnsealed(AuthorityUnavailable):
    """The bytes on disk are not the bytes the Director sealed.

    Deliberately distinct from `LaunchSpecInvalid`. A malformed spec is a bug in
    whoever built it; THIS is the signature of the attack the seal exists for —
    something replaced or edited the payload between the write and the read —
    and it must never be answered by re-reading, retrying, or repairing.
    """


def is_storable_launch_id(value: object) -> bool:
    return (isinstance(value, str) and bool(_SAFE_ID.match(value))
            and ".." not in value)


@dataclass(frozen=True)
class LaunchSpec:
    """The trusted launcher's EXACT intention, and nothing else."""

    launch_id: str
    executable: str          # absolute path; never a bare name, never PATH-searched
    argv: tuple[str, ...]    # the exact logical argv vector, argv[0] included
    cwd: str                 # absolute path; the run's authorized workspace
    # WHY THE OUTPUT PATHS TRAVEL IN THE SPEC RATHER THAN AS HANDLES.
    # `CreateProcessWithLogonW` creates the process through the Secondary Logon
    # service, in a different logon session, and handle inheritance across that
    # boundary is not something to assume. Naming the paths instead lets the
    # bootstrap open them ITSELF, as the Worker, with the Worker's own rights —
    # so NO handle crosses the identity boundary at all and the handle-leak
    # question has a structural answer rather than an audited one.
    stdout_path: str = ""    # absolute; opened by the bootstrap, truncating
    stderr_path: str = ""    # absolute; opened by the bootstrap, truncating
    # THE SEALED ENVIRONMENT OVERLAY (F-17 Stage 5, D3 hardening). The launcher
    # no longer builds the Worker's environment: `CreateProcessWithLogonW` with
    # LOGON_WITH_PROFILE and `lpEnvironment = NULL` does it, from the Worker's
    # own profile, which is what removed the LoadUserProfileW /
    # SeBackup+SeRestore dependency. The few DETERMINISM variables Gnosis still
    # needs therefore travel here, sealed, and the bootstrap applies them on top
    # of the profile environment Windows gave it.
    #
    # NEVER A CREDENTIAL: the spec is Worker-readable, and a credential-shaped
    # NAME is refused by construction below.
    environment: tuple[tuple[str, str], ...] = ()
    run_id: str | None = None    # binding for Stage 6; never worker-supplied
    schema: str = LAUNCH_SPEC_SCHEMA

    def __post_init__(self) -> None:
        if self.schema not in SUPPORTED_LAUNCH_SPEC_SCHEMAS:
            raise LaunchSpecInvalid(f"unknown launch-spec schema {self.schema!r}")
        if not is_storable_launch_id(self.launch_id):
            raise LaunchSpecInvalid(
                f"launch_id {self.launch_id!r} is not a storable record name")
        if self.run_id is not None and not is_storable_launch_id(self.run_id):
            raise LaunchSpecInvalid(f"run_id {self.run_id!r} is not storable")
        for name in ("executable", "cwd", "stdout_path", "stderr_path"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise LaunchSpecInvalid(f"{name} must be a non-empty string")
            # An absolute path is the whole point: the bootstrap must never
            # perform a PATH search, and a relative path would be resolved
            # against whatever directory the child happened to start in.
            if not _is_absolute_windows_path(value):
                raise LaunchSpecInvalid(
                    f"{name} must be an absolute path; got {value!r}")
        if not isinstance(self.argv, tuple) or not self.argv:
            raise LaunchSpecInvalid("argv must be a non-empty tuple")
        for index, item in enumerate(self.argv):
            if not isinstance(item, str):
                raise LaunchSpecInvalid(f"argv[{index}] is not a string: {item!r}")
            if "\x00" in item:
                # A NUL terminates a Windows command line. An argument carrying
                # one would be silently truncated by the OS, which is exactly
                # the "no silent truncation" rule this stage is built around.
                raise LaunchSpecInvalid(f"argv[{index}] contains a NUL byte")
        self._validate_environment()

    def _validate_environment(self) -> None:
        if not isinstance(self.environment, tuple):
            raise LaunchSpecInvalid("environment must be a tuple of (name, value)")
        if len(self.environment) > MAX_ENVIRONMENT_ENTRIES:
            raise LaunchSpecInvalid(
                f"environment carries {len(self.environment)} entries, over the "
                f"{MAX_ENVIRONMENT_ENTRIES} bound; this overlay is for a handful "
                "of determinism variables, not for a whole environment")
        seen: set[str] = set()
        for entry in self.environment:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise LaunchSpecInvalid(f"environment entry {entry!r} is not a pair")
            name, value = entry
            if not isinstance(name, str) or not _SAFE_ENV_NAME.match(name):
                raise LaunchSpecInvalid(f"environment name {name!r} is not a safe name")
            if _CREDENTIAL_SHAPED.search(name):
                raise LaunchSpecInvalid(
                    f"environment name {name!r} looks like a credential; the "
                    "LaunchSpec is Worker-readable and may never carry one")
            if name in seen:
                raise LaunchSpecInvalid(f"environment name {name!r} appears twice")
            seen.add(name)
            if not isinstance(value, str) or "\x00" in value:
                raise LaunchSpecInvalid(f"environment value for {name!r} is invalid")
            if len(value) > MAX_ENVIRONMENT_VALUE:
                raise LaunchSpecInvalid(f"environment value for {name!r} is too long")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "launch_id": self.launch_id,
                "executable": self.executable, "argv": list(self.argv),
                "cwd": self.cwd, "stdout_path": self.stdout_path,
                "stderr_path": self.stderr_path,
                "environment": [list(pair) for pair in self.environment],
                "run_id": self.run_id}

    def digest(self) -> str:
        """`launch_spec_digest` — the seal. One canonical primitive (ADR-0004);
        there is no second hashing implementation anywhere in this path."""
        return hash_canonical(self.to_dict())

    @property
    def logical_command_digest(self) -> str:
        """Identity of the LOGICAL command alone, independent of transport.

        DERIVED, never stored. Storing it beside `argv` would put the same fact
        in two places with no way for them to disagree — a field that cannot
        fail a check is not a check (Stage 3's RM13). This is what provenance
        and replay bind to, because it is unchanged by which transport carried
        the command.
        """
        return hash_canonical(list(self.argv))

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, data: Any) -> LaunchSpec:
        if not isinstance(data, dict):
            raise LaunchSpecInvalid("a launch spec must be a JSON object")
        unknown = set(data) - _FIELDS
        if unknown:
            # Silently ignoring an unknown security-relevant field is how a
            # newer writer's instruction gets half-executed by an older reader.
            raise LaunchSpecInvalid(
                f"launch spec carries unknown fields {sorted(unknown)}")
        missing = _FIELDS - {"run_id"} - set(data)
        if missing:
            raise LaunchSpecInvalid(f"launch spec is missing {sorted(missing)}")
        argv = data["argv"]
        if not isinstance(argv, list):
            raise LaunchSpecInvalid("argv must be a JSON array")
        environment = data["environment"]
        if not isinstance(environment, list):
            raise LaunchSpecInvalid("environment must be a JSON array")
        pairs: list[tuple[str, str]] = []
        for entry in environment:
            if not isinstance(entry, list) or len(entry) != 2:
                raise LaunchSpecInvalid(f"environment entry {entry!r} is not a pair")
            pairs.append((entry[0], entry[1]))
        return cls(launch_id=data["launch_id"], executable=data["executable"],
                   argv=tuple(argv), cwd=data["cwd"],
                   stdout_path=data["stdout_path"], stderr_path=data["stderr_path"],
                   environment=tuple(pairs),
                   run_id=data.get("run_id"), schema=data["schema"])


def child_environment(spec: LaunchSpec,
                      own_environment: dict[str, str]) -> dict[str, str]:
    """The logical command's environment: the WORKER's own, plus the seal.

    `own_environment` is the environment the bootstrap itself was given, which
    under `LOGON_WITH_PROFILE` with `lpEnvironment = NULL` is the WORKER's
    profile environment, built by Windows — measured OS-real to contain no
    Director state. The sealed overlay adds only the determinism variables the
    Director named, and the Worker cannot alter them because the spec is sealed.
    """
    env = dict(own_environment)
    for name, value in spec.environment:
        env[name] = value
    return env


def _is_absolute_windows_path(value: str) -> bool:
    """A drive-qualified absolute path. Deliberately strict.

    A UNC path is refused: it resolves through the network redirector, so what
    it names is decided by something outside this machine's trust plane. A
    rooted-but-driveless path (`\\dir`) is refused too, because it is relative
    to the current drive and therefore not absolute at all.
    """
    if value.startswith("\\\\"):
        return False
    return len(value) >= 3 and value[1] == ":" and value[2] in "\\/"


def launch_spec_path(root: Path, launch_id: str) -> Path:
    if not is_storable_launch_id(launch_id):
        raise LaunchSpecInvalid(
            f"launch_id {launch_id!r} is not a storable record name; refusing to "
            "build a launch-root path from it")
    return root / f"{launch_id}.json"


def seal_launch_spec(root: Path, spec: LaunchSpec) -> str:
    """Write the spec into the trusted launch root and return its digest.

    Write, flush, atomically replace, RE-READ, and derive the digest from the
    bytes that are actually on disk — never from the object in memory. The
    digest the transport command carries must be the digest of what the
    bootstrap will read, or the seal proves nothing about the file.
    """
    path = launch_spec_path(root, spec.launch_id)
    payload = spec.canonical_bytes()
    if len(payload) > MAX_LAUNCH_SPEC_BYTES:
        raise LaunchSpecInvalid(
            f"launch spec is {len(payload)} bytes, over the "
            f"{MAX_LAUNCH_SPEC_BYTES}-byte bound")
    atomic_write_bytes(path, payload)
    written = read_launch_spec_bytes(path)
    if written != payload:
        raise LaunchSpecUnsealed("the launch spec did not read back as written")
    return LaunchSpec.from_dict(json.loads(written.decode("utf-8"))).digest()


def read_launch_spec_bytes(path: Path) -> bytes:
    """Read the payload under a hard size bound, failing closed.

    The bound is checked against what was actually read, not against a stat()
    taken beforehand: a file whose size changes between the two is precisely
    the case this must not be relaxed for.
    """
    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_LAUNCH_SPEC_BYTES + 1)
    except FileNotFoundError as exc:
        raise LaunchSpecUnsealed(f"no launch spec at {path}") from exc
    except OSError as exc:
        raise LaunchSpecUnsealed(f"the launch spec is unreadable: {exc}") from exc
    if len(payload) > MAX_LAUNCH_SPEC_BYTES:
        raise LaunchSpecInvalid(
            f"launch spec exceeds the {MAX_LAUNCH_SPEC_BYTES}-byte bound")
    return payload


def read_sealed_launch_spec(path: Path, *, expected_digest: str) -> LaunchSpec:
    """THE BOOTSTRAP'S ENTRY POINT. Read, verify the seal, and refuse otherwise.

    Order matters and is deliberate: the digest is checked against the parsed
    spec's own canonical form, so a payload that parses to something different
    from what it claims cannot pass by being byte-identical to nothing. Every
    failure is closed; there is no path that returns a partially-trusted spec.
    """
    if not isinstance(expected_digest, str) or not _DIGEST.match(expected_digest):
        raise LaunchSpecInvalid(
            f"expected_digest must be a 64-character lowercase hex digest; "
            f"got {expected_digest!r}")
    payload = read_launch_spec_bytes(path)
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LaunchSpecInvalid(f"launch spec is not readable JSON: {exc}") from exc
    spec = LaunchSpec.from_dict(data)
    actual = spec.digest()
    if actual != expected_digest:
        raise LaunchSpecUnsealed(
            f"launch spec at {path} digests to {actual}, not the expected "
            f"{expected_digest}; the payload is not the one that was sealed")
    if spec.canonical_bytes() != payload:
        # The digest matched, so the MEANING is right, but the bytes are not
        # canonical. Something re-serialised the file. That is not a launch
        # this process was told to perform, and it is refused rather than
        # normalised into one.
        raise LaunchSpecUnsealed(
            f"launch spec at {path} is not in canonical form; refusing a "
            "payload that was rewritten after it was sealed")
    return spec
