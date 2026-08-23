"""Prove the F-14 suite would catch the defects it claims to catch.

A green suite says nothing about whether its tests are load-bearing. The
only honest way to find out is to put each defect back and watch the
suite go red — and to record that it did, with exit codes, so the claim
is evidence rather than prose.

The defects put back here are the ones F-14 is about: identity that is
really just `git status`, a single fingerprint instead of two, a
before/after comparison that never compares, a broken probe that reads as
"nothing changed", a bundle written into the tree it is measuring, and a
summary that reports a pass for evidence the binding refused.

MF10..MF13 are the first independent review's finding: two equal
fingerprints prove two instants, not the interval between them. Each of
those four restores a version in which a check can change a file, read
the change and put the original bytes back without the capture noticing.

MF14..MF16 are the second review's: a write made through a memory-mapped
view need not generate any notification at all, so the covered inputs are
made unwritable instead of merely watched. These three take the
prevention away again.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/mutation_check_f14.py

Writes the transcript to stdout and, with `--out <path>`, to a file an
ADR can cite. Exits non-zero if any mutant survives, so it cannot produce
a clean transcript for an unguarded tree.

Kept separate from `scripts/mutation_check.py` on purpose: that script is
part of F-34's closed evidence and re-running it must keep producing the
same nine mutants over the same targeted suite.

The source files are restored in a `finally`, including on Ctrl-C. If
this process is killed outright, `git diff` shows exactly what to undo.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

CAPTURE = "src/gnosis/kernel/evidence_capture.py"
SCRIPT = "scripts/capture_evidence.py"

# Narrower than `tests/` on purpose: these are the tests that assert the
# binding, and a mutant that leaves them green has not been caught by
# anything a reader of F-14 would look at.
SUITE = [
    "tests/test_evidence_binding.py",
    "tests/test_git_evidence.py",
]


@dataclass(frozen=True)
class Mutant:
    """One defect, put back."""

    name: str
    description: str
    edits: list[tuple[str, str, str]] = field(default_factory=list)  # (file, old, new)


MUTANTS: list[Mutant] = [
    Mutant(
        "MF1", "the tree's identity is `git status --porcelain` again — a "
               "state and a name, never a content",
        [(CAPTURE,
          """    try:
        payload = dict(fingerprint(repo))
    except OSError as exc:""",
          """    try:
        payload = {"is_repo": True, "status": subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, capture_output=True,
            text=True, check=False).stdout}
    except OSError as exc:""")],
    ),
    Mutant(
        "MF2", "the before/after comparison is removed: two different "
               "fingerprints bind anyway",
        [(CAPTURE,
          """    if pre.digest != post.digest:
        return TreeBinding(pre, post, BindingVerdict.TREE_MUTATED,
                           describe_drift(pre.fingerprint, post.fingerprint))""",
          """    if False:
        return TreeBinding(pre, post, BindingVerdict.TREE_MUTATED, ())""")],
    ),
    Mutant(
        "MF3", "an unavailable identity binds: a probe that could not "
               "answer reads as agreement",
        [(CAPTURE,
          """    if not pre.available or not post.available or pre.digest is None or post.digest is None:
        return TreeBinding(pre, post, BindingVerdict.IDENTITY_UNAVAILABLE)""",
          """    if False:
        return TreeBinding(pre, post, BindingVerdict.IDENTITY_UNAVAILABLE)""")],
    ),
    Mutant(
        "MF4", "the post fingerprint is never taken, so the capture has "
               "only one end to compare",
        [(CAPTURE,
          """            finally:
                lock.release()
            post = identity(repo)""",
          """            finally:
                lock.release()
            pass""")],
    ),
    Mutant(
        "MF5", "the bundle is staged inside the repository again, so the "
               "evidence appears in its own post fingerprint",
        [(SCRIPT,
          '    return Path(tempfile.mkdtemp(prefix="gnosis-evidence-"))',
          '    return Path(tempfile.mkdtemp(prefix="gnosis-evidence-", '
          'dir=str(REPO / ".gnosis")))')],
    ),
    Mutant(
        "MF6", "an untracked file whose bytes could not be read is still "
               "called an identified tree",
        [(CAPTURE,
          """    if unreadable:
        return TreeIdentity(False, None, payload,
                            "untracked files could not be read: " + ", ".join(unreadable))""",
          """    if False:
        return TreeIdentity(False, None, payload, "")""")],
    ),
    Mutant(
        "MF7", "a failed git probe is accepted as an identity",
        [(CAPTURE,
          """    if "probe_failed" in payload:
        return TreeIdentity(False, None, payload,
                            f"git probe failed: {payload['probe_failed']}")""",
          """    if False:
        return TreeIdentity(False, None, payload, "")""")],
    ),
    Mutant(
        "MF8", "the summary reports a pass for evidence the binding "
               "refused (ADR-0025 round 2, transplanted onto this surface)",
        [(CAPTURE,
          """        "all_passed": valid and checks_verdict is ChecksVerdict.ALL_CLEAN,
        "gates_clean": valid and checks_verdict in (
            ChecksVerdict.ALL_CLEAN, ChecksVerdict.WITHIN_BASELINE),""",
          """        "all_passed": checks_verdict is ChecksVerdict.ALL_CLEAN,
        "gates_clean": checks_verdict in (
            ChecksVerdict.ALL_CLEAN, ChecksVerdict.WITHIN_BASELINE),""")],
    ),
    Mutant(
        "MF9", "a capture with no checks is allowed to report a result",
        [(CAPTURE,
          "    if not commands:\n        raise EmptyCaptureError(",
          "    if commands and not commands:\n        raise EmptyCaptureError(")],
    ),
    # MF10..MF13 are the first independent review's finding: two equal
    # fingerprints do not prove the interval between them. Each of these
    # restores a version in which a change that undoes itself passes.
    Mutant(
        "MF10", "an observed write to a covered input is not a violation, "
                "so a change that undoes itself passes",
        [(CAPTURE,
          """    verdict = (ObservationVerdict.INPUTS_MUTATED if violations
               else ObservationVerdict.CLEAN)""",
          "    verdict = ObservationVerdict.CLEAN")],
    ),
    Mutant(
        "MF11", "an observation that could have missed something is "
                "accepted as if it had seen nothing",
        [(CAPTURE,
          """    if not observation.available or not observation.complete:
        return Boundary(
            ObservationVerdict.UNOBSERVED, observation.mechanism,""",
          """    if False:
        return Boundary(
            ObservationVerdict.UNOBSERVED, observation.mechanism,""")],
    ),
    Mutant(
        "MF12", "validity goes back to the binding alone: equal endpoints "
                "are enough again (the reviewed defect, restored)",
        [(CAPTURE,
          """        return (self.binding.verdict is BindingVerdict.BOUND
                and self.boundary.verdict is ObservationVerdict.CLEAN)""",
          "        return self.binding.verdict is BindingVerdict.BOUND")],
    ),
    Mutant(
        "MF13", "a path that appears and disappears inside the run is not "
                "judged, so create-read-delete is invisible again",
        [(CAPTURE,
          """    ignored = _git_ignored(repo, sorted(unknown))
    for path, action in sorted(unknown.items()):
        if path in ignored:
            allowed_count += 1
        else:
            violations.append(f"{action}: {path}")""",
          "    allowed_count += len(unknown)")],
    ),
    # MF14..MF16 are the SECOND independent review's finding: a write made
    # through a memory-mapped view need not notify anything, so watching
    # cannot be the whole boundary. Each of these removes the prevention
    # that closes it and leaves only the watching.
    Mutant(
        "MF14", "the covered inputs are never made unwritable; only the "
                "write stream is left, which a mapped write can evade",
        [(CAPTURE,
          """            lock = input_lock(repo)
            lock_outcome = lock.acquire(sorted(covered))""",
          """            lock = input_lock(repo)
            lock_outcome = LockOutcome(True, 0, (), "none")""")],
    ),
    Mutant(
        "MF15", "a lock that could not be enforced is recorded as if it "
                "had been",
        [(CAPTURE,
          "    if lock is not None and not lock.enforced:",
          "    if False:")],
    ),
    Mutant(
        "MF16", "the checks run even when the inputs could not be "
                "protected",
        [(CAPTURE,
          "                if lock_outcome.enforced:",
          "                if True:")],
    ),
]


def _pytest(paths: list[str], fail_fast: bool) -> tuple[int, str]:
    argv = [sys.executable, "-m", "pytest", *paths, "-q"]
    if fail_fast:
        argv.append("-x")
    proc = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, check=False)
    tail = (proc.stdout.strip().splitlines() or [""])[-1][:200]
    return proc.returncode, tail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    lines: list[str] = []

    def say(text: str = "") -> None:
        print(text, flush=True)
        lines.append(text)

    say("MUTATION CHECK — F-14, evidence binds bytes over a protected, observed interval")
    say("=" * 72)
    say(f"targeted suite: {' '.join(SUITE)}")
    say()

    originals = {rel: (REPO / rel).read_text(encoding="utf-8")
                 for rel in {edit[0] for m in MUTANTS for edit in m.edits}}

    code, tail = _pytest(SUITE, fail_fast=False)
    say(f"BASELINE (repair in place): exit={code}  {tail}")
    if code != 0:
        say()
        say("ABORTED: the baseline suite is not green, so nothing a mutant "
            "does could be attributed to the mutant.")
        if args.out:
            args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1
    say()

    survived: list[str] = []
    try:
        for mutant in MUTANTS:
            for rel, old, new in mutant.edits:
                source = (REPO / rel).read_text(encoding="utf-8")
                if old not in source:
                    survived.append(f"{mutant.name} (NOT APPLIED)")
                    say(f"{mutant.name}: {mutant.description}")
                    say(f"  ABORTED: the target text is no longer present in {rel}.")
                    say("  verdict: NOT APPLIED — this mutant proves nothing.")
                    say()
                    break
                (REPO / rel).write_text(source.replace(old, new, 1), encoding="utf-8")
            else:
                code, tail = _pytest(SUITE, fail_fast=True)
                say(f"{mutant.name}: {mutant.description}")
                say(f"  files:  {', '.join(sorted({e[0] for e in mutant.edits}))}")
                say(f"  result: exit={code}  {tail}")
                say(f"  verdict: {'CAUGHT' if code != 0 else 'SURVIVED'}")
                say()
                if code == 0:
                    survived.append(mutant.name)
            # Restored between mutants as well as at the end: one mutant
            # must never be measured against another's edit.
            for rel, text in originals.items():
                (REPO / rel).write_text(text, encoding="utf-8")
    finally:
        for rel, text in originals.items():
            (REPO / rel).write_text(text, encoding="utf-8")

    code, tail = _pytest(SUITE, fail_fast=False)
    say(f"RESTORED: exit={code}  {tail}")
    say()
    say(f"mutants: {len(MUTANTS)}  survived/aborted: {len(survived)}"
        + (f"  -> {', '.join(survived)}" if survived else ""))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return 1 if survived or code != 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
