"""Trust-plane deployment identity — what is EXECUTED, MEASURED and BOUND (F-17 Stage 2).

Evidence must prove the **actual trusted deployment**, not "some source commit
exists in Git" and not "the provisioning script intended this". Every field of
`TrustPlaneDeploymentIdentity` therefore comes from a **real query against the
running system**: bytes read off the disk, the SCM's own answer about the
service, security descriptors read back from the OS.

The separation this module exists to enforce:

    DesiredDeploymentConfig      what provisioning INTENDS — locations to look
                                 at and expectations to check against. It is
                                 NEVER a source of identity.
    TrustPlaneDeploymentIdentity what was actually OBSERVED. The authoritative
                                 value. `deployment_digest` is a hash over this
                                 and only this.

so that

    desired configuration -> provision
    OS / filesystem       -> query observed state -> canonicalize -> identity
                                                                  -> deployment_digest

A deployment whose observed state drifts from what was intended is caught
because the identity reflects reality; changing the *intention* alone changes
nothing (`tests/test_deployment_identity.py` proves both directions).

**Fail closed.** Anything mandatory that cannot be observed — a missing
service, an unresolvable service SID, an unknown SID type, an unreadable
binary, an unreadable or unsupported security descriptor, a manifest that does
not match the bytes on disk — raises `DeploymentIdentityUnavailable`. There are
no defaults: a value that could not be observed is not a value.

**Hashing is detection, not prevention.** This module BINDS what it observed at
the moment it observed it. Nothing here stops the Worker modifying a trusted
file afterwards; only the ACL/SID boundary does that. The window between
`observe` and `execute` is a declared Stage-2 gap (see `TOCTOU` in the module
docs and the residual risks in the Stage-2 evidence).

Scope note: the reparse/redirection handling here covers the Trust Plane and
its runtime — the objects that form the deployment — and nothing else. It is
deliberately NOT a general filesystem audit, and it is deliberately NOT the
F-14 capture boundary (`kernel.input_lock`), which answers a different question
about a different set of paths; importing that module would add ~936 lines to
the TCB for a contract this stage does not need.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import subprocess
import sys
from ctypes import wintypes as W
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from gnosis.kernel.canonical import hash_canonical
from gnosis.trust.launch import AuthorityUnavailable

DEPLOYMENT_SCHEMA = "gnosis.trust.deployment.v1"
MANIFEST_SCHEMA = "gnosis.trust.package.v1"

_IS_WINDOWS = sys.platform == "win32"


class DeploymentIdentityUnavailable(AuthorityUnavailable):
    """A mandatory part of the deployment could not be OBSERVED, so no identity
    may be produced. A subclass of AuthorityUnavailable: every existing
    fail-closed handler already refuses to proceed on it, and the distinct type
    keeps "the OS boundary is not on offer" separable from "the deployment
    could not be measured"."""


# ---------------------------------------------------------------------------
# Security-descriptor canonicalization (pure: bytes in, identity out)
#
# The digest must not depend on incidental `icacls` / `sc sdshow` text, on the
# short SDDL SID aliases (BA vs S-1-5-32-544), or on how a right happens to be
# spelled (FA vs 0x1f01ff). So the BINARY descriptor is parsed through the Win32
# accessors and re-expressed in one form: SIDs always as S-1-… strings, masks
# and flags always as integers.
#
# ACE ORDER IS PRESERVED, DELIBERATELY. Order is semantic in an ACL — Windows
# evaluates ACEs in sequence, so a deny ACE moved after an allow ACE is a
# different descriptor, not a differently-formatted one. Sorting them would
# therefore be exactly the "canonicalization loses ACL semantics" stop condition
# this stage is forbidden to cross. Two descriptors that differ ONLY in the
# order of ACEs get different identities: a false drift (which fails closed),
# never a false match. Deciding they are equivalent would mean re-implementing
# the Windows access check, which is out of scope by direction.
# ---------------------------------------------------------------------------

# ACEs whose layout is ACE_HEADER + ACCESS_MASK + SID. Object ACEs (types 5-8)
# carry GUIDs at a different offset and are NOT parsed: an unsupported form
# fails closed rather than being silently misread.
_SIMPLE_ACE_TYPES = {
    0x00,  # ACCESS_ALLOWED
    0x01,  # ACCESS_DENIED
    0x02,  # SYSTEM_AUDIT
    0x03,  # SYSTEM_ALARM
    0x11,  # SYSTEM_MANDATORY_LABEL
    0x12,  # SYSTEM_RESOURCE_ATTRIBUTE
    0x13,  # SYSTEM_SCOPED_POLICY_ID
    0x14,  # SYSTEM_PROCESS_TRUST_LABEL
    0x15,  # SYSTEM_ACCESS_FILTER
}
_MANDATORY_LABEL_ACE = 0x11

# Control bits that carry inheritance/protection SEMANTICS. SE_SELF_RELATIVE
# (0x8000) is excluded on purpose: it describes how the descriptor is stored,
# not what it means, and including it would make an absolute and a self-relative
# copy of the same descriptor differ.
_SEMANTIC_CONTROL_MASK = (
    0x0004    # SE_DACL_PRESENT
    | 0x0008  # SE_DACL_DEFAULTED
    | 0x0010  # SE_SACL_PRESENT
    | 0x0020  # SE_SACL_DEFAULTED
    | 0x0100  # SE_DACL_AUTO_INHERITED
    | 0x0200  # SE_SACL_AUTO_INHERITED
    | 0x1000  # SE_DACL_PROTECTED
    | 0x2000  # SE_SACL_PROTECTED
)


