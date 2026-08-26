"""Prove the F-17 OS-authority-boundary suite catches the defects it claims.

Each mutant restores a real defect in the authority boundary or the anchor
protocol; the targeted suite must go red. The OS-boundary mutants (AM1/AM2)
require an elevated (High) run, exactly like the tests they exercise.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/mutation_check_authority.py [--out PATH]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AUTH = "src/gnosis/kernel/authority.py"
SUITE = ["tests/test_authority_boundary.py"]


@dataclass(frozen=True)
class Mutant:
    name: str
    description: str
    edits: list[tuple[str, str, str]] = field(default_factory=list)


MUTANTS: list[Mutant] = [
    Mutant("AM1", "the worker is launched at HIGH, not Medium, so it can write the anchor",
           [(AUTH, "token = lowered_primary_token(sid_string)",
             "token = lowered_primary_token(SID_HIGH)")]),
    Mutant("AM2", "the AnchorStore is labelled Medium, not High, so a Medium worker writes it",
           [(AUTH, '"/setintegritylevel", "(OI)(CI)High"',
             '"/setintegritylevel", "(OI)(CI)Medium"')]),
    Mutant("AM3", "publish stops binding the bundle to the run's head, so a cross-run/replay bundle anchors",
           [(AUTH, "    if bound is None or bound != identity.head_sha:",
             "    if bound is None:")]),
    Mutant("AM4", "publish stops checking self-consistency, so a broken bundle anchors",
           [(AUTH, '    if not getattr(result, "verified", False):\n'
                   '        raise AuthorityUnavailable("bundle is not self-consistent; refusing to anchor it")',
             '    if False:\n'
             '        raise AuthorityUnavailable("bundle is not self-consistent; refusing to anchor it")')]),
    Mutant("AM5", "verify stops re-verifying the chain, so a broken chain still verifies",
           [(AUTH, "    if not store.verify_chain():\n"
                   '        raise AuthorityUnavailable("the anchor chain does not verify")',
             "    if False:\n"
             '        raise AuthorityUnavailable("the anchor chain does not verify")')]),
    Mutant("AM6", "verify accepts a missing anchor record instead of failing closed",
           [(AUTH, "    if record is None:\n"
                   '        raise AuthorityUnavailable(f"no anchor record for run {run_id}; fail closed")',
             "    if False:\n"
             '        raise AuthorityUnavailable(f"no anchor record for run {run_id}; fail closed")')]),
    Mutant("AM7", "append stops requiring a record to extend the chain",
           [(AUTH, "        if record.seq != len(existing) or record.prev_record_digest != expected_prev:",
             "        if False:")]),
    Mutant("AM8", "assert_integrity stops failing closed, so a worker at the wrong (High) level proceeds",
           [(AUTH, "    actual = process_integrity()\n    if actual != expected:",
             "    actual = process_integrity()\n    if False:")]),
]


def _pytest() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, "-m", "pytest", *SUITE, "-q", "-x"],
                          cwd=REPO, capture_output=True, text=True, check=False)
    tail = (proc.stdout.strip().splitlines() or [""])[-1][:200]
    return proc.returncode, tail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    lines: list[str] = []

    def say(t: str = "") -> None:
        print(t, flush=True)
        lines.append(t)

    say("MUTATION CHECK — F-17 OS authority boundary")
    say("=" * 60)
    say(f"targeted suite: {' '.join(SUITE)}")
    say("")
    originals = {rel: (REPO / rel).read_text(encoding="utf-8")
                 for rel in {e[0] for m in MUTANTS for e in m.edits}}
    code, tail = _pytest()
    say(f"BASELINE (repair in place): exit={code}  {tail}")
    if code != 0:
        say("ABORTED: baseline not green.")
        if args.out:
            args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1
    say("")
    survived: list[str] = []
    try:
        for m in MUTANTS:
            applied = True
            for rel, old, new in m.edits:
                src = (REPO / rel).read_text(encoding="utf-8")
                if old not in src:
                    applied = False
                    break
                (REPO / rel).write_text(src.replace(old, new, 1), encoding="utf-8", newline="")
            if not applied:
                survived.append(f"{m.name} (NOT APPLIED)")
                say(f"{m.name}: {m.description}\n  verdict: NOT APPLIED")
            else:
                code, tail = _pytest()
                say(f"{m.name}: {m.description}")
                say(f"  result: exit={code}  {tail}")
                say(f"  verdict: {'CAUGHT' if code != 0 else 'SURVIVED'}")
                if code == 0:
                    survived.append(m.name)
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
