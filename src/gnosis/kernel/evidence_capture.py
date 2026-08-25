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

**Two fingerprints are not enough, and that was the first independent
review's finding.** Equal endpoints prove the tree was the same at two
instants; they prove nothing about the interval. A check that modifies a
file, reads the modified bytes and restores the original bytes — and the
original size, attributes and timestamps — leaves both fingerprints
identical. Nothing sampled closes that: polling, `mtime`, `git status`
and a third fingerprint are all snapshots of a moment, and a transient
change lives between moments.

So the interval has its own authority: a write observer
(`kernel.write_observer`) armed before the first fingerprint and stopped
after the last, which streams every create, delete, rename, size,
attribute and last-write change under the tree. A write and its undo both
appear. An observation that could have missed something — an overflowed
kernel queue, an undelivered tail, no mechanism at all — is INCOMPLETE,
and incomplete fails closed exactly like a broken identity probe.

Six outcomes stay distinct, because the operator response differs::

    PASSED / FAILED        the checks — the code is right or wrong
    WITHIN_LINT_BASELINE   known, bounded debt; not a failure
    TREE_MUTATED           the endpoints differ; unattributable
    INPUTS_MUTATED         a covered input was written during the run,
                           whatever the endpoints say
    IDENTITY_UNAVAILABLE   the identity probe is broken
    BOUNDARY_UNAVAILABLE   the write observer is missing or incomplete

The last two fail closed on purpose. A probe that could not answer must
never read as "nothing changed", or breaking the probe becomes the way to
defeat the check.

**"Git ignores it" was being used as authority, and that was the
seventh review's finding.** `content_fingerprint` does not enumerate
git-ignored files, `covered_paths` did not add them, and the classifier
forgave a change to any path `git check-ignore` accepted. Put together
that read as *ignored ⇒ cannot affect the result*, which is false: a
`.env`, a local config, a fixture, a database, a plugin, or the
interpreter and tools in `.venv` are all ignored and all real inputs.
Reproduced — a check read `MALICIOUS` from an ignored file and the bundle
still said `CLEAN`, `evidence_valid: true`, `all_passed: true`.

So every path in the working tree now belongs to exactly one declared
class, and the default is the conservative one::

    INPUT          covered, locked, IDENTIFIED BY FILE ID AND HASHED.
                   Everything git reports — tracked, untracked AND
                   ignored, with nested-clone directory entries expanded
                   — that is not under a declared OUTPUT root. An
                   undeclared path is an INPUT.
    OUTPUT         a declared root the checks legitimately write: caches,
                   runtime state, artifacts. Events there are allowed,
                   and whatever already existed there when the capture
                   began is hashed, so nothing planted under one can be
                   read as an unnamed input.

`git check-ignore` is no longer consulted anywhere. The classes are
declared by the caller, recorded in the bundle, and a reviewer can
challenge any single declaration.

**And identity means bytes.** A file id says which object and a lock says
it did not change; neither says what was in it. Every input is hashed
through the handle that holds it, and the manifest is in the bundle, so
the evidence can be re-derived by a third party from the files rather
than believed.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .canonical import hash_canonical
from .git_evidence import content_fingerprint
from .input_lock import InputLock, LockOutcome, create_input_lock
from .write_observer import (
    BARRIER_DIR,
    Observation,
    WriteObserver,
    create_write_observer,
)

# Distinct on purpose: a reader who sees only the exit code still learns
# which of the six situations happened.
EXIT_OK = 0
EXIT_CHECKS_FAILED = 1
EXIT_TREE_MUTATED = 2
EXIT_IDENTITY_UNAVAILABLE = 3
EXIT_INPUTS_MUTATED = 4
EXIT_BOUNDARY_UNAVAILABLE = 5
EXIT_INPUTS_UNPROTECTED = 6
EXIT_PREPARATION_DRIFT = 7

_UNREADABLE_PREFIX = "unreadable: "

# Not a covered input and not the caller's choice: `content_fingerprint`
# never hashes `.git`, and git writes there while reading the tree.
_GIT_DIR = ".git/"


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


class PathClass(Enum):
    """Which side of the evidence boundary a path is on.

    TWO classes, and the eighth review is why there is no third. There
    used to be an OUT_OF_SCOPE class for roots too large to enumerate:
    not locked, not identified, not hashed, and any event there a
    violation. That last part made it honest about CHANGES and said
    nothing at all about READS, so an unbound root was still a silent
    input channel. A class whose contents cannot be stated is not a
    class the evidence can carry, so it is gone.

    Both remaining classes are byte-bound. They differ in what may
    change: an INPUT may not, an OUTPUT may.
    """

    INPUT = "INPUT"
    OUTPUT = "OUTPUT"


