"""Bind a captured transcript to the exact bytes it ran against.

``git status --porcelain`` prints ``XY <path>``: a state and a name,
never a content. Two different dirty trees that touch the same files
produce a byte-identical status, so a bundle built on HEAD and status
alone cannot say WHICH bytes passed the suite. That is F-14 of the frozen
audit, and it is not hypothetical: the bundle this project cited as proof
of "760 tests passing" recorded four ` M` paths whose contents are
unrecoverable from it. Agreeing with a later commit is an inference FROM
the commit, not a proof FROM the evidence.

Identity here is ``content_fingerprint()`` (``kernel.git_evidence``),
which the repository already had and this surface was the last not to
use: HEAD, the patch against it, and the sha256 of every untracked file's
bytes listed per path. It is content-addressed, so different bytes give a
different digest whatever the file is called; it is portable, so an
identical clone re-derives it; and it discloses nothing, since only
hashes are recorded — an untracked file the operator has not committed is
represented without being read out.

Three rules make the binding worth something:

- The identity is taken BEFORE the first check and again immediately
  AFTER the last one. One fingerprint says nothing about a tree that
  moved underneath a 500-second suite, and a fingerprint taken only at
  the end describes the tree the suite LEFT, not the one it ran against.
- Anything other than two identical, available fingerprints is a failure,
  whatever the checks said. A transcript that cannot name its own bytes
  is not evidence of a green tree; it is a green transcript.
- The bundle is written OUTSIDE the repository and published after the
  post fingerprint, so evidence never invalidates itself by existing.

Four outcomes stay distinct, because the operator response differs::

    PASSED / FAILED        the checks — the code is right or wrong
    WITHIN_LINT_BASELINE   known, bounded debt; not a failure
    TREE_MUTATED           the transcript is unattributable
    IDENTITY_UNAVAILABLE   the probe is broken

The last one fails closed on purpose. A probe that could not answer must
never read as "nothing changed", or breaking the probe becomes the way to
defeat the check.

Known blind spot, stated rather than implied: ``content_fingerprint``
does not enumerate git-ignored files (see its docstring). Build caches,
``.venv`` and the ignored parts of ``.gnosis/`` are outside the
identified tree. Closing that means walking the whole tree, which is a
different decision than this one.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .canonical import hash_canonical
from .git_evidence import content_fingerprint

# Distinct on purpose: a reader who sees only the exit code still learns
# which of the four situations happened.
EXIT_OK = 0
EXIT_CHECKS_FAILED = 1
EXIT_TREE_MUTATED = 2
EXIT_IDENTITY_UNAVAILABLE = 3

_UNREADABLE_PREFIX = "unreadable: "


class BindingVerdict(Enum):
    """Whether the transcript can be attributed to a known tree."""

    BOUND = "BOUND"
    TREE_MUTATED = "TREE_MUTATED"
    IDENTITY_UNAVAILABLE = "IDENTITY_UNAVAILABLE"


class CheckOutcome(Enum):
    """What one command said. Lint debt is not a synonym for failure."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    WITHIN_LINT_BASELINE = "WITHIN_LINT_BASELINE"
    NEW_LINT_DEBT = "NEW_LINT_DEBT"


class ChecksVerdict(Enum):
    """The whole set of checks, classified once."""

    ALL_CLEAN = "ALL_CLEAN"
    WITHIN_BASELINE = "WITHIN_BASELINE"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True)
class TreeIdentity:
    """The content identity of a working tree at one instant.

    ``available`` and ``digest`` are separate because an unavailable
    identity still carries its payload: the reason a probe failed is
    forensics, and discarding it would leave "the tree could not be
    identified" with nothing behind it.
    """

    available: bool
    digest: str | None
    fingerprint: Mapping[str, Any]
    reason: str | None = None
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "digest": self.digest,
            "reason": self.reason,
            "ts": self.ts,
            # The WHOLE fingerprint, not a summary of it: a reviewer must
            # be able to re-derive the digest by hand from what is here.
            "fingerprint": dict(self.fingerprint),
        }


FingerprintFn = Callable[[Path], Mapping[str, Any]]


