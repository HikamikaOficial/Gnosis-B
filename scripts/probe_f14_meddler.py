"""A separate process that mutates a covered file and outlives the capture.

Driven over stdin/stdout so every step is a real handshake on a pipe, not
a sleep. Protocol, one line each way:

    (on start)   <- READY
    -> OPEN      <- OPENED | OPEN-REFUSED <errno>
    -> MODIFY    <- MODIFIED <sha256-of-what-is-now-on-disk-as-seen-by-a-fresh-read>
    -> RESTORE   <- RESTORED <sha256>
    -> CLOSE     <- CLOSED

Modes:

    handle          os.open + os.write, raw fd, no FlushFileBuffers,
                    handle kept open across the whole capture
    mmap            a writable memory-mapped view, mutated through the
                    view, no flush(), kept alive across the capture
    section         CreateFileMapping + MapViewOfFile, then the FILE
                    handle is closed: only the mapping object and the
                    writable view remain
    section-orphan  as above, and the MAPPING handle is closed too: only
                    the view remains
    section-dup     as `section`, with a duplicate of the file handle
                    kept alive instead

The three section modes are the third review's reproduction A. They ask
whether a writable section with no ordinary file handle behind it still
blocks a GENERIC_READ / FILE_SHARE_READ open.
"""
from __future__ import annotations

import hashlib
import mmap
import os
import sys
from pathlib import Path

TAMPERED = b"TAMPERED-BY-AN-OPEN-HANDLE\n"


def digest(path: str) -> str:
    """A FRESH read, by a new handle: what any other reader would see."""
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def say(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def run_handle(path: str) -> None:
    say("READY")
    if sys.stdin.readline().strip() != "OPEN":
        return
    try:
        fd = os.open(path, os.O_RDWR | os.O_BINARY)
    except OSError as exc:
        say(f"OPEN-REFUSED {type(exc).__name__} {exc.errno}")
        return
    original = os.read(fd, 1 << 20)
    say("OPENED")
    while True:
        line = sys.stdin.readline().strip()
        if line == "MODIFY":
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, TAMPERED)
            os.ftruncate(fd, len(TAMPERED))
            say(f"MODIFIED {digest(path)}")
        elif line == "RESTORE":
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, original)
            os.ftruncate(fd, len(original))
            say(f"RESTORED {digest(path)}")
        elif line == "CLOSE":
            os.close(fd)
            say(f"CLOSED {digest(path)}")
            return
        elif not line:
            return


def run_mmap(path: str) -> None:
    say("READY")
    if sys.stdin.readline().strip() != "OPEN":
        return
    try:
        handle = open(path, "r+b")  # noqa: SIM115 - must outlive the capture
    except OSError as exc:
        say(f"OPEN-REFUSED {type(exc).__name__} {exc.errno}")
        return
    view = mmap.mmap(handle.fileno(), 0)
    original = bytes(view[:])
    payload = TAMPERED[:len(original)].ljust(len(original), b".")
    say("OPENED")
    while True:
        line = sys.stdin.readline().strip()
        if line == "MODIFY":
            view[:] = payload
            say(f"MODIFIED {digest(path)}")
        elif line == "RESTORE":
            view[:] = original
            say(f"RESTORED {digest(path)}")
        elif line == "CLOSE":
            view.flush()
            view.close()
            handle.close()
            say(f"CLOSED {digest(path)}")
            return
        elif not line:
            return


def run_section(path: str, mode: str) -> None:
    """A writable section whose file handle is gone before anyone asks."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileMappingW.argtypes = (wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                       wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR)
    k32.CreateFileMappingW.restype = wintypes.HANDLE
    k32.MapViewOfFile.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.DWORD, ctypes.c_size_t)
    k32.MapViewOfFile.restype = wintypes.LPVOID
    k32.UnmapViewOfFile.argtypes = (wintypes.LPVOID,)
    k32.FlushViewOfFile.argtypes = (wintypes.LPVOID, ctypes.c_size_t)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    k32.DuplicateHandle.argtypes = (wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                    ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                    wintypes.BOOL, wintypes.DWORD)
    k32.GetCurrentProcess.restype = wintypes.HANDLE

    say("READY")
    if sys.stdin.readline().strip() != "OPEN":
        return
    invalid = ctypes.c_void_p(-1).value
    file_handle = k32.CreateFileW(path, 0x80000000 | 0x40000000, 7, None, 3, 0x80, None)
    if not file_handle or file_handle == invalid:
        say(f"OPEN-REFUSED CreateFileW {ctypes.get_last_error()}")
        return
    mapping = k32.CreateFileMappingW(file_handle, None, 0x04, 0, 0, None)
    if not mapping:
        say(f"OPEN-REFUSED CreateFileMapping {ctypes.get_last_error()}")
        return
    view = k32.MapViewOfFile(mapping, 0x0002, 0, 0, 0)
    if not view:
        say(f"OPEN-REFUSED MapViewOfFile {ctypes.get_last_error()}")
        return
    original = ctypes.string_at(view, len(Path(path).read_bytes()))
    duplicate = wintypes.HANDLE()
    if mode == "section-dup":
        k32.DuplicateHandle(k32.GetCurrentProcess(), file_handle,
                            k32.GetCurrentProcess(), ctypes.byref(duplicate),
                            0, False, 0x00000002)
    k32.CloseHandle(file_handle)
    if mode == "section-orphan":
        k32.CloseHandle(mapping)
    say("OPENED")
    while True:
        line = sys.stdin.readline().strip()
        if line == "MODIFY":
            ctypes.memmove(view, b"TAMPERED", 8)
            say(f"MODIFIED {digest(path)}")
        elif line == "RESTORE":
            ctypes.memmove(view, original, len(original))
            say(f"RESTORED {digest(path)}")
        elif line == "CLOSE":
            k32.FlushViewOfFile(view, 0)
            k32.UnmapViewOfFile(view)
            say(f"CLOSED {digest(path)}")
            return
        elif not line:
            return


if __name__ == "__main__":
    mode, target = sys.argv[1], sys.argv[2]
    if mode == "handle":
        run_handle(target)
    elif mode.startswith("section"):
        run_section(target, mode)
    else:
        run_mmap(target)
