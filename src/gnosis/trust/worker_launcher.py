"""The trusted dedicated-worker launcher (F-17 Stage 5).

THE PROPERTY THIS EXISTS FOR:

    actual child process TokenUser SID == expected Worker SID

and a hard failure whenever that cannot be established. There is NO same-user
fallback anywhere in this module: if the trusted launch cannot be performed, the
run fails. `subprocess.Popen` as the Director is not a degraded mode, it is the
absence of the boundary, and returning it would report success for a launch that
never crossed an identity.

THE TRANSPORT PROBLEM, AND THE SHAPE OF THE ANSWER. `CreateProcessWithLogonW` is
the only primitive that creates this boundary without the trust plane acquiring a
privilege it was never granted, and its `lpCommandLine` is capped at 1024
characters while Gnosis's real logical command is ~12128. So the command line
carries only a bootstrap path, a launch-spec path and a digest; the logical argv
travels in the SEALED LaunchSpec and is re-created, element for element, by the
bootstrap already running under the Worker SID (see `trust.launch_spec` and
`trust.bootstrap`).

    transport command   short, bounded, checked against a hard ceiling
    logical command     exact, unbounded by the transport, digest-sealed

CREATION ORDER IS THE SECURITY PROPERTY. The child is created SUSPENDED, and no
Worker instruction executes until its identity has been proved and its
containment established:

    1  CreateProcessWithLogonW(..., CREATE_SUSPENDED)
    2  OpenProcessToken on the child
    3  TokenUser SID must equal the expected Worker SID
    4  integrity must be the expected level
    5  the token must not be an administrator
    6  no dangerous privilege may be present
    7  create and configure the Job Object (KILL_ON_JOB_CLOSE, no breakaway)
    8  AssignProcessToJobObject
    9  IsProcessInJob must be TRUE
    10 ONLY THEN ResumeThread

Any failure terminates the process, closes every handle and raises. Unverified
Worker code never begins execution.

WHAT THIS MODULE DOES NOT CLAIM. The Job Object contains descendants; it is not a
security boundary against a Worker that has other means. The DPAPI blob is
machine-bound (`CRYPTPROTECT_LOCAL_MACHINE`), which is NOT "only the trusted
launcher can decrypt" — the authorization boundary is the NTFS ACL that denies
the Worker READ on the blob, and DPAPI only ensures the bytes are useless off
this machine. The password exists transiently in this process's memory for the
duration of one logon call and is zeroized best-effort afterwards; perfect
physical erasure is not promised.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from ctypes import wintypes as W
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from gnosis.trust.launch import AuthorityUnavailable, token_integrity
from gnosis.trust.launch_spec import LaunchSpec, seal_launch_spec

_IS_WINDOWS = sys.platform == "win32"

# The documented ceiling for CreateProcessWithLogonW's lpCommandLine. The
# transport command is checked against a SELF-IMPOSED budget well below it: a
# design that fits in 1023 characters is a design that fails the first time a
# path gets longer.
LOGON_COMMAND_LINE_LIMIT = 1024
TRANSPORT_COMMAND_BUDGET = 512

# Present in the Worker's token, any of these would defeat the point of running
# the Worker as a separate, unprivileged identity.
DANGEROUS_PRIVILEGES: frozenset[str] = frozenset({
    "SeDebugPrivilege", "SeImpersonatePrivilege", "SeTakeOwnershipPrivilege",
    "SeBackupPrivilege", "SeRestorePrivilege", "SeTcbPrivilege",
    "SeAssignPrimaryTokenPrivilege", "SeCreateTokenPrivilege",
})

BUILTIN_ADMINISTRATORS_SID = "S-1-5-32-544"

# The ONLY Director-side variables that may reach the Worker. Everything else in
# the Worker's environment comes from the Worker's OWN profile, built by
# CreateEnvironmentBlock against the Worker's token. There is deliberately no
# pattern match and no "copy everything except": an allowlist that is a deny-list
# in disguise leaks whatever nobody thought to name (finding E1).
DEFAULT_ENVIRONMENT_ALLOWLIST: frozenset[str] = frozenset({
    "PYTHONUTF8",           # the project's own encoding contract (L-0001)
    "PYTHONIOENCODING",
})


class WorkerLaunchFailed(AuthorityUnavailable):
    """The trusted launch could not be performed. There is no fallback."""


class WorkerIdentityMismatch(WorkerLaunchFailed):
    """The child exists but is not who it was required to be.

    Distinct from a launch that could not happen at all: this one produced a
    live process under an identity nobody authorized, and the response is not
    to retry but to terminate it and refuse.
    """


@dataclass(frozen=True)
class LaunchedWorkerIdentity:
    """What the OS actually said about the process that was created.

    Every field here is OBSERVED — read back off the child's own token — and
    none is copied from configuration, a username, an environment variable or
    anything the Worker said. Stage 6 populates `RunIdentity.owner_worker_sid`
    from `observed_sid` and from nothing else.

    NOTE ON `is_administrator` AND `dangerous_privileges`: on the success path
    they are ALWAYS False and empty, because `verify_worker_token` raises
    otherwise and this record is only built after it returns. They are kept as a
    RECORD of what was checked, not as variables a reader should test — stated
    here so nobody mistakes a constant for a signal.
    """

    pid: int
    observed_sid: str
    integrity: str
    is_administrator: bool
    dangerous_privileges: tuple[str, ...]
    launch_spec_digest: str
    logical_command_digest: str
    transport_command_length: int
    contained_in_job: bool
    launcher_kind: str = "trusted-windows-createprocesswithlogonw+bootstrap"
    launcher_version: str = "gnosis.trust.worker_launcher.v1"


@dataclass
class WorkerLaunchResult:
    """A live, verified, contained Worker. Wait on it, then close it."""

    identity: LaunchedWorkerIdentity
    _handles: _ProcessHandles = field(repr=False)

    def wait(self, timeout_s: float, *, poll_interval_s: float = 0.2,
             is_cancelled: object = None) -> tuple[int, bool, bool]:
        """Wait for the tree. Returns (exit_code, timed_out, cancelled).

        Termination goes through the JOB, never through the root PID: killing
        only the root is what let descendants outlive a run (finding D1).
        """
        return self._handles.wait(timeout_s, poll_interval_s, is_cancelled)

    def close(self) -> None:
        self._handles.close()


class WorkerLauncher(Protocol):
    """The boundary the runner depends on.

    A Protocol, so tests can inject an explicit fake and production can inject
    the real thing — and so there is exactly ONE place where the choice is
    made. What must never exist is a runner that catches a launch failure and
    falls back to launching as itself.
    """

    def launch(self, spec: LaunchSpec) -> WorkerLaunchResult:
        ...


# ---------------------------------------------------------------------------
# Windows primitives
# ---------------------------------------------------------------------------
if _IS_WINDOWS:
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _a32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    _userenv = ctypes.WinDLL("userenv", use_last_error=True)

    LOGON_WITH_PROFILE = 0x00000001
    CREATE_SUSPENDED = 0x00000004
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    CREATE_NO_WINDOW = 0x08000000
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000

    LOGON32_LOGON_INTERACTIVE = 2
    LOGON32_PROVIDER_DEFAULT = 0

    TOKEN_QUERY = 0x0008
    TokenUser = 1
    TokenGroups = 2
    TokenPrivileges = 3

    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    CRYPTPROTECT_LOCAL_MACHINE = 0x4
    INFINITE = 0xFFFFFFFF
    WAIT_TIMEOUT = 0x00000102
    STILL_ACTIVE = 259

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", W.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    class _SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", W.DWORD)]

    class _LUID(ctypes.Structure):
        _fields_ = [("LowPart", W.DWORD), ("HighPart", ctypes.c_long)]

    class _LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", _LUID), ("Attributes", W.DWORD)]

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", W.DWORD), ("lpReserved", W.LPWSTR), ("lpDesktop", W.LPWSTR),
            ("lpTitle", W.LPWSTR), ("dwX", W.DWORD), ("dwY", W.DWORD),
            ("dwXSize", W.DWORD), ("dwYSize", W.DWORD), ("dwXCountChars", W.DWORD),
            ("dwYCountChars", W.DWORD), ("dwFillAttribute", W.DWORD),
            ("dwFlags", W.DWORD), ("wShowWindow", W.WORD), ("cbReserved2", W.WORD),
            ("lpReserved2", ctypes.c_void_p), ("hStdInput", W.HANDLE),
            ("hStdOutput", W.HANDLE), ("hStdError", W.HANDLE)]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", W.HANDLE), ("hThread", W.HANDLE),
                    ("dwProcessId", W.DWORD), ("dwThreadId", W.DWORD)]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", W.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", W.DWORD), ("Affinity", ctypes.POINTER(W.ULONG)),
                    ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD)]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", _IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    _a32.CreateProcessWithLogonW.argtypes = [
        W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, W.DWORD, W.LPCWSTR, W.LPWSTR, W.DWORD,
        ctypes.c_void_p, W.LPCWSTR, ctypes.POINTER(_STARTUPINFOW),
        ctypes.POINTER(_PROCESS_INFORMATION)]
    _a32.CreateProcessWithLogonW.restype = W.BOOL
    _a32.LogonUserW.argtypes = [W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, W.DWORD, W.DWORD,
                                ctypes.POINTER(W.HANDLE)]
    _a32.LogonUserW.restype = W.BOOL
    _a32.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, ctypes.POINTER(W.HANDLE)]
    _a32.OpenProcessToken.restype = W.BOOL
    _a32.GetTokenInformation.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                         W.DWORD, ctypes.POINTER(W.DWORD)]
    _a32.GetTokenInformation.restype = W.BOOL
    _a32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(W.LPWSTR)]
    _a32.ConvertSidToStringSidW.restype = W.BOOL
    _a32.LookupPrivilegeNameW.argtypes = [W.LPCWSTR, ctypes.c_void_p, W.LPWSTR,
                                          ctypes.POINTER(W.DWORD)]
    _a32.LookupPrivilegeNameW.restype = W.BOOL
    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, W.LPCWSTR]
    _k32.CreateJobObjectW.restype = W.HANDLE
    _k32.SetInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                             W.DWORD]
    _k32.SetInformationJobObject.restype = W.BOOL
    _k32.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
    _k32.AssignProcessToJobObject.restype = W.BOOL
    _k32.IsProcessInJob.argtypes = [W.HANDLE, W.HANDLE, ctypes.POINTER(W.BOOL)]
    _k32.IsProcessInJob.restype = W.BOOL
    _k32.TerminateJobObject.argtypes = [W.HANDLE, W.UINT]
    _k32.TerminateJobObject.restype = W.BOOL
    _k32.ResumeThread.argtypes = [W.HANDLE]
    _k32.ResumeThread.restype = W.DWORD
    _k32.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
    _k32.TerminateProcess.restype = W.BOOL
    _k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    _k32.WaitForSingleObject.restype = W.DWORD
    _k32.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
    _k32.GetExitCodeProcess.restype = W.BOOL
    _k32.CloseHandle.argtypes = [W.HANDLE]
    _k32.CloseHandle.restype = W.BOOL
    _k32.LocalFree.argtypes = [ctypes.c_void_p]
    _crypt.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), W.LPCWSTR, ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, W.DWORD, ctypes.POINTER(_DATA_BLOB)]
    _crypt.CryptProtectData.restype = W.BOOL
    _crypt.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, W.DWORD, ctypes.POINTER(_DATA_BLOB)]
    _crypt.CryptUnprotectData.restype = W.BOOL
    _userenv.CreateEnvironmentBlock.argtypes = [ctypes.POINTER(ctypes.c_void_p),
                                                W.HANDLE, W.BOOL]
    _userenv.CreateEnvironmentBlock.restype = W.BOOL
    _userenv.DestroyEnvironmentBlock.argtypes = [ctypes.c_void_p]
    _userenv.DestroyEnvironmentBlock.restype = W.BOOL

    PI_NOUI = 0x00000001

    class _PROFILEINFOW(ctypes.Structure):
        _fields_ = [("dwSize", W.DWORD), ("dwFlags", W.DWORD),
                    ("lpUserName", W.LPWSTR), ("lpProfilePath", W.LPWSTR),
                    ("lpDefaultPath", W.LPWSTR), ("lpServerName", W.LPWSTR),
                    ("lpPolicyPath", W.LPWSTR), ("hProfile", W.HANDLE)]

    _userenv.LoadUserProfileW.argtypes = [W.HANDLE, ctypes.POINTER(_PROFILEINFOW)]
    _userenv.LoadUserProfileW.restype = W.BOOL
    _userenv.UnloadUserProfile.argtypes = [W.HANDLE, W.HANDLE]
    _userenv.UnloadUserProfile.restype = W.BOOL


def _secret_text(buffer: ctypes.Array[ctypes.c_char]) -> str:
    """Decode a UTF-16-LE secret buffer WITHOUT splitting a code unit.

    `rstrip(b"\x00")` is the obvious and wrong way to do this: every ASCII
    character encodes as <byte> + 0x00, so stripping trailing NUL BYTES eats the
    high half of the last character and leaves an odd-length buffer that will
    not decode. Trailing NULs are removed in PAIRS, and an odd length is
    truncated first, so the result is always a whole number of code units.
    """
    raw = buffer.raw
    if len(raw) % 2:
        raw = raw[:-1]
    while raw.endswith(b"\x00\x00"):
        raw = raw[:-2]
    return raw.decode("utf-16-le")


def _winfail(call: str) -> None:
    raise WorkerLaunchFailed(f"{call} failed (winerr {ctypes.get_last_error()})")


def _require_windows() -> None:
    if not _IS_WINDOWS:
        raise WorkerLaunchFailed(
            "the trusted worker launcher is a Windows mechanism; there is no "
            "cross-platform fallback because there is no boundary to fall back to")


# ---------------------------------------------------------------------------
# DPAPI credential at rest
# ---------------------------------------------------------------------------
def protect_worker_secret(secret: str, *, description: str = "gnosis-worker") -> bytes:
    """DPAPI-protect a secret, MACHINE-BOUND.

    `CRYPTPROTECT_LOCAL_MACHINE` means the blob is useless on any other machine.
    It does NOT mean only the trusted launcher can decrypt it: any process on
    THIS machine that can READ the bytes can unprotect them. The authorization
    boundary is therefore the NTFS ACL that denies the Worker read access, and
    this function's guarantee is deliberately stated no more strongly than that.
    """
    _require_windows()
    raw = secret.encode("utf-16-le")
    buffer = ctypes.create_string_buffer(raw, len(raw))
    blob_in = _DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DATA_BLOB()
    try:
        if not _crypt.CryptProtectData(ctypes.byref(blob_in), description, None,
                                       None, None, CRYPTPROTECT_LOCAL_MACHINE,
                                       ctypes.byref(blob_out)):
            _winfail("CryptProtectData")
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.memset(buffer, 0, len(raw))
        if blob_out.pbData:
            _k32.LocalFree(blob_out.pbData)


def _unprotect_worker_secret(blob: bytes) -> ctypes.Array[ctypes.c_char]:
    """Return the plaintext in a MUTABLE buffer the caller must zeroize.

    A `str` would be immutable and interned by the runtime, so it could not be
    erased at all. The buffer is the smallest thing that can be.
    """
    _require_windows()
    buffer = ctypes.create_string_buffer(blob, len(blob))
    blob_in = _DATA_BLOB(len(blob), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DATA_BLOB()
    if not _crypt.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None,
                                     0, ctypes.byref(blob_out)):
        raise WorkerLaunchFailed(
            "the worker credential could not be unprotected (winerr "
            f"{ctypes.get_last_error()}); it is missing, corrupt, truncated, or "
            "was protected on another machine")
    try:
        plaintext = ctypes.create_string_buffer(
            ctypes.string_at(blob_out.pbData, blob_out.cbData), blob_out.cbData)
    finally:
        if blob_out.pbData:
            ctypes.memset(blob_out.pbData, 0, blob_out.cbData)
            _k32.LocalFree(blob_out.pbData)
    return plaintext


# ---------------------------------------------------------------------------
# Token inspection
# ---------------------------------------------------------------------------
def _token_info(token: W.HANDLE, info_class: int) -> ctypes.Array[ctypes.c_char]:
    size = W.DWORD(0)
    _a32.GetTokenInformation(token, info_class, None, 0, ctypes.byref(size))
    buf = ctypes.create_string_buffer(max(size.value, 1))
    if not _a32.GetTokenInformation(token, info_class, buf, size, ctypes.byref(size)):
        _winfail(f"GetTokenInformation({info_class})")
    return buf


def _sid_to_string(sid: int) -> str:
    out = W.LPWSTR()
    if not _a32.ConvertSidToStringSidW(sid, ctypes.byref(out)):
        _winfail("ConvertSidToStringSidW")
    try:
        return out.value or ""
    finally:
        _k32.LocalFree(out)


def _token_user_sid(token: W.HANDLE) -> str:
    buf = _token_info(token, TokenUser)
    entry = ctypes.cast(buf, ctypes.POINTER(_SID_AND_ATTRIBUTES)).contents
    return _sid_to_string(entry.Sid)


def _token_group_sids(token: W.HANDLE) -> tuple[str, ...]:
    buf = _token_info(token, TokenGroups)
    count = ctypes.cast(buf, ctypes.POINTER(W.DWORD)).contents.value
    array = ctypes.cast(ctypes.addressof(buf) + ctypes.sizeof(ctypes.c_void_p),
                        ctypes.POINTER(_SID_AND_ATTRIBUTES * count)).contents
    return tuple(_sid_to_string(item.Sid) for item in array if item.Sid)


def _token_privileges(token: W.HANDLE) -> tuple[str, ...]:
    buf = _token_info(token, TokenPrivileges)
    count = ctypes.cast(buf, ctypes.POINTER(W.DWORD)).contents.value
    array = ctypes.cast(ctypes.addressof(buf) + ctypes.sizeof(W.DWORD),
                        ctypes.POINTER(_LUID_AND_ATTRIBUTES * count)).contents
    names: list[str] = []
    for entry in array:
        need = W.DWORD(0)
        _a32.LookupPrivilegeNameW(None, ctypes.byref(entry.Luid), None,
                                  ctypes.byref(need))
        name = ctypes.create_unicode_buffer(need.value + 1)
        need = W.DWORD(need.value + 1)
        if _a32.LookupPrivilegeNameW(None, ctypes.byref(entry.Luid), name,
                                     ctypes.byref(need)):
            names.append(name.value)
    return tuple(sorted(names))


# ---------------------------------------------------------------------------
# The environment block
# ---------------------------------------------------------------------------
def _environment_block_for_token(token: W.HANDLE) -> dict[str, str]:
    """The Worker's OWN profile environment, from the OS.

    `CreateEnvironmentBlock` is the documented way to obtain the environment a
    user's profile defines. Building it from the Worker's token is what makes
    USERPROFILE, APPDATA and the rest point at the WORKER, and is why the
    Director's environment is never a starting point (finding E1).
    """
    block = ctypes.c_void_p()
    if not _userenv.CreateEnvironmentBlock(ctypes.byref(block), token, False):
        _winfail("CreateEnvironmentBlock")
    try:
        out: dict[str, str] = {}
        address = block.value or 0
        while True:
            entry = ctypes.wstring_at(address)
            if not entry:
                break
            address += (len(entry) + 1) * ctypes.sizeof(ctypes.c_wchar)
            if "=" in entry[1:]:
                name, _, value = entry[1:].partition("=")
                out[entry[0] + name] = value
        return out
    finally:
        _userenv.DestroyEnvironmentBlock(block)


def build_worker_environment(
        worker_env: Mapping[str, str], director_env: Mapping[str, str],
        allowlist: frozenset[str] = DEFAULT_ENVIRONMENT_ALLOWLIST,
        extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The Worker's environment: its OWN profile, plus a named allowlist.

    The Director's environment is NEVER the base. Only the variables named in
    `allowlist` are carried across, and only if the Director actually has them.
    An allowlist expressed as "everything except..." would leak whatever nobody
    thought to name; this one can only ever pass what it lists.
    """
    env = dict(worker_env)
    for name in sorted(allowlist):
        value = director_env.get(name)
        if value:
            env[name] = value
    for name, value in sorted((extra or {}).items()):
        env[name] = value
    return env


