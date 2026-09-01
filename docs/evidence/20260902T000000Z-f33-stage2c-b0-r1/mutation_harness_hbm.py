"""F-33 Stage 2C-B0-R1 harness mutation set (HBM1-HBM16)."""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(r"C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi")
PY = REPO / ".venv" / "Scripts" / "python.exe"
CB = "scripts/stage2cb.py"
OPS = "scripts/stage2cb_ops.py"
T = "tests/test_stage2cb_backend.py"

MUTANTS = [
    ("HBM1", "dry OS guard removed", OPS,
     "        if not authorized:", "        if False:",
     f"{T}::TestGuardsAndJournal::test_windows_real_ops_guarded"),
    ("HBM2", "reviewer env allowlist bypassed", CB,
     "    return {k: full_env[k] for k in _REVIEWER_ENV_ALLOW if k in full_env}",
     "    return dict(full_env)",
     f"{T}::TestRouteAndEnv::test_reviewer_env_is_allowlist"),
    ("HBM3", "account rollback registration removed", CB,
     '            journal.register("f17-uninstall", base.rollback)',
     "            pass  # HBM3",
     f"{T}::TestFailureInjection::test_post_base_failure_actually_deletes_worker"),
    ("HBM4", "service rollback registration removed", CB,
     '            journal.register("service-stop",\n                             lambda: self.ops.service_stop(self.config.service_name))',
     "            pass  # HBM4",
     f"{T}::TestFailureInjection::test_post_service_failure_actually_stops_service"),
    ("HBM5", "cleanup unrelated resource permitted", CB,
     "    return (manifest.worker_username == config.worker_username",
     "    return True or (manifest.worker_username == config.worker_username",
     f"{T}::TestResidueAndRecovery::test_recovery_refuses_on_ownership_mismatch"),
    ("HBM6", "rollback failure ignored", CB,
     "        return (not failures), failures",
     "        return True, []  # HBM6",
     f"{T}::TestCleanupFailure::test_worker_delete_cleanup_failure_reports_residue"),
    ("HBM7", "provider ledger reset", CB,
     "        self.used += 1\n        return self.used",
     "        self.used = 0\n        return self.used  # HBM7",
     f"{T}::TestBudget::test_consume_enforces_ceiling"),
    ("HBM8", ">5 calls permitted", CB,
     "        return self.used + n <= self.max_total",
     "        return True  # HBM8",
     f"{T}::TestBudget::test_boundaries"),
    ("HBM10", "spawn=False selected", CB,
     "                        comp, reobserve_f17=self.reobserve_f17, spawn=True,",
     "                        comp, reobserve_f17=self.reobserve_f17, spawn=False,  # HBM10",
     f"{T}::TestPositiveSimulatedB1::test_spawn_true_and_pipe_publisher_selected"),
    ("HBM11", "InProcessPublisherClient selected", CB,
     'publisher_client="gnosis.director.publisher_client.PipePublisherClient"',
     'publisher_client="gnosis.director.publisher_client.InProcessPublisherClient"',
     f"{T}::TestPositiveSimulatedB1::test_spawn_true_and_pipe_publisher_selected"),
    ("HBM12", "worker env keeps provider secrets", CB,
     '    denied = ("ANTHROPIC", "CLAUDE", "AWS", "OPENAI")',
     "    denied = ()  # HBM12",
     f"{T}::TestRouteAndEnv::test_worker_env_strips_provider_secrets"),
    ("HBM13", "OSREAL bypasses F-17 Provisioner (fabricated digest)", CB,
     "                              deployment_digest=result.deployment_digest,",
     '                              deployment_digest="0" * 64,  # HBM13',
     f"{T}::TestGuardsAndJournal::test_base_provision_returns_observed_digest"),
    ("HBM14", "unimplemented on live path", OPS,
     '        rc, out = self._f17.run(["sc.exe", "start", name])',
     '        raise NotImplementedError("later")  # HBM14',
     f"{T}::TestGuardsAndJournal::test_no_unimplemented_on_live_path"),
    ("HBM16", "worker path bypasses F-17 launcher", CB,
     '        worker_path="gnosis.director.trusted_runner.TrustedExecutionRunner"\n                    " -> gnosis.trust.worker_launcher",',
     '        worker_path="subprocess.Popen",  # HBM16',
     f"{T}::TestPositiveSimulatedB1::test_spawn_true_and_pipe_publisher_selected"),
]


def run_test(node: str) -> bool:
    p = subprocess.run([str(PY), "-m", "pytest", node, "-q", "--no-header",
                        "-p", "no:cacheprovider"], cwd=REPO, capture_output=True, text=True)
    return p.returncode == 0


def main() -> int:
    results = []
    for mid, desc, rel, old, new, node in MUTANTS:
        path = REPO / rel
        original = path.read_text(encoding="utf-8")
        if old not in original:
            results.append((mid, "NOT_APPLIED"))
            print(f"{mid}: NOT APPLIED (anchor) — {desc}")
            continue
        try:
            path.write_text(original.replace(old, new, 1), encoding="utf-8")
            passed = run_test(node)
        finally:
            path.write_text(original, encoding="utf-8")
        v = "CAUGHT" if not passed else "SURVIVED"
        results.append((mid, v))
        print(f"{mid}: {v}  ({desc})")
    caught = sum(1 for _, v in results if v == "CAUGHT")
    print(f"\n{caught}/{len(results)} applied HBM mutants CAUGHT")
    print("STRUCTURAL: HBM9 (canonical GnosisDeploymentProvisioner used), "
          "HBM15 (reviewer runs in operator subprocess; route selects production runner)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
