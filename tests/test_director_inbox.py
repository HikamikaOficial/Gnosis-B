import json
import tempfile
import unittest
from pathlib import Path

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.director.inbox import DirectorInbox


class TestDirectorInbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / ".gnosis" / "director"
        self.inbox = DirectorInbox(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def _drop_brief(self, brief_id: str, filename: str = None) -> Path:
        brief = DirectorBrief(brief_id=brief_id, title="T", mission="Do it.", source=BriefSource.MANUAL)
        path = self.inbox.layout.inbox / (filename or f"{brief_id}.json")
        path.write_text(json.dumps(brief.to_dict()), encoding="utf-8")
        return path

    def test_layout_created(self):
        for d in ("inbox", "processed", "rejected", "outbox", "escalations"):
            self.assertTrue((self.root / d).is_dir())

    def test_claim_moves_to_processed(self):
        path = self._drop_brief("BRIEF-1")
        result = self.inbox.claim(path)
        self.assertTrue(result.accepted)
        self.assertEqual(result.brief.brief_id, "BRIEF-1")
        self.assertFalse(path.exists())
        self.assertTrue((self.inbox.layout.processed / "BRIEF-1.json").exists())

    def test_list_pending_reflects_inbox_only(self):
        self._drop_brief("BRIEF-1")
        self.assertEqual(len(self.inbox.list_pending()), 1)
        self.inbox.claim(self.inbox.list_pending()[0])
        self.assertEqual(len(self.inbox.list_pending()), 0)

    def test_malformed_brief_rejected_not_dropped(self):
        path = self.inbox.layout.inbox / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        result = self.inbox.claim(path)
        self.assertFalse(result.accepted)
        self.assertFalse(path.exists())
        rejected = list(self.inbox.layout.rejected.glob("malformed-*"))
        self.assertEqual(len(rejected), 1)

    def test_duplicate_brief_id_rejected(self):
        first = self._drop_brief("BRIEF-1")
        self.inbox.claim(first)

        second = self._drop_brief("BRIEF-1", filename="resubmitted.json")
        result = self.inbox.claim(second)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "duplicate brief_id")
        self.assertFalse(second.exists())
        duplicates = list(self.inbox.layout.rejected.glob("duplicate-*"))
        self.assertEqual(len(duplicates), 1)
        # Original processed record must be untouched by the duplicate attempt.
        self.assertTrue((self.inbox.layout.processed / "BRIEF-1.json").exists())

    def test_is_processed(self):
        self.assertFalse(self.inbox.is_processed("BRIEF-1"))
        self.inbox.claim(self._drop_brief("BRIEF-1"))
        self.assertTrue(self.inbox.is_processed("BRIEF-1"))


if __name__ == "__main__":
    unittest.main()
