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
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

MECHANISM = "CreateFileW(GENERIC_READ, FILE_SHARE_READ)"

_IS_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class LockOutcome:
    """Whether the covered inputs were actually made unwritable."""

    enforced: bool
    locked: int
    refused: tuple[str, ...]
    mechanism: str
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "enforced": self.enforced,
            "locked_inputs": self.locked,
            "refused": list(self.refused),
            "mechanism": self.mechanism,
            "reason": self.reason,
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
        return LockOutcome(False, 0, tuple(paths), self.mechanism, self.reason)

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
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    _kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL

    @dataclass
    class WindowsInputLock:
        """One read handle per covered file, held for the whole run."""

        root: Path
        _handles: list[int] = field(default_factory=list)

        def acquire(self, paths: Sequence[str]) -> LockOutcome:
            refused: list[str] = []
            for relative in sorted(paths):
                target = self.root / relative
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

            if refused:
                # Fail closed, and say how many were fine: a reader needs
                # to know whether this is one locked file or a broken tree.
                return LockOutcome(
                    False, len(self._handles), tuple(refused), MECHANISM,
                    f"{len(refused)} covered input(s) could not be made unwritable; "
                    "another process holds them open for writing")
            return LockOutcome(True, len(self._handles), (), MECHANISM)

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
