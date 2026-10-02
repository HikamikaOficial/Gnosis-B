"""Launch / identity primitives for the F-17 authority boundary.

This is the AUTHORITATIVE implementation of the launch and identity slice of
the Trust Plane (moved verbatim from `kernel.authority` in the Stage-1
trust-plane split; `kernel.authority` is now a compatibility re-export).

The worker and the Director run as the same OS user, so no NTFS DACL separates
them — a DACL is keyed by SID and they share one. **Windows Mandatory
Integrity Control does**: a process at a LOWER integrity level cannot write an
object labelled at a HIGHER level (the NO_WRITE_UP policy), enforced by the
kernel regardless of the DACL. Under the frozen P2 production model these MIC
primitives are **defense-in-depth**; the primary boundary is a distinct
RESTRICTED service SID + the NTFS DACL (see `docs/F17_PRODUCTION_WIRING_AND_
CLOSURE.md`).

Threat model. This defeats **T2** — a malicious worker with a normal (Medium)
same-user token. It does NOT defeat **T3** (a compromised Director/Kernel) or
**T4** (an administrator / full-OS compromise). Those are declared out of
scope; no cryptography is introduced.

Fail-closed. Where the OS boundary cannot be established — a non-Windows
platform, a Director that is not itself HIGH integrity, a label that does not
take — an anchor cannot be protected, so the store refuses to initialise
rather than pretend.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes as W
from pathlib import Path

_IS_WINDOWS = sys.platform == "win32"

# Integrity SIDs (the RID is the level: Low 0x1000, Medium 0x2000, High 0x3000).
SID_LOW = "S-1-16-4096"
SID_MEDIUM = "S-1-16-8192"
SID_HIGH = "S-1-16-12288"

_INTEGRITY_NAMES = {0x1000: "Low", 0x2000: "Medium", 0x3000: "High",
                    0x4000: "System", 0x0000: "Untrusted"}


class AuthorityUnavailable(RuntimeError):
    """The OS authority boundary could not be established, so nothing that
    depends on it may proceed. Distinct from a write being denied: this says
    the guarantee itself is not on offer here."""


# ---------------------------------------------------------------------------
# Windows primitives. Guarded so a non-Windows import does not explode; every
# entry point checks _IS_WINDOWS and fails closed off it.
# ---------------------------------------------------------------------------
if _IS_WINDOWS:
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _a32 = ctypes.WinDLL("advapi32", use_last_error=True)

    _k32.GetCurrentProcess.restype = W.HANDLE
    _k32.GetCurrentProcess.argtypes = []
    _k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    _k32.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
    _k32.CloseHandle.argtypes = [W.HANDLE]
    _a32.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, ctypes.POINTER(W.HANDLE)]
    _a32.OpenProcessToken.restype = W.BOOL
    _a32.GetTokenInformation.argtypes = [
        W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD)]
    _a32.GetTokenInformation.restype = W.BOOL
    _a32.SetTokenInformation.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD]
    _a32.SetTokenInformation.restype = W.BOOL
    _a32.DuplicateTokenEx.argtypes = [
        W.HANDLE, W.DWORD, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(W.HANDLE)]
    _a32.DuplicateTokenEx.restype = W.BOOL
    _a32.ConvertStringSidToSidW.argtypes = [W.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    _a32.ConvertStringSidToSidW.restype = W.BOOL
    _a32.GetLengthSid.argtypes = [ctypes.c_void_p]
    _a32.GetLengthSid.restype = W.DWORD
    _a32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    _a32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    _a32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, W.DWORD]
    _a32.GetSidSubAuthority.restype = ctypes.POINTER(W.DWORD)

    _TOKEN_QUERY = 0x0008
    _TOKEN_DUPLICATE = 0x0002
    _TOKEN_ASSIGN_PRIMARY = 0x0001
    _TOKEN_ADJUST_DEFAULT = 0x0080
    _TOKEN_ALL_ACCESS = 0xF01FF
    _TokenIntegrityLevel = 25
    _SecurityImpersonation = 2
    _TokenPrimary = 1
    _SE_GROUP_INTEGRITY = 0x00000020
    _LOGON_WITH_PROFILE = 0x00000001
    _CREATE_UNICODE_ENVIRONMENT = 0x00000400

    class _SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", W.DWORD)]

    class _TOKEN_MANDATORY_LABEL(ctypes.Structure):
        _fields_ = [("Label", _SID_AND_ATTRIBUTES)]

    class _STARTUPINFO(ctypes.Structure):
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

    _a32.CreateProcessWithTokenW.argtypes = [
        W.HANDLE, W.DWORD, W.LPCWSTR, W.LPWSTR, W.DWORD, ctypes.c_void_p,
        W.LPCWSTR, ctypes.POINTER(_STARTUPINFO), ctypes.POINTER(_PROCESS_INFORMATION)]
    _a32.CreateProcessWithTokenW.restype = W.BOOL

    def _fail(call: str) -> None:
        raise AuthorityUnavailable(f"{call} failed (winerr {ctypes.get_last_error()})")

    def token_integrity(token: int) -> str:
        """The integrity level of ANY token handle, as a level name.

        Split out of `process_integrity` (F-17 Stage 5) because the trusted
        launcher must read the integrity of the CHILD's token, not its own, and
        a second copy of the mandatory-label decode is exactly the duplication
        the Trust Plane refuses elsewhere. `process_integrity` is now this
        function applied to the current process.
        """
        size = W.DWORD()
        _a32.GetTokenInformation(token, _TokenIntegrityLevel, None, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        if not _a32.GetTokenInformation(token, _TokenIntegrityLevel, buf, size,
                                        ctypes.byref(size)):
            _fail("GetTokenInformation")
        tml = ctypes.cast(buf, ctypes.POINTER(_TOKEN_MANDATORY_LABEL)).contents
        count = _a32.GetSidSubAuthorityCount(tml.Label.Sid)[0]
        rid = _a32.GetSidSubAuthority(tml.Label.Sid, count - 1)[0]
        return _INTEGRITY_NAMES.get(rid, f"0x{rid:04x}")

    def process_integrity() -> str:
        """The integrity level of the current process, as a level name."""
        token = W.HANDLE()
        if not _a32.OpenProcessToken(_k32.GetCurrentProcess(), _TOKEN_QUERY,
                                     ctypes.byref(token)):
            _fail("OpenProcessToken")
        try:
            return token_integrity(token.value or 0)
        finally:
            _k32.CloseHandle(token)

    def lowered_primary_token(sid_string: str) -> W.HANDLE:
        """Duplicate the current token to PRIMARY and lower its integrity to
        `sid_string`. Lowering one's own integrity needs no privilege; the
        result can never be raised (a Medium token cannot mint a High one)."""
        src = W.HANDLE()
        access = (_TOKEN_QUERY | _TOKEN_DUPLICATE | _TOKEN_ASSIGN_PRIMARY
                  | _TOKEN_ADJUST_DEFAULT)
        if not _a32.OpenProcessToken(_k32.GetCurrentProcess(), access, ctypes.byref(src)):
            _fail("OpenProcessToken")
        dup = W.HANDLE()
        if not _a32.DuplicateTokenEx(src, _TOKEN_ALL_ACCESS, None,
                                     _SecurityImpersonation, _TokenPrimary,
                                     ctypes.byref(dup)):
            _fail("DuplicateTokenEx")
        psid = ctypes.c_void_p()
        if not _a32.ConvertStringSidToSidW(sid_string, ctypes.byref(psid)):
            _fail("ConvertStringSidToSidW")
        label = _TOKEN_MANDATORY_LABEL()
        label.Label.Sid = psid
        label.Label.Attributes = _SE_GROUP_INTEGRITY
        size = ctypes.sizeof(_SID_AND_ATTRIBUTES) + _a32.GetLengthSid(psid)
        if not _a32.SetTokenInformation(dup, _TokenIntegrityLevel,
                                        ctypes.byref(label), size):
            _fail("SetTokenInformation")
        return dup

    def run_at_integrity(cmdline: str, cwd: str, sid_string: str = SID_MEDIUM) -> int:
        """Launch `cmdline` with a token lowered to `sid_string` (Medium by
        default). Returns the child exit code. Requires SeImpersonatePrivilege.
        Every child the launched process spawns inherits the lowered token."""
        token = lowered_primary_token(sid_string)
        si = _STARTUPINFO()
        si.cb = ctypes.sizeof(si)
        pi = _PROCESS_INFORMATION()
        if not _a32.CreateProcessWithTokenW(
                token, _LOGON_WITH_PROFILE, None, cmdline,
                _CREATE_UNICODE_ENVIRONMENT, None, cwd, ctypes.byref(si), ctypes.byref(pi)):
            _fail("CreateProcessWithTokenW")
        _k32.WaitForSingleObject(pi.hProcess, 0xFFFFFFFF)
        code = W.DWORD()
        _k32.GetExitCodeProcess(pi.hProcess, ctypes.byref(code))
        _k32.CloseHandle(pi.hProcess)
        _k32.CloseHandle(pi.hThread)
        return int(code.value)

else:  # pragma: no cover - exercised only off Windows
    def token_integrity(token: int) -> str:
        raise AuthorityUnavailable("integrity levels are a Windows mechanism")

    def process_integrity() -> str:
        raise AuthorityUnavailable("integrity levels are a Windows mechanism")

    def run_at_integrity(cmdline: str, cwd: str, sid_string: str = SID_MEDIUM) -> int:
        raise AuthorityUnavailable("restricted launch is a Windows mechanism")


def assert_integrity(expected: str) -> None:
    """Fail closed unless the current process runs at `expected` integrity.

    Verifiable introspection for the wiring: the worker calls
    `assert_integrity("Medium")` at startup and the publisher
    `assert_integrity("High")`, so a launch that silently ran the worker at
    the wrong (higher) level is refused rather than proceeding as if
    protected."""
    actual = process_integrity()
    if actual != expected:
        raise AuthorityUnavailable(
            f"process integrity is {actual}, expected {expected}; fail closed")


def assert_publisher_identity(*, require_high: bool = True) -> None:
    """Publisher-identity precondition for owning an AnchorStore.

    STAGE 1 (trust-plane split) — this preserves the ORIGINAL same-user-MIC
    semantics EXACTLY: fail closed unless the current process is HIGH
    integrity. It is the EXPLICIT LOCUS where the future OS-real service-SID
    gate lands — assert the process user SID equals the deployed RESTRICTED
    publisher service SID recorded in DEPLOYMENT.json (plus is_token_restricted)
    — per ADR-0027 §3 and docs/F17_PRODUCTION_WIRING_AND_CLOSURE.md §3/§4.

    It is NOT yet that gate: it does not fake an undeployed service identity,
    and it does not weaken the current check. Substituting the service-SID gate
    needs the real deployment from a later stage (Stage 6, publisher wiring),
    so this documented compatibility precondition stands in until then. Never
    turned into a bare `require_high = False` bypass: the OS-enforced boundary
    remains the root of trust, and this in-process check is fail-closed
    consistency / defense-in-depth on top of it.
    """
    if require_high and _IS_WINDOWS and process_integrity() != "High":
        raise AuthorityUnavailable(
            "an AnchorStore may only be created by a HIGH-integrity "
            f"publisher; this process is {process_integrity()}")


def label_high_no_write_up(path: Path) -> None:
    """Label a directory HIGH integrity with NO_WRITE_UP, inherited by its
    contents, so a lower-integrity process cannot write into it. Verifies the
    label took; raises AuthorityUnavailable otherwise (fail closed)."""
    if not _IS_WINDOWS:
        raise AuthorityUnavailable("mandatory labels are a Windows mechanism")
    proc = subprocess.run(
        ["icacls", str(path), "/setintegritylevel", "(OI)(CI)High"],
        capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AuthorityUnavailable(f"could not label {path} High: {proc.stderr.strip()}")
    check = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=False)
    if "(NW)" not in check.stdout or (
            "High" not in check.stdout and "alto" not in check.stdout.lower()):
        raise AuthorityUnavailable(f"the High NO_WRITE_UP label did not take on {path}")
