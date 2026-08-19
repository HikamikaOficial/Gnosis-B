"""Git evidence capture.

Read-only: this module never mutates the target repository. It snapshots
git status, the current HEAD, branch, and a diff stat so a run's effect
on the tree is deterministically recorded evidence rather than an LLM's
claim about what it changed.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GitEvidence:
    is_repo: bool
    head_sha: str | None
    branch: str | None
    status_porcelain: str
    diff_stat: str
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_repo": self.is_repo, "head_sha": self.head_sha, "branch": self.branch,
            "status_porcelain": self.status_porcelain, "diff_stat": self.diff_stat, "ts": self.ts,
        }


def _run_git(repo_path: Path, args: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(repo_path), capture_output=True, text=True, timeout=30,
        )
        return proc.returncode, (proc.stdout or proc.stderr).strip()
    except FileNotFoundError:
        return 127, "git executable not found"


def capture_git_evidence(repo_path: Path) -> GitEvidence:
    code, _ = _run_git(repo_path, ["rev-parse", "--is-inside-work-tree"])
    if code != 0:
        return GitEvidence(is_repo=False, head_sha=None, branch=None, status_porcelain="", diff_stat="")

    _, head_sha = _run_git(repo_path, ["rev-parse", "HEAD"])
    _, branch = _run_git(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"])
    _, status = _run_git(repo_path, ["status", "--porcelain"])
    _, diff_stat = _run_git(repo_path, ["diff", "--stat"])

    return GitEvidence(
        is_repo=True,
        head_sha=head_sha if not head_sha.lower().startswith("fatal") else None,
        branch=branch,
        status_porcelain=status,
        diff_stat=diff_stat,
    )
