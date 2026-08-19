import json
import threading
import tempfile
import unittest
from pathlib import Path

from gnosis.kernel.atomic_io import atomic_write_text
from gnosis.kernel.file_lock import FileLock, lock_path_for
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.state_machine import RunState


class TestRunStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RunStore(Path(self.tmp.name) / "runs")

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_run_layout(self):
        paths = self.store.create_run("RUN-1", "TASK-1")
        self.assertTrue(paths.root.is_dir())
        self.assertTrue(paths.meta.exists())
        self.assertTrue(paths.ledger.exists())
        self.assertTrue(paths.raw_dir.is_dir())
        self.assertTrue(paths.git_dir.is_dir())

    def test_meta_round_trip_and_state_update(self):
        self.store.create_run("RUN-1", "TASK-1")
        meta = self.store.read_meta("RUN-1")
        self.assertEqual(meta.state, RunState.PENDING.value)
        self.store.update_state("RUN-1", RunState.RUNNING)
        self.assertEqual(self.store.read_meta("RUN-1").state, RunState.RUNNING.value)

    def test_heartbeat_round_trip(self):
        self.store.create_run("RUN-1", "TASK-1")
        self.assertIsNone(self.store.read_heartbeat("RUN-1"))
        self.store.heartbeat("RUN-1")
        hb = self.store.read_heartbeat("RUN-1")
        self.assertIn("pid", hb)
        self.assertIn("ts", hb)

    def test_heartbeat_with_explicit_fingerprint(self):
        from gnosis.runner.liveness import ProcessFingerprint

        self.store.create_run("RUN-1", "TASK-1")
        self.store.heartbeat("RUN-1", ProcessFingerprint(pid=4321, start_time=1.0))
        hb = self.store.read_heartbeat("RUN-1")
        self.assertEqual(hb["pid"], 4321)
        self.assertEqual(hb["start_time"], 1.0)

    def test_duplicate_run_id_rejected(self):
        self.store.create_run("RUN-1", "TASK-1")
        with self.assertRaises(FileExistsError):
            self.store.create_run("RUN-1", "TASK-1")

    def test_list_run_ids(self):
        self.store.create_run("RUN-1", "TASK-1")
        self.store.create_run("RUN-2", "TASK-1")
        self.assertEqual(self.store.list_run_ids(), ["RUN-1", "RUN-2"])

    def test_corrupted_meta_fails_loud_not_silent(self):
        paths = self.store.create_run("RUN-1", "TASK-1")
        paths.meta.write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            self.store.read_meta("RUN-1")


class TestRunStoreConcurrency(unittest.TestCase):
    """Exercises the meta.json read-modify-write path (write_meta /
    update_state) under real thread contention using the exact lock file
    those methods use in production, demonstrating no silently lost
    updates and no corrupted meta.json."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RunStore(Path(self.tmp.name) / "runs")

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_lost_updates_on_meta_extra_counter(self):
        paths = self.store.create_run("RUN-1", "TASK-1")
        thread_count = 8
        increments_per_thread = 20
        errors = []

        def worker():
            try:
                for _ in range(increments_per_thread):
                    with FileLock(lock_path_for(paths.meta), timeout_s=15.0):
                        meta = self.store.read_meta("RUN-1")
                        meta.extra = meta.extra or {}
                        meta.extra["counter"] = meta.extra.get("counter", 0) + 1
                        atomic_write_text(paths.meta, json.dumps(meta.to_dict(), sort_keys=True))
            except Exception as exc:  # pragma: no cover - surfaced via errors list
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        self.assertEqual(errors, [])
        final = self.store.read_meta("RUN-1")
        self.assertEqual(final.extra["counter"], thread_count * increments_per_thread)

    def test_concurrent_update_state_never_corrupts_meta(self):
        self.store.create_run("RUN-1", "TASK-1")
        states = [RunState.PENDING, RunState.RUNNING]
        errors = []

        def worker(state):
            try:
                for _ in range(20):
                    self.store.update_state("RUN-1", state)
            except Exception as exc:  # pragma: no cover - surfaced via errors list
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(s,)) for s in states for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        self.assertEqual(errors, [])
        final = self.store.read_meta("RUN-1")  # must parse cleanly, not raise
        self.assertIn(final.state, {RunState.PENDING.value, RunState.RUNNING.value})


if __name__ == "__main__":
    unittest.main()
