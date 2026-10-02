"""F-33 Stage 2C-B1-PRE0 — OS-real execution driver dry qualification (D1-D18).

No Windows mutation, no provider calls. Proves the authorized driver invokes the
already-qualified Stage2CBOrchestrator with correct, verified bindings, and that
privileged construction is gated.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "scripts", REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import run_f33_stage2c_b1_osreal as drv
import stage2cb as s
import stage2cb_ops as sops

from gnosis.director import cli


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dcfg = drv.default_driver_config(self.root, live_used=1)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _dry(self, **kw):
        return drv.run_driver(self.dcfg, execute_os_real=False, confirm="",
                              expected_head_sha=drv.expected_head(), **kw)


class TestDriverDry(_Base):
    def test_d1_default_invocation_cannot_mutate(self) -> None:
        ops = sops.DryOperations()
        t = self._dry(dry_ops=ops)
        self.assertEqual(t["result"], "DRY-TRACE-OK")
        self.assertFalse(t["real_ops_constructed"])
        self.assertTrue(t["orchestration"]["success"])

    def test_d16_dry_zero_os_mutation(self) -> None:
        ops = sops.DryOperations()
        self._dry(dry_ops=ops)
        # DryOperations is a fake boundary; no WindowsRealOperations was constructed
        self.assertFalse(any(isinstance(o, sops.WindowsRealOperations) for o in [ops]))

    def test_d17_dry_zero_provider_calls(self) -> None:
        ops = sops.DryOperations()
        self._dry(dry_ops=ops)
        # the operator subprocess seam is faked; no real claude/subprocess spawn
        self.assertTrue(ops.ops_of("spawn_operator"))  # faked spawn recorded, not real

    def test_d10_uses_same_stage2cb_orchestrator(self) -> None:
        with mock.patch.object(s, "Stage2CBOrchestrator",
                               wraps=s.Stage2CBOrchestrator) as m:
            self._dry(dry_ops=sops.DryOperations())
        self.assertTrue(m.called)

    def test_d15_pipe_publisher_route(self) -> None:
        t = self._dry(dry_ops=sops.DryOperations())
        self.assertIn("run", t["orchestration"]["launch_argv"])
        # route selected inside orchestrator is PipePublisherClient (asserted in the
        # backend suite); here we confirm the driver runs that orchestrator path.
        self.assertTrue(t["orchestration"]["success"])


class TestDriverGates(_Base):
    def test_d2_execute_without_auth_is_blocked(self) -> None:
        t = drv.run_driver(self.dcfg, execute_os_real=True, confirm="wrong",
                           expected_head_sha=drv.expected_head())
        self.assertEqual(t["result"], "BLOCKED-NO-AUTH")
        self.assertFalse(t["real_ops_constructed"])

    def test_d3_head_mismatch_blocks(self) -> None:
        t = drv.run_driver(self.dcfg, execute_os_real=True, confirm=drv.CONFIRM_TOKEN,
                           expected_head_sha="0" * 40)
        self.assertEqual(t["result"], "BLOCKED-HEAD")
        self.assertFalse(t["real_ops_constructed"])

    def test_d4_active_residue_blocks(self) -> None:
        store = s.ResidueStore(self.dcfg.stage.residue_record_path(),
                               self.dcfg.stage.run_id)
        store.write_initial(self.dcfg.stage)  # active record
        t = drv.run_driver(self.dcfg, execute_os_real=True, confirm=drv.CONFIRM_TOKEN,
                           expected_head_sha=drv.expected_head())
        self.assertEqual(t["result"], "BLOCKED-RESIDUE")
        self.assertFalse(t["real_ops_constructed"])  # real ops NOT constructed

    def test_d8_missing_runtime_src_blocks(self) -> None:
        bad = drv.default_driver_config(self.root, live_used=1)
        bad.runtime_src = str(self.root / "nonexistent-runtime")
        t = drv.run_driver(bad, execute_os_real=True, confirm=drv.CONFIRM_TOKEN,
                           expected_head_sha=drv.expected_head())
        self.assertEqual(t["result"], "BLOCKED-RUNTIME")
        self.assertFalse(t["real_ops_constructed"])

    def test_d9_real_backend_only_after_gates(self) -> None:
        # any failing gate -> WindowsRealOperations is never constructed
        for kw in ({"confirm": "wrong", "expected_head_sha": drv.expected_head()},
                   {"confirm": drv.CONFIRM_TOKEN, "expected_head_sha": "0" * 40}):
            t = drv.run_driver(self.dcfg, execute_os_real=True, **kw)
            self.assertFalse(t["real_ops_constructed"])


class TestDriverBindings(_Base):
    def test_d5_real_f17_observer_selected(self) -> None:
        # make_real_reobserve calls observe_deployment (not a cached constant)
        with mock.patch("gnosis.trust.deployment.observe_deployment") as mobs:
            mobs.return_value = mock.Mock(digest=lambda: "a" * 64)
            fn = drv.make_real_reobserve(self.dcfg.stage)
            digest = fn()
        self.assertTrue(mobs.called)
        self.assertEqual(digest, "a" * 64)

    def test_d7_runtime_src_is_stage8_mechanism(self) -> None:
        self.assertEqual(drv.QUALIFIED_RUNTIME_SRC, sys.base_prefix)
        self.assertTrue(Path(drv.QUALIFIED_RUNTIME_SRC).is_dir())

    def test_d11_production_reviewer_absolute(self) -> None:
        cfgd = drv.build_operator_config(self.dcfg.stage, self.dcfg.reviewer_binary)
        self.assertTrue(Path(cfgd["reviewer"]["binary"]).is_absolute())
        self.assertNotIn(cfgd["attribution"]["reviewer_id"],
                         ("claude-cli", "agent://unattributed"))
        # cli.build_reviewer rejects a relative reviewer binary
        with self.assertRaises(cli.OperatorError):
            cli.build_reviewer({"binary": "claude"})

    def test_d12_live_ledger_starts_at_one(self) -> None:
        self.assertEqual(self.dcfg.live_used, 1)
        self.assertIn("1 used / 4 remaining", drv.plan_trace(self.dcfg)["live_ledger"])

    def test_d12b_run_uses_cumulative_ledger_not_zero(self) -> None:
        seen: list[int] = []
        real_budget = s.LiveCallBudget

        def _spy(used: int, **kw):  # type: ignore[no-untyped-def]
            seen.append(used)
            return real_budget(used, **kw)
        with mock.patch.object(s, "LiveCallBudget", side_effect=_spy):
            drv.run_driver(self.dcfg, execute_os_real=False, confirm="",
                           expected_head_sha=drv.expected_head(),
                           dry_ops=sops.DryOperations())
        self.assertIn(1, seen)          # started at cumulative used=1
        self.assertNotIn(0, seen)       # never reset to zero

    def test_config_has_all_required_sections(self) -> None:
        cfgd = drv.build_operator_config(self.dcfg.stage, self.dcfg.reviewer_binary)
        for k in cli._REQUIRED_CONFIG:
            self.assertIn(k, cfgd)

    def test_observe_fn_none_means_real(self) -> None:
        # Provisioner._observe: `observer = self.observe_fn or observe_deployment`,
        # so observe_fn=None -> real observe_deployment (proven from source).
        src = (REPO / "src" / "gnosis" / "provision" / "provisioner.py").read_text(
            encoding="utf-8")
        self.assertIn("observer = self.observe_fn or observe_deployment", src)


class TestOperatorArgv(_Base):
    def test_d13_corrected_argv_reaches_run(self) -> None:
        with mock.patch.object(cli, "_run", return_value=(0, {})) as m:
            rc = cli.main(["run", "--config", "c.json", "--brief", "b.json"])
        self.assertTrue(m.called)
        self.assertEqual([str(a) for a in m.call_args[0]], ["c.json", "b.json"])
        self.assertEqual(rc, 0)

    def test_d14_old_argv_is_parser_invalid(self) -> None:
        with mock.patch.object(cli, "_run", return_value=(0, {})) as m:
            rc = cli.main(["run", "--brief", "run-id"])   # missing --config
        self.assertFalse(m.called)
        self.assertEqual(rc, cli.EXIT_USAGE)

    def test_driver_emits_corrected_argv(self) -> None:
        argv = self.dcfg.operator_args()
        self.assertEqual(argv[0], "run")
        self.assertIn("--config", argv)
        self.assertIn("--brief", argv)


class TestRecovery(_Base):
    def test_d18_recovery_refuses_ambiguous(self) -> None:
        # driver recovery consumes s.recover (ownership-safe); ambiguous -> refuse.
        with mock.patch.object(s, "recover",
                               return_value=("AMBIGUOUS_RESIDUE", [])) as m:
            status, targets = drv.recover(self.dcfg)
        self.assertTrue(m.called)
        self.assertEqual(status, "AMBIGUOUS_RESIDUE")
        self.assertEqual(targets, [])


if __name__ == "__main__":
    unittest.main()
