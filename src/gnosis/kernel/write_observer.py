"""Observe every write inside a directory, including the ones that undo themselves.

Two fingerprints taken at two instants prove that the tree was the same
at those two instants. They prove nothing about the interval between
them. A check that modifies a file, reads the modified bytes and then
restores the original bytes — and the original size, attributes and
timestamps — leaves both fingerprints identical and the claim "the tree
did not change during the run" false. That is a transient, or ABA,
change, and it is what the first independent review of ADR-0026
reproduced.

Nothing sampled can close that hole. Polling, `mtime`, `git status` and a
third fingerprint are all snapshots of a moment, and a transient change
lives between moments. The authority has to be a stream of the writes
themselves.

On Windows that stream is `ReadDirectoryChangesW`, watching the tree
recursively. The kernel queues a notification for every create, delete,
rename, size, attribute, security and last-write change under the
directory, from the moment the first read is issued. A write followed by
its own undo produces notifications for both; there is no window in which
a change happens and no record of it exists.

Two failure modes are treated as loudly as a violation, because a
mechanism that can silently go blind is worse than no mechanism:

- **Overflow.** If changes arrive faster than they are drained, the
  kernel drops the queue and reports a zero-length read. Events were
  lost, so the observation is INCOMPLETE and the capture must fail
  closed.
- **Undelivered tail.** The last write before the run ends may still be
  in flight. Waiting "long enough" is a timer, and a timer is the thing
  that was just proved insufficient. Instead `stop()` writes a barrier
  file into the watched tree and blocks until it OBSERVES that barrier.
  Notifications are delivered in order, so seeing the barrier proves
  every earlier change has already been delivered. If the barrier is
  never observed, the observation is incomplete and the capture fails
  closed.

The barrier is the one write this module makes. It lives in
`.gnosis-capture-barrier/`, is removed immediately, and is always
classified as an allowed path by the caller.

Stated limits: the mechanism is Windows-only, and on any other platform
`create_write_observer` returns an observer that reports itself
unavailable rather than one that reports nothing happened. Changes made
through a memory-mapped section may be reported when the section is
flushed rather than when the memory is written.
"""
from __future__ import annotations

import shutil
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

BARRIER_DIR = ".gnosis-capture-barrier"

_IS_WINDOWS = sys.platform == "win32"


@dataclass(frozen=True)
class WriteEvent:
    """One change, as the filesystem reported it."""

    action: str
    path: str  # relative to the watched root, forward slashes

    def to_dict(self) -> dict[str, str]:
        return {"action": self.action, "path": self.path}


@dataclass(frozen=True)
class Observation:
    """What the observer saw, and whether it can promise it saw everything.

    `complete` is the load-bearing field. `available and complete` is the
    only combination that licenses a caller to treat an empty `events`
    tuple as "nothing was written".
    """

    available: bool
    complete: bool
    events: tuple[WriteEvent, ...]
    mechanism: str
    reason: str | None = None

    @property
    def trustworthy(self) -> bool:
        return self.available and self.complete


class WriteObserver(Protocol):
    def start(self) -> None: ...

    def stop(self) -> Observation: ...


@dataclass
class UnavailableObserver:
    """No mechanism here. Says so; never says 'nothing happened'."""

    reason: str
    mechanism: str = "none"

    def start(self) -> None:
        return None

    def stop(self) -> Observation:
        return Observation(False, False, (), self.mechanism, self.reason)


MECHANISM = "ReadDirectoryChangesW(recursive)"