def probe_tree_identity(
    repo: Path, *, fingerprint: FingerprintFn = content_fingerprint,
) -> TreeIdentity:
    """Content identity of ``repo``, or an explicit refusal to claim one.

    Every path out of here that is not a real digest sets ``available`` to
    False. That includes an untracked file the fingerprint could not read:
    a file whose bytes were never hashed is not covered by the identity,
    and letting it through would reproduce the defect one layer down.

    Exceptions other than ``OSError`` are deliberately NOT swallowed. They
    abort the capture with a non-zero exit, which is also failing closed,
    and turning every unknown fault into a tidy verdict is how a broken
    probe starts to look like a working one.
    """
    try:
        payload = dict(fingerprint(repo))
    except OSError as exc:
        return TreeIdentity(False, None, {"probe_raised": repr(exc)},
                            f"the identity probe raised: {exc}")

    if not payload.get("is_repo"):
        return TreeIdentity(False, None, payload, "not a git work tree")
    if "probe_failed" in payload:
        return TreeIdentity(False, None, payload,
                            f"git probe failed: {payload['probe_failed']}")

    untracked: Mapping[str, Any] = payload.get("untracked") or {}
    unreadable = sorted(
        path for path, digest in untracked.items()
        if isinstance(digest, str) and digest.startswith(_UNREADABLE_PREFIX)
    )
    if unreadable:
        return TreeIdentity(False, None, payload,
                            "untracked files could not be read: " + ", ".join(unreadable))

    try:
        digest = hash_canonical(payload)
    except (TypeError, ValueError) as exc:
        return TreeIdentity(False, None, payload, f"the identity could not be hashed: {exc}")
    return TreeIdentity(True, digest, payload)


def describe_drift(pre: Mapping[str, Any], post: Mapping[str, Any]) -> tuple[str, ...]:
    """Name what moved, by field and by path. Never by content.

    An operator handed "the tree changed" has to go looking. One handed
    "untracked changed: notes.md" knows in a line. Paths are already
    visible in ``git status``; the bytes behind them are not disclosed
    here or anywhere else in the bundle.
    """
    drift: list[str] = []
    for name in ("head_sha", "branch", "status_sha256", "patch_sha256"):
        if pre.get(name) != post.get(name):
            drift.append(name)

    pre_untracked: Mapping[str, Any] = pre.get("untracked") or {}
    post_untracked: Mapping[str, Any] = post.get("untracked") or {}
    for path in sorted(set(pre_untracked) | set(post_untracked)):
        if path not in post_untracked:
            drift.append(f"untracked removed: {path}")
        elif path not in pre_untracked:
            drift.append(f"untracked added: {path}")
        elif pre_untracked[path] != post_untracked[path]:
            drift.append(f"untracked changed: {path}")
    return tuple(drift)


@dataclass(frozen=True)
class TreeBinding:
    """Two identities and the verdict that compares them."""

    pre: TreeIdentity
    post: TreeIdentity
    verdict: BindingVerdict
    drift: tuple[str, ...] = ()

    @property
    def identical(self) -> bool:
        """True only for a tree proved unchanged across the whole run."""
        return self.verdict is BindingVerdict.BOUND

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding": self.verdict.value,
            "identical": self.identical,
            "drift": list(self.drift),
            "reason": self.pre.reason or self.post.reason,
            "primitive": "gnosis.kernel.git_evidence.content_fingerprint",
            "covers": (
                "from immediately before the first check to immediately after the "
                "last one; the bundle is published afterwards and is deliberately "
                "not part of the identified tree"
            ),
            "blind_spot": (
                "git-ignored files are not enumerated by content_fingerprint "
                "(build caches, .venv, the ignored parts of .gnosis/)"
            ),
            "pre": self.pre.to_dict(),
            "post": self.post.to_dict(),
        }


def bind_tree(pre: TreeIdentity, post: TreeIdentity) -> TreeBinding:
    """Compare two identities. Unavailable dominates; different is mutated.

    The digests are checked for presence as well as equality. An identity
    that says ``available`` with no digest is a contradiction rather than
    a match, and two missing digests comparing equal is exactly the shape of
    bug this project has already paid for once (``all([]) is True``).
    """
    if not pre.available or not post.available or pre.digest is None or post.digest is None:
        return TreeBinding(pre, post, BindingVerdict.IDENTITY_UNAVAILABLE)
    if pre.digest != post.digest:
        return TreeBinding(pre, post, BindingVerdict.TREE_MUTATED,
                           describe_drift(pre.fingerprint, post.fingerprint))
    return TreeBinding(pre, post, BindingVerdict.BOUND)


@dataclass(frozen=True)
class CheckCommand:
    """One command in the capture.

    ``lint_baseline`` marks a command whose non-zero exit is measured
    against the recorded backlog instead of failing the run. It is a
    property of the command rather than a match on its name, so a second
    such gate does not mean editing an ``if name == "ruff"``.
    """

    name: str
    argv: tuple[str, ...]
    lint_baseline: bool = False


