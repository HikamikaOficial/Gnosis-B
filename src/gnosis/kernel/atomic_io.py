"""Corruption-resistant writes.

write-then-os.replace() is the standard technique for making a file write
atomic from the perspective of any reader: a reader always sees either the
fully-old content or the fully-new content, never a torn/partial write,
because os.replace() is a single filesystem rename operation on both
POSIX and Windows (same volume). This is what meta.json, heartbeat.json,
and result.json are written with, so a process killed mid-write can never
leave a run's canonical JSON state files corrupted.

WHAT IS AND IS NOT GUARANTEED (F-17 Stage 4 stated this precisely rather
than leaving it implied). The new content is flushed to the storage stack
(os.fsync -> FlushFileBuffers on Windows) BEFORE the replace, and the
replace itself is a single rename. So:

  process crash / service crash   GUARANTEED. A reader in any other
                                  process sees either the whole old file
                                  or the whole new one; a killed writer
                                  can leave a stray `.tmp-*` beside the
                                  target but never a half-written target.
  power loss / storage failure    BEST EFFORT, EXPLICITLY BOUNDED. The
                                  data is fsynced, but the rename's own
                                  metadata is not (Windows offers no
                                  directory fsync); NTFS journals it, which
                                  is not the same as a guarantee. Nothing
                                  here is power-loss proof and it is never
                                  claimed to be.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path


def _replace_with_retry(tmp_path: Path, path: Path) -> None:
    """os.replace, with the bounded Windows sharing-violation retry.

    Windows: antivirus/indexer services briefly open freshly written
    files, making os.replace fail with a transient sharing violation
    (WinError 32) — the recurring class documented as L-0002. Bounded
    retry: a file still held after ~1s is a real conflict and raises.
    """
    for attempt in range(20):
        try:
            os.replace(tmp_path, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
    with tmp_path.open("w", encoding=encoding) as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    _replace_with_retry(tmp_path, path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """The BYTE-EXACT sibling of atomic_write_text: same durability, same
    atomic replacement, no text-mode newline translation.

    Kept separate rather than folded into atomic_write_text, whose callers
    (meta.json, heartbeat.json, result.json) have written platform-native
    line endings since M1; re-encoding them through this path would silently
    change bytes those files' readers already have on disk. Required by
    F-17 Stage 4, whose watermark and hash-chained ledger prefix are exact
    byte sequences that a text-mode writer would rewrite.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
    with tmp_path.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    _replace_with_retry(tmp_path, path)