def _encode_environment_block(env: Mapping[str, str]) -> ctypes.Array[ctypes.c_wchar]:
    # Windows requires the block sorted case-insensitively, NUL-separated and
    # double-NUL terminated.
    parts = [f"{name}={value}" for name, value in
             sorted(env.items(), key=lambda item: item[0].upper())]
    raw = "\0".join(parts) + "\0\0"
    return ctypes.create_unicode_buffer(raw, len(raw))


# ---------------------------------------------------------------------------
# Handles
# ---------------------------------------------------------------------------
@dataclass
class _ProcessHandles:
    process: int
    thread: int
    job: int

    def wait(self, timeout_s: float, poll_interval_s: float,
             is_cancelled: object) -> tuple[int, bool, bool]:
        deadline = time.monotonic() + timeout_s
        cancelled = False
        timed_out = False
        while True:
            status = _k32.WaitForSingleObject(self.process,
                                              int(poll_interval_s * 1000))
            if status != WAIT_TIMEOUT:
                break
            if callable(is_cancelled) and is_cancelled():
                cancelled = True
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
        if cancelled or timed_out:
            # THROUGH THE JOB, never the root PID. Terminating only the root is
            # what let descendants outlive a run (finding D1); the job kills the
            # whole tree, including processes the Worker spawned.
            _k32.TerminateJobObject(self.job, 1)
            _k32.WaitForSingleObject(self.process, 5000)
        code = W.DWORD(0)
        if not _k32.GetExitCodeProcess(self.process, ctypes.byref(code)):
            _winfail("GetExitCodeProcess")
        exit_code = int(code.value)
        if exit_code == STILL_ACTIVE:
            exit_code = 1
        return exit_code, timed_out, cancelled

    def close(self) -> None:
        # Closing the JOB handle is what enforces KILL_ON_JOB_CLOSE: when the
        # last handle goes, every process still inside the job dies. It is
        # closed LAST so the tree is never orphaned by an early release.
        for handle in (self.thread, self.process, self.job):
            if handle:
                _k32.CloseHandle(handle)
        self.process = self.thread = self.job = 0


