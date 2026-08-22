"""Adapter milestone 2/4: InteractionStore wired to the real CLI runner.

The test that matters is the last class: a Director brief recorded once,
then replayed with the live runner replaced by one that FAILS if called.
Everything else is a property of that path.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.director.brief_record import BriefRecordState
from gnosis.director.orchestrator import DirectorOrchestrator
from gnosis.kernel.engine import TaskEngine
from gnosis.kernel.git_evidence import content_fingerprint
from gnosis.kernel.replay import InteractionStore, ReplayMiss, ReplayMode
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.verification import CommandVerifier
from gnosis.runner.capture import ExecutionResult
from gnosis.runner.claude_cli_runner import ClaudeCodeCLIRunner, McpRunnerConfig
from gnosis.runner.replay_runner import (
    MAX_RECORDED_STREAM_BYTES,
    ReplayedFailure,
    ReplayingCLIRunner,
    UnreplayableStream,
    mcp_fingerprint,
)
from gnosis.runner.retry import RetryPolicy

_FAST_RETRY = RetryPolicy(max_attempts=1, backoff_base_s=0.01, backoff_factor=2.0, max_backoff_s=0.02)

# Every task now needs deterministic verification to reach COMPLETED: the
# engine refuses a verifier-less run before it launches anything, and
# `completion_is_evidenced` refuses the transition without a passing
# result (F-34). This is REAL verification — a child process and the exit
# code the OS reports — not a stand-in that says "passed" without looking,
# which is the fixture mistake L-0013 was earned on.
_PASSING_VERIFIER = CommandVerifier(
    "always-pass", [sys.executable, "-c", "raise SystemExit(0)"])


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


class _MutatingRunner(_ScriptedRunner):
    """Writes into the REPOSITORY, like the only agent GNOSIS runs.

    The scripted runner above touches nothing but its own stdout files,
    which the tests place outside the repo — a stand-in structurally
    incapable of exhibiting the failure that mattered (independent
    review). This one edits the tree between calls."""

    def __init__(self, edits, **kwargs):
        super().__init__(**kwargs)
        self.edits = list(edits)

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s=1800.0, **kwargs):
        result = super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs)
        name, content = self.edits[min(self.calls, len(self.edits)) - 1]
        (Path(cwd) / name).write_text(content, encoding="utf-8")
        return result


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
        fingerprint = content_fingerprint(self.repo)
        self.assertNotIn(str(self.repo), json.dumps(fingerprint))
        config = self.repo / "tools.json"
        config.write_text("{}", encoding="utf-8")
        printed = json.dumps(mcp_fingerprint(McpRunnerConfig(config_paths=(str(config),)), self.repo))
        self.assertNotIn(str(self.repo), printed)

    def test_a_non_git_workspace_is_a_decision_not_a_crash(self):
        plain = self.root / "plain"
        plain.mkdir()
        self.assertEqual(content_fingerprint(plain), {"is_repo": False})


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
        recorded = recording.run_pending(verifier=_PASSING_VERIFIER)
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
        replayed = replaying.run_pending(verifier=_PASSING_VERIFIER)

        self.assertEqual(
            replaying.records.get("BRIEF-REC").state, BriefRecordState.COMPLETED.value)
        self.assertEqual(replayed[0].execution.report.status,
                         recorded[0].execution.report.status)
        # And the evidence the engine captured came from the cassette.
        run_id = replayed[0].execution.run_ids[-1]
        stdout = RunStore(self.root_second / "runs").paths_for(run_id).stdout
        self.assertEqual(Path(stdout).read_bytes(), b'{"result": "shipped"}')


class TestRecordingAnAgentThatEditsTheRepo(_ReplayRunnerTestCase):
    """The case the mechanism exists for, and the one it used to fail.

    Keying each call on the tree it saw meant call 2 got a key derived
    from call 1's edits — which a replay, reproducing stdout but not those
    edits, could never compute again."""

    def test_two_calls_replay_even_though_the_agent_changed_the_tree(self):
        edits = [("a.py", "written by call 1\n"), ("b.py", "written by call 2\n")]
        live = _MutatingRunner(edits, stdout=b'{"ok": 1}')
        recorder = ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.RECORD), inner=live)
        out, err = self._paths("a")
        recorder.run("step", self.repo, out, err, timeout_s=60.0)
        recorder.run("step", self.repo, out, err, timeout_s=60.0)
        self.assertEqual(live.calls, 2)

        # Reset the tree to what the recording started from, which is the
        # only state a replay can honestly claim to reproduce.
        for name, _ in edits:
            (self.repo / name).unlink()

        player = ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.REPLAY), inner=_ForbiddenRunner())
        player.run("step", self.repo, out, err, timeout_s=60.0)
        player.run("step", self.repo, out, err, timeout_s=60.0)   # used to ReplayMiss

    def test_a_replay_against_a_different_starting_tree_still_misses(self):
        # The fix must not have bought multi-call replay by making the
        # cassette indifferent to which tree it replays against.
        live = _MutatingRunner([("a.py", "x\n")], stdout=b'{"ok": 1}')
        out, err = self._paths("a")
        ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.RECORD), inner=live,
        ).run("step", self.repo, out, err, timeout_s=60.0)
        (self.repo / "a.py").unlink()
        (self.repo / "unrelated.py").write_text("different starting point\n", encoding="utf-8")
        with self.assertRaises(ReplayMiss):
            ReplayingCLIRunner(
                InteractionStore(self.cassette, ReplayMode.REPLAY),
                inner=_ForbiddenRunner(),
            ).run("step", self.repo, out, err, timeout_s=60.0)


class TestFailuresAndCorruption(_ReplayRunnerTestCase):
    def test_a_call_that_raised_live_is_recorded_and_re_raises_on_replay(self):
        # The call happened and may have cost money. Dropping its row let
        # the NEXT recording take occurrence 0, so a failed call replayed
        # as a later success (independent review).
        class _Exploding:
            calls = 0

            def run(self, **kwargs):
                _Exploding.calls += 1
                raise FileNotFoundError("claude binary missing")

        out, err = self._paths("a")
        recorder = ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.RECORD), inner=_Exploding())
        with self.assertRaises(FileNotFoundError):
            recorder.run("boom", self.repo, out, err, timeout_s=60.0)

        player = ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.REPLAY), inner=_ForbiddenRunner())
        with self.assertRaises(ReplayedFailure):
            player.run("boom", self.repo, out, err, timeout_s=60.0)

    def test_a_torn_cassette_tail_does_not_swallow_the_next_call(self):
        # Appending onto an unterminated row glued them together, silently
        # discarding the just-recorded live call.
        out, err = self._paths("a")
        ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.RECORD),
            inner=_ScriptedRunner(stdout=b"first"),
        ).run("one", self.repo, out, err, timeout_s=60.0)
        with self.cassette.open("a", encoding="utf-8") as fh:
            fh.write('{"key": "torn", "tool": "claude_code_cli"')   # no newline

        ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.RECORD),
            inner=_ScriptedRunner(stdout=b"second"),
        ).run("two", self.repo, out, err, timeout_s=60.0)

        store = InteractionStore(self.cassette, ReplayMode.REPLAY)
        prompts = {record.params["prompt"] for record in store.records()}
        self.assertEqual(prompts, {"one", "two"})

    def test_a_forged_key_cannot_misdirect_a_replay(self):
        # The stored key is data. Trusting it let a row claim to be some
        # other call's response.
        out, err = self._paths("a")
        ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.RECORD),
            inner=_ScriptedRunner(stdout=b"real"),
        ).run("honest", self.repo, out, err, timeout_s=60.0)
        rows = [json.loads(line) for line in
                self.cassette.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows[0]["key"] = "0" * 64
        self.cassette.write_text(
            "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")

        replayed = ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.REPLAY), inner=_ForbiddenRunner(),
        ).run("honest", self.repo, out, err, timeout_s=60.0)
        self.assertEqual(out.read_bytes(), b"real")
        self.assertEqual(replayed.exit_code, 0)

    def test_the_director_can_be_built_in_replay_mode_from_production_code(self):
        # ADR-0014 shipped with ZERO production constructions of
        # ReplayingCLIRunner — reachable from tests only, the exact
        # condition its own opening paragraph condemns.
        from gnosis.director.orchestrator import recording_orchestrator
        orchestrator = recording_orchestrator(
            director_root=self.root / "director",
            run_store=RunStore(self.root / "runs"), repo_path=self.repo,
            cassette=self.cassette, mode=ReplayMode.RECORD,
            inner_runner=_ScriptedRunner(stdout=b'{"ok": 1}'),
        )
        brief = DirectorBrief(brief_id="B1", title="T", mission="Ship it.",
                              source=BriefSource.MANUAL)
        (orchestrator.inbox.layout.inbox / "B1.json").write_text(
            json.dumps(brief.to_dict()), encoding="utf-8")
        outcomes = orchestrator.run_pending(verifier=_PASSING_VERIFIER)
        self.assertTrue(outcomes[0].accepted)
        self.assertTrue(self.cassette.exists())

    def test_the_wrapper_shows_policy_rules_the_real_binary(self):
        # Wrapping a runner for audit must not change the action identity
        # the policy gate approves.
        inner = ClaudeCodeCLIRunner(binary="claude")
        wrapped = ReplayingCLIRunner(
            InteractionStore(self.cassette, ReplayMode.RECORD), inner=inner)
        self.assertEqual(wrapped.binary, inner.binary)


if __name__ == "__main__":
    unittest.main()
