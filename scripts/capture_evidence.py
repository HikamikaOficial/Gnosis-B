"""Capture a verification transcript BOUND to the bytes it ran against.

An ADR line reading "874 passed; mypy strict clean" is a claim about a
command nobody can see. This script runs the commands and keeps their
argv, exit code, duration and output, so the claim is a transcript.

That was the first half, and it was not enough. The audit's F-14: the
bundle recorded HEAD and `git status --porcelain`, which is a state and a
NAME, never a content. Two different dirty trees that touch the same
files produce a byte-identical bundle, so nothing in the evidence said
WHICH bytes passed. Every F-34 round had to write an external
`tree-binding.json` by hand around this script to say what the script
should have said itself.

Now the tree's identity — `content_fingerprint()`, the primitive this
repository already had — is taken before the first check and again
immediately after the last, and both complete fingerprints go into
`SUMMARY.json`. If they differ, or if either could not be taken, the
capture is not evidence and says so, whatever the tests did.

The bundle is built OUTSIDE the repository and published afterwards, so
the evidence does not turn up in its own post fingerprint.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/capture_evidence.py

Equal endpoints were not enough either, and an independent review said so
by reproducing it: a check that changes a file, reads it and restores the
original bytes leaves both fingerprints identical. So the interval has
its own authority — a write observer streams every change under the tree
while the checks run, and a change that undoes itself is still a change.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/capture_evidence.py

Exit codes are distinct on purpose:

    0  bound and observed clean; gates clean or within the lint baseline
    1  a check failed (or lint debt rose above the baseline)
    2  the two fingerprints differ — the transcript is unattributable
    3  the tree's identity could not be taken — the probe is broken
    4  a covered input was written during the run, endpoints notwithstanding
    5  the interval could not be observed — no mechanism, or an incomplete one
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    # Runnable with a bare interpreter, not only from an editable install.
    sys.path.insert(0, str(REPO / "src"))

from gnosis.kernel.evidence_capture import (  # noqa: E402
    CheckCommand,
    publish_bundle,
    run_capture,
)

EVIDENCE_ROOT = REPO / ".gnosis" / "evidence"
LINT_BASELINE = REPO / ".gnosis" / "state" / "lint_baseline.json"

# Places inside the tree a check may legitimately write. Kept short on
# purpose: everything a check writes that CAN be redirected is redirected
# out of the tree entirely (see `check_environment`), so this list is
# what is left rather than a convenience. `.git/` is here because git
# updates its index while reading the tree, and `.git` is not a covered
# input — content_fingerprint does not hash it. The cache directories are
# belt and braces: they are redirected and git-ignored already, and
# naming them keeps a reader from having to derive that.
ALLOWED_WRITES: tuple[str, ...] = (
    ".git/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "__pycache__",
)

COMMANDS: list[CheckCommand] = [
    CheckCommand("pytest", (sys.executable, "-m", "pytest", "tests/", "-q")),
    CheckCommand("mypy", (sys.executable, "-m", "mypy", "src/gnosis")),
    # Ruff's rule set here is broader than the one earlier milestones were
    # written against, so the repo carries documented residuals in files
    # nobody has touched since. Counting them, rather than ignoring the
    # check or pretending it is clean, is what keeps "no NEW lint debt"
    # enforceable while the backlog is paid down.
    CheckCommand("ruff", (sys.executable, "-m", "ruff", "check", "src/gnosis", "tests",
                          "--no-cache", "--output-format=concise"), lint_baseline=True),
    CheckCommand("git-head", ("git", "rev-parse", "HEAD")),
    CheckCommand("git-status", ("git", "status", "--porcelain")),
]


def lint_baseline() -> int:
    try:
        payload = json.loads(LINT_BASELINE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # No baseline recorded: any finding is new debt. Failing closed
        # here is the point — a missing baseline must not read as
        # unlimited allowance.
        return 0
    value = payload.get("max_findings")
    return int(value) if isinstance(value, int) else 0


def staging_root() -> Path:
    """Where the bundle is built: OUTSIDE the repository, deliberately.

    `.gnosis/evidence/` is tracked, so a bundle written in place is an
    untracked change in the tree the post fingerprint is about to read.
    The capture would then report that the tree moved — and it would be
    right, about itself. Build it elsewhere, publish it after.
    """
    return Path(tempfile.mkdtemp(prefix="gnosis-evidence-"))


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    staging = staging_root()
    # The checks' caches go here, beside the bundle and outside the repo,
    # so nothing legitimate has to be forgiven inside the tree.
    scratch = staging.parent / f"{staging.name}.scratch"
    try:
        capture = run_capture(REPO, COMMANDS, staging, lint_baseline=lint_baseline(),
                              allowed_writes=ALLOWED_WRITES, scratch=scratch)
        out_dir = publish_bundle(staging, EVIDENCE_ROOT / stamp)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(scratch, ignore_errors=True)

    print(json.dumps(dict(capture.summary), indent=2, sort_keys=True))
    print(f"\nevidence: {out_dir.relative_to(REPO)}")
    if not capture.evidence_valid:
        print(f"\n{capture.summary['verdict']}")
        print("This bundle is a transcript, not evidence: it cannot be cited "
              "as proof about a tree.")
    return capture.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
