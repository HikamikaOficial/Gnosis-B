"""Worker supervision: pacing, circuit breakers, and what it may not decide.

The tests that carry this file are `test_backoff_survives_a_restart` —
because pacing held in memory is pacing a crash forgets — and the
`TestWhatASupervisorMayNotDecide` class, which pins the line between
doing less and deciding to re-run work whose outcome nobody recorded.
"""
import tempfile
import unittest
from pathlib import Path

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.director.supervisor import (
    BackoffPolicy,
    Disposition,
    StopReason,
    SupervisorPolicy,
    WorkerSupervisor,
)
from gnosis.director.work_queue import WorkQueue
from gnosis.kernel.budget import BudgetExhausted
from gnosis.kernel.claims import ClaimStore, WorkAuthority
from gnosis.kernel.lease import LeaseStore
from gnosis.runner.gated_runner import CredentialHeld


def _brief(brief_id: str) -> DirectorBrief:
    return DirectorBrief(brief_id=brief_id, title=f"Do {brief_id}",
                         mission="Make it work.", source=BriefSource.MANUAL)


class _SupervisorTestCase(unittest.TestCase):
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

    def _supervisor(self, backoff=None, policy=None) -> WorkerSupervisor:
        # No clock parameter: the supervisor takes the QUEUE's, so the
        # two time bases cannot disagree.
        return WorkerSupervisor(self.queue, backoff=backoff, policy=policy)


class TestPacing(_SupervisorTestCase):
    def test_the_supervisor_cannot_be_given_a_clock_that_disagrees(self):
        # The wiring that silently disabled backoff: a monotonic
        # supervisor clock over a wall-clock queue wrote deadlines the
        # queue always reads as past.
        supervisor = self._supervisor()
        self.assertIs(supervisor.clock, self.queue.clock)
        with self.assertRaises(TypeError):
            WorkerSupervisor(self.queue, clock=lambda: 0.0)

    def test_a_parked_brief_is_not_offered_again_immediately(self):
        # `drain` re-offered instantly; max_attempts stopped the loop and
        # nothing paced it.
        self.queue.enqueue(_brief("BRIEF-1"))
        supervisor = self._supervisor(BackoffPolicy(base_s=60.0))

        report = supervisor.run("worker-a", lambda work: Disposition.PARK)

        self.assertEqual(report.parked, ("BRIEF-1",))
        # ALL_WAITING, not QUEUE_EMPTY: the queue is not empty, everything
        # in it is paced. Reporting both as "empty" made a fully
        # backed-off queue read as an idle one, and an operator acts on
        # those differently (independent review).
        self.assertEqual(report.stopped_because, StopReason.ALL_WAITING)
        self.assertEqual([b for b, _ in report.waiting], ["BRIEF-1"])
        # Still pending, but not yet claimable.
        self.assertEqual(self.queue.pending_ids(), ["BRIEF-1"])
        self.assertIsNone(self.queue.claim("worker-b"))

        self.now[0] += 61
        self.assertIsNotNone(self.queue.claim("worker-b"))

    def test_backoff_survives_a_restart(self):
        # Pacing held in a worker's memory is pacing a crash forgets — and
        # what it paces is launches against a shut window, which is
        # exactly what must not resume at full speed (L-0024's shape).
        self.queue.enqueue(_brief("BRIEF-1"))
        self._supervisor(BackoffPolicy(base_s=120.0)).run(
            "worker-a", lambda work: Disposition.PARK)

        # A brand new queue object, as after a process restart.
        restarted = WorkQueue(self.root / "queue", self.authority,
                              clock=lambda: self.now[0])
        self.assertIsNone(restarted.claim("worker-b"))
        self.now[0] += 121
        self.assertIsNotNone(restarted.claim("worker-b"))

    def test_backoff_grows_with_the_briefs_own_attempts(self):
        policy = BackoffPolicy(base_s=10.0, factor=3.0, max_s=1000.0)
        self.assertEqual(policy.delay_for(1), 10.0)
        self.assertEqual(policy.delay_for(2), 30.0)
        self.assertEqual(policy.delay_for(3), 90.0)

    def test_backoff_is_capped(self):
        policy = BackoffPolicy(base_s=10.0, factor=10.0, max_s=45.0)
        self.assertEqual(policy.delay_for(9), 45.0)

    def test_a_shrinking_backoff_is_refused(self):
        # It would pace nothing while reading as pacing.
        with self.assertRaises(ValueError):
            BackoffPolicy(factor=0.5)
        with self.assertRaises(ValueError):
            BackoffPolicy(base_s=0)
        with self.assertRaises(TypeError):
            BackoffPolicy(base_s=True)