def classify_path(path: str, outputs: Sequence[str]) -> PathClass:
    """The declared class of one path. Undeclared means INPUT.

    An entry with a slash is a prefix; one without is a directory name
    matched against any component, so `__pycache__` covers every nesting
    of it without naming each one.
    """
    if _is_allowed_path(path, outputs):
        return PathClass.OUTPUT
    return PathClass.INPUT


class ObservationVerdict(Enum):
    """What the interval between the two fingerprints is known to be.

    CLEAN is a positive claim and requires a complete observation. An
    observer that was absent, that overflowed, or whose tail could not be
    proved delivered lands in UNOBSERVED — never in CLEAN, because "we
    saw nothing" and "we could not see" are the two answers this whole
    unit exists to keep apart.
    """

    CLEAN = "CLEAN"
    INPUTS_MUTATED = "INPUTS_MUTATED"
    UNOBSERVED = "UNOBSERVED"
    UNPROTECTED = "UNPROTECTED"
    PREPARATION_DRIFT = "PREPARATION_DRIFT"


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
                "content_fingerprint enumerates what git tracks, so git-ignored "
                "files (build caches, .venv, the ignored parts of .gnosis/) are "
                "not in THIS digest. They are not unbound: every one of them is "
                "locked, hashed through the handle holding it, and listed in "
                "input-manifest.json, whose aggregate is protection.content_digest"
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


def _git_lines(repo: Path, args: Sequence[str]) -> list[str]:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, check=False)
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.split("\0") if line]


def covered_paths(repo: Path, outputs: Sequence[str] = ()) -> frozenset[str]:
    """Every file the boundary is a statement about.

    Tracked, untracked AND ignored — everything git can enumerate —
    minus the paths the caller has declared as OUTPUT. Ignored files used
    to be excluded here and in `content_fingerprint`, which is how a
    git-ignored input could be swapped underneath a check without
    anything noticing.

    An ignored DIRECTORY that git reports as one entry — a nested clone it
    will not descend into — is expanded here by walking it. Git declining
    to look inside is not a reason for the evidence to decline too.
    """
    tracked = _git_lines(repo, ["ls-files", "-z"])
    status = _git_lines(repo, ["status", "--porcelain", "-z", "--untracked-files=all"])
    untracked = [entry[3:] for entry in status if entry.startswith("?? ")]
    ignored: list[str] = []
    for entry in _git_lines(
            repo, ["ls-files", "-z", "--others", "--ignored", "--exclude-standard"]):
        candidate = entry.replace("\\", "/")
        if not candidate.endswith("/"):
            ignored.append(candidate)
            continue
        for found in (repo / candidate).rglob("*"):
            if found.is_file():
                ignored.append(found.relative_to(repo).as_posix())
    return frozenset(
        candidate for candidate in
        (path.replace("\\", "/") for path in (*tracked, *untracked, *ignored))
        if classify_path(candidate, outputs) is PathClass.INPUT)


def output_paths(repo: Path, outputs: Sequence[str] = ()) -> frozenset[str]:
    """Files that already exist under a declared OUTPUT root.

    They are not locked — an output is allowed to change — but they are
    hashed, because a file planted under an output root before a capture
    and then read by a check would otherwise be an unnamed input. The
    eighth review asked for that specifically.
    """
    found: list[str] = []
    for root in outputs:
        if "/" not in root:
            continue
        base = repo / root
        if not base.is_dir():
            continue
        found.extend(item.relative_to(repo).as_posix()
                     for item in base.rglob("*") if item.is_file())
    return frozenset(found)


def _is_allowed_path(path: str, allowed: Sequence[str]) -> bool:
    """An entry with a slash is a prefix; one without is a directory name."""
    parts = path.split("/")
    for entry in allowed:
        if "/" in entry:
            if path == entry.rstrip("/") or path.startswith(entry):
                return True
        elif entry in parts:
            return True
    return False


