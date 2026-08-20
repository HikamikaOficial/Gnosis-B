import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.director.brief_record import BriefRecordState
from gnosis.director.orchestrator import DirectorOrchestrator
from gnosis.kernel.claims import ClaimStatus, ClaimStore, WorkAuthority
from gnosis.kernel.engine import TaskEngine
from gnosis.kernel.lease import LeaseStore
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.state_machine import RunState
from gnosis.kernel.verification import CommandVerifier
from gnosis.kernel.worktree import WorktreeManager
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
        (self.repo / "README.md").write_text("root" + chr(10), encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.repo, check=True, capture_output=True)
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
        self.run_store.create_run("RUN-ORPHAN", task_id)
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


class TestGovernedOrchestrator(unittest.TestCase):
    """Orchestrator claim migration (ADR-0006..0008 follow-up): with a
    WorkAuthority + WorktreeManager configured, every brief runs under a
    fenced grant inside the task's own worktree."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        (self.repo / "README.md").write_text("root" + chr(10), encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.repo, check=True, capture_output=True)
        self.run_store = RunStore(self.root / "runs")
        self.director_root = self.root / ".gnosis" / "director"
        self.claims = ClaimStore(self.root / "claims.json")
        self.leases = LeaseStore(self.root / "leases.json")
        self.authority = WorkAuthority(self.claims, self.leases, default_ttl_s=300)
        self.worktrees = WorktreeManager(self.repo, self.root / "worktrees")
        self.verifier = CommandVerifier(
            "noop-pass", [sys.executable, "-c", "import sys; sys.exit(0)"],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _drop_brief(self, brief_id: str) -> None:
        orch = DirectorOrchestrator(self.director_root, self.run_store, self.repo)
        brief = DirectorBrief(brief_id=brief_id, title="Governed thing",
                              mission="Ship it.", source=BriefSource.MANUAL)
        path = orch.inbox.layout.inbox / f"{brief.brief_id}.json"
        path.write_text(json.dumps(brief.to_dict()), encoding="utf-8")

    def test_governed_brief_resolves_claim_inside_worktree(self):
        self._drop_brief("BRIEF-GOV-1")
        engine = TaskEngine(
            run_store=self.run_store, cli_runner=_FakeCliRunner(["succeed"]),
            retry_policy=_FAST_RETRY,
        )
        orch = DirectorOrchestrator(
            director_root=self.director_root, run_store=self.run_store,
            repo_path=self.repo, task_engine=engine,
            authority=self.authority, worker_id="orchestrator-1",
            worktrees=self.worktrees,
        )
        outcomes = orch.run_pending(verifier=self.verifier)
        self.assertEqual(len(outcomes), 1)
        self.assertTrue(outcomes[0].accepted)
        task_id = outcomes[0].task_id
        claim = self.claims.get(task_id)
        self.assertEqual(claim.status, ClaimStatus.RESOLVED)
        self.assertEqual(claim.holder, "orchestrator-1")
        handle = self.worktrees.load_handle(task_id)
        self.assertTrue(Path(handle.path).exists())
        record = orch.records.get("BRIEF-GOV-1")
        self.assertEqual(record.state, BriefRecordState.COMPLETED.value)

    def test_authority_without_worker_id_is_refused_at_construction(self):
        with self.assertRaises(ValueError):
            DirectorOrchestrator(
                director_root=self.director_root, run_store=self.run_store,
                repo_path=self.repo, authority=self.authority,
            )

    def test_authority_without_worktrees_is_refused_at_construction(self):
        # Governed briefs must be workspace-isolated (Codex review).
        with self.assertRaises(ValueError):
            DirectorOrchestrator(
                director_root=self.director_root, run_store=self.run_store,
                repo_path=self.repo, authority=self.authority,
                worker_id="orchestrator-1",
            )

    def test_governed_failure_fails_the_brief_without_aborting_the_batch(self):
        # Deposition / workspace failure / precondition violations are
        # EXPECTED in governed mode: the brief must end FAILED and visible,
        # and the rest of the batch must still run (adversarial review).
        self._drop_brief("BRIEF-GOV-BAD")
        self._drop_brief("BRIEF-GOV-OK")
        orch = DirectorOrchestrator(
            director_root=self.director_root, run_store=self.run_store,
            repo_path=self.repo,
            task_engine=TaskEngine(
                run_store=self.run_store, cli_runner=_FakeCliRunner(["succeed"] * 4),
                retry_policy=_FAST_RETRY,
            ),
            authority=self.authority, worker_id="orchestrator-1",
            worktrees=self.worktrees,
        )
        # No verifier: the engine's evidence gate refuses every governed
        # brief with ValueError, the batch must survive it.
        outcomes = orch.run_pending()
        self.assertEqual(len(outcomes), 2)
        self.assertTrue(all(o.accepted for o in outcomes))
        self.assertTrue(all("execution failed" in o.reason for o in outcomes))
        for brief_id in ("BRIEF-GOV-BAD", "BRIEF-GOV-OK"):
            self.assertEqual(
                orch.records.get(brief_id).state, BriefRecordState.FAILED.value,
            )


if __name__ == "__main__":
    unittest.main()
