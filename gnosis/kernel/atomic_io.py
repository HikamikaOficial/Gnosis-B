"""Corruption-resistant writes.

write-then-os.replace() is the standard technique for making a file write
atomic from the perspective of any reader: a reader always sees either the
fully-old content or the fully-new content, never a torn/partial write,
because os.replace() is a single filesystem rename operation on both
POSIX and Windows (same volume). This is what meta.json, heartbeat.json,
and result.json are written with, so a process killed mid-write can never
leave a run's canonical JSON state files corrupted.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
    with tmp_path.open("w", encoding=encoding) as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, path)
