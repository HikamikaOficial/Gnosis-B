import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gnosis.kernel.run_store import RunStore
from gnosis.kernel.state_machine import RunState
from gnosis.runner.recovery import RecoveryManager


class TestRecoveryManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RunStore(Path(self.tmp.name) / "runs")

    def tearDown(self):
        self.tmp.cleanup()

    def test_stale_running_run_marked_crashed(self):
        self.store.create_run("RUN-1", "TASK-1")
        self.store.update_state("RUN-1", RunState.RUNNING)
        stale_ts = (datetime.now(timezone.utc) - timedelta(seconds=999)).isoformat()
        self.store.paths_for("RUN-1").heartbeat.write_text(json.dumps({"ts": stale_ts, "pid": 1}))

        manager = RecoveryManager(self.store, stale_after_s=60)
        crashed = manager.scan()

        self.assertEqual(len(crashed), 1)
        self.assertEqual(crashed[0].run_id, "RUN-1")
        self.assertEqual(self.store.read_meta("RUN-1").state, RunState.CRASHED.value)

    def test_run_with_no_heartbeat_marked_crashed(self):
        self.store.create_run("RUN-1", "TASK-1")
        self.store.update_state("RUN-1", RunState.RUNNING)
        crashed = RecoveryManager(self.store, stale_after_s=60).scan()
        self.assertEqual(len(crashed), 1)

    def test_fresh_heartbeat_not_flagged(self):
        self.store.create_run("RUN-1", "TASK-1")
        self.store.update_state("RUN-1", RunState.RUNNING)
        self.store.heartbeat("RUN-1", pid=1)
        crashed = RecoveryManager(self.store, stale_after_s=60).scan()
        self.assertEqual(crashed, [])
        self.assertEqual(self.store.read_meta("RUN-1").state, RunState.RUNNING.value)

    def test_non_running_runs_ignored(self):
        self.store.create_run("RUN-1", "TASK-1")
        crashed = RecoveryManager(self.store, stale_after_s=0).scan()
        self.assertEqual(crashed, [])

    def test_crash_event_recorded_in_ledger(self):
        self.store.create_run("RUN-1", "TASK-1")
        self.store.update_state("RUN-1", RunState.RUNNING)
        RecoveryManager(self.store, stale_after_s=60).scan()
        events = self.store.ledger_for("RUN-1").read_all()
        self.assertTrue(any(e.event_type == "run.crashed_detected" for e in events))


if __name__ == "__main__":
    unittest.main()
