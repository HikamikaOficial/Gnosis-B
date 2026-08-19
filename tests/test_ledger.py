import tempfile
import unittest
from pathlib import Path

from gnosis.kernel.ledger import RunLedger


class TestRunLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_and_read_back(self):
        ledger = RunLedger(self.path)
        e1 = ledger.append("RUN-1", "run.started", {"foo": "bar"})
        e2 = ledger.append("RUN-1", "run.finished", {"exit_code": 0})
        self.assertEqual(e1.seq, 1)
        self.assertEqual(e2.seq, 2)
        events = ledger.read_all()
        self.assertEqual([e.event_type for e in events], ["run.started", "run.finished"])

    def test_survives_reopen(self):
        RunLedger(self.path).append("RUN-1", "run.started", {})
        reopened = RunLedger(self.path)
        reopened.append("RUN-1", "run.finished", {})
        self.assertEqual(len(reopened.read_all()), 2)
        self.assertEqual(reopened.read_all()[-1].seq, 2)

    def test_has_no_mutation_api(self):
        ledger = RunLedger(self.path)
        for attr in ("update", "delete", "remove", "edit"):
            self.assertFalse(hasattr(ledger, attr))


if __name__ == "__main__":
    unittest.main()