@dataclass(frozen=True)
class AceIdentity:
    """One ACE, in the single canonical representation."""

    ace_type: int
    ace_flags: int
    access_mask: int
    sid: str

    def to_dict(self) -> dict[str, Any]:
        return {"ace_type": self.ace_type, "ace_flags": self.ace_flags,
                "access_mask": self.access_mask, "sid": self.sid}


@dataclass(frozen=True)
class SecurityDescriptorIdentity:
    """A security descriptor as observed, normalized in representation only."""

    owner_sid: str
    group_sid: str
    control: int
    dacl_present: bool
    aces: tuple[AceIdentity, ...]
    mandatory_label: AceIdentity | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_sid": self.owner_sid,
            "group_sid": self.group_sid,
            "control": self.control,
            "dacl_present": self.dacl_present,
            "aces": [a.to_dict() for a in self.aces],
            "mandatory_label": (self.mandatory_label.to_dict()
                                if self.mandatory_label is not None else None),
        }

    def digest(self) -> str:
        return hash_canonical(self.to_dict())


# ---------------------------------------------------------------------------
# Win32 layer. Explicit APIs, checked return codes, fail closed, no shell text
# parsing, no locale dependence. Guarded so a non-Windows import does not
# explode; every entry point checks _IS_WINDOWS and refuses off it.
# ---------------------------------------------------------------------------
if _IS_WINDOWS:
    import msvcrt  # Windows-only stdlib; reached only under _IS_WINDOWS

    _a32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _a32.GetSecurityDescriptorOwner.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(W.BOOL)]
    _a32.GetSecurityDescriptorOwner.restype = W.BOOL
    _a32.GetSecurityDescriptorGroup.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(W.BOOL)]
    _a32.GetSecurityDescriptorGroup.restype = W.BOOL
    _a32.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(W.BOOL), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(W.BOOL)]
    _a32.GetSecurityDescriptorDacl.restype = W.BOOL
    _a32.GetSecurityDescriptorSacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(W.BOOL), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(W.BOOL)]
    _a32.GetSecurityDescriptorSacl.restype = W.BOOL
    _a32.GetSecurityDescriptorControl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(W.WORD), ctypes.POINTER(W.DWORD)]
    _a32.GetSecurityDescriptorControl.restype = W.BOOL
    _a32.GetSecurityDescriptorLength.argtypes = [ctypes.c_void_p]
    _a32.GetSecurityDescriptorLength.restype = W.DWORD
    _a32.IsValidSecurityDescriptor.argtypes = [ctypes.c_void_p]
    _a32.IsValidSecurityDescriptor.restype = W.BOOL
    _a32.GetAclInformation.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, W.DWORD, ctypes.c_int]
    _a32.GetAclInformation.restype = W.BOOL
    _a32.GetAce.argtypes = [ctypes.c_void_p, W.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    _a32.GetAce.restype = W.BOOL
    _a32.IsValidSid.argtypes = [ctypes.c_void_p]
    _a32.IsValidSid.restype = W.BOOL
    _a32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(W.LPWSTR)]
    _a32.ConvertSidToStringSidW.restype = W.BOOL
    _a32.GetNamedSecurityInfoW.argtypes = [
        W.LPCWSTR, ctypes.c_int, W.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
    _a32.GetNamedSecurityInfoW.restype = W.DWORD
    _a32.LookupAccountNameW.argtypes = [
        W.LPCWSTR, W.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(W.DWORD),
        W.LPWSTR, ctypes.POINTER(W.DWORD), ctypes.POINTER(W.DWORD)]
    _a32.LookupAccountNameW.restype = W.BOOL
    _a32.OpenSCManagerW.argtypes = [W.LPCWSTR, W.LPCWSTR, W.DWORD]
    _a32.OpenSCManagerW.restype = ctypes.c_void_p
    _a32.OpenServiceW.argtypes = [ctypes.c_void_p, W.LPCWSTR, W.DWORD]
    _a32.OpenServiceW.restype = ctypes.c_void_p
    _a32.CloseServiceHandle.argtypes = [ctypes.c_void_p]
    _a32.CloseServiceHandle.restype = W.BOOL
    _a32.QueryServiceConfigW.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD)]
    _a32.QueryServiceConfigW.restype = W.BOOL
    _a32.QueryServiceConfig2W.argtypes = [
        ctypes.c_void_p, W.DWORD, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD)]
    _a32.QueryServiceConfig2W.restype = W.BOOL
    _a32.QueryServiceObjectSecurity.argtypes = [
        ctypes.c_void_p, W.DWORD, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD)]
    _a32.QueryServiceObjectSecurity.restype = W.BOOL
    _k32.LocalFree.argtypes = [ctypes.c_void_p]
    _k32.LocalFree.restype = ctypes.c_void_p
    _k32.GetFinalPathNameByHandleW.argtypes = [W.HANDLE, W.LPWSTR, W.DWORD, W.DWORD]
    _k32.GetFinalPathNameByHandleW.restype = W.DWORD
    _k32.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, ctypes.c_void_p,
                                 W.DWORD, W.DWORD, W.HANDLE]
    _k32.CreateFileW.restype = W.HANDLE
    _k32.CloseHandle.argtypes = [W.HANDLE]
    _k32.CloseHandle.restype = W.BOOL
    _a32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        W.LPCWSTR, W.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(W.DWORD)]
    _a32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = W.BOOL

    class _ACE_HEADER(ctypes.Structure):
        _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte),
                    ("AceSize", W.WORD)]

    class _ACL_SIZE_INFORMATION(ctypes.Structure):
        _fields_ = [("AceCount", W.DWORD), ("AclBytesInUse", W.DWORD),
                    ("AclBytesFree", W.DWORD)]

    class _SERVICE_REQUIRED_PRIVILEGES_INFO(ctypes.Structure):
        _fields_ = [("pmszRequiredPrivileges", ctypes.c_void_p)]

    class _QUERY_SERVICE_CONFIGW(ctypes.Structure):
        _fields_ = [
            ("dwServiceType", W.DWORD), ("dwStartType", W.DWORD),
            ("dwErrorControl", W.DWORD), ("lpBinaryPathName", W.LPWSTR),
            ("lpLoadOrderGroup", W.LPWSTR), ("dwTagId", W.DWORD),
            ("lpDependencies", W.LPWSTR), ("lpServiceStartName", W.LPWSTR),
            ("lpDisplayName", W.LPWSTR)]

    _SE_FILE_OBJECT = 1
    _OWNER_SECURITY_INFORMATION = 0x00000001
    _GROUP_SECURITY_INFORMATION = 0x00000002
    _DACL_SECURITY_INFORMATION = 0x00000004
    _LABEL_SECURITY_INFORMATION = 0x00000010
    _AclSizeInformation = 2
    _SC_MANAGER_CONNECT = 0x0001
    _SERVICE_QUERY_CONFIG = 0x0001
    _READ_CONTROL = 0x00020000
    _SERVICE_CONFIG_SERVICE_SID_INFO = 5
    _SERVICE_CONFIG_REQUIRED_PRIVILEGES_INFO = 6


