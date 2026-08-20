"""Adapter milestone 4/4: the hold/park plane under a real scheduler.

ADR-0012 built holds, reconcile and boot_sweep and said plainly that
nothing called them. These tests are about the calling: a held credential
actually stops a launch, a parked run actually leaves a durable record,
and a restart actually sees it.
"""
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from gnosis.kernel.engine import TaskEngine
from gnosis.kernel.failures import (
    Disposition,
    EvidenceGrade,
    FailureClass,
    FailureClassification,
    HoldScope,
    RateLimitHold,
)
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.scheduler import (
    PARK_REASON,
    HoldStore,
    TaskScheduler,
    holds_summary,
)
from gnosis.kernel.state_machine import RunState
from gnosis.runner.capture import ExecutionResult
from gnosis.runner.retry import RetryPolicy

_FAST_RETRY = RetryPolicy(max_attempts=1, backoff_base_s=0.01, backoff_factor=2.0, max_backoff_s=0.02)


class _Runner:
    def __init__(self, stderr=b"", exit_code=0, structured=None):
        self.stderr, self.exit_code, self.structured = stderr, exit_code, structured
        self.calls = 0

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        self.calls += 1
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text('{"ok": true}' if self.exit_code == 0 else "", encoding="utf-8")
        stderr_path.write_bytes(self.stderr)
        return ExecutionResult(
            command=("claude",), exit_code=self.exit_code, timed_out=False,
            cancelled=False, duration_s=0.1, stdout_path=str(stdout_path),
            stderr_path=str(stderr_path), started_at="t0", ended_at="t1",
            parsed_json=self.structured,
        )


class _SchedulerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        self.run_store = RunStore(self.root / "runs")
        self.holds = HoldStore(self.root / "holds.jsonl")
        self.now = 1_000_000.0

    def tearDown(self):
        self.tmp.cleanup()

    def _scheduler(self, runner=None, credential="claude://default", **kwargs):
        engine = TaskEngine(
            run_store=self.run_store, cli_runner=runner or _Runner(),
            retry_policy=_FAST_RETRY,
        )
        return TaskScheduler(
            engine=engine, run_store=self.run_store, holds=self.holds,
            credential=credential, clock=lambda: self.now, **kwargs,
        )

    def _submit(self, scheduler, task_id="TASK-1", **kwargs):
        return scheduler.submit(
            task_id=task_id, objective="Demo", prompt="do it",
            repo_path=self.repo, **kwargs,
        )


class TestHoldsGateLaunches(_SchedulerTestCase):
    def test_a_held_credential_parks_the_task_instead_of_running_it(self):
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 600,
            placed_at=self.now,
        ))
        runner = _Runner()
        outcome = self._submit(self._scheduler(runner))

        self.assertEqual(runner.calls, 0)
        self.assertTrue(outcome.parked)
        self.assertEqual(outcome.reason_code, PARK_REASON)
        self.assertIsNotNone(outcome.hold)

    def test_an_open_window_launches_normally(self):
        runner = _Runner()
        outcome = self._submit(self._scheduler(runner))
        self.assertEqual(runner.calls, 1)
        self.assertTrue(outcome.launched)

    def test_an_expired_hold_admits_again(self):
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 60,
            placed_at=self.now,
        ))
        scheduler = self._scheduler()
        self.assertFalse(scheduler.admits())
        self.now += 61
        self.assertTrue(scheduler.admits())

    def test_a_rate_limited_run_places_a_durable_hold(self):
        runner = _Runner(exit_code=1, structured={
            "error": {"type": "rate_limit_error"},
            "rate_limited": True,
            "reset_at": self.now + 300,
        })
        outcome = self._submit(self._scheduler(runner))
        self.assertIsNotNone(outcome.hold)
        self.assertEqual(outcome.hold.credential, "claude://default")
        # Durable, not in-memory: a brand new scheduler sees it.
        fresh = self._scheduler()
        self.assertFalse(fresh.admits())

    def test_an_ordinary_failure_never_holds_the_credential(self):
        # Holding a credential because a test failed would take the whole
        # system down for a bug.
        runner = _Runner(exit_code=1, stderr=b"AssertionError: boom")
        outcome = self._submit(self._scheduler(runner))
        self.assertIsNone(outcome.hold)
        self.assertTrue(self._scheduler().admits())

    def test_reconcile_is_idempotent_across_pumps_and_restarts(self):
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 600,
            placed_at=self.now,
        ))
        scheduler = self._scheduler()
        first = scheduler.live_holds()
        second = scheduler.live_holds()
        self.assertEqual([h.to_dict() for h in first], [h.to_dict() for h in second])
        restarted = self._scheduler().live_holds()
        self.assertEqual([h.to_dict() for h in first], [h.to_dict() for h in restarted])

    def test_the_most_restrictive_competing_hold_wins_regardless_of_order(self):
        for reset in (self.now + 100, self.now + 900, self.now + 300):
            self.holds.place(RateLimitHold(
                credential="claude://default", scope=HoldScope.ACCOUNT,
                reason_code="rate_limited:usage", reset_at=reset, placed_at=self.now,
            ))
        live = self._scheduler().live_holds()
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0].reset_at, self.now + 900)

    def test_a_probe_admits_only_the_named_run(self):
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 600,
            placed_at=self.now,
        ))
        scheduler = self._scheduler(scheduler_id="prober-1")
        scheduler.probe("prober-1")
        self.assertTrue(scheduler.admits(is_resume=True))
        # ...and nobody else, including a plain (non-resume) submission.
        self.assertFalse(scheduler.admits())
        other = self._scheduler(scheduler_id="prober-2")
        self.assertFalse(other.admits(is_resume=True))

    def test_a_window_reopens_only_by_a_recorded_decision(self):
        # The operator topped up the account: the hold is wrong now, and
        # clearing it must be an auditable act, not an edit to a file.
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 9999,
            placed_at=self.now,
        ))
        scheduler = self._scheduler()
        self.assertFalse(scheduler.admits())
        self.holds.supersede("claude://default", self.now, reason="operator:topped-up")
        self.assertTrue(scheduler.admits())
        # The decision itself survives; nothing was erased.
        rows = self.holds.path.read_text(encoding="utf-8")
        self.assertIn("operator:topped-up", rows)
        self.assertIn("rate_limited:usage", rows)

    def test_superseding_one_credential_leaves_the_others_held(self):
        for credential in ("claude://default", "codex://default"):
            self.holds.place(RateLimitHold(
                credential=credential, scope=HoldScope.ACCOUNT,
                reason_code="rate_limited:usage", reset_at=self.now + 600,
                placed_at=self.now,
            ))
        self.holds.supersede("claude://default", self.now, reason="operator:cleared")
        self.assertTrue(self._scheduler().admits())
        other = self._scheduler(credential="codex://default")
        self.assertFalse(other.admits())

    def test_a_damaged_hold_row_does_not_open_every_window(self):
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 600,
            placed_at=self.now,
        ))
        with self.holds.path.open("a", encoding="utf-8") as fh:
            fh.write("{not json\n")
        self.assertFalse(self._scheduler().admits())

    def test_the_clock_is_wall_time_so_durable_windows_actually_expire(self):
        # `reset_at` is an epoch timestamp from the provider. A monotonic
        # reading is neither comparable to it nor meaningful across the
        # restart these rows exist to survive, and mixing them makes every
        # durable hold look permanently unexpired.
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=time.time() - 1,
            placed_at=time.time() - 100,
        ))
        default_clock = TaskScheduler(
            engine=TaskEngine(run_store=self.run_store, cli_runner=_Runner()),
            run_store=self.run_store, holds=self.holds, credential="claude://default",
        )
        self.assertTrue(default_clock.admits())   # the window really has reopened


