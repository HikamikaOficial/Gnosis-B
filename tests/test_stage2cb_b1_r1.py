r"""F-33 Stage 2C-B1-R1 — pipe-readiness + driver-owned scaffold cleanup.

Filesystem/mock only; no OS provisioning, no provider calls. Root cause of the
first OS-real B1 failure = NAME-MISMATCH (bare pipe name vs the canonical
`\\.\pipe\<name>` form). This suite qualifies the fix + bounded readiness +
automatic driver-owned cleanup.
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


class _Clock:
    def __init__(self, step: float = 1.0) -> None:
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        v = self.t
        self.t += self.step
        return v


class TestPipeReadiness(unittest.TestCase):
    def _wait(self, exists_seq, alive_seq, *, timeout_s=5.0):
        ex = iter(exists_seq)
        al = iter(alive_seq)
        return s.wait_pipe_ready(
            r"\\.\pipe\p",
            pipe_exists=lambda: next(ex),
            service_alive=lambda: next(al),
            now=_Clock(step=1.0), timeout_s=timeout_s, poll_s=0.0, sleep=None)

    def test_p1_ready_immediately(self) -> None:
        r = self._wait([True], [True])
        self.assertTrue(r.ready)
        self.assertEqual(r.reason, "ready")
        self.assertEqual(r.polls, 1)

    def test_p2_ready_after_multiple_polls(self) -> None:
        r = self._wait([False, False, True], [True, True, True])
        self.assertTrue(r.ready)
        self.assertEqual(r.polls, 3)

    def test_p3_never_ready_times_out(self) -> None:
        r = self._wait([False] * 100, [True] * 100, timeout_s=3.0)
        self.assertFalse(r.ready)
        self.assertEqual(r.reason, "timeout")

    def test_p4_publisher_dies_immediate_fail(self) -> None:
        r = self._wait([False, False], [True, False])
        self.assertFalse(r.ready)
        self.assertEqual(r.reason, "service-died")

    def test_p5_exact_pipe_checked_no_reprefix(self) -> None:
        # the readiness checks the EXACT pipe_name it is given (the caller supplies
        # Path(pipe_name).exists()); a checker for a different name never readies.
        seen = []
        s.wait_pipe_ready(
            r"\\.\pipe\right",
            pipe_exists=lambda: (seen.append("check"), False)[1],
            service_alive=lambda: False, now=_Clock(), timeout_s=1.0, poll_s=0.0)
        self.assertTrue(seen)  # the injected exact-name checker was used

    def test_p6_observation_exception_fails_closed(self) -> None:
        def _boom() -> bool:
            raise OSError("pipe observation failed")
        r = s.wait_pipe_ready(r"\\.\pipe\p", pipe_exists=_boom,
                              service_alive=lambda: True, now=_Clock(), timeout_s=5.0)
        self.assertFalse(r.ready)
        self.assertEqual(r.reason, "observation-error")

    def test_p7_timeout_is_bounded_finite_polls(self) -> None:
        r = self._wait([False] * 10000, [True] * 10000, timeout_s=5.0)
        self.assertFalse(r.ready)
        self.assertLess(r.polls, 100)   # finite, bounded by the deadline/clock


class TestCanonicalPipeName(unittest.TestCase):
    def test_driver_pipe_name_is_full_local_path(self) -> None:
        # the NAME-MISMATCH root-cause fix: the driver config uses the FULL path.
        with tempfile.TemporaryDirectory() as d:
            dcfg = drv.default_driver_config(Path(d))
        self.assertTrue(dcfg.stage.pipe_name.startswith(r"\\.\pipe"))

    def test_pipe_publisher_client_requires_full_path(self) -> None:
        from gnosis.director.publisher_client import (
            PipePublisherClient,
            PublisherClientError,
        )
        PipePublisherClient(r"\\.\pipe\gnosis-s2cb-probe")   # accepted
        with self.assertRaises(PublisherClientError):
            PipePublisherClient("gnosis-s2cb-probe")          # bare -> rejected

    def test_real_pipe_ready_uses_exact_path_not_reprefixed(self) -> None:
        # WindowsRealOperations.pipe_ready must observe the EXACT pipe_name (no
        # \\.\pipe\ prepend), so a full pipe_name is not double-prefixed. R2C: the
        # observation is a Win32 named-pipe probe, NOT pathlib existence.
        src = (REPO / "scripts" / "stage2cb_ops.py").read_text(encoding="utf-8")
        self.assertIn("NamedPipeReadinessObserver(pipe_name", src)
        self.assertNotIn("Path(pipe_name).exists()", src)          # R2C: removed
        self.assertNotIn('Path(rf"\\\\.\\pipe\\{pipe_name}")', src)


class TestDriverScaffoldCleanup(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "gnosis-2cb-b1-run-b1-1"
        self.dcfg = drv.default_driver_config(self.root, live_used=1)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, ops, cleanup=True):
        return drv.run_driver(self.dcfg, execute_os_real=False, confirm="",
                              expected_head_sha=drv.expected_head(), dry_ops=ops,
                              cleanup_scaffold=cleanup)

    def test_success_self_cleans_scaffold(self) -> None:
        t = self._run(sops.DryOperations())
        self.assertEqual(t["orchestration"]["success"], True)
        self.assertEqual(t["scaffold_cleanup"], "removed")
        self.assertFalse(Path(self.dcfg.stage.layout.code_base).parent.exists())

    def test_failed_pipe_replay_self_cleans(self) -> None:
        # replay the exact real failure: pipe never ready -> orchestrator fails,
        # rollback retires the residue record, driver removes its scaffold.
        t = self._run(sops.DryOperations(pipe_not_ready=True))
        self.assertFalse(t["orchestration"]["success"])
        # R2A enriches the message with the failure class; behavior is unchanged.
        self.assertIn("publisher pipe not ready", t["orchestration"]["error"])
        self.assertTrue(t["orchestration"]["rollback_ok"])
        self.assertEqual(t["scaffold_cleanup"], "removed")
        self.assertFalse(Path(self.dcfg.stage.layout.code_base).parent.exists())

    def test_retained_when_residue_present(self) -> None:
        # if a residue record remains (rollback incomplete), scaffold is KEPT.
        store = s.ResidueStore(self.dcfg.stage.residue_record_path(),
                               self.dcfg.stage.run_id)
        store.write_initial(self.dcfg.stage)   # active record left behind
        trace: dict = {}
        drv._finalize_scaffold(self.dcfg, trace, cleanup_scaffold=True)
        self.assertIn("RETAINED", trace["scaffold_cleanup"])
        self.assertTrue(store.path.is_file())   # recovery metadata preserved

    def test_caller_managed_root_not_removed(self) -> None:
        t = self._run(sops.DryOperations(), cleanup=False)
        self.assertEqual(t["scaffold_cleanup"], "left (caller-managed root)")

    def test_scaffold_root_is_exact_owned_parent(self) -> None:
        inv = drv.plan_trace(self.dcfg)["driver_owned_resources"]
        root = Path(inv["scaffold_root"])
        for nested in ("operator_config", "operator_brief", "residue_record"):
            self.assertTrue(str(inv[nested]).startswith(str(root)))

    def test_cleanup_failure_reports_failed_not_removed(self) -> None:
        # RBM4 assurance: when scaffold rmtree FAILS (root remains), the reported
        # status must NOT be "removed" — it must reflect the failure. Compares
        # actual filesystem truth against the reported cleanup state.
        from unittest import mock
        scaffold_root = Path(self.dcfg.stage.layout.code_base).parent
        (scaffold_root / "GnosisStage2CBRecovery" / "inputs").mkdir(parents=True,
                                                                    exist_ok=True)
        # no residue record present -> reaches the rmtree branch
        self.assertFalse(self.dcfg.stage.residue_record_path().is_file())
        trace: dict = {}
        # force rmtree to be a no-op so the scaffold REMAINS after "cleanup"
        with mock.patch("shutil.rmtree", side_effect=lambda *a, **k: None) as m:
            drv._finalize_scaffold(self.dcfg, trace, cleanup_scaffold=True)
        self.assertTrue(m.called)                              # cleanup attempted
        self.assertTrue(scaffold_root.exists())               # deletion failed (fs truth)
        self.assertNotEqual(trace["scaffold_cleanup"], "removed")   # not falsely clean
        self.assertIn("FAILED", trace["scaffold_cleanup"])    # honest failure report
        # recovery ownership remains derivable (deterministic run-bound root)
        self.assertTrue(str(scaffold_root).endswith("gnosis-2cb-b1-run-b1-1"))


if __name__ == "__main__":
    unittest.main()
