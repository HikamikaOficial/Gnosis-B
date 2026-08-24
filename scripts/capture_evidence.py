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
INPUT unless this file declares it an OUTPUT, and every INPUT is locked
AND hashed. Being git-ignored exempts nothing, and there is no class for
bytes the evidence cannot state.

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

# There is no third class. An eighth review pointed out that a root the
# evidence cannot state is a silent input channel however loudly it is
# declared, so OUT_OF_SCOPE is gone. The nested clones under
# external/repositories/ and .gnosis/lab/**/{candidates,tools,datasets}
# are INPUTs now like everything else: 88,424 files and 2.4 GB of them,
# measured, and that cost is the price of the guarantee rather than a
# reason to weaken it.

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
