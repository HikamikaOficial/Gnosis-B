"""F-33 Stage 2C-B1-R2A — Publisher startup / pipe-failure diagnostics.

Diagnostics/evidence plumbing only; no OS provisioning, no provider calls, no
behavior/topology/timeout change. Proves the trace can establish the actual
Publisher-pipe failure mechanism instead of a generic "pipe not ready".
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "scripts", REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import run_f33_stage2c_b1_osreal as drv
import stage2cb as s
import stage2cb_ops as sops

F17D = "f" * 64


def _pm(**over):
    # default access_contract is UNKNOWN: the R2B producer never asserts a
    # positive access contract from leaf icacls evidence (no false PASS).
    base = {"service_running_observed": False, "runtime_exe_exists": True,
            "service_entry_exists": True, "config_path_exists": True,
            "access_contract": "UNKNOWN", "service_exit_code": 0,
            "deployment_root": r"C:\Users\x\AppData\Local\Temp\gnosis-2cb-b1-run-b1-1"}
    base.update(over)
    return base


class TestPublisherFailureClassifier(unittest.TestCase):
    def test_dia1_service_dies_before_pipe(self) -> None:
        self.assertEqual(s.classify_publisher_failure(
            {"terminal_reason": "service-died"}, _pm(service_running_observed=False)),
            "SERVICE PROCESS START FAILURE")

    def test_dia2_service_running_pipe_times_out(self) -> None:
        self.assertEqual(s.classify_publisher_failure(
            {"terminal_reason": "timeout"}, _pm(service_running_observed=True)),
            "PIPE SERVER INITIALIZATION FAILURE")

    def test_dia3_observation_error(self) -> None:
        self.assertEqual(s.classify_publisher_failure(
            {"terminal_reason": "observation-error"}, _pm()),
            "READINESS OBSERVATION FAILURE")

    def test_dia4_missing_runtime(self) -> None:
        self.assertEqual(s.classify_publisher_failure(
            {"terminal_reason": "service-died"}, _pm(runtime_exe_exists=False)),
            "RUNTIME EXECUTION FAILURE")

    def test_dia5_inaccessible_path(self) -> None:
        # R2B: the access-failure branch requires an AUTHORITATIVE denial, so the
        # fixture injects a proven deny (verdict DIRECTLY-DENIED), not a weak
        # substring-negative. The semantic requirement is unchanged.
        self.assertEqual(s.classify_publisher_failure(
            {"terminal_reason": "service-died"},
            _pm(access_contract="FAIL",
                access_detail={"verdict": "DIRECTLY-DENIED",
                               "deny_semantics_proven": True})),
            "DEPLOYMENT/ANCESTOR ACCESS FAILURE")

    def test_dia6_config_inconsistency(self) -> None:
        self.assertEqual(s.classify_publisher_failure(
            {"terminal_reason": "service-died"}, _pm(config_path_exists=False)),
            "PUBLISHER CONFIGURATION FAILURE")

    def test_dia7_healthy_delayed_pipe_ready(self) -> None:
        self.assertEqual(s.classify_publisher_failure(
            {"terminal_reason": "ready"}, _pm(service_running_observed=True)), "READY")

    def test_early_exit_distinct(self) -> None:
        self.assertEqual(s.classify_publisher_failure(
            {"terminal_reason": "service-died"},
            _pm(service_running_observed=False, service_exit_code=3)),
            "SERVICE PROCESS EARLY EXIT")

    def test_dm2_guard_timeout_not_running_is_start_failure(self) -> None:
        # timeout but service NOT running -> start failure (guards DM2 that would
        # falsely report RUNNING and misclassify as pipe-init).
        self.assertEqual(s.classify_publisher_failure(
            {"terminal_reason": "timeout"}, _pm(service_running_observed=False)),
            "SERVICE PROCESS START FAILURE")

    def test_dm5_guard_temp_path_not_root_cause(self) -> None:
        # a temp deployment_root with access_contract PASS + running service must
        # NOT be classified as an access/topology failure from the path alone.
        cls = s.classify_publisher_failure(
            {"terminal_reason": "timeout"},
            _pm(service_running_observed=True, access_contract="PASS",
                deployment_root=r"C:\Users\x\AppData\Local\Temp\gnosis-2cb-b1-run-b1-1"))
        self.assertNotEqual(cls, "DEPLOYMENT/ANCESTOR ACCESS FAILURE")
        self.assertEqual(cls, "PIPE SERVER INITIALIZATION FAILURE")


class TestOrchestratorCapturesDiagnostics(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dcfg = drv.default_driver_config(
            Path(self.tmp.name) / "gnosis-2cb-b1-run-b1-1", live_used=1)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_pipe_failure_populates_structured_diagnostics(self) -> None:
        ops = sops.DryOperations(
            pipe_not_ready=True, readiness_reason="timeout",
            postmortem=_pm(service_running_observed=True, access_contract="PASS"))
        t = drv.run_driver(self.dcfg, execute_os_real=False, confirm="",
                           expected_head_sha=drv.expected_head(), dry_ops=ops)
        o = t["orchestration"]
        self.assertFalse(o["success"])
        self.assertIsNotNone(o["pipe_readiness"])
        self.assertEqual(o["pipe_readiness"]["terminal_reason"], "timeout")
        self.assertIn("expected_pipe", o["pipe_readiness"])
        self.assertIsNotNone(o["service_postmortem"])
        self.assertEqual(o["publisher_failure_class"], "PIPE SERVER INITIALIZATION FAILURE")

    def test_readiness_schema_fields_present(self) -> None:
        ops = sops.DryOperations(pipe_not_ready=True, readiness_reason="service-died")
        ops.pipe_ready(r"\\.\pipe\gnosis-s2cb-probe", "GnosisPubS2CBProbe")
        d = ops.last_readiness()
        for k in ("terminal_reason", "expected_pipe", "timeout_s", "poll_interval_s",
                  "poll_count", "elapsed_s", "service_running_observed", "pipe_seen"):
            self.assertIn(k, d)


class TestNoBehaviorChange(unittest.TestCase):
    def test_pipe_name_and_timeout_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            dcfg = drv.default_driver_config(Path(d))
        self.assertEqual(dcfg.stage.pipe_name, r"\\.\pipe\gnosis-s2cb-probe")
        ops_src = (REPO / "scripts" / "stage2cb_ops.py").read_text(encoding="utf-8")
        self.assertIn("timeout_s=15.0", ops_src)   # readiness timeout unchanged


if __name__ == "__main__":
    unittest.main()