def _require_windows(what: str) -> None:
    if not _IS_WINDOWS:
        raise DeploymentIdentityUnavailable(
            f"{what} is a Windows mechanism; deployment identity is unavailable here")


def _fail(call: str, code: int | None = None) -> None:
    err = ctypes.get_last_error() if code is None else code
    raise DeploymentIdentityUnavailable(f"{call} failed (winerr {err})")


def _sid_to_string(sid_ptr: Any) -> str:
    ptr = ctypes.c_void_p(sid_ptr) if isinstance(sid_ptr, int) else sid_ptr
    if not ptr or not _a32.IsValidSid(ptr):
        raise DeploymentIdentityUnavailable("security descriptor holds an invalid SID")
    out = W.LPWSTR()
    if not _a32.ConvertSidToStringSidW(ptr, ctypes.byref(out)):
        _fail("ConvertSidToStringSidW")
    try:
        value = out.value
    finally:
        _k32.LocalFree(out)
    if not value:
        raise DeploymentIdentityUnavailable("ConvertSidToStringSidW returned no SID")
    return value


def _parse_acl(acl_ptr: Any) -> tuple[AceIdentity, ...]:
    """Every ACE of an ACL, in the order the ACL holds them."""
    info = _ACL_SIZE_INFORMATION()
    if not _a32.GetAclInformation(acl_ptr, ctypes.byref(info),
                                  ctypes.sizeof(info), _AclSizeInformation):
        _fail("GetAclInformation")
    aces: list[AceIdentity] = []
    for index in range(info.AceCount):
        ace = ctypes.c_void_p()
        if not _a32.GetAce(acl_ptr, index, ctypes.byref(ace)):
            _fail("GetAce")
        header = ctypes.cast(ace, ctypes.POINTER(_ACE_HEADER)).contents
        if header.AceType not in _SIMPLE_ACE_TYPES:
            # Object ACEs place GUIDs before the SID; reading them with the
            # simple layout would silently produce a wrong identity.
            raise DeploymentIdentityUnavailable(
                f"unsupported ACE type 0x{header.AceType:02x} in the observed "
                "descriptor; refusing to guess its layout")
        base = ace.value or 0
        mask = ctypes.cast(ctypes.c_void_p(base + 4),
                           ctypes.POINTER(W.DWORD)).contents.value
        aces.append(AceIdentity(ace_type=int(header.AceType),
                                ace_flags=int(header.AceFlags),
                                access_mask=int(mask),
                                sid=_sid_to_string(base + 8)))
    return tuple(aces)