def _create_job() -> int:
    job = _k32.CreateJobObjectW(None, None)
    if not job:
        _winfail("CreateJobObject")
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    # KILL_ON_JOB_CLOSE and NOTHING ELSE. BREAKAWAY_OK and
    # SILENT_BREAKAWAY_OK are deliberately NOT set: either would let a child
    # ask to leave the job, which is the containment this exists to provide.
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _k32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                        ctypes.byref(info), ctypes.sizeof(info)):
        _k32.CloseHandle(job)
        _winfail("SetInformationJobObject")
    return int(job)


# ---------------------------------------------------------------------------
# The launcher
# ---------------------------------------------------------------------------
def bootstrap_script_path() -> Path:
    """The bootstrap's absolute path, derived from THIS module's location.

    Never from an environment variable or a caller-supplied string: the whole
    point is that the Worker executes code from the trusted, Worker-read-only
    tool root and nothing else.
    """
    return (Path(__file__).resolve().parent / "bootstrap.py")


def build_transport_command(runtime: Path, spec_path: Path, digest: str) -> str:
    """The SHORT command line that crosses the identity boundary.

    `-I` isolates the interpreter: PYTHONPATH, the user site directory and every
    other Python environment variable are ignored, so a Worker cannot inject a
    module into the bootstrap by setting a variable. `-E` and `-s` are implied.
    """
    return subprocess.list2cmdline(
        [str(runtime), "-I", str(bootstrap_script_path()), str(spec_path), digest])


