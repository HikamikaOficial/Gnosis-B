"""Make the covered inputs unwritable for the duration of a capture.

The second independent review of ADR-0026 broke the observation-only
boundary and was right to. `ReadDirectoryChangesW` reports a write when
the write reaches the cache; a modification made through a **writable
memory-mapped view** need not report anything until the view is flushed
or unmapped. Reproduced: a covered file was mutated through a mapping, a
check read the mutated bytes, the bytes were restored, the view stayed
alive across the barrier, and the capture finished `evidence_valid: true`
with an empty violation list. No amount of extra watching fixes that,
because the notification the watcher is waiting for is never generated.

So the inputs stop being writable instead.

For every covered file the capture opens a handle with `GENERIC_READ`
and a share mode of `FILE_SHARE_READ` alone. While that handle is open
Windows refuses any other open that asks for write or delete access. The
consequences, all verified rather than assumed:

    another process reads the file          allowed
    another process writes the file         ERROR_SHARING_VIOLATION
    another process maps it writable        ERROR_SHARING_VIOLATION
    another process deletes it              ERROR_SHARING_VIOLATION
    another process renames it              ERROR_SHARING_VIOLATION
    another process changes its attributes  allowed, and notified

The mapping case is the one that matters: a writable section needs a
handle with write access, and there is no way to get one. The hole is
closed by refusing the operation, not by hoping to hear about it.

A third review asked the questions that decide whether the mechanism is
real, and the answers are measured rather than argued:

- **A live writable section with no file handle left.** A section keeps
  the underlying file object alive with the access it was created
  through, so the share-mode check still sees a writer. Verified in four
  shapes — file handle open; file handle closed; file handle AND mapping
  handle closed with only the view alive; a duplicated handle kept alive
  — and every one of them refuses the lock with ERROR_SHARING_VIOLATION.
  The capture then runs nothing.
- **Which object is being protected.** Every handle records its
  `FILE_ID_INFO` (volume serial plus 128-bit file id) and its final path,
  and a handle whose final path is not the path it was opened by is a
  refusal. A path substituted between the fingerprint and the lock cannot
  leave the capture protecting one object while the checks read another.
- **The volume.** These are local Windows filesystem semantics. A
  network redirector, or a filesystem that cannot answer
  `FILE_ID_INFO`, does not demonstrably provide them, so the boundary
  refuses to claim it does.

What this does NOT cover, stated rather than implied:

- **Paths that do not exist yet.** A file created during the run cannot
  be locked in advance. Creation, deletion and rename are directory-entry
  operations, which the write observer reports synchronously and which no
  cache can defer, so those stay the observer's job. The two mechanisms
  are complementary by construction: prevention where a notification can
  be withheld, observation where it cannot.
- **File attributes.** `chmod` still succeeds. It cannot grant write
  access while the share mode stands, and it is reported by the observer.
- **`.git` and ignored files**, which are not covered inputs.

If any covered file cannot be locked — because another process already
holds it open for writing — the boundary does not exist and the capture
refuses to run the checks at all. A partially protected tree is not a
protected tree, and finding out after a 19-minute suite is worse than
finding out before it.
"""
from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .canonical import hash_canonical

MECHANISM = "CreateFileW(GENERIC_READ, FILE_SHARE_READ)"

