"""Read-only source provenance checks for the maintenance installation entry."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class InstallSourceError(ValueError):
    pass


@dataclass(frozen=True)
class InstallSource:
    repository: Path
    commit: str
    tree: str


def inspect_install_source(repository: Path, *, expected_commit: str,
                           expected_tree: str) -> InstallSource:
    """Refuse wrong roots, changed snapshots and uncommitted installation input.

    This observes source provenance only. It does not approve a commit, verify
    Windows ACLs, or assert that the candidate passed acceptance tests.
    """
    if any(re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is None
           for value in (expected_commit, expected_tree)):
        raise InstallSourceError("expected source commit/tree must be full object IDs")
    root = Path(repository).resolve(strict=True)

    def git(*args: str) -> str:
        try:
            result = subprocess.run(["git", *args], cwd=root, capture_output=True,
                                    text=True, check=False, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise InstallSourceError("source observation unavailable") from exc
        if result.returncode:
            raise InstallSourceError("source Git observation failed")
        return result.stdout.strip()

    if Path(git("rev-parse", "--show-toplevel")).resolve() != root:
        raise InstallSourceError("installation source must be the repository root")
    commit = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    if commit != expected_commit or tree != expected_tree:
        raise InstallSourceError("installation source does not match the approved snapshot")
    if git("status", "--porcelain=v1", "--untracked-files=all"):
        raise InstallSourceError("installation source has uncommitted or untracked files")
    return InstallSource(root, commit, tree)
