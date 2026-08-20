import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from gnosis.kernel.claims import ClaimStatus, ClaimStore, StaleClaimError, WorkAuthority
from gnosis.kernel.code_intelligence import (
    CodeIntelligenceProvider,
    CodeIntelligenceUnavailable,
    CompactContext,
    IndexStatus,
)
from gnosis.kernel.engine import TaskEngine
from gnosis.kernel.lease import LeaseStore, StaleLeaseError
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.state_machine import RunState, TaskState
from gnosis.kernel.verification import CommandVerifier, VerificationResult, Verifier
from gnosis.runner.capture import ExecutionResult
from gnosis.runner.claude_cli_runner import McpRunnerConfig
from gnosis.runner.retry import RetryPolicy

_FAST_RETRY = RetryPolicy(max_attempts=3, backoff_base_s=0.01, backoff_factor=2.0, max_backoff_s=0.02)


class _FakeCliRunner:
    """Duck-types ClaudeCodeCLIRunner.run() without shelling out to claude,
    keeping the engine integration test hermetic and free."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0
        self.prompts_seen = []

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        self.calls += 1
        self.prompts_seen.append(prompt)
        outcome = self._outcomes[min(self.calls, len(self._outcomes)) - 1]
        stdout_path.write_text('{"ok": true}' if outcome == "succeed" else "", encoding="utf-8")
        stderr_path.write_text("" if outcome == "succeed" else "simulated failure", encoding="utf-8")
        return ExecutionResult(
            command=("fake-claude",), exit_code=0 if outcome == "succeed" else 1,
            timed_out=False, cancelled=False, duration_s=0.01,
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            started_at="t0", ended_at="t1",
        )


class TestTaskEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        self.store = RunStore(self.root / "runs")

    def tearDown(self):
        self.tmp.cleanup()

    def test_success_path_completes_task(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-1", objective="Demo", prompt="do it", repo_path=self.repo,
        )
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        self.assertEqual(len(outcome.run_ids), 1)
        self.assertEqual(outcome.report.status.value, "COMPLETED")

    def test_retries_then_succeeds(self):
        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["fail", "fail", "succeed"]),
            retry_policy=_FAST_RETRY,
        )
        outcome = engine.execute_task(
            task_id="TASK-2", objective="Demo", prompt="do it", repo_path=self.repo,
        )
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        self.assertEqual(len(outcome.run_ids), 3)

    def test_exhausts_retries_and_fails(self):
        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["fail", "fail", "fail"]),
            retry_policy=_FAST_RETRY,
        )
        outcome = engine.execute_task(
            task_id="TASK-3", objective="Demo", prompt="do it", repo_path=self.repo,
        )
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertEqual(len(outcome.run_ids), 3)

    def test_verifier_failure_fails_task_even_if_cli_succeeds(self):
        failing_verifier = CommandVerifier("always-fail", [sys.executable, "-c", "import sys; sys.exit(1)"])
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-4", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=failing_verifier,
        )
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertFalse(outcome.verification.passed)

    def test_mcp_config_forwarded_and_audited_in_ledger(self):
        cfg = McpRunnerConfig(config_paths=("tool.json",))
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-MCP", objective="Demo", prompt="do it", repo_path=self.repo, mcp=cfg,
        )
        events = self.store.ledger_for(outcome.run_ids[-1]).read_all()
        started = next(e for e in events if e.event_type == "run.attempt_started")
        self.assertEqual(started.data["mcp"], {"config_paths": ["tool.json"], "strict": False})

    def test_no_mcp_config_audited_as_none(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-NOMCP", objective="Demo", prompt="do it", repo_path=self.repo,
        )
        events = self.store.ledger_for(outcome.run_ids[-1]).read_all()
        started = next(e for e in events if e.event_type == "run.attempt_started")
        self.assertIsNone(started.data["mcp"])

    def test_git_evidence_captured_per_run(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-5", objective="Demo", prompt="do it", repo_path=self.repo,
        )
        git_dir = self.store.paths_for(outcome.run_ids[-1]).git_dir
        self.assertTrue((git_dir / "pre.json").exists())
        self.assertTrue((git_dir / "post.json").exists())


class _FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _CancellationAwareRunner(_FakeCliRunner):
    """Simulates a long CLI run that honors cooperative cancellation, so
    the pump->token->child chain is actually exercised. Signals `started`
    so tests can schedule a deposition strictly inside the CLI window."""

    def __init__(self, started):
        super().__init__(["succeed"])
        self.observed_cancel = False
        self._started = started

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        self._started.set()
        token = kwargs.get("cancellation_token")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if token is not None and token.is_cancelled():
                self.observed_cancel = True
                break
            time.sleep(0.02)
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("cancelled" if self.observed_cancel else "timeout", encoding="utf-8")
        return ExecutionResult(
            command=("fake-claude",), exit_code=1, timed_out=False,
            cancelled=self.observed_cancel, duration_s=0.1,
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            started_at="t0", ended_at="t1",
        )


class _SlowClockVerifier(Verifier):
    """A verifier whose (fake-clock) duration exceeds the lease TTL,
    advanced in steps with real sleeps in between so the heartbeat pump
    gets the chance a real deployment's wall clock would give it."""

    name = "slow-clock"

    def __init__(self, clock, steps, step_s, sleep_s):
        self._clock = clock
        self._steps = steps
        self._step_s = step_s
        self._sleep_s = sleep_s

    def run(self, cwd):
        for _ in range(self._steps):
            self._clock.advance(self._step_s)
            time.sleep(self._sleep_s)
        return VerificationResult(
            name=self.name, passed=True, exit_code=0, duration_s=0.5,
            stdout_excerpt="", stderr_excerpt="",
        )