_IS_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class VolumeCapabilities:
    """Whether this volume demonstrably provides what the boundary needs.

    The share-mode refusal and `FILE_ID_INFO` are local Windows
    filesystem semantics. A network redirector may implement them
    partially, differently, or not at all, and a boundary that is only
    probably there is not one. Rather than extrapolate from a test run on
    a local NTFS volume, the capture asks the volume and refuses what it
    cannot demonstrate.
    """

    supported: bool
    drive_type: str
    filesystem: str
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "supported": self.supported,
            "drive_type": self.drive_type,
            "filesystem": self.filesystem,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LockOutcome:
    """Whether the covered inputs were actually made unwritable."""

    enforced: bool
    locked: int
    refused: tuple[str, ...]
    mechanism: str
    reason: str | None = None
    identities: Mapping[str, str] = field(default_factory=dict)
    volume: VolumeCapabilities | None = None

    @property
    def identity_digest(self) -> str:
        """One hash over every protected object, by path and by file id."""
        return hash_canonical(sorted(self.identities.items()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "enforced": self.enforced,
            "locked_inputs": self.locked,
            "refused": list(self.refused),
            "mechanism": self.mechanism,
            "reason": self.reason,
            "identified_objects": len(self.identities),
            "identity_digest": self.identity_digest,
            "volume": self.volume.to_dict() if self.volume is not None else None,
            "identity_note": (
                "every protected handle is recorded by FILE_ID_INFO (volume serial "
                "plus 128-bit file id) and verified to still resolve to the path it "
                "was opened by; the full map is input-identities.json in this bundle"
            ),
        }


class InputLock(Protocol):
    def acquire(self, paths: Sequence[str]) -> LockOutcome: ...

    def release(self) -> None: ...


@dataclass
class UnavailableLock:
    """No mechanism here. Says so; never claims the inputs are protected."""

    reason: str
    mechanism: str = "none"

    def acquire(self, paths: Sequence[str]) -> LockOutcome:
        return LockOutcome(False, 0, tuple(paths), self.mechanism, self.reason,
                           volume=VolumeCapabilities(False, "unknown", "unknown",
                                                     self.reason))

    def release(self) -> None:
        return None


if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _GENERIC_READ = 0x80000000
    _FILE_SHARE_READ = 0x00000001
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x00000080
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _FILE_ID_INFO_CLASS = 18
    _VOLUME_NAME_DOS = 0

    _DRIVE_TYPES = {0: "unknown", 1: "no-root-dir", 2: "removable", 3: "fixed",
                    4: "remote", 5: "cdrom", 6: "ramdisk"}
    # The boundary is demonstrated on a local volume whose filesystem can
    # answer FILE_ID_INFO. Anything else is refused rather than assumed.
    _SUPPORTED_DRIVE_TYPES = frozenset({"fixed"})
    _SUPPORTED_FILESYSTEMS = frozenset({"NTFS", "ReFS"})

    class _FileIdInfo(ctypes.Structure):
        _fields_ = (("VolumeSerialNumber", ctypes.c_ulonglong),
                    ("FileId", ctypes.c_ubyte * 16))

    _kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.GetFileAttributesW.argtypes = (wintypes.LPCWSTR,)
    _kernel32.GetFileAttributesW.restype = wintypes.DWORD
    _kernel32.GetFileInformationByHandleEx.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD)
    _kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    _kernel32.GetFinalPathNameByHandleW.argtypes = (
        wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
    _kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _kernel32.GetDriveTypeW.argtypes = (wintypes.LPCWSTR,)
    _kernel32.GetDriveTypeW.restype = wintypes.UINT
    _kernel32.GetVolumeInformationW.argtypes = (
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD, wintypes.LPVOID,
        wintypes.LPVOID, wintypes.LPVOID, wintypes.LPWSTR, wintypes.DWORD)
    _kernel32.GetVolumeInformationW.restype = wintypes.BOOL

    def _file_identity(handle: int) -> str | None:
        """VolumeSerialNumber + 128-bit FileId, as the reviewer asked for."""
        info = _FileIdInfo()
        ok = _kernel32.GetFileInformationByHandleEx(
            handle, _FILE_ID_INFO_CLASS, ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            return None
        return f"{info.VolumeSerialNumber:016x}:{bytes(info.FileId).hex()}"

    def _final_path(handle: int) -> str | None:
        needed = _kernel32.GetFinalPathNameByHandleW(handle, None, 0, _VOLUME_NAME_DOS)
        if needed == 0:
            return None
        buffer = ctypes.create_unicode_buffer(needed + 1)
        written = _kernel32.GetFinalPathNameByHandleW(
            handle, buffer, needed + 1, _VOLUME_NAME_DOS)
        if written == 0:
            return None
        return buffer.value

    def classify_volume(drive_type: str, filesystem: str) -> VolumeCapabilities:
        """The rule, separated from the syscalls so it can be tested.

        Deliberately a whitelist. A volume type nobody has demonstrated
        the boundary on is refused, which is the opposite of the usual
        instinct and the only version that cannot quietly be wrong.
        """
        if drive_type not in _SUPPORTED_DRIVE_TYPES:
            return VolumeCapabilities(
                False, drive_type, filesystem,
                f"drive type {drive_type!r} is not one the boundary has been "
                "demonstrated on; it is refused rather than assumed")
        if filesystem not in _SUPPORTED_FILESYSTEMS:
            return VolumeCapabilities(
                False, drive_type, filesystem,
                f"filesystem {filesystem!r} is not one that demonstrably answers "
                "FILE_ID_INFO with local share-mode semantics")
        return VolumeCapabilities(True, drive_type, filesystem)

    def probe_volume(path: Path) -> VolumeCapabilities:
        """Ask the volume whether it provides what the boundary relies on."""
        resolved = str(path.resolve())
        if resolved.startswith("\\\\"):
            return VolumeCapabilities(
                False, "remote", "unknown",
                "a UNC path is served by a network redirector, which does not "
                "demonstrably provide local share-mode or FILE_ID_INFO semantics")
        drive = Path(resolved).drive
        if not drive:
            return VolumeCapabilities(False, "unknown", "unknown",
                                      f"no volume could be derived from {resolved}")
        root = drive + "\\"
        drive_type = _DRIVE_TYPES.get(_kernel32.GetDriveTypeW(root), "unknown")
        name = ctypes.create_unicode_buffer(261)
        filesystem = ctypes.create_unicode_buffer(261)
        ok = _kernel32.GetVolumeInformationW(
            root, name, 261, None, None, None, filesystem, 261)
        found = filesystem.value if ok else "unknown"
        return classify_volume(drive_type, found)

    @dataclass
    class WindowsInputLock:
        """One read handle per covered file, held for the whole run."""

        root: Path
        # Injectable so a test can present a volume this machine does not
        # have. The refusal has to be testable somewhere other than on a
        # network share nobody in CI can mount.
        volume_probe: Callable[[Path], VolumeCapabilities] | None = None
        _handles: list[int] = field(default_factory=list)

        def acquire(self, paths: Sequence[str]) -> LockOutcome:
            probe = self.volume_probe or probe_volume
            volume = probe(self.root)
            if not volume.supported:
                return LockOutcome(False, 0, tuple(sorted(paths)), MECHANISM,
                                   volume.reason, volume=volume)

            refused: list[str] = []
            identities: dict[str, str] = {}
            for relative in sorted(paths):
                target = self.root / relative
                attributes = _kernel32.GetFileAttributesW(str(target))
                if (attributes != _INVALID_FILE_ATTRIBUTES
                        and attributes & _FILE_ATTRIBUTE_REPARSE_POINT):
                    # A reparse point is a redirection: what the lock holds
                    # and what a check opens need not be the same object,
                    # and this tree has never had one to reason about.
                    refused.append(f"{relative} (reparse point)")
                    continue
                handle = _kernel32.CreateFileW(
                    str(target), _GENERIC_READ, _FILE_SHARE_READ, None,
                    _OPEN_EXISTING, _FILE_ATTRIBUTE_NORMAL, None)
                if not handle or handle == _INVALID_HANDLE_VALUE:
                    error = ctypes.get_last_error()
                    if error == 2 or error == 3:
                        # ERROR_FILE_NOT_FOUND / ERROR_PATH_NOT_FOUND: a
                        # tracked file that is deleted in the working tree
                        # has nothing to protect and nothing to mutate.
                        continue
                    if error == 5:
                        # ERROR_ACCESS_DENIED on a directory-like entry
                        # (a submodule gitlink); retry with the flag that
                        # makes a directory openable, and record a refusal
                        # if even that fails.
                        handle = _kernel32.CreateFileW(
                            str(target), _GENERIC_READ, _FILE_SHARE_READ, None,
                            _OPEN_EXISTING, _FILE_FLAG_BACKUP_SEMANTICS, None)
                        if handle and handle != _INVALID_HANDLE_VALUE:
                            self._handles.append(handle)
                            continue
                    refused.append(f"{relative} (error {error})")
                    continue
                self._handles.append(handle)
                problem = self._identify(relative, target, handle, identities)
                if problem is not None:
                    refused.append(problem)

            if refused:
                # Fail closed, and say how many were fine: a reader needs
                # to know whether this is one locked file or a broken tree.
                return LockOutcome(
                    False, len(self._handles), tuple(refused), MECHANISM,
                    f"{len(refused)} covered input(s) could not be protected as "
                    "the objects the capture identified",
                    identities=identities, volume=volume)
            return LockOutcome(True, len(self._handles), (), MECHANISM,
                               identities=identities, volume=volume)

        @staticmethod
        def _identify(relative: str, target: Path, handle: int,
                      identities: dict[str, str]) -> str | None:
            """Record WHICH object was locked, and check it is still that path.

            Two different failures, both fatal. An identity that cannot be
            read means the filesystem does not support the guarantee being
            claimed. A final path that is not the path opened means the
            entry was substituted, and the capture would be protecting one
            object while the checks read another.
            """
            identity = _file_identity(handle)
            if identity is None:
                return f"{relative} (no FILE_ID_INFO)"
            final = _final_path(handle)
            if final is None:
                return f"{relative} (no final path)"
            expected = str(target.resolve())
            final = final.removeprefix("\\\\?\\")
            if final.lower() != expected.lower():
                return f"{relative} (path resolves to {final})"
            identities[relative] = identity
            return None

        def release(self) -> None:
            for handle in self._handles:
                _kernel32.CloseHandle(handle)
            self._handles.clear()


def create_input_lock(root: Path) -> InputLock:
    """The platform's input lock, or one that admits it is not there."""
    if _IS_WINDOWS:
        return WindowsInputLock(root)
    return UnavailableLock(
        f"no input lock on {sys.platform}: the share-mode boundary is a Windows "
        "mechanism, and POSIX advisory locks do not stop a writable mapping")
