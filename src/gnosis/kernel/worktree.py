"""Isolated Git worktree primitives.

Gives a task/run its own checked-out working directory, on its own
branch, without touching the source repo's own working tree. This is the
*primitive* only, no parallel scheduling is wired on top of it (deferred
to a later milestone per Director decision: run state is not yet safe for
concurrent multi-task execution).

`source_repo` must be a repository Gnosis owns/operates on. Never point a
WorktreeManager at a read-only reference corpus: `create()`/`remove()`
both run `git` commands against `source_repo`, which is exactly the kind
of mutation a reference corpus must never receive.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .git_evidence import GitEvidence, capture_git_evidence


class WorktreeError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorktreeHandle:
    task_id: str
    run_id: Optional[str]
    source_repo: str
    path: str
    branch: str
    created_at: str

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id, "run_id": self.run_id, "source_repo": self.source_repo,
            "path": self.path, "branch": self.branch, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorktreeHandle":
        return cls(**data)


def _run_git(cwd: Path, args: list[str], timeout_s: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout_s)


class WorktreeManager:
    """Creates/tracks/cleans up isolated worktrees under `worktrees_root`,
    each checked out from `source_repo` on its own `gnosis/<task_id>`
    branch."""

    def __init__(self, source_repo: Path, worktrees_root: Path):
        self.source_repo = Path(source_repo)
        self.worktrees_root = Path(worktrees_root)
        self.worktrees_root.mkdir(parents=True, exist_ok=True)

    def create(self, task_id: str, run_id: Optional[str] = None, base_ref: str = "HEAD") -> WorktreeHandle:
        evidence = capture_git_evidence(self.source_repo)
        if not evidence.is_repo:
            raise WorktreeError(f"{self.source_repo} is not a git repository")

        branch = f"gnosis/{task_id}"
        target = self.worktrees_root / task_id
        if target.exists():
            raise WorktreeError(f"Worktree path already exists: {target}")

        proc = _run_git(self.source_repo, ["worktree", "add", "-b", branch, str(target), base_ref])
        if proc.returncode != 0:
            raise WorktreeError(f"git worktree add failed: {proc.stderr.strip()}")

        handle = WorktreeHandle(
            task_id=task_id, run_id=run_id, source_repo=str(self.source_repo),
            path=str(target), branch=branch,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        # The handle marker lives *outside* the checked-out tree
        # (worktrees_root/<task_id>.json), not inside it, so writing it
        # never makes git consider a freshly-created worktree "dirty".
        self._handle_marker(task_id).write_text(
            json.dumps(handle.to_dict(), indent=2, sort_keys=True), encoding="utf-8",
        )
        return handle

    def _handle_marker(self, task_id: str) -> Path:
        return self.worktrees_root / f".{task_id}.worktree.json"

    def evidence_for(self, handle: WorktreeHandle) -> GitEvidence:
        return capture_git_evidence(Path(handle.path))

    def remove(self, handle: WorktreeHandle, force: bool = False) -> None:
        """Cleans up a worktree. Fails (without force=True) if the
        worktree has uncommitted changes, so a caller mid-debugging or
        mid-recovery cannot lose evidence by accident; pass force=True
        once the caller has decided it is safe to discard."""
        args = ["worktree", "remove", str(handle.path)]
        if force:
            args.append("--force")
        proc = _run_git(self.source_repo, args)
        if proc.returncode != 0:
            raise WorktreeError(f"git worktree remove failed: {proc.stderr.strip()}")

    def prune(self) -> None:
        _run_git(self.source_repo, ["worktree", "prune"])

    def list_worktree_paths(self) -> list[Path]:
        if not self.worktrees_root.exists():
            return []
        return sorted(p for p in self.worktrees_root.iterdir() if p.is_dir())

    def load_handle(self, task_id: str) -> WorktreeHandle:
        marker = self._handle_marker(task_id)
        if not marker.exists():
            raise WorktreeError(f"No worktree handle found for task {task_id}")
        return WorktreeHandle.from_dict(json.loads(marker.read_text(encoding="utf-8")))
