"""OS-enforced authority boundary for the evidence anchor (F-17, BLOCKER C).

The worker and the Director run as the same OS user, so no NTFS DACL separates
them — a DACL is keyed by SID and they share one. **Windows Mandatory
Integrity Control does**: a process at a LOWER integrity level cannot write an
object labelled at a HIGHER level (the NO_WRITE_UP policy), enforced by the
kernel regardless of the DACL. That is an authority boundary between two
processes of the SAME user, which is exactly what a trust anchor against a
compromised worker needs.

The arrangement, demonstrated OS-real (see `git-authority-audit.txt`):

  - the Director / anchor **publisher runs at HIGH integrity** (elevated);
  - the **AnchorStore directory is laballed HIGH with NO_WRITE_UP**,
    inherited by its contents;
  - the **worker is launched at MEDIUM integrity** — a duplicate of the
    Director's token with its integrity lowered — so the worker AND every
    child process or shell it spawns is DENIED write / create / delete /
    rename / change-DACL / lower-label / take-ownership on the anchor by the
    kernel, and cannot raise its own integrity back to HIGH.

So `worker_write_authority ∩ anchor_write_authority = ∅` holds by the
processes' effective OS authority, not by a role flag, a prompt, or a path.

Threat model. This defeats **T2** — a malicious worker with a normal (Medium)
same-user token. It does NOT defeat **T3** (a compromised Director/Kernel: it
runs at HIGH and legitimately owns the anchor) or **T4** (an administrator /
full-OS compromise: SeRelabelPrivilege / ownership can relabel anything).
Those are declared out of scope; no cryptography is introduced.

Fail-closed. Where the OS boundary cannot be established — a non-Windows
platform, a Director that is not itself HIGH integrity, a label that does not
take — an anchor cannot be protected, so the store refuses to initialise
rather than pretend. An unprotectable anchor is not an anchor.
"""
from __future__ import annotations

import ctypes
import json
import subprocess
import sys
from ctypes import wintypes as W
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import GENESIS_HASH, hash_canonical

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

    def process_integrity() -> str:
        """The integrity level of the current process, as a level name."""
        token = W.HANDLE()
        if not _a32.OpenProcessToken(_k32.GetCurrentProcess(), _TOKEN_QUERY,
                                     ctypes.byref(token)):
            _fail("OpenProcessToken")
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


# ---------------------------------------------------------------------------
# The anchor record and the store.
# ---------------------------------------------------------------------------
ANCHOR_SCHEMA = "gnosis.anchor.v1"


@dataclass(frozen=True)
class AnchorRecord:
    """One published anchor. Binds WHICH run + WHICH source + WHICH bundle +
    WHICH digest, chained to the previous record. No general-purpose fields."""

    task_id: str
    run_id: str
    repository_id: str          # canonical repository identity (Director-held)
    head_sha: str               # the commit the bundle is bound to
    tree_identity: str          # implementation/tree identity (content digest)
    bundle_path: str            # bundle identity, repo-relative
    bundle_digest: str          # the trusted expected_digest
    seq: int
    prev_record_digest: str
    schema: str = ANCHOR_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "task_id": self.task_id, "run_id": self.run_id,
            "repository_id": self.repository_id, "head_sha": self.head_sha,
            "tree_identity": self.tree_identity, "bundle_path": self.bundle_path,
            "bundle_digest": self.bundle_digest, "seq": self.seq,
            "prev_record_digest": self.prev_record_digest,
        }

    def digest(self) -> str:
        """This record's own digest — the next record chains to it."""
        return hash_canonical(json.dumps(self.to_dict(), sort_keys=True))


