"""F-33 Stage 2C-B1-R1 mutation set: PBM1-5 (pipe readiness) + RBM1-4 (cleanup)."""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(r"C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi")
PY = REPO / ".venv" / "Scripts" / "python.exe"
CB = "scripts/stage2cb.py"
OPS = "scripts/stage2cb_ops.py"
DRV = "scripts/run_f33_stage2c_b1_osreal.py"
TR = "tests/test_stage2cb_b1_r1.py::TestPipeReadiness"
TC = "tests/test_stage2cb_b1_r1.py::TestCanonicalPipeName"
TS = "tests/test_stage2cb_b1_r1.py::TestDriverScaffoldCleanup"

MUTANTS = [
    ("PBM1", "one-shot check (no poll loop)", CB,
     "    while polls < max_polls:",
     "    while polls < 1:  # PBM1",
     f"{TR}::test_p2_ready_after_multiple_polls"),
    ("PBM2", "timeout accepted as success", CB,
     '        if now() - start >= timeout_s:\n            return ReadinessResult(False, "timeout", polls, now() - start)',
     '        if now() - start >= timeout_s:\n            return ReadinessResult(True, "timeout", polls, now() - start)  # PBM2',
     f"{TR}::test_p3_never_ready_times_out"),
    ("PBM4", "ignore Publisher death", CB,
     '        if not service_alive():\n            return ReadinessResult(False, "service-died", polls, now() - start)',
     '        if False:  # PBM4\n            return ReadinessResult(False, "service-died", polls, now() - start)',
     f"{TR}::test_p4_publisher_dies_immediate_fail"),
    ("PBM5", "unbounded readiness (no timeout)", CB,
     '        if now() - start >= timeout_s:\n            return ReadinessResult(False, "timeout", polls, now() - start)',
     '        if now() - start >= 10**12:  # PBM5 (effectively unbounded)\n            return ReadinessResult(False, "timeout", polls, now() - start)',
     f"{TR}::test_p7_timeout_is_bounded_finite_polls"),
    ("PBM3", "real pipe_ready re-prefixes / wrong pipe", OPS,
     "            pipe_exists=lambda: Path(pipe_name).exists(),",
     '            pipe_exists=lambda: Path(rf"\\\\.\\pipe\\{pipe_name}").exists(),  # PBM3',
     f"{TC}::test_real_pipe_ready_uses_exact_path_not_reprefixed"),
    ("RBM1", "omit driver scaffold cleanup", DRV,
     "    _sh.rmtree(scaffold_root, ignore_errors=True)",
     "    pass  # RBM1 (no scaffold cleanup)",
     f"{TS}::test_success_self_cleans_scaffold"),
    ("RBM2", "clean scaffold despite residue present", DRV,
     '    if residue_present:\n        trace["scaffold_cleanup"] = "RETAINED (residue record present; recover first)"\n        return',
     '    if False:  # RBM2\n        trace["scaffold_cleanup"] = "RETAINED (residue record present; recover first)"\n        return',
     f"{TS}::test_retained_when_residue_present"),
    ("RBM4", "report 'removed' even when cleanup failed (false clean)", DRV,
     '    trace["scaffold_cleanup"] = ("removed" if not scaffold_root.exists()\n                                 else "FAILED (residue present)")',
     '    trace["scaffold_cleanup"] = "removed"  # RBM4 (unconditional false clean)',
     f"{TS}::test_cleanup_failure_reports_failed_not_removed"),
]

STRUCTURAL = {
    "RBM3": "broad-prefix cleanup — scaffold_root is the EXACT run-bound "
            "code_base.parent; test_scaffold_root_is_exact_owned_parent proves all "
            "nested driver artifacts are under that one owned root (no glob/prefix)",
}


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
    for mid, why in STRUCTURAL.items():
        print(f"{mid}: STRUCTURAL — {why}")
    print(f"\n{caught}/{len(MUTANTS)} applied mutants CAUGHT; {len(STRUCTURAL)} structural")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
