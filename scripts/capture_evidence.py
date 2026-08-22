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

Exit codes are distinct on purpose:

    0  bound, and the gates are clean or within the recorded lint baseline
    1  bound, and a check failed (or lint debt rose above the baseline)
    2  the tree changed during the capture — the transcript is unattributable
    3  the tree's identity could not be taken — the probe is broken
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
    try:
        capture = run_capture(REPO, COMMANDS, staging, lint_baseline=lint_baseline())
        out_dir = publish_bundle(staging, EVIDENCE_ROOT / stamp)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    print(json.dumps(dict(capture.summary), indent=2, sort_keys=True))
    print(f"\nevidence: {out_dir.relative_to(REPO)}")
    if not capture.evidence_valid:
        print(f"\n{capture.summary['verdict']}")
        print("This bundle is a transcript, not evidence: it cannot be cited "
              "as proof about a tree.")
    return capture.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