def canonical_security_descriptor(sd_bytes: bytes) -> SecurityDescriptorIdentity:
    """Canonicalize an OBSERVED binary security descriptor.

    Normalizes REPRESENTATION (SID string form, integer masks and flags) and
    preserves SEMANTICS (ACE order, every ACE, the inheritance/protection
    control bits). No ACE is dropped as "redundant": whether two ACEs are
    equivalent is a question about the Windows access check, which this
    deliberately does not re-implement.
    """
    _require_windows("security-descriptor canonicalization")
    if not sd_bytes:
        raise DeploymentIdentityUnavailable(
            "empty security descriptor; nothing to canonicalize")
    buf = ctypes.create_string_buffer(sd_bytes, len(sd_bytes))
    if not _a32.IsValidSecurityDescriptor(buf):
        raise DeploymentIdentityUnavailable(
            "malformed security descriptor; refusing to canonicalize")

    control = W.WORD()
    revision = W.DWORD()
    if not _a32.GetSecurityDescriptorControl(buf, ctypes.byref(control),
                                             ctypes.byref(revision)):
        _fail("GetSecurityDescriptorControl")

    owner = ctypes.c_void_p()
    defaulted = W.BOOL()
    if not _a32.GetSecurityDescriptorOwner(buf, ctypes.byref(owner),
                                           ctypes.byref(defaulted)):
        _fail("GetSecurityDescriptorOwner")
    if not owner:
        raise DeploymentIdentityUnavailable(
            "observed descriptor has no owner; fail closed")
    owner_sid = _sid_to_string(owner)

    group = ctypes.c_void_p()
    if not _a32.GetSecurityDescriptorGroup(buf, ctypes.byref(group),
                                           ctypes.byref(defaulted)):
        _fail("GetSecurityDescriptorGroup")
    group_sid = _sid_to_string(group) if group else ""

    dacl_present = W.BOOL()
    dacl = ctypes.c_void_p()
    if not _a32.GetSecurityDescriptorDacl(buf, ctypes.byref(dacl_present),
                                          ctypes.byref(dacl), ctypes.byref(defaulted)):
        _fail("GetSecurityDescriptorDacl")
    if not dacl_present.value or not dacl:
        # A NULL DACL grants everyone full access. It is a real, and alarming,
        # observation - recorded as such via dacl_present, never smoothed into
        # "this object simply has no ACEs".
        aces: tuple[AceIdentity, ...] = ()
    else:
        aces = _parse_acl(dacl)

    sacl_present = W.BOOL()
    sacl = ctypes.c_void_p()
    label: AceIdentity | None = None
    if (_a32.GetSecurityDescriptorSacl(buf, ctypes.byref(sacl_present),
                                       ctypes.byref(sacl), ctypes.byref(defaulted))
            and sacl_present.value and sacl):
        for ace in _parse_acl(sacl):
            if ace.ace_type == _MANDATORY_LABEL_ACE:
                label = ace
                break

    return SecurityDescriptorIdentity(
        owner_sid=owner_sid,
        group_sid=group_sid,
        control=int(control.value) & _SEMANTIC_CONTROL_MASK,
        dacl_present=bool(dacl_present.value),
        aces=aces,
        mandatory_label=label,
    )


# ---------------------------------------------------------------------------
# Paths: canonical form and redirection
#
# Only the objects that FORM the deployment are handled here — the trust root,
# its files, the runtime, the state roots. `_final_path` asks Windows what an
# OPEN HANDLE actually refers to, so a symlink, junction or reparse point
# anywhere in the chain resolves to the object whose bytes are really read.
# That is what keeps `expected path` and `executed bytes` from being two
# different objects without the identity noticing.
# ---------------------------------------------------------------------------
def _final_path(handle: int) -> str:
    """The OS-resolved path of an open handle: real on-disk case, reparse
    points resolved, no `\\\\?\\` prefix. UNC is refused — a trust root that
    lives on a remote share is not a boundary this stage can reason about."""
    buf = ctypes.create_unicode_buffer(32768)
    length = _k32.GetFinalPathNameByHandleW(W.HANDLE(handle), buf, 32768, 0)
    if length == 0 or length >= 32768:
        _fail("GetFinalPathNameByHandleW")
    value = buf.value
    if value.startswith(("\\\\?\\UNC\\", "\\\\UNC\\")):
        raise DeploymentIdentityUnavailable(
            f"trust-plane object resolves to a UNC path ({value}); refused")
    return value.removeprefix("\\\\?\\")


def observed_directory_path(path: Path) -> str:
    """The OS-resolved canonical path of an existing DIRECTORY."""
    _require_windows("path resolution")
    handle = _k32.CreateFileW(str(path), 0x80000000, 0x00000007, None, 3,
                              0x02000000, None)
    if handle == -1 or handle is None or handle == 0xFFFFFFFFFFFFFFFF:
        _fail(f"CreateFileW({path})")
    try:
        return _final_path(handle)
    finally:
        _k32.CloseHandle(W.HANDLE(handle))


def _measure_file(path: Path) -> tuple[str, int, str]:
    """(resolved path, size, sha256) — identity and bytes from ONE handle.

    The digest is computed from the bytes read through the very handle whose
    resolved path was taken, so `manifest says hash X` can never stand in for
    what is actually on disk at that location.
    """
    _require_windows("file measurement")
    try:
        with open(path, "rb") as fh:
            resolved = _final_path(msvcrt.get_osfhandle(fh.fileno()))
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise DeploymentIdentityUnavailable(
            f"trusted artifact {path} could not be read: {exc}") from exc
    return resolved, size, digest.hexdigest()


# ---------------------------------------------------------------------------
# Observed security of a path
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PathSecurityIdentity:
    """A deployment path as observed: where it really is, and who may touch it."""

    path: str
    security_descriptor: SecurityDescriptorIdentity

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path,
                "security_descriptor": self.security_descriptor.to_dict()}


def read_path_security_descriptor(path: Path) -> bytes:
    """The OBSERVED binary security descriptor of a file or directory,
    including its mandatory label. Read through GetNamedSecurityInfoW — never
    parsed out of `icacls` text, which is formatted and localized."""
    _require_windows("security descriptor observation")
    psd = ctypes.c_void_p()
    unused = ctypes.c_void_p()
    info = (_OWNER_SECURITY_INFORMATION | _GROUP_SECURITY_INFORMATION
            | _DACL_SECURITY_INFORMATION | _LABEL_SECURITY_INFORMATION)
    status = _a32.GetNamedSecurityInfoW(
        str(path), _SE_FILE_OBJECT, info, ctypes.byref(unused),
        ctypes.byref(unused), ctypes.byref(unused), ctypes.byref(unused),
        ctypes.byref(psd))
    if status != 0 or not psd:
        _fail(f"GetNamedSecurityInfoW({path})", status)
    try:
        length = _a32.GetSecurityDescriptorLength(psd)
        if not length:
            raise DeploymentIdentityUnavailable(
                f"security descriptor of {path} has zero length; fail closed")
        return ctypes.string_at(psd, length)
    finally:
        _k32.LocalFree(psd)