class TestCircuitBreakers(_SupervisorTestCase):
    def test_it_stops_when_the_queue_empties(self):
        for i in range(3):
            self.queue.enqueue(_brief(f"BRIEF-{i}"))
        report = self._supervisor().run("worker-a", lambda w: Disposition.COMPLETED)
        self.assertEqual(report.stopped_because, StopReason.QUEUE_EMPTY)
        self.assertEqual(len(report.completed), 3)

    def test_it_stops_after_max_briefs(self):
        for i in range(10):
            self.queue.enqueue(_brief(f"BRIEF-{i:02d}"))
        report = self._supervisor(policy=SupervisorPolicy(max_briefs=4)).run(
            "worker-a", lambda w: Disposition.COMPLETED)
        self.assertEqual(report.stopped_because, StopReason.MAX_BRIEFS)
        self.assertEqual(report.handled, 4)
        self.assertEqual(len(self.queue.pending_ids()), 6)

    def test_it_stops_on_wall_clock(self):
        for i in range(10):
            self.queue.enqueue(_brief(f"BRIEF-{i:02d}"))

        def slow(work):
            self.now[0] += 30
            return Disposition.COMPLETED

        report = self._supervisor(policy=SupervisorPolicy(wall_clock_s=60)).run(
            "worker-a", slow)
        self.assertEqual(report.stopped_because, StopReason.WALL_CLOCK)
        self.assertLess(report.handled, 10)

    def test_it_stops_when_nothing_is_completing(self):
        # A queue where every brief parks is a system waiting on something
        # external; spinning through it re-learns the same answer.
        for i in range(10):
            self.queue.enqueue(_brief(f"BRIEF-{i:02d}"))
        report = self._supervisor(
            backoff=BackoffPolicy(base_s=0.001),
            policy=SupervisorPolicy(max_consecutive_parks=3),
        ).run("worker-a", lambda w: Disposition.PARK)
        self.assertEqual(report.stopped_because, StopReason.CONSECUTIVE_PARKS)
        self.assertEqual(len(report.parked), 3)

    def test_a_completion_resets_the_park_streak(self):
        for i in range(6):
            self.queue.enqueue(_brief(f"BRIEF-{i:02d}"))
        seen: list[str] = []

        def alternate(work):
            seen.append(work.brief_id)
            return Disposition.PARK if len(seen) % 2 else Disposition.COMPLETED

        report = self._supervisor(
            backoff=BackoffPolicy(base_s=0.001),
            policy=SupervisorPolicy(max_consecutive_parks=2),
        ).run("worker-a", alternate)
        # It got past the streak limit because completions kept resetting it.
        self.assertGreater(report.handled, 2)


