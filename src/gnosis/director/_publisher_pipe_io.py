"""Bounded-by-parent Windows pipe transport helper; no publication authority.

Only the parent builds the request and interprets the reply. Keeping blocking
Windows I/O in a disposable process lets timeout kill close every pipe handle
without abandoning a live native operation referencing freed Python buffers.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes as w


def main() -> int:
    endpoint, connect_ms, response_limit = sys.argv[1:]
    request = sys.stdin.buffer.read(513)
    if not request or len(request) > 512:
        return 2
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.WaitNamedPipeW.argtypes = (w.LPCWSTR, w.DWORD)
    kernel.WaitNamedPipeW.restype = w.BOOL
    kernel.CreateFileW.argtypes = (w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID,
                                  w.DWORD, w.DWORD, w.HANDLE)
    kernel.CreateFileW.restype = w.HANDLE
    kernel.WriteFile.argtypes = (w.HANDLE, w.LPCVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID)
    kernel.WriteFile.restype = w.BOOL
    kernel.ReadFile.argtypes = (w.HANDLE, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID)
    kernel.ReadFile.restype = w.BOOL
    kernel.CloseHandle.argtypes = (w.HANDLE,)
    kernel.CloseHandle.restype = w.BOOL
    if not kernel.WaitNamedPipeW(endpoint, int(connect_ms)):
        return 3
    # Matches the existing server WORKER_PIPE_ACCESS; GENERIC_WRITE would also
    # request FILE_CREATE_PIPE_INSTANCE, intentionally absent from its DACL.
    handle = kernel.CreateFileW(endpoint, 0x00120083, 0, None, 3, 0, None)
    if handle in (None, 0, ctypes.c_void_p(-1).value):
        return 4
    try:
        written = w.DWORD()
        if (not kernel.WriteFile(handle, request, len(request), ctypes.byref(written), None)
                or written.value != len(request)):
            return 5
        limit = int(response_limit) + 1
        buffer = ctypes.create_string_buffer(limit)
        received = w.DWORD()
        if not kernel.ReadFile(handle, buffer, limit, ctypes.byref(received), None):
            return 6
        sys.stdout.buffer.write(buffer.raw[:received.value])
        return 0
    finally:
        kernel.CloseHandle(handle)


if __name__ == "__main__":
    raise SystemExit(main())