@dataclass(frozen=True)
class ObservedToken:
    """What the OS said about the child's token. Facts only, no judgement."""

    sid: str
    integrity: str
    group_sids: tuple[str, ...]
    privileges: tuple[str, ...]


def verify_worker_token(observed: ObservedToken, account: WorkerAccount) -> tuple[str, ...]:
    """Raise unless this token is EXACTLY the authorized Worker.

    Extracted from the Win32 flow deliberately. The decision is the security
    property, and a decision buried inside a ctypes sequence can only be tested
    by creating a real account — so a mutation that deletes one of these checks
    would have survived every fast test and been caught only by an OS-real
    probe run. Here each refusal is a unit test.

    Returns the dangerous privileges found, which is always empty on success.
    """
    if observed.sid != account.expected_sid:
        raise WorkerIdentityMismatch(
            f"the child runs as {observed.sid}, not the expected worker "
            f"{account.expected_sid}; refusing and terminating it")
    if observed.integrity != account.expected_integrity:
        raise WorkerIdentityMismatch(
            f"the child is {observed.integrity} integrity, expected "
            f"{account.expected_integrity}")
    if BUILTIN_ADMINISTRATORS_SID in observed.group_sids:
        raise WorkerIdentityMismatch(
            "the child's token is a member of BUILTIN\\Administrators")
    dangerous = tuple(sorted(set(observed.privileges) & DANGEROUS_PRIVILEGES))
    if dangerous:
        # A non-admin account is NOT enough: privileges are granted
        # independently of group membership and are what actually decide what a
        # token may do.
        raise WorkerIdentityMismatch(
            f"the child's token holds dangerous privileges {list(dangerous)}")
    return dangerous


