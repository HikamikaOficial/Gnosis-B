"""The multi-worker plane: a durable queue and a budget.

The test that matters is `test_concurrent_workers_never_run_a_brief
_twice` — everything else is a property of that path. It uses real
threads racing on real files rather than a simulated interleaving,
because the mechanism under test IS the race.
"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.director.work_queue import WorkQueue, drain
from gnosis.kernel.budget import Budget, BudgetExhausted, BudgetLedger
from gnosis.kernel.claims import ClaimStatus, ClaimStore, WorkAuthority
from gnosis.kernel.file_lock import FileLock
from gnosis.kernel.lease import LeaseStore


def _brief(brief_id: str) -> DirectorBrief:
    return DirectorBrief(brief_id=brief_id, title=f"Do {brief_id}",
                         mission="Make it work.", source=BriefSource.MANUAL)


class _QueueTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.claims = ClaimStore(self.root / "claims.json")
        self.leases = LeaseStore(self.root / "leases.json")
        self.authority = WorkAuthority(self.claims, self.leases, default_ttl_s=60)
        self.queue = WorkQueue(self.root / "queue", self.authority)

    def tearDown(self):
        self.tmp.cleanup()


class TestOwnershipIsTheClaimsPlane(_QueueTestCase):
    def test_concurrent_workers_never_run_a_brief_twice(self):
        # Real threads, real files, one shared claims store. Two workers
        # scanning the same directory WILL see the same brief; the CAS is
        # what makes exactly one of them the owner.
        for index in range(24):
            self.queue.enqueue(_brief(f"BRIEF-{index:02d}"))

        executed: list[str] = []
        by_worker: dict[str, int] = {}
        guard = threading.Lock()
        started = threading.Barrier(6)
        errors: list[BaseException] = []

        def worker(name: str) -> None:
            try:
                started.wait(timeout=10)
                for work in drain(self.queue, name):
                    with guard:
                        executed.append(work.brief_id)
                        by_worker[name] = by_worker.get(name, 0) + 1
                    # Hold the claim briefly so the race window is real.
                    time.sleep(0.002)
                    self.queue.complete(work, outcome="COMPLETED")
            except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(f"worker-{i}",))
                   for i in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(errors, [])
        self.assertEqual(len(executed), 24, "a brief ran more than once")
        self.assertEqual(sorted(executed), sorted(set(executed)))
        self.assertEqual(self.queue.depth(), 0)
        self.assertEqual(len(self.queue.done_ids()), 24)
        # If one worker drained the queue before the others woke up, the
        # race never happened and this test proves nothing.
        self.assertGreater(len(by_worker), 1, f"only one worker ran: {by_worker}")

    def test_a_claimed_brief_is_invisible_to_other_workers(self):
        self.queue.enqueue(_brief("BRIEF-1"))
        first = self.queue.claim("worker-a")
        self.assertIsNotNone(first)
        self.assertIsNone(self.queue.claim("worker-b"))
        self.assertEqual(self.queue.running_ids(), ["BRIEF-1"])

    def test_the_grant_proves_ownership_and_survives_to_completion(self):
        self.queue.enqueue(_brief("BRIEF-1"))
        work = self.queue.claim("worker-a")
        # The claims plane, not the queue, is the authority on this.
        self.authority.assert_current(work.grant)
        self.queue.complete(work, outcome="COMPLETED")
        self.assertEqual(self.claims.get("BRIEF-1").status, ClaimStatus.RESOLVED)

    def test_enqueue_is_idempotent_by_brief_id(self):
        self.assertTrue(self.queue.enqueue(_brief("BRIEF-1")))
        self.assertFalse(self.queue.enqueue(_brief("BRIEF-1")))
        self.assertEqual(self.queue.pending_ids(), ["BRIEF-1"])

    def test_a_brief_already_running_cannot_be_re_enqueued(self):
        # Re-enqueuing live work would create a second task for it and
        # orphan the first one's evidence.
        self.queue.enqueue(_brief("BRIEF-1"))
        self.queue.claim("worker-a")
        self.assertFalse(self.queue.enqueue(_brief("BRIEF-1")))


class TestParksReturnWorkToTheQueue(_QueueTestCase):
    def test_a_released_brief_is_claimable_again(self):
        # Rule 6: a park leaves the work untouched and resumable, so it
        # must become claimable — not consumed.
        self.queue.enqueue(_brief("BRIEF-1"))
        work = self.queue.claim("worker-a")
        self.queue.release(work, reason="rate_limited:usage")

        self.assertEqual(self.queue.pending_ids(), ["BRIEF-1"])
        self.assertEqual(self.queue.running_ids(), [])
        again = self.queue.claim("worker-b")
        self.assertIsNotNone(again)
        self.assertEqual(again.brief_id, "BRIEF-1")

    def test_attempts_are_counted_across_claims(self):
        self.queue.enqueue(_brief("BRIEF-1"))
        first = self.queue.claim("worker-a")
        self.assertEqual(first.attempts, 1)
        self.queue.release(first, reason="parked")
        second = self.queue.claim("worker-b")
        self.assertEqual(second.attempts, 2)

    def test_a_completed_brief_does_not_come_back(self):
        self.queue.enqueue(_brief("BRIEF-1"))
        self.queue.complete(self.queue.claim("worker-a"), outcome="COMPLETED")
        self.assertIsNone(self.queue.claim("worker-b"))


class TestACrashedWorkerLosesNothing(_QueueTestCase):
    """Reclaimed ownership is not enough: the record has to come back too."""

    def _short_lived(self, clock=time.time) -> WorkQueue:
        authority = WorkAuthority(
            ClaimStore(self.root / "c2.json", clock=clock),
            LeaseStore(self.root / "l2.json", clock=clock),
            default_ttl_s=0.05, reclaim_grace_s=0.0, clock=clock,
        )
        return WorkQueue(self.root / "q2", authority, clock=clock)

    def test_a_brief_whose_worker_died_becomes_claimable_again(self):
        # Verified before shipping: the claims plane reclaimed the claim
        # through the lease TTL, and the brief still sat in `running/`
        # where no worker looks — ownership free, record unreachable,
        # which is the ghost rule 4 forbids.
        clock = [1000.0]
        queue = self._short_lived(clock=lambda: clock[0])
        queue.enqueue(_brief("BRIEF-1"))
        self.assertIsNotNone(queue.claim("worker-that-dies"))

        # Expire an acquired lease, independent of CI disk write latency.
        clock[0] += 0.15
        queue.authority.sweep()
        self.assertEqual(queue.running_ids(), ["BRIEF-1"])
        self.assertIsNone(queue.claim("worker-b"), "should be invisible before recovery")

        self.assertEqual(queue.recover(), ["BRIEF-1"])
        again = queue.claim("worker-b")
        self.assertIsNotNone(again)
        self.assertEqual(again.brief_id, "BRIEF-1")

    def test_recovery_never_takes_a_brief_from_a_live_worker(self):
        # The premise is a LIVE lease, not "all Windows disk writes take <50ms".
        queue = self._short_lived(clock=lambda: 1000.0)
        queue.enqueue(_brief("BRIEF-1"))
        live = queue.claim("worker-a")

        self.assertEqual(queue.recover(), [])
        self.assertEqual(queue.running_ids(), ["BRIEF-1"])
        # ...and the live worker can still finish.
        queue.complete(live, outcome="COMPLETED")
        self.assertEqual(queue.done_ids(), ["BRIEF-1"])

    def test_recovery_is_idempotent(self):
        clock = [1000.0]
        queue = self._short_lived(clock=lambda: clock[0])
        queue.enqueue(_brief("BRIEF-1"))
        self.assertIsNotNone(queue.claim("worker-that-dies"))
        clock[0] += 0.15
        queue.authority.sweep()

        self.assertEqual(queue.recover(), ["BRIEF-1"])
        self.assertEqual(queue.recover(), [])
        self.assertEqual(queue.pending_ids(), ["BRIEF-1"])


class TestRepairsFromTheIndependentReview(_QueueTestCase):
    def _short_lived(self, clock=time.time, **kwargs):
        authority = WorkAuthority(
            ClaimStore(self.root / "c3.json", clock=clock),
            LeaseStore(self.root / "l3.json", clock=clock),
            default_ttl_s=0.05, reclaim_grace_s=0.0, clock=clock,
        )
        return WorkQueue(self.root / "q3", authority, clock=clock, **kwargs)

    def test_a_crash_after_completing_does_not_re_execute_the_work(self):
        # `complete` resolves the claim and THEN moves the file. A crash
        # between them left a RESOLVED claim with the record in
        # `running/`, and my own recovery returned it to `pending` — which
        # would re-execute finished work, worse than the ghost recovery
        # exists to prevent (independent review caught it in the fix).
        queue = self._short_lived(clock=lambda: 1000.0)
        queue.enqueue(_brief("BRIEF-1"))
        work = queue.claim("worker-a")
        queue.authority.resolve(work.grant, outcome="COMPLETED")   # then the crash

        self.assertEqual(queue.recover(), ["BRIEF-1"])
        self.assertEqual(queue.done_ids(), ["BRIEF-1"])
        self.assertEqual(queue.pending_ids(), [])
        self.assertIsNone(queue.claim("worker-b"))

    def test_a_crash_after_releasing_returns_the_work(self):
        queue = self._short_lived(clock=lambda: 1000.0)
        queue.enqueue(_brief("BRIEF-1"))
        work = queue.claim("worker-a")
        queue.authority.release(work.grant)                        # then the crash

        self.assertEqual(queue.recover(), ["BRIEF-1"])
        self.assertEqual(queue.pending_ids(), ["BRIEF-1"])

    def test_a_brief_is_not_re_offered_forever(self):
        # Rule 8. `release` returns work to pending and `drain` re-offers
        # it immediately; the per-brief budget does NOT bound that,
        # because parking launches nothing and spends nothing.
        queue = self._short_lived(clock=lambda: 1000.0, max_attempts=3)
        queue.enqueue(_brief("BRIEF-1"))
        for _ in range(3):
            work = queue.claim("worker-a")
            self.assertIsNotNone(work)
            queue.release(work, reason="parked")

        self.assertIsNone(queue.claim("worker-a"))
        self.assertTrue(any("attempts_exhausted" in reason
                            for _, reason in queue.skipped))
        # It LEAVES the queue rather than being skipped on every future
        # scan: a brief nobody will ever claim, sitting in `pending`
        # forever, is a decision no operator can see.
        self.assertEqual(queue.pending_ids(), [])
        self.assertEqual(queue.blocked_ids(), ["BRIEF-1"])

        # And only an operator brings it back.
        self.assertTrue(queue.requeue("BRIEF-1"))
        self.assertIsNotNone(queue.claim("worker-a"))

    def test_concurrent_enqueue_of_one_brief_id_admits_exactly_one(self):
        # Both racers passed the existence check before either wrote, and
        # replace-based writing let the later one silently win.
        results: list[bool] = []
        guard = threading.Lock()
        ready = threading.Barrier(8)

        def enqueue() -> None:
            ready.wait(timeout=10)
            accepted = self.queue.enqueue(_brief("BRIEF-RACE"))
            with guard:
                results.append(accepted)

        threads = [threading.Thread(target=enqueue) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(sum(results), 1, results)
        self.assertEqual(self.queue.pending_ids(), ["BRIEF-RACE"])

    def test_drain_recovers_stranded_work_before_claiming(self):
        # A mechanism nothing calls is a parallel fiction; a worker
        # starting up is when a previous worker's stranded record should
        # come back.
        clock = [1000.0]
        queue = self._short_lived(clock=lambda: clock[0])
        queue.enqueue(_brief("BRIEF-1"))
        self.assertIsNotNone(queue.claim("worker-that-dies"))
        clock[0] += 0.15
        queue.authority.sweep()

        claimed = [w.brief_id for w in drain(queue, "worker-b")]
        self.assertEqual(claimed, ["BRIEF-1"])


class TestDamageIsNotAnOutage(_QueueTestCase):
    def test_one_unreadable_record_does_not_stop_the_queue(self):
        # A queue that refuses to run because one file is damaged turns a
        # single bad record into a total outage.
        self.queue.enqueue(_brief("BRIEF-GOOD"))
        (self.queue.root / "pending" / "BRIEF-BAD.json").write_text(
            "{not json", encoding="utf-8")

        claimed = [w.brief_id for w in drain(self.queue, "worker-a")]
        self.assertEqual(claimed, ["BRIEF-GOOD"])
        # And the damaged record is still there for a human to look at.
        self.assertTrue((self.queue.root / "pending" / "BRIEF-BAD.json").exists())


class TestBudget(unittest.TestCase):
    def test_launches_are_bounded(self):
        ledger = BudgetLedger(Budget(max_agent_launches=2))
        ledger.check()
        ledger.spend_launch()
        ledger.check()
        ledger.spend_launch()
        with self.assertRaises(BudgetExhausted) as caught:
            ledger.check()
        self.assertEqual(caught.exception.kind, "max_agent_launches")

    def test_wall_clock_is_bounded(self):
        now = [1000.0]
        ledger = BudgetLedger(Budget(wall_clock_s=30.0), clock=lambda: now[0])
        ledger.check()
        now[0] += 29.0
        ledger.check()
        now[0] += 2.0
        with self.assertRaises(BudgetExhausted) as caught:
            ledger.check()
        self.assertEqual(caught.exception.kind, "wall_clock_s")

    def test_an_unbounded_budget_never_refuses(self):
        ledger = BudgetLedger()
        for _ in range(100):
            ledger.check()
            ledger.spend_launch()
        self.assertIsNone(ledger.remaining_launches())

    def test_a_launch_is_counted_before_it_can_crash(self):
        # Counting on the way out would let a crash-looping brief spend
        # forever.
        ledger = BudgetLedger(Budget(max_agent_launches=1))
        ledger.spend_launch()          # the child then explodes
        with self.assertRaises(BudgetExhausted):
            ledger.check()

    def test_a_nonsense_budget_is_refused_at_construction(self):
        for kwargs in ({"wall_clock_s": 0}, {"max_agent_launches": 0},
                       {"wall_clock_s": -1}):
            with self.assertRaises(ValueError):
                Budget(**kwargs)
        # bool is int in Python; a budget of `True` is a mistake, not 1.
        with self.assertRaises(TypeError):
            Budget(max_agent_launches=True)

    def test_a_resumed_brief_inherits_what_it_already_spent(self):
        # An in-memory ledger tracked one INVOCATION, so a parked brief
        # that was released and re-claimed started from zero and could
        # launch agents forever while every individual run looked
        # bounded (independent review).
        import tempfile as _tempfile

        from gnosis.kernel.budget import BudgetStore
        with _tempfile.TemporaryDirectory() as tmp:
            store = BudgetStore(Path(tmp))
            budget = Budget(max_agent_launches=2)

            first = store.ledger_for("BRIEF-1", budget)
            first.check()
            first.spend_launch()
            store.record("BRIEF-1", first)

            # The brief parks, is released, and a new invocation starts.
            second = store.ledger_for("BRIEF-1", budget)
            self.assertEqual(second.launches, 1)
            second.check()
            second.spend_launch()
            store.record("BRIEF-1", second)

            third = store.ledger_for("BRIEF-1", budget)
            with self.assertRaises(BudgetExhausted):
                third.check()

    def test_unreadable_spend_reads_as_zero_and_says_so(self):
        import tempfile as _tempfile

        from gnosis.kernel.budget import BudgetStore
        with _tempfile.TemporaryDirectory() as tmp:
            store = BudgetStore(Path(tmp))
            (Path(tmp) / "BRIEF-1.json").write_text("{not json", encoding="utf-8")
            # Permissive direction, stated rather than hidden: the queue's
            # attempt cap is the bound that still applies.
            self.assertEqual(store.load("BRIEF-1"), (0, 0.0))

    def test_the_ledger_reports_what_was_spent(self):
        ledger = BudgetLedger(Budget(max_agent_launches=3))
        ledger.spend_launch()
        payload = ledger.to_dict()
        self.assertEqual(payload["launches"], 1)
        self.assertEqual(payload["remaining_launches"], 2)


class TestACrashBetweenThePlaneAndTheFile(unittest.TestCase):
    """Every transition is a claims-plane call AND a file move. The window
    between them is where a decision gets silently reversed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = [1_000_000.0]
        self.authority = WorkAuthority(
            ClaimStore(self.root / "claims.json"),
            LeaseStore(self.root / "leases.json"),
            default_ttl_s=300,
        )
        self.queue = WorkQueue(self.root / "queue", self.authority,
                               clock=lambda: self.now[0])
        self.queue.enqueue(_brief("BRIEF-1"))

    def tearDown(self):
        self.tmp.cleanup()

    def _crash_after_the_plane_call(self, method, **kwargs):
        """Run the transition up to the plane call, then stop."""
        work = self.queue.claim("worker-a")
        assert work is not None
        original = self.queue._move
        self.queue._move = lambda *a, **k: None      # the crash
        try:
            method(work, **kwargs)
        finally:
            self.queue._move = original
        return work

    def test_a_lost_block_is_not_resurrected_by_recovery(self):
        # The decision that a human must look at this brief was made and
        # the claim was given up; recovery must finish it, not overrule it.
        self._crash_after_the_plane_call(self.queue.block, reason="needs_human")
        self.queue.recover()
        self.assertEqual(self.queue.blocked_ids(), ["BRIEF-1"])
        self.assertEqual(self.queue.pending_ids(), [])

    def test_a_lost_park_keeps_its_backoff(self):
        # "Backoff is durable" has to mean durable across the crash too,
        # or the pacing evaporates exactly when the system is least well.
        self._crash_after_the_plane_call(self.queue.release, reason="parked",
                                         not_before=self.now[0] + 60)
        self.queue.recover()
        self.assertEqual(self.queue.pending_ids(), ["BRIEF-1"])
        self.assertIsNone(self.queue.claim("worker-b"))
        self.now[0] += 61
        self.assertIsNotNone(self.queue.claim("worker-b"))

    def test_a_lost_completion_is_still_not_re_executed(self):
        self._crash_after_the_plane_call(self.queue.complete, outcome="COMPLETED")
        self.queue.recover()
        self.assertEqual(self.queue.done_ids(), ["BRIEF-1"])

    def test_a_requeued_brief_does_not_carry_the_old_block_marker(self):
        # Otherwise an operator revives a brief and the next crash sends
        # it straight back to blocked, citing a reason from a past life.
        self.queue.block(self.queue.claim("worker-a"), reason="needs_human")
        self.assertTrue(self.queue.requeue("BRIEF-1", reason="operator looked"))
        work = self.queue.claim("worker-b")
        self.authority.release(work.grant)          # crash, no intent stamped
        self.queue.recover()
        self.assertEqual(self.queue.pending_ids(), ["BRIEF-1"])
        self.assertEqual(self.queue.blocked_ids(), [])


