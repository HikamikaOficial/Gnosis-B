"""Prove the F-17 Stage-7 suite catches what it claims.

Each mutant restores a real way for an unknown or dangerous .git surface to
reach an anchor, or for the backend/version gate to fail open. A SURVIVOR is a
claim the suite does not actually check.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/mutation_check_stage7.py [--out PATH]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SURFACE = "src/gnosis/kernel/git_surface.py"
CAPTURE = "src/gnosis/kernel/evidence_capture.py"
GITEV = "src/gnosis/kernel/git_evidence.py"
ANCHOR = "src/gnosis/trust/anchor.py"
ORCH = "src/gnosis/trust/orchestration.py"

SUITE = [
    "tests/test_git_surface.py",
    "tests/test_git_surface_enforcement.py",
    "tests/test_git_backend_gate.py",
    "tests/test_evidence_binding.py::TestGitMachineryIsJudged",
]


@dataclass(frozen=True)
class Mutant:
    name: str
    description: str
    edits: list[tuple[str, str, str]] = field(default_factory=list)


# Multi-line anchors as named constants (ISC004-safe, and the anchor must match
# the source exactly).
_UNKNOWN_DEFAULT = (
    '        return GitSurfaceVerdict(\n'
    '            GitSurfaceClass.UNKNOWN, "unqualified",'
)
_BOOKKEEPING_DEFAULT = (
    '        return GitSurfaceVerdict(\n'
    '            GitSurfaceClass.KNOWN_CONTENT_OR_BOOKKEEPING, "unqualified",'
)
_OVERLAP_GUARD = (
    "    if len(matches) > 1:\n"
    "        raise GitSurfaceOverlap("
)
_OVERLAP_FIRST_MATCH = (
    "    if len(matches) > 99:\n"
    "        raise GitSurfaceOverlap("
)
_CANON_LOWER = 'lowered = stripped.lower()'
_CANON_NOLOWER = 'lowered = stripped'
_CANON_STRIP = 'stripped = part.rstrip(". ")'
_CANON_NOSTRIP = 'stripped = part'
_VERSION_GATE = "if (major, minor) != (_QUALIFIED_GIT_MAJOR, _QUALIFIED_GIT_MINOR):"
_VERSION_OPEN = "if (major, minor) == (-1, -1):"
_BACKEND_GATE = "if fmt != _QUALIFIED_REF_FORMAT:"
_BACKEND_OPEN = "if fmt == '\\x00never':"
_ANCHOR_GATE = "if boundary_verdict != _PUBLISHABLE_BOUNDARY_VERDICT:"
_ANCHOR_OPEN = "if boundary_verdict == '\\x00never':"
_ABSENT_NONE = "return verdict if isinstance(verdict, str) else None"
_ABSENT_CLEAN = 'return verdict if isinstance(verdict, str) else "CLEAN"'
_UNQ_ROUTE = (
    "                else:\n"
    "                    unqualified_violations.append(\n"
    '                        f"{event.action}: {path} [{surface.rule_id}]")'
)
_UNQ_COUNT = (
    "                else:\n"
    "                    machinery += 1  # MUTANT: unqualified forgiven"
)
_EXIT_UNQ = (
    "    if boundary.verdict is ObservationVerdict.MACHINERY_UNQUALIFIED:\n"
    "        return EXIT_MACHINERY_UNQUALIFIED"
)
_EXIT_UNQ_OK = (
    "    if boundary.verdict is ObservationVerdict.MACHINERY_UNQUALIFIED:\n"
    "        return EXIT_OK"
)
_REPLACE_FAILCLOSED = (
    "    if code != 0:\n"
    "        # F-17 Stage 7: a FAILED probe is UNKNOWN, not \"no replace refs\"."
)
_REPLACE_FAILOPEN = (
    "    if code > 9999:\n"
    "        # F-17 Stage 7: a FAILED probe is UNKNOWN, not \"no replace refs\"."
)
_SHALLOW_FAILCLOSED = (
    "    if code != 0:\n"
    "        # A failed probe is UNKNOWN, not \"not shallow\" (fail-open removed)."
)
_SHALLOW_FAILOPEN = (
    "    if code > 9999:\n"
    "        # A failed probe is UNKNOWN, not \"not shallow\" (fail-open removed)."
)


def _rule_class(rule_id: str, frm: str, to: str) -> tuple[str, str, str]:
    old = f'_Rule("{rule_id}", {frm},'
    new = f'_Rule("{rule_id}", {to},'
    return (SURFACE, old, new)


MUTANTS: list[Mutant] = [
    Mutant("S7M01", "an unqualified .git surface defaults to bookkeeping, not UNKNOWN",
           [(SURFACE, _UNKNOWN_DEFAULT, _BOOKKEEPING_DEFAULT)]),
    Mutant("S7M02", "the overlap guard is disabled (first-match instead of raise)",
           [(SURFACE, _OVERLAP_GUARD, _OVERLAP_FIRST_MATCH)]),
    Mutant("S7M03", "refs/heads broadened to a blanket refs/ rule",
           [(SURFACE, '_prefix("refs/heads/")', '_prefix("refs/")')]),
    Mutant("S7M04", "loose-object broadened to a blanket objects/ rule",
           [(SURFACE, "_regex(_LOOSE_OBJECT)", '_prefix("objects/")')]),
    Mutant("S7M05", "packed-refs downgraded from trust-sensitive to bookkeeping",
           [_rule_class("ts.packed-refs", "_TS", "_BK")]),
    Mutant("S7M06", "replace refs downgraded to bookkeeping",
           [_rule_class("ts.refs-replace", "_TS", "_BK")]),
    Mutant("S7M07", "HEAD downgraded to bookkeeping",
           [_rule_class("ts.head", "_TS", "_BK")]),
    Mutant("S7M08", "info/exclude downgraded to bookkeeping",
           [_rule_class("ts.info-exclude", "_TS", "_BK")]),
    Mutant("S7M09", "canonicalization no longer case-folds (Windows case bypass)",
           [(SURFACE, _CANON_LOWER, _CANON_NOLOWER)]),
    Mutant("S7M10", "canonicalization no longer strips trailing dot/space",
           [(SURFACE, _CANON_STRIP, _CANON_NOSTRIP)]),
    Mutant("S7M11", "the git version gate accepts any version",
           [(GITEV, _VERSION_GATE, _VERSION_OPEN)]),
    Mutant("S7M12", "an unqualified ref backend (reftable) is accepted",
           [(GITEV, _BACKEND_GATE, _BACKEND_OPEN)]),
    Mutant("S7M13", "the replace-ref probe fails open again",
           [(GITEV, _REPLACE_FAILCLOSED, _REPLACE_FAILOPEN)]),
    Mutant("S7M14", "the shallow probe fails open again",
           [(GITEV, _SHALLOW_FAILCLOSED, _SHALLOW_FAILOPEN)]),
    Mutant("S7M15", "the build_anchor_record boundary gate is removed",
           [(ANCHOR, _ANCHOR_GATE, _ANCHOR_OPEN)]),
    Mutant("S7M16", "an absent boundary verdict reads as CLEAN",
           [(ANCHOR, _ABSENT_NONE, _ABSENT_CLEAN)]),
    Mutant("S7M17", "the authorize_publishable boundary gate is removed",
           [(ORCH, _ANCHOR_GATE, _ANCHOR_OPEN)]),
    Mutant("S7M18", "an unqualified .git write is counted, not judged (kernel routing)",
           [(CAPTURE, _UNQ_ROUTE, _UNQ_COUNT)]),
    Mutant("S7M19", "MACHINERY_UNQUALIFIED maps to exit 0",
           [(CAPTURE, _EXIT_UNQ, _EXIT_UNQ_OK)]),
]


def _pytest() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, "-m", "pytest", *SUITE, "-q", "-x",
                           "-p", "no:cacheprovider"],
                          cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)
    tail = (proc.stdout.strip().splitlines() or [""])[-1][:200]
    return proc.returncode, tail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    lines: list[str] = []

    def say(message: str) -> None:
        print(message)
        lines.append(message)

    touched = sorted({rel for m in MUTANTS for rel, _, _ in m.edits})
    originals = {rel: (REPO / rel).read_text(encoding="utf-8") for rel in touched}

    say("F-17 STAGE 7 — MUTATION CHECK OVER THE CLASSIFIER, GATE AND ENFORCEMENT")
    say("=" * 74)
    code, tail = _pytest()
    say(f"BASELINE: exit={code}  {tail}")
    if code != 0:
        say("baseline is not green; refusing to attribute mutant verdicts")
        return 1
    say("")

    survived: list[str] = []
    try:
        for mutant in MUTANTS:
            applied = True
            for rel, old, new in mutant.edits:
                src = (REPO / rel).read_text(encoding="utf-8")
                if old not in src:
                    applied = False
                    break
                (REPO / rel).write_text(src.replace(old, new, 1),
                                        encoding="utf-8", newline="")
            if not applied:
                survived.append(f"{mutant.name} (NOT APPLIED)")
                say(f"{mutant.name}: {mutant.description}\n  verdict: NOT APPLIED")
            else:
                code, tail = _pytest()
                say(f"{mutant.name}: {mutant.description}")
                say(f"  result: exit={code}  {tail}")
                say(f"  verdict: {'CAUGHT' if code != 0 else 'SURVIVED'}")
                if code == 0:
                    survived.append(mutant.name)
            for rel, text in originals.items():
                (REPO / rel).write_text(text, encoding="utf-8", newline="")
            say("")
    finally:
        for rel, text in originals.items():
            (REPO / rel).write_text(text, encoding="utf-8", newline="")

    code, tail = _pytest()
    say(f"RESTORED: exit={code}  {tail}")
    say(f"mutants: {len(MUTANTS)}  survived/aborted: {len(survived)}"
        + (f"  -> {survived}" if survived else ""))
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if survived or code != 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
