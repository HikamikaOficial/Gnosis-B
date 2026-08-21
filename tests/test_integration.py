"""Integration of results: landing reviewed work on the shared branch.

The test that justifies this module is
`test_a_clean_merge_that_breaks_the_tree_does_not_land`. Everything else
guards the arrangement around it.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gnosis.kernel.convergence import (
    ConvergenceOutcome,
    ConvergenceResult,
)
from gnosis.kernel.integration import (
    CHECKPOINT_REF_PREFIX,
    IntegrationOutcome,
    WorkIntegrator,
    integration_branches,
)
from gnosis.kernel.verification import CommandVerifier
from gnosis.kernel.worktree import WorktreeManager

_CONVERGED = ConvergenceResult(
    outcome=ConvergenceOutcome.CONVERGED, rounds=(), gate_ledger=(), dissent=(),
    warnings=(),
)
_NOT_CONVERGED = ConvergenceResult(
    outcome=ConvergenceOutcome.ROUNDS_EXHAUSTED, rounds=(), gate_ledger=(),
    dissent=(), warnings=(),
)


class _IntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self._git("init")
        self._git("config", "user.email", "e@x.com")
        self._git("config", "user.name", "T")
        # A tiny program plus a check that imports and runs it. The check
        # is what makes a semantic break observable.
        (self.repo / "lib.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
        (self.repo / "app.py").write_text(
            "from lib import greet\n\n\ndef main():\n    return greet()\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", "init")

        self.worktrees = WorktreeManager(self.repo, self.root / "worktrees")
        self.integrator = WorkIntegrator(
            source_repo=self.repo, worktrees=self.worktrees,
            verifier=self._verifier(),
            integration_root=self.root / "integration",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=str(cwd or self.repo),
                              capture_output=True, text=True, check=False)

    def _verifier(self):
        # Imports EVERY module in the tree. A check that only imports what
        # it already knows about cannot see a module a concurrent task
        # added — and that is exactly the semantic break being hunted.
        return CommandVerifier(
            "import-check",
            [sys.executable, "-c",
             ("import importlib, pathlib; "
              "[importlib.import_module(p.stem) "
              " for p in sorted(pathlib.Path('.').glob('*.py'))]")],
        )

    def _head(self) -> str:
        return self._git("rev-parse", "HEAD").stdout.strip()

    def _work(self, task_id: str, write: dict[str, str]) -> Path:
        """Mint a task worktree and leave uncommitted work in it, the way
        an agent does."""
        handle = self.worktrees.create(task_id)
        path = Path(handle.path)
        for name, content in write.items():
            (path / name).write_text(content, encoding="utf-8")
        return path


class TestSemanticIntegration(_IntegrationTestCase):
    def test_a_clean_merge_that_breaks_the_tree_does_not_land(self):
        """Rule 16, demonstrated rather than asserted.

        Task A renames `greet` to `salute` and updates its own caller.
        Task B adds a NEW caller of `greet`. The two touch different
        regions, git merges them without a single conflict, and the
        merged tree raises ImportError.
        """
        # BOTH fork from the SAME base, which is the only situation where
        # this can arise: two briefs running concurrently, each reviewed
        # against a tree that did not yet contain the other's work.
        self._work("TASK-A", {
            "lib.py": "def salute():\n    return 'hi'\n",
            "app.py": "from lib import salute\n\n\ndef main():\n    return salute()\n",
        })
        self._work("TASK-B", {
            "extra.py": "from lib import greet\n\n\ndef shout():\n    return greet().upper()\n",
        })

        first = self.integrator.integrate("TASK-A", _CONVERGED)
        self.assertEqual(first.outcome, IntegrationOutcome.INTEGRATED, first.reason)
        before = self._head()
        # Waived deliberately: this test isolates what the MERGE and the
        # post-merge verification do. B's review is genuinely stale now
        # that A has landed, and the stale-review gate fires first — which
        # `test_a_stale_review_is_caught_before_the_merge_is_attempted`
        # asserts separately.
        second = self.integrator.integrate("TASK-B", _CONVERGED,
                                           waive_stale_review=True)

        # Git had no complaint...
        self.assertEqual(second.conflicts, ())
        self.assertIsNotNone(second.merged_sha)
        # ...and the tree it produced does not work, so it did not land.
        self.assertEqual(second.outcome, IntegrationOutcome.VERIFICATION_FAILED)
        self.assertFalse(second.verification.passed)
        self.assertEqual(self._head(), before, "the shared branch must not have moved")

    def test_a_textual_conflict_is_typed_and_names_its_paths(self):
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'A'\n"})
        self._work("TASK-B", {"lib.py": "def greet():\n    return 'B'\n"})
        self.assertEqual(
            self.integrator.integrate("TASK-A", _CONVERGED).outcome,
            IntegrationOutcome.INTEGRATED)

        result = self.integrator.integrate("TASK-B", _CONVERGED,
                                           waive_stale_review=True)

        self.assertEqual(result.outcome, IntegrationOutcome.MERGE_CONFLICT)
        self.assertIn("lib.py", result.conflicts)
        # "merge failed" is not actionable; the paths are.
        self.assertTrue(result.conflicts)

    def test_a_stale_review_is_caught_before_the_merge_is_attempted(self):
        # Staleness is DERIVED by the integrator, not asserted by the
        # caller: the first version took `require_rereview` as a parameter
        # defaulting to False, so the public API's default landed an
        # expired review in silence (independent review).
        self._work("TASK-A", {"a.py": "A = 1" + chr(10)})
        self._work("TASK-B", {"b.py": "B = 2" + chr(10)})
        self.assertTrue(self.integrator.integrate("TASK-A", _CONVERGED).integrated)

        before = self._head()
        result = self.integrator.integrate("TASK-B", _CONVERGED)
        self.assertEqual(result.outcome, IntegrationOutcome.REVIEW_STALE)
        self.assertIsNone(result.merged_sha)          # no merge was attempted
        self.assertEqual(self._head(), before)

    def test_a_failed_merge_leaves_no_staging_worktree_behind(self):
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'A'\n"})
        self._work("TASK-B", {"lib.py": "def greet():\n    return 'B'\n"})
        self.integrator.integrate("TASK-A", _CONVERGED)
        self.integrator.integrate("TASK-B", _CONVERGED)

        leftovers = list((self.root / "integration").glob("merge-*"))
        self.assertEqual(leftovers, [], leftovers)
        registered = self._git("worktree", "list").stdout
        self.assertNotIn("merge-", registered)


class TestTheTargetOnlyMovesOnEvidence(_IntegrationTestCase):
    def test_unconverged_work_is_refused_before_anything_is_touched(self):
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'A'\n"})
        before = self._head()
        result = self.integrator.integrate("TASK-A", _NOT_CONVERGED)

        self.assertEqual(result.outcome, IntegrationOutcome.NOT_CONVERGED)
        self.assertEqual(self._head(), before)
        self.assertIsNone(result.merged_sha)

    def test_no_convergence_result_at_all_is_refused(self):
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'A'\n"})
        self.assertEqual(
            self.integrator.integrate("TASK-A", None).outcome,
            IntegrationOutcome.NOT_CONVERGED)

    def test_a_dirty_source_repo_is_refused(self):
        # Merging into a dirty checkout mixes uncommitted human work with
        # agent work, and rollback could not tell them apart.
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'A'\n"})
        (self.repo / "human-wip.txt").write_text("mine\n", encoding="utf-8")
        result = self.integrator.integrate("TASK-A", _CONVERGED)
        self.assertEqual(result.outcome, IntegrationOutcome.SOURCE_DIRTY)
        self.assertTrue((self.repo / "human-wip.txt").exists())

    def test_a_task_that_changed_nothing_is_not_integrated(self):
        self.worktrees.create("TASK-EMPTY")
        result = self.integrator.integrate("TASK-EMPTY", _CONVERGED)
        self.assertEqual(result.outcome, IntegrationOutcome.NOTHING_TO_INTEGRATE)

    def test_a_missing_worktree_is_an_error_not_a_silent_pass(self):
        result = self.integrator.integrate("TASK-ABSENT", _CONVERGED)
        self.assertEqual(result.outcome, IntegrationOutcome.INTEGRATION_ERROR)
        self.assertIn("worktree_unavailable", result.reason)


class TestProvenanceAndRollback(_IntegrationTestCase):
    def test_a_checkpoint_names_the_pre_integration_state(self):
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'A'\n"})
        before = self._head()
        result = self.integrator.integrate("TASK-A", _CONVERGED)

        # The base sha is in the ref: re-integrating the same task id must
        # not overwrite an earlier rollback point and send an operator's
        # `reset --hard` to the wrong commit (Codex review).
        self.assertEqual(result.checkpoint_ref, f"{CHECKPOINT_REF_PREFIX}TASK-A/{before}")
        resolved = self._git("rev-parse", result.checkpoint_ref).stdout.strip()
        self.assertEqual(resolved, before)
        # Rollback is a named ref, not a sha an operator reconstructs.
        self.assertIn(result.checkpoint_ref, self.integrator.rollback_command(result))

    def test_re_integrating_a_task_id_does_not_clobber_its_earlier_checkpoint(self):
        self._work("TASK-A", {"one.py": "A = 1\n"})
        first = self.integrator.integrate("TASK-A", _CONVERGED)
        self.assertTrue(first.integrated, first.reason)
        first_base = self._git("rev-parse", first.checkpoint_ref).stdout.strip()

        # The same task id, a second time, from the new base.
        self.worktrees.remove(self.worktrees.load_handle("TASK-A"), delete_branch=True)
        self._work("TASK-A", {"two.py": "B = 2\n"})
        second = self.integrator.integrate("TASK-A", _CONVERGED)
        self.assertTrue(second.integrated, second.reason)

        self.assertNotEqual(first.checkpoint_ref, second.checkpoint_ref)
        # The first rollback point still resolves to what it always did.
        self.assertEqual(
            self._git("rev-parse", first.checkpoint_ref).stdout.strip(), first_base)

    def test_the_kernel_does_not_run_the_rollback_itself(self):
        # Undoing an integration is an irreversible act on shared state.
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'A'\n"})
        result = self.integrator.integrate("TASK-A", _CONVERGED)
        after = self._head()
        self.assertIsNotNone(self.integrator.rollback_command(result))
        self.assertEqual(self._head(), after)   # nothing was reset for us

    def test_changed_paths_are_recorded_for_ownership_analysis(self):
        # Rule 15: a worktree is not a conflict solution, so the signal a
        # future scheduler needs is which paths a task claims.
        self._work("TASK-A", {
            "lib.py": "def greet():\n    return 'A'\n",
            "new.py": "VALUE = 1\n",
        })
        result = self.integrator.integrate("TASK-A", _CONVERGED)
        self.assertEqual(set(result.changed_paths), {"lib.py", "new.py"})

    def test_integrated_work_is_actually_present_afterwards(self):
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'INTEGRATED'\n"})
        result = self.integrator.integrate("TASK-A", _CONVERGED)
        self.assertTrue(result.integrated, result.reason)
        self.assertIn("INTEGRATED", (self.repo / "lib.py").read_text(encoding="utf-8"))
        self.assertEqual(self._head(), result.merged_sha)

    def test_kernel_branches_are_visible_to_an_operator(self):
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'A'\n"})
        self.assertIn("gnosis/TASK-A", integration_branches(self.repo))


class TestTheTargetIsNamed(_IntegrationTestCase):
    """Integration used to advance whatever the repo had checked out."""

    def test_a_detached_head_is_refused(self):
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'A'\n"})
        integrator = WorkIntegrator(
            source_repo=self.repo, worktrees=self.worktrees,
            verifier=self._verifier(), target_branch="master",
            integration_root=self.root / "integration",
        )
        self._git("checkout", "--detach", "HEAD")
        result = integrator.integrate("TASK-A", _CONVERGED)
        self.assertEqual(result.outcome, IntegrationOutcome.WRONG_TARGET)

    def test_an_unrelated_checked_out_branch_is_refused(self):
        # Landing on an operator's feature branch while reporting that the
        # shared branch moved is the failure being prevented.
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'A'\n"})
        target = self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        integrator = WorkIntegrator(
            source_repo=self.repo, worktrees=self.worktrees,
            verifier=self._verifier(), target_branch=target,
            integration_root=self.root / "integration",
        )
        self._git("checkout", "-b", "someones-feature")
        before = self._head()
        result = integrator.integrate("TASK-A", _CONVERGED)

        self.assertEqual(result.outcome, IntegrationOutcome.WRONG_TARGET)
        self.assertIn(target, result.reason)
        self.assertEqual(self._head(), before)


class TestTheGateSeesTheRealChangeSet(_IntegrationTestCase):
    def test_policy_is_asked_about_uncommitted_work_too(self):
        # The snapshot used to be taken BEFORE autosave, so it described
        # only what was already committed while autosave then committed
        # the agent's uncommitted files as well — a rule allowing one path
        # could authorise landing another (Codex review).
        from gnosis.kernel.integration import INTEGRATION_INTERVENTION_POINT
        from gnosis.kernel.policy import (
            InterventionPoint,
            PolicyEngine,
            RuleOutcome,
            Verdict,
        )
        seen: list[list[str]] = []

        def capture(snapshot):
            seen.append(list(snapshot.payload["changed_paths"]))
            return RuleOutcome(Verdict.ALLOW, "ok:seen")

        policy = PolicyEngine([InterventionPoint(
            name=INTEGRATION_INTERVENTION_POINT,
            declared_tools=frozenset({"git_merge"}),
            rules=(("rule", capture),), requires_intent=True,
        )])
        integrator = WorkIntegrator(
            source_repo=self.repo, worktrees=self.worktrees,
            verifier=self._verifier(),
            integration_root=self.root / "integration", policy=policy,
        )
        # Uncommitted, exactly as an agent leaves it.
        self._work("TASK-A", {"restricted.py": "SECRET = 1\n"})
        integrator.integrate("TASK-A", _CONVERGED)
        self.assertEqual(seen, [["restricted.py"]])

    def test_a_denied_integration_never_moves_the_branch(self):
        from gnosis.kernel.integration import INTEGRATION_INTERVENTION_POINT
        from gnosis.kernel.policy import (
            InterventionPoint,
            PolicyEngine,
            RuleOutcome,
            Verdict,
        )
        policy = PolicyEngine([InterventionPoint(
            name=INTEGRATION_INTERVENTION_POINT,
            declared_tools=frozenset({"git_merge"}),
            rules=(("no", lambda s: RuleOutcome(Verdict.DENY, "security:frozen")),),
            requires_intent=True,
        )])
        integrator = WorkIntegrator(
            source_repo=self.repo, worktrees=self.worktrees,
            verifier=self._verifier(),
            integration_root=self.root / "integration", policy=policy,
        )
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'A'\n"})
        before = self._head()
        result = integrator.integrate("TASK-A", _CONVERGED)

        self.assertEqual(result.outcome, IntegrationOutcome.REFUSED_BY_POLICY)
        self.assertEqual(result.reason, "security:frozen")
        self.assertEqual(self._head(), before)


class TestCrashRecovery(_IntegrationTestCase):
    def test_a_staging_worktree_left_by_a_crash_is_swept(self):
        # The `finally` only runs on a normal unwind; a kill during
        # verification leaves the worktree registered forever.
        stranded = self.root / "integration" / "merge-TASK-CRASHED-deadbeef"
        stranded.parent.mkdir(parents=True, exist_ok=True)
        self._git("worktree", "add", "--detach", str(stranded), self._head())
        self.assertIn("merge-TASK-CRASHED", self._git("worktree", "list").stdout)

        self._work("TASK-A", {"lib.py": "def greet():\n    return 'A'\n"})
        self.integrator.integrate("TASK-A", _CONVERGED)

        self.assertNotIn("merge-TASK-CRASHED", self._git("worktree", "list").stdout)
        self.assertFalse(stranded.exists())


class TestDestructionIsProvenanceGated(_IntegrationTestCase):
    def test_the_lock_is_anchored_to_the_repo_not_to_a_configured_directory(self):
        # Two integrators pointed at the same repo with different
        # integration roots would otherwise take two different locks and
        # serialize nothing — which is the case rules 15 and 16 are about.
        other = WorkIntegrator(
            source_repo=self.repo, worktrees=self.worktrees,
            verifier=self._verifier(),
            integration_root=self.root / "somewhere-else",
        )
        self.assertEqual(self.integrator._lock_path(), other._lock_path())
        self.assertIn(".git", str(self.integrator._lock_path()))

    def test_a_path_it_did_not_mint_is_never_force_removed(self):
        # Rule 27 bans forced destruction as a shortcut. The staging
        # worktree is disposable BECAUSE the kernel created it; a path
        # that fails that provenance check is left alone.
        outsider = self.root / "not-ours"
        outsider.mkdir()
        (outsider / "precious.txt").write_text("keep me\n", encoding="utf-8")

        self.integrator._discard(outsider)
        self.assertTrue((outsider / "precious.txt").exists())

        # And one inside the root but without the minted prefix.
        (self.root / "integration").mkdir(parents=True, exist_ok=True)
        stray = self.root / "integration" / "human-notes"
        stray.mkdir()
        (stray / "notes.txt").write_text("mine\n", encoding="utf-8")
        self.integrator._discard(stray)
        self.assertTrue((stray / "notes.txt").exists())


class TestSerialisation(_IntegrationTestCase):
    def test_two_integrations_in_sequence_each_verify_against_the_new_base(self):
        # The second merge must be computed against what the first landed,
        # not against the base it forked from.
        self._work("TASK-A", {"new_a.py": "A = 1\n"})
        self.assertTrue(self.integrator.integrate("TASK-A", _CONVERGED).integrated)
        landed_a = self._head()

        self._work("TASK-B", {"new_b.py": "B = 2\n"})
        second = self.integrator.integrate("TASK-B", _CONVERGED)

        self.assertTrue(second.integrated, second.reason)
        self.assertEqual(second.base_sha, landed_a)
        self.assertTrue((self.repo / "new_a.py").exists())
        self.assertTrue((self.repo / "new_b.py").exists())


class TestRereviewIsEvidence(_IntegrationTestCase):
    """L-0027: a review expires when its tree moves. Until now the only
    way past was an operator authorising a task id — a DECISION, not a
    verdict. A re-review against the merged tree is the verdict."""

    def _reviewer(self, verdict="PASS", findings=(), on_review=None):
        from gnosis.kernel.convergence import ReviewReport, ReviewVerdict
        seen = []

        def review(tree):
            seen.append(Path(tree))
            if on_review is not None:
                on_review(Path(tree))
            return ReviewReport(verdict=ReviewVerdict(verdict),
                                findings=tuple(findings), reviewer="rev-2")
        review.seen = seen
        return review

    def _integrator(self, re_reviewer=None):
        return WorkIntegrator(
            source_repo=self.repo, worktrees=self.worktrees,
            verifier=self._verifier(),
            integration_root=self.root / "integration",
            re_reviewer=re_reviewer,
        )

    def _stale_task(self, task_id="TASK-A"):
        """Fork a task, then move the branch: its review now describes a
        tree that no longer exists."""
        self._work(task_id, {"a.py": "A = 1" + chr(10)})
        (self.repo / "moved.py").write_text("M = 1" + chr(10), encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", "the branch moved on")

    def test_a_passing_rereview_lets_stale_work_land(self):
        reviewer = self._reviewer("PASS")
        integrator = self._integrator(reviewer)
        self._stale_task()
        before = self._head()

        result = integrator.integrate("TASK-A", _CONVERGED)

        self.assertTrue(result.integrated, result.reason)
        self.assertIsNotNone(result.rereview)
        self.assertEqual(result.rereview.reviewer, "rev-2")
        self.assertNotEqual(self._head(), before)

    def test_the_rereview_judges_the_merged_tree_not_the_task_worktree(self):
        # The question a re-review answers is "is this correct in the tree
        # that will land", and the task worktree is not that tree.
        reviewer = self._reviewer("PASS")
        integrator = self._integrator(reviewer)
        self._stale_task()
        integrator.integrate("TASK-A", _CONVERGED)

        judged = reviewer.seen[0]
        self.assertNotEqual(judged, self.repo)
        self.assertNotEqual(judged, Path(self.worktrees.load_handle("TASK-A").path))
        self.assertIn("merge-", judged.name)

    def test_a_failing_rereview_stops_the_landing(self):
        reviewer = self._reviewer("FAIL")
        integrator = self._integrator(reviewer)
        self._stale_task()
        before = self._head()

        result = integrator.integrate("TASK-A", _CONVERGED)

        self.assertEqual(result.outcome, IntegrationOutcome.REVIEW_FAILED)
        self.assertEqual(self._head(), before)
        self.assertIsNotNone(result.rereview)

    def test_a_blocking_finding_stops_the_landing_even_on_a_pass(self):
        # The SAME blocking rule convergence uses. A finding that blocked
        # convergence but not landing would be a contradiction an operator
        # could only discover by experiment.
        from gnosis.kernel.convergence import Finding, Severity
        reviewer = self._reviewer("PASS", findings=[
            Finding(Severity.CRITICAL, "correctness", "still broken", "rev-2"),
        ])
        integrator = self._integrator(reviewer)
        self._stale_task()
        before = self._head()

        result = integrator.integrate("TASK-A", _CONVERGED)
        self.assertEqual(result.outcome, IntegrationOutcome.REVIEW_FAILED)
        self.assertEqual(self._head(), before)

    def test_a_non_blocking_finding_is_gated_not_lost(self):
        from gnosis.kernel.convergence import Finding, Severity
        reviewer = self._reviewer("PASS", findings=[
            Finding(Severity.INFO, "style", "naming", "rev-2"),
        ])
        integrator = self._integrator(reviewer)
        self._stale_task()

        result = integrator.integrate("TASK-A", _CONVERGED)
        self.assertTrue(result.integrated, result.reason)
        self.assertEqual(len(result.rereview_gated), 1)
        self.assertIn("below blocking set", result.rereview_gated[0].gate_reason)

    def test_a_rereviewer_that_edits_the_merged_tree_is_refused(self):
        # Rule 9 at the moment it matters most. What LANDS is the captured
        # merged_sha so the edit cannot reach the branch, but the verdict
        # is worthless and saying so is the point.
        def tamper(tree):
            (tree / "a.py").write_text("tampered by the reviewer" + chr(10),
                                       encoding="utf-8")

        reviewer = self._reviewer("PASS", on_review=tamper)
        integrator = self._integrator(reviewer)
        self._stale_task()
        before = self._head()

        result = integrator.integrate("TASK-A", _CONVERGED)
        self.assertEqual(result.outcome,
                         IntegrationOutcome.REVIEWER_MODIFIED_SUBJECT)
        self.assertEqual(self._head(), before)

    def test_a_stale_review_with_no_reviewer_refuses(self):
        integrator = self._integrator(None)
        self._stale_task()
        before = self._head()
        result = integrator.integrate("TASK-A", _CONVERGED)
        self.assertEqual(result.outcome, IntegrationOutcome.REVIEW_STALE)
        self.assertIn("no_reviewer_configured", result.reason)
        self.assertEqual(self._head(), before)

    def test_an_operator_can_still_waive_it_deliberately(self):
        integrator = self._integrator(None)
        self._stale_task()
        result = integrator.integrate("TASK-A", _CONVERGED, waive_stale_review=True)
        self.assertTrue(result.integrated, result.reason)
        self.assertIsNone(result.rereview)

    def test_a_fresh_review_is_not_re_reviewed(self):
        # Re-review is for evidence that expired, not a second opinion on
        # everything: running it always would double the cost of every
        # landing for no added evidence.
        reviewer = self._reviewer("PASS")
        integrator = self._integrator(reviewer)
        self._work("TASK-A", {"a.py": "A = 1" + chr(10)})
        result = integrator.integrate("TASK-A", _CONVERGED)
        self.assertTrue(result.integrated, result.reason)
        self.assertEqual(reviewer.seen, [])
        self.assertIsNone(result.rereview)


if __name__ == "__main__":
    unittest.main()
