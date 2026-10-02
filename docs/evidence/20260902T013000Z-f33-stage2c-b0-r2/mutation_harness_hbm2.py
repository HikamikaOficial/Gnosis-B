"""F-33 Stage 2C-B0-R2 residue-persistence mutation set (HBM17-HBM20)."""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(r"C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi")
PY = REPO / ".venv" / "Scripts" / "python.exe"
CB = "scripts/stage2cb.py"
T = "tests/test_stage2cb_backend.py"
TC = f"{T}::TestCrashPersistentResidue"

MUTANTS = [
    ("HBM17", "do not persist residue manifest before first acquisition", CB,
     "            if self.residue_store is not None:\n                self.residue_store.write_initial(self.config)",
     "            pass  # HBM17 (no initial persist)",
     f"{TC}::test_manifest_persisted_before_first_acquisition"),
    ("HBM18", "resource acquired but persisted state never updated", CB,
     "            if self.residue_store is not None:\n                self.residue_store.mark_acquired(self._persistent_identities())",
     "            pass  # HBM18 (no acquired update)",
     f"{TC}::test_acquisition_persisted_incrementally"),
    ("HBM19", "delete residue manifest before rollback fully succeeded", CB,
     "        if rec2 is not None and all(not r.acquired for r in rec2.resources):\n            store.retire()",
     "        store.retire()  # HBM19 (always retire)",
     f"{TC}::test_failed_rollback_keeps_record_with_remaining_residue"),
    ("HBM20", "recovery cleans a resource with ambiguous/unproven ownership", CB,
     '    if ambiguous:\n        return "AMBIGUOUS_RESIDUE", []',
     '    if False:  # HBM20\n        return "AMBIGUOUS_RESIDUE", []',
     f"{TC}::test_recovery_refuses_ambiguous_ownership"),
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
        print(f"{mid}: {v}  ({desc})")
    print(f"\n{caught}/{len(MUTANTS)} residue mutants CAUGHT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