def observe_path_security(path: Path) -> PathSecurityIdentity:
    """Observe WHERE a deployment directory really is and its canonical ACL."""
    resolved = observed_directory_path(path)
    return PathSecurityIdentity(
        path=resolved,
        security_descriptor=canonical_security_descriptor(
            read_path_security_descriptor(Path(resolved))))


# ---------------------------------------------------------------------------
# The trust package: a deterministic manifest over the ACTUAL deployed bytes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FileIdentity:
    """One deployed trusted artifact, measured from its real bytes."""

    path: str      # canonical, relative to the resolved trust root, "/" separated
    size: int
    digest: str    # sha256 of the bytes read through the identified handle

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size": self.size, "digest": self.digest}


@dataclass(frozen=True)
class TrustPackageManifest:
    """Every file of the deployed trust package, in one deterministic order.

    Determinism, deliberately: entries are sorted by their canonical relative
    path in code-point order (not locale order), the path comes from the
    OS-resolved name so its case is the on-disk case rather than whatever the
    caller typed, and NOTHING incidental is bound — no mtime, no creation
    time, no directory enumeration order. The same installation, byte for
    byte, produces the same manifest digest on any machine.
    """

    schema: str
    package_version: str
    source_commit: str
    source_tree: str
    files: tuple[FileIdentity, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "package_version": self.package_version,
                "source_commit": self.source_commit, "source_tree": self.source_tree,
                "files": [f.to_dict() for f in self.files]}

    def digest(self) -> str:
        return hash_canonical(self.to_dict())


