from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_integration import _CONVERGED, _IntegrationTestCase
from test_pipeline import _Agent, _PipelineTestCase

from gnosis.kernel.claims import ClaimStore, StaleClaimError, WorkAuthority
from gnosis.kernel.execution_scope import ExecutionScope
from gnosis.kernel.integration import IntegrationOutcome, WorkIntegrator
from gnosis.kernel.lease import LeaseStore, StaleLeaseError
from gnosis.kernel.subject import observe_subject
from gnosis.kernel.verification import VerificationResult
from gnosis.runner.claude_cli_runner import CancellationToken


class TestPreparedIntegration(_IntegrationTestCase):
    def test_deposition_after_final_guard_cannot_advance_target(self):
        prepared = self._prepare()
        authority = WorkAuthority(ClaimStore(self.root / "claims"),
                                  LeaseStore(self.root / "leases"), default_ttl_s=120)
        grant = authority.acquire("brief", "old")
        resumer = self._resumer()
        resumer.scope = ExecutionScope.borrowed(authority, grant, CancellationToken())
        before = self._head()
        ready = [False]
        original_guard = resumer._guard

        def allow(*args):
            ready[0] = True

        def check_then_replace():
            original_guard()
            if ready[0]:
                ready[0] = False
                authority.release(grant)
                authority.acquire("brief", "new")

        with (patch.object(resumer, "_gate", side_effect=allow),
              patch.object(resumer, "_guard", side_effect=check_then_replace),
              pytest.raises(StaleClaimError)):
            resumer.resume_prepared(prepared)
        assert self._head() == before
        assert resumer.scope.cancellation.is_cancelled()

    def _prepare(self):
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'changed'\n"})
        receipts = []
        def crash(prepared):
            receipts.append(prepared)
            raise SystemExit("controller died after prepared receipt")
        self.integrator.on_prepared = crash
        original_head = self._head()
        with pytest.raises(SystemExit):
            self.integrator.integrate("TASK-A", _CONVERGED)
        assert self._head() == original_head
        assert len(receipts) == 1
        return receipts[0]

    def _resumer(self):
        return WorkIntegrator(self.repo, self.worktrees, self._verifier(),
                              integration_root=self.root / "integration")

    def test_saved_merge_survives_cleanup_and_resumes_without_reverification(self):
        prepared = self._prepare()
        assert self._git("cat-file", "-e", prepared.merged_sha).returncode == 0
        resumer = self._resumer()
        with patch.object(resumer.verifier, "run", side_effect=AssertionError("already verified")):
            result = resumer.resume_prepared(prepared)
        assert result.outcome is IntegrationOutcome.INTEGRATED
        assert self._head() == prepared.merged_sha
        assert (self.repo / "lib.py").read_text() == "def greet():\n    return 'changed'\n"

    def test_restart_after_advance_recognizes_actual_commit_not_a_status_flag(self):
        prepared = self._prepare()
        self._git("merge", "--ff-only", prepared.merged_sha)
        resumer = self._resumer()
        with patch.object(resumer, "_gate", side_effect=AssertionError("must not advance again")):
            result = resumer.resume_prepared(prepared)
        assert result.integrated
        assert result.merged_sha == self._head()

    def test_changed_human_checkout_is_preserved(self):
        prepared = self._prepare()
        (self.repo / "lib.py").write_text("human edit\n")
        result = self._resumer().resume_prepared(prepared)
        assert not result.integrated
        assert result.reason == "integration_target_changed_after_preparation"
        assert self._head() == prepared.base_sha
        assert (self.repo / "lib.py").read_text() == "human edit\n"

    def test_changed_task_branch_does_not_borrow_old_merge_receipt(self):
        prepared = self._prepare()
        handle = self.worktrees.load_handle("TASK-A")
        (Path(handle.path) / "new.txt").write_text("later work")
        self.worktrees.autosave(handle, reason="later")
        result = self._resumer().resume_prepared(prepared)
        assert not result.integrated
        assert result.reason == "task_branch_moved_after_preparation"
        assert self._head() == prepared.base_sha

    def test_malformed_verification_cannot_be_recovered_as_an_advance(self):
        prepared = self._prepare()
        bad = replace(prepared, verification=VerificationResult("bad", 1, 0, 0.0, "", ""))
        result = self._resumer().resume_prepared(bad)
        assert not result.integrated
        assert self._head() == prepared.base_sha

    def test_branch_change_after_policy_cannot_add_unapproved_files_to_merge(self):
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'changed'\n"})
        before = self._head()
        original = self.integrator._merge_and_verify
        def mutate_then_merge(*args, **kwargs):
            handle = self.worktrees.load_handle("TASK-A")
            (Path(handle.path) / "unapproved.txt").write_text("after policy snapshot")
            self.worktrees.autosave(handle, reason="concurrent writer")
            return original(*args, **kwargs)
        with patch.object(self.integrator, "_merge_and_verify", side_effect=mutate_then_merge):
            result = self.integrator.integrate("TASK-A", _CONVERGED)
        assert not result.integrated
        assert result.reason == "task_branch_moved_after_preparation"
        assert self._head() == before
        assert not (self.repo / "unapproved.txt").exists()

    def test_deposition_during_verification_prevents_shared_branch_advance(self):
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'changed'\n"})
        before = self._head()
        current = [True]
        def assert_current():
            if not current[0]:
                raise StaleLeaseError("replaced")
        token = CancellationToken()
        self.integrator.scope = ExecutionScope(assert_current, token, 1, "old")
        original = self.integrator.verifier.run
        def verify_then_depose(path):
            result = original(path)
            current[0] = False
            return result
        with (patch.object(self.integrator.verifier, "run", side_effect=verify_then_depose),
              pytest.raises(StaleLeaseError)):
            self.integrator.integrate("TASK-A", _CONVERGED)
        assert self._head() == before
        assert token.is_cancelled()


class TestCommitBeforeReview(_PipelineTestCase):
    def test_task_is_committed_before_review_and_integration_keeps_that_identity(self):
        author = _Agent()
        original = author.run
        def implement(**kwargs):
            (kwargs["cwd"] / "code.py").write_text("x = 2\n")
            return original(**kwargs)
        pipeline = self._pipeline(_Agent(), implementer=author,
                                  bind_review_subject=True, commit_before_review=True)
        with patch.object(author, "run", side_effect=implement):
            work = pipeline.run_brief(self._brief())
        assert work.status.value == "COMPLETED"
        source = pipeline._exec_root(work.task_id)
        subject = observe_subject(source)
        assert work.convergence.rounds[-1].subject == subject
        integrator = WorkIntegrator(self.repo, self.worktrees, self._verifier())
        result = integrator.integrate(work.task_id, work.convergence)
        assert result.integrated, result.reason
        assert observe_subject(source) == subject
        assert (self.repo / "code.py").read_text() == "x = 2\n"

    def test_mutation_after_review_is_refused_before_autosave(self):
        pipeline = self._pipeline(_Agent(), bind_review_subject=True, commit_before_review=True)
        work = pipeline.run_brief(self._brief())
        source = pipeline._exec_root(work.task_id)
        before = observe_subject(source)
        (source / "code.py").write_text("not reviewed\n")
        integrator = WorkIntegrator(self.repo, self.worktrees, self._verifier())
        autosave = Mock(wraps=self.worktrees.autosave)
        with patch.object(self.worktrees, "autosave", autosave):
            result = integrator.integrate(work.task_id, work.convergence)
        assert not result.integrated
        autosave.assert_not_called()
        assert observe_subject(source).head_sha == before.head_sha
        assert (source / "code.py").read_text() == "not reviewed\n"
