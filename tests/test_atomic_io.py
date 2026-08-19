import tempfile
import unittest
from pathlib import Path

from gnosis.kernel.atomic_io import atomic_write_text


class TestAtomicWriteText(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_and_read_back(self):
        atomic_write_text(self.path, '{"a": 1}')
        self.assertEqual(self.path.read_text(encoding="utf-8"), '{"a": 1}')

    def test_overwrite_leaves_no_temp_files(self):
        atomic_write_text(self.path, "first")
        atomic_write_text(self.path, "second")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "second")
        leftovers = list(self.path.parent.glob("*.tmp-*"))
        self.assertEqual(leftovers, [])

    def test_creates_parent_directories(self):
        nested = Path(self.tmp.name) / "a" / "b" / "state.json"
        atomic_write_text(nested, "x")
        self.assertEqual(nested.read_text(encoding="utf-8"), "x")

    def test_old_content_intact_if_never_replaced(self):
        # Simulates "crash before os.replace()": the tmp file is written
        # but the final os.replace() never runs. The destination path
        # must still hold the last successfully-committed content, never
        # a torn write.
        atomic_write_text(self.path, "committed")
        tmp_path = self.path.with_name(self.path.name + ".tmp-simulated")
        tmp_path.write_text("half-writ", encoding="utf-8")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "committed")


if __name__ == "__main__":
    unittest.main()
