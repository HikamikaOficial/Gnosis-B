"""Crash accounting at the production integration/re-review boundary.

The merge is a seam double; checkpoint serialization, budget gates and review raw
output are real. Git merge/restart behavior is covered in integration_resume.
"""
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from gnosis.director.checkpoint import CapturedProof, TrustedAttempt
from gnosis.director.composition import ProductionComposition
from gnosis.director.publication import GitTreeEvidence
from gnosis.kernel.budget import Budget, BudgetExhausted
from tests import trust_fixtures as tf
from tests.test_phase_checkpoint import _record
from tests.test_pipeline import _Agent
from tests.test_pipeline_resume import _disk_pipeline


@pytest.mark.parametrize("limited", [False, True])
def test_crashed_rereviews_keep_budget_and_raw_attempts(tmp_path: Path, limited: bool) -> None:
    tf.git_repo(tmp_path / "repo")
    launches = []

    class InterruptedReviewer(_Agent):
        def run(self, **kwargs):
            # A separate store read proves reservation precedes invocation.
            saved = pipeline.checkpoints.load("brief-1")
            launches.append(saved.launches)
            super().run(**kwargs)
            raise SystemExit("review process/controller interrupted")

    pipeline = _disk_pipeline(tmp_path, _Agent(), InterruptedReviewer())
    pipeline.budget = Budget(max_agent_launches=4 if limited else 20)
    record = replace(_record(),
        trusted_attempt=TrustedAttempt(tf.spec(), tf.launched()), proof_attempts=1,
        proof=CapturedProof("run-1", 1, "d" * 64, GitTreeEvidence("a" * 40, "b" * 40)))
    pipeline.checkpoints.create(record)

    def invoke_review(task_id, convergence, *, re_reviewer):
        return re_reviewer(tmp_path / "repo")

    with patch("gnosis.director.composition.WorkIntegrator") as integrator:
        integrator.return_value.integrate.side_effect = invoke_review
        attempts = 1 if limited else 3
        for _ in range(attempts):
            composition = ProductionComposition(pipeline, Mock(), Mock(), tmp_path / "repo",
                                                 Mock(), integration_target="master")
            with pytest.raises(SystemExit, match="interrupted"):
                composition._finish_integration(record.brief, record.task_id, "run-1")
        saved = pipeline.checkpoints.load(record.brief.brief_id)
        assert saved.launches == 3 + attempts
        assert saved.integration_attempts == attempts
        assert saved.integration is None and saved.prepared_integration is None
        raw = sorted((pipeline.inbox.layout.outbox / "task-1-rereview").rglob("*.stdout"))
        assert len(raw) == attempts
        retained = {path: path.read_bytes() for path in raw}
        if limited:
            with pytest.raises(BudgetExhausted):
                composition._finish_integration(record.brief, record.task_id, "run-1")
        else:
            outcome = composition._finish_integration(record.brief, record.task_id, "run-1")
            assert not outcome.success and "attempt budget exhausted" in outcome.reason
        assert launches == list(range(4, 4 + attempts))
        assert {path: path.read_bytes() for path in raw} == retained
        assert pipeline.checkpoints.load(record.brief.brief_id).launches == 3 + attempts
