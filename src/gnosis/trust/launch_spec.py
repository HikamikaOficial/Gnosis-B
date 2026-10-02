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
import os
import re
from collections.abc import Mapping
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
                     "stdout_path", "stderr_path", "environment",
                     "environment_policy_version", "run_id"})

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

# ---------------------------------------------------------------------------
# THE LOGICAL CHILD'S ENVIRONMENT POLICY.
#
# Versioned because a change to WHICH NAMES may cross the boundary must not be
# invisible to provenance. The version travels inside the LaunchSpec and is
# therefore inside `launch_spec_digest`.
# ---------------------------------------------------------------------------
ENVIRONMENT_POLICY_VERSION = "gnosis.trust.worker_env.v1"

# Taken from the Worker's environment ONLY IF the value lies inside the profile
# root the OS reported. A previous run can persist any of these into
# HKCU\Environment pointing anywhere it can write.
PROFILE_SCOPED_NAMES: frozenset[str] = frozenset({
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP",
})

# Inherited as-is. Every name here is NON-PATH, so redirection is not a risk;
# path-valued machine variables (ProgramFiles, ProgramData, ...) are
# deliberately ABSENT because HKCU\Environment can override them for this user
# and the measured toolchain does not need them.
PLAIN_INHERITED_NAMES: frozenset[str] = frozenset({
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "USERNAME", "USERDOMAIN",
})

DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD"

# The ONLY names the sealed overlay may set. Closed, so the overlay can never
# reintroduce a dangerous variable the base policy dropped: adding one here is
# a deliberate, reviewable act rather than a value a caller can pass.
OVERLAY_ALLOWED_NAMES: frozenset[str] = frozenset({
    "PYTHONUTF8", "PYTHONIOENCODING", "PATH",
})


def credential_shaped(names: frozenset[str]) -> list[str]:
    """The names in `names` that look like a credential.

    THE CLOSED SET IS THE SECURITY MODEL; this is defence in depth, and it
    guards the POLICY rather than each value. A per-value check would be
    unreachable — the closed set rejects every unlisted name before any value
    is examined — and an unreachable check is the RM13 defect the project has
    already paid for once. Guarding the SET instead makes it live: it fails the
    moment someone widens `OVERLAY_ALLOWED_NAMES` to admit a credential.
    """
    return sorted(name for name in names if _CREDENTIAL_SHAPED.search(name))


# Enforced AT IMPORT. The LaunchSpec is Worker-readable, so a credential-shaped
# name in the overlay policy would hand the Worker a credential; a module that
# would do that must not load at all.
if credential_shaped(OVERLAY_ALLOWED_NAMES):
    raise AuthorityUnavailable(
        "OVERLAY_ALLOWED_NAMES contains credential-shaped names "
        f"{credential_shaped(OVERLAY_ALLOWED_NAMES)}; the LaunchSpec is "
        "Worker-readable and may never carry a credential")


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
    # WHICH NAMES may cross the boundary is part of the launch INTENT, so a
    # change to the policy must not be invisible to provenance. It rides in
    # the spec and is therefore inside launch_spec_digest.
    environment_policy_version: str = ENVIRONMENT_POLICY_VERSION
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
            if not isinstance(value, str) or "\0" in value:
                raise LaunchSpecInvalid(f"environment value for {name!r} is invalid")
            if name not in OVERLAY_ALLOWED_NAMES:
                # THE CLOSED SET IS THE SECURITY MODEL. Unknown name == denied.
                # It is what stops the overlay reintroducing a variable the base
                # policy dropped — NODE_OPTIONS, PYTHONPATH, GIT_CONFIG_GLOBAL
                # and every name nobody thought of.
                raise LaunchSpecInvalid(
                    f"environment name {name!r} is not in the sealed overlay's "
                    f"allowed set {sorted(OVERLAY_ALLOWED_NAMES)}; the overlay may "
                    "not reintroduce a variable the base policy drops")
            if name == "PATH":
                # A sealed PATH is the ONLY way a directory reaches the logical
                # command's search path, so every entry must be somewhere a
                # reader can locate: absolute and drive-qualified, never
                # relative, never UNC.
                for element in (v for v in value.split(";") if v):
                    if not _is_absolute_windows_path(element):
                        raise LaunchSpecInvalid(
                            f"sealed PATH entry {element!r} is not an absolute "
                            "drive-qualified path")
            if name in seen:
                raise LaunchSpecInvalid(f"environment name {name!r} appears twice")
            seen.add(name)
            if len(value) > MAX_ENVIRONMENT_VALUE:
                raise LaunchSpecInvalid(f"environment value for {name!r} is too long")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "launch_id": self.launch_id,
                "executable": self.executable, "argv": list(self.argv),
                "cwd": self.cwd, "stdout_path": self.stdout_path,
                "stderr_path": self.stderr_path,
                "environment": [list(pair) for pair in self.environment],
                "environment_policy_version": self.environment_policy_version,
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
                   environment_policy_version=data["environment_policy_version"],
                   run_id=data.get("run_id"), schema=data["schema"])


