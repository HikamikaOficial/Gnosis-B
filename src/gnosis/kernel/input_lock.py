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

An eighth review named what all of this still was not. A file id says
WHICH object; a lock says the object did not change while the checks
ran. Neither says WHAT the bytes were, and evidence that cannot be
re-derived from its own record is not durable. So every input is now
hashed — SHA-256, read through the very handle that holds it unwritable,
so the bytes hashed are provably the bytes the checks read — and the
manifest goes into the bundle. Path, size, timestamps, file id, git
status and the lock itself are all recorded, and none of them is the
identity.

A fifth review found the one path that escaped all of that. A covered
entry that is a DIRECTORY — a submodule gitlink is the realistic case —
made `CreateFileW` fail with `ERROR_ACCESS_DENIED`, and the code reopened
it with `FILE_FLAG_BACKUP_SEMANTICS`, appended the handle and skipped
identification entirely. That handle counted towards `locked_inputs`,
never appeared in `identities`, and the outcome could still say
`enforced: true` — contradicting this module's own published guarantee
that every protected handle is recorded by `FILE_ID_INFO`. A directory
handle also proves nothing about the bytes inside a submodule's working
tree, which is what a check would actually read.

Directory-like covered inputs are now refused before any open is
attempted, and the invariant is checked rather than assumed: an outcome
cannot be `enforced` unless every handle it holds is an object it can
name. Submodule support is not attempted; it is declined.

Every identified object is also required to live on the volume that was
probed, compared by the `VolumeSerialNumber` that comes back inside
`FILE_ID_INFO`. That is what keeps a reparse point in an ANCESTOR
directory — a junction or a mount point above the covered path, which the
per-path reparse check cannot see — from placing an input on a volume
whose semantics were never demonstrated.

A sixth review found that the per-path reparse check was looking at the
wrong thing. It asked whether the TARGET was a reparse point; it never
asked whether the PATH USED TO REACH IT could be redirected. Measured on
this machine, with the previous code:

    repo\\linked -> dirA          lock: enforced=True over dirA\\a.py
    rmdir linked; mklink /J linked dirB   -> succeeded WHILE the handle
                                             on dirA\\a.py was held
    read repo\\linked\\a.py       -> SWAPPED-B
    rmdir linked; mklink /J linked dirA   -> the tree looks untouched

The lock held the right object and the check read a different one,
because a junction is a directory entry and holding a handle on a file
underneath it protects the file, not the name. The volume serial does not
help: dirA and dirB are on the same NTFS volume and their objects carry
the same serial.

So the whole resolution chain has to be plain. Every directory component
between the repository root and a covered input is checked, the root's
own chain up to the drive is checked once, and a single reparse point
anywhere in either refuses the capture before a check runs. Junction
support is not attempted; it is declined, exactly as submodules are.

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
- **Any path reached through a junction, mount point or symlink.**
  Refused, not supported. Protecting one means protecting the resolution
  chain as well as the object, and that is a different architecture.
- **Submodules and any other directory-like covered entry.** Refused, not
  supported. Supporting one means locking and identifying the objects
  inside its working tree, and that has not been demonstrated.
- **A tracked path deleted from the working tree.** There is nothing to
  open and nothing to mutate; if it reappears during the run the write
  observer reports it, because the path is in the covered set.