@dataclass(frozen=True)
class WorkerAccount:
    """WHO to launch as. The SID is the authoritative identity; the username is
    only what `CreateProcessWithLogonW` needs to perform the logon, and is never
    trusted as the answer to "who is this?" — that comes from the child's token."""

    username: str
    domain: str
    expected_sid: str
    expected_integrity: str = "Medium"


class TrustedWindowsWorkerLauncher:
    """Production `WorkerLauncher`. Fails closed; never falls back."""

    def __init__(self, account: WorkerAccount, credential_blob_path: Path,
                 launch_root: Path, runtime: Path | None = None,
                 environment_allowlist: frozenset[str] = DEFAULT_ENVIRONMENT_ALLOWLIST,
                 director_env: Mapping[str, str] | None = None) -> None:
        self.account = account
        self.credential_blob_path = credential_blob_path
        self.launch_root = launch_root
        self.runtime = runtime or Path(sys.executable)
        self.environment_allowlist = environment_allowlist
        # Captured explicitly rather than read from os.environ at launch time,
        # so what may cross is a decision the caller makes and a test can pin.
        self._director_env: Mapping[str, str] = director_env or {}

    def launch(self, spec: LaunchSpec) -> WorkerLaunchResult:
        _require_windows()
        digest = seal_launch_spec(self.launch_root, spec)
        spec_path = self.launch_root / f"{spec.launch_id}.json"
        command = build_transport_command(self.runtime, spec_path, digest)
        if len(command) > TRANSPORT_COMMAND_BUDGET:
            raise WorkerLaunchFailed(
                f"the transport command is {len(command)} characters, over this "
                f"launcher's {TRANSPORT_COMMAND_BUDGET}-character budget (the OS "
                f"limit is {LOGON_COMMAND_LINE_LIMIT}). Refusing rather than "
                "designing to the edge of a hard cap.")

        blob = self.credential_blob_path.read_bytes()
        password = _unprotect_worker_secret(blob)
        try:
            worker_env = self._worker_profile_environment(password)
            env = build_worker_environment(
                worker_env, self._director_env, self.environment_allowlist)
            handles, pid = self._create_suspended(command, password, env, spec)
        finally:
            # BEST-EFFORT ZEROIZATION, and named as such: the buffer this
            # process owns is erased immediately after the last use. What the
            # OS did with copies of it inside LogonUser/seclogon is outside
            # this process's reach and is not claimed to be erased.
            ctypes.memset(password, 0, len(password))
            del password

        try:
            identity = self._verify_and_contain(handles, pid, spec, digest, command)
        except BaseException:
            _k32.TerminateProcess(handles.process, 1)
            handles.close()
            raise
        return WorkerLaunchResult(identity=identity, _handles=handles)

    def _worker_profile_environment(
            self, password: ctypes.Array[ctypes.c_char]) -> dict[str, str]:
        """Log the Worker on ONLY to read its profile environment.

        The token is used for `CreateEnvironmentBlock` and closed immediately.
        It is NEVER used to create a process: doing that would be
        `CreateProcessWithTokenW`, which needs `SeImpersonatePrivilege` — a
        privilege this stage was explicitly not granted, and which is not
        acquired here to work around another API's limit.
        """
        token = W.HANDLE()
        secret = _secret_text(password)
        try:
            ok = _a32.LogonUserW(self.account.username, self.account.domain or None,
                                 secret, LOGON32_LOGON_INTERACTIVE,
                                 LOGON32_PROVIDER_DEFAULT, ctypes.byref(token))
        finally:
            del secret
        if not ok:
            raise WorkerLaunchFailed(
                "the worker credential was rejected by LogonUser (winerr "
                f"{ctypes.get_last_error()}); the password is wrong, rotated, or "
                "the account is unusable")
        # THE PROFILE MUST BE LOADED FIRST. `CreateEnvironmentBlock` against a
        # bare logon token returns the DEFAULT profile's environment, so
        # USERPROFILE and APPDATA would point at the machine default rather than
        # at the Worker — measured, not assumed: the first OS-real run of this
        # probe reported exactly that and the two checks failed.
        profile = _PROFILEINFOW()
        profile.dwSize = ctypes.sizeof(profile)
        profile.dwFlags = PI_NOUI
        profile.lpUserName = self.account.username
        loaded = bool(_userenv.LoadUserProfileW(token, ctypes.byref(profile)))
        try:
            if not loaded:
                raise WorkerLaunchFailed(
                    "the worker profile could not be loaded (winerr "
                    f"{ctypes.get_last_error()}); refusing to launch with an "
                    "environment that does not belong to the worker")
            return _environment_block_for_token(token)
        finally:
            if loaded:
                _userenv.UnloadUserProfile(token, profile.hProfile)
            _k32.CloseHandle(token)

    def _create_suspended(self, command: str, password: ctypes.Array[ctypes.c_char],
                          env: Mapping[str, str],
                          spec: LaunchSpec) -> tuple[_ProcessHandles, int]:
        startup = _STARTUPINFOW()
        startup.cb = ctypes.sizeof(startup)
        # NO STARTF_USESTDHANDLES: not one handle crosses the identity
        # boundary. The bootstrap opens the endpoints the sealed spec names,
        # itself, as the Worker — so there is nothing to audit for leakage
        # because there is nothing to leak.
        info = _PROCESS_INFORMATION()
        block = _encode_environment_block(env)
        buffer = ctypes.create_unicode_buffer(command, len(command) + 1)
        secret = _secret_text(password)
        try:
            ok = _a32.CreateProcessWithLogonW(
                self.account.username, self.account.domain or None, secret,
                LOGON_WITH_PROFILE, str(self.runtime), buffer,
                CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW,
                ctypes.byref(block), str(Path(spec.cwd)), ctypes.byref(startup),
                ctypes.byref(info))
        finally:
            del secret
        if not ok:
            raise WorkerLaunchFailed(
                f"CreateProcessWithLogonW failed (winerr {ctypes.get_last_error()})")
        handles = _ProcessHandles(process=int(info.hProcess),
                                  thread=int(info.hThread), job=0)
        return handles, int(info.dwProcessId)

    def _verify_and_contain(self, handles: _ProcessHandles, pid: int,
                            spec: LaunchSpec, digest: str,
                            command: str) -> LaunchedWorkerIdentity:
        token = W.HANDLE()
        if not _a32.OpenProcessToken(handles.process, TOKEN_QUERY,
                                     ctypes.byref(token)):
            _winfail("OpenProcessToken(child)")
        try:
            observed_sid = _token_user_sid(token)
            integrity = token_integrity(token.value or 0)
            groups = _token_group_sids(token)
            privileges = _token_privileges(token)
        finally:
            _k32.CloseHandle(token)

        dangerous = verify_worker_token(
            ObservedToken(sid=observed_sid, integrity=integrity, group_sids=groups,
                          privileges=privileges), self.account)
        is_admin = BUILTIN_ADMINISTRATORS_SID in groups

        handles.job = _create_job()
        if not _k32.AssignProcessToJobObject(handles.job, handles.process):
            _winfail("AssignProcessToJobObject")
        contained = W.BOOL(False)
        if not _k32.IsProcessInJob(handles.process, handles.job,
                                   ctypes.byref(contained)):
            _winfail("IsProcessInJob")
        if not contained.value:
            raise WorkerLaunchFailed(
                "the child was not contained by the job object; refusing to "
                "resume a process whose descendants could outlive the run")

        # EVERYTHING above passed. Only now may Worker code execute.
        if _k32.ResumeThread(handles.thread) == 0xFFFFFFFF:
            _winfail("ResumeThread")
        return LaunchedWorkerIdentity(
            pid=pid, observed_sid=observed_sid, integrity=integrity,
            is_administrator=is_admin, dangerous_privileges=dangerous,
            launch_spec_digest=digest,
            logical_command_digest=spec.logical_command_digest,
            transport_command_length=len(command), contained_in_job=True)