class TestBootSweep(_SchedulerTestCase):
    def test_a_stranded_run_is_failed_durably_rather_than_left_a_ghost(self):
        self.run_store.create_run("RUN-GHOST", "TASK-1")
        self.run_store.update_state("RUN-GHOST", RunState.RUNNING)

        outcomes = self._scheduler().boot()
        ghost = next(o for o in outcomes if o.run.run_id == "RUN-GHOST")
        self.assertIn(ghost.disposition, (Disposition.FAILED, Disposition.READOPTED))
        if ghost.disposition is Disposition.FAILED:
            self.assertEqual(
                self.run_store.read_meta("RUN-GHOST").state, RunState.CRASHED.value)

    def test_a_finished_run_is_left_alone(self):
        # Re-adopting completed work is worse than the ghost the sweep
        # exists to prevent.
        self.run_store.create_run("RUN-DONE", "TASK-1")
        self.run_store.update_state("RUN-DONE", RunState.RUNNING)
        self.run_store.update_state("RUN-DONE", RunState.SUCCEEDED)

        outcomes = self._scheduler().boot()
        done = next(o for o in outcomes if o.run.run_id == "RUN-DONE")
        self.assertEqual(done.disposition, Disposition.UNTOUCHED)
        self.assertEqual(done.reason_code, "already_terminal")
        self.assertEqual(
            self.run_store.read_meta("RUN-DONE").state, RunState.SUCCEEDED.value)

    def test_every_run_leaves_the_sweep_with_a_disposition(self):
        for run_id, state in (("R1", RunState.RUNNING), ("R2", RunState.PENDING)):
            self.run_store.create_run(run_id, "TASK-1")
            if state is RunState.RUNNING:
                self.run_store.update_state(run_id, state)
        outcomes = self._scheduler().boot()
        self.assertEqual({o.run.run_id for o in outcomes}, {"R1", "R2"})
        self.assertTrue(all(o.reason_code for o in outcomes))

    def test_a_parked_run_is_readopted_rather_than_failed(self):
        self.run_store.create_run("RUN-PARKED", "TASK-1")
        self.run_store.update_state("RUN-PARKED", RunState.RUNNING)

        def classify(run_id):
            return FailureClassification(
                FailureClass.RATE_LIMITED, "rate_limited:usage",
                EvidenceGrade.STRUCTURED, "test",
            )

        outcomes = self._scheduler().boot(classify=classify)
        parked = next(o for o in outcomes if o.run.run_id == "RUN-PARKED")
        self.assertEqual(parked.disposition, Disposition.READOPTED)
        # A park is not an agent failure and must not be written as one.
        self.assertNotEqual(
            self.run_store.read_meta("RUN-PARKED").state, RunState.CRASHED.value)


class TestOperatorView(_SchedulerTestCase):
    def test_an_estimated_window_is_labelled_as_such(self):
        # The kernel's bounded guess must not read like something the
        # provider said.
        summary = holds_summary([
            RateLimitHold(credential="c", scope=HoldScope.ACCOUNT,
                          reason_code="r", reset_at=1.0, window_estimated=True),
            RateLimitHold(credential="d", scope=HoldScope.ACCOUNT,
                          reason_code="r", reset_at=2.0),
        ])
        self.assertEqual([row["window_source"] for row in summary],
                         ["estimated", "provider"])


if __name__ == "__main__":
    unittest.main()
