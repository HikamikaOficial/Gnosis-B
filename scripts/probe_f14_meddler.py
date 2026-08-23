"""A separate process that mutates a covered file and outlives the capture.

Driven over stdin/stdout so every step is a real handshake on a pipe, not
a sleep. Protocol, one line each way:

    (on start)   <- READY
    -> OPEN      <- OPENED | OPEN-REFUSED <errno>
    -> MODIFY    <- MODIFIED <sha256-of-what-is-now-on-disk-as-seen-by-a-fresh-read>
    -> RESTORE   <- RESTORED <sha256>
    -> CLOSE     <- CLOSED

Two modes:

    handle  os.open + os.write, raw fd, no FlushFileBuffers, handle kept
            open across the whole capture
    mmap    a writable memory-mapped view, mutated through the view, no
            flush(), view kept alive across the whole capture
"""
from __future__ import annotations

import hashlib
import mmap
import os
import sys

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


if __name__ == "__main__":
    mode, target = sys.argv[1], sys.argv[2]
    if mode == "handle":
        run_handle(target)
    else:
        run_mmap(target)
