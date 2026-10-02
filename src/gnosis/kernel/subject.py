"""Byte identity and a disposable, standalone Git copy of a reviewed subject.

This is an endpoint comparison, NOT an interval/boundary verdict. Publication
still requires the existing locked, observed evidence capture on the copy.
All files (including ignored inputs) are included; unsupported links, streams,
nested repositories and oversized subjects fail closed. The source is read-only.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import hash_canonical
from .input_lock import stream_inventory

MAX_FILES = 100_000
MAX_BYTES = 2 * 1024**3
_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")


class SubjectUnavailable(RuntimeError):
    """The reviewed bytes cannot be established or faithfully copied."""


@dataclass(frozen=True)
class SubjectIdentity:
    head_sha: str
    files: tuple[tuple[str, str], ...]
    directories: tuple[str, ...]
    executable_files: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"head_sha": self.head_sha, "files": dict(self.files),
                "directories": list(self.directories),
                "executable_files": list(self.executable_files)}

    def digest(self) -> str:
        return hash_canonical(self.to_dict())


def _git(root: Path, *args: str, trusted_repository: Path | None = None) -> str:
    # No inherited GIT_DIR/worktree/config/transport override may select another
    # repository. Local repository config remains observable by F-17 later.
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    # Subject roots cross the Director/Worker ownership boundary deliberately.
    # Keep global/system configuration excluded; authorize only this operation's
    # explicit repository, never an inherited safe.directory or wildcard.
    assigned = (trusted_repository if trusted_repository is not None else root).absolute()
    for parent in (assigned, *assigned.parents):
        if not stat.S_ISDIR(_plain(parent).st_mode):
            raise SubjectUnavailable("Git subject root is not a plain directory")
    command = ["git", "-c", "safe.directory=", "-c",
               "safe.directory=" + assigned.as_posix(), *args]
    try:
        result = subprocess.run(command, cwd=root, env=env,
                                capture_output=True, text=True, encoding="utf-8",
                                errors="strict", timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise SubjectUnavailable(f"subject Git observation failed: {type(exc).__name__}") from exc
    if result.returncode:
        raise SubjectUnavailable(f"subject Git operation failed (exit {result.returncode})")
    return result.stdout.strip()


def _plain(path: Path) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise SubjectUnavailable(f"linked/reparse subject path is unsupported: {path}")
    return info


def observe_subject(root: Path) -> SubjectIdentity:
    """Hash real bytes, rather than Git's status/diff-stat or binary-diff summary."""
    root = root.absolute()
    try:
        for parent in (root, *root.parents):
            if not stat.S_ISDIR(_plain(parent).st_mode):
                raise SubjectUnavailable("subject root is not a plain directory")
        top = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
        if top != root.resolve():
            raise SubjectUnavailable("subject must be a Git worktree root")
        head = _git(root, "rev-parse", "HEAD")
        if not _SHA.fullmatch(head):
            raise SubjectUnavailable("subject has no valid HEAD")
        files: list[tuple[str, str]] = []
        directories: list[str] = []
        executable: list[str] = []
        total = 0

        def fail_walk(exc: OSError) -> None:
            raise exc

        for base, dirs, names in os.walk(root, followlinks=False, onerror=fail_walk):
            parent_path = Path(base)
            if parent_path == root:
                dirs[:] = [d for d in dirs if d.casefold() != ".git"]
                names = [n for n in names if n.casefold() != ".git"]
            elif any(n.casefold() == ".git" for n in (*dirs, *names)):
                raise SubjectUnavailable("nested repositories/submodules are unsupported")
            for name in dirs:
                child = parent_path / name
                if not stat.S_ISDIR(_plain(child).st_mode):
                    raise SubjectUnavailable(f"non-directory subject entry: {child}")
                directories.append(child.relative_to(root).as_posix())
                if len(directories) > MAX_FILES:
                    raise SubjectUnavailable("subject exceeds bounded directory limit")
            for name in names:
                child = parent_path / name
                info = _plain(child)
                if not stat.S_ISREG(info.st_mode):
                    raise SubjectUnavailable(f"non-regular subject input: {child}")
                total += info.st_size
                if len(files) >= MAX_FILES or total > MAX_BYTES:
                    raise SubjectUnavailable("subject exceeds bounded proof-copy limits")
                digest = hashlib.sha256()
                read_size = 0
                with child.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1 << 20), b""):
                        read_size += len(chunk)
                        if read_size > info.st_size:
                            raise SubjectUnavailable("subject changed while being read")
                        digest.update(chunk)
                after = child.lstat()
                if (read_size != info.st_size or info.st_mtime_ns != after.st_mtime_ns
                        or info.st_ino != after.st_ino or info.st_mode != after.st_mode):
                    raise SubjectUnavailable("subject changed while being read")
                relative = child.relative_to(root).as_posix()
                files.append((relative, digest.hexdigest()))
                if os.name != "nt" and info.st_mode & 0o111:
                    executable.append(relative)
        streams, failures = stream_inventory(root, [p for p, _ in files], directories)
        if streams or failures:
            raise SubjectUnavailable("named streams or unobservable streams cannot be copied")
        if _git(root, "rev-parse", "HEAD") != head:
            raise SubjectUnavailable("subject HEAD changed during observation")
        return SubjectIdentity(head, tuple(sorted(files)), tuple(sorted(directories)),
                               tuple(sorted(executable)))
    except OSError as exc:
        raise SubjectUnavailable(f"subject could not be read: {type(exc).__name__}") from exc


def copy_subject(source: Path, destination: Path, expected: SubjectIdentity) -> Path:
    """Preserve source HEAD/history with independent objects, then copy exact bytes.

    No checkout/filter/hook is run, and no source index, config, hook or alternates
    is copied. The copy's index is HEAD's index; staged/unstaged distinctions are
    not transferred. The proof binds the actual filesystem content and re-runs
    verification there. Failed copies are retained for diagnosis, never reused.
    """
    source, destination = source.absolute(), destination.absolute()
    if (destination == source or source in destination.parents
            or destination in source.parents):
        raise SubjectUnavailable("proof copy must be outside the source tree")
    if destination.exists():
        raise SubjectUnavailable("proof copy already exists; refusing overwrite")
    if observe_subject(source) != expected:
        raise SubjectUnavailable("reviewed subject changed before proof copy")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _git(destination.parent, "clone", "--no-checkout", "--no-local", "--no-hardlinks",
         "--template=", "--", str(source), str(destination), trusted_repository=source)
    _git(destination, "update-ref", "HEAD", expected.head_sha)
    _git(destination, "read-tree", expected.head_sha)
    try:
        for relative in expected.directories:
            (destination / relative).mkdir(parents=True, exist_ok=True)
        for relative, _ in expected.files:
            origin = source / relative
            _plain(origin)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target, follow_symlinks=False)
    except OSError as exc:
        raise SubjectUnavailable(f"proof copy failed: {type(exc).__name__}") from exc
    if observe_subject(source) != expected or observe_subject(destination) != expected:
        raise SubjectUnavailable("proof copy differs from reviewed subject")
    return destination
