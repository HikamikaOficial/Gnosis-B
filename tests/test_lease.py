import tempfile
import threading
import unittest
from pathlib import Path

from gnosis.kernel.lease import LeaseHeldError, LeaseStore, StaleLeaseError


class FakeClock:
    """Deterministic, manually advanced clock so expiry paths are tested
    without real sleeps (and therefore without flakiness)."""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestLeaseStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "leases.json"
        self.clock = FakeClock()
        self.store = LeaseStore(self.path, clock=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_grant_has_token_one(self):
        lease = self.store.acquire("task/T1", "worker-a", ttl_s=30)
        self.assertEqual(lease.fencing_token, 1)
        self.assertEqual(lease.holder, "worker-a")
        self.assertEqual(self.store.current("task/T1").lease_id, lease.lease_id)

    def test_live_lease_blocks_second_acquire_even_same_holder(self):
        self.store.acquire("task/T1", "worker-a", ttl_s=30)
        with self.assertRaises(LeaseHeldError):
            self.store.acquire("task/T1", "worker-b", ttl_s=30)
        # Same holder too: renewal is heartbeat's job, double-acquire is a bug.
        with self.assertRaises(LeaseHeldError):
            self.store.acquire("task/T1", "worker-a", ttl_s=30)

    def test_expired_lease_is_taken_over_with_greater_token(self):
        old = self.store.acquire("task/T1", "worker-a", ttl_s=30)
        self.clock.advance(31)
        new = self.store.acquire("task/T1", "worker-b", ttl_s=30)
        self.assertGreater(new.fencing_token, old.fencing_token)
        self.assertEqual(new.holder, "worker-b")

    def test_deposed_holder_is_denied_everywhere(self):
        # The NO STALE WRITE invariant: after takeover, every operation
        # with the old lease_id fails loudly.
        old = self.store.acquire("task/T1", "worker-a", ttl_s=30)
        self.clock.advance(31)
        self.store.acquire("task/T1", "worker-b", ttl_s=30)

        with self.assertRaises(StaleLeaseError):
            self.store.assert_current("task/T1", old.lease_id)
        with self.assertRaises(StaleLeaseError):
            self.store.heartbeat("task/T1", old.lease_id, extend_s=30)
        with self.assertRaises(StaleLeaseError):
            self.store.release("task/T1", old.lease_id)

    def test_heartbeat_extends_expiry(self):
        lease = self.store.acquire("task/T1", "worker-a", ttl_s=30)
        self.clock.advance(20)
        renewed = self.store.heartbeat("task/T1", lease.lease_id, extend_s=30)
        self.assertEqual(renewed.lease_id, lease.lease_id)
        self.assertEqual(renewed.fencing_token, lease.fencing_token)
        self.clock.advance(25)  # 45s after issue; would be dead without renewal
        self.store.assert_current("task/T1", lease.lease_id)

    def test_expired_lease_fails_assert_even_without_takeover(self):
        lease = self.store.acquire("task/T1", "worker-a", ttl_s=30)
        self.clock.advance(31)
        with self.assertRaises(StaleLeaseError):
            self.store.assert_current("task/T1", lease.lease_id)
        self.assertIsNone(self.store.current("task/T1"))

    def test_tokens_are_monotonic_across_release_and_regrant(self):
        first = self.store.acquire("task/T1", "worker-a", ttl_s=30)
        self.store.release("task/T1", first.lease_id)
        second = self.store.acquire("task/T1", "worker-a", ttl_s=30)
        self.assertEqual(second.fencing_token, first.fencing_token + 1)

    def test_resources_are_independent(self):
        a = self.store.acquire("task/T1", "worker-a", ttl_s=30)
        b = self.store.acquire("task/T2", "worker-b", ttl_s=30)
        self.assertEqual(a.fencing_token, 1)
        self.assertEqual(b.fencing_token, 1)

    def test_state_survives_reopen(self):
        lease = self.store.acquire("task/T1", "worker-a", ttl_s=30)
        reopened = LeaseStore(self.path, clock=self.clock)
        self.assertEqual(reopened.current("task/T1").lease_id, lease.lease_id)
        with self.assertRaises(LeaseHeldError):
            reopened.acquire("task/T1", "worker-b", ttl_s=30)

    def test_invalid_ttl_rejected(self):
        with self.assertRaises(ValueError):
            self.store.acquire("task/T1", "worker-a", ttl_s=0)


class TestLeaseStoreConcurrency(unittest.TestCase):
    def test_exactly_one_winner_under_thread_contention(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leases.json"
            winners: list[str] = []
            losers: list[str] = []
            unexpected: list[Exception] = []

            def worker(name: str) -> None:
                try:
                    store = LeaseStore(path)
                    store.acquire("task/T1", name, ttl_s=60)
                    winners.append(name)
                except LeaseHeldError:
                    losers.append(name)
                except Exception as exc:  # noqa: BLE001 - worker thread must surface, not raise
                    unexpected.append(exc)  # pragma: no cover - asserted empty below

            threads = [
                threading.Thread(target=worker, args=(f"worker-{i}",))
                for i in range(12)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)

            self.assertEqual(unexpected, [])
            self.assertEqual(len(winners), 1)
            self.assertEqual(len(losers), 11)
            lease = LeaseStore(path).current("task/T1")
            self.assertIsNotNone(lease)
            self.assertEqual(lease.holder, winners[0])
            self.assertEqual(lease.fencing_token, 1)


if __name__ == "__main__":
    unittest.main()