class _SignalOnFirstAttemptRunner(_FakeCliRunner):
    """Sets an event when attempt 1 finishes, so a test can schedule a
    deposition deterministically inside the retry backoff window."""

    def __init__(self, outcomes, attempt1_done):
        super().__init__(outcomes)
        self._attempt1_done = attempt1_done

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        result = super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs)
        if self.calls == 1:
            self._attempt1_done.set()
        return result


class _DeposingCliRunner(_FakeCliRunner):
    """Succeeds, but simulates a deposition during the CLI window: the
    lease TTL elapses, the sweep reclaims the claim, and another worker
    takes the task over — all while this 'CLI run' is still executing."""

    def __init__(self, authority, clock, ttl_s):
        super().__init__(["succeed"])
        self.authority = authority
        self.clock = clock
        self.ttl_s = ttl_s

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        self.clock.advance(self.ttl_s + 1)
        self.authority.sweep()
        self.authority.acquire("TASK-AUTH", "worker-b")
        return super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs)


class TestTaskEngineWorkAuthority(unittest.TestCase):
    """Directive 4 part two: the engine's durable write paths are fenced
    by the two-plane WorkAuthority (ADR-0006)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        self.store = RunStore(self.root / "runs")
        self.clock = _FakeClock()
        self.claims = ClaimStore(self.root / "claims.json", clock=self.clock)
        self.leases = LeaseStore(self.root / "leases.json", clock=self.clock)
        self.authority = WorkAuthority(
            self.claims, self.leases, default_ttl_s=60,
            reclaim_grace_s=30, clock=self.clock,
        )

    def _depose_via_rival(self):
        """Expire worker-a's lease, sweep, and hand the task to worker-b."""
        self.clock.advance(61)
        self.authority.sweep()
        self.authority.acquire("TASK-AUTH", "worker-b")

    def tearDown(self):
        self.tmp.cleanup()

    def test_completed_task_resolves_claim_and_releases_lease(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-AUTH", objective="Demo", prompt="do it", repo_path=self.repo,
            authority=self.authority, worker_id="worker-a",
        )
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        claim = self.claims.get("TASK-AUTH")
        self.assertEqual(claim.status, ClaimStatus.RESOLVED)
        self.assertEqual(claim.outcome, "COMPLETED")
        self.assertIsNone(self.leases.current("task/TASK-AUTH"))

    def test_worker_id_required_with_authority(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        with self.assertRaises(ValueError):
            engine.execute_task(
                task_id="TASK-AUTH", objective="Demo", prompt="do it",
                repo_path=self.repo, authority=self.authority,
            )

    def test_deposed_worker_aborts_without_writing_final_state(self):
        runner = _DeposingCliRunner(self.authority, self.clock, ttl_s=60)
        engine = TaskEngine(run_store=self.store, cli_runner=runner)
        with self.assertRaises((StaleLeaseError, StaleClaimError)):
            engine.execute_task(
                task_id="TASK-AUTH", objective="Demo", prompt="do it",
                repo_path=self.repo, authority=self.authority, worker_id="worker-a",
            )
        # NO STALE WRITE: the deposed attempt never recorded its outcome —
        # the run's durable state still says RUNNING and the ledger stops
        # at attempt_started.
        run_ids = self.store.list_run_ids()
        self.assertEqual(len(run_ids), 1)
        self.assertEqual(self.store.read_meta(run_ids[0]).state, "RUNNING")
        events = self.store.ledger_for(run_ids[0]).read_all()
        self.assertEqual(events[-1].event_type, "run.attempt_started")
        # The task now belongs to worker-b at a strictly greater epoch.
        claim = self.claims.get("TASK-AUTH")
        self.assertEqual(claim.holder, "worker-b")
        self.assertEqual(claim.status, ClaimStatus.ACTIVE)

    def test_pump_detects_mid_run_deposition_and_cancels_child(self):
        # Pins the whole heartbeat-pump chain (adversarial-review finding:
        # previously untested): rival takeover mid-run -> pump renewal
        # fails -> child cancelled cooperatively -> typed abort with no
        # final state written.
        started = threading.Event()
        runner = _CancellationAwareRunner(started)
        engine = TaskEngine(run_store=self.store, cli_runner=runner)

        def depose_inside_cli_window():
            started.wait(timeout=10)
            self._depose_via_rival()

        deposer = threading.Thread(target=depose_inside_cli_window)
        deposer.start()
        try:
            with self.assertRaises((StaleLeaseError, StaleClaimError)):
                engine.execute_task(
                    task_id="TASK-AUTH", objective="Demo", prompt="do it",
                    repo_path=self.repo, authority=self.authority,
                    worker_id="worker-a", lease_heartbeat_interval_s=0.05,
                )
        finally:
            deposer.join()
        self.assertTrue(runner.observed_cancel)  # child was not leaked
        run_ids = self.store.list_run_ids()
        self.assertEqual(len(run_ids), 1)
        self.assertEqual(self.store.read_meta(run_ids[0]).state, "RUNNING")

    def test_attempt_entry_guard_blocks_deposed_retry(self):
        # Pins the attempt-entry guard specifically (adversarial-review
        # finding: only the post-run guard was load-bearing): deposition
        # lands during the retry backoff, so attempt 2 must be refused
        # BEFORE it creates a second run.
        attempt1_done = threading.Event()
        engine = TaskEngine(
            run_store=self.store,
            cli_runner=_SignalOnFirstAttemptRunner(["fail", "succeed"], attempt1_done),
            retry_policy=RetryPolicy(max_attempts=2, backoff_base_s=0.8,
                                     backoff_factor=1.0, max_backoff_s=0.8),
        )

        def depose_during_backoff():
            attempt1_done.wait(timeout=10)
            time.sleep(0.2)  # attempt 1's post-run guard has passed by now
            self._depose_via_rival()

        deposer = threading.Thread(target=depose_during_backoff)
        deposer.start()
        try:
            with self.assertRaises((StaleLeaseError, StaleClaimError)):
                engine.execute_task(
                    task_id="TASK-AUTH", objective="Demo", prompt="do it",
                    repo_path=self.repo, authority=self.authority,
                    worker_id="worker-a", lease_heartbeat_interval_s=0.05,
                )
        finally:
            deposer.join()
        # Attempt 1 ran; the deposed worker never opened a second run.
        self.assertEqual(len(self.store.list_run_ids()), 1)

    def test_slow_verifier_survives_via_pump(self):
        # Adversarial-review major finding on the first version: a verifier
        # outliving the lease TTL self-deposed a healthy worker after
        # verified success. The pump must keep the lease alive through
        # verification so resolve() lands.
        verifier = _SlowClockVerifier(self.clock, steps=12, step_s=15, sleep_s=0.1)
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-AUTH", objective="Demo", prompt="do it",
            repo_path=self.repo, verifier=verifier,
            authority=self.authority, worker_id="worker-a",
            lease_ttl_s=120, lease_heartbeat_interval_s=0.05,
        )
        # 180 fake-seconds elapsed against a 120s TTL (which renewals must
        # honor — the grant's own TTL, not the 60s facade default), and the
        # task still completed and resolved: no self-deposition.
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        self.assertEqual(self.claims.get("TASK-AUTH").status, ClaimStatus.RESOLVED)

    def test_failed_task_keeps_claim_active_until_swept(self):
        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["fail"]),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        outcome = engine.execute_task(
            task_id="TASK-AUTH", objective="Demo", prompt="do it", repo_path=self.repo,
            authority=self.authority, worker_id="worker-a",
        )
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        # Failure does not silently release ownership (grit's lesson):
        claim = self.claims.get("TASK-AUTH")
        self.assertEqual(claim.status, ClaimStatus.ACTIVE)
        # ...the lease expires instead, and the sweep reclaims audibly.
        self.clock.advance(61)
        reclaimed = self.authority.sweep()
        self.assertEqual([c.task_id for c in reclaimed], ["TASK-AUTH"])
        self.assertEqual(self.claims.get("TASK-AUTH").status, ClaimStatus.RECLAIMED)


