r"""F-33 Stage 2C-B1-R4A — worker-launch diagnostic mutation set (WDM1-WDM10).

The R4A diagnostic surfaces the governed report's `problems_encountered` verbatim
(which already contains the F-17 failing call/stage + native winerr) through
`OperatorOutcome` -> the operator record. Behavioral mutants attack that surfacing;
structural items are documented where the minimal verbatim-passthrough diagnostic has
no code to mutate (stage/process/token are ENCODED in the F-17 message it forwards) or
where a mutation would require editing frozen F-17.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(r"C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi")
PY = REPO / ".venv" / "Scripts" / "python.exe"
COMP = "src/gnosis/director/composition.py"
CLI = "src/gnosis/director/cli.py"
T = "tests/test_stage2cb_b1_r4a.py"

BEHAVIORAL = [
    ("WDM1", "drop the native code/message from the diagnostic extraction", COMP,
     "                       \"no publication attempted\",\n                problems=work.report.problems_encountered)",
     "                       \"no publication attempted\",\n                problems=())",
     f"{T}::TestAttribution::test_worker_failure_stage_and_winerr_surfaced"),
    ("WDM2", "transform/truncate the message (corrupt stage/winerr)", COMP,
     "                       \"no publication attempted\",\n                problems=work.report.problems_encountered)",
     "                       \"no publication attempted\",\n                problems=tuple(p[:5] for p in work.report.problems_encountered))",
     f"{T}::TestAttribution::test_problems_surfaced_verbatim_no_transform"),
    ("WDM4", "hide the winerr in the operator record", CLI,
     '        "problems": list(outcome.problems),',
     '        "problems": [],',
     f"{T}::TestCliRecordSurfacesProblems::test_run_record_includes_problems_and_blocked_exit"),
    ("WDM8", "skip the governed BLOCKED mapping (claim success)", COMP,
     "                success=False, task_id=work.task_id, run_id=None,",
     "                success=True, task_id=work.task_id, run_id=None,",
     f"{T}::TestAttribution::test_governed_blocked_preserved"),
]

STRUCTURAL = [
    ("WDM3", "always claim process_created=false — the diagnostic surfaces the F-17 "
     "message which ENCODES the failing call (CreateProcessWithLogonW = not created; "
     "AssignProcessToJobObject = created-then-failed); no separate boolean to falsify"),
    ("WDM5", "diagnostic failure suppresses WorkerLaunchFailed — the BLOCKED decision "
     "is computed from work.status; `problems` is a pure attr read that cannot alter "
     "success/work_status (test_governed_blocked_preserved)"),
    ("WDM6", "log secret credential material — the diagnostic forwards problems "
     "verbatim and adds no new source; it cannot introduce secrets the report lacked "
     "(test_secret_safety_passthrough_only)"),
    ("WDM7", "retry/fallback after launch failure — no retry/fallback code added; the "
     "outcome is a single OperatorOutcome"),
    ("WDM9", "alter the LaunchSpec while observing — the diagnostic never touches the "
     "LaunchSpec/runner (BLOCKED branch returns before runner access)"),
    ("WDM10", "modify historical F-17 launcher to obtain PASS — caught by the F-17 "
     "freeze: worker_launcher.py diff = NONE (F-17 unchanged)"),
]


def run_test(node: str) -> bool:
    p = subprocess.run([str(PY), "-m", "pytest", node, "-q", "--no-header",
                        "-p", "no:cacheprovider"], cwd=REPO, capture_output=True, text=True)
    return p.returncode == 0


def main() -> int:
    caught = 0
    for mid, desc, rel, old, new, node in BEHAVIORAL:
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
    for mid, why in STRUCTURAL:
        print(f"{mid}: STRUCTURAL — {why}")
    print(f"\n{caught}/{len(BEHAVIORAL)} applied behavioral worker-diagnostic mutants "
          f"CAUGHT; {len(STRUCTURAL)} structural (documented)")
    return 0 if caught == len(BEHAVIORAL) else 1


if __name__ == "__main__":
    raise SystemExit(main())