@dataclass(frozen=True)
class Boundary:
    """What is known about the interval the checks ran in."""

    verdict: ObservationVerdict
    mechanism: str
    observed_events: int
    allowed_events: int
    violations: tuple[str, ...]
    covered_files: int
    allowed_writes: tuple[str, ...]
    reason: str | None = None
    machinery_events: int = 0
    protection: Mapping[str, Any] = field(default_factory=dict)
    locked_identity: Mapping[str, Any] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return self.verdict is ObservationVerdict.CLEAN

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "mechanism": self.mechanism,
            "observed_events": self.observed_events,
            "allowed_events": self.allowed_events,
            "machinery_events": self.machinery_events,
            "violations": list(self.violations),
            "covered_files": self.covered_files,
            "allowed_writes": list(self.allowed_writes),
            "input_policy": (
                "every path git can enumerate — tracked, untracked AND ignored, "
                "with directory entries for nested clones expanded — is an INPUT "
                "unless it is under a declared OUTPUT root. INPUTs are locked and "
                "hashed; an OUTPUT's pre-existing bytes are hashed too, so nothing "
                "planted under one can be read as an unnamed input. There is no "
                "unbound class, and git check-ignore is not consulted"
            ),
            "reason": self.reason,
            "protection": dict(self.protection),
            "locked_identity": dict(self.locked_identity),
            "identity_of_what_ran": (
                "locked_identity is taken AFTER every covered input is unwritable, "
                "so it describes the bytes the checks will actually read; it must "
                "equal the pre-check identity or the capture is refused"
            ),
            "authority": (
                "the write stream, not a comparison of endpoints: a change that "
                "undoes itself before the second fingerprint is still a change"
            ),
            "machinery_note": (
                "writes under .git/ are counted, not judged: git updates its own "
                "index while merely reading the tree, and .git is not a covered "
                "input. Tamper-evidence for the machinery itself is F-17 and is "
                "not repaired here"
            ),
        }