def _canonical(path: str) -> str:
    """A comparable form. Deliberately does NOT resolve links: the caller wants
    to know where a value points as written, and a resolve would follow a
    junction the Worker planted straight past the check."""
    return os.path.normcase(os.path.normpath(path)).rstrip("\\")


def _inside(root: str, value: str) -> bool:
    """True if `value` is `root` or lies beneath it.

    Compared component-wise, not by string prefix: `C:\\Users\\Bob2` starts with
    `C:\\Users\\Bob` as a string and is a different profile.
    """
    if not _is_absolute_windows_path(value):
        return False
    root_parts = _canonical(root).split("\\")
    value_parts = _canonical(value).split("\\")
    return value_parts[: len(root_parts)] == root_parts


def deterministic_path(system_root: str, trusted_entries: str = "") -> str:
    """PATH is BUILT, never inherited.

    The Worker's profile PATH is attacker-controlled across runs: a previous
    run can persist entries into `HKCU\\Environment` that point at anything it
    can write. So PATH is constructed from the OS's own Windows directory, and
    the only additions are the trusted tool directories the Director SEALED —
    which the Worker cannot edit. No worktree, no profile bin directory, no
    TEMP, no current directory.
    """
    root = system_root.rstrip("\\")
    system = [f"{root}\\system32", root, f"{root}\\System32\\Wbem",
              f"{root}\\System32\\WindowsPowerShell\\v1.0"]
    extra = [entry for entry in trusted_entries.split(";") if entry]
    return ";".join([*extra, *system])


def child_environment(spec: LaunchSpec, own_environment: Mapping[str, str], *,
                      profile_root: str, system_root: str) -> dict[str, str]:
    """The logical command's environment, built by a CLOSED ALLOWLIST.

    WHY THIS IS NOT A COPY. The bootstrap's own environment no longer comes
    from the Director — that was finding E1, repaired — but it now comes from
    the WORKER'S PROFILE, and under the T2 threat model the Worker is
    compromised. A previous run can persist variables into `HKCU\\Environment`
    that Windows will faithfully rebuild for the next run: `NODE_OPTIONS`
    loading a script, `PYTHONPATH` shadowing a module, `GIT_CONFIG_GLOBAL`
    redirecting configuration, a proxy or TLS override redirecting traffic.
    Forwarding `os.environ` would carry all of it into the logical command and
    quietly defeat the sealed launch.

    So the rule is UNKNOWN VARIABLE == DENIED, not "denied if the name looks
    dangerous". A deny-list can only ever exclude what somebody thought of; the
    credential-shaped-name filter that also exists is defence in depth on top of
    this, never a substitute for it.

    Three sources, and nothing else:

      OS FACTS       SystemRoot / SystemDrive / windir / COMSPEC / PATH /
                     PATHEXT come from `system_root`, which the bootstrap asked
                     the OS for. They are not read from the environment at all,
                     so the Worker cannot redirect them.
      PROFILE VALUES USERPROFILE / APPDATA / LOCALAPPDATA / TEMP / TMP are taken
                     from the Worker's own environment AND REQUIRED TO LIE
                     INSIDE the profile root the OS reported. A value pointing
                     anywhere else is dropped, not corrected.
      SEALED OVERLAY the determinism variables the Director named, applied last.
                     Their names are constrained to a closed set at seal time,
                     so the overlay can never reintroduce a dangerous variable
                     the base policy dropped.
    """
    env: dict[str, str] = {}
    root = system_root.rstrip("\\")
    env["SystemRoot"] = root
    env["windir"] = root
    env["SystemDrive"] = root[:2]
    env["COMSPEC"] = f"{root}\\system32\\cmd.exe"
    env["PATHEXT"] = DEFAULT_PATHEXT

    for name in sorted(PROFILE_SCOPED_NAMES):
        value = own_environment.get(name)
        if value and _inside(profile_root, value):
            env[name] = value

    for name in sorted(PLAIN_INHERITED_NAMES):
        value = own_environment.get(name)
        if value:
            env[name] = value

    overlay = dict(spec.environment)
    env["PATH"] = deterministic_path(root, overlay.pop("PATH", ""))
    env.update(overlay)
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
