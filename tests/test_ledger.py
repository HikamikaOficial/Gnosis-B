import json
import tempfile
import threading
import unittest
from pathlib import Path

from gnosis.kernel.canonical import GENESIS_HASH, hash_canonical
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


class TestRunLedgerHashChain(unittest.TestCase):
    """Directive 2 (REFERENCE_REPOSITORY_FINDINGS): append-only chain with
    per-event hashes, full-chain verification, fail-closed on interior
    corruption, torn tail tolerated, legacy prefix never extended."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.jsonl"
        self.ledger = RunLedger(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_events_are_chained_from_genesis(self):
        e1 = self.ledger.append("RUN-1", "run.started", {})
        e2 = self.ledger.append("RUN-1", "run.finished", {})
        self.assertEqual(e1.prev_hash, GENESIS_HASH)
        self.assertEqual(e2.prev_hash, e1.event_hash)
        self.assertEqual(e1.event_hash, hash_canonical(e1.hashable_payload()))
        verified = self.ledger.verify_chain()
        self.assertEqual([e.seq for e in verified], [1, 2])

    def test_chain_survives_reopen(self):
        self.ledger.append("RUN-1", "run.started", {})
        reopened = RunLedger(self.path)
        e2 = reopened.append("RUN-1", "run.finished", {})
        self.assertEqual(e2.prev_hash, reopened.read_all()[0].event_hash)
        reopened.verify_chain()

    def test_tampered_payload_is_detected_and_blocks_append(self):
        self.ledger.append("RUN-1", "run.started", {"amount": 1})
        self.ledger.append("RUN-1", "run.finished", {})
        lines = self.path.read_text(encoding="utf-8").splitlines()
        lines[0] = lines[0].replace('"amount": 1', '"amount": 999')
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with self.assertRaises(LedgerCorruptionError):
            self.ledger.verify_chain()
        with self.assertRaises(LedgerCorruptionError):
            self.ledger.append("RUN-1", "run.more", {})

    def test_deleted_interior_event_is_detected(self):
        for i in range(3):
            self.ledger.append("RUN-1", "run.progress", {"i": i})
        lines = self.path.read_text(encoding="utf-8").splitlines()
        del lines[1]
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with self.assertRaises(LedgerCorruptionError):
            self.ledger.verify_chain()

    def test_torn_tail_still_verifies_and_append_recovers(self):
        e1 = self.ledger.append("RUN-1", "run.started", {})
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write('{"seq": 2, "ts": "trun')
        verified = self.ledger.verify_chain()
        self.assertEqual(len(verified), 1)
        e2 = self.ledger.append("RUN-1", "run.recovered", {})
        self.assertEqual(e2.seq, 2)
        self.assertEqual(e2.prev_hash, e1.event_hash)

    def test_legacy_ledger_is_readable_but_refuses_appends(self):
        legacy = {"seq": 1, "ts": "2026-01-01T00:00:00+00:00",
                  "run_id": "RUN-L", "event_type": "run.started", "data": {}}
        self.path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
        events = self.ledger.read_all()
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].event_hash)
        self.ledger.verify_chain()  # legacy-only: readable, not an error
        with self.assertRaises(LedgerCorruptionError):
            self.ledger.append("RUN-L", "run.more", {})

    def test_chained_event_after_legacy_prefix_is_rejected(self):
        legacy = {"seq": 1, "ts": "2026-01-01T00:00:00+00:00",
                  "run_id": "RUN-L", "event_type": "run.started", "data": {}}
        forged = {"seq": 2, "ts": "2026-01-01T00:00:01+00:00",
                  "run_id": "RUN-L", "event_type": "run.forged", "data": {},
                  "prev_hash": GENESIS_HASH}
        forged["event_hash"] = hash_canonical(forged)
        self.path.write_text(
            json.dumps(legacy) + "\n" + json.dumps(forged) + "\n", encoding="utf-8",
        )
        with self.assertRaises(LedgerCorruptionError):
            self.ledger.verify_chain()


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
