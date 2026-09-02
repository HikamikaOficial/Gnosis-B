"""F-33 Stage 2C-B1-PRE0 driver mutation set (EDM1-EDM12)."""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(r"C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi")
PY = REPO / ".venv" / "Scripts" / "python.exe"
D = "scripts/run_f33_stage2c_b1_osreal.py"
T = "tests/test_stage2cb_b1_driver.py"

# (id, desc, file, old, new, killing_test) — behavioral, single-replacement mutants
MUTANTS = [
    ("EDM1", "allow os-real without explicit authorization", D,
     "    if execute_os_real and confirm != CONFIRM_TOKEN:",
     "    if execute_os_real and False:  # EDM1",
     f"{T}::TestDriverGates::test_d2_execute_without_auth_is_blocked"),
    ("EDM3", "reobserve returns cached digest (no fresh observation)", D,
     "        return identity.digest()",
     '        return "f" * 64  # EDM3',
     f"{T}::TestDriverBindings::test_d5_real_f17_observer_selected"),
    ("EDM6", "runtime preflight omitted", D,
     '    if not Path(dcfg.runtime_src).is_dir() or not (\n            Path(dcfg.runtime_src) / "python.exe").exists():',
     "    if False:  # EDM6",
     f"{T}::TestDriverGates::test_d8_missing_runtime_src_blocks"),
    ("EDM7", "operator argv reverts to parser-invalid form", D,
     '        return ("run", "--config", str(self.operator_config_path),\n                "--brief", str(self.operator_brief_path))',
     '        return ("run", "--brief", self.stage.run_id)  # EDM7',
     f"{T}::TestOperatorArgv::test_driver_emits_corrected_argv"),
    ("EDM9", "live-call ledger reset to zero", D,
     "        config=dcfg.stage, ops=ops, budget=s.LiveCallBudget(used=dcfg.live_used),",
     "        config=dcfg.stage, ops=ops, budget=s.LiveCallBudget(used=0),  # EDM9",
     f"{T}::TestDriverBindings::test_d12b_run_uses_cumulative_ledger_not_zero"),
    ("EDM10", "active residue record ignored", D,
     '    if rec is not None and rec.status == "active":',
     "    if False:  # EDM10",
     f"{T}::TestDriverGates::test_d4_active_residue_blocks"),
    ("EDM12", "reviewer executable becomes PATH-controlled", D,
     '        "reviewer": {"binary": reviewer_binary},',
     '        "reviewer": {"binary": "claude"},  # EDM12',
     f"{T}::TestDriverBindings::test_d11_production_reviewer_absolute"),
]

STRUCTURAL = {
    "EDM2": "construct real ops before gates — construction is inside "
            "_construct_real_ops_after_gates, AFTER residue+runtime checks; gate-fail "
            "tests (D4/D8/D9) show no construction on failure",
    "EDM4": "observe_fn bypasses real — the os-real branch literally sets "
            "observe_fn=None; None==real observe_deployment proven by "
            "test_observe_fn_none_means_real",
    "EDM5": "runtime_src invalid — a config condition, exercised by D8 (FOLDED)",
    "EDM8": "driver calls cli.main directly — the driver calls Stage2CBOrchestrator; "
            "D10 proves the orchestrator is used",
    "EDM11": "driver duplicates orchestration — D10 proves the qualified "
             "Stage2CBOrchestrator is invoked, not a duplicate",
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
    print(f"\n{caught}/{len(MUTANTS)} applied EDM mutants CAUGHT; "
          f"{len(STRUCTURAL)} structural/folded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