if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _FILE_LIST_DIRECTORY = 0x0001
    _FILE_SHARE_ALL = 0x0007
    _OPEN_EXISTING = 3
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_FLAG_OVERLAPPED = 0x40000000
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    # Everything that can constitute a write. ATTRIBUTES is in the list
    # because clearing a read-only bit in order to write is itself a
    # change worth seeing.
    _NOTIFY_ALL = 0x001 | 0x002 | 0x004 | 0x008 | 0x010 | 0x040 | 0x100

    _WAIT_OBJECT_0 = 0x00000000
    _INFINITE = 0xFFFFFFFF

    _ACTIONS = {1: "added", 2: "removed", 3: "modified",
                4: "renamed_from", 5: "renamed_to"}

    class _Overlapped(ctypes.Structure):
        _fields_ = (
            ("Internal", ctypes.c_void_p),
            ("InternalHigh", ctypes.c_void_p),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        )

    _kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CreateEventW.argtypes = (
        wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
    _kernel32.CreateEventW.restype = wintypes.HANDLE
    _kernel32.ReadDirectoryChangesW.argtypes = (
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.BOOL,
        wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID, wintypes.LPVOID)
    _kernel32.ReadDirectoryChangesW.restype = wintypes.BOOL
    _kernel32.GetOverlappedResult.argtypes = (
        wintypes.HANDLE, wintypes.LPVOID, wintypes.LPVOID, wintypes.BOOL)
    _kernel32.GetOverlappedResult.restype = wintypes.BOOL
    _kernel32.WaitForMultipleObjects.argtypes = (
        wintypes.DWORD, wintypes.LPVOID, wintypes.BOOL, wintypes.DWORD)
    _kernel32.WaitForMultipleObjects.restype = wintypes.DWORD
    _kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
    _kernel32.SetEvent.restype = wintypes.BOOL
    _kernel32.ResetEvent.argtypes = (wintypes.HANDLE,)
    _kernel32.ResetEvent.restype = wintypes.BOOL
    _kernel32.CancelIoEx.argtypes = (wintypes.HANDLE, wintypes.LPVOID)
    _kernel32.CancelIoEx.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL

    def _decode(buffer: bytes, length: int) -> list[tuple[int, str]]:
        """FILE_NOTIFY_INFORMATION records, walked by their own offsets."""
        out: list[tuple[int, str]] = []
        offset = 0
        while offset + 12 <= length:
            next_entry = int.from_bytes(buffer[offset:offset + 4], "little")
            action = int.from_bytes(buffer[offset + 4:offset + 8], "little")
            name_bytes = int.from_bytes(buffer[offset + 8:offset + 12], "little")
            start = offset + 12
            name = buffer[start:start + name_bytes].decode("utf-16-le", errors="replace")
            out.append((action, name))
            if next_entry == 0:
                break
            offset += next_entry
        return out

    class WindowsWriteObserver:
        """Every write under `root`, delivered as a stream, drained in order."""

        def __init__(self, root: Path, *, buffer_bytes: int = 1 << 20,
                     barrier_timeout_s: float = 30.0) -> None:
            self.root = root
            self._buffer_bytes = buffer_bytes
            self._barrier_timeout_s = barrier_timeout_s
            self._handle: int | None = None
            self._io_event: int | None = None
            self._stop_event: int | None = None
            self._buffer: ctypes.Array[ctypes.c_char] | None = None
            self._overlapped = _Overlapped()
            self._thread: threading.Thread | None = None
            self._events: list[WriteEvent] = []
            self._condition = threading.Condition()
            self._complete = True
            self._reason: str | None = None
            self._available = False

        # -- lifecycle ---------------------------------------------------

        def start(self) -> None:
            handle = _kernel32.CreateFileW(
                str(self.root), _FILE_LIST_DIRECTORY, _FILE_SHARE_ALL, None,
                _OPEN_EXISTING, _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OVERLAPPED, None)
            if not handle or handle == _INVALID_HANDLE_VALUE:
                self._reason = (f"could not open {self.root} for change notification: "
                                f"error {ctypes.get_last_error()}")
                return
            self._handle = handle
            self._io_event = _kernel32.CreateEventW(None, True, False, None)
            self._stop_event = _kernel32.CreateEventW(None, True, False, None)
            if not self._io_event or not self._stop_event:
                self._reason = f"could not create wait events: error {ctypes.get_last_error()}"
                self._close()
                return
            self._buffer = ctypes.create_string_buffer(self._buffer_bytes)
            self._overlapped.hEvent = self._io_event
            if not self._issue_read():
                self._reason = (f"ReadDirectoryChangesW refused to arm: "
                                f"error {ctypes.get_last_error()}")
                self._close()
                return
            self._available = True
            self._thread = threading.Thread(target=self._drain, name="write-observer",
                                            daemon=True)
            self._thread.start()

        def stop(self) -> Observation:
            if not self._available:
                return Observation(False, False, (), MECHANISM,
                                   self._reason or "the observer was never armed")
            saw_barrier = self._await_barrier()
            if self._stop_event is not None:
                _kernel32.SetEvent(self._stop_event)
            if self._handle is not None:
                _kernel32.CancelIoEx(self._handle, ctypes.byref(self._overlapped))
            if self._thread is not None:
                self._thread.join(timeout=10.0)
            self._close()

            with self._condition:
                events = tuple(self._events)
                complete = self._complete
                reason = self._reason
            if not saw_barrier:
                complete = False
                reason = reason or (
                    f"the delivery barrier was not observed within "
                    f"{self._barrier_timeout_s:g}s, so the tail of the change "
                    f"stream cannot be assumed delivered")
            return Observation(True, complete, events, MECHANISM, reason)

        # -- internals ---------------------------------------------------

        def _issue_read(self) -> bool:
            if self._handle is None or self._buffer is None or self._io_event is None:
                return False
            _kernel32.ResetEvent(self._io_event)
            return bool(_kernel32.ReadDirectoryChangesW(
                self._handle, ctypes.byref(self._buffer), self._buffer_bytes, True,
                _NOTIFY_ALL, None, ctypes.byref(self._overlapped), None))

        def _drain(self) -> None:
            if self._io_event is None or self._stop_event is None:
                return
            handles = (wintypes.HANDLE * 2)(
                wintypes.HANDLE(self._io_event), wintypes.HANDLE(self._stop_event))
            transferred = wintypes.DWORD()
            while True:
                which = _kernel32.WaitForMultipleObjects(
                    2, ctypes.byref(handles), False, _INFINITE)
                if which == _WAIT_OBJECT_0 + 1:
                    return
                if which != _WAIT_OBJECT_0:
                    self._fail(f"waiting on the change stream failed: {which}")
                    return
                if self._handle is None or self._buffer is None:
                    return
                ok = _kernel32.GetOverlappedResult(
                    self._handle, ctypes.byref(self._overlapped),
                    ctypes.byref(transferred), False)
                if not ok:
                    error = ctypes.get_last_error()
                    if error != 995:  # ERROR_OPERATION_ABORTED: this is `stop()`
                        self._fail(f"reading the change stream failed: error {error}")
                    return
                if transferred.value == 0:
                    # The kernel dropped the queue. Events were lost and no
                    # amount of later reading recovers them.
                    self._fail("the change buffer overflowed; events were lost")
                else:
                    self._record(bytes(self._buffer.raw[:transferred.value]))
                if not self._issue_read():
                    self._fail("ReadDirectoryChangesW could not be re-armed: "
                               f"error {ctypes.get_last_error()}")
                    return

        def _record(self, raw: bytes) -> None:
            decoded = [
                WriteEvent(_ACTIONS.get(action, f"action-{action}"),
                           name.replace("\\", "/"))
                for action, name in _decode(raw, len(raw))
            ]
            with self._condition:
                self._events.extend(decoded)
                self._condition.notify_all()

        def _fail(self, reason: str) -> None:
            with self._condition:
                self._complete = False
                self._reason = self._reason or reason
                self._condition.notify_all()

        def _await_barrier(self) -> bool:
            """Write a marker, then block until the stream delivers it.

            Ordering, not timing: a notification for the marker cannot
            arrive before the notifications for writes that happened
            earlier, so observing it proves the tail was delivered.
            """
            token = uuid.uuid4().hex
            barrier = self.root / BARRIER_DIR
            try:
                barrier.mkdir(parents=True, exist_ok=True)
                (barrier / f"{token}.barrier").write_text(token, encoding="utf-8")
            except OSError as exc:
                self._fail(f"the delivery barrier could not be written: {exc}")
                return False
            try:
                deadline = time.monotonic() + self._barrier_timeout_s
                with self._condition:
                    while not any(token in event.path for event in self._events):
                        if not self._complete:
                            return False
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            return False
                        self._condition.wait(remaining)
                return True
            finally:
                shutil.rmtree(barrier, ignore_errors=True)

        def _close(self) -> None:
            for handle in (self._handle, self._io_event, self._stop_event):
                if handle:
                    _kernel32.CloseHandle(handle)
            self._handle = None
            self._io_event = None
            self._stop_event = None


def create_write_observer(root: Path) -> WriteObserver:
    """The platform's write observer, or one that admits it is not there."""
    if _IS_WINDOWS:
        return WindowsWriteObserver(root)
    return UnavailableObserver(
        f"no write observer on {sys.platform}: ReadDirectoryChangesW is Windows-only, "
        "and no sampled substitute can see a change that undoes itself")
