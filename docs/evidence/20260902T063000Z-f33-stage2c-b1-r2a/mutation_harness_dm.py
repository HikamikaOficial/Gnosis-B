"""F-33 Stage 2C-B1-R2A diagnostic mutation set (DM1-DM6)."""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(r"C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi")
PY = REPO / ".venv" / "Scripts" / "python.exe"
CB = "scripts/stage2cb.py"
T = "tests/test_stage2cb_b1_r2a.py::TestPublisherFailureClassifier"

MUTANTS = [
    ("DM1", "collapse a distinct failure into a generic class", CB,
     '        return "SERVICE PROCESS START FAILURE"',
     '        return "AMBIGUOUS"  # DM1',
     f"{T}::test_dia1_service_dies_before_pipe"),
    ("DM2", "report service RUNNING when it is not", CB,
     '    running = bool(postmortem.get("service_running_observed"))',
     "    running = True  # DM2",
     f"{T}::test_dm2_guard_timeout_not_running_is_start_failure"),
    ("DM3", "omit service exit-code post-mortem influence", CB,
     '        if isinstance(exit_code, int) and exit_code != 0:\n            return "SERVICE PROCESS EARLY EXIT"',
     "        if False:  # DM3\n            return \"SERVICE PROCESS EARLY EXIT\"",
     f"{T}::test_early_exit_distinct"),
    ("DM4", "report access PASS without checking (ignore FAIL)", CB,
     '        if postmortem.get("access_contract") == "FAIL":',
     "        if False:  # DM4",
     f"{T}::test_dia5_inaccessible_path"),
    ("DM5", "classify temp topology as root cause from path string", CB,
     '    reason = readiness.get("terminal_reason")',
     '    if "Temp" in str(postmortem.get("deployment_root", "")):  # DM5\n        return "DEPLOYMENT/ANCESTOR ACCESS FAILURE"\n    reason = readiness.get("terminal_reason")',
     f"{T}::test_dm5_guard_temp_path_not_root_cause"),
    ("DM6", "hide observation error and report generic", CB,
     '    if reason == "observation-error":\n        return "READINESS OBSERVATION FAILURE"',
     '    if False:  # DM6\n        return "READINESS OBSERVATION FAILURE"',
     f"{T}::test_dia3_observation_error"),
]


def run_test(node: str) -> bool:
    p = subprocess.run([str(PY), "-m", "pytest", node, "-q", "--no-header",
                        "-p", "no:cacheprovider"], cwd=REPO, capture_output=True, text=True)
    return p.returncode == 0


def main() -> int:
    caught = 0
    for mid, desc, rel, old, new, node in MUTANTS:
        path = REPO / rel
        original = path.read_text(encoding="utf-8")
        if old not in original:
            print(f"{mid}: NOT APPLIED (anchor) — {desc}")
            continue
        try:
            path.write_text(original.replace(old, new, 1), encoding="utf-8")
            passed = run_test(node)
        finally:
            path.write_text(original, encoding="utf-8")
        v = "CAUGHT" if not passed else "SURVIVED"
        caught += v == "CAUGHT"
        print(f"{mid}: APPLIED / {v}  ({desc})")
    print(f"\n{caught}/{len(MUTANTS)} applied diagnostic mutants CAUGHT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
