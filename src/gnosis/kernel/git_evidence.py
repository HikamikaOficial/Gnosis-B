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


def git_topology_eligible(repo_path: Path) -> tuple[bool, str | None]:
    """Is `repo_path` a topology whose git machinery lives INSIDE it?

    F-17's machinery judgement (hooks, config) works only when the write
    observer can see those files — that is, when `.git` is a plain
    directory inside the watched tree and both the git-dir and the
    common-dir resolve to it. In a linked worktree, a submodule, or a
    `--separate-git-dir` clone, `.git` is a redirect FILE and the
    trust-relevant machinery — HEAD, index, config, hooks, refs — lives in
    an external git-dir/common-dir OUTSIDE the tree, where the observer
    never looks. Measured: a capture run inside a worktree with a hook
    installed into the common dir returned CLEAN. So such a topology is
    NOT eligible for the guarantee, and the capture must fail closed rather
    than degrade to a protected-looking verdict.

    Returns ``(True, None)`` for a standard single-repo topology (or for a
    non-repo directory, which has no git machinery to tamper), and
    ``(False, reason)`` otherwise. The redirect is treated as adversarial:
    `git rev-parse` resolves it and the resolved paths are checked to lie
    inside the canonical tree, so a `.git` file pointing outside the tree
    (path confusion / traversal) is refused, not followed into.
    """
    code, _ = _run_git(repo_path, ["rev-parse", "--is-inside-work-tree"])
    if code != 0:
        # Not a git repository: there is no `.git` machinery to tamper, so
        # the machinery guarantee is vacuous and does not gate the capture.
        return True, None

    dot_git = repo_path / ".git"
    if dot_git.is_file():
        return False, (
            ".git is a redirect file (linked worktree, submodule, or "
            "separate-git-dir): the git machinery that runs the checks lives "
            "outside the watched tree and cannot be observed")
    if not dot_git.is_dir():
        return False, ".git is neither a directory nor a redirect file"

    try:
        tree = repo_path.resolve(strict=False)
        expected = (tree / ".git").resolve(strict=False)
    except OSError as exc:
        return False, f"the repository path could not be canonicalised: {exc}"

    code, toplevel = _run_git(repo_path, ["rev-parse", "--show-toplevel"])
    if code != 0:
        return False, f"git could not report the work-tree top level: {toplevel}"
    if Path(toplevel).resolve(strict=False) != tree:
        return False, (
            f"the work-tree top level is {toplevel}, not the captured path; "
            "the capture is not at the root of its own work tree")

    code, git_dir = _run_git(repo_path, ["rev-parse", "--absolute-git-dir"])
    if code != 0:
        return False, f"git could not report its git-dir: {git_dir}"
    if Path(git_dir).resolve(strict=False) != expected:
        return False, (
            f"the git-dir is {git_dir}, not {expected}: the machinery is not "
            "the .git directory inside the watched tree")

    code, common = _run_git(repo_path, ["rev-parse", "--git-common-dir"])
    if code != 0:
        return False, f"git could not report its common-dir: {common}"
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = (repo_path / common_path)
    if common_path.resolve(strict=False) != expected:
        return False, (
            f"the common-dir is {common}, not the in-tree .git: a shared "
            "git-dir puts hooks and config outside the watched tree")

    return True, None


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
    """Identity of a working tree by its CONTENT — portable on purpose.

    Answers "is this the same situation?", for keying a policy approval
    or a replay cassette. Everything in it travels: an identical clone
    somewhere else produces the same fingerprint. (The complementary
    question — "did anything change?" — is `tamper_fingerprint`, which is
    exhaustive rather than portable.)

    Status alone cannot answer even this, and a fingerprint built on it
    silently did not: a file already listed as ` M code.py` keeps that
    exact status line however many more times it is rewritten, and `diff
    --stat` keeps the same counts for any same-length edit. Verified — in
    the common convergence case, where a fix round has already dirtied
    the tree, both were byte-identical across a rewrite. An approval to
    "run the migration" therefore survived the contents of an
    already-dirty file changing underneath it (independent review;
    L-0011 records the same blindness in the rule-9 check).

    So this hashes the actual patch (`git diff HEAD`, covering staged and
    unstaged changes to tracked files) plus the contents of every
    untracked file, listed individually rather than collapsed into a
    directory entry.

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

    # `-z` because plain porcelain C-quotes any path with a non-ASCII or
    # special character (`?? "caf\303\251.txt"`). Reading that literally
    # failed, and the failure was recorded as a STABLE `unreadable:`
    # string — so the file's real bytes were never hashed and a reviewer
    # could edit it undetected. A rule-9 bypass that needed nothing more
    # than an accent in a filename (Codex review, reproduced).
    code, status = _run_git(path, ["status", "--porcelain", "-z", "--untracked-files=all"])
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
    for entry in status.split("\0"):
        # `-z` records are `XY <path>` with no quoting and no escaping,
        # NUL-separated. Rename records carry a second NUL-separated path,
        # but an untracked entry never does.
        if not entry.startswith("?? "):
            continue
        relative = entry[3:]
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


def tamper_fingerprint(path: Path) -> dict[str, Any]:
    """`content_fingerprint` PLUS the repository's own machinery.

    Two different questions need two different functions, and collapsing
    them broke a real property:

    - *Is this the same situation?* — for keying a policy approval or a
      replay cassette. That answer must be PORTABLE: an identical clone
      elsewhere is the same situation, even though its `remote.origin.url`
      differs. `content_fingerprint`.
    - *Did anything change?* — for catching a reviewer that edited what it
      was judging (rule 9). That answer must be EXHAUSTIVE, and `git
      status` says nothing about `.git` itself: a "read-only" agent could
      install a pre-commit hook (arbitrary code that runs on the next
      commit) or repoint a remote, and the check would see an unchanged
      tree. Verified missed before this existed.

    The machinery hash is what makes the second answer complete and the
    first one machine-local, which is exactly why it belongs here and not
    in `content_fingerprint`.
    """
    fingerprint = content_fingerprint(path)
    if not fingerprint.get("is_repo"):
        return fingerprint
    return {**fingerprint, "machinery": _machinery_fingerprint(path)}


# Hooks git ships as inert examples. Hashing them adds noise, and their
# presence or absence is not a tamper signal.
_SAMPLE_SUFFIX = ".sample"


def _machinery_fingerprint(path: Path) -> dict[str, Any]:
    """Hash the parts of `.git` that can execute or redirect.

    Deliberately narrow: hooks (code that runs on git operations) and
    config (where a push goes, what a filter runs). Hashing all of `.git`
    would make the fingerprint change on every ordinary git read.
    """
    code, common_dir = _run_git(path, ["rev-parse", "--git-common-dir"])
    if code != 0:
        return {"probe_failed": common_dir}
    git_dir = Path(common_dir)
    if not git_dir.is_absolute():
        git_dir = path / git_dir

    fingerprint: dict[str, Any] = {}
    config = git_dir / "config"
    try:
        fingerprint["config"] = hash_canonical(config.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        fingerprint["config"] = None

    hooks: dict[str, str] = {}
    hooks_dir = git_dir / "hooks"
    try:
        entries = sorted(hooks_dir.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        if entry.name.endswith(_SAMPLE_SUFFIX) or not entry.is_file():
            continue
        try:
            hooks[entry.name] = hash_canonical(
                base64.b64encode(entry.read_bytes()).decode("ascii"))
        except OSError as exc:
            hooks[entry.name] = f"unreadable: {exc}"
    fingerprint["hooks"] = hooks
    return fingerprint
