"""Validate the complete-tree Git for Windows input before provisioning.

This validates layout, not provenance: deployment must copy the entire input
tree and bind its observed manifest before exposing its cmd directory to Worker.
"""
from __future__ import annotations

import stat
from pathlib import Path


class GitPackageError(ValueError):
    pass


REQUIRED_FILES = (
    "cmd/git.exe", "mingw64/bin/git.exe", "usr/bin/sh.exe", "etc/gitconfig",
    "mingw64/libexec/git-core/git-remote-https.exe",
)


def git_package_entrypoint(root: Path) -> Path:
    root = Path(root)
    if (not root.is_absolute() or not root.is_dir()
            or root.is_symlink() or root.is_junction()):
        raise GitPackageError("Git package must be an ordinary absolute directory")
    for item in root.rglob("*"):
        if item.is_symlink() or item.is_junction():
            raise GitPackageError("Git package contains a redirected path")
    for relative in REQUIRED_FILES:
        path = root / relative
        try:
            info = path.stat()
        except OSError as exc:
            raise GitPackageError(f"Git package lacks required file: {relative}") from exc
        if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
            raise GitPackageError(f"Git package has an invalid required file: {relative}")
    return root / "cmd" / "git.exe"
