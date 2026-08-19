import re
import unittest

from gnosis.kernel.ids import is_run_id, is_task_id, new_run_id, new_task_id

_ID_RE = re.compile(r"^(TASK|RUN)-\d{8}T\d{9}Z-[0-9a-f]{8}$")


class TestIds(unittest.TestCase):
    def test_format(self):
        self.assertRegex(new_task_id(), _ID_RE)
        self.assertRegex(new_run_id(), _ID_RE)

    def test_prefix_predicates(self):
        self.assertTrue(is_task_id(new_task_id()))
        self.assertFalse(is_task_id(new_run_id()))
        self.assertTrue(is_run_id(new_run_id()))
        self.assertFalse(is_run_id(new_task_id()))

    def test_uniqueness(self):
        ids = {new_run_id() for _ in range(200)}
        self.assertEqual(len(ids), 200)


if __name__ == "__main__":
    unittest.main()
