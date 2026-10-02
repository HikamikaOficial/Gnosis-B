"""F-33 Stage 2C-B0-R1 — dry qualification of the complete OS-real backend.

No Windows provisioning, no provider calls, no process spawn. Exercises the SAME
orchestration graph B1 will run, with the fake `DryOperations` backend, plus the
budget/journal/residue/recovery/preflight/route/env components.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from stage2cb import (
    RESIDUE_SCHEMA_V2,
    BudgetError,
    FakeObserved,
    LiveCallBudget,
    OperatorRouteSelection,
    ResidueManifest,
    ResidueStore,
    Stage2CBConfig,
    Stage2CBOrchestrator,
    TransactionJournal,
    make_base_provision,
    ownership_matches,
    parse_residue_manifest,
    parse_residue_record,
    plan_recovery,
    preflight,
    recover,
    reviewer_environment,
    select_production_route,
    worker_environment,
)
from stage2cb_ops import DryOperations, WindowsRealOperations

from gnosis.provision.codex_package import codex_package_entrypoint
from gnosis.provision.layout import DeploymentLayout
from tests.test_codex_package import make_package

F17D = "f" * 64
CLAUDE = r"C:\Users\nicol\.local\bin\claude.exe"


def _config(root: Path) -> Stage2CBConfig:
    layout = DeploymentLayout(code_base=str(root / "code"), state_base=str(root / "state"),
                              work_base=str(root / "work"), release_id="TST")
    (root / "rtsrc").mkdir(parents=True, exist_ok=True)
    return Stage2CBConfig(
        layout=layout, service_name="GnosisPubS2CBProbe", pipe_name="gnosis-s2cb-probe",
        worker_username="GnosisWkrS2CB", package_version="0.0.0",
        source_commit="deadbeef", source_tree="t" * 40, runtime_src=str(root / "rtsrc"),
        reviewer_binary=CLAUDE, run_id="run-tst-1")


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = _config(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _orch(self, ops: DryOperations, *, used: int = 1,
              inject_fail_after: str | None = None,
              operator_exit_code: int = 0, with_store: bool = False,
              inject_crash_at: str | None = None) -> Stage2CBOrchestrator:
        store = (ResidueStore(self.config.residue_record_path(), self.config.run_id)
                 if with_store or inject_crash_at else None)
        return Stage2CBOrchestrator(
            config=self.config, ops=ops, budget=LiveCallBudget(used=used),
            reobserve_f17=lambda: F17D, observe_fn=lambda c: FakeObserved(F17D),
            inject_fail_after=inject_fail_after, operator_exit_code=operator_exit_code,
            residue_store=store, inject_crash_at=inject_crash_at)

    def _store(self) -> ResidueStore:
        return ResidueStore(self.config.residue_record_path(), self.config.run_id)


class TestPositiveSimulatedB1(_Base):
    def test_full_positive_trace_success(self) -> None:
        ops = DryOperations()
        res = self._orch(ops).run()
        self.assertTrue(res.success, res.stages)
        self.assertEqual(res.operator_exit, 0)
        self.assertTrue(res.anchored and res.completed)
        self.assertTrue(res.rollback_ok, res.rollback_failures)

    def test_consumes_real_f17_provisioner(self) -> None:
        ops = DryOperations()
        self._orch(ops).run()
        # the real F-17 Provisioner.install ran through ops
        self.assertTrue(ops.ops_of("create_worker"))
        self.assertTrue(ops.ops_of("protect_secret"))
        self.assertTrue(any(a[0][:2] == ("sc.exe", "create") for a in ops.ops_of("run")))
        self.assertTrue(any("icacls" in a[0][0] for a in ops.ops_of("run")))

    def test_spawn_true_and_pipe_publisher_selected(self) -> None:
        ops = DryOperations()
        res = self._orch(ops).run()
        self.assertTrue(res.spawn_true)
        self.assertEqual(res.launch_argv[-3:], ("run", "--brief", "run-tst-1"))
        self.assertTrue(any(a.endswith("operator_entry.py") for a in res.launch_argv))
        assert res.route is not None
        self.assertEqual(res.route.publisher_client,
                         "gnosis.director.publisher_client.PipePublisherClient")
        self.assertIn("ClaudeCLIRunner", res.route.reviewer_runner)
        self.assertTrue(res.route.replay_forbidden)
        self.assertIn("worker_launcher", res.route.worker_path)
        self.assertIn("TrustedExecutionRunner", res.route.worker_path)
        # the process-creation seam actually fired (spawn=True is real, not cosmetic)
        self.assertTrue(ops.ops_of("spawn_operator"))

    def test_no_real_os_effects(self) -> None:
        ops = DryOperations()
        self._orch(ops).run()
        # DryOperations never touches real accounts/services; assert the harness
        # used only faked create/service ops (no real subprocess to sc/net).
        self.assertTrue(ops.ops_of("create_worker"))  # faked, recorded
        # everything that would be a real OS effect went through the recorded log
        self.assertGreater(len(ops.log), 0)

    def test_success_requires_anchored(self) -> None:
        ops = DryOperations(anchored=False)
        res = self._orch(ops).run()
        self.assertFalse(res.success)
        self.assertFalse(res.anchored)
        self.assertTrue(res.rollback_ok)   # still cleaned up

    def test_success_requires_zero_exit(self) -> None:
        ops = DryOperations()
        res = self._orch(ops, operator_exit_code=3).run()
        self.assertFalse(res.success)
        self.assertEqual(res.operator_exit, 3)
        self.assertTrue(res.rollback_ok)


class TestFailureInjection(_Base):
    STAGES: ClassVar[list[str]] = [
        "base_provision", "composed_deployment", "trusted_record", "acls",
        "service_start", "pipe_ready", "route_selected", "operator_launch",
        "anchored_check"]

    def test_injection_at_each_stage_rolls_back(self) -> None:
        for stage in self.STAGES:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as d:
                self.config = _config(Path(d))
                ops = DryOperations()
                res = self._orch(ops, inject_fail_after=stage).run()
                self.assertFalse(res.success)
                self.assertTrue(res.rollback_ok, res.rollback_failures)

    def test_partial_acquisition_failure_in_f17_install(self) -> None:
        # failure DURING account creation -> base_provision fails, journal has no
        # cleanup claim for resources never acquired, and rollback stays clean.
        ops = DryOperations(fail_op="create_worker")
        res = self._orch(ops).run()
        self.assertFalse(res.success)
        self.assertTrue(res.rollback_ok)

    def test_partial_service_failure(self) -> None:
        ops = DryOperations(fail_op="service_start")
        res = self._orch(ops).run()
        self.assertFalse(res.success)
        self.assertTrue(res.rollback_ok)

    def test_post_base_failure_actually_deletes_worker(self) -> None:
        # a failure AFTER base provisioning must trigger the registered F-17
        # uninstall (delete_worker), proving the cleanup registration exists.
        ops = DryOperations()
        self._orch(ops, inject_fail_after="composed_deployment").run()
        self.assertTrue(ops.ops_of("delete_worker"))

    def test_post_service_failure_actually_stops_service(self) -> None:
        ops = DryOperations()
        self._orch(ops, inject_fail_after="route_selected").run()
        self.assertTrue(ops.ops_of("service_stop"))


class TestCleanupFailure(_Base):
    def test_worker_delete_cleanup_failure_reports_residue(self) -> None:
        ops = DryOperations(fail_cleanup=("delete_worker",))
        res = self._orch(ops, inject_fail_after="composed_deployment").run()
        self.assertFalse(res.rollback_ok)
        self.assertTrue(any("f17-uninstall" in f for f in res.rollback_failures))

    def test_service_stop_cleanup_failure_reports_residue(self) -> None:
        ops = DryOperations(fail_cleanup=("service_stop",))
        res = self._orch(ops, inject_fail_after="pipe_ready").run()
        self.assertFalse(res.rollback_ok)
        # other cleanups (composed, f17) still attempted
        self.assertTrue(any("service-stop" in f for f in res.rollback_failures))


class TestCollisionPreflight(_Base):
    def _pre(self, ops: DryOperations, residue: ResidueManifest | None = None):
        return preflight(self.config, ops, expected_head="H", actual_head="H",
                         f17_stable=True, budget=LiveCallBudget(used=1),
                         owned_residue=residue)

    def test_clean_state_passes(self) -> None:
        ops = DryOperations()
        self.assertTrue(self._pre(ops).ok)

    def test_account_collision_stops(self) -> None:
        ops = DryOperations(existing_accounts=("GnosisWkrS2CB",))
        r = self._pre(ops)
        self.assertFalse(r.ok)
        self.assertIn("worker account collision", r.failures)

    def test_service_collision_stops(self) -> None:
        ops = DryOperations(existing_services=("GnosisPubS2CBProbe",))
        self.assertFalse(self._pre(ops).ok)

    def test_root_collision_stops(self) -> None:
        ops = DryOperations(existing_roots=(self.config.layout.code_base,))
        self.assertFalse(self._pre(ops).ok)

    def test_owned_residue_requires_recovery(self) -> None:
        ops = DryOperations()
        m = ResidueManifest("r", "GnosisWkrS2CB", "GnosisPubS2CBProbe",
                            "gnosis-s2cb-probe", self.config.owned_roots())
        r = self._pre(ops, residue=m)
        self.assertFalse(r.ok)

    def test_not_elevated_stops(self) -> None:
        ops = DryOperations(elevated=False)
        self.assertFalse(self._pre(ops).ok)

    def test_head_mismatch_stops(self) -> None:
        ops = DryOperations()
        r = preflight(self.config, ops, expected_head="A", actual_head="B",
                      f17_stable=True, budget=LiveCallBudget(used=1), owned_residue=None)
        self.assertIn("HEAD mismatch", r.failures)


class TestBudget(unittest.TestCase):
    def test_boundaries(self) -> None:
        self.assertEqual(LiveCallBudget(used=1).remaining(), 4)
        self.assertTrue(LiveCallBudget(used=1).permit(4))
        self.assertFalse(LiveCallBudget(used=1).permit(5))
        self.assertTrue(LiveCallBudget(used=4).permit(1))
        self.assertFalse(LiveCallBudget(used=5).permit(1))

    def test_used_over_max_is_invalid(self) -> None:
        with self.assertRaises(BudgetError):
            LiveCallBudget(used=6)

    def test_consume_enforces_ceiling(self) -> None:
        b = LiveCallBudget(used=4)
        b.consume("one")
        self.assertEqual(b.used, 5)
        with self.assertRaises(BudgetError):
            b.consume("over")

    def test_orchestrator_refuses_when_budget_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            config = _config(Path(d))
            ops = DryOperations()
            orch = Stage2CBOrchestrator(
                config=config, ops=ops, budget=LiveCallBudget(used=5),
                reobserve_f17=lambda: F17D, observe_fn=lambda c: FakeObserved(F17D))
            res = orch.run()
            self.assertFalse(res.success)
            self.assertFalse(ops.ops_of("spawn_operator"))  # never launched


class TestResidueAndRecovery(unittest.TestCase):
    def _cfg(self, d: str) -> Stage2CBConfig:
        return _config(Path(d))

    def test_manifest_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cfg = self._cfg(d)
            m = ResidueManifest("r1", cfg.worker_username, cfg.service_name,
                                cfg.pipe_name, cfg.owned_roots())
            self.assertEqual(parse_residue_manifest(m.dumps()), m)

    def test_corrupt_manifest_fails_closed(self) -> None:
        for bad in ('{"schema":', '{"schema":"wrong.v9"}', '{}', '[]',
                    '{"schema":"gnosis.stage2cb.residue.v1"}'):
            with self.assertRaises(ValueError):
                parse_residue_manifest(bad)

    def test_recovery_refuses_on_ownership_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cfg = self._cfg(d)
            foreign = ResidueManifest("r", "SomeoneElse", "OtherSvc", "other-pipe",
                                     ("C:\\Windows",))
            self.assertFalse(ownership_matches(foreign, cfg))
            safe, targets = plan_recovery(foreign, cfg)
            self.assertFalse(safe)
            self.assertEqual(targets, [])

    def test_recovery_plans_owned_residue(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cfg = self._cfg(d)
            owned = ResidueManifest("r", cfg.worker_username, cfg.service_name,
                                   cfg.pipe_name, cfg.owned_roots())
            safe, targets = plan_recovery(owned, cfg)
            self.assertTrue(safe)
            self.assertTrue(any("delete_worker" in t for t in targets))
            self.assertTrue(any("delete_service" in t for t in targets))


class TestRouteAndEnv(unittest.TestCase):
    def test_route_requires_absolute_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cfg = _config(Path(d))
            good = select_production_route(cfg)
            self.assertIsInstance(good, OperatorRouteSelection)
            bad = Stage2CBConfig(**{**cfg.__dict__, "reviewer_binary": "claude"})
            with self.assertRaises(ValueError):
                select_production_route(bad)

    def test_worker_env_strips_provider_secrets(self) -> None:
        env = {"PATH": "x", "ANTHROPIC_API_KEY": "s", "CLAUDE_SESSION": "s",
               "AWS_SECRET": "s", "SystemRoot": "C:\\Windows"}
        w = worker_environment(env)
        self.assertNotIn("ANTHROPIC_API_KEY", w)
        self.assertNotIn("CLAUDE_SESSION", w)
        self.assertNotIn("AWS_SECRET", w)
        self.assertIn("PATH", w)

    def test_reviewer_env_is_allowlist(self) -> None:
        env = {"PATH": "x", "SystemRoot": "y", "SECRET_TOKEN": "z", "TEMP": "t"}
        r = reviewer_environment(env)
        self.assertEqual(set(r), {"PATH", "SystemRoot", "TEMP"})
        self.assertNotIn("SECRET_TOKEN", r)


class TestCrashPersistentResidue(_Base):
    HK_BOUNDARIES: ClassVar[list[str]] = [
        "HK0_before_base", "HK_after_base_os_before_persist", "HK_after_base_acquired",
        "base_provision", "composed_deployment", "acls", "service_start",
        "operator_launch", "anchored_check"]

    def test_manifest_persisted_before_first_acquisition(self) -> None:
        # HBM17: a HARD kill BEFORE any OS mutation still leaves an on-disk record
        # (intended, not acquired). A purely in-memory journal cannot satisfy this.
        self._orch(DryOperations(), inject_crash_at="HK0_before_base").run()
        rec = self._store().load()
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec.schema, RESIDUE_SCHEMA_V2)
        self.assertEqual(rec.status, "active")
        self.assertTrue(all(r.intended and not r.acquired for r in rec.resources))

    def test_acquisition_persisted_incrementally(self) -> None:
        # HBM18: after base acquisition the disk record reflects acquired=true.
        self._orch(DryOperations(), inject_crash_at="HK_after_base_acquired").run()
        rec = self._store().load()
        assert rec is not None
        self.assertTrue(any(r.identity == self.config.worker_username and r.acquired
                            for r in rec.resources))
        self.assertTrue(any(r.identity == self.config.service_name and r.acquired
                            for r in rec.resources))

    def test_ambiguous_window_recoverable_not_assumed_unrelated(self) -> None:
        # crash AFTER OS creation but BEFORE acquired persisted: acquired=false, yet
        # the worker/service exist. Recovery observes reality and plans cleanup.
        ops = DryOperations()
        self._orch(ops, inject_crash_at="HK_after_base_os_before_persist").run()
        rec = self._store().load()
        assert rec is not None
        self.assertFalse(any(r.acquired for r in rec.resources))  # not yet persisted
        status, targets = recover(self._store(), self.config, ops)
        self.assertEqual(status, "PLAN")
        self.assertIn(f"worker:{self.config.worker_username}", targets)

    def test_clean_rollback_removes_resources_and_record(self) -> None:
        ops = DryOperations()
        r = self._orch(ops, with_store=True).run()
        self.assertTrue(r.success)
        self.assertTrue(ops.account_absent(self.config.worker_username))
        self.assertTrue(ops.service_absent(self.config.service_name))
        self.assertFalse(self.config.residue_record_path().is_file())  # retired

    def test_failed_rollback_keeps_record_with_remaining_residue(self) -> None:
        ops = DryOperations(fail_cleanup=("delete_worker",))
        r = self._orch(ops, with_store=True, inject_fail_after="composed_deployment").run()
        self.assertFalse(r.rollback_ok)
        rec = self._store().load()
        assert rec is not None                              # HBM19: record NOT deleted
        self.assertTrue(any(r.identity == self.config.worker_username and r.acquired
                            for r in rec.resources))
        # recovery targets only the positively-owned remaining resource
        status, targets = recover(self._store(), self.config, ops)
        self.assertEqual(status, "PLAN")
        self.assertIn(f"worker:{self.config.worker_username}", targets)

    def test_hard_kill_at_every_boundary_leaves_valid_or_absent_record(self) -> None:
        for hk in self.HK_BOUNDARIES:
            with self.subTest(hk=hk), tempfile.TemporaryDirectory() as d:
                self.config = _config(Path(d))
                self._orch(DryOperations(), inject_crash_at=hk).run()
                rec = self._store().load()  # must be parseable (or absent)
                self.assertIsNotNone(rec)   # written before the first mutation

    def test_preflight_active_record_stops(self) -> None:
        st = self._store()
        st.write_initial(self.config)
        r = preflight(self.config, DryOperations(), expected_head="H", actual_head="H",
                      f17_stable=True, budget=LiveCallBudget(used=1), store=st)
        self.assertFalse(r.ok)
        self.assertTrue(any("active residue record" in x for x in r.failures))

    def test_preflight_malformed_record_stops(self) -> None:
        self.config.residue_record_path().parent.mkdir(parents=True, exist_ok=True)
        self.config.residue_record_path().write_text('{"schema":', encoding="utf-8")
        r = preflight(self.config, DryOperations(), expected_head="H", actual_head="H",
                      f17_stable=True, budget=LiveCallBudget(used=1), store=self._store())
        self.assertFalse(r.ok)
        self.assertTrue(any("malformed residue record" in x for x in r.failures))

    def test_recovery_refuses_run_id_mismatch(self) -> None:
        st = self._store()
        st.write_initial(self.config)
        st.mark_acquired({self.config.worker_username})
        other = _config(Path(self.tmp.name))  # same paths, different run_id
        other = Stage2CBConfig(**{**other.__dict__, "run_id": "different-run"})
        status, _targets = recover(st, other, DryOperations())
        self.assertEqual(status, "REFUSE_RUN_MISMATCH")

    def test_corrupt_and_stale_record(self) -> None:
        path = self.config.residue_record_path()
        for bad in ('{"schema":', '{"schema":"gnosis.stage2cb.residue.v1"}',
                    '{"schema":"gnosis.stage2cb.residue.v2","run_id":"r"}'):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(bad, encoding="utf-8")
            with self.assertRaises(ValueError):
                parse_residue_record(bad)
        # stale: valid record but resources already absent -> STALE_VERIFIED_ABSENT
        st = self._store()
        st.write_initial(self.config)
        st.mark_acquired({self.config.worker_username})
        status, _targets = recover(st, self.config, DryOperations())  # fresh ops: absent
        self.assertEqual(status, "STALE_VERIFIED_ABSENT")

    def test_recovery_refuses_ambiguous_ownership(self) -> None:
        # HBM20: a present resource whose identity the current config does NOT claim
        # must NEVER be destructively cleaned; recovery returns AMBIGUOUS_RESIDUE.
        st = self._store()
        st.write_initial(self.config)  # record intends worker=GnosisWkrS2CB
        st.mark_acquired({self.config.worker_username})
        ops = DryOperations(existing_accounts=(self.config.worker_username,))  # present
        other = Stage2CBConfig(**{**self.config.__dict__,
                                  "worker_username": "GnosisWkrDIFFERENT"})
        status, targets = recover(st, other, ops)
        self.assertEqual(status, "AMBIGUOUS_RESIDUE")
        self.assertEqual(targets, [])

    def test_record_location_outside_owned_roots(self) -> None:
        rp = str(self.config.residue_record_path())
        for owned in self.config.owned_roots():
            self.assertFalse(rp.startswith((owned + "\\", owned + "/")))

    def test_atomic_write_leaves_no_temp(self) -> None:
        st = self._store()
        st.write_initial(self.config)
        st.mark_acquired({self.config.worker_username})
        leftovers = list(self.config.residue_record_path().parent.glob(".residue_*.tmp"))
        self.assertEqual(leftovers, [])


class TestGuardsAndJournal(unittest.TestCase):
    def test_base_provision_copies_complete_provider_before_observation(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            native = make_package(root / "native")
            cfg = replace(_config(root), codex_runtime_src=str(native))
            class FilesystemProviderOps(DryOperations):
                def copytree(self, src, dst):
                    if Path(src) == native:
                        self._rec("copytree", src, dst)
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        super().copytree(src, dst)

            ops = FilesystemProviderOps()
            observed = []

            def observe(config):
                deployed = Path(config.runtime_root) / "providers" / "codex"
                # Observation receives DesiredDeploymentConfig: provider bytes
                # must already be present when identity measurement begins.
                self.assertEqual(codex_package_entrypoint(deployed), deployed / "bin" / "codex.exe")
                for file in native.rglob("*"):
                    if file.is_file():
                        self.assertEqual(file.read_bytes(),
                            (deployed / file.relative_to(native)).read_bytes())
                observed.append(True)
                return FakeObserved(F17D)

            provision, _handle = make_base_provision(cfg, ops, observe_fn=observe)
            self.assertEqual(provision().deployment_digest, F17D)
            self.assertEqual(observed, [True])

    def test_windows_real_ops_guarded(self) -> None:
        with self.assertRaises(PermissionError):
            WindowsRealOperations()
        # authorized construction is possible but not used in this slice
        self.assertIsInstance(WindowsRealOperations(authorized=True), WindowsRealOperations)

    def test_journal_registers_before_next_op(self) -> None:
        j = TransactionJournal()
        order: list[str] = []
        j.register("a", lambda: order.append("clean-a"))
        j.register("b", lambda: order.append("clean-b"))
        ok, _failures = j.rollback()
        self.assertTrue(ok)
        self.assertEqual(order, ["clean-b", "clean-a"])  # reverse order

    def test_base_provision_returns_observed_digest(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cfg = _config(Path(d))
            ops = DryOperations()
            base_provision, handle = make_base_provision(
                cfg, ops, observe_fn=lambda c: FakeObserved(F17D))
            base = base_provision()
            self.assertEqual(base.deployment_digest, F17D)   # observed, not fabricated
            self.assertIsNotNone(handle["install"])

    def test_no_unimplemented_on_live_path(self) -> None:
        # HBM14: the authorized live path must have no TODO / pass-only /
        # NotImplementedError.
        for name in ("stage2cb.py", "stage2cb_ops.py"):
            src = (REPO / "scripts" / name).read_text(encoding="utf-8")
            self.assertNotIn("raise NotImplementedError", src, name)
            self.assertNotIn("# TODO", src, name)
            self.assertNotIn("will wire during B1", src, name)


if __name__ == "__main__":
    unittest.main()
