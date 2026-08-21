"""Adapter milestone 4/4: the hold/park plane under a real scheduler.

ADR-0012 built holds, reconcile and boot_sweep and said plainly that
nothing called them. These tests are about the calling: a held credential
actually stops a launch, a parked run actually leaves a durable record,
and a restart actually sees it.
"""
import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import ClassVar

from gnosis.kernel.credentials import (
    Credential,
    CredentialKind,
    CredentialPool,
)
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
    ProbePolicy,
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


class _EnvRunner(_Runner):
    """Records the environment each launch was actually given."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.environments: list = []

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        self.environments.append(kwargs.get("env"))
        return super().run(prompt, cwd, stdout_path, stderr_path, timeout_s,
                           **{k: v for k, v in kwargs.items() if k != "env"})


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
        # The previous version of this test passed `scheduler_id` and
        # `probe(run_id)` the SAME string, so it could not tell that the
        # code compared the scheduler's identity instead of the run's —
        # meaning any submission from any scheduler with that id was
        # admitted, which is the stampede a probe exists to prevent
        # (Codex review). The identities are deliberately different now.
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 600,
            placed_at=self.now,
        ))
        scheduler = self._scheduler(scheduler_id="scheduler-A")
        scheduler.probe("RUN-PROBE")

        self.assertTrue(scheduler.admits(is_resume=True, probe_run_id="RUN-PROBE"))
        # A DIFFERENT run, from the same scheduler, is not the probe.
        self.assertFalse(scheduler.admits(is_resume=True, probe_run_id="RUN-OTHER"))
        # Nor is an unattributed resume.
        self.assertFalse(scheduler.admits(is_resume=True))
        # Nor is ordinary new work.
        self.assertFalse(scheduler.admits())
        # And another scheduler cannot ride the probe by sharing an id.
        other = self._scheduler(scheduler_id="scheduler-A")
        self.assertFalse(other.admits(is_resume=True))

    def test_a_probe_never_leaves_the_credential_open_between_two_rows(self):
        # supersede-then-place left a window: a crash, or another
        # scheduler's read, between them saw nothing holding the
        # credential (Codex review). Both rows are one append now.
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 600,
            placed_at=self.now,
        ))
        self._scheduler().probe("RUN-PROBE")
        text = self.holds.path.read_text(encoding="utf-8")
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        # ONE row carries the whole transition. Two rows in a single
        # append was not enough: a crash can flush the first line and not
        # the second, leaving a supersede with nothing replacing it.
        self.assertEqual(rows[-1]["row"], "narrow")
        self.assertIn("hold", rows[-1])

        # No prefix of the log — down to a torn byte — admits work.
        for cut in range(1, len(text) + 1):
            self.holds.path.write_text(text[:cut], encoding="utf-8")
            self.assertFalse(self._scheduler().admits(),
                             f"credential admitted work after {cut} durable bytes")

    def test_damaged_rows_deny_rather_than_reading_as_no_holds(self):
        # A truncated sole hold row silently admitted work against a shut
        # credential: skipping the row opens the window it described. A
        # safety mechanism has to fail in the shut direction.
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 600,
            placed_at=self.now,
        ))
        self.holds.path.write_text('{"row": "hold", "credent', encoding="utf-8")
        self.assertFalse(self._scheduler().admits())
        self.assertTrue(self.holds.read().damaged)

    def test_an_underspecified_supersede_row_cannot_reopen_a_window(self):
        # `at` and `reason` were optional, so a half-specified control row
        # still erased every hold on the credential.
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 600,
            placed_at=self.now,
        ))
        with self.holds.path.open("a", encoding="utf-8") as fh:
            fh.write('{"row": "supersede", "credential": "claude://default"}\n')
        self.assertFalse(self._scheduler().admits())

    def test_a_non_finite_window_is_rejected_at_the_recovery_boundary(self):
        # `Infinity` produced a hold that never expires; `NaN` never
        # expired AND made reconcile order-dependent, since every
        # comparison against NaN is false.
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now - 1,
            placed_at=self.now,
        ))
        with self.holds.path.open("a", encoding="utf-8") as fh:
            fh.write('{"row":"hold","credential":"claude://default","scope":"ACCOUNT",'
                     '"reason_code":"r","reset_at":Infinity,"placed_at":0}\n')
        snapshot = self.holds.read()
        self.assertTrue(snapshot.damaged)
        self.assertFalse(self._scheduler().admits())

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

    def test_one_corrupt_heartbeat_does_not_abort_the_whole_sweep(self):
        # `read_heartbeat` json.loads an arbitrary file, and nothing
        # caught it: a single truncated heartbeat aborted the sweep and
        # left every later run with no disposition — the ghost the sweep
        # exists to prevent, caused by the sweep (Codex review).
        for run_id in ("RUN-BAD", "RUN-AFTER"):
            self.run_store.create_run(run_id, "TASK-1")
            self.run_store.update_state(run_id, RunState.RUNNING)
        self.run_store.heartbeat("RUN-BAD")
        self.run_store.paths_for("RUN-BAD").heartbeat.write_text("{not json",
                                                                 encoding="utf-8")

        outcomes = self._scheduler().boot()
        self.assertEqual({o.run.run_id for o in outcomes}, {"RUN-BAD", "RUN-AFTER"})
        self.assertTrue(all(o.reason_code for o in outcomes))

    def test_a_heartbeat_without_a_start_time_is_unknown_not_alive(self):
        # `is_alive` answers "a process with this PID exists", which on a
        # recycled PID is a different process wearing a dead run's
        # identity — and trusting it strands the run forever.
        self.run_store.create_run("RUN-PID", "TASK-1")
        self.run_store.update_state("RUN-PID", RunState.RUNNING)
        self.run_store.paths_for("RUN-PID").heartbeat.write_text(
            json.dumps({"ts": "2026-08-21T00:00:00+00:00", "pid": 1, "start_time": None}),
            encoding="utf-8")

        outcome = next(o for o in self._scheduler().boot() if o.run.run_id == "RUN-PID")
        self.assertIsNone(outcome.run.process_alive)
        self.assertNotEqual(outcome.disposition, Disposition.UNTOUCHED)

    def test_a_heartbeat_from_the_future_is_not_treated_as_fresh(self):
        # Clamping a future timestamp to zero staleness made a dead run
        # look like it had just checked in.
        from datetime import UTC, datetime, timedelta
        self.run_store.create_run("RUN-FUTURE", "TASK-1")
        self.run_store.update_state("RUN-FUTURE", RunState.RUNNING)
        ahead = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        self.run_store.paths_for("RUN-FUTURE").heartbeat.write_text(
            json.dumps({"ts": ahead, "pid": 999999, "start_time": None}), encoding="utf-8")

        outcome = next(o for o in self._scheduler().boot()
                       if o.run.run_id == "RUN-FUTURE")
        self.assertIsNone(outcome.run.heartbeat_stale_s)
        self.assertNotEqual(outcome.disposition, Disposition.UNTOUCHED)

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


class TestTheProbeHasACaller(_SchedulerTestCase):
    """ADR-0016 built `probe()` and nothing invoked it, so the kernel's own
    GUESSED windows still ended in the stampede the probe exists to
    prevent: at the estimated reset the hold simply vanished and every
    queued run was admitted together."""

    def _estimated_hold(self, window_s=900.0):
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:prose", reset_at=self.now + window_s,
            placed_at=self.now, window_estimated=True,
        ))

    def _rate_limiting_runner(self):
        return _Runner(exit_code=1, structured={
            "error": {"type": "rate_limit_error"},
            "rate_limited": True,
        })

    def test_when_the_guess_was_wrong_only_one_run_pays_for_it(self):
        # Five runs are waiting; the kernel's estimate is about to elapse;
        # the window is in fact still shut. One launch discovers that and
        # the other four never leave the queue — and, because the failed
        # probe re-holds the account, the guess is CORRECTED before it
        # would have expired and released everybody.
        #
        # Sequentially this is not yet a stampede prevented: the first
        # launch would have re-held the credential anyway. The stampede is
        # the concurrent case, and `test_racing_claims_produce_exactly_one
        # _probe` is the test that shows it.
        self._estimated_hold()
        self.now += 900 - 30          # inside the probe lead
        runner = self._rate_limiting_runner()
        scheduler = self._scheduler(runner)

        outcomes = [self._submit(scheduler, task_id=f"TASK-{i}") for i in range(5)]

        self.assertEqual(runner.calls, 1, "more than one run tested the window")
        self.assertEqual(sum(1 for o in outcomes if o.launched), 1)
        self.assertEqual(sum(1 for o in outcomes if o.parked), 4)
        # And the failed probe left an ACCOUNT hold, not a probe nobody owns.
        held = self._scheduler().live_holds()
        self.assertEqual(len(held), 1)
        self.assertIs(held[0].scope, HoldScope.ACCOUNT)

    def test_when_the_guess_was_right_the_probe_reopens_it_for_everyone(self):
        # A successful probe is the answer the question was asked for, and
        # nothing used to read it: the narrowing stood until its own
        # deadline while the window was demonstrably open.
        self._estimated_hold()
        self.now += 900 - 30
        runner = _Runner()
        scheduler = self._scheduler(runner)

        outcomes = [self._submit(scheduler, task_id=f"TASK-{i}") for i in range(5)]

        self.assertEqual(sum(1 for o in outcomes if o.launched), 5)
        self.assertEqual(self._scheduler().live_holds(), [])

    def test_a_window_the_provider_supplied_is_never_probed(self):
        # It is not a guess. Spending a launch to contradict it buys
        # nothing, and the launch would be charged to somebody.
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 900,
            placed_at=self.now, window_estimated=False,
        ))
        self.now += 900 - 30
        runner = _Runner()
        scheduler = self._scheduler(runner)
        self.assertIsNone(scheduler.probe_is_due())
        self.assertTrue(self._submit(scheduler).parked)
        self.assertEqual(runner.calls, 0)

    def test_an_unknown_window_becomes_probeable_instead_of_permanent(self):
        # A hold with no window never expires by itself — the "loaded gun"
        # an earlier review named. A probe is the only way out of one.
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:prose", reset_at=None,
            placed_at=self.now, window_estimated=True,
        ))
        scheduler = self._scheduler()
        self.assertIsNone(scheduler.probe_is_due(), "probed the instant it was placed")
        self.now += 901
        self.assertIsNotNone(scheduler.probe_is_due())

    def test_a_probe_never_inherits_the_window_it_replaces(self):
        # Inheriting was wrong both ways: a past `reset_at` expired the
        # probe hold the instant it was written (admitting everyone), and
        # a `None` pinned the credential to a run that may be dead.
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:prose", reset_at=None,
            placed_at=self.now, window_estimated=True,
        ))
        scheduler = self._scheduler(probe_policy=ProbePolicy(ttl_s=120.0))
        placed = scheduler.probe("RUN-PROBE")
        self.assertEqual(placed.reset_at, self.now + 120.0)
        self.assertTrue(scheduler.admits(probe_run_id="RUN-PROBE"))

    def test_an_abandoned_probe_does_not_pin_the_credential_forever(self):
        # The probing run dies without answering. A narrowing that
        # outlives its holder is a lease that cannot expire.
        self._estimated_hold()
        self.now += 900 - 30
        scheduler = self._scheduler(probe_policy=ProbePolicy(ttl_s=120.0))
        self.assertIsNotNone(scheduler.claim_probe("RUN-DEAD"))
        self.assertFalse(scheduler.admits(probe_run_id="RUN-OTHER"))

        self.now += 121
        self.assertTrue(self._scheduler().admits(probe_run_id="RUN-OTHER"))

    def _contested_claim(self, run_id):
        """The claim step alone, as a caller reaches it having ALREADY
        passed the due check — which is the only state where the race is
        real."""
        now = self.now
        return self.holds.narrow_if_unclaimed(
            "claude://default", now, reason=f"probe:{run_id}",
            replacement=RateLimitHold(
                credential="claude://default", scope=HoldScope.PROBE,
                reason_code="rate_limited:prose", placed_at=now,
                reset_at=now + 120.0, probe_holder=run_id, window_estimated=True,
            ),
        )

    def test_a_caller_past_the_due_check_is_still_refused_by_the_claim(self):
        # Deterministic version of the race, at the STORE level: both
        # callers saw the probe due, one appended, and only the
        # compare-and-set can stop the other. Its partner below runs the
        # same contention through `claim_probe`, the entry production
        # actually takes — a guard verified only as a function leaves its
        # production use unverified (independent review).
        self._estimated_hold()
        self.now += 900 - 30
        first, second = self._scheduler(), self._scheduler()
        self.assertIsNotNone(first.probe_is_due())
        self.assertIsNotNone(second.probe_is_due())

        granted = first.claim_probe("RUN-A")
        self.assertIsNotNone(granted)
        self.assertIsNone(self._contested_claim("RUN-B"))

        fresh = self._scheduler()
        self.assertTrue(fresh.admits(probe_run_id=granted.probe_holder))
        self.assertFalse(fresh.admits(probe_run_id="RUN-B"))
        # And the raw name, without the minted secret, is not admission.
        self.assertFalse(fresh.admits(probe_run_id="RUN-A"))

    def test_a_provider_window_arriving_mid_claim_is_not_probed(self):
        # Dueness is re-checked INSIDE the lock. Guarding "nobody else is
        # probing" while leaving "there is still a hold worth probing" a
        # check-then-act let a provider window — which the ADR promises is
        # never probed — be suspended by a claim decided before it landed.
        self._estimated_hold()
        self.now += 900 - 30
        scheduler = self._scheduler()
        self.assertIsNotNone(scheduler.probe_is_due())

        stale_answer = scheduler.probe_is_due()

        # A real provider limit lands before the claim takes the lock.
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 8000,
            placed_at=self.now, window_estimated=False,
        ))
        # The caller is now holding an answer that was true a moment ago.
        # Only the re-check inside the lock can stop it.
        scheduler.probe_is_due = lambda credential=None: stale_answer
        self.assertIsNone(scheduler.claim_probe("RUN-LATE"),
                          "a provider window was suspended by a stale claim")
        live = self._scheduler().live_holds()
        self.assertEqual(len(live), 1)
        self.assertIs(live[0].scope, HoldScope.ACCOUNT)
        self.assertFalse(live[0].window_estimated)

    def test_racing_claims_produce_exactly_one_probe(self):
        # The same contention with real threads on real files. Every
        # thread has passed the due check before the barrier, so they all
        # reach the contested append together.
        self._estimated_hold()
        self.now += 900 - 30
        for index in range(6):
            self.assertIsNotNone(self._scheduler().probe_is_due(), index)

        winners: list = []
        lock = threading.Lock()
        barrier = threading.Barrier(6)

        def claim(index):
            # Through `claim_probe`, the production entry — not the store
            # API underneath it.
            scheduler = self._scheduler()
            barrier.wait()
            got = scheduler.claim_probe(f"RUN-{index}")
            if got is not None:
                with lock:
                    winners.append(got)

        threads = [threading.Thread(target=claim, args=(i,)) for i in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertFalse([t for t in threads if t.is_alive()], "a claim hung")
        self.assertEqual(len(winners), 1, f"{len(winners)} callers all probed")
        fresh = self._scheduler()
        self.assertTrue(fresh.admits(probe_run_id=winners[0].probe_holder))
        self.assertFalse(any(fresh.admits(probe_run_id=f"RUN-{i}") for i in range(6)))

    def test_a_second_probe_is_not_claimed_while_one_is_answering(self):
        self._estimated_hold()
        self.now += 900 - 30
        scheduler = self._scheduler()
        self.assertIsNotNone(scheduler.claim_probe("RUN-FIRST"))
        self.assertIsNone(scheduler.claim_probe("RUN-SECOND"))

    def test_the_probe_holder_is_the_task_not_the_scheduler(self):
        # A shared identity was the original defect: any submission from
        # any scheduler with that id rode the probe.
        self._estimated_hold()
        self.now += 900 - 30
        scheduler = self._scheduler(self._rate_limiting_runner(),
                                    scheduler_id="scheduler-A")
        self._submit(scheduler, task_id="TASK-PROBE")
        rows = [json.loads(line) for line
                in self.holds.path.read_text(encoding="utf-8").splitlines()]
        narrowed = [r for r in rows if r.get("row") == "narrow"]
        self.assertEqual(len(narrowed), 1)
        holder = narrowed[0]["hold"]["probe_holder"]
        # Attributable AND unguessable: the task names it, a secret minted
        # inside the claim makes winning the claim the only way to hold
        # it. A holder equal to the task id is a string any process with
        # the task id can assert, and asserting it IS admission.
        self.assertTrue(holder.startswith("TASK-PROBE:"), holder)
        self.assertGreater(len(holder), len("TASK-PROBE:") + 8)

    def test_probing_can_be_switched_off_without_reopening_the_window(self):
        # Off means MORE conservative, never less: everyone keeps waiting.
        self._estimated_hold()
        self.now += 900 - 30
        runner = _Runner()
        scheduler = self._scheduler(runner, probe_when_due=False)
        self.assertTrue(self._submit(scheduler).parked)
        self.assertEqual(runner.calls, 0)

    def test_a_shrinking_or_absent_probe_policy_is_refused(self):
        for kwargs in ({"lead_s": 0}, {"ttl_s": -1}, {"unknown_window_wait_s": 0}):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                ProbePolicy(**kwargs)
        with self.assertRaises(TypeError):
            ProbePolicy(ttl_s=True)


class TestRotationAtTheEnginesLaunch(_SchedulerTestCase):
    """The implementation launch does not go through `GatedAgentRunner`;
    it goes through `submit` -> `execute_task`. Rotating only the gated
    launches would leave the main one on a single credential while the
    mechanism claimed otherwise."""

    def _pool(self):
        return CredentialPool([
            Credential("seat-a", CredentialKind.SUBSCRIPTION,
                       env_from={"CLAUDE_TOKEN": "SEAT_A_TOKEN"}),
            Credential("seat-b", CredentialKind.SUBSCRIPTION,
                       env_from={"CLAUDE_TOKEN": "SEAT_B_TOKEN"}),
            Credential("metered", CredentialKind.METERED,
                       env_from={"ANTHROPIC_API_KEY": "METERED_TOKEN"}),
        ])

    BASE: ClassVar[dict[str, str]] = {
        "PATH": "/usr/bin", "SEAT_A_TOKEN": "aaa", "SEAT_B_TOKEN": "bbb",
        "METERED_TOKEN": "mmm"}

    def _rotating(self, runner, **kwargs):
        return self._scheduler(runner, credential="seat-a",
                               credentials=self._pool(),
                               base_environment=self.BASE, **kwargs)

    def _hold(self, credential):
        self.holds.place(RateLimitHold(
            credential=credential, scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 900,
            placed_at=self.now,
        ))

    def test_the_implementation_launch_is_bound_to_the_selected_credential(self):
        runner = _EnvRunner()
        self._submit(self._rotating(runner))
        self.assertEqual(runner.environments[0]["CLAUDE_TOKEN"], "aaa")

    def test_a_held_seat_moves_the_implementation_to_the_next_seat(self):
        self._hold("seat-a")
        runner = _EnvRunner()
        outcome = self._submit(self._rotating(runner))
        self.assertTrue(outcome.launched)
        self.assertEqual(runner.environments[0]["CLAUDE_TOKEN"], "bbb")

    def test_every_seat_held_parks_instead_of_billing(self):
        self._hold("seat-a")
        self._hold("seat-b")
        runner = _EnvRunner()
        outcome = self._submit(self._rotating(runner))
        self.assertTrue(outcome.parked)
        self.assertEqual(outcome.reason_code, PARK_REASON)
        self.assertEqual(runner.calls, 0, "it billed a metered key to keep moving")

    def test_the_crossing_happens_only_when_authorised(self):
        self._hold("seat-a")
        self._hold("seat-b")
        runner = _EnvRunner()
        outcome = self._submit(self._rotating(
            runner, authorised_kinds=frozenset({CredentialKind.METERED})))
        self.assertTrue(outcome.launched)
        self.assertEqual(runner.environments[0]["ANTHROPIC_API_KEY"], "mmm")

    def test_without_a_pool_the_launch_inherits_as_it_always_did(self):
        runner = _EnvRunner()
        self._submit(self._scheduler(runner))
        self.assertIsNone(runner.environments[0])


if __name__ == "__main__":
    unittest.main()