def classify_observation(
    repo: Path,
    observation: Observation,
    covered: frozenset[str],
    allowed_writes: Sequence[str],
    lock: LockOutcome | None = None,
    drift: Sequence[str] = (),
    locked_identity: Mapping[str, Any] | None = None,
) -> Boundary:
    """Turn prevention plus a stream of writes into one verdict.

    The boundary has two halves and needs both. The lock is what makes a
    covered input unwritable, including through a memory mapping, which
    is the case no watcher can see. The stream is what covers the
    operations the lock cannot pre-empt — a path that did not exist when
    the lock was taken, and the metadata changes that remain legal.

    A path is a violation when it is one of the covered files, or when it
    is a path nobody declared — that second case is how a file created
    and deleted inside the run gets caught, since it is in neither
    fingerprint. Git's opinion about it is not part of the test.

    Directories are judged the same way as anything else, with one
    exception that is a fact about the filesystem rather than a
    concession: a directory's own timestamp moves when its entries move,
    so a `modified` event on a directory is allowed. Creating, removing
    or renaming one is not.

    `git check-ignore` is not consulted, and there is no unbound class
    left for a path to fall into: every path is an INPUT whose bytes are
    hashed or a declared OUTPUT whose pre-existing bytes are hashed.
    """
    allowed = (BARRIER_DIR, *allowed_writes)
    protection: Mapping[str, Any] = lock.to_dict() if lock is not None else {}
    prepared: Mapping[str, Any] = locked_identity or {}
    if lock is not None and not lock.enforced:
        return Boundary(
            ObservationVerdict.UNPROTECTED, observation.mechanism,
            len(observation.events), 0, tuple(lock.refused), len(covered),
            tuple(allowed), lock.reason or "the covered inputs were not made unwritable",
            protection=protection, locked_identity=prepared)
    if lock is not None and not lock.fully_bound:
        # The eighth review's invariant at the consumer. A lock can be
        # enforced and fully identified while the bytes behind it were
        # never hashed, and that state is not evidence.
        return Boundary(
            ObservationVerdict.UNPROTECTED, observation.mechanism,
            len(observation.events), 0,
            (f"{lock.locked} handle(s) held, {len(lock.content_digests)} hashed",),
            len(covered), tuple(allowed),
            "an enforced lock held inputs whose bytes were never hashed",
            protection=protection, locked_identity=prepared)
    if lock is not None and not lock.fully_identified:
        # The producer can no longer build this, and the consumer refuses
        # it anyway. `locked_inputs` and `identified_objects` describe the
        # same domain, so an outcome that says enforced while holding a
        # handle it cannot name is not protection — the fifth review found
        # exactly one such path.
        return Boundary(
            ObservationVerdict.UNPROTECTED, observation.mechanism,
            len(observation.events), 0,
            (f"{lock.locked} handle(s) held, {len(lock.identities)} identified",),
            len(covered), tuple(allowed),
            "an enforced lock held handles that were never identified",
            protection=protection, locked_identity=prepared)
    if drift:
        # The tree moved between the fingerprint and the moment the inputs
        # became unwritable. Nothing ran, and the identity in the bundle
        # would not have described the bytes a check would have read.
        return Boundary(
            ObservationVerdict.PREPARATION_DRIFT, observation.mechanism,
            len(observation.events), 0, tuple(drift), len(covered), tuple(allowed),
            "the tree changed while the boundary was being built",
            protection=protection, locked_identity=prepared)
    if not observation.available or not observation.complete:
        return Boundary(
            ObservationVerdict.UNOBSERVED, observation.mechanism,
            len(observation.events), 0, (), len(covered), tuple(allowed),
            observation.reason or "the write observer could not promise a complete stream",
            protection=protection, locked_identity=prepared)

    violations: list[str] = []
    allowed_count = 0
    machinery = 0
    unknown: dict[str, str] = {}
    for event in observation.events:
        path = event.path
        if path in covered:
            violations.append(f"{event.action}: {path}")
        elif path == _GIT_DIR.rstrip("/") or path.startswith(_GIT_DIR):
            # Git rewrites its index while merely reading the tree, so
            # judging these would make the mechanism unusable. They are
            # counted instead of forgiven silently.
            machinery += 1
        elif _is_allowed_path(path, allowed):
            allowed_count += 1
        elif event.action == "modified" and (repo / path).is_dir():
            # A directory's own timestamp moves when its entries move, and
            # the entries produce their own events, so THAT is forgiven.
            # Nothing else about a directory is: the sixth review pointed
            # out that this branch used to swallow added/removed/renamed
            # too, purely because the path happened to be a directory
            # again by the time the classifier looked. A junction removed
            # and recreated against another target is exactly that shape.
            allowed_count += 1
        else:
            unknown.setdefault(path, event.action)

    for path, action in sorted(unknown.items()):
        # No `git check-ignore` here, and that is the seventh review's
        # repair. A path nobody declared is an unknown, and an unknown is
        # a violation: being ignored by git was never evidence that a
        # check cannot read it.
        violations.append(f"{action}: {path}")

    verdict = (ObservationVerdict.INPUTS_MUTATED if violations
               else ObservationVerdict.CLEAN)
    return Boundary(verdict, observation.mechanism, len(observation.events),
                    allowed_count, tuple(dict.fromkeys(violations)), len(covered),
                    tuple(allowed), machinery_events=machinery, protection=protection,
                    locked_identity=prepared)


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
    """A finished capture: the binding, the boundary, the checks, the bundle."""

    binding: TreeBinding
    checks: tuple[CheckResult, ...]
    checks_verdict: ChecksVerdict
    bundle: Path
    summary: Mapping[str, Any]
    exit_code: int
    boundary: Boundary

    @property
    def evidence_valid(self) -> bool:
        """Whether this bundle may be cited as evidence about a tree.

        Both halves are required. The binding says the endpoints agree;
        the boundary says nothing happened in between. Equal endpoints
        alone were the first independent review's finding.
        """
        return (self.binding.verdict is BindingVerdict.BOUND
                and self.boundary.verdict is ObservationVerdict.CLEAN)


def check_environment(scratch: Path) -> dict[str, str]:
    """Send every cache a check would write into a directory outside the tree.

    A capture that flags mypy's own cache as tampering is a capture
    nobody will keep running. Redirecting beats allow-listing: a cache
    that never lands in the tree cannot be confused with an input, and
    what is left in the allow-list stays small enough to read.
    """
    env = dict(os.environ)
    env["PYTHONPYCACHEPREFIX"] = str(scratch / "pycache")
    env["MYPY_CACHE_DIR"] = str(scratch / "mypy_cache")
    env["RUFF_CACHE_DIR"] = str(scratch / "ruff_cache")
    addopts = env.get("PYTEST_ADDOPTS", "")
    env["PYTEST_ADDOPTS"] = f"{addopts} -p no:cacheprovider".strip()
    return env


