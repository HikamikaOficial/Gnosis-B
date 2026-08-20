"""Adapter milestone 2/4: InteractionStore wired to the real CLI runner.

The test that matters is the last class: a Director brief recorded once,
then replayed with the live runner replaced by one that FAILS if called.
Everything else is a property of that path.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.director.brief_record import BriefRecordState
from gnosis.director.orchestrator import DirectorOrchestrator
from gnosis.kernel.engine import TaskEngine
from gnosis.kernel.replay import InteractionStore, ReplayMiss, ReplayMode
from gnosis.kernel.run_store import RunStore
from gnosis.runner.capture import ExecutionResult
from gnosis.runner.claude_cli_runner import McpRunnerConfig
from gnosis.runner.replay_runner import (
    MAX_RECORDED_STREAM_BYTES,
    ReplayingCLIRunner,
    UnreplayableStream,
    mcp_fingerprint,
    workspace_fingerprint,
)
from gnosis.runner.retry import RetryPolicy

_FAST_RETRY = RetryPolicy(max_attempts=1, backoff_base_s=0.01, backoff_factor=2.0, max_backoff_s=0.02)


class _ScriptedRunner:
    """Stands in for the real ClaudeCodeCLIRunner: writes real files."""

    def __init__(self, stdout=b'{"ok": true}', stderr=b"", exit_code=0):
        self.stdout, self.stderr, self.exit_code = stdout, stderr, exit_code
        self.calls = 0

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        self.calls += 1
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_bytes(self.stdout)
        stderr_path.write_bytes(self.stderr)
        return ExecutionResult(
            command=("claude", "-p", prompt), exit_code=self.exit_code,
            timed_out=False, cancelled=False, duration_s=1.5,
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            started_at="t0", ended_at="t1",
            parsed_json={"ok": True} if self.exit_code == 0 else None,
        )


class _ForbiddenRunner:
    """Any call is a test failure: replay must never reach the model."""

    def run(self, *args, **kwargs):
        raise AssertionError("the live CLI was invoked during REPLAY")


class _ReplayRunnerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        (self.repo / "README.md").write_text("root\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.repo, check=True, capture_output=True)
        self.cassette = self.root / "cassette.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _paths(self, name):
        return self.root / f"{name}.out", self.root / f"{name}.err"


class TestRecordAndReplay(_ReplayRunnerTestCase):
    def test_replay_returns_the_recorded_run_without_calling_the_cli(self):
        out, err = self._paths("a")
        live = _ScriptedRunner(stdout=b'{"answer": 42}', stderr=b"warned")
        recorder = ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.RECORD), inner=live)
        recorded = recorder.run("do it", self.repo, out, err, timeout_s=60.0)
        self.assertEqual(live.calls, 1)

        out.unlink()
        err.unlink()
        player = ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.REPLAY), inner=_ForbiddenRunner())
        replayed = player.run("do it", self.repo, out, err, timeout_s=60.0)

        # The side effects the engine actually reads are reproduced, not
        # just the return value.
        self.assertEqual(out.read_bytes(), b'{"answer": 42}')
        self.assertEqual(err.read_bytes(), b"warned")
        self.assertEqual(replayed.exit_code, recorded.exit_code)
        self.assertEqual(replayed.parsed_json, recorded.parsed_json)
        self.assertEqual(replayed.command, recorded.command)
        self.assertEqual(replayed.duration_s, recorded.duration_s)

    def test_a_missing_recording_aborts_instead_of_calling_the_model(self):
        ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.RECORD),
            inner=_ScriptedRunner()).run("recorded", self.repo, *self._paths("a"))
        player = ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.REPLAY), inner=_ForbiddenRunner())
        with self.assertRaises(ReplayMiss):
            player.run("never recorded", self.repo, *self._paths("b"))

    def test_repeated_identical_calls_replay_in_order(self):
        out, err = self._paths("a")
        store = InteractionStore(self.cassette, ReplayMode.RECORD)
        first = _ScriptedRunner(stdout=b"first")
        ReplayingCLIRunner(store, inner=first).run("same", self.repo, out, err)
        second = _ScriptedRunner(stdout=b"second")
        ReplayingCLIRunner(store, inner=second).run("same", self.repo, out, err)

        player = ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.REPLAY), inner=_ForbiddenRunner())
        player.run("same", self.repo, out, err)
        self.assertEqual(out.read_bytes(), b"first")
        player.run("same", self.repo, out, err)
        self.assertEqual(out.read_bytes(), b"second")

    def test_non_utf8_output_replays_byte_for_byte(self):
        # Recording a lossy decode would make a replayed run observe
        # different bytes than the live one.
        raw = b"\xff\xfe not utf-8 \x00\x01"
        out, err = self._paths("a")
        ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.RECORD),
            inner=_ScriptedRunner(stdout=raw)).run("bin", self.repo, out, err)
        out.unlink()
        ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.REPLAY),
            inner=_ForbiddenRunner()).run("bin", self.repo, out, err)
        self.assertEqual(out.read_bytes(), raw)

    def test_an_oversized_stream_keeps_the_live_output_but_refuses_replay(self):
        big = b"x" * (MAX_RECORDED_STREAM_BYTES + 1)
        out, err = self._paths("a")
        live = ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.RECORD),
            inner=_ScriptedRunner(stdout=big))
        result = live.run("huge", self.repo, out, err)
        # The run really happened: its own output must survive.
        self.assertEqual(out.read_bytes(), big)
        self.assertEqual(result.exit_code, 0)
        # But replaying a prefix would be a quiet lie.
        with self.assertRaises(UnreplayableStream):
            ReplayingCLIRunner(
                InteractionStore(self.cassette, ReplayMode.REPLAY),
                inner=_ForbiddenRunner()).run("huge", self.repo, out, err)


class TestCassetteIdentity(_ReplayRunnerTestCase):
    """What counts as 'the same call' — the part that decides whether a
    cassette is evidence or a coincidence."""

    def _record(self, store, **kwargs):
        runner = ReplayingCLIRunner(store, inner=_ScriptedRunner())
        defaults = {"prompt": "do it", "cwd": self.repo, "timeout_s": 60.0}
        defaults.update(kwargs)
        out, err = self._paths("x")
        return runner.run(stdout_path=out, stderr_path=err, **defaults)

    def _misses_when(self, **changed):
        store = InteractionStore(self.cassette, ReplayMode.RECORD)
        self._record(store)
        player = ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.REPLAY), inner=_ForbiddenRunner())
        out, err = self._paths("y")
        params = {"prompt": "do it", "cwd": self.repo, "timeout_s": 60.0,
                  "stdout_path": out, "stderr_path": err}
        params.update(changed)
        with self.assertRaises(ReplayMiss):
            player.run(**params)

    def test_a_different_model_is_a_different_call(self):
        self._misses_when(model="claude-opus-5")

    def test_a_different_permission_mode_is_a_different_call(self):
        self._misses_when(permission_mode="bypassPermissions")

    def test_a_shorter_deadline_is_a_different_call(self):
        # A deadline can turn a success into a timeout, so it determines
        # the response.
        self._misses_when(timeout_s=1.0)

    def test_a_different_workspace_state_is_a_different_call(self):
        store = InteractionStore(self.cassette, ReplayMode.RECORD)
        self._record(store)
        (self.repo / "new.txt").write_text("changed", encoding="utf-8")
        player = ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.REPLAY), inner=_ForbiddenRunner())
        out, err = self._paths("y")
        with self.assertRaises(ReplayMiss):
            player.run("do it", self.repo, out, err, timeout_s=60.0)

    def test_the_key_is_workspace_content_not_its_path(self):
        # A cassette recorded in one clone must replay in an identical
        # clone elsewhere, or it is machine-local scratch, not evidence.
        clone = self.root / "clone"
        subprocess.run(["git", "clone", str(self.repo), str(clone)],
                       check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=clone, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=clone, check=True)
        self._record(InteractionStore(self.cassette, ReplayMode.RECORD))
        out, err = self._paths("y")
        replayed = ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.REPLAY),
            inner=_ForbiddenRunner()).run("do it", clone, out, err, timeout_s=60.0)
        self.assertEqual(replayed.exit_code, 0)

    def test_an_mcp_config_rewrite_is_a_different_call(self):
        # Same reason ADR-0013 binds approvals to config content: the file
        # decides which tools the agent can reach.
        config = self.repo / "tools.json"
        config.write_text('{"mcpServers": {}}', encoding="utf-8")
        mcp = McpRunnerConfig(config_paths=(str(config),))
        store = InteractionStore(self.cassette, ReplayMode.RECORD)
        self._record(store, mcp=mcp)
        config.write_text('{"mcpServers": {"danger": {"command": "sh"}}}', encoding="utf-8")
        player = ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.REPLAY), inner=_ForbiddenRunner())
        out, err = self._paths("y")
        with self.assertRaises(ReplayMiss):
            player.run("do it", self.repo, out, err, timeout_s=60.0, mcp=mcp)

    def test_absolute_paths_never_enter_the_key(self):
        self.assertNotIn("is_repo", {})  # guard against an empty assertion
        fingerprint = workspace_fingerprint(self.repo)
        self.assertNotIn(str(self.repo), json.dumps(fingerprint))
        config = self.repo / "tools.json"
        config.write_text("{}", encoding="utf-8")
        printed = json.dumps(mcp_fingerprint(McpRunnerConfig(config_paths=(str(config),)), self.repo))
        self.assertNotIn(str(self.repo), printed)

    def test_a_non_git_workspace_is_a_decision_not_a_crash(self):
        plain = self.root / "plain"
        plain.mkdir()
        self.assertEqual(workspace_fingerprint(plain), {"is_repo": False})


class TestBriefReplayEndToEnd(_ReplayRunnerTestCase):
    """L-0006: wiring to the primitive is not wiring to production. A real
    brief must record and replay through DirectorOrchestrator."""

    def _orchestrator(self, runner):
        return DirectorOrchestrator(
            director_root=self.root / "director", run_store=RunStore(self.root / "runs"),
            repo_path=self.repo,
            task_engine=TaskEngine(
                run_store=RunStore(self.root / "runs"), cli_runner=runner,
                retry_policy=_FAST_RETRY),
        )

    def _drop_brief(self, orch, brief_id):
        brief = DirectorBrief(brief_id=brief_id, title="Replayable",
                              mission="Ship it.", source=BriefSource.MANUAL)
        (orch.inbox.layout.inbox / f"{brief_id}.json").write_text(
            json.dumps(brief.to_dict()), encoding="utf-8")

    def test_a_brief_records_once_and_replays_with_no_model(self):
        live = _ScriptedRunner(stdout=b'{"result": "shipped"}')
        recording = self._orchestrator(
            ReplayingCLIRunner(InteractionStore(self.cassette, ReplayMode.RECORD), inner=live))
        self._drop_brief(recording, "BRIEF-REC")
        recorded = recording.run_pending()
        self.assertEqual(live.calls, 1)
        self.assertEqual(
            recording.records.get("BRIEF-REC").state, BriefRecordState.COMPLETED.value)

        # A second orchestrator, a fresh state directory, no live runner.
        self.root_second = self.root / "second"
        replaying = DirectorOrchestrator(
            director_root=self.root_second / "director",
            run_store=RunStore(self.root_second / "runs"), repo_path=self.repo,
            task_engine=TaskEngine(
                run_store=RunStore(self.root_second / "runs"),
                cli_runner=ReplayingCLIRunner(
                    InteractionStore(self.cassette, ReplayMode.REPLAY),
                    inner=_ForbiddenRunner()),
                retry_policy=_FAST_RETRY),
        )
        self._drop_brief(replaying, "BRIEF-REC")
        replayed = replaying.run_pending()

        self.assertEqual(
            replaying.records.get("BRIEF-REC").state, BriefRecordState.COMPLETED.value)
        self.assertEqual(replayed[0].execution.report.status,
                         recorded[0].execution.report.status)
        # And the evidence the engine captured came from the cassette.
        run_id = replayed[0].execution.run_ids[-1]
        stdout = RunStore(self.root_second / "runs").paths_for(run_id).stdout
        self.assertEqual(Path(stdout).read_bytes(), b'{"result": "shipped"}')


if __name__ == "__main__":
    unittest.main()