@dataclass(frozen=True)
class CheckResult:
    """What one command did, classified but not collapsed."""

    name: str
    argv: tuple[str, ...]
    exit_code: int
    duration_s: float
    tail: str
    outcome: CheckOutcome
    lint_findings: int | None = None
    lint_baseline: int | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "argv": list(self.argv),
            "exit_code": self.exit_code,
            "duration_s": self.duration_s,
            "tail": self.tail,
            "outcome": self.outcome.value,
        }
        if self.lint_findings is not None:
            payload["lint_findings"] = self.lint_findings
            payload["lint_baseline"] = self.lint_baseline
        if self.detail is not None:
            # Key kept as `verdict`: earlier bundles and the ADRs that
            # cite them read that name.
            payload["verdict"] = self.detail
        return payload


def count_lint_findings(stdout: str) -> int:
    """Findings in ruff's concise output, counted the way the baseline was."""
    return sum(1 for line in stdout.splitlines()
               if line.strip() and ":" in line and not line.startswith("["))


class EmptyCaptureError(ValueError):
    """A capture with no checks would assert a result from nothing."""


@dataclass(frozen=True)
class Capture:
    """A finished capture: the binding, the checks, and the bundle."""

    binding: TreeBinding
    checks: tuple[CheckResult, ...]
    checks_verdict: ChecksVerdict
    bundle: Path
    summary: Mapping[str, Any]
    exit_code: int

    @property
    def evidence_valid(self) -> bool:
        """Whether this bundle may be cited as evidence about a tree."""
        return self.binding.verdict is BindingVerdict.BOUND