class _FakeCodeIntelligenceProvider(CodeIntelligenceProvider):
    """Deterministic test double -- never shells out to a real tool, so
    TaskEngine's code-intelligence integration is testable without the
    M2.1 lab install present."""

    def __init__(self, available=True, stale=False, fail_symbols=()):
        self.available = available
        self.stale = stale
        self.fail_symbols = set(fail_symbols)
        self.index_calls = []
        self.explore_calls = []

    def index(self, repo_path, full=False):
        self.index_calls.append((repo_path, full))
        if not self.available:
            raise CodeIntelligenceUnavailable("fake: provider unavailable")

    def status(self):
        if not self.available:
            raise CodeIntelligenceUnavailable("fake: provider unavailable")
        return IndexStatus(available=True, files_indexed=5, nodes=10, edges=8, stale=self.stale)

    def find(self, query):
        raise CodeIntelligenceUnavailable("fake: not implemented")

    def callers(self, symbol):
        raise CodeIntelligenceUnavailable("fake: not implemented")

    def callees(self, symbol):
        raise CodeIntelligenceUnavailable("fake: not implemented")

    def impact(self, symbol):
        raise CodeIntelligenceUnavailable("fake: not implemented")

    def explore(self, query):
        self.explore_calls.append(query)
        if not self.available or query in self.fail_symbols:
            raise CodeIntelligenceUnavailable(f"fake: explore failed for {query}")
        return CompactContext(query=query, text=f"relevant context for {query}", related_symbols=(query,))


