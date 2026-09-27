from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pipeline import _FAIL_REVIEW, _PASS_REVIEW, _Agent, _PipelineTestCase
from test_queue_fencing import fixture

from gnosis.director.checkpoint import PipelineCheckpointStore
from gnosis.director.supervisor import StopReason, WorkerSupervisor
from gnosis.kernel.claims import ClaimStatus, ClaimStore, WorkAuthority
from gnosis.kernel.execution_scope import ExecutionCancelled, ExecutionScope
from gnosis.kernel.lease import LeaseStore, StaleLeaseError
from gnosis.runner.claude_cli_runner import CancellationToken


def test_supervisor_cancels_live_handler_when_its_grant_is_replaced(tmp_path):
    queue, now = fixture(tmp_path)
    replacement = None
    def handler(work):
        nonlocal replacement
        now[0] += 11
        queue.authority.sweep()
        queue.recover()
        replacement = queue.claim("replacement")
        deadline = time.monotonic() + 5
        while not work.cancellation_token.is_cancelled() and time.monotonic() < deadline:
            time.sleep(0.005)
        assert work.cancellation_token.is_cancelled()
    report = WorkerSupervisor(queue, heartbeat_interval_s=0.01).run("old", handler)
    assert report.stopped_because is StopReason.DEPOSED
    queue.authority.assert_current(replacement.grant)
    assert queue.done_ids() == queue.blocked_ids() == []


def test_cancelled_scope_cannot_enter_a_phase():
    token = CancellationToken()
    current = Mock()
    scope = ExecutionScope(current, token, 1, "owner")
    token.cancel()
    with pytest.raises(ExecutionCancelled):
        scope.check()
    current.assert_called_once()


class TestBorrowedPipelineScope(_PipelineTestCase):
    def setUp(self):
        super().setUp()
        self.brief = super()._brief()
        self.now = [1000.0]
        clock = lambda: self.now[0]
        self.authority = WorkAuthority(ClaimStore(self.root / "claims", clock=clock),
            LeaseStore(self.root / "leases", clock=clock), default_ttl_s=10,
            reclaim_grace_s=0, clock=clock)
        self.grant = self.authority.acquire(self._brief().brief_id, "owner")
        self.token = CancellationToken()
        self.scope = ExecutionScope.borrowed(self.authority, self.grant, self.token)

    def _brief(self):
        return self.brief

    def _scoped(self, author, reviewer):
        return self._pipeline(reviewer, implementer=author, scope=self.scope,
            checkpoint_store=PipelineCheckpointStore(self.root / "protected", self.scope),
            checkpoint_context="a" * 64)

    def _depose(self):
        self.now[0] += 11
        self.authority.sweep()
        return self.authority.acquire(self._brief().brief_id, "replacement")

    def test_successful_implementation_and_rework_do_not_resolve_outer_grant(self):
        author = _Agent(on_fix=lambda cwd: (cwd / "code.py").write_text("x = 2\n"))
        reviewer = _Agent(review_answers=(_FAIL_REVIEW, _PASS_REVIEW))
        pipeline = self._scoped(author, reviewer)
        with (patch.object(author, "run", wraps=author.run) as implementation,
              patch.object(reviewer, "run", wraps=reviewer.run) as review):
            result = pipeline.run_brief(self._brief())
        assert result.status.value == "COMPLETED"
        assert implementation.call_count == review.call_count == 2
        assert all(call.kwargs["cancellation_token"] is self.token
                   for call in (*implementation.call_args_list, *review.call_args_list))
        self.authority.assert_current(self.grant)
        assert self.authority.claims.get(self._brief().brief_id).status is ClaimStatus.ACTIVE

    def test_stale_scope_cannot_create_task_or_checkpoint(self):
        author, reviewer = _Agent(), _Agent()
        pipeline = self._scoped(author, reviewer)
        new = self._depose()
        with pytest.raises(StaleLeaseError):
            pipeline.run_brief(self._brief())
        assert not pipeline.records.exists(self._brief().brief_id)
        assert pipeline.checkpoints.load(self._brief().brief_id) is None
        assert not author.prompts and not reviewer.prompts
        assert self.token.is_cancelled()
        self.authority.assert_current(new)

    def _test_replacement(self, phase):
        author, reviewer = _Agent(), _Agent()
        pipeline = self._scoped(author, reviewer)
        runner = author if phase == "implementation" else reviewer
        original = runner.run
        before = None
        new = None
        def return_after_deposition(**kwargs):
            nonlocal before, new
            result = original(**kwargs)
            before = pipeline.checkpoints.path_for(self._brief().brief_id).read_bytes()
            new = self._depose()
            return result
        with (patch.object(runner, "run", side_effect=return_after_deposition),
              pytest.raises(StaleLeaseError)):
            pipeline.run_brief(self._brief())
        assert pipeline.checkpoints.path_for(self._brief().brief_id).read_bytes() == before
        assert pipeline.records.get(self._brief().brief_id).state == "IN_PROGRESS"
        assert self.token.is_cancelled()
        self.authority.assert_current(new)

    def test_implementation_cannot_checkpoint_after_losing_ownership(self):
        self._test_replacement("implementation")

    def test_review_cannot_checkpoint_or_report_after_losing_ownership(self):
        self._test_replacement("review")
