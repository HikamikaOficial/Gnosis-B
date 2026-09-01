"""F-33 Stage-2A integration: GovernedPipeline -> TrustedExecutionPort.

These prove the governed pipeline's production-capable IMPLEMENTATION execution
is wired to the OS-real-qualified trusted seam and cannot silently take the old
direct route, while the pipeline's governance semantics (verifier-required,
implementer!=reviewer, DirectorOrchestrator non-canonical) stay intact.

The `_SpyLauncher` faithfully stands in for the deterministic Worker at the
component level: it reads the sealed cassette and echoes its real sha256, so the
H4 digest binding is exercised end to end. The REAL OS boundary is qualified
separately by the F-33 OS-real probe (a fake launcher cannot satisfy that gate).
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gnosis.director import deterministic_worker as dw
from gnosis.director import trusted_runner as tr
from gnosis.director.execution import TrustedExecutionPort
from gnosis.director.pipeline import GovernedPipeline
from gnosis.director.trusted_runner import TrustedExecutionRunner
from gnosis.kernel.convergence import ConvergencePolicy
from gnosis.kernel.engine import AGENT_RUN_INTERVENTION_POINT, TaskEngine
from gnosis.kernel.policy import InterventionPoint, PolicyEngine, RuleOutcome, Verdict
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.scheduler import HoldStore, TaskScheduler
from gnosis.kernel.state_machine import TaskState
from gnosis.kernel.verification import CommandVerifier
from gnosis.kernel.worktree import WorktreeManager
from gnosis.runner.retry import RetryPolicy

FAKE_PYTHON = Path(r"C:\qualified\runtime\python.exe")
_FAST_RETRY = RetryPolicy(max_attempts=1, backoff_base_s=0.01, backoff_factor=2.0,
                          max_backoff_s=0.02)


@dataclass
class _FakeIdentity:
    pid: int = 4321
    observed_sid: str = "S-1-5-21-spy-worker"
    integrity: str = "Medium"
    is_administrator: bool = False
    contained_in_job: bool = True
    launch_spec_digest: str = "0" * 64


class _SpyLaunched:
    def __init__(self, exit_code: int, timed_out: bool) -> None:
        self._exit_code = exit_code
        self._timed_out = timed_out
        self.identity = _FakeIdentity()
        self.closed = False

    def wait(self, timeout_s: float, *, poll_interval_s: float = 0.2,
             is_cancelled: Any = None) -> tuple[int, bool, bool]:
        return self._exit_code, self._timed_out, False

    def close(self) -> None:
        self.closed = True


class _SpyLauncher:
    """Faithful deterministic-Worker stand-in: reads the sealed cassette and
    echoes its real sha256 (so H4 binding passes on the happy path), or emits a
    configured failure for the negative cases."""

    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.launch_count = 0
        self.saw_schema: str | None = None
        self.last_cassette_digest: str | None = None
        self.last_cwd: str | None = None

    def launch(self, spec: Any) -> _SpyLaunched:
        self.launch_count += 1
        self.last_cwd = spec.cwd
        blob = Path(spec.argv[-1]).read_bytes()
        self.saw_schema = json.loads(blob).get("schema")
        digest = hashlib.sha256(blob).hexdigest()
        self.last_cassette_digest = digest
        out = Path(spec.stdout_path)
        if self.mode == "ok":
            out.write_text(json.dumps({
                "schema": dw.RESULT_SCHEMA, "ok": True, "cassette_sha256": digest,
                "turn_count": 1, "final_message": "done", "provider_calls": 0,
            }), encoding="utf-8")
            return _SpyLaunched(0, False)
        if self.mode == "fail":
            out.write_text("", encoding="utf-8")
            return _SpyLaunched(13, False)
        if self.mode == "malformed":
            out.write_text("this is not json", encoding="utf-8")
            return _SpyLaunched(0, False)
        raise AssertionError(f"unknown spy mode {self.mode!r}")


def _permissive() -> PolicyEngine:
    return PolicyEngine([InterventionPoint(
        name=AGENT_RUN_INTERVENTION_POINT,
        declared_tools=frozenset({"claude_cli"}),
        rules=(("rule", lambda s: RuleOutcome(Verdict.ALLOW, "ok:permitted")),),
        requires_intent=True,
    )])


class _ReviewAgent:
    """A distinct review runner object (never the implementer)."""

    @property
    def binary(self) -> str:
        return "claude-review"

    def run(self, prompt: str, cwd: Any, stdout_path: Any, stderr_path: Any,
            timeout_s: float = 1800.0, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("review runner must not be invoked in these tests")


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        run = lambda *a: subprocess.run(["git", *a], cwd=self.repo, check=True,
                                        capture_output=True)
        run("init")
        run("config", "user.email", "e@x.com")
        run("config", "user.name", "T")
        (self.repo / "code.py").write_text("x = 1\n", encoding="utf-8")
        run("add", "-A")
        run("commit", "-m", "init")
        self.run_store = RunStore(self.root / "runs")
        self.ws = self.root / "ws"
        self.ws.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _runner(self, mode: str = "ok") -> tuple[TrustedExecutionRunner, _SpyLauncher]:
        spy = _SpyLauncher(mode)
        port = TrustedExecutionPort(launcher=spy, python_executable=FAKE_PYTHON)
        runner = TrustedExecutionRunner(port, workspace=self.ws)
        return runner, spy

    def _engine(self, runner: TrustedExecutionRunner) -> TaskEngine:
        return TaskEngine(run_store=self.run_store, cli_runner=runner,
                          retry_policy=_FAST_RETRY)

    def _passing_verifier(self) -> CommandVerifier:
        return CommandVerifier("check", [sys.executable, "-c", "raise SystemExit(0)"])


class TestPipelineReachesPort(_Base):
    def test_p1_engine_implementer_execution_reaches_port(self) -> None:
        runner, spy = self._runner("ok")
        engine = self._engine(runner)
        outcome = engine.execute_task(
            task_id="T1", objective="demo", prompt="do the work",
            repo_path=self.repo, verifier=self._passing_verifier())
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        # The governed implementation launch went through the trusted port.
        self.assertEqual(spy.launch_count, 1)
        self.assertEqual(spy.saw_schema, dw.CASSETTE_SCHEMA)

    def test_p2_run_request_preserved_through_seam(self) -> None:
        # cwd (the governed exec root) is carried to the sealed launch, and the
        # request's prompt determines the deterministic cassette (distinct
        # prompts -> distinct sealed cassettes).
        runner, spy = self._runner("ok")
        engine = self._engine(runner)
        engine.execute_task(task_id="T2", objective="demo", prompt="prompt-A",
                            repo_path=self.repo, verifier=self._passing_verifier())
        digest_a = spy.last_cassette_digest
        self.assertEqual(Path(spy.last_cwd), self.repo)
        runner2, spy2 = self._runner("ok")
        self._engine(runner2).execute_task(
            task_id="T3", objective="demo", prompt="prompt-B",
            repo_path=self.repo, verifier=self._passing_verifier())
        self.assertNotEqual(digest_a, spy2.last_cassette_digest)

    def test_p4_port_failure_propagates_as_governed_failure(self) -> None:
        runner, spy = self._runner("fail")
        outcome = self._engine(runner).execute_task(
            task_id="T4", objective="demo", prompt="x", repo_path=self.repo,
            verifier=self._passing_verifier())
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertGreaterEqual(spy.launch_count, 1)

    def test_p5_malformed_worker_result_cannot_complete(self) -> None:
        runner, _spy = self._runner("malformed")
        outcome = self._engine(runner).execute_task(
            task_id="T5", objective="demo", prompt="x", repo_path=self.repo,
            verifier=self._passing_verifier())
        self.assertNotEqual(outcome.final_task_state, TaskState.COMPLETED)


class TestGovernanceSemanticsIntact(_Base):
    def _pipeline(self, *, review_runner: Any, implementer: TrustedExecutionRunner
                  ) -> GovernedPipeline:
        engine = self._engine(implementer)
        scheduler = TaskScheduler(
            engine=engine, run_store=self.run_store,
            holds=HoldStore(self.root / "holds.jsonl"),
            credential="claude://default", clock=lambda: 1_000_000.0)
        return GovernedPipeline(
            director_root=self.root / "director", scheduler=scheduler,
            repo_path=self.repo, verifier=self._passing_verifier(),
            policy=_permissive(), review_runner=review_runner,
            worktrees=WorktreeManager(self.repo, self.root / "worktrees"),
            convergence_policy=ConvergencePolicy(max_rounds=2),
            policy_actor="agent://worker-a")

    def test_p6_verifier_required_through_trusted_seam(self) -> None:
        runner, _ = self._runner("ok")
        engine = self._engine(runner)
        with self.assertRaises(ValueError):
            engine.execute_task(task_id="T6", objective="demo", prompt="x",
                                repo_path=self.repo, verifier=None)  # type: ignore[arg-type]

    def test_p7_same_implementer_and_reviewer_rejected(self) -> None:
        runner, _ = self._runner("ok")
        # The SAME trusted runner object as both implementer and reviewer must
        # fail closed (constitution rule 10 / ADR-0032 identity floor).
        with self.assertRaises(ValueError):
            self._pipeline(review_runner=runner, implementer=runner)

    def test_p7_distinct_reviewer_constructs(self) -> None:
        runner, _ = self._runner("ok")
        pipeline = self._pipeline(review_runner=_ReviewAgent(), implementer=runner)
        # The engine's canonical implementer IS the trusted runner.
        self.assertIs(pipeline.scheduler.engine.cli_runner, runner)


class TestNoBypassStructural(_Base):
    def _source(self) -> str:
        return Path(tr.__file__).read_text(encoding="utf-8")

    def test_p3_runner_has_no_subprocess_or_direct_exec(self) -> None:
        tree = ast.parse(self._source())
        top_imports: set[str] = set()
        from_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                top_imports.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_imports.add(node.module.split(".")[0])
                from_modules.add(node.module)
        self.assertNotIn("subprocess", top_imports)
        self.assertNotIn("os", top_imports)
        # It must not import the old direct CLI runner at all.
        self.assertNotIn("gnosis.runner.claude_cli_runner", from_modules)
        # No direct-exec identifiers appear as CODE (docstring prose excluded).
        code_names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for banned in ("Popen", "ClaudeCodeCLIRunner"):
            self.assertNotIn(banned, code_names)

    def test_p3_only_execution_call_is_port_execute(self) -> None:
        tree = ast.parse(self._source())
        exec_calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self" and node.func.attr in {
                "execute", "run", "launch"}
        }
        # The runner calls self._port.execute; it must expose no self._launch*.
        self.assertNotIn("launch", exec_calls)

    def test_p8_no_directororchestrator_route(self) -> None:
        self.assertNotIn("DirectorOrchestrator", self._source())


if __name__ == "__main__":
    unittest.main()
