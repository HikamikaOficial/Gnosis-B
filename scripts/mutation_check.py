"""Prove the F-34 suite would catch the defects it claims to catch.

A green suite says nothing about whether the tests are load-bearing. The
only honest way to find out is to put each defect back and watch the
suite go red — and to record that it did, with exit codes, so the claim
is evidence rather than prose. Three independent reviews of F-34 each
found a reader of `VerificationResult.passed` that the previous round's
tests did not cover, so "we tested it" is exactly the claim that needs
proving here.

Each mutant restores ONE production defect, verbatim where possible. A
mutant that survives is a hole in the suite, not a curiosity: it means
the invariant is asserted by nothing.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/mutation_check.py

Writes the transcript to stdout and, with `--out <path>`, to a file an
ADR can cite. Exits non-zero if any mutant survives, so it cannot
produce a clean transcript for an unguarded tree.

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

VERIFICATION = "src/gnosis/kernel/verification.py"
CONVERGENCE = "src/gnosis/kernel/convergence.py"
INTEGRATION = "src/gnosis/kernel/integration.py"
CLI_REVIEW = "src/gnosis/adapters/cli_review.py"
PIPELINE = "src/gnosis/director/pipeline.py"

# The suite that must go red. Narrower than `tests/` on purpose: these are
# the modules that assert the invariant, and a mutant that leaves them all
# green has not been caught by anything a reader of F-34 would look at.
SUITE = [
    "tests/test_no_invalid_done.py",
    "tests/test_verification.py",
    "tests/test_convergence.py",
    "tests/test_integration.py",
    "tests/test_pipeline.py",
]


@dataclass(frozen=True)
class Mutant:
    """One defect, put back.

    `edits` is a list because some defects are only reachable when two
    guards are removed together — an honest mutant restores the whole
    defect rather than half of it, which would survive for the wrong
    reason.
    """

    name: str
    description: str
    edits: list[tuple[str, str, str]] = field(default_factory=list)  # (file, old, new)


MUTANTS: list[Mutant] = [
    Mutant(
        "M1", "CompositeVerifier reads `passed` for truthiness again "
              "(`all(r.passed for r in results)`)",
        [(VERIFICATION, '''        invalid = [child for child, verdict in graded
                   if verdict is VerificationVerdict.MALFORMED]
        if invalid or not graded:
            # `not graded` is unreachable through `__init__` and is kept
            # anyway: it states the invariant where it is relied upon, so
            # deleting the constructor's guard cannot silently restore
            # `all([]) is True` here.
            return self._no_verdict(graded, invalid)

        # Every member is PASSED or FAILED, so every member IS a
        # `VerificationResult` — but that is derived, and the narrowing is
        # therefore done explicitly rather than assumed.
        results = [child for child, _ in graded if isinstance(child, VerificationResult)]
        failed = [child for child, verdict in graded
                  if verdict is VerificationVerdict.FAILED
                  and isinstance(child, VerificationResult)]
        all_passed = not failed''',
          '''        results = [child for child, _ in graded]
        all_passed = all(r.passed for r in results)
        failed = [r for r in results if not r.passed]''')],
    ),
    Mutant(
        "M2", "an empty CompositeVerifier can be constructed again",
        [(VERIFICATION, "        if not members:\n            raise EmptyCompositeError(",
          "        if members and not members:\n            raise EmptyCompositeError(")],
    ),
    Mutant(
        "M3", "`all([]) is True` is restored end to end: the constructor "
              "accepts an empty collection AND `run` no longer guards it",
        [(VERIFICATION, "        if not members:\n            raise EmptyCompositeError(",
          "        if members and not members:\n            raise EmptyCompositeError("),
         (VERIFICATION, "        if invalid or not graded:", "        if invalid:")],
    ),
    Mutant(
        "M4", "a malformed member is collapsed into an ordinary FAILED",
        [(VERIFICATION, "            return self._no_verdict(graded, invalid)",
          """            return VerificationResult(
                name=self.name, passed=False, exit_code=1, duration_s=0.0,
                stdout_excerpt="", stderr_excerpt="a member was unreadable")""")],
    ),
    Mutant(
        "M5", "ConvergenceLoop reads `verification.passed` for truthiness "
              "again, and malformed evidence counts as collected",
        [(CONVERGENCE, "                and verdict is not VerificationVerdict.MALFORMED\n",
          ""),
         (CONVERGENCE, "                and verdict is VerificationVerdict.PASSED",
          "                and verification is not None and verification.passed")],
    ),
    Mutant(
        "M6", "WorkIntegrator lands on `if not verification.passed`",
        [(INTEGRATION, '''        if verdict is VerificationVerdict.MALFORMED:
            return IntegrationResult(
                IntegrationOutcome.VERIFICATION_INVALID, task_id, branch,
                reason="merged_tree_verification_stated_no_verdict",
                base_sha=base_sha, merged_sha=merged_sha,
                checkpoint_ref=checkpoint_ref, changed_paths=changed,
                verification=verification,
                detail={"evidence": evidence_reason(verification)},
            )
        if verdict is not VerificationVerdict.PASSED:''',
          "        if not verification.passed:")],
    ),
    Mutant(
        "M7", "the fixer prompt reads `not verification.passed` again, so "
              "invalid evidence is described as nothing at all",
        [(CLI_REVIEW, '''    if evidence is None:
        return None
    verdict = verification_verdict(evidence)
    if verdict is VerificationVerdict.FAILED:
        return ("Deterministic verification is currently FAILING; that must "
                "end up passing.")
    if verdict is VerificationVerdict.MALFORMED:''',
          '''    if evidence is not None and not evidence.passed:
        return ("Deterministic verification is currently FAILING; that must "
                "end up passing.")
    if False:''')],
    ),
    Mutant(
        "M8", "GovernedPipeline derives COMPLETED from CONVERGED alone",
        [(PIPELINE, '''        if converged_on_valid_evidence(convergence):
            return ReportStatus.COMPLETED''',
          "        if True:\n            return ReportStatus.COMPLETED")],
    ),
    Mutant(
        "M9", "the shared verdict itself reads truthiness (round-2 mutant, "
              "kept: it is the single point everything now derives from)",
        [(VERIFICATION, """    if passed is True:
        return VerificationVerdict.PASSED
    if passed is False:
        return VerificationVerdict.FAILED""",
          """    if passed:
        return VerificationVerdict.PASSED
    return VerificationVerdict.FAILED""")],
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

    say("MUTATION CHECK — F-34, third independent review")
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
            # Restored between mutants as well as at the end: one
            # mutant must never be measured against another's edit.
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
