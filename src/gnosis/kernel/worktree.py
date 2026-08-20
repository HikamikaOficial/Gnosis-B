"""Isolated Git worktree primitives with provenance-gated destruction.

Gives a task/run its own checked-out working directory, on its own
branch, without touching the source repo's own working tree. This is the
*primitive* only, no parallel scheduling is wired on top of it.

Directive 5 (docs/research/REFERENCE_REPOSITORY_FINDINGS.md §5) rules
implemented here:

- The kernel mints per-task worktrees/branches (`gnosis/<task_id>`) and
  records that provenance in a handle marker at creation time.
  **Destruction is gated on that provenance**: remove() refuses any
  handle whose marker is absent or disagrees with the handle — "did the
  kernel mint this" is checked, not assumed.
- **Creation is idempotent with reattach paths**: re-creating an intact
  worktree returns its existing handle; a marker whose directory is gone
  is reattached (on the surviving branch when one exists, so committed
  work is never lost); an existing branch without a marker is adopted,
  not deleted.
- **Non-empty unregistered directories are recoverable work, never
  deleted**: both create() and remove() hard-abort when a directory
  exists that git does not register as a worktree.
- **Autosave commits carry a reason tag and refuse conflict states**:
  autosave() tags `gnosis-autosave(<task_id>): <reason>` and refuses
  mid-merge/mid-rebase, unmerged paths, and leftover conflict markers —
  losing a recovery point beats poisoning the branch.
- **Resume state is hostile input**: task ids are shape-checked before
  any path/ref is built from them (no traversal, no ref injection);
  handle markers are cross-checked (branch = minted namespace, path
  under the manager's root, source repo match) before any destructive
  git action; corrupt state (present but wrong) raises a different error
  than absent state, and both are hard aborts.

`source_repo` must be a repository Gnosis owns/operates on. Never point a
WorktreeManager at a read-only reference corpus: `create()`/`remove()`
both run `git` commands against `source_repo`, which is exactly the kind
of mutation a reference corpus must never receive.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .git_evidence import GitEvidence, capture_git_evidence

BRANCH_PREFIX = "gnosis/"

# Task ids become path components and ref components; anything outside
# this shape is hostile input, rejected before any path or git ref is
# built from it.
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

# Conflict-marker shapes `git diff --check` reports; also used to scan
# untracked files (which no `git diff` variant inspects).
_CONFLICT_MARKER_RE = re.compile(r"^(?:<{7}|={7}|>{7})(?: |$)", re.MULTILINE)

# Destruction floor: branches the kernel will never auto-delete even if
# every other check were somehow passed.
_PROTECTED_BRANCHES = frozenset({"main", "master", "develop", "trunk"})


class WorktreeError(RuntimeError):
    pass


class WorktreeAbsentError(WorktreeError):
    """Expected state (marker/worktree) does not exist at all."""


class WorktreeCorruptStateError(WorktreeError):
    """State exists but is unparseable or fails cross-checks. Distinct
    from absence on purpose: absent state may be created fresh, corrupt
    state is a hard abort demanding a human/recovery decision."""


class WorktreeProvenanceError(WorktreeError):
    """Destruction refused: the kernel cannot prove it minted this."""


class WorktreeAutosaveRefusedError(WorktreeError):
    """Autosave refused to avoid poisoning the branch. Carries a machine-
    readable reason tag alongside the human message."""

    def __init__(self, reason_tag: str, detail: str):
        super().__init__(f"autosave refused [{reason_tag}]: {detail}")
        self.reason_tag = reason_tag


@dataclass(frozen=True)
class WorktreeHandle:
    task_id: str
    run_id: str | None
    source_repo: str
    path: str
    branch: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id, "run_id": self.run_id, "source_repo": self.source_repo,
            "path": self.path, "branch": self.branch, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorktreeHandle:
        return cls(**data)


def _run_git(cwd: Path, args: list[str], timeout_s: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout_s)


def _validate_task_id(task_id: str) -> None:
    if not _TASK_ID_RE.match(task_id):
        raise WorktreeError(
            f"Invalid task id {task_id!r}: must match {_TASK_ID_RE.pattern} "
            "(task ids become path and ref components; anything else is "
            "treated as hostile input)"
        )


class WorktreeManager:
    """Creates/tracks/cleans up isolated worktrees under `worktrees_root`,
    each checked out from `source_repo` on its own `gnosis/<task_id>`
    branch."""

    def __init__(self, source_repo: Path, worktrees_root: Path):
        self.source_repo = Path(source_repo)
        self.worktrees_root = Path(worktrees_root)
        self.worktrees_root.mkdir(parents=True, exist_ok=True)

    # -- creation (idempotent, with reattach paths) --------------------------

    def create(self, task_id: str, run_id: str | None = None, base_ref: str = "HEAD") -> WorktreeHandle:
        _validate_task_id(task_id)
        evidence = capture_git_evidence(self.source_repo)
        if not evidence.is_repo:
            raise WorktreeError(f"{self.source_repo} is not a git repository")

        branch = BRANCH_PREFIX + task_id
        target = self.worktrees_root / task_id
        marker = self._handle_marker(task_id)

        if marker.exists():
            handle = self.load_handle(task_id)  # validates as hostile input
            if target.exists():
                if self._is_registered_worktree(target):
                    return handle  # intact: idempotent no-op
                raise WorktreeCorruptStateError(
                    f"{target} exists but git does not register it as a worktree; "
                    "it may hold recoverable work and is never deleted "
                    "automatically — inspect or move it manually"
                )
            # Marker survives, directory is gone: reattach. Prune the stale
            # registration first, then re-add on the surviving branch (so
            # committed work is preserved) or freshly if the branch is gone.
            _run_git(self.source_repo, ["worktree", "prune"])
            self._worktree_add(target, branch, base_ref)
            return handle

        if target.exists():
            raise WorktreeCorruptStateError(
                f"{target} exists without a kernel handle marker (unregistered "
                "directory). It may hold recoverable work and is never deleted "
                "automatically — inspect or move it manually"
            )

        self._worktree_add(target, branch, base_ref)
        handle = WorktreeHandle(
            task_id=task_id, run_id=run_id, source_repo=str(self.source_repo),
            path=str(target), branch=branch,
            created_at=datetime.now(UTC).isoformat(),
        )
        # The handle marker lives *outside* the checked-out tree
        # (worktrees_root/.<task_id>.worktree.json), not inside it, so
        # writing it never makes git consider a fresh worktree "dirty".
        # It is the creation-time provenance record destruction is gated on.
        marker.write_text(
            json.dumps(handle.to_dict(), indent=2, sort_keys=True), encoding="utf-8",
        )
        return handle

    def _worktree_add(self, target: Path, branch: str, base_ref: str) -> None:
        if self._branch_exists(branch):
            # Adopt the surviving kernel-minted branch rather than deleting
            # or shadowing it: its commits are recoverable work.
            proc = _run_git(self.source_repo, ["worktree", "add", str(target), branch])
        else:
            proc = _run_git(self.source_repo, ["worktree", "add", "-b", branch, str(target), base_ref])
        if proc.returncode != 0:
            raise WorktreeError(f"git worktree add failed: {proc.stderr.strip()}")

    # -- resume-state loading (hostile input) ---------------------------------

    def load_handle(self, task_id: str) -> WorktreeHandle:
        _validate_task_id(task_id)
        marker = self._handle_marker(task_id)
        if not marker.exists():
            raise WorktreeAbsentError(f"No worktree handle found for task {task_id}")
        try:
            handle = WorktreeHandle.from_dict(json.loads(marker.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise WorktreeCorruptStateError(
                f"Handle marker for task {task_id} is unreadable: {exc}"
            ) from exc
        # Wrong-TYPED fields (task_id: 123, path: null) parse fine but must
        # classify as corrupt state, not leak as bare TypeErrors downstream.
        for field_name in ("task_id", "source_repo", "path", "branch", "created_at"):
            if not isinstance(getattr(handle, field_name), str):
                raise WorktreeCorruptStateError(
                    f"Handle marker for task {task_id}: field {field_name!r} "
                    "is not a string"
                )
        if handle.run_id is not None and not isinstance(handle.run_id, str):
            raise WorktreeCorruptStateError(
                f"Handle marker for task {task_id}: field 'run_id' is neither "
                "null nor a string"
            )
        self._validate_handle(handle, expected_task_id=task_id)
        return handle

    def _validate_handle(self, handle: WorktreeHandle, expected_task_id: str | None = None) -> None:
        """A handle is a resume/recovery header: validate it as hostile
        input before it is allowed anywhere near a destructive operation."""
        _validate_task_id(handle.task_id)
        if expected_task_id is not None and handle.task_id != expected_task_id:
            raise WorktreeCorruptStateError(
                f"Handle task_id {handle.task_id!r} does not match expected "
                f"{expected_task_id!r}"
            )
        expected_branch = BRANCH_PREFIX + handle.task_id
        if handle.branch != expected_branch:
            raise WorktreeCorruptStateError(
                f"Handle branch {handle.branch!r} is not the kernel-minted "
                f"{expected_branch!r}"
            )
        expected_path = (self.worktrees_root / handle.task_id).resolve()
        if Path(handle.path).resolve() != expected_path:
            raise WorktreeCorruptStateError(
                f"Handle path {handle.path!r} is not this manager's "
                f"{expected_path}"
            )
        if Path(handle.source_repo).resolve() != self.source_repo.resolve():
            raise WorktreeCorruptStateError(
                f"Handle source repo {handle.source_repo!r} is not this "
                f"manager's {self.source_repo}"
            )

    # -- destruction (provenance-gated) ---------------------------------------

    def remove(self, handle: WorktreeHandle, force: bool = False,
               delete_branch: bool = False, force_delete_branch: bool = False) -> None:
        """Cleans up a worktree the kernel can prove it minted.

        Two independent destruction decisions carry two independent flags
        (adversarial-review finding: one flag conflated them): ``force``
        only overrides the dirty-tree refusal (uncommitted files are
        discarded); ``force_delete_branch`` only escalates branch deletion
        to ``-D`` for unmerged history. Refuses entirely — regardless of
        either flag — when provenance cannot be proven: no marker
        (WorktreeProvenanceError), marker/handle mismatch
        (WorktreeCorruptStateError), or a directory git does not register
        as a worktree (recoverable work, never deleted).

        Destruction order is worktree → branch → marker, so the provenance
        record is the LAST thing destroyed: if branch deletion refuses,
        the marker survives and both a retry and create()'s reattach path
        keep working (adversarial-review finding: the old order orphaned
        the branch and dead-ended the retry)."""
        self._validate_handle(handle)
        marker = self._handle_marker(handle.task_id)
        if not marker.exists():
            raise WorktreeProvenanceError(
                f"Refusing to remove {handle.path}: no kernel handle marker — "
                "cannot prove the kernel minted this worktree"
            )
        recorded = self.load_handle(handle.task_id)
        if recorded != handle:
            raise WorktreeCorruptStateError(
                f"Refusing to remove {handle.path}: presented handle disagrees "
                "with the creation-time provenance record"
            )

        target = Path(handle.path)
        if target.exists():
            if not self._is_registered_worktree(target):
                raise WorktreeCorruptStateError(
                    f"Refusing to remove {target}: git does not register it as "
                    "a worktree; it may hold recoverable work"
                )
            args = ["worktree", "remove", str(target)]
            if force:
                args.append("--force")
            proc = _run_git(self.source_repo, args)
            if proc.returncode != 0:
                raise WorktreeError(f"git worktree remove failed: {proc.stderr.strip()}")
        else:
            # Directory already gone: idempotent removal — drop the stale
            # registration, then fall through to branch/marker cleanup.
            self._unregister_missing(target)

        if delete_branch:
            # May raise (unmerged without force_delete_branch, protected
            # floor...): the marker below is then deliberately left intact.
            self._delete_minted_branch(handle.branch, force=force_delete_branch)

        marker.unlink(missing_ok=True)

    def _unregister_missing(self, target: Path) -> None:
        """Drop the stale registration of a worktree whose directory is
        gone. Tries the targeted removal first; only falls back to the
        repo-global `git worktree prune` (which also sweeps OTHER missing
        worktrees — an accepted V1 collateral on this single-root
        workstation) when git refuses the targeted form."""
        proc = _run_git(self.source_repo, ["worktree", "remove", "--force", str(target)])
        if proc.returncode != 0 and self._is_registered_worktree(target):
            _run_git(self.source_repo, ["worktree", "prune"])

    def _delete_minted_branch(self, branch: str, force: bool) -> None:
        """Only branches the kernel minted may be auto-deleted, and never
        the protected floor or the source repo's current branch."""
        if not branch.startswith(BRANCH_PREFIX):
            raise WorktreeProvenanceError(
                f"Refusing to delete branch {branch!r}: outside the kernel's "
                f"{BRANCH_PREFIX!r} namespace"
            )
        if branch in _PROTECTED_BRANCHES:
            raise WorktreeProvenanceError(f"Refusing to delete protected branch {branch!r}")
        head = _run_git(self.source_repo, ["rev-parse", "--abbrev-ref", "HEAD"])
        if head.returncode == 0 and head.stdout.strip() == branch:
            raise WorktreeProvenanceError(
                f"Refusing to delete branch {branch!r}: it is the source "
                "repo's current branch"
            )
        proc = _run_git(self.source_repo, ["branch", "-d", branch])
        if proc.returncode != 0:
            if not force:
                raise WorktreeError(
                    f"git branch -d refused (unmerged work?): {proc.stderr.strip()} — "
                    "pass force_delete_branch=True only after deciding the "
                    "branch history is disposable"
                )
            proc = _run_git(self.source_repo, ["branch", "-D", branch])
            if proc.returncode != 0:
                raise WorktreeError(f"git branch -D failed: {proc.stderr.strip()}")

    # -- autosave (reason-tagged recovery points) ------------------------------

    def autosave(self, handle: WorktreeHandle, reason: str) -> str | None:
        """Commit all uncommitted work in the worktree as a recovery point,
        tagged `gnosis-autosave(<task_id>): <reason>`. Returns the commit
        sha, or None when there is nothing to commit.

        Refuses (WorktreeAutosaveRefusedError) mid-merge/mid-rebase states,
        unmerged paths, and leftover conflict markers: losing a recovery
        point beats poisoning the branch with a half-resolved state."""
        self._validate_handle(handle)
        target = Path(handle.path)
        if not target.exists():
            raise WorktreeAbsentError(f"Worktree directory {target} does not exist")
        if not self._is_registered_worktree(target):
            raise WorktreeCorruptStateError(
                f"{target} is not a git-registered worktree"
            )

        git_dir_proc = _run_git(target, ["rev-parse", "--git-dir"])
        if git_dir_proc.returncode != 0:
            raise WorktreeCorruptStateError(
                f"Cannot resolve git dir for {target}: {git_dir_proc.stderr.strip()}"
            )
        git_dir = Path(git_dir_proc.stdout.strip())
        if not git_dir.is_absolute():
            git_dir = (target / git_dir).resolve()
        for marker_name, tag in (("MERGE_HEAD", "mid-merge"),
                                 ("rebase-merge", "mid-rebase"),
                                 ("rebase-apply", "mid-rebase"),
                                 ("CHERRY_PICK_HEAD", "mid-cherry-pick"),
                                 ("REVERT_HEAD", "mid-revert"),
                                 ("BISECT_LOG", "mid-bisect")):
            if (git_dir / marker_name).exists():
                raise WorktreeAutosaveRefusedError(tag, f"{git_dir / marker_name} present")

        # A recovery point must land on the minted branch: a commit made on
        # a detached HEAD lands on no ref and becomes unreachable the
        # moment the worktree is removed (adversarial-review finding).
        head = _run_git(target, ["rev-parse", "--abbrev-ref", "HEAD"])
        if head.returncode != 0 or head.stdout.strip() != handle.branch:
            raise WorktreeAutosaveRefusedError(
                "off-branch",
                f"HEAD is {head.stdout.strip() or 'unresolvable'!r}, "
                f"not the minted {handle.branch!r}",
            )

        status = _run_git(target, ["status", "--porcelain"])
        if status.returncode != 0:
            raise WorktreeError(f"git status failed: {status.stderr.strip()}")
        lines = [line for line in status.stdout.splitlines() if line.strip()]
        if not lines:
            return None
        unmerged = [line for line in lines
                    if line[:2] in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}]
        if unmerged:
            raise WorktreeAutosaveRefusedError(
                "unmerged-paths", f"{len(unmerged)} unmerged path(s): {unmerged[:3]}"
            )
        # Conflict markers hide in three places `git add -A` would commit:
        # unstaged tracked changes (diff --check), STAGED tracked changes
        # (diff --cached --check — bare diff --check misses them once the
        # caller ran `git add`, the classic escape after `merge --quit`),
        # and untracked files, which no diff variant inspects at all
        # (adversarial-review finding, reproduced with committed markers).
        for args in (["diff", "--check"], ["diff", "--cached", "--check"]):
            check = _run_git(target, args)
            if "conflict marker" in check.stdout.lower():
                raise WorktreeAutosaveRefusedError(
                    "conflict-markers", check.stdout.strip()[:500]
                )
        for line in lines:
            if not line.startswith("??"):
                continue
            untracked = target / line[3:].strip().strip('"')
            if not untracked.is_file() or untracked.stat().st_size > 1_000_000:
                continue
            content = untracked.read_text(encoding="utf-8", errors="ignore")
            if _CONFLICT_MARKER_RE.search(content):
                raise WorktreeAutosaveRefusedError(
                    "conflict-markers",
                    f"untracked file {untracked.name} contains conflict markers",
                )

        clean_reason = " ".join(reason.split())[:200] or "unspecified"
        add = _run_git(target, ["add", "-A"])
        if add.returncode != 0:
            raise WorktreeError(f"git add failed: {add.stderr.strip()}")
        commit = _run_git(
            target, ["commit", "-m", f"gnosis-autosave({handle.task_id}): {clean_reason}"],
        )
        if commit.returncode != 0:
            raise WorktreeError(f"git commit failed: {commit.stderr.strip()}")
        sha = _run_git(target, ["rev-parse", "HEAD"])
        if sha.returncode != 0:
            raise WorktreeError(f"git rev-parse failed after autosave: {sha.stderr.strip()}")
        return sha.stdout.strip()

    # -- shared helpers --------------------------------------------------------

    def _handle_marker(self, task_id: str) -> Path:
        return self.worktrees_root / f".{task_id}.worktree.json"

    def _branch_exists(self, branch: str) -> bool:
        proc = _run_git(self.source_repo, ["rev-parse", "--verify", "--quiet",
                                           f"refs/heads/{branch}"])
        return proc.returncode == 0

    def _is_registered_worktree(self, target: Path) -> bool:
        proc = _run_git(self.source_repo, ["worktree", "list", "--porcelain"])
        if proc.returncode != 0:
            return False
        registered = {
            Path(line[len("worktree "):]).resolve()
            for line in proc.stdout.splitlines()
            if line.startswith("worktree ")
        }
        return target.resolve() in registered

    def evidence_for(self, handle: WorktreeHandle) -> GitEvidence:
        return capture_git_evidence(Path(handle.path))

    def prune(self) -> None:
        _run_git(self.source_repo, ["worktree", "prune"])

    def list_worktree_paths(self) -> list[Path]:
        if not self.worktrees_root.exists():
            return []
        return sorted(p for p in self.worktrees_root.iterdir() if p.is_dir())
