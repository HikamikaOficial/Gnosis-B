import tempfile
import unittest
from pathlib import Path

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
        self.store.heartbeat("RUN-1", pid=1234)
        hb = self.store.read_heartbeat("RUN-1")
        self.assertEqual(hb["pid"], 1234)

    def test_duplicate_run_id_rejected(self):
        self.store.create_run("RUN-1", "TASK-1")
        with self.assertRaises(FileExistsError):
            self.store.create_run("RUN-1", "TASK-1")

    def test_list_run_ids(self):
        self.store.create_run("RUN-1", "TASK-1")
        self.store.create_run("RUN-2", "TASK-1")
        self.assertEqual(self.store.list_run_ids(), ["RUN-1", "RUN-2"])


if __name__ == "__main__":
    unittest.main()
