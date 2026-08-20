import tempfile
import threading
import unittest
from pathlib import Path

from gnosis.kernel.claims import (
    ClaimConflictError,
    ClaimStatus,
    ClaimStore,
    StaleClaimError,
    WorkAuthority,
)
from gnosis.kernel.lease import LeaseHeldError, LeaseStore, StaleLeaseError


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestClaimStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.store = ClaimStore(Path(self.tmp.name) / "claims.json", clock=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fresh_claim_is_active_epoch_and_version_one(self):
        claim = self.store.claim("T1", "worker-a")
        self.assertEqual(claim.status, ClaimStatus.ACTIVE)
        self.assertEqual(claim.epoch, 1)
        self.assertEqual(claim.version, 1)

    def test_same_actor_retry_is_idempotent(self):
        first = self.store.claim("T1", "worker-a")
        again = self.store.claim("T1", "worker-a")
        # A retry is not an ownership mutation: neither version nor epoch move.
        self.assertEqual(again.version, first.version)
        self.assertEqual(again.epoch, first.epoch)

    def test_conflict_carries_typed_current_claim(self):
        self.store.claim("T1", "worker-a")
        try:
            self.store.claim("T1", "worker-b")
        except ClaimConflictError as exc:
            self.assertEqual(exc.claim.holder, "worker-a")
            self.assertEqual(exc.claim.status, ClaimStatus.ACTIVE)
            self.assertEqual(exc.claim.epoch, 1)
        else:
            self.fail("expected ClaimConflictError")

    def test_release_requires_matching_version(self):
        claim = self.store.claim("T1", "worker-a")
        with self.assertRaises(StaleClaimError):
            self.store.release("T1", "worker-a", expected_version=claim.version + 7)
        with self.assertRaises(StaleClaimError):
            self.store.release("T1", "worker-b", expected_version=claim.version)

    def test_epoch_increases_across_regrant(self):
        first = self.store.claim("T1", "worker-a")
        self.store.release("T1", "worker-a", expected_version=first.version)
        second = self.store.claim("T1", "worker-b")
        self.assertEqual(second.epoch, first.epoch + 1)
        self.assertEqual(second.status, ClaimStatus.ACTIVE)

    def test_resolve_is_terminal(self):
        claim = self.store.claim("T1", "worker-a")
        resolved = self.store.resolve("T1", "worker-a", claim.version, outcome="COMPLETED")
        self.assertEqual(resolved.status, ClaimStatus.RESOLVED)
        self.assertEqual(resolved.outcome, "COMPLETED")
        with self.assertRaises(StaleClaimError):
            self.store.release("T1", "worker-a", expected_version=resolved.version)

    def test_assert_active_rejects_wrong_epoch_and_non_active(self):
        claim = self.store.claim("T1", "worker-a")
        self.store.assert_active("T1", "worker-a", claim.epoch)
        with self.assertRaises(StaleClaimError):
            self.store.assert_active("T1", "worker-a", claim.epoch + 1)
        with self.assertRaises(StaleClaimError):
            self.store.assert_active("T1", "worker-b", claim.epoch)
        self.store.resolve("T1", "worker-a", claim.version, outcome="done")
        with self.assertRaises(StaleClaimError):
            self.store.assert_active("T1", "worker-a", claim.epoch)

    def test_reclaim_if_repeats_predicate_and_version_check(self):
        claim = self.store.claim("T1", "worker-a")
        # Version moved -> skip (None), not an error.
        self.assertIsNone(
            self.store.reclaim_if("T1", claim.version + 1, lambda: True, reason="x")
        )
        # Predicate false at mutation time -> skip.
        self.assertIsNone(
            self.store.reclaim_if("T1", claim.version, lambda: False, reason="x")
        )
        reclaimed = self.store.reclaim_if(
            "T1", claim.version, lambda: True, reason="lease expired"
        )
        self.assertIsNotNone(reclaimed)
        self.assertEqual(reclaimed.status, ClaimStatus.RECLAIMED)
        self.assertEqual(reclaimed.version, claim.version + 1)
        self.assertEqual(reclaimed.outcome, "lease expired")

    def test_history_records_every_ownership_mutation(self):
        first = self.store.claim("T1", "worker-a")
        self.store.release("T1", "worker-a", first.version)
        self.store.claim("T1", "worker-b")
        actions = [entry["action"] for entry in self.store.history("T1")]
        self.assertEqual(actions, ["claim", "release", "claim"])
        epochs = [entry["epoch"] for entry in self.store.history("T1")]
        self.assertEqual(epochs, [1, 1, 2])

    def test_state_survives_reopen(self):
        claim = self.store.claim("T1", "worker-a")
        reopened = ClaimStore(self.store.path, clock=self.clock)
        with self.assertRaises(ClaimConflictError):
            reopened.claim("T1", "worker-b")
        self.assertEqual(reopened.get("T1").version, claim.version)

    def test_exactly_one_winner_under_thread_contention(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claims.json"
            winners: list[str] = []
            conflicts: list[str] = []
            unexpected: list[Exception] = []

            def worker(name: str) -> None:
                try:
                    ClaimStore(path).claim("T1", name)
                    winners.append(name)
                except ClaimConflictError:
                    conflicts.append(name)
                except Exception as exc:  # noqa: BLE001 - worker thread must surface, not raise
                    unexpected.append(exc)  # pragma: no cover - asserted empty below

            threads = [
                threading.Thread(target=worker, args=(f"w{i}",)) for i in range(12)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)

            self.assertEqual(unexpected, [])
            self.assertEqual(len(winners), 1)
            self.assertEqual(len(conflicts), 11)
            final = ClaimStore(path).get("T1")
            self.assertEqual(final.holder, winners[0])
            self.assertEqual(final.epoch, 1)


class TestWorkAuthority(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.clock = FakeClock()
        self.claims = ClaimStore(root / "claims.json", clock=self.clock)
        self.leases = LeaseStore(root / "leases.json", clock=self.clock)
        self.authority = WorkAuthority(
            self.claims, self.leases, default_ttl_s=60,
            reclaim_grace_s=30, clock=self.clock,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_acquire_grants_both_planes(self):
        grant = self.authority.acquire("T1", "worker-a")
        self.assertEqual(grant.claim.epoch, 1)
        self.assertEqual(grant.lease.fencing_token, 1)
        self.authority.assert_current(grant)

    def test_second_worker_conflicts_while_active(self):
        self.authority.acquire("T1", "worker-a")
        with self.assertRaises(ClaimConflictError):
            self.authority.acquire("T1", "worker-b")

    def test_same_actor_retry_reuses_live_lease(self):
        first = self.authority.acquire("T1", "worker-a")
        again = self.authority.acquire("T1", "worker-a")
        self.assertEqual(again.lease.lease_id, first.lease.lease_id)
        self.assertEqual(again.claim.version, first.claim.version)

    def test_sweep_reclaims_only_expired(self):
        self.authority.acquire("T1", "worker-a")
        # Past the grace window but the lease is still live: the lease
        # predicate alone must protect the claim.
        self.clock.advance(40)
        self.assertEqual(self.authority.sweep(), [])
        self.clock.advance(21)  # now the 60s lease has expired too
        reclaimed = self.authority.sweep()
        self.assertEqual([c.task_id for c in reclaimed], ["T1"])
        self.assertEqual(reclaimed[0].status, ClaimStatus.RECLAIMED)

    def test_sweep_grace_protects_fresh_claim_without_lease(self):
        # acquire()'s claim-then-lease window: a claim exists but its lease
        # was never acquired. Inside the grace window the sweep must not
        # touch it; after the grace window it is fair game.
        self.claims.claim("T1", "worker-a")
        self.assertEqual(self.authority.sweep(), [])
        self.clock.advance(31)
        reclaimed = self.authority.sweep()
        self.assertEqual([c.task_id for c in reclaimed], ["T1"])

    def test_assert_current_lease_plane_is_individually_load_bearing(self):
        # Lease expired, claim still ACTIVE (no sweep ran): the lease-plane
        # check alone must reject the grant.
        grant = self.authority.acquire("T1", "worker-a")
        self.clock.advance(61)
        self.assertEqual(self.claims.get("T1").status, ClaimStatus.ACTIVE)
        with self.assertRaises(StaleLeaseError):
            self.authority.assert_current(grant)

    def test_assert_current_claim_plane_is_individually_load_bearing(self):
        # Claim reclaimed while the lease is still live: the claim-plane
        # check alone must reject the grant.
        grant = self.authority.acquire("T1", "worker-a")
        self.claims.reclaim_if("T1", grant.claim.version, lambda: True, reason="forced")
        self.assertIsNotNone(self.leases.current("task/T1"))  # lease still live
        with self.assertRaises(StaleClaimError):
            self.authority.assert_current(grant)

    def test_release_frees_both_planes_for_the_next_worker(self):
        grant = self.authority.acquire("T1", "worker-a")
        released = self.authority.release(grant)
        self.assertEqual(released.status, ClaimStatus.RELEASED)
        self.assertIsNone(self.leases.current("task/T1"))
        # No TTL latency for the successor: immediate re-acquire works.
        succ = self.authority.acquire("T1", "worker-b")
        self.assertGreater(succ.claim.epoch, grant.claim.epoch)

    def test_heartbeat_extends_by_the_grants_own_ttl(self):
        # Renewals honor the TTL the grant was acquired with, not the
        # facade default (adversarial-review finding).
        grant = self.authority.acquire("T1", "worker-a", ttl_s=600)
        self.clock.advance(500)  # would be dead under the 60s default
        renewed = self.authority.heartbeat(grant)
        self.assertEqual(renewed.expires_at, self.clock.now + 600)
        self.clock.advance(599)
        self.authority.assert_current(grant)

    def test_resolve_succeeds_even_if_lease_expired_after_entry_check(self):
        # The claim commit is the durable truth; a lease that expires in
        # the resolve window must not convert completed work into a
        # caller-visible failure (adversarial-review finding). Simulate the
        # window by expiring the lease between two resolves' plane checks:
        # here we expire it right before calling resolve's internals via a
        # lease whose TTL ends exactly now.
        grant = self.authority.acquire("T1", "worker-a", ttl_s=60)
        # Craft the interleaving deterministically: pass the entry check,
        # then expire the lease before the final release by advancing the
        # clock inside a patched claims.resolve.
        original_resolve = self.claims.resolve

        def resolve_then_expire(*args, **kwargs):
            result = original_resolve(*args, **kwargs)
            self.clock.advance(61)  # lease dies after the claim committed
            return result

        self.claims.resolve = resolve_then_expire
        try:
            resolved = self.authority.resolve(grant, outcome="COMPLETED")
        finally:
            self.claims.resolve = original_resolve
        self.assertEqual(resolved.status, ClaimStatus.RESOLVED)

    def test_deposed_grant_fails_assert_and_new_worker_supersedes(self):
        old = self.authority.acquire("T1", "worker-a")
        self.clock.advance(61)
        self.authority.sweep()
        new = self.authority.acquire("T1", "worker-b")
        self.assertGreater(new.claim.epoch, old.claim.epoch)
        self.assertGreater(new.lease.fencing_token, old.lease.fencing_token)
        with self.assertRaises((StaleLeaseError, StaleClaimError)):
            self.authority.assert_current(old)
        self.authority.assert_current(new)

    def test_heartbeat_keeps_grant_alive(self):
        grant = self.authority.acquire("T1", "worker-a")
        self.clock.advance(50)
        self.authority.heartbeat(grant)
        self.clock.advance(50)  # 100s after issue; dead without the heartbeat
        self.assertEqual(self.authority.sweep(), [])
        self.authority.assert_current(grant)

    def test_resolve_ends_both_planes(self):
        grant = self.authority.acquire("T1", "worker-a")
        resolved = self.authority.resolve(grant, outcome="COMPLETED")
        self.assertEqual(resolved.status, ClaimStatus.RESOLVED)
        self.assertIsNone(self.leases.current("task/T1"))

    def test_reclaimed_claim_with_live_foreign_lease_fails_loudly(self):
        # Pathological but constructible: the claim was reclaimed while the
        # old holder's lease is somehow still live. The new worker's acquire
        # must fail loudly on the lease plane, not half-succeed.
        grant = self.authority.acquire("T1", "worker-a")
        self.claims.reclaim_if("T1", grant.claim.version, lambda: True, reason="forced")
        with self.assertRaises(LeaseHeldError):
            self.authority.acquire("T1", "worker-b")


if __name__ == "__main__":
    unittest.main()