def assert_no_same_user_fallback(launcher: object) -> None:
    """The production profile has NO degraded mode.

    Called at the boundary so the absence is a checked property rather than a
    convention. A launcher that is None, or that is the explicit test fake, is
    refused here — the run fails instead of quietly executing as the Director.
    """
    if launcher is None:
        raise WorkerLaunchFailed(
            "no trusted worker launcher is configured; the run fails rather "
            "than launching as the Director")
    if getattr(launcher, "is_test_fake", False):
        raise WorkerLaunchFailed(
            f"{type(launcher).__name__} is a test fake and may never be selected "
            "in the production profile")


def summarise_launch(identity: LaunchedWorkerIdentity) -> dict[str, object]:
    """Trusted launch metadata for the runner's provenance.

    The TRANSPORT command is deliberately absent. `ExecutionResult.command`
    keeps its historical meaning — the LOGICAL command Gnosis ordered — so
    replay and cassettes are unaffected by the transport that carried it. What
    is added names the transport without conflating it with the payload.
    """
    return {
        "launcher_kind": identity.launcher_kind,
        "launcher_version": identity.launcher_version,
        "launch_spec_digest": identity.launch_spec_digest,
        "logical_command_digest": identity.logical_command_digest,
        "observed_worker_sid": identity.observed_sid,
        "worker_integrity": identity.integrity,
        "contained_in_job": identity.contained_in_job,
        "transport_command_length": identity.transport_command_length,
    }


def logical_argv(spec: LaunchSpec) -> Sequence[str]:
    return spec.argv