def _run_check(repo: Path, command: CheckCommand, staging: Path,
               lint_baseline: int, env: Mapping[str, str] | None = None) -> CheckResult:
    started = time.monotonic()
    proc = subprocess.run(
        list(command.argv), cwd=repo, capture_output=True, text=True, check=False,
        env=dict(env) if env is not None else None,
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


def _exit_code(binding: TreeBinding, checks: ChecksVerdict, boundary: Boundary) -> int:
    # Severity order, and it is a claim: a capture that cannot name its
    # own bytes is worse than one that names them and finds them red,
    # because the second is still evidence and the first is not. Not
    # knowing what happened in the interval outranks knowing that
    # something did, for the same reason.
    if binding.verdict is BindingVerdict.IDENTITY_UNAVAILABLE:
        return EXIT_IDENTITY_UNAVAILABLE
    if binding.verdict is BindingVerdict.TREE_MUTATED:
        return EXIT_TREE_MUTATED
    if boundary.verdict is ObservationVerdict.UNOBSERVED:
        return EXIT_BOUNDARY_UNAVAILABLE
    if boundary.verdict is ObservationVerdict.UNPROTECTED:
        return EXIT_INPUTS_UNPROTECTED
    if boundary.verdict is ObservationVerdict.PREPARATION_DRIFT:
        return EXIT_PREPARATION_DRIFT
    if boundary.verdict is ObservationVerdict.INPUTS_MUTATED:
        return EXIT_INPUTS_MUTATED
    if checks not in (ChecksVerdict.ALL_CLEAN, ChecksVerdict.WITHIN_BASELINE):
        return EXIT_CHECKS_FAILED
    return EXIT_OK


def _verdict_line(binding: TreeBinding, checks: ChecksVerdict, boundary: Boundary) -> str:
    if binding.verdict is BindingVerdict.IDENTITY_UNAVAILABLE:
        reason = binding.pre.reason or binding.post.reason or "no reason recorded"
        return f"INVALID EVIDENCE: the tree could not be identified - {reason}"
    if binding.verdict is BindingVerdict.TREE_MUTATED:
        return ("INVALID EVIDENCE: the tree changed during the capture; "
                "see tree_identity.drift")
    if boundary.verdict is ObservationVerdict.UNOBSERVED:
        return ("INVALID EVIDENCE: the interval between the fingerprints was not "
                f"observed - {boundary.reason}")
    if boundary.verdict is ObservationVerdict.UNPROTECTED:
        return ("INVALID EVIDENCE: the covered inputs were not made unwritable, so "
                f"nothing ran - {boundary.reason}")
    if boundary.verdict is ObservationVerdict.PREPARATION_DRIFT:
        return ("INVALID EVIDENCE: the tree changed while the boundary was being "
                "built, so nothing ran; see boundary.violations")
    if boundary.verdict is ObservationVerdict.INPUTS_MUTATED:
        return ("INVALID EVIDENCE: a covered input was written during the capture "
                "and the endpoints do not show it; see boundary.violations")
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
    boundary: Boundary,
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
    valid = (binding.verdict is BindingVerdict.BOUND
             and boundary.verdict is ObservationVerdict.CLEAN)
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
        "boundary": boundary.to_dict(),
        "bundle_staged_outside_repo": staged_outside_repo,
        "exit_code": _exit_code(binding, checks_verdict, boundary),
        "verdict": _verdict_line(binding, checks_verdict, boundary),
    }


def _preparation_drift(pre: TreeIdentity, prepared: TreeIdentity) -> tuple[str, ...]:
    """What moved between the fingerprint and the inputs becoming unwritable."""
    if not prepared.available:
        return ((f"the identity could not be re-taken once the inputs were locked: "
                 f"{prepared.reason}"),)
    if prepared.digest == pre.digest:
        return ()
    return describe_drift(pre.fingerprint, prepared.fingerprint) or ("digest",)


def file_digests(repo: Path, paths: Iterable[str]) -> dict[str, str]:
    """SHA-256 of files that are not locked, read by path.

    Used for the pre-existing contents of OUTPUT roots. Weaker than the
    INPUT manifest by construction — an output is allowed to change, so
    this says what was there when the capture began, not what stayed —
    and that is exactly its job: bytes planted under an output root
    before a run are named rather than anonymous.
    """
    digests: dict[str, str] = {}
    for relative in sorted(paths):
        target = repo / relative
        try:
            digest = hashlib.sha256()
            with target.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
        except OSError as exc:
            digests[relative] = f"unreadable: {exc}"
            continue
        digests[relative] = digest.hexdigest()
    return digests