class TestConcurrentRecovery(unittest.TestCase):
    """Two supervisors start together and both call `recover()` — the
    designed deployment, since concurrency comes from running several."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = [1_000_000.0]
        self.authority = WorkAuthority(
            ClaimStore(self.root / "c.json"), LeaseStore(self.root / "l.json"),
            default_ttl_s=300)

    def tearDown(self):
        self.tmp.cleanup()

    def _queue(self):
        return WorkQueue(self.root / "q", self.authority, clock=lambda: self.now[0])

    def _stranded(self, brief_id):
        queue = self._queue()
        queue.enqueue(_brief(brief_id))
        work = queue.claim("worker-that-dies")
        self.authority.release(work.grant)      # the claim is gone, the record is not

    def test_a_brief_never_ends_up_in_two_directories_at_once(self):
        # Write-then-unlink let the loser act on a stale read: it wrote
        # `pending` again and deleted the `running` record the winner had
        # just re-claimed, so one brief sat in both — and once the claim
        # resolved, a third worker ran it a second time.
        for i in range(8):
            self._stranded(f"BRIEF-{i}")

        barrier = threading.Barrier(4)
        errors: list = []

        def recover_and_claim(worker_id):
            # A DISTINCT worker id per thread. Sharing one is not a
            # deployment: the claims plane lets a holder re-acquire its
            # own claim, so four threads under one id depose each other
            # by design and the test would be measuring that instead.
            queue = self._queue()
            try:
                barrier.wait()
                queue.recover()
                while (work := queue.claim(worker_id)) is not None:
                    queue.complete(work, outcome="COMPLETED")
            except Exception as exc:            # noqa: BLE001 - reported below
                errors.append(exc)

        threads = [threading.Thread(target=recover_and_claim, args=(f"worker-{i}",))
                   for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertFalse([t for t in threads if t.is_alive()], "a recovery hung")
        self.assertEqual(errors, [])
        queue = self._queue()
        overlap = set(queue.pending_ids()) & set(queue.running_ids())
        self.assertEqual(overlap, set(), f"a brief is in two directories: {overlap}")
        # Every brief ended up in exactly one place, and each ran once.
        placed = (queue.pending_ids() + queue.running_ids()
                  + queue.done_ids() + queue.blocked_ids())
        self.assertEqual(sorted(placed), [f"BRIEF-{i}" for i in range(8)])
        self.assertEqual(len(placed), len(set(placed)))

    def test_claiming_and_recovering_cannot_interleave(self):
        # The invariant, tested directly. The multi-thread test above is a
        # smoke test: it does not force the interleaving and passes with
        # the lock removed, so on its own it would be a green test over a
        # race that never happened (L-0032). THIS is the evidence.
        #
        # `replace` alone cannot separate the two operations: it proves
        # the origin was still there, not that it was still the same
        # record. A recovery holding a read from before a claim landed
        # would move the file a live owner had just re-created.
        queue = self._queue()
        queue.enqueue(_brief("BRIEF-1"))     # claimable work, or claim
        held = FileLock(queue._lock_path, timeout_s=30.0)   # returns at once
        held.acquire()

        started, finished = threading.Event(), threading.Event()
        taken: list = []

        def claim_in_background():
            started.set()
            taken.append(self._queue().claim("worker-b"))
            finished.set()

        thread = threading.Thread(target=claim_in_background, daemon=True)
        thread.start()
        self.assertTrue(started.wait(timeout=10))
        self.assertFalse(finished.wait(timeout=1.5),
                         "claim did not wait for the queue lock")
        held.release()
        self.assertTrue(finished.wait(timeout=20), "claim never resumed")
        thread.join(timeout=10)
        self.assertIsNotNone(taken[0], "the claim was lost, not merely delayed")

    def test_recovering_waits_for_a_claim_in_progress(self):
        self._stranded("BRIEF-1")
        queue = self._queue()
        held = FileLock(queue._lock_path, timeout_s=30.0)
        held.acquire()

        started, finished = threading.Event(), threading.Event()

        def recover_in_background():
            started.set()
            self._queue().recover()
            finished.set()

        thread = threading.Thread(target=recover_in_background, daemon=True)
        thread.start()
        self.assertTrue(started.wait(timeout=10))
        self.assertFalse(finished.wait(timeout=1.5),
                         "recover did not wait for the queue lock")
        held.release()
        self.assertTrue(finished.wait(timeout=20), "recover never resumed")
        thread.join(timeout=10)

    def test_recovered_work_comes_back_paced(self):
        # A park's `not_before` survives on the record; a worker that
        # simply died left none, so a crash loop re-launched at full
        # speed with only `max_attempts` between it and forever.
        self._stranded("BRIEF-1")
        queue = self._queue()
        queue.recover(pace=lambda attempts: 45.0)

        self.assertEqual(queue.pending_ids(), ["BRIEF-1"])
        self.assertIsNone(queue.claim("worker-b"), "the crash came back unpaced")
        self.assertEqual([b for b, _ in queue.waiting()], ["BRIEF-1"])
        self.now[0] += 46
        self.assertIsNotNone(queue.claim("worker-b"))

    def test_a_recovered_completion_is_not_paced_it_is_done(self):
        queue = self._queue()
        queue.enqueue(_brief("BRIEF-1"))
        work = queue.claim("worker-a")
        self.authority.resolve(work.grant, outcome="COMPLETED")   # crash before the move
        queue.recover(pace=lambda attempts: 45.0)
        self.assertEqual(queue.done_ids(), ["BRIEF-1"])
        self.assertEqual(queue.waiting(), [])


class TestAVanishedRecordIsNotALicenceToGuess(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.authority = WorkAuthority(
            ClaimStore(self.root / "c.json"), LeaseStore(self.root / "l.json"),
            default_ttl_s=300)
        self.queue = WorkQueue(self.root / "q", self.authority)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_move_whose_origin_vanished_does_not_reset_the_attempt_bound(self):
        # Another worker's recovery moved the record between the plane
        # call and the move. Inventing a stub here wrote a record with no
        # `attempts`, so the next claim read 0 — an automated path
        # clearing the bound the module says only an operator clears.
        self.queue.enqueue(_brief("BRIEF-1"))
        for _ in range(3):
            work = self.queue.claim("worker-a")
            self.queue.release(work, reason="parked")
        record = json.loads(
            (self.root / "q" / "pending" / "BRIEF-1.json").read_text(encoding="utf-8"))
        self.assertEqual(record["attempts"], 3)

        work = self.queue.claim("worker-a")
        # A concurrent recovery takes the record away mid-transition.
        (self.root / "q" / "running" / "BRIEF-1.json").rename(
            self.root / "q" / "pending" / "BRIEF-1.json")
        self.queue.release(work, reason="parked")

        survived = json.loads(
            (self.root / "q" / "pending" / "BRIEF-1.json").read_text(encoding="utf-8"))
        self.assertEqual(survived["attempts"], 4, "the attempt bound was cleared")
        self.assertIn("brief", survived)
        self.assertIn("title", survived["brief"], "the brief payload was destroyed")
        self.assertTrue(any("vanished" in reason for _, reason in self.queue.skipped))

    def test_a_brief_whose_payload_was_stubbed_is_not_claimable_at_all(self):
        # The other half of the same defect: a stub record has no title,
        # so `DirectorBrief.from_dict` raised inside `claim` AFTER the
        # grant was taken — poisoning the brief for every future worker.
        self.queue.enqueue(_brief("BRIEF-1"))
        work = self.queue.claim("worker-a")
        (self.root / "q" / "running" / "BRIEF-1.json").unlink()
        self.queue.release(work, reason="parked")
        self.assertEqual(self.queue.pending_ids(), [])
        self.assertIsNone(self.queue.claim("worker-b"))


class TestAWaitNobodyCanSee(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = [1_000_000.0]
        self.authority = WorkAuthority(
            ClaimStore(self.root / "claims.json"),
            LeaseStore(self.root / "leases.json"),
            default_ttl_s=300,
        )
        self.queue = WorkQueue(self.root / "queue", self.authority,
                               clock=lambda: self.now[0])

    def tearDown(self):
        self.tmp.cleanup()

    def _park_with(self, brief_id, not_before):
        self.queue.enqueue(_brief(brief_id))
        work = self.queue.claim("worker-a")
        self.queue.release(work, reason="parked", not_before=1.0)
        path = self.root / "queue" / "pending" / f"{brief_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["not_before"] = not_before
        path.write_text(json.dumps(record), encoding="utf-8")

    def test_an_unusable_not_before_does_not_strand_a_brief(self):
        # inf, NaN and a string all read as "never claimable" if honoured
        # literally, and the brief keeps sitting in `pending` looking
        # available to anyone who lists the queue.
        values = [float("inf"), float("nan"), "soon", True]
        for index, value in enumerate(values):
            brief_id = f"BRIEF-{index}"
            self._park_with(brief_id, value)

        claimed = []
        while (work := self.queue.claim("worker-b")) is not None:
            claimed.append(work.brief_id)
            self.queue.complete(work, outcome="COMPLETED")

        self.assertEqual(len(claimed), len(values))
        # And the queue SAYS it ignored them rather than quietly deciding.
        self.assertEqual(len(self.queue.skipped), len(values))
        self.assertIn("unusable not_before", self.queue.skipped[0][1])

    def test_waiting_names_what_is_backing_off_and_until_when(self):
        self._park_with("BRIEF-1", self.now[0] + 90)
        self.assertEqual(self.queue.pending_ids(), ["BRIEF-1"])
        self.assertEqual(self.queue.waiting(), [("BRIEF-1", self.now[0] + 90)])
        self.now[0] += 91
        self.assertEqual(self.queue.waiting(), [])


if __name__ == "__main__":
    unittest.main()
