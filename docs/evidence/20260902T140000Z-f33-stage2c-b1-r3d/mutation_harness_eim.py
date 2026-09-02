r"""F-33 Stage 2C-B1-R3D — effective-identity mutation set (EIM1-EIM14).

Behavioral mutants inject a trust-binding defect into the production composed
identity (gnosis_deployment.py) and run the guard test that must fail on it. Source
is always restored. Several EIM items are STRUCTURAL: the composed binding is the
single authoritative check that binds base+application+effective, so some individual
launch checks are backstopped by it (defense in depth) and are guarded by the
message-asserting behavioral tests / existing property tests rather than by a lone
"launch-passes" mutation. Those are listed explicitly, not silently claimed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(r"C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi")
PY = REPO / ".venv" / "Scripts" / "python.exe"
GD = "src/gnosis/provision/gnosis_deployment.py"
T = "tests/test_stage2cb_b1_r3d.py"

BEHAVIORAL = [
    ("EIM1", "omit effective from the composed binding formula", GD,
     '        "effective_deployment_digest": effective_deployment_digest,\n    }, separators=(",", ":"), sort_keys=True)',
     '    }, separators=(",", ":"), sort_keys=True)',
     f"{T}::TestEffectiveIdentity::test_binding_uses_all_three_identities"),
    ("EIM2", "reuse the pre-app base digest as the effective identity", GD,
     "            effective = self._observe_effective()",
     "            effective = base.deployment_digest  # EIM2",
     f"{T}::TestEffectiveIdentity::test_record_carries_distinct_base_and_effective"),
    ("EIM4", "accept an old/unknown record schema", GD,
     '    if data["schema"] != COMPOSED_RECORD_SCHEMA:',
     "    if False:  # EIM4",
     f"{T}::TestCanonicalLaunchEffective::test_wrong_schema_right_keys_rejected"),
    ("EIM6", "skip the record application-digest check at launch", GD,
     '        if measured != record.application_tree_digest:\n            raise GnosisDeploymentError(\n                "re-measured application tree digest does not match the trusted record")\n        # (4) measured operator entry + canonical worker image present & measured.',
     '        if False:  # EIM6\n            raise GnosisDeploymentError(\n                "re-measured application tree digest does not match the trusted record")\n        # (4) measured operator entry + canonical worker image present & measured.',
     f"{T}::TestCanonicalLaunchEffective::test_coherent_app_tamper_caught_by_record"),
    ("EIM7", "skip the fresh effective whole-root check at launch", GD,
     "        if observed_effective != record.effective_deployment_digest:",
     "        if False:  # EIM7",
     f"{T}::TestCanonicalLaunchEffective::test_whole_root_change_refused"),
    ("EIM9", "skip the record composed-binding consistency check", GD,
     '    if composed_deployment_digest(data["f17_deployment_digest"],\n                                  data["application_tree_digest"],\n                                  data["effective_deployment_digest"]) != data[\n            "composed_deployment_digest"]:',
     "    if False:  # EIM9",
     f"{T}::TestRecordSchema::test_mix_and_match_operands_rejected"),
]

# STRUCTURAL / covered-by-property (documented, not claimed as applied-and-caught):
STRUCTURAL = [
    ("EIM3", "measure effective before deploy — reorder, not a 1-line mutation; "
     "guarded by test_effective_measured_after_app_deploy (asserts app present)"),
    ("EIM5", "update trusted digest after mismatch — canonical_launch performs NO "
     "record write (grep: no write_text/_atomic_write_json in canonical_launch)"),
    ("EIM8", "ignore an extra file — an extra importable file changes the whole-root "
     "effective identity; identical mechanism to EIM7 (test_whole_root_change_refused)"),
    ("EIM10", "remove effective operand from composed — identical to EIM1 at the "
     "formula (test_binding_uses_all_three_identities)"),
    ("EIM11", "substrate mutation after record — changes the whole-root effective "
     "identity; caught by the effective check (EIM7 mechanism)"),
    ("EIM12", "application mutation after record — caught by measure() / the record "
     "app check (test_application_tamper_still_refused / EIM6)"),
    ("EIM13", "move verification after spawn — spawn is the final statement; the "
     "checks precede it structurally (canonical_launch source ordering)"),
    ("EIM14", "content-only effective observer — the observer is production "
     "observe_deployment (full canonical identity, incl. SDDL/paths), injected, not "
     "a gnosis_deployment mutation; the effective digest is whatever it returns"),
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
    print(f"\n{caught}/{len(BEHAVIORAL)} applied behavioral effective-identity "
          f"mutants CAUGHT; {len(STRUCTURAL)} structural (documented)")
    return 0 if caught == len(BEHAVIORAL) else 1


if __name__ == "__main__":
    raise SystemExit(main())