class TestWhatASupervisorMayNotDecide(_SupervisorTestCase):
    """The line: doing LESS is the supervisor's; deciding that work whose
    outcome nobody recorded should run again is not."""

    def test_a_handler_that_raises_blocks_the_brief_rather_than_retrying(self):
        # The outcome is unknown. Retrying would be the supervisor
        # deciding that unknown work should run again.
        self.queue.enqueue(_brief("BRIEF-1"))

        def explode(work):
            raise RuntimeError("nobody enumerated this")

        report = self._supervisor().run("worker-a", explode)

        self.assertEqual(report.stopped_because, StopReason.HANDLER_RAISED)
        self.assertEqual(report.blocked, ("BRIEF-1",))
        self.assertEqual(self.queue.blocked_ids(), ["BRIEF-1"])
        self.assertEqual(self.queue.pending_ids(), [])
        self.assertIn("RuntimeError", report.errors[0][1])

    def test_a_shut_window_parks_the_brief_it_does_not_send_it_to_a_human(self):
        # Rules 6 and 7. The bare `except Exception` blocked ANY raise,
        # so a rate limit — the thing the whole hold plane exists to
        # treat as a park — ended as a brief awaiting an operator.
        self.queue.enqueue(_brief("BRIEF-1"))

        def held(work):
            raise CredentialHeld("window is shut")

        report = self._supervisor(BackoffPolicy(base_s=30.0)).run("worker-a", held)

        self.assertEqual(report.blocked, ())
        self.assertEqual(report.parked, ("BRIEF-1",))
        self.assertEqual(self.queue.blocked_ids(), [])
        self.assertEqual(self.queue.pending_ids(), ["BRIEF-1"])
        self.assertIsNone(self.queue.claim("worker-b"), "the park was not paced")

    def test_an_exhausted_budget_parks_too(self):
        self.queue.enqueue(_brief("BRIEF-1"))

        def spent(work):
            raise BudgetExhausted("max_agent_launches", 3, 3)

        report = self._supervisor(BackoffPolicy(base_s=30.0)).run("worker-a", spent)
        self.assertEqual(report.parked, ("BRIEF-1",))
        self.assertEqual(self.queue.blocked_ids(), [])

    def test_a_raising_handler_never_leaves_the_brief_claimed(self):
        # The stranding ADR-0019's review found, arriving through a
        # different door.
        self.queue.enqueue(_brief("BRIEF-1"))
        self._supervisor().run("worker-a", lambda w: 1 / 0)
        self.assertEqual(self.queue.running_ids(), [])

    def test_a_handler_that_returns_nonsense_is_an_invalid_output_not_a_park(self):
        # A bare `return` is the commonest handler bug. Treated as a park
        # it becomes an indefinite pacing loop that reads as a system
        # waiting on an external window — rule 8 wants it bounded.
        self.queue.enqueue(_brief("BRIEF-1"))
        report = self._supervisor().run("worker-a", lambda w: None)

        self.assertEqual(report.stopped_because, StopReason.INVALID_OUTPUT)
        self.assertEqual(self.queue.blocked_ids(), ["BRIEF-1"])
        self.assertEqual(report.parked, ())
        self.assertIn("not a Disposition", report.errors[0][1])

    def test_a_string_that_merely_looks_like_a_disposition_is_refused(self):
        # `Disposition` is a str enum, so "PARK" compares equal to it —
        # an identity check would pass where the type check must not.
        self.queue.enqueue(_brief("BRIEF-1"))
        report = self._supervisor().run("worker-a", lambda w: "PARK")
        self.assertEqual(report.stopped_because, StopReason.INVALID_OUTPUT)

    def test_a_blocked_brief_is_not_resurrected_by_any_worker(self):
        self.queue.enqueue(_brief("BRIEF-1"))
        self._supervisor().run("worker-a", lambda w: Disposition.BLOCK)
        self.assertEqual(self.queue.blocked_ids(), ["BRIEF-1"])

        # A second supervisor, a second worker, a fresh run: still blocked.
        report = self._supervisor().run("worker-b", lambda w: Disposition.COMPLETED)
        self.assertEqual(report.handled, 0)
        self.assertEqual(self.queue.blocked_ids(), ["BRIEF-1"])

    def test_only_an_operator_clears_the_attempt_count(self):
        # A bound an automated path could clear is not a bound.
        self.queue.enqueue(_brief("BRIEF-1"))
        supervisor = self._supervisor(backoff=BackoffPolicy(base_s=0.001))
        for _ in range(6):
            supervisor.run("worker-a", lambda w: Disposition.PARK)
            self.now[0] += 1

        self.assertEqual(self.queue.blocked_ids(), ["BRIEF-1"])
        # The supervisor has no method that would undo this.
        self.assertFalse(hasattr(supervisor, "requeue"))
        self.assertTrue(self.queue.requeue("BRIEF-1", reason="operator looked"))
        self.assertEqual(self.queue.pending_ids(), ["BRIEF-1"])

    def test_recovery_runs_before_claiming_not_as_a_separate_ritual(self):
        # A previous worker's stranded record comes back when a worker
        # starts, the same moment ADR-0016's boot sweep runs.
        self.queue.enqueue(_brief("BRIEF-1"))
        work = self.queue.claim("worker-that-dies")
        self.authority.release(work.grant)          # crash after the release
        self.assertEqual(self.queue.running_ids(), ["BRIEF-1"])

        report = self._supervisor().run("worker-b", lambda w: Disposition.COMPLETED)
        self.assertEqual(report.completed, ("BRIEF-1",))


if __name__ == "__main__":
    unittest.main()
