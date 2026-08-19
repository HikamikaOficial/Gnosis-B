import tempfile
import threading
import unittest
from pathlib import Path

from gnosis.kernel.ledger import LedgerCorruptionError, RunLedger


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

    def test_tolerates_truncated_final_line(self):
        ledger = RunLedger(self.path)
        ledger.append("RUN-1", "run.started", {})
        ledger.append("RUN-1", "run.progress", {"step": 1})
        # Simulate a process killed mid-write: append a truncated,
        # unparseable final line directly to the file.
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write('{"seq": 3, "ts": "2026-01-0')  # deliberately cut off

        events = ledger.read_all()
        self.assertEqual(len(events), 2)
        self.assertEqual([e.event_type for e in events], ["run.started", "run.progress"])

    def test_non_final_corruption_raises(self):
        ledger = RunLedger(self.path)
        ledger.append("RUN-1", "run.started", {})
        ledger.append("RUN-1", "run.finished", {})
        with self.path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
        lines[0] = "not-json-at-all\n"
        self.path.write_text("".join(lines), encoding="utf-8")

        with self.assertRaises(LedgerCorruptionError):
            ledger.read_all()

    def test_next_append_recovers_after_truncated_final_line(self):
        ledger = RunLedger(self.path)
        ledger.append("RUN-1", "run.started", {})
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write('{"seq": 2, "ts": "trun')
        # The next real append must resume from the last *valid* seq (1),
        # not from a seq implied by the truncated garbage.
        event = ledger.append("RUN-1", "run.recovered", {})
        self.assertEqual(event.seq, 2)


class TestRunLedgerConcurrency(unittest.TestCase):
    """Directly exercises the concurrency weakness flagged in the M0
    review: many writers appending to the same run's ledger at once must
    not lose events or assign duplicate/gapped sequence numbers."""

    def test_no_lost_or_duplicate_events_under_thread_contention(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.jsonl"
            writer_count = 12
            events_per_writer = 15
            errors = []

            def worker(writer_index: int):
                try:
                    ledger = RunLedger(path)
                    for i in range(events_per_writer):
                        ledger.append("RUN-1", "run.progress", {"writer": writer_index, "i": i})
                except Exception as exc:  # pragma: no cover - surfaced via errors list
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(w,)) for w in range(writer_count)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)

            self.assertEqual(errors, [])
            events = RunLedger(path).read_all()
            seqs = [e.seq for e in events]
            expected_total = writer_count * events_per_writer
            self.assertEqual(len(events), expected_total)
            self.assertEqual(sorted(seqs), list(range(1, expected_total + 1)))
            self.assertEqual(len(set(seqs)), expected_total)  # no duplicate seqs


if __name__ == "__main__":
    unittest.main()
