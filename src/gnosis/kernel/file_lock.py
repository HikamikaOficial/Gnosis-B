"""Cross-platform advisory exclusive file lock (stdlib only).

This is the primitive that turns Gnosis's concurrency model into option
"B" from the M1 Director decision: rather than trying to build a general
cross-process concurrent-write coordination system, every mutable
resource (a run's ledger, a run's meta.json) has exactly one lock file,
and any writer, whatever process or thread it lives in, must hold that
lock for the duration of its read-modify-write cycle. Two writers can
never interleave; the second simply waits (bounded by timeout_s) or fails
loudly. This makes unsafe concurrent writes structurally impossible
rather than merely unlikely.

Wraps msvcrt.locking on Windows and fcntl.flock on POSIX behind one
interface. Both are per-(process, open-file-handle) region locks, so a
fresh handle opened by a second thread in the *same* process still
conflicts with a lock held by a first thread's handle, giving intra- and
inter-process serialization from a single mechanism.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import IO

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class LockTimeoutError(RuntimeError):
    pass


class FileLock:
    """Exclusive advisory lock on `path` (the file is created if missing).
    Blocking with a bounded poll timeout; never waits forever.

    One instance == one acquisition. Create a fresh FileLock for each
    critical section rather than sharing one instance across threads: a
    single instance holds at most one OS handle, so a second concurrent
    acquire() call on the *same* instance raises immediately instead of
    waiting its turn."""

    def __init__(self, path: Path, timeout_s: float = 30.0, poll_interval_s: float = 0.02):
        self.path = path
        self.timeout_s = timeout_s
        self.poll_interval_s = poll_interval_s
        self._fh: IO[bytes] | None = None

    def acquire(self) -> None:
        if self._fh is not None:
            raise RuntimeError(f"FileLock({self.path}) is already held by this instance")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_s
        fh = open(self.path, "a+b")
        while True:
            try:
                _lock_exclusive_nonblocking(fh)
                self._fh = fh
                return
            except OSError:
                if time.monotonic() >= deadline:
                    fh.close()
                    raise LockTimeoutError(
                        f"Could not acquire lock {self.path} within {self.timeout_s}s"
                    )
                time.sleep(self.poll_interval_s)

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            _unlock(self._fh)
        finally:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def _lock_exclusive_nonblocking(fh) -> None:
    if sys.platform == "win32":
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fh) -> None:
    if sys.platform == "win32":
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def lock_path_for(resource_path: Path) -> Path:
    return resource_path.with_name(resource_path.name + ".lock")