class AnchorStore:
    """An append-only, hash-chained anchor ledger inside a HIGH-integrity
    directory that only a HIGH-integrity (Director) process can write.

    The OS boundary — not this class — is what stops a worker rewriting it: a
    Medium worker cannot write the ledger file or its directory. This class
    enforces the LOGICAL integrity (append-only, chained, re-verified) on top.
    """

    LEDGER = "anchors.jsonl"

    def __init__(self, root: Path, *, require_high: bool = True) -> None:
        self.root = root
        self.ledger = root / self.LEDGER
        root.mkdir(parents=True, exist_ok=True)
        # Fail closed unless the CURRENT process is HIGH: only a High publisher
        # may own an anchor store, or the label below is writable by whoever
        # created it.
        if require_high and _IS_WINDOWS and process_integrity() != "High":
            raise AuthorityUnavailable(
                "an AnchorStore may only be created by a HIGH-integrity "
                f"publisher; this process is {process_integrity()}")
        label_high_no_write_up(root)

    def records(self) -> list[AnchorRecord]:
        if not self.ledger.exists():
            return []
        out: list[AnchorRecord] = []
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(AnchorRecord(**json.loads(line)))
        return out

    def verify_chain(self) -> bool:
        prev = GENESIS_HASH
        for i, rec in enumerate(self.records()):
            if rec.seq != i or rec.prev_record_digest != prev:
                return False
            prev = rec.digest()
        return True

    def append(self, record: AnchorRecord) -> None:
        """Append a record, re-verifying the whole chain first. Fails closed
        on a chain that does not verify or a record that does not extend it."""
        if not self.verify_chain():
            raise AuthorityUnavailable("the anchor chain does not verify; refusing to extend")
        existing = self.records()
        expected_prev = existing[-1].digest() if existing else GENESIS_HASH
        if record.seq != len(existing) or record.prev_record_digest != expected_prev:
            raise AuthorityUnavailable("record does not extend the chain")
        with self.ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")

    def lookup(self, run_id: str) -> AnchorRecord | None:
        found: AnchorRecord | None = None
        for rec in self.records():
            if rec.run_id == run_id:
                found = rec  # last wins, but run_id should be unique
        return found

    def next_seq_and_prev(self) -> tuple[int, str]:
        recs = self.records()
        return (len(recs), recs[-1].digest() if recs else GENESIS_HASH)


@dataclass(frozen=True)
class RunIdentity:
    """The Director's OWN trusted record of a run. The publisher reconstructs
    the anchor from THIS, never from worker-supplied values — that is what
    stops the worker using the publisher as a confused-deputy write oracle."""

    task_id: str
    run_id: str
    repository_id: str
    head_sha: str
    bundle_path: str  # where the Director expects this run's bundle


def _bundle_head_sha(bundle_dir: Path) -> str | None:
    try:
        summary = json.loads((bundle_dir / "SUMMARY.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    post = summary.get("tree_identity", {}).get("post", {})
    fp = post.get("fingerprint") or {}
    value = fp.get("head_sha")
    return value if isinstance(value, str) else None


def _bundle_content_digest(bundle_dir: Path) -> str:
    try:
        summary = json.loads((bundle_dir / "SUMMARY.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    value = summary.get("boundary", {}).get("protection", {}).get("content_digest")
    return value if isinstance(value, str) else ""


def publish_anchor(store: AnchorStore, identity: RunIdentity, bundle_dir: Path,
                   verify: Any = None) -> AnchorRecord:
    """The publication protocol, run by the HIGH-integrity Director. It NEVER
    trusts a worker-supplied digest, path or identity:

    1. the bundle path comes from the Director's `identity`, not the worker;
    2. `verify_bundle` RECOMPUTES the digest from the bundle bytes;
    3. the bundle's own bound `head_sha` must equal the Director's `head_sha`
       (rejects a bundle from another run / a replayed old bundle);
    4. the record binds the Director-held identity, is chained, and is
       re-read after the write.
    """
    if verify is None:
        from .evidence_capture import verify_bundle  # lazy: avoid import cycle
        verify = verify_bundle
    result = verify(bundle_dir)
    if not getattr(result, "verified", False):
        raise AuthorityUnavailable("bundle is not self-consistent; refusing to anchor it")
    bound = _bundle_head_sha(bundle_dir)
    if bound is None or bound != identity.head_sha:
        raise AuthorityUnavailable(
            f"bundle is bound to {bound}, not the run's head {identity.head_sha}; "
            "refusing to anchor (cross-run / replay)")
    seq, prev = store.next_seq_and_prev()
    record = AnchorRecord(
        task_id=identity.task_id, run_id=identity.run_id,
        repository_id=identity.repository_id, head_sha=identity.head_sha,
        tree_identity=_bundle_content_digest(bundle_dir),
        bundle_path=identity.bundle_path, bundle_digest=result.bundle_digest,
        seq=seq, prev_record_digest=prev)
    store.append(record)
    reread = store.lookup(identity.run_id)
    if reread is None or reread.bundle_digest != record.bundle_digest:
        raise AuthorityUnavailable("the anchor did not read back as written")
    return record


def verify_anchored_bundle(store: AnchorStore, run_id: str, bundle_dir: Path,
                           verify: Any = None) -> bool:
    """Verify a bundle against the AUTHORITATIVE digest from the store — not a
    caller-supplied one. Fails closed on a missing record or a broken chain."""
    if verify is None:
        from .evidence_capture import verify_bundle  # lazy: avoid import cycle
        verify = verify_bundle
    if not store.verify_chain():
        raise AuthorityUnavailable("the anchor chain does not verify")
    record = store.lookup(run_id)
    if record is None:
        raise AuthorityUnavailable(f"no anchor record for run {run_id}; fail closed")
    result = verify(bundle_dir, expected_digest=record.bundle_digest)
    return bool(getattr(result, "verified", False))
