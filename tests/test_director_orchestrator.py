import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.director.brief_record import BriefRecordState
from gnosis.director.orchestrator import DirectorOrchestrator
from gnosis.kernel.engine import TaskEngine
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.state_machine import RunState
from gnosis.runner.capture import ExecutionResult
from gnosis.runner.retry import RetryPolicy

_FAST_RETRY = RetryPolicy(max_attempts=2, backoff_base_s=0.01, backoff_factor=2.0, max_backoff_s=0.02)


class _FakeCliRunner:
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


def _make_brief(brief_id: str, title: str = "Do a thing") -> DirectorBrief:
    return DirectorBrief(brief_id=brief_id, title=title, mission="Ship it.", source=BriefSource.MANUAL)


class TestDirectorOrchestrator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        self.run_store = RunStore(self.root / "runs")
        self.director_root = self.root / ".gnosis" / "director"

    def tearDown(self):
        self.tmp.cleanup()

    def _orchestrator(self, outcomes=("succeed",)) -> DirectorOrchestrator:
        engine = TaskEngine(run_store=self.run_store, cli_runner=_FakeCliRunner(outcomes), retry_policy=_FAST_RETRY)
        return DirectorOrchestrator(
            director_root=self.director_root, run_store=self.run_store, repo_path=self.repo, task_engine=engine,
        )

    def _drop_brief(self, brief: DirectorBrief) -> None:
        orch = DirectorOrchestrator(self.director_root, self.run_store, self.repo)
        path = orch.inbox.layout.inbox / f"{brief.brief_id}.json"
        path.write_text(json.dumps(brief.to_dict()), encoding="utf-8")

    def test_end_to_end_success_writes_outbox_report(self):
        self._drop_brief(_make_brief("BRIEF-1"))
        orch = self._orchestrator(outcomes=["succeed"])

        outcomes = orch.run_pending()

        self.assertEqual(len(outcomes), 1)
        self.assertTrue(outcomes[0].accepted)
        task_id = outcomes[0].task_id
        self.assertTrue((orch.inbox.layout.outbox / f"{task_id}.json").exists())
        self.assertTrue((orch.inbox.layout.outbox / f"{task_id}.md").exists())

        record = orch.records.get("BRIEF-1")
        self.assertEqual(record.state, BriefRecordState.COMPLETED.value)
        self.assertEqual(record.task_id, task_id)

    def test_failed_task_recorded_as_failed(self):
        self._drop_brief(_make_brief("BRIEF-1"))
        orch = self._orchestrator(outcomes=["fail", "fail"])

        orch.run_pending()

        record = orch.records.get("BRIEF-1")
        self.assertEqual(record.state, BriefRecordState.FAILED.value)

    def test_duplicate_brief_ingestion_runs_task_only_once(self):
        brief = _make_brief("BRIEF-1")
        self._drop_brief(brief)
        engine = TaskEngine(
            run_store=self.run_store, cli_runner=_FakeCliRunner(["succeed"]), retry_policy=_FAST_RETRY,
        )
        orch = DirectorOrchestrator(self.director_root, self.run_store, self.repo, task_engine=engine)

        first_pass = orch.run_pending()
        self.assertEqual(len(first_pass), 1)
        self.assertTrue(first_pass[0].accepted)

        # Re-drop the exact same brief_id (simulating a re-sent brief).
        self._drop_brief(brief)
        second_pass = orch.run_pending()

        self.assertEqual(len(second_pass), 1)
        self.assertFalse(second_pass[0].accepted)
        self.assertEqual(second_pass[0].reason, "duplicate brief_id")
        # Only one task was ever executed against the CLI runner.
        self.assertEqual(engine.cli_runner.calls, 1)

    def test_resume_interrupted_marks_stuck_brief_failed(self):
        self._drop_brief(_make_brief("BRIEF-1"))
        orch = DirectorOrchestrator(self.director_root, self.run_store, self.repo)

        claim = orch.inbox.claim(orch.inbox.list_pending()[0])
        task_id = "TASK-INTERRUPTED"
        orch.records.create(claim.brief.brief_id, task_id, BriefRecordState.ASSIGNED)
        orch.records.update(claim.brief.brief_id, state=BriefRecordState.IN_PROGRESS)

        # Simulate a run that was RUNNING when the process died: no
        # heartbeat is ever written, so RecoveryManager will flag it.
        run_paths = self.run_store.create_run("RUN-ORPHAN", task_id)
        self.run_store.update_state("RUN-ORPHAN", RunState.RUNNING)
        orch.records.update(claim.brief.brief_id, run_ids=["RUN-ORPHAN"])

        recovered = orch.resume_interrupted(stale_after_s=0)

        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].brief_id, "BRIEF-1")
        self.assertEqual(recovered[0].state, BriefRecordState.FAILED.value)
        self.assertEqual(self.run_store.read_meta("RUN-ORPHAN").state, RunState.CRASHED.value)

    def test_resume_interrupted_leaves_live_run_alone(self):
        self._drop_brief(_make_brief("BRIEF-1"))
        orch = DirectorOrchestrator(self.director_root, self.run_store, self.repo)
        claim = orch.inbox.claim(orch.inbox.list_pending()[0])
        task_id = "TASK-LIVE"
        orch.records.create(claim.brief.brief_id, task_id, BriefRecordState.ASSIGNED)
        orch.records.update(claim.brief.brief_id, state=BriefRecordState.IN_PROGRESS)

        self.run_store.create_run("RUN-LIVE", task_id)
        self.run_store.update_state("RUN-LIVE", RunState.RUNNING)
        self.run_store.heartbeat("RUN-LIVE")  # this process's own, live, fingerprint
        orch.records.update(claim.brief.brief_id, run_ids=["RUN-LIVE"])

        recovered = orch.resume_interrupted(stale_after_s=3600)

        self.assertEqual(recovered, [])
        self.assertEqual(orch.records.get("BRIEF-1").state, BriefRecordState.IN_PROGRESS.value)


if __name__ == "__main__":
    unittest.main()
