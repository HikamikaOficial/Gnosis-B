import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gnosis.kernel.run_store import RunStore
from gnosis.kernel.state_machine import RunState
from gnosis.runner.liveness import ProcessFingerprint, current_fingerprint
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
        # A heartbeat with the *current, live* process's fingerprint, but
        # timestamped far in the past: process liveness alone would say
        # "alive", it is really this test process, so staleness must be
        # the signal that trips here.
        fp = current_fingerprint()
        stale_ts = (datetime.now(timezone.utc) - timedelta(seconds=999)).isoformat()
        payload = {"ts": stale_ts, **fp.to_dict()}
        self.store.paths_for("RUN-1").heartbeat.write_text(json.dumps(payload))

        manager = RecoveryManager(self.store, stale_after_s=60)
        crashed = manager.scan()

        self.assertEqual(len(crashed), 1)
        self.assertEqual(crashed[0].run_id, "RUN-1")
        self.assertEqual(crashed[0].reason, "heartbeat_stale")
        self.assertEqual(self.store.read_meta("RUN-1").state, RunState.CRASHED.value)

    def test_dead_process_detected_immediately_even_if_heartbeat_fresh(self):
        self.store.create_run("RUN-1", "TASK-1")
        self.store.update_state("RUN-1", RunState.RUNNING)
        # A PID far outside any plausible live range: no process, so the
        # fresh timestamp alone must not save it from being flagged.
        dead_fp = ProcessFingerprint(pid=999_999_999, start_time=None)
        fresh_ts = datetime.now(timezone.utc).isoformat()
        self.store.paths_for("RUN-1").heartbeat.write_text(
            json.dumps({"ts": fresh_ts, **dead_fp.to_dict()})
        )

        crashed = RecoveryManager(self.store, stale_after_s=3600).scan()

        self.assertEqual(len(crashed), 1)
        self.assertEqual(crashed[0].reason, "process_not_alive")
        self.assertFalse(crashed[0].process_alive)

    def test_pid_reuse_not_confused_with_original_owner(self):
        self.store.create_run("RUN-1", "TASK-1")
        self.store.update_state("RUN-1", RunState.RUNNING)
        fp = current_fingerprint()
        # Same PID as this live process, but a start_time that does not
        # match, simulating the PID having been reused by a different
        # process than the one that actually owned this run.
        mismatched = ProcessFingerprint(pid=fp.pid, start_time=(fp.start_time or 0) - 99999)
        fresh_ts = datetime.now(timezone.utc).isoformat()
        self.store.paths_for("RUN-1").heartbeat.write_text(
            json.dumps({"ts": fresh_ts, **mismatched.to_dict()})
        )

        crashed = RecoveryManager(self.store, stale_after_s=3600).scan()

        self.assertEqual(len(crashed), 1)
        self.assertEqual(crashed[0].reason, "process_not_alive")

    def test_run_with_no_heartbeat_marked_crashed(self):
        self.store.create_run("RUN-1", "TASK-1")
        self.store.update_state("RUN-1", RunState.RUNNING)
        crashed = RecoveryManager(self.store, stale_after_s=60).scan()
        self.assertEqual(len(crashed), 1)
        self.assertEqual(crashed[0].reason, "no_heartbeat")

    def test_fresh_heartbeat_from_live_owner_not_flagged(self):
        self.store.create_run("RUN-1", "TASK-1")
        self.store.update_state("RUN-1", RunState.RUNNING)
        self.store.heartbeat("RUN-1")  # current (live) process's fingerprint
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