def _read_package_declaration(root: Path) -> dict[str, str]:
    """version/commit/tree, read from the DEPLOYED package, not from a caller.

    These are properties OF the installation, so they are observed from
    PACKAGE.json inside the trust root — whose bytes are themselves measured
    into the manifest — rather than being passed in by whoever is asking.
    """
    declaration = root / "PACKAGE.json"
    try:
        raw = json.loads(declaration.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DeploymentIdentityUnavailable(
            f"trust package declaration {declaration} is unreadable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise DeploymentIdentityUnavailable(
            f"trust package declaration {declaration} is malformed: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != MANIFEST_SCHEMA:
        raise DeploymentIdentityUnavailable(
            f"trust package declaration {declaration} is not {MANIFEST_SCHEMA}")
    out: dict[str, str] = {}
    for field in ("package_version", "source_commit", "source_tree"):
        value = raw.get(field)
        if not isinstance(value, str) or not value:
            raise DeploymentIdentityUnavailable(
                f"trust package declaration is missing {field}; fail closed")
        out[field] = value
    return out


def observe_trust_package(root: Path) -> TrustPackageManifest:
    """Measure EVERY file under the deployed trust root.

    No file is excluded. An excluded file is an unmeasured file, and an
    unmeasured file under the trust root is code that can run without the
    identity changing.
    """
    _require_windows("trust package observation")
    if not root.is_dir():
        raise DeploymentIdentityUnavailable(f"trust root {root} does not exist; fail closed")
    resolved_root = observed_directory_path(root)
    prefix = resolved_root.rstrip("\\") + "\\"
    declaration = _read_package_declaration(root)

    files: list[FileIdentity] = []
    for candidate in root.rglob("*"):
        if candidate.is_dir():
            continue
        resolved, size, digest = _measure_file(candidate)
        if not resolved.startswith(prefix):
            # The file resolves outside the trust root: a redirection that
            # would make `expected path` and `executed bytes` different objects.
            raise DeploymentIdentityUnavailable(
                f"trusted artifact {candidate} resolves outside the trust root "
                f"to {resolved}; refusing to measure a redirected deployment")
        relative = str(PurePosixPath(*Path(resolved[len(prefix):]).parts))
        files.append(FileIdentity(path=relative, size=size, digest=digest))

    if not files:
        raise DeploymentIdentityUnavailable(f"trust root {root} holds no files; fail closed")
    return TrustPackageManifest(
        schema=MANIFEST_SCHEMA,
        package_version=declaration["package_version"],
        source_commit=declaration["source_commit"],
        source_tree=declaration["source_tree"],
        files=tuple(sorted(files, key=lambda f: f.path)))


def verify_package_against_expected(observed: TrustPackageManifest,
                                    expected: TrustPackageManifest) -> None:
    """`hash(actual bytes) == manifest expected hash`, per file, both ways.

    Fails closed on a changed file, a missing file AND an extra file — an
    unexpected artifact under the trust root is code nobody approved.
    """
    observed_map = {f.path: f for f in observed.files}
    expected_map = {f.path: f for f in expected.files}
    missing = sorted(set(expected_map) - set(observed_map))
    extra = sorted(set(observed_map) - set(expected_map))
    changed = sorted(p for p in set(observed_map) & set(expected_map)
                     if (observed_map[p].digest != expected_map[p].digest
                         or observed_map[p].size != expected_map[p].size))
    if missing or extra or changed:
        raise DeploymentIdentityUnavailable(
            "the deployed trust package does not match the expected manifest "
            f"(missing={missing}, unexpected={extra}, changed={changed}); fail closed")


# ---------------------------------------------------------------------------
# The trusted runtime
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RuntimeIdentity:
    """The interpreter that actually executes the trust plane.

    Bound by its BYTES, not merely by "Python 3.12": two python.exe with the
    same nominal version are not the same trusted runtime.
    """

    executable_path: str
    executable_size: int
    executable_digest: str
    version: str
    implementation: str
    architecture: str
    machine: str

    def to_dict(self) -> dict[str, Any]:
        return {"executable_path": self.executable_path,
                "executable_size": self.executable_size,
                "executable_digest": self.executable_digest,
                "version": self.version, "implementation": self.implementation,
                "architecture": self.architecture, "machine": self.machine}


_RUNTIME_PROBE = (
    "import json,platform,sys;"
    "print(json.dumps({'version':sys.version,"
    "'implementation':sys.implementation.name,"
    "'architecture':platform.architecture()[0],"
    "'machine':platform.machine()}))")


def observe_runtime(executable: Path) -> RuntimeIdentity:
    """Measure the runtime: its real bytes, and what it says about itself.

    The version/architecture come from ASKING THAT executable (`-I -S -c`), not
    from the observing process — the deployment's runtime need not be the one
    running this code.
    """
    _require_windows("runtime observation")
    resolved, size, digest = _measure_file(executable)
    try:
        # encoding/errors are pinned: a runtime whose stderr is not UTF-8 (a
        # localized console codepage) must not turn into a decode crash in the
        # middle of an identity measurement.
        proc = subprocess.run([resolved, "-I", "-S", "-c", _RUNTIME_PROBE],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeploymentIdentityUnavailable(
            f"trusted runtime {resolved} could not be queried: {exc}") from exc
    if proc.returncode != 0:
        raise DeploymentIdentityUnavailable(
            f"trusted runtime {resolved} refused the identity probe "
            f"(exit {proc.returncode}); fail closed")
    try:
        reported = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise DeploymentIdentityUnavailable(
            f"trusted runtime {resolved} returned an unparsable identity: {exc}") from exc
    for field in ("version", "implementation", "architecture", "machine"):
        if not isinstance(reported.get(field), str) or not reported[field]:
            raise DeploymentIdentityUnavailable(
                f"trusted runtime did not report {field}; fail closed")
    return RuntimeIdentity(
        executable_path=resolved, executable_size=size, executable_digest=digest,
        version=reported["version"], implementation=reported["implementation"],
        architecture=reported["architecture"], machine=reported["machine"])


# ---------------------------------------------------------------------------
# The Windows service, as the SCM actually holds it
# ---------------------------------------------------------------------------
_SID_TYPES = {0: "NONE", 1: "UNRESTRICTED", 3: "RESTRICTED"}
_START_TYPES = {0: "BOOT", 1: "SYSTEM", 2: "AUTO", 3: "DEMAND", 4: "DISABLED"}
_ERROR_SERVICE_DOES_NOT_EXIST = 1060


@dataclass(frozen=True)
class ServiceIdentity:
    """The publisher service exactly as the SCM reports it."""

    name: str
    account: str
    image_path: str
    start_type: str
    service_sid: str
    sid_type: str
    required_privileges: tuple[str, ...]
    security_descriptor: SecurityDescriptorIdentity

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "account": self.account,
                "image_path": self.image_path, "start_type": self.start_type,
                "service_sid": self.service_sid, "sid_type": self.sid_type,
                "required_privileges": list(self.required_privileges),
                "security_descriptor": self.security_descriptor.to_dict()}


def service_sid(name: str) -> str:
    """The OS-resolved SID of `NT SERVICE\\<name>`.

    Asked of Windows rather than derived from the documented name hash: a SID
    this code computed itself would prove only that the code can compute it.
    """
    _require_windows("service SID lookup")
    size = W.DWORD(0)
    domain_size = W.DWORD(0)
    use = W.DWORD(0)
    account = f"NT SERVICE\\{name}"
    _a32.LookupAccountNameW(None, account, None, ctypes.byref(size), None,
                            ctypes.byref(domain_size), ctypes.byref(use))
    if not size.value:
        _fail(f"LookupAccountNameW({account})")
    sid_buf = ctypes.create_string_buffer(size.value)
    domain_buf = ctypes.create_unicode_buffer(max(domain_size.value, 1))
    if not _a32.LookupAccountNameW(None, account, sid_buf, ctypes.byref(size),
                                   domain_buf, ctypes.byref(domain_size),
                                   ctypes.byref(use)):
        _fail(f"LookupAccountNameW({account})")
    return _sid_to_string(ctypes.cast(sid_buf, ctypes.c_void_p))


def _query_service_config2(handle: Any, level: int, what: str) -> Any:
    """The raw SCM answer, returned as the LIVE buffer.

    Deliberately not `buf.raw`: SERVICE_REQUIRED_PRIVILEGES_INFO holds a
    POINTER into this very buffer, so a copy of the bytes would leave the
    caller reading freed memory.
    """
    needed = W.DWORD(0)
    _a32.QueryServiceConfig2W(handle, level, None, 0, ctypes.byref(needed))
    buf = ctypes.create_string_buffer(max(needed.value, 16))
    if not _a32.QueryServiceConfig2W(handle, level, buf, len(buf), ctypes.byref(needed)):
        _fail(f"QueryServiceConfig2W({what})")
    return buf


def _read_multi_sz(address: int) -> tuple[str, ...]:
    """A Windows MULTI_SZ (NUL-separated, double-NUL terminated) as strings."""
    if not address:
        return ()
    out: list[str] = []
    offset = 0
    while True:
        item = ctypes.wstring_at(address + offset)
        if not item:
            return tuple(out)
        out.append(item)
        offset += (len(item) + 1) * 2


def read_service_security_descriptor(handle: Any) -> bytes:
    """The OBSERVED binary security descriptor of the service object."""
    needed = W.DWORD(0)
    info = (_OWNER_SECURITY_INFORMATION | _GROUP_SECURITY_INFORMATION
            | _DACL_SECURITY_INFORMATION)
    _a32.QueryServiceObjectSecurity(handle, info, None, 0, ctypes.byref(needed))
    if not needed.value:
        _fail("QueryServiceObjectSecurity(size)")
    buf = ctypes.create_string_buffer(needed.value)
    if not _a32.QueryServiceObjectSecurity(handle, info, buf, needed,
                                           ctypes.byref(needed)):
        _fail("QueryServiceObjectSecurity")
    return buf.raw[:needed.value]


def observe_service(name: str) -> ServiceIdentity:
    """Read the REAL service state from the SCM. Anything mandatory that is
    missing or unrecognised fails closed rather than defaulting."""
    _require_windows("service observation")
    scm = _a32.OpenSCManagerW(None, None, _SC_MANAGER_CONNECT)
    if not scm:
        _fail("OpenSCManagerW")
    try:
        handle = _a32.OpenServiceW(scm, name, _SERVICE_QUERY_CONFIG | _READ_CONTROL)
        if not handle:
            err = ctypes.get_last_error()
            if err == _ERROR_SERVICE_DOES_NOT_EXIST:
                raise DeploymentIdentityUnavailable(
                    f"service {name} does not exist; there is no deployment to identify")
            _fail(f"OpenServiceW({name})", err)
        try:
            needed = W.DWORD(0)
            _a32.QueryServiceConfigW(handle, None, 0, ctypes.byref(needed))
            if not needed.value:
                _fail("QueryServiceConfigW(size)")
            buf = ctypes.create_string_buffer(needed.value)
            if not _a32.QueryServiceConfigW(handle, buf, needed, ctypes.byref(needed)):
                _fail("QueryServiceConfigW")
            config = ctypes.cast(buf, ctypes.POINTER(_QUERY_SERVICE_CONFIGW)).contents
            image_path = config.lpBinaryPathName
            account = config.lpServiceStartName
            if not image_path or not account:
                raise DeploymentIdentityUnavailable(
                    f"service {name} reports no ImagePath/account; fail closed")
            start_type = _START_TYPES.get(int(config.dwStartType))
            if start_type is None:
                raise DeploymentIdentityUnavailable(
                    f"service {name} has an unrecognised start type "
                    f"{config.dwStartType}; fail closed")

            sid_buf = _query_service_config2(
                handle, _SERVICE_CONFIG_SERVICE_SID_INFO, "SERVICE_SID_INFO")
            raw_sid_type = int.from_bytes(sid_buf.raw[:4], "little")
            sid_type = _SID_TYPES.get(raw_sid_type)
            if sid_type is None:
                raise DeploymentIdentityUnavailable(
                    f"service {name} reports an unrecognised SID type "
                    f"{raw_sid_type}; fail closed")

            # SERVICE_REQUIRED_PRIVILEGES_INFO is a pointer to a MULTI_SZ inside
            # the answer buffer, which must stay alive while it is read. The
            # privileges are a SET, so they are sorted: the order the SCM
            # happens to return them in is not part of what the deployment means.
            priv_buf = _query_service_config2(
                handle, _SERVICE_CONFIG_REQUIRED_PRIVILEGES_INFO,
                "REQUIRED_PRIVILEGES_INFO")
            privileges = _read_multi_sz(
                ctypes.cast(priv_buf,
                            ctypes.POINTER(_SERVICE_REQUIRED_PRIVILEGES_INFO)
                            ).contents.pmszRequiredPrivileges or 0)

            descriptor = canonical_security_descriptor(
                read_service_security_descriptor(handle))
            return ServiceIdentity(
                name=name, account=account, image_path=image_path,
                start_type=start_type, service_sid=service_sid(name),
                sid_type=sid_type, required_privileges=tuple(sorted(privileges)),
                security_descriptor=descriptor)
        finally:
            _a32.CloseServiceHandle(handle)
    finally:
        _a32.CloseServiceHandle(scm)


# ---------------------------------------------------------------------------
# The named-pipe policy, read from the DEPLOYED policy file
#
# The pipe itself only exists while the service runs, so what a provisioned
# deployment can be measured against is the policy the deployed trust package
# carries. Its bytes are already inside the manifest; here its SDDL is put
# through the SAME binary canonicalization as every other descriptor, so
# reformatting the string cannot cause drift and changing what it GRANTS must.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PipePolicyIdentity:
    schema_version: str
    name: str
    flags: tuple[str, ...]
    security_descriptor: SecurityDescriptorIdentity

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "name": self.name,
                "flags": list(self.flags),
                "security_descriptor": self.security_descriptor.to_dict()}


def canonical_sddl(sddl: str) -> SecurityDescriptorIdentity:
    """Canonicalize an SDDL string through the BINARY descriptor it denotes."""
    _require_windows("SDDL canonicalization")
    psd = ctypes.c_void_p()
    size = W.DWORD(0)
    if not _a32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(psd), ctypes.byref(size)):
        _fail("ConvertStringSecurityDescriptorToSecurityDescriptorW")
    try:
        return canonical_security_descriptor(ctypes.string_at(psd, size.value))
    finally:
        _k32.LocalFree(psd)