def write_manifest(staging: Path, inputs: Mapping[str, str],
                   outputs: Mapping[str, str]) -> Path:
    """The bytes this capture is about, as a file a third party can check."""
    path = staging / "input-manifest.json"
    path.write_text(json.dumps({
        "note": (
            "SHA-256 per path. `inputs` were read through the handles that held "
            "them unwritable, so they are the bytes the checks read. "
            "`outputs_at_start` is what already existed under a declared OUTPUT "
            "root when the capture began; those may legitimately change."
        ),
        "inputs": dict(sorted(inputs.items())),
        "outputs_at_start": dict(sorted(outputs.items())),
    }, indent=2, sort_keys=False), encoding="utf-8")
    return path


def write_identities(staging: Path, identities: Mapping[str, str]) -> Path:
    """Which filesystem object each protected path actually was."""
    path = staging / "input-identities.json"
    path.write_text(json.dumps(dict(identities), indent=2, sort_keys=True),
                    encoding="utf-8")
    return path


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
    observer: Callable[[Path], WriteObserver] = create_write_observer,
    input_lock: Callable[[Path], InputLock] = create_input_lock,
    allowed_writes: Sequence[str] = (),
    scratch: Path | None = None,
    now: Callable[[], str] = _utc_now,
) -> Capture:
    """Run the checks inside an observed interval, between two fingerprints.

    The order is the argument. The observer is armed FIRST, so the pre
    fingerprint is itself inside the observed window; the checks run; the
    post fingerprint is taken while the observer is still running; only
    then is the stream closed, behind a barrier that proves its tail was
    delivered. The unobserved windows are the instant before arming and
    the instant after the barrier, and nothing runs in either.

    Nothing is written into ``repo`` by this function: the bundle lands in
    ``staging`` and the checks' caches are redirected into ``scratch``,
    both outside the tree, and publishing is a separate step the caller
    takes AFTER this returns.

    If the pre-check identity is unavailable, NOTHING RUNS. Spending 500
    seconds to produce a transcript that could never be attributed is not
    caution, and the empty ``checks`` tuple is what says so.
    """
    if not commands:
        raise EmptyCaptureError(
            "a capture with no checks would report a result nothing produced")

    staging.mkdir(parents=True, exist_ok=True)
    if scratch is None:
        scratch = staging.parent / f"{staging.name}.scratch"
    scratch.mkdir(parents=True, exist_ok=True)

    watcher = observer(repo)
    watcher.start()
    results: list[CheckResult] = []
    covered: frozenset[str] = frozenset()
    lock_outcome: LockOutcome | None = None
    prepared: TreeIdentity | None = None
    drift: tuple[str, ...] = ()
    try:
        pre = identity(repo)
        if pre.available:
            covered = covered_paths(repo, allowed_writes)
            env = check_environment(scratch)
            lock = input_lock(repo)
            lock_outcome = lock.acquire(sorted(covered))
            try:
                if lock_outcome.enforced:
                    # The identity that matters is taken HERE, once nothing
                    # can write the inputs any more: acquiring ~700 locks
                    # takes long enough to be a window, and an identity
                    # from before that window describes bytes that could
                    # still have moved inside it.
                    prepared = identity(repo)
                    drift = _preparation_drift(pre, prepared)
                    write_identities(staging, lock_outcome.identities)
                    write_manifest(staging, lock_outcome.content_digests,
                                   file_digests(repo, output_paths(repo, allowed_writes)))
                    if not drift:
                        # Nothing runs against inputs that anything could
                        # still write. Discovering that after the suite is
                        # worse than discovering it before.
                        for command in commands:
                            results.append(
                                _run_check(repo, command, staging, lint_baseline, env))
            finally:
                lock.release()
            post = identity(repo)
        else:
            post = TreeIdentity(
                False, None, {},
                "not taken: the pre-check identity was unavailable, so no check was run")
    finally:
        observation = watcher.stop()

    binding = bind_tree(pre, post)
    boundary = classify_observation(repo, observation, covered, allowed_writes,
                                    lock_outcome, drift,
                                    prepared.to_dict() if prepared is not None else None)
    checks_verdict = _checks_verdict(results)
    summary = build_summary(
        binding, results, checks_verdict, boundary,
        staged_outside_repo=not _is_inside(staging, repo),
        captured_at=now(),
    )
    write_summary(staging, summary)
    exit_code = summary["exit_code"]
    return Capture(binding, tuple(results), checks_verdict, staging, summary,
                   int(exit_code), boundary)


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