def _run_check(repo: Path, command: CheckCommand, staging: Path,
               lint_baseline: int) -> CheckResult:
    started = time.monotonic()
    proc = subprocess.run(
        list(command.argv), cwd=repo, capture_output=True, text=True, check=False,
    )
    duration = time.monotonic() - started
    (staging / f"{command.name}.stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (staging / f"{command.name}.stderr.txt").write_text(proc.stderr, encoding="utf-8")
    # The last line is the one an ADR quotes ("874 passed in ...").
    tail = (proc.stdout.strip().splitlines() or [""])[-1][:300]

    if command.lint_baseline and proc.returncode != 0:
        count = count_lint_findings(proc.stdout)
        above = count > lint_baseline
        return CheckResult(
            command.name, tuple(command.argv), proc.returncode, round(duration, 2), tail,
            CheckOutcome.NEW_LINT_DEBT if above else CheckOutcome.WITHIN_LINT_BASELINE,
            lint_findings=count, lint_baseline=lint_baseline,
            detail=(f"NEW LINT DEBT: {count} > baseline {lint_baseline}" if above
                    else "known backlog, not above baseline"),
        )
    outcome = CheckOutcome.PASSED if proc.returncode == 0 else CheckOutcome.FAILED
    return CheckResult(command.name, tuple(command.argv), proc.returncode,
                       round(duration, 2), tail, outcome)


def _checks_verdict(results: Sequence[CheckResult]) -> ChecksVerdict:
    if not results:
        return ChecksVerdict.NOT_RUN
    if any(r.outcome in (CheckOutcome.FAILED, CheckOutcome.NEW_LINT_DEBT) for r in results):
        return ChecksVerdict.FAILED
    if any(r.outcome is CheckOutcome.WITHIN_LINT_BASELINE for r in results):
        return ChecksVerdict.WITHIN_BASELINE
    return ChecksVerdict.ALL_CLEAN


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _exit_code(binding: TreeBinding, checks: ChecksVerdict) -> int:
    # Severity order, and it is a claim: a capture that cannot name its
    # own bytes is worse than one that names them and finds them red,
    # because the second is still evidence and the first is not.
    if binding.verdict is BindingVerdict.IDENTITY_UNAVAILABLE:
        return EXIT_IDENTITY_UNAVAILABLE
    if binding.verdict is BindingVerdict.TREE_MUTATED:
        return EXIT_TREE_MUTATED
    if checks not in (ChecksVerdict.ALL_CLEAN, ChecksVerdict.WITHIN_BASELINE):
        return EXIT_CHECKS_FAILED
    return EXIT_OK


def _verdict_line(binding: TreeBinding, checks: ChecksVerdict) -> str:
    if binding.verdict is BindingVerdict.IDENTITY_UNAVAILABLE:
        reason = binding.pre.reason or binding.post.reason or "no reason recorded"
        return f"INVALID EVIDENCE: the tree could not be identified - {reason}"
    if binding.verdict is BindingVerdict.TREE_MUTATED:
        return ("INVALID EVIDENCE: the tree changed during the capture; "
                "see tree_identity.drift")
    # Strings preserved from the previous script, so anything already
    # reading a bundle keeps reading it.
    if checks is ChecksVerdict.ALL_CLEAN:
        return "all gates clean"
    if checks is ChecksVerdict.WITHIN_BASELINE:
        return "within baseline; see non_zero_exits"
    return "FAILED"


def build_summary(
    binding: TreeBinding,
    checks: Sequence[CheckResult],
    checks_verdict: ChecksVerdict,
    *,
    staged_outside_repo: bool,
    captured_at: str,
) -> dict[str, Any]:
    """The bundle's single readable claim, with the raw facts beside it.

    ``all_passed`` is gated on the binding. A summary that reads ``true``
    while the gate refused the evidence is where a reader stops, and this
    project has already shipped that bug once at a different height
    (ADR-0025, round 2). The ungated fact is not deleted, it is renamed:
    ``checks_all_zero_exit`` says what the commands did,
    ``checks_verdict`` says how that was classified, and every result
    keeps its own exit code.
    """
    non_zero = [r.name for r in checks if r.exit_code != 0]
    all_zero = bool(checks) and not non_zero
    valid = binding.verdict is BindingVerdict.BOUND
    return {
        "captured_at": captured_at,
        "python": sys.version.split()[0],
        "results": [r.to_dict() for r in checks],
        "checks_verdict": checks_verdict.value,
        "checks_all_zero_exit": all_zero,
        "non_zero_exits": non_zero,
        "all_passed": valid and checks_verdict is ChecksVerdict.ALL_CLEAN,
        "gates_clean": valid and checks_verdict in (
            ChecksVerdict.ALL_CLEAN, ChecksVerdict.WITHIN_BASELINE),
        "evidence_valid": valid,
        "tree_identity": binding.to_dict(),
        "bundle_staged_outside_repo": staged_outside_repo,
        "exit_code": _exit_code(binding, checks_verdict),
        "verdict": _verdict_line(binding, checks_verdict),
    }


def write_summary(staging: Path, summary: Mapping[str, Any]) -> Path:
    path = staging / "SUMMARY.json"
    path.write_text(json.dumps(dict(summary), indent=2, sort_keys=True), encoding="utf-8")
    return path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def run_capture(
    repo: Path,
    commands: Sequence[CheckCommand],
    staging: Path,
    *,
    lint_baseline: int = 0,
    identity: Callable[[Path], TreeIdentity] = probe_tree_identity,
    now: Callable[[], str] = _utc_now,
) -> Capture:
    """Run the checks between two fingerprints and write the bundle.

    Nothing is written into ``repo``: the bundle lands in ``staging``, and
    publishing it is a separate step the caller takes AFTER this returns,
    so the evidence cannot appear in its own post fingerprint.

    If the pre-check identity is unavailable, NOTHING RUNS. Spending 500
    seconds to produce a transcript that could never be attributed is not
    caution, and the empty ``checks`` tuple is what says so.
    """
    if not commands:
        raise EmptyCaptureError(
            "a capture with no checks would report a result nothing produced")

    staging.mkdir(parents=True, exist_ok=True)
    pre = identity(repo)

    results: list[CheckResult] = []
    if pre.available:
        for command in commands:
            results.append(_run_check(repo, command, staging, lint_baseline))
        post = identity(repo)
    else:
        post = TreeIdentity(
            False, None, {},
            "not taken: the pre-check identity was unavailable, so no check was run")

    binding = bind_tree(pre, post)
    checks_verdict = _checks_verdict(results)
    summary = build_summary(
        binding, results, checks_verdict,
        staged_outside_repo=not _is_inside(staging, repo),
        captured_at=now(),
    )
    write_summary(staging, summary)
    exit_code = summary["exit_code"]
    return Capture(binding, tuple(results), checks_verdict, staging, summary, int(exit_code))


def publish_bundle(staging: Path, destination: Path) -> Path:
    """Copy the finished bundle into the repository.

    Called after the post fingerprint, never before. Refuses to overwrite:
    an evidence directory that can be silently replaced is not evidence.
    """
    if destination.exists():
        raise FileExistsError(f"evidence bundle already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(staging, destination)
    return destination
