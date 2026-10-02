r"""F-33 Stage 2C-B1-R3E.1 — canonical config-writer mutation set (CWM1-CWM10).

Behavioral mutants inject a defect into the canonical production writer
(gnosis.director.composition.build_operator_config), the driver delegation, or the
reader (cli.py), and run the guard test that must fail on it. Source is restored.
Structural items are documented (not counted as caught) where the code path simply
does not exist.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(r"C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi")
PY = REPO / ".venv" / "Scripts" / "python.exe"
COMP = "src/gnosis/director/composition.py"
CLI = "src/gnosis/director/cli.py"
DRV = "scripts/run_f33_stage2c_b1_osreal.py"
T = "tests/test_stage2cb_b1_r3e1.py"
TR3E = "tests/test_stage2cb_b1_r3e.py"

BEHAVIORAL = [
    ("CWM1", "canonical writer omits release_id", COMP,
     '            "work_base": lay.work_base, "release_id": lay.release_id,',
     '            "work_base": lay.work_base,',
     f"{T}::TestCanonicalWriter::test_release_id_from_layout_B1"),
    ("CWM2", 'canonical writer hardcodes "B1"', COMP,
     '            "work_base": lay.work_base, "release_id": lay.release_id,',
     '            "work_base": lay.work_base, "release_id": "B1",',
     f"{T}::TestCanonicalWriter::test_release_id_from_layout_R42"),
    ("CWM3", 'canonical writer substitutes "current"', COMP,
     '            "work_base": lay.work_base, "release_id": lay.release_id,',
     '            "work_base": lay.work_base, "release_id": "current",',
     f"{T}::TestCanonicalWriter::test_release_id_from_layout_B1"),
    ("CWM6", "canonical writer reads release_id from environment", COMP,
     '            "work_base": lay.work_base, "release_id": lay.release_id,',
     '            "work_base": lay.work_base, "release_id": __import__("os").environ.get("release_id", lay.release_id),',
     f"{T}::TestCanonicalWriter::test_writer_ignores_environment"),
    ("CWM7", "writer/reader field-name drift (release_id key renamed)", COMP,
     '            "work_base": lay.work_base, "release_id": lay.release_id,',
     '            "work_base": lay.work_base, "release_id_x": lay.release_id,',
     f"{T}::TestWriterReaderRoundtrip::test_roundtrip_B1"),
    ("CWM4", "harness bypasses the canonical writer (local schema)", DRV,
     "    return _canonical_build_operator_config(OperatorConfigInputs(",
     '    return {"deployment": {"code_base": lay.code_base}}  # CWM4 bypass\n    return _canonical_build_operator_config(OperatorConfigInputs(',
     f"{T}::TestDriverDelegates::test_driver_delegates_to_canonical_writer"),
    ("CWM10", 'reader restores implicit "current" on missing field', CLI,
     '        release_id = dep["release_id"]',
     '        release_id = dep.get("release_id", "current")',
     f"{TR3E}::TestFailClosed::test_missing_release_id_fails_closed_not_current"),
]

STRUCTURAL = [
    ("CWM5", "writer takes release_id from brief/work input — build_operator_config "
     "accepts only OperatorConfigInputs(layout=...); there is no brief/work param"),
    ("CWM8", "writer emits wrong release while other roots stay B1 — release_id and "
     "all release-dependent paths derive from the ONE layout; a wrong value is the "
     "CWM2/CWM3 case and is caught by the writer->reader roundtrip"),
    ("CWM9", "a second independent config writer remains active — the driver DELEGATES "
     "(test_driver_delegates asserts import+call, no local schema); no other writer "
     "of the operator config exists in src/ or scripts/"),
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
    print(f"\n{caught}/{len(BEHAVIORAL)} applied behavioral config-writer mutants "
          f"CAUGHT; {len(STRUCTURAL)} structural (documented)")
    return 0 if caught == len(BEHAVIORAL) else 1


if __name__ == "__main__":
    raise SystemExit(main())
