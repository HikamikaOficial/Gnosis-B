r"""F-33 Stage 2C-B1-R3E — release-id plumbing mutation set (RIM1-RIM10).

Behavioral mutants inject a release-identity defect into the F-33 director
(cli.py) and run the guard test that must fail on it. Source is always restored.
Structural items are documented (not counted as caught) where a faithful behavioral
mutation is genuinely impossible — the code path simply does not exist.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(r"C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi")
PY = REPO / ".venv" / "Scripts" / "python.exe"
CLI = "src/gnosis/director/cli.py"
T = "tests/test_stage2cb_b1_r3e.py"

BEHAVIORAL = [
    ("RIM1", "omit release_id when constructing DeploymentLayout", CLI,
     '                                  work_base=dep["work_base"],\n                                  release_id=release_id)',
     '                                  work_base=dep["work_base"])',
     f"{T}::TestReleaseIdReachesLayout::test_actual_release_B1_reconstructed"),
    ("RIM2", 'hardcode release_id="B1"', CLI,
     "                                  release_id=release_id)",
     '                                  release_id="B1")',
     f"{T}::TestReleaseIdReachesLayout::test_arbitrary_release_generalises"),
    ("RIM3", 'restore fallback "current" when release_id missing', CLI,
     '        release_id = dep["release_id"]',
     '        release_id = dep.get("release_id", "current")',
     f"{T}::TestFailClosed::test_missing_release_id_fails_closed_not_current"),
    ("RIM5", "trust an environment override of release_id", CLI,
     '        release_id = dep["release_id"]',
     '        release_id = __import__("os").environ.get("release_id") or dep["release_id"]',
     f"{T}::TestNoUntrustedReleaseSource::test_release_id_comes_from_trusted_config_only"),
    ("RIM6", "parse cwd instead of the authoritative config", CLI,
     '        release_id = dep["release_id"]',
     '        release_id = __import__("pathlib").Path.cwd().name',
     f"{T}::TestReleaseIdReachesLayout::test_actual_release_B1_reconstructed"),
    ("RIM9", "accept a traversal/path-like release id", CLI,
     "        if not (isinstance(release_id, str) and _RELEASE_ID_RE.match(release_id)):",
     "        if False:  # RIM9",
     f"{T}::TestFailClosed::test_invalid_release_ids_rejected"),
]

STRUCTURAL = [
    ("RIM4", "trust release_id from the untrusted brief — build_operator_composition "
     "reads release_id ONLY from the trusted config's `dep`; the brief is not in "
     "scope, so there is no brief-reading path to mutate"),
    ("RIM7", "allow a wrong release and probe/fallback to another root — no "
     "directory-probing loop exists; a single authoritative release_id is used and "
     "a wrong one fails at observe_deployment (no fallback)"),
    ("RIM8", "skip operator self-observation — observe_deployment's result "
     "(deployment_identity) is consumed downstream; removing it breaks composition "
     "construction, and the capture tests require it to be called"),
    ("RIM10", "use source-checkout release metadata at runtime — release_id is read "
     "from the deployed trusted config only; no source/checkout read exists "
     "(checkout-independence is structural)"),
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
    print(f"\n{caught}/{len(BEHAVIORAL)} applied behavioral release-id mutants CAUGHT; "
          f"{len(STRUCTURAL)} structural (documented)")
    return 0 if caught == len(BEHAVIORAL) else 1


if __name__ == "__main__":
    raise SystemExit(main())