If any covered file cannot be locked — because another process already
holds it open for writing — the boundary does not exist and the capture
refuses to run the checks at all. A partially protected tree is not a
protected tree, and finding out after a 19-minute suite is worse than
finding out before it.
"""
from __future__ import annotations

import hashlib
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
    content_digests: Mapping[str, str] = field(default_factory=dict)

    @property
    def identity_digest(self) -> str:
        """One hash over every protected object, by path and by file id."""
        return hash_canonical(sorted(self.identities.items()))

    @property
    def content_digest(self) -> str:
        """One hash over the BYTES of every protected input.

        Distinct from `identity_digest` on purpose. That one answers
        "which objects"; this one answers "which bytes", and only the
        second can be re-derived by a third party from the files.
        """
        return hash_canonical(sorted(self.content_digests.items()))

    @property
    def fully_bound(self) -> bool:
        """Every handle held has a content digest, not just a file id.

        The eighth review's invariant. `fully_identified` can be true
        while this is false, which is exactly the state it was in:
        covered, locked, identified by object, and byte-unknown.
        """
        return self.locked == len(self.content_digests)

    @property
    def fully_identified(self) -> bool:
        """Every handle held is an object this outcome can name.

        `locked_inputs` and `identified_objects` describe the same domain,
        so they have to agree. They did not once: a directory handle was
        counted as locked and never identified, and the outcome still said
        enforced. Consumers check this as well as the producer, because
        the two-readers lesson of ADR-0025 applies to a lock as much as to
        a verdict.
        """
        return self.locked == len(self.identities)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enforced": self.enforced,
            "locked_inputs": self.locked,
            "refused": list(self.refused),
            "mechanism": self.mechanism,
            "reason": self.reason,
            "identified_objects": len(self.identities),
            "fully_identified": self.fully_identified,
            "identity_digest": self.identity_digest,
            "byte_bound_inputs": len(self.content_digests),
            "fully_bound": self.fully_bound,
            "content_digest": self.content_digest,
            "volume": self.volume.to_dict() if self.volume is not None else None,
            "content_note": (
                "content_digest is SHA-256 over the bytes of every protected "
                "input, each read through the handle that holds it unwritable, so "
                "the bytes hashed are the bytes the checks read; the full map is "
                "input-manifest.json in this bundle. A file id is not a content "
                "identity and neither is a lock"
            ),
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

    def content_digests(self) -> dict[str, str]:
        return {}

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
    _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    _INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _FILE_ID_INFO_CLASS = 18
    _VOLUME_NAME_DOS = 0

    _DRIVE_TYPES = {0: "unknown", 1: "no-root-dir", 2: "removable", 3: "fixed",
                    4: "remote", 5: "cdrom", 6: "ramdisk"}
    # The demonstrated domain, and nothing wider. These two sets are the
    # extension point: a filesystem joins the second one when the whole
    # boundary has been RUN on a real volume of that kind, not when it
    # looks like it should work.
    #
    # ReFS was in this set and is not any more. It supports FILE_ID_INFO
    # and shares Windows' share-mode model, which is an argument, and the
    # fourth independent review pointed out that an argument is not a
    # demonstration: no ReFS volume exists on this machine, no probe has
    # ever run on one, and no evidence bundle contains the string. It is a
    # candidate for the set, recorded here so the path back is obvious,
    # and it is refused until someone runs the probe on a real one.
    _SUPPORTED_DRIVE_TYPES = frozenset({"fixed"})
    _SUPPORTED_FILESYSTEMS = frozenset({"NTFS"})
    # Filesystems that plausibly qualify and have not been demonstrated.
    # Listed to be refused with a reason, never to be accepted.
    _CANDIDATE_FILESYSTEMS = frozenset({"ReFS"})

    class _FileIdInfo(ctypes.Structure):
        _fields_ = (("VolumeSerialNumber", ctypes.c_ulonglong),
                    ("FileId", ctypes.c_ubyte * 16))

    _kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.ReadFile.argtypes = (wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                   wintypes.LPVOID, wintypes.LPVOID)
    _kernel32.ReadFile.restype = wintypes.BOOL
    _kernel32.SetFilePointerEx.argtypes = (wintypes.HANDLE, ctypes.c_longlong,
                                           wintypes.LPVOID, wintypes.DWORD)
    _kernel32.SetFilePointerEx.restype = wintypes.BOOL
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

    def _file_identity(handle: int) -> tuple[int, str] | None:
        """VolumeSerialNumber + 128-bit FileId, as the reviewer asked for.

        Returned split rather than formatted: the serial is compared
        against the probed volume, and a caller that only wants a label
        can join the two itself.
        """
        info = _FileIdInfo()
        ok = _kernel32.GetFileInformationByHandleEx(
            handle, _FILE_ID_INFO_CLASS, ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            return None
        return info.VolumeSerialNumber, bytes(info.FileId).hex()

    def volume_serial_of(path: Path) -> int | None:
        """The serial of the volume a directory actually lives on.

        Read from a handle rather than from the drive letter, so that a
        junction or mount point above a covered path cannot quietly move
        the input to another volume: every protected object must come back
        with this same number.
        """
        handle = _kernel32.CreateFileW(
            str(path), _GENERIC_READ, _FILE_SHARE_READ | 0x00000002 | 0x00000004,
            None, _OPEN_EXISTING, _FILE_FLAG_BACKUP_SEMANTICS, None)
        if not handle or handle == _INVALID_HANDLE_VALUE:
            return None
        try:
            identity = _file_identity(handle)
        finally:
            _kernel32.CloseHandle(handle)
        return None if identity is None else identity[0]

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
        if filesystem in _CANDIDATE_FILESYSTEMS:
            # Refused with its own reason: "nobody has run it there" is a
            # different fact from "it cannot work there", and an operator
            # who sees this knows what would change the answer.
            return VolumeCapabilities(
                False, drive_type, filesystem,
                f"filesystem {filesystem!r} is a candidate the boundary has NOT been "
                "demonstrated on; it is refused until the probe has been run on a "
                "real volume of that kind")
        if filesystem not in _SUPPORTED_FILESYSTEMS:
            return VolumeCapabilities(
                False, drive_type, filesystem,
                f"filesystem {filesystem!r} is not one that demonstrably answers "
                "FILE_ID_INFO with local share-mode semantics")
        return VolumeCapabilities(True, drive_type, filesystem)

    def reparse_in_chain(path: Path) -> str | None:
        """The first component of `path` that can redirect resolution.

        Walks from the drive down to `path` itself. An unreadable
        component counts as a redirection: a link that cannot be examined
        is not a link that can be trusted.
        """
        chain: list[Path] = []
        current = path
        while True:
            chain.append(current)
            if current.parent == current:
                break
            current = current.parent
        for component in reversed(chain):
            attributes = _kernel32.GetFileAttributesW(str(component))
            if attributes == _INVALID_FILE_ATTRIBUTES:
                return f"{component} (attributes unreadable)"
            if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                return f"{component} (reparse point)"
        return None

    def handle_digest(handle: int) -> str | None:
        """SHA-256 of a file, read through the handle that locks it.

        Reading by path would be a second open and a second object; this
        cannot be pointed anywhere else, because the handle IS the thing
        keeping the file unwritable.
        """
        if not _kernel32.SetFilePointerEx(handle, 0, None, 0):  # FILE_BEGIN
            return None
        digest = hashlib.sha256()
        buffer = ctypes.create_string_buffer(1 << 20)
        read = wintypes.DWORD()
        while True:
            if not _kernel32.ReadFile(handle, buffer, len(buffer),
                                      ctypes.byref(read), None):
                return None
            if read.value == 0:
                return digest.hexdigest()
            digest.update(buffer.raw[:read.value])

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
        # Same reason: this machine has one volume, so the cross-volume
        # refusal is only testable if the expected serial can be supplied.
        expected_serial: int | None = None
        _handles: list[int] = field(default_factory=list)
        _digests: dict[str, str] = field(default_factory=dict)

        def acquire(self, paths: Sequence[str]) -> LockOutcome:
            probe = self.volume_probe or probe_volume
            volume = probe(self.root)
            if not volume.supported:
                return LockOutcome(False, 0, tuple(sorted(paths)), MECHANISM,
                                   volume.reason, volume=volume)

            serial = (self.expected_serial if self.expected_serial is not None
                      else volume_serial_of(self.root))
            if serial is None:
                return LockOutcome(
                    False, 0, tuple(sorted(paths)), MECHANISM,
                    "the volume serial of the repository root could not be read, so "
                    "no input can be shown to live on the volume that was probed",
                    volume=volume)
            # Cached for the loop: re-probing the root once per covered
            # input turned a 0.5s acquisition into a 7s one.
            self.expected_serial = serial

            root_redirect = reparse_in_chain(self.root)
            if root_redirect is not None:
                # If the root is reached through a redirection, every
                # covered path inherits it and nothing below can be
                # trusted to resolve to the object that was locked.
                return LockOutcome(
                    False, 0, tuple(sorted(paths)), MECHANISM,
                    f"the repository root is reached through a redirection: "
                    f"{root_redirect}; the boundary does not protect a resolution "
                    "chain it does not own",
                    volume=volume)
            ancestors: dict[str, str | None] = {}

            refused: list[str] = []
            identities: dict[str, str] = {}
            # Counted from here, not from zero: a caller may acquire in
            # more than one call on the same lock, and the invariant is
            # about the handles THIS call opened against the objects THIS
            # call named.
            held_before = len(self._handles)
            for relative in sorted(paths):
                target = self.root / relative
                redirect = self._redirectable_ancestor(relative, ancestors)
                if redirect is not None:
                    refused.append(redirect)
                    continue
                attributes = _kernel32.GetFileAttributesW(str(target))
                if (attributes != _INVALID_FILE_ATTRIBUTES
                        and attributes & _FILE_ATTRIBUTE_REPARSE_POINT):
                    # A reparse point is a redirection: what the lock holds
                    # and what a check opens need not be the same object,
                    # and this tree has never had one to reason about.
                    refused.append(f"{relative} (reparse point)")
                    continue
                if (attributes != _INVALID_FILE_ATTRIBUTES
                        and attributes & _FILE_ATTRIBUTE_DIRECTORY):
                    # The fifth review's finding. This used to fall through
                    # to CreateFileW, fail with ERROR_ACCESS_DENIED, be
                    # reopened with FILE_FLAG_BACKUP_SEMANTICS, and be
                    # appended to the handle list WITHOUT being identified
                    # — a handle that counted as locked and could never be
                    # named. A submodule gitlink is the realistic case, and
                    # a handle on its directory says nothing about the
                    # bytes inside it that a check would read.
                    refused.append(
                        f"{relative} (directory-like covered input; submodule and "
                        "gitlink semantics are not demonstrated by this boundary)")
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
                    refused.append(f"{relative} (error {error})")
                    continue
                self._handles.append(handle)
                problem = self._identify(relative, target, handle, identities)
                if problem is not None:
                    refused.append(problem)

            unbound = (len(self._handles) - held_before) - len(self._digests)
            if unbound > 0:
                # The eighth review's invariant, at the producer: a
                # handle without a content digest is a locked object
                # whose bytes the evidence cannot state.
                refused.append(f"{unbound} protected handle(s) were never hashed")
            unidentified = (len(self._handles) - held_before) - len(identities)
            if unidentified > 0:
                # Unreachable through the branches above, and checked
                # anyway: this is the invariant the fifth review found
                # broken, so it is asserted where it can be seen rather
                # than argued for in a comment.
                refused.append(
                    f"{unidentified} protected handle(s) were never identified")

            if refused:
                # Fail closed, and say how many were fine: a reader needs
                # to know whether this is one locked file or a broken tree.
                return LockOutcome(
                    False, len(self._handles), tuple(refused), MECHANISM,
                    f"{len(refused)} covered input(s) could not be protected as "
                    "the objects the capture identified",
                    identities=identities, volume=volume,
                    content_digests=dict(self._digests))
            return LockOutcome(True, len(self._handles), (), MECHANISM,
                               identities=identities, volume=volume,
                               content_digests=dict(self._digests))

        def _redirectable_ancestor(self, relative: str,
                                   cache: dict[str, str | None]) -> str | None:
            """Refuse an input whose PATH can be pointed somewhere else.

            The sixth review's finding. Holding a handle on the object
            protects the object; it does not stop the junction above it
            from being removed and recreated against a different
            directory while a check reads the lexical path. Cached per
            directory: hundreds of covered inputs share a handful of
            ancestors.
            """
            current = self.root
            for part in relative.replace("\\", "/").split("/")[:-1]:
                current = current / part
                key = str(current).lower()
                if key not in cache:
                    attributes = _kernel32.GetFileAttributesW(str(current))
                    if attributes == _INVALID_FILE_ATTRIBUTES:
                        cache[key] = "attributes unreadable"
                    elif attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                        cache[key] = "reparse point"
                    else:
                        cache[key] = None
                problem = cache[key]
                if problem is not None:
                    return (f"{relative} (ancestor "
                            f"{current.relative_to(self.root).as_posix()} is a "
                            f"{problem}; the path used to reach this input can be "
                            "redirected while the object stays locked)")
            return None

        def _identify(self, relative: str, target: Path, handle: int,
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
            serial, file_id = identity
            expected_serial = self.expected_serial
            if expected_serial is None or serial != expected_serial:
                # A junction or mount point ABOVE this path can put it on
                # another volume, which the per-path reparse check cannot
                # see. The serial comes back inside FILE_ID_INFO, so the
                # object says which volume it is on and this compares it.
                return (f"{relative} (object is on volume {serial:016x}, not the "
                        f"probed volume {expected_serial:016x})"
                        if expected_serial is not None else
                        f"{relative} (the probed volume serial is unavailable)")
            final = _final_path(handle)
            if final is None:
                return f"{relative} (no final path)"
            expected = str(target.resolve())
            final = final.removeprefix("\\\\?\\")
            if final.lower() != expected.lower():
                return f"{relative} (path resolves to {final})"
            digest = handle_digest(handle)
            if digest is None:
                return f"{relative} (bytes could not be read for hashing)"
            identities[relative] = f"{serial:016x}:{file_id}"
            self._digests[relative] = digest
            return None

        def content_digests(self) -> dict[str, str]:
            """Path to SHA-256 for everything this lock is holding."""
            return dict(self._digests)

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
