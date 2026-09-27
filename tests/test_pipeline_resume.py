"""Recreate the real pipeline over persisted Git/worktree/kernel state."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trust_fixtures as tf
from test_pipeline import _FAIL_REVIEW, _Agent, _permissive, _PipelineTestCase

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.contracts.engineer_report import ReportStatus
from gnosis.director.checkpoint import CheckpointError, PipelineCheckpointStore
from gnosis.director.pipeline import GovernedPipeline
from gnosis.kernel.budget import Budget
from gnosis.kernel.convergence import ConvergencePolicy
from gnosis.kernel.engine import TaskEngine
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.scheduler import HoldStore, TaskScheduler
from gnosis.kernel.verification import CommandVerifier
from gnosis.kernel.worktree import WorktreeManager
from gnosis.runner.retry import RetryPolicy


def _disk_pipeline(root, author, reviewer):
    store = RunStore(root / "runs")
    engine = TaskEngine(store, cli_runner=author, retry_policy=RetryPolicy(max_attempts=3))
    return GovernedPipeline(root / "director",
        TaskScheduler(engine, store, HoldStore(root / "holds.jsonl"), "test://worker"),
        root / "repo", CommandVerifier("check", [sys.executable, "-c", "pass"]),
        _permissive(), reviewer, convergence_policy=ConvergencePolicy(max_rounds=3),
        worktrees=WorktreeManager(root / "repo", root / "worktrees"),
        checkpoint_store=PipelineCheckpointStore(root / "protected"),
        checkpoint_context="c" * 64)


@pytest.mark.parametrize("phase", ["implementation", "review"])
def test_real_process_death_preserves_task_work_raw_output_and_budget(tmp_path, phase):
    tf.git_repo(tmp_path / "repo")
    brief = DirectorBrief("KILL-1", "preserve", "preserve work", BriefSource.MANUAL)
    (tmp_path / "brief.json").write_text(json.dumps(brief.to_dict()))
    child = r'''
import json, os, sys
from pathlib import Path
from test_pipeline_resume import _disk_pipeline, _Agent, DirectorBrief
root, phase = Path(sys.argv[1]), sys.argv[2]
class KilledAgent(_Agent):
    def run(self, **kwargs):
        (kwargs["cwd"] / "saved.txt").write_text("before process death")
        super().run(**kwargs)
        os._exit(77)
brief = DirectorBrief.from_dict(json.loads((root / "brief.json").read_text()))
_disk_pipeline(root, KilledAgent() if phase == "implementation" else _Agent(),
              KilledAgent() if phase == "review" else _Agent()).run_brief(brief)
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((str(Path(__file__).resolve().parents[1] / "src"),
                                        str(Path(__file__).resolve().parent)))
    killed = subprocess.run([sys.executable, "-c", child, str(tmp_path), phase],
                            capture_output=True, text=True, env=env, timeout=60, check=False)
    assert killed.returncode == 77, killed.stderr
    author, reviewer = _Agent(), _Agent()
    restored = _disk_pipeline(tmp_path, author, reviewer)
    checkpoint = restored.checkpoints.load(brief.brief_id)
    assert checkpoint.implementation_attempts == 1
    assert checkpoint.rounds_started == (1 if phase == "review" else 0)
    source = restored._exec_root(checkpoint.task_id)
    assert (source / "saved.txt").read_text() == "before process death"
    raw = restored.scheduler.engine.run_store.paths_for(checkpoint.attempt_ids[0]).stdout
    before_raw = raw.read_bytes()
    assert before_raw
    result = restored.run_brief(brief)
    assert result.status is ReportStatus.COMPLETED, result.reason_code
    assert result.task_id == checkpoint.task_id
    assert (source / "saved.txt").read_text() == "before process death"
    assert raw.read_bytes() == before_raw
    assert len(author.prompts) == (1 if phase == "implementation" else 0)
    saved = restored.checkpoints.load(brief.brief_id)
    assert saved.implementation_attempts == (2 if phase == "implementation" else 1)
    assert saved.rounds_started == (1 if phase == "implementation" else 2)


class TestPipelineResume(_PipelineTestCase):
    def setUp(self):
        super().setUp()
        self.resume_brief = super()._brief()

    def _brief(self):
        return self.resume_brief

    def _durable(self, reviewer, implementer=None, **kwargs):
        return self._pipeline(reviewer, implementer=implementer,
                              checkpoint_store=PipelineCheckpointStore(self.root / "protected"),
                              checkpoint_context="a" * 64, **kwargs)

    def test_restart_after_implementation_reuses_task_worktree_and_run(self):
        author, reviewer = _Agent(), _Agent()
        first = self._durable(reviewer, author)
        with (patch.object(first, "_converge", side_effect=SystemExit("power loss")),
              pytest.raises(SystemExit)):
            first.run_brief(self._brief())
        saved = first.checkpoints.load("BRIEF-1")
        assert saved.implementation is not None
        source = first._exec_root(saved.task_id)
        (source / "preserved.txt").write_text("unfinished work")
        resumed = self._durable(reviewer, author).run_brief(self._brief())
        assert resumed.status is ReportStatus.COMPLETED
        assert resumed.task_id == saved.task_id
        assert resumed.implementation.run_ids == saved.implementation.execution.run_ids
        assert (source / "preserved.txt").read_text() == "unfinished work"
        assert len(author.prompts) == 1

    def test_restart_after_convergence_never_relaunches_and_repairs_evidence_copy(self):
        author, reviewer = _Agent(), _Agent()
        first = self._durable(reviewer, author)
        with (patch.object(first, "_finish", side_effect=SystemExit("power loss")),
              pytest.raises(SystemExit)):
            first.run_brief(self._brief())
        saved = first.checkpoints.load("BRIEF-1")
        evidence = first.inbox.layout.outbox / f"{saved.task_id}-convergence" / "convergence.json"
        evidence.write_text('{"outcome":"INTERRUPTED"}')
        resumed = self._durable(reviewer, author).run_brief(self._brief())
        assert resumed.status is ReportStatus.COMPLETED
        assert resumed.task_id == saved.task_id
        assert len(author.prompts) == reviewer.reviews == 1
        assert json.loads(evidence.read_text())["outcome"] == "CONVERGED"

    def test_reviewed_bytes_changed_after_crash_cannot_be_completed(self):
        author, reviewer = _Agent(), _Agent()
        first = self._durable(reviewer, author)
        done = first.run_brief(self._brief())
        assert done.status is ReportStatus.COMPLETED
        (first._exec_root(done.task_id) / "code.py").write_text("corrupt = True\n")
        resumed = self._durable(reviewer, author).run_brief(self._brief())
        assert resumed.status is ReportStatus.BLOCKED
        assert resumed.reason_code == "convergence_error:CheckpointError"
        assert reviewer.reviews == len(author.prompts) == 1

    def test_interrupted_implementation_is_reserved_and_bounded_across_restarts(self):
        author, reviewer = _Agent(), _Agent()
        first = self._durable(reviewer, author)
        def partial(**kwargs):
            (kwargs["cwd"] / "partial.txt").write_text("saved before kill")
            raise SystemExit("power loss")
        with patch.object(author, "run", side_effect=partial), pytest.raises(SystemExit):
            first.run_brief(self._brief())
        saved = first.checkpoints.load("BRIEF-1")
        assert saved.implementation_attempts == saved.launches == 1
        assert len(saved.attempt_ids) == 1
        resumed = self._durable(reviewer, author).run_brief(self._brief())
        assert resumed.reason_code == "budget:implementation_attempts"
        assert resumed.status is ReportStatus.PARTIAL
        assert resumed.task_id == saved.task_id
        assert not author.prompts and not reviewer.reviews
        assert (first._exec_root(saved.task_id) / "partial.txt").read_text() == "saved before kill"

    def test_interrupted_implementation_reattaches_work_when_attempt_budget_remains(self):
        author, reviewer = _Agent(), _Agent()
        first = self._durable(reviewer, author)
        first.scheduler.engine.retry_policy = RetryPolicy(max_attempts=2)
        with (patch.object(author, "run", side_effect=SystemExit("power loss")),
              pytest.raises(SystemExit)):
            first.run_brief(self._brief())
        saved = first.checkpoints.load("BRIEF-1")
        source = first._exec_root(saved.task_id)
        (source / "partial.txt").write_text("keep")
        second = self._durable(reviewer, author)
        second.scheduler.engine.retry_policy = RetryPolicy(max_attempts=2)
        resumed = second.run_brief(self._brief())
        assert resumed.status is ReportStatus.COMPLETED
        assert resumed.task_id == saved.task_id
        assert (source / "partial.txt").read_text() == "keep"
        restored = second.checkpoints.load("BRIEF-1")
        assert restored.implementation_attempts == 2
        assert len(restored.attempt_ids) == 2
        assert second.records.get("BRIEF-1").run_ids == list(restored.attempt_ids)

    def test_interrupted_correction_preserves_review_then_resumes_next_round(self):
        author, reviewer = _Agent(), _Agent(review_answers=(_FAIL_REVIEW,))
        first = self._durable(reviewer, author)
        def kill_fix(cwd):
            (cwd / "fixed.txt").write_text("completed before interruption")
            raise SystemExit("power loss")
        author.on_fix = kill_fix
        with pytest.raises(SystemExit):
            first.run_brief(self._brief())
        saved = first.checkpoints.load("BRIEF-1")
        assert saved.rounds_started == 1
        assert saved.convergence.rounds[0].review is not None
        assert saved.convergence.rounds[0].fix is None
        author.on_fix = None  # the replacement Worker can finish the requested fix
        resumed = self._durable(_Agent(), author).run_brief(self._brief())
        assert resumed.status is ReportStatus.COMPLETED
        assert [r.index for r in resumed.convergence.rounds] == [1, 2]
        assert len(resumed.convergence.rework_attempts) == 2
        assert resumed.convergence.rework_attempts[-1].result.succeeded
        assert len(author.prompts) == 3  # implementation + interrupted + resumed correction

    def test_spent_round_cannot_be_restarted_forever(self):
        author, reviewer = _Agent(), _Agent()
        first = self._durable(reviewer, author)
        with patch.object(reviewer, "run", side_effect=SystemExit("power loss")):
            for _ in range(2):
                with pytest.raises(SystemExit):
                    first.run_brief(self._brief())
        saved = first.checkpoints.load("BRIEF-1")
        assert saved.rounds_started == 2
        resumed = self._durable(reviewer, author).run_brief(self._brief())
        assert resumed.status is ReportStatus.PARTIAL
        assert resumed.reason_code == "ROUNDS_EXHAUSTED"
        assert len(author.prompts) == 1 and reviewer.reviews == 0

    def test_launch_budget_does_not_reset_on_restart(self):
        author, reviewer = _Agent(), _Agent()
        first = self._durable(reviewer, author, budget=Budget(max_agent_launches=1))
        before = first.run_brief(self._brief())
        assert before.status is ReportStatus.PARTIAL
        resumed = self._durable(reviewer, author, budget=Budget(max_agent_launches=1)).run_brief(self._brief())
        assert resumed.status is ReportStatus.PARTIAL
        assert len(author.prompts) == 1 and reviewer.reviews == 0

    def test_changed_context_refuses_before_work(self):
        author, reviewer = _Agent(), _Agent()
        first = self._durable(reviewer, author)
        first.run_brief(self._brief())
        second = self._durable(reviewer, author)
        second.checkpoint_context = "b" * 64
        with pytest.raises(CheckpointError, match="context"):
            second.run_brief(self._brief())
        assert len(author.prompts) == reviewer.reviews == 1
