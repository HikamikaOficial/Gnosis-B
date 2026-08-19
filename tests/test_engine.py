import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gnosis.kernel.code_intelligence import (
    CodeIntelligenceProvider,
    CodeIntelligenceUnavailable,
    CompactContext,
    ImpactResult,
    IndexStatus,
    SymbolLocation,
)
from gnosis.kernel.engine import TaskEngine
from gnosis.runner.claude_cli_runner import McpRunnerConfig
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.state_machine import RunState, TaskState
from gnosis.kernel.verification import CommandVerifier
from gnosis.runner.capture import ExecutionResult
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
