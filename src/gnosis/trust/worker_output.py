"""Bounded reads of untrusted Worker files through a validated, locked handle.

Validate before reading: a Worker-controlled link must never cause the Director
to copy a privileged file into an output artifact. Windows is the production
platform. The Linux implementation supports component tests with the same
identity checks; unsupported platforms refuse the operation.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


class WorkerOutputUnavailable(OSError):
    pass


def retain_worker_output(destination: Path, data: bytes) -> None:
    """Durably create a protected output record without replacing prior evidence.

The destination is supplied by the trusted RunStore, never by Worker data.
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def read_worker_output(path: Path, *, limit: int) -> bytes:
    """Read an ordinary, single-link file at exactly its lexical absolute path.

On Windows the handle denies concurrent writers and deletion for the complete
validation/read interval. No path reopen occurs after validation. Oversize files
are refused; this function never silently truncates evidence.
"""
    if type(limit) is not int or limit < 0:
        raise ValueError("output byte limit must be a nonnegative integer")
    expected = os.path.abspath(path)
    if sys.platform == "win32":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        from gnosis.trust.deployment import DeploymentIdentityUnavailable, _final_path

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        # READ, SHARE_READ only, OPEN_EXISTING, OPEN_REPARSE_POINT.
        handle = kernel.CreateFileW(expected, 0x80000000, 1, None, 3, 0x00200000, None)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise WorkerOutputUnavailable("cannot lock Worker output for reading")
        try:
            try:
                observed = _final_path(handle)
            except DeploymentIdentityUnavailable as exc:
                raise WorkerOutputUnavailable("Worker output path cannot be established") from exc
            if os.path.normcase(observed) != os.path.normcase(expected):
                raise WorkerOutputUnavailable("Worker output path was redirected")
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle(handle)
            raise
    elif sys.platform == "linux":
        fd = os.open(expected, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if os.readlink(f"/proc/self/fd/{fd}") != expected:
                raise WorkerOutputUnavailable("Worker output path was redirected")
        except BaseException:
            os.close(fd)
            raise
    else:
        raise WorkerOutputUnavailable("secure Worker output read is unsupported")
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or getattr(info, "st_file_attributes", 0) & 0x400):
            raise WorkerOutputUnavailable("Worker output is not an ordinary single-link file")
        if info.st_size > limit:
            raise WorkerOutputUnavailable("Worker output exceeds its byte bound")
        raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise WorkerOutputUnavailable("Worker output exceeds its byte bound")
        return raw
