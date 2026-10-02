r"""F-33 Stage 2C-B1-R3B — identity-delta diagnostics mutation set (DDM1-DDM8).

Each mutant injects a gate-preservation or delta-truthfulness defect into the R3B
instrumentation and runs the guarding test that must fail on it. Source is always
restored. A mutant is CAUGHT when the guard fails.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(r"C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi")
PY = REPO / ".venv" / "Scripts" / "python.exe"
IDD = "scripts/identity_delta.py"
DRV = "scripts/run_f33_stage2c_b1_osreal.py"
T = "tests/test_stage2cb_b1_r3b.py"

MUTANTS = [
    ("DDM1", "use launch observation as both sides of the diff", IDD,
     "    components: dict[str, str] = {}",
     "    provision = launch  # DDM1\n    components: dict[str, str] = {}",
     f"{T}::TestClassify::test_package_content_changed"),
    ("DDM2", "digests_match lies (mask a real digest mismatch)", IDD,
     '"digests_match": bool(prov_dig is not None and prov_dig == launch_dig),',
     '"digests_match": True,  # DDM2',
     f"{T}::TestRecorder::test_digests_match_reflects_reality"),
    ("DDM3", "write diagnostics inside an observed root", IDD,
     "        prov_id = self.provision[\"identity\"] if self.provision else None",
     "        import pathlib; pathlib.Path('diag.json').write_text('x')  # DDM3\n"
     "        prov_id = self.provision[\"identity\"] if self.provision else None",
     f"{T}::TestRecorder::test_recorder_does_no_filesystem_io"),
    ("DDM4", "report only the first changed component; hide the rest", IDD,
     "    for key in sorted(set(provision) | set(launch)):",
     "    for key in sorted(set(provision) | set(launch))[:1]:  # DDM4",
     f"{T}::TestClassify::test_multiple_components"),
    ("DDM5", "ignore SDDL / security-descriptor changes", IDD,
     '        if (("security_descriptor" in pv_d or "security_descriptor" in lv_d)\n'
     '                and pv_d.get("security_descriptor") != lv_d.get("security_descriptor")):',
     "        if False:  # DDM5 (body kept, condition disabled)",
     f"{T}::TestClassify::test_store_security_changed"),
    ("DDM6", "ignore content-manifest (tree) changes", IDD,
     '        if "files" in pv_d or "files" in lv_d:',
     "        if False:  # DDM6",
     f"{T}::TestClassify::test_package_content_changed"),
    ("DDM7", "treat a diagnostics failure as permission to continue", DRV,
     "            except Exception:  # noqa: BLE001,S110  diagnostics never break the gate\n                pass",
     "            except Exception:  # noqa: BLE001,S110\n                return 'DDM7-BYPASS'",
     f"{T}::TestGatePreservingReobserve::test_reobserve_returns_digest_even_if_record_raises"),
    ("DDM8", "reobserve twice; diff the wrong (later) observation", DRV,
     "                recorder.record_launch(identity)",
     "                recorder.record_launch(observe_deployment(DesiredDeploymentConfig("
     "trust_root=Path(lay.trust_root), runtime_executable=Path(lay.runtime_executable), "
     "runtime_root=Path(lay.runtime_root), runidentity_store=Path(lay.runidentity_root), "
     "anchorstore=Path(lay.anchors_root), service_name=cfg.service_name)))  # DDM8",
     f"{T}::TestGatePreservingReobserve::test_reobserve_records_the_gate_observation"),
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
    print(f"\n{caught}/{len(MUTANTS)} applied identity-delta mutants CAUGHT")
    return 0 if caught == len(MUTANTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