class TestTaskEngineCodeIntelligence(unittest.TestCase):
    """M2.5 section 6: provider available, provider unavailable, stale
    index, provider failure without run-state corruption, evidence
    recording, TaskEngine context retrieval."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        self.store = RunStore(self.root / "runs")

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_context_gathered_when_not_configured(self):
        cli = _FakeCliRunner(["succeed"])
        engine = TaskEngine(run_store=self.store, cli_runner=cli)
        outcome = engine.execute_task(
            task_id="TASK-CI-0", objective="Demo", prompt="do it", repo_path=self.repo,
        )
        self.assertEqual(cli.prompts_seen, ["do it"])
        events = self.store.ledger_for(outcome.run_ids[-1]).read_all()
        self.assertFalse(any(e.event_type == "code_intelligence.context_gathered" for e in events))

    def test_provider_available_context_prepended_to_prompt(self):
        cli = _FakeCliRunner(["succeed"])
        provider = _FakeCodeIntelligenceProvider(available=True)
        engine = TaskEngine(run_store=self.store, cli_runner=cli)
        engine.execute_task(
            task_id="TASK-CI-1", objective="Demo", prompt="do it", repo_path=self.repo,
            code_intelligence=provider, focus_symbols=["entrypoint"],
        )
        self.assertEqual(len(cli.prompts_seen), 1)
        self.assertIn("relevant context for entrypoint", cli.prompts_seen[0])
        self.assertIn("do it", cli.prompts_seen[0])
        self.assertEqual(provider.explore_calls, ["entrypoint"])

    def test_evidence_recorded_in_ledger_and_run_dir(self):
        cli = _FakeCliRunner(["succeed"])
        provider = _FakeCodeIntelligenceProvider(available=True)
        engine = TaskEngine(run_store=self.store, cli_runner=cli)
        outcome = engine.execute_task(
            task_id="TASK-CI-2", objective="Demo", prompt="do it", repo_path=self.repo,
            code_intelligence=provider, focus_symbols=["entrypoint", "helper"],
        )
        run_id = outcome.run_ids[-1]
        events = self.store.ledger_for(run_id).read_all()
        gathered = next(e for e in events if e.event_type == "code_intelligence.context_gathered")
        self.assertEqual(gathered.data["provider"], "_FakeCodeIntelligenceProvider")
        symbols_queried = {q["symbol"] for q in gathered.data["queries"] if q.get("op") == "explore"}
        self.assertEqual(symbols_queried, {"entrypoint", "helper"})

        evidence_path = self.store.paths_for(run_id).root / "code_intelligence.json"
        self.assertTrue(evidence_path.exists())

        started = next(e for e in events if e.event_type == "run.attempt_started")
        self.assertTrue(started.data["code_intelligence_used"])

    def test_provider_unavailable_does_not_block_or_corrupt_run(self):
        cli = _FakeCliRunner(["succeed"])
        provider = _FakeCodeIntelligenceProvider(available=False)
        engine = TaskEngine(run_store=self.store, cli_runner=cli)
        outcome = engine.execute_task(
            task_id="TASK-CI-3", objective="Demo", prompt="do it", repo_path=self.repo,
            code_intelligence=provider, focus_symbols=["entrypoint"],
        )
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        self.assertEqual(cli.prompts_seen, ["do it"])  # no context to prepend, provider was down
        run_id = outcome.run_ids[-1]
        self.assertEqual(self.store.read_meta(run_id).state, RunState.SUCCEEDED.value)
        events = self.store.ledger_for(run_id).read_all()
        gathered = next(e for e in events if e.event_type == "code_intelligence.context_gathered")
        self.assertFalse(gathered.data["queries"][-1]["success"])

    def test_partial_symbol_failure_still_includes_successful_ones(self):
        cli = _FakeCliRunner(["succeed"])
        provider = _FakeCodeIntelligenceProvider(available=True, fail_symbols={"broken_symbol"})
        engine = TaskEngine(run_store=self.store, cli_runner=cli)
        engine.execute_task(
            task_id="TASK-CI-4", objective="Demo", prompt="do it", repo_path=self.repo,
            code_intelligence=provider, focus_symbols=["entrypoint", "broken_symbol"],
        )
        self.assertIn("relevant context for entrypoint", cli.prompts_seen[0])
        self.assertNotIn("relevant context for broken_symbol", cli.prompts_seen[0])

    def test_stale_index_note_included_in_context(self):
        cli = _FakeCliRunner(["succeed"])
        provider = _FakeCodeIntelligenceProvider(available=True, stale=True)
        engine = TaskEngine(run_store=self.store, cli_runner=cli)
        engine.execute_task(
            task_id="TASK-CI-5", objective="Demo", prompt="do it", repo_path=self.repo,
            code_intelligence=provider, focus_symbols=["entrypoint"],
        )
        self.assertIn("may be stale", cli.prompts_seen[0])

    def test_context_gathered_once_not_duplicated_across_retries(self):
        cli = _FakeCliRunner(["fail", "fail", "succeed"])
        provider = _FakeCodeIntelligenceProvider(available=True)
        engine = TaskEngine(
            run_store=self.store, cli_runner=cli, retry_policy=_FAST_RETRY,
        )
        outcome = engine.execute_task(
            task_id="TASK-CI-6", objective="Demo", prompt="do it", repo_path=self.repo,
            code_intelligence=provider, focus_symbols=["entrypoint"],
        )
        self.assertEqual(len(outcome.run_ids), 3)
        self.assertEqual(provider.explore_calls, ["entrypoint"])  # gathered once, not per retry
        first_run_events = self.store.ledger_for(outcome.run_ids[0]).read_all()
        self.assertTrue(any(e.event_type == "code_intelligence.context_gathered" for e in first_run_events))
        for run_id in outcome.run_ids[1:]:
            later_events = self.store.ledger_for(run_id).read_all()
            self.assertFalse(any(e.event_type == "code_intelligence.context_gathered" for e in later_events))

    def test_max_context_chars_bounds_included_text(self):
        cli = _FakeCliRunner(["succeed"])
        provider = _FakeCodeIntelligenceProvider(available=True)
        engine = TaskEngine(run_store=self.store, cli_runner=cli)
        outcome = engine.execute_task(
            task_id="TASK-CI-7", objective="Demo", prompt="do it", repo_path=self.repo,
            code_intelligence=provider, focus_symbols=["entrypoint"], max_context_chars=5,
        )
        run_id = outcome.run_ids[-1]
        events = self.store.ledger_for(run_id).read_all()
        gathered = next(e for e in events if e.event_type == "code_intelligence.context_gathered")
        self.assertLessEqual(gathered.data["context_included_chars"], 5)


if __name__ == "__main__":
    unittest.main()
