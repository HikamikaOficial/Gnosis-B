"""Git evidence capture.

Read-only: this module never mutates the target repository. It snapshots
git status, the current HEAD, branch, and a diff stat so a run's effect
on the tree is deterministically recorded evidence rather than an LLM's
claim about what it changed.
"""
from __future__ import annotations

import base64
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .canonical import hash_canonical

_SHA_RE = re.compile(r"[0-9a-f]{40,64}\Z")


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
            ["git", *args], cwd=str(repo_path), capture_output=True, text=True,
            timeout=30, check=False,  # rc is returned and handled by callers
        )
        return proc.returncode, (proc.stdout or proc.stderr).strip()
    except FileNotFoundError:
        return 127, "git executable not found"
    except subprocess.TimeoutExpired:
        return 124, "git timed out"
    except OSError as exc:
        # Evidence capture is read-only and must fail closed as data, not
        # as an exception escaping a probe (convergence relies on this).
        return 126, f"git could not run: {exc}"


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
        # `git rev-parse HEAD` on a repo with no commits echoes the literal
        # string "HEAD" to stdout (the fatal goes to stderr), so a prefix
        # check alone recorded a bogus head. Only a real sha counts.
        head_sha=head_sha if _SHA_RE.fullmatch(head_sha) else None,
        branch=branch,
        status_porcelain=status,
        diff_stat=diff_stat,
    )


def content_fingerprint(path: Path) -> dict[str, Any]:
    """Tamper-detection fingerprint: does this tree hold the same BYTES?

    Status alone cannot answer this, and a fingerprint built on it
    silently could not either: a file already listed
    as ` M code.py` keeps that exact status line however many more times
    it is rewritten, and `diff --stat` keeps the same counts for any
    same-length edit. Verified — in the common convergence case, where a
    fix round has already dirtied the tree, both were byte-identical
    across a reviewer rewriting a tracked file.

    So this hashes the actual patch (`git diff HEAD`, covering staged and
    unstaged changes to tracked files) plus the contents of every
    untracked file, listed individually rather than collapsed into a
    directory entry.

    It answers BOTH questions the kernel needs about a tree, which is why
    there is only one of these: "is this the same situation?" for keying
    a policy approval or a replay cassette, and "did anything change?" for
    tamper detection. An earlier, cheaper variant answered only the first
    and answered it wrongly — an approval to "run the migration" survived
    the contents of an already-dirty file being rewritten, because the
    status line did not move (independent review; the same blindness
    L-0011 records for the rule-9 check).

    Read-only. It runs `git` — which is why the policy gate's invariant is
    stated as "no process that could act on the repository or on the
    agent's behalf", not "no process at all": computing the identity of
    the thing being judged is part of judging it.

    Known blind spot, stated rather than implied: **ignored files are not
    covered.** `git status` does not list them and enumerating them means
    walking the whole tree. A reviewer writing to an ignored path is not
    detected here; that needs the sandbox boundary.
    """
    evidence = capture_git_evidence(path)
    if not evidence.is_repo:
        return {"is_repo": False}

    code, status = _run_git(path, ["status", "--porcelain", "--untracked-files=all"])
    if code != 0:
        # A probe that failed must not read as "nothing changed": that
        # would make a broken git the way to defeat the check.
        return {"is_repo": True, "probe_failed": status}

    if evidence.head_sha is not None:
        diff_code, patch = _run_git(path, ["diff", "HEAD"])
    else:
        # No commits yet: there is no HEAD to diff against.
        diff_code, staged = _run_git(path, ["diff", "--cached"])
        unstaged_code, unstaged = _run_git(path, ["diff"])
        patch = staged + "\n" + unstaged
        diff_code = diff_code or unstaged_code
    if diff_code != 0:
        return {"is_repo": True, "probe_failed": patch}

    untracked: dict[str, str] = {}
    for line in status.splitlines():
        if not line.startswith("?? "):
            continue
        relative = line[3:].strip().strip('"')
        candidate = path / relative
        try:
            untracked[relative] = hash_canonical(
                base64.b64encode(candidate.read_bytes()).decode("ascii")
            )
        except OSError as exc:
            untracked[relative] = f"unreadable: {exc}"

    return {
        "is_repo": True,
        "head_sha": evidence.head_sha,
        "branch": evidence.branch,
        "status_sha256": hash_canonical(status),
        "patch_sha256": hash_canonical(patch),
        "untracked": untracked,
    }
