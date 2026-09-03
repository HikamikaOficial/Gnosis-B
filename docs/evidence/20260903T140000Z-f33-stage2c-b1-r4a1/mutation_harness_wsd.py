r"""F-33 Stage 2C-B1-R4A.1 — scoped worker-launch diagnostic mutation set (WSD1-WSD10).

R4A.1 replaces R4A's broad `problems` forwarding with a dedicated, reason-scoped
`OperatorOutcome.worker_launch_diagnostic` that exposes ONLY the single authoritative
`WorkerLaunchFailed` attribution line. These mutants attack that scoping; each is
applied to the pristine file, the guard test node is run, then the file is restored.
WSD10 is structural (F-17 freeze: `worker_launcher.py` diff must stay NONE).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(r"C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi")
PY = REPO / ".venv" / "Scripts" / "python.exe"
COMP = "src/gnosis/director/composition.py"
T1 = "tests/test_stage2cb_b1_r4a1.py"

# Shared anchors in `_worker_launch_diagnostic`.
GUARD = ("    if work.reason_code not in _WORKER_LAUNCH_REASONS:\n"
         "        return None\n"
         "    prefix = work.reason_code.split(\":\", 1)[1] + \": \"   "
         "# e.g. \"WorkerLaunchFailed: \"\n"
         "    for line in work.report.problems_encountered:\n"
         "        if line.startswith(prefix):")
RET = "            return line if len(line) <= _WORKER_LAUNCH_DIAG_MAX else None"

BEHAVIORAL = [
    ("WSD1", "broad forwarding: forward the whole problems list into the field", COMP,
     "                worker_launch_diagnostic=_worker_launch_diagnostic(work))",
     "                worker_launch_diagnostic=\"; \".join(work.report.problems_encountered))",
     f"{T1}::TestPrivacyNegatives::test_reviewer_blocked_does_not_leak"),
    ("WSD2", "activate for ANY pipeline_error:* (not just the worker-launch class)", COMP,
     "    if work.reason_code not in _WORKER_LAUNCH_REASONS:",
     "    if not work.reason_code.startswith(\"pipeline_error:\"):",
     f"{T1}::TestPrivacyNegatives::test_other_pipeline_error_does_not_activate"),
    ("WSD3", "substring activation: match on 'WorkerLaunchFailed' in any problem text",
     COMP, GUARD,
     "    prefix = \"WorkerLaunchFailed\"  # WSD3 substring, reason ignored\n"
     "    for line in work.report.problems_encountered:\n"
     "        if prefix in line:",
     f"{T1}::TestWorkerPositivesAndSelection::test_false_positive_text_not_activated"),
    ("WSD4", "concatenate all problems after finding a worker failure", COMP, RET,
     "            return \"; \".join(work.report.problems_encountered)",
     f"{T1}::TestWorkerPositivesAndSelection::test_multiple_problems_selects_only_launcher_line"),
    ("WSD5", "drop the native winerr from the selected launcher line", COMP, RET,
     "            return line.split(\" (winerr\")[0]",
     f"{T1}::TestWorkerPositivesAndSelection::test_createprocess_positive"),
    ("WSD6", "drop/replace the failing API (stage) in the launcher line", COMP, RET,
     "            return \"worker launch failed (winerr N)\"",
     f"{T1}::TestWorkerPositivesAndSelection::test_createprocess_positive"),
    ("WSD7", "let the diagnostic path claim success (break governed BLOCKED)", COMP,
     "                success=False, task_id=work.task_id, run_id=None,",
     "                success=True, task_id=work.task_id, run_id=None,",
     f"{T1}::TestBoundingSuccessAndGovernance::test_governed_blocked_semantics_preserved"),
    ("WSD8", "expose reviewer finding.description (first problem, reason ignored)",
     COMP, GUARD,
     "    prefix = \"\"  # WSD8 forward first problem regardless of reason/type\n"
     "    for line in work.report.problems_encountered:\n"
     "        if True:",
     f"{T1}::TestPrivacyNegatives::test_reviewer_blocked_does_not_leak"),
    ("WSD9", "expose evidence-failure message (first problem, reason ignored)",
     COMP, GUARD,
     "    prefix = \"\"  # WSD9 forward evidence message regardless of type\n"
     "    for line in work.report.problems_encountered:\n"
     "        if True:",
     f"{T1}::TestPrivacyNegatives::test_evidence_failure_does_not_leak"),
]

STRUCTURAL = [
    ("WSD10", "modify historical F-17 launcher to obtain attribution — caught by the "
     "F-17 freeze: worker_launcher.py diff = NONE (F-17 unchanged); attribution is "
     "surfaced downstream from the already-preserved exception message"),
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