def observe_pipe_policy(root: Path) -> PipePolicyIdentity:
    """Read PIPE_POLICY.json from the deployed trust root."""
    policy_path = root / "PIPE_POLICY.json"
    try:
        raw = json.loads(policy_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DeploymentIdentityUnavailable(
            f"pipe policy {policy_path} is unreadable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise DeploymentIdentityUnavailable(
            f"pipe policy {policy_path} is malformed: {exc}") from exc
    if not isinstance(raw, dict):
        raise DeploymentIdentityUnavailable(f"pipe policy {policy_path} is not an object")
    schema_version = raw.get("schema_version")
    name = raw.get("name")
    sddl = raw.get("sddl")
    flags = raw.get("flags")
    if not isinstance(schema_version, str) or not schema_version:
        raise DeploymentIdentityUnavailable("pipe policy has no schema_version; fail closed")
    if not isinstance(name, str) or not name:
        raise DeploymentIdentityUnavailable("pipe policy has no pipe name; fail closed")
    if not isinstance(sddl, str) or not sddl:
        raise DeploymentIdentityUnavailable("pipe policy has no SDDL; fail closed")
    if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
        raise DeploymentIdentityUnavailable("pipe policy flags are malformed; fail closed")
    return PipePolicyIdentity(schema_version=schema_version, name=name,
                              flags=tuple(sorted(flags)),
                              security_descriptor=canonical_sddl(sddl))


# ---------------------------------------------------------------------------
# The deployment identity itself
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TrustPlaneDeploymentIdentity:
    """What is executed, what was measured, what gets bound into evidence.

    Every field is an OBSERVATION. Nothing a caller wished for reaches this
    structure, which is why `deployment_digest` measures reality: change the
    intention and the digest does not move; change the machine and it does.
    """

    schema: str
    package: TrustPackageManifest
    runtime: RuntimeIdentity
    service: ServiceIdentity
    trust_root: PathSecurityIdentity
    runidentity_store: PathSecurityIdentity
    anchorstore: PathSecurityIdentity
    pipe_policy: PipePolicyIdentity

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "package": self.package.to_dict(),
                "runtime": self.runtime.to_dict(), "service": self.service.to_dict(),
                "trust_root": self.trust_root.to_dict(),
                "runidentity_store": self.runidentity_store.to_dict(),
                "anchorstore": self.anchorstore.to_dict(),
                "pipe_policy": self.pipe_policy.to_dict()}

    def digest(self) -> str:
        """`deployment_digest` — the ONE canonical hash primitive (ADR-0004)
        over the whole observed identity. No competing implementation."""
        return hash_canonical(self.to_dict())


