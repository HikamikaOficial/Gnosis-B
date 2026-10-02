"""Prove the F-17 Stage-2 deployment-identity suite catches the defects it claims.

Each mutant restores a real way for a deployment identity to stop measuring
reality — a file left out of the manifest, an expectation standing in for the
bytes, an observed field quietly dropped from the digest, a missing state
turned into a default, intention substituted for observation, or dynamic code
loading opening a door the closed-world import model cannot see. The targeted
suite must go red for every one of them.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/mutation_check_deployment.py [--out PATH]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEPLOY = "src/gnosis/trust/deployment.py"
SUITE = ["tests/test_deployment_identity.py", "tests/test_trust_boundary.py"]


@dataclass(frozen=True)
class Mutant:
    name: str
    description: str
    edits: list[tuple[str, str, str]] = field(default_factory=list)


MUTANTS: list[Mutant] = [
    Mutant("DM1", "the manifest omits a deployed file, so that file can change unmeasured",
           [(DEPLOY, "        if candidate.is_dir():",
             '        if candidate.is_dir() or candidate.name == "PIPE_POLICY.json":')]),
    Mutant("DM2", "the expected manifest no longer refuses a deployment whose bytes differ",
           [(DEPLOY, "    if missing or extra or changed:",
             "    if False:")]),
    Mutant("DM3", "the service ImagePath is dropped from the identity",
           [(DEPLOY, '                "image_path": self.image_path, "start_type": self.start_type,',
             '                "start_type": self.start_type,')]),
    Mutant("DM4", "the service SID is dropped from the identity",
           [(DEPLOY, '                "service_sid": self.service_sid, "sid_type": self.sid_type,',
             '                "sid_type": self.sid_type,')]),
    Mutant("DM5", "the service SID TYPE is dropped, so RESTRICTED and UNRESTRICTED look alike",
           [(DEPLOY, '                "service_sid": self.service_sid, "sid_type": self.sid_type,',
             '                "service_sid": self.service_sid,')]),
    Mutant("DM6", "a path's DACL is dropped, so re-ACLing the AnchorStore is invisible",
           [(DEPLOY, ('        return {"path": self.path,\n'
                      '                "security_descriptor": self.security_descriptor.to_dict()}'),
             '        return {"path": self.path}')]),
    Mutant("DM7", "the canonicalizer drops deny ACEs as 'redundant'",
           [(DEPLOY, "        base = ace.value or 0",
             ("        if header.AceType == 0x01:  # mutant: drop deny ACEs\n"
              "            continue\n"
              "        base = ace.value or 0"))]),
    Mutant("DM8", "a missing declaration field becomes a default instead of failing closed",
           [(DEPLOY, ("        value = raw.get(field)\n"
                      "        if not isinstance(value, str) or not value:"),
             ('        value = raw.get(field, "unknown")\n'
              "        if False:"))]),
    Mutant("DM9", "the deployment digest stops covering the trusted runtime",
           [(DEPLOY, '                "runtime": self.runtime.to_dict(), "service": self.service.to_dict(),',
             '                "service": self.service.to_dict(),')]),
    Mutant("DM10", "observed state is replaced by the desired config (intention becomes identity)",
           [(DEPLOY, ("    package = observe_trust_package(config.trust_root)\n"
                      "    if config.expected_manifest is not None:\n"
                      "        verify_package_against_expected(package, config.expected_manifest)"),
             "    package = config.expected_manifest or observe_trust_package(config.trust_root)")]),
    Mutant("DM11", "dynamic code loading enters the Trust Plane (the frozen Stage-2 rule)",
           [(DEPLOY, "import ctypes\n",
             "import ctypes\nimport importlib  # mutant: dynamic module loading\n")]),
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

    say("MUTATION CHECK — F-17 Stage 2 trust-plane deployment identity")
    say("=" * 62)
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
