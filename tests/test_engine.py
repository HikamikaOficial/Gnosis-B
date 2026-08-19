import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gnosis.kernel.engine import TaskEngine
from gnosis.runner.claude_cli_runner import McpRunnerConfig
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.state_machine import TaskState
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

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        self.calls += 1
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


if __name__ == "__main__":
    unittest.main()
