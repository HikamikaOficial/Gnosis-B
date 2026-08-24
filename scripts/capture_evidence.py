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
    6  the covered inputs could not be made unwritable, so nothing ran
    7  the tree moved while the boundary was being built

Every path git can enumerate — tracked, untracked AND ignored — is an
INPUT unless this file declares it an OUTPUT (the checks write there) or
OUT_OF_SCOPE (the evidence claims nothing about it, and an event there
invalidates the capture). Being git-ignored exempts nothing.

A second review then broke the observation: a write made through a
memory-mapped view need not generate any notification at all. So the
covered inputs are no longer merely watched — for the duration of the
checks the capture holds every one of them open with a share mode that
refuses write, delete and rename to everything else, which is also the
only way to refuse a writable mapping. Watching remains for what cannot
be locked in advance: paths that do not exist yet.
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

# THE DECLARED PATH POLICY. Every path git can enumerate is an INPUT —
# covered, locked, identified — unless it appears below. Nothing is
# exempt for being git-ignored: the seventh review showed a check reading
# MALICIOUS out of an ignored file while the bundle said evidence_valid.
#
# Each entry is a claim a reviewer can challenge on its own. An entry
# with a slash is a path prefix; one without is a directory name matched
# against any component.

# OUTPUT — the checks legitimately write here, so events are allowed.
# Everything that CAN be redirected out of the tree already is (see
# `check_environment`); this is what is left.
ALLOWED_WRITES: tuple[str, ...] = (
    ".git/",                # git rewrites its index while reading the tree
    "__pycache__",          # bytecode, redirected but named for the reader
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".gnosis/runtime/",     # kernel runtime state
    ".gnosis/logs/",
    ".gnosis/traces/",
    ".gnosis/artifacts/",
    ".gnosis/tmp/",
    ".gnosis/state/",       # lease/claim/lint-baseline stores
    ".gnosis/workspaces/",  # governed execution worktrees
    ".zerker/",             # ZMem's local store, held open by its server
    ".m3/",                 # M3's local index
    "memory/",              # local memory databases and indexes
    # Measured, not assumed: the first capture run under this policy
    # caught the code-intelligence suite writing a CodeGraph index into a
    # dataset fixture. The index is an output of the checks; the fixture
    # around it is not, and OUTPUT is matched before OUT_OF_SCOPE so this
    # carves out only the generated part.
    ".codegraph",
)

# OUT_OF_SCOPE — the evidence makes NO claim about these bytes, because
# enumerating them is not affordable: they are nested clones. Measured
# rather than guessed — expanding them is 90,237 paths and 1,218s to
# lock, against 2,944 paths and 2.3s for the input set as declared here.
#
# Out of scope is NOT the same as allowed. These roots are not locked and
# not identified, and any observed event under one INVALIDATES the
# capture, because the declaration says nothing writes there and an event
# says the declaration was wrong. What the declaration does not cover is
# a change made BEFORE the capture starts; the bundle names the roots so
# a reader knows the shape of what is not claimed.
OUT_OF_SCOPE: tuple[str, ...] = (
    # Constitution: READ-ONLY SOURCE, never executed, never imported.
    "external/repositories/",
    # .gitignore: "reproducible installs (uv venvs, npm, portable
    # downloads); fixture/dataset dirs are rebuildable and contain nested
    # git repos".
    ".gnosis/lab/code-intelligence/candidates/",
    ".gnosis/lab/code-intelligence/tools/",
    ".gnosis/lab/code-intelligence/datasets/",
    ".gnosis/lab/memory/candidates/",
    ".gnosis/lab/memory/datasets/",
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
                              allowed_writes=ALLOWED_WRITES,
                              out_of_scope=OUT_OF_SCOPE, scratch=scratch)
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
