import tempfile
import threading
import time
import unittest
from pathlib import Path

from gnosis.kernel.file_lock import FileLock, LockTimeoutError, lock_path_for


class TestFileLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "resource.lock"

    def tearDown(self):
        self.tmp.cleanup()

    def test_acquire_and_release(self):
        lock = FileLock(self.path)
        lock.acquire()
        lock.release()
        # Should be acquirable again after release.
        lock2 = FileLock(self.path)
        lock2.acquire()
        lock2.release()

    def test_context_manager(self):
        with FileLock(self.path):
            pass

    def test_second_holder_blocks_until_first_releases(self):
        order = []
        first = FileLock(self.path)
        first.acquire()

        def try_acquire_second():
            second = FileLock(self.path, timeout_s=5.0, poll_interval_s=0.01)
            second.acquire()
            order.append("second")
            second.release()

        t = threading.Thread(target=try_acquire_second)
        t.start()
        time.sleep(0.2)
        order.append("first_still_holding")
        first.release()
        t.join(timeout=5)
        self.assertEqual(order, ["first_still_holding", "second"])

    def test_timeout_raises(self):
        holder = FileLock(self.path)
        holder.acquire()
        try:
            blocked = FileLock(self.path, timeout_s=0.2, poll_interval_s=0.02)
            with self.assertRaises(LockTimeoutError):
                blocked.acquire()
        finally:
            holder.release()

    def test_lock_path_for(self):
        resource = Path("runs/RUN-1/ledger.jsonl")
        self.assertEqual(lock_path_for(resource).name, "ledger.jsonl.lock")


class TestFileLockConcurrentCounter(unittest.TestCase):
    """A shared-counter stress test: N threads each increment a counter
    persisted in a file, guarded by FileLock. Without the lock this would
    lose updates under races; with it, the final count must be exact."""

    def test_no_lost_updates_under_thread_contention(self):
        with tempfile.TemporaryDirectory() as tmp:
            counter_path = Path(tmp) / "counter.txt"
            counter_path.write_text("0", encoding="utf-8")
            lock_path = lock_path_for(counter_path)

            increments_per_thread = 25
            thread_count = 8

            def worker():
                for _ in range(increments_per_thread):
                    # A fresh FileLock per critical section: this is how
                    # RunLedger/RunStore actually use it (one instance per
                    # call), and it is what makes cross-thread AND
                    # cross-process contention both work, unlike sharing a
                    # single instance (which owns exactly one OS handle).
                    with FileLock(lock_path, timeout_s=10.0):
                        current = int(counter_path.read_text(encoding="utf-8"))
                        counter_path.write_text(str(current + 1), encoding="utf-8")

            threads = [threading.Thread(target=worker) for _ in range(thread_count)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            final = int(counter_path.read_text(encoding="utf-8"))
            self.assertEqual(final, increments_per_thread * thread_count)


if __name__ == "__main__":
    unittest.main()