@dataclass(frozen=True)
class DesiredDeploymentConfig:
    """What provisioning INTENDS. Never a source of identity.

    It answers only "which objects should I go and look at" plus "what did we
    mean these to be", so that `compare_with_desired` can report drift. No
    field of it is ever copied into a `TrustPlaneDeploymentIdentity`; the
    serialize-the-config-and-call-it-a-deployment-digest shortcut is exactly
    what this separation exists to make impossible.
    """

    trust_root: Path
    runtime_executable: Path
    runidentity_store: Path
    anchorstore: Path
    service_name: str
    expected_package_version: str | None = None
    expected_service_account: str | None = None
    expected_sid_type: str | None = None
    expected_manifest: TrustPackageManifest | None = None


def observe_deployment(config: DesiredDeploymentConfig) -> TrustPlaneDeploymentIdentity:
    """Query the real system and build the authoritative identity.

    `config` supplies WHERE to look and nothing else. If an expected manifest
    is supplied it is verified AFTER measurement — against the actual bytes —
    so it can refuse a deployment, never define one.
    """
    _require_windows("deployment observation")
    package = observe_trust_package(config.trust_root)
    if config.expected_manifest is not None:
        verify_package_against_expected(package, config.expected_manifest)
    return TrustPlaneDeploymentIdentity(
        schema=DEPLOYMENT_SCHEMA,
        package=package,
        runtime=observe_runtime(config.runtime_executable),
        service=observe_service(config.service_name),
        trust_root=observe_path_security(config.trust_root),
        runidentity_store=observe_path_security(config.runidentity_store),
        anchorstore=observe_path_security(config.anchorstore),
        pipe_policy=observe_pipe_policy(config.trust_root))


def compare_with_desired(identity: TrustPlaneDeploymentIdentity,
                         config: DesiredDeploymentConfig) -> tuple[str, ...]:
    """Drift between what was OBSERVED and what was INTENDED.

    The only place a desired value is read at all. It returns findings; it does
    not touch the identity, and the identity does not depend on it.
    """
    drifts: list[str] = []
    if (config.expected_package_version is not None
            and identity.package.package_version != config.expected_package_version):
        drifts.append(
            f"package_version observed {identity.package.package_version!r}, "
            f"intended {config.expected_package_version!r}")
    if (config.expected_service_account is not None
            and identity.service.account != config.expected_service_account):
        drifts.append(f"service account observed {identity.service.account!r}, "
                      f"intended {config.expected_service_account!r}")
    if (config.expected_sid_type is not None
            and identity.service.sid_type != config.expected_sid_type):
        drifts.append(f"service SID type observed {identity.service.sid_type!r}, "
                      f"intended {config.expected_sid_type!r}")
    return tuple(drifts)
