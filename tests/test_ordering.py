"""Cross-task ordering: which converged task lands first, and what it costs.

Two tests carry this file. `test_only_the_first_landing_keeps_its_review`
is the mechanism's real output — the review half of convergence expiring
when the base moves, which nothing said before. And
`test_ordering_cannot_save_a_semantic_conflict` is the limitation, pinned
so a future change cannot quietly claim more than paths can deliver.
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
from gnosis.kernel.integration import IntegrationOutcome, WorkIntegrator
from gnosis.kernel.ordering import (
    AttemptStatus,
    LandingCoordinator,
    LandingReason,
    ReadyTask,
    plan_landings,
)
from gnosis.kernel.verification import CommandVerifier
from gnosis.kernel.worktree import WorktreeManager

_CONVERGED = ConvergenceResult(
    outcome=ConvergenceOutcome.CONVERGED, rounds=(), gate_ledger=(), dissent=(),
    warnings=(),
)


class TestPlanning(unittest.TestCase):
    """Pure: same inputs, same plan."""

    def test_a_fresh_base_lands_first_and_keeps_its_review(self):
        plan = plan_landings("HEAD1", [
            ReadyTask("STALE", "OLD", ("a.py",), converged_at=1.0),
            ReadyTask("FRESH", "HEAD1", ("b.py",), converged_at=2.0),
        ])
        self.assertEqual([p.task.task_id for p in plan.landings], ["FRESH", "STALE"])
        self.assertEqual(plan.first.reason, LandingReason.FRESH_BASE)
        self.assertTrue(plan.first.review_still_applies)

    def test_only_the_first_landing_keeps_its_review(self):
        # THE point of this module. A review is evidence about a specific
        # tree; the first landing moves that tree, so every later task was
        # judged against something that no longer exists. Integration
        # re-runs the VERIFICATION and re-runs nothing of the review.
        plan = plan_landings("HEAD1", [
            ReadyTask("A", "HEAD1", ("a.py",), converged_at=1.0),
            ReadyTask("B", "HEAD1", ("b.py",), converged_at=2.0),
            ReadyTask("C", "HEAD1", ("c.py",), converged_at=3.0),
        ])
        self.assertEqual([p.review_still_applies for p in plan.landings],
                         [True, False, False])
        self.assertEqual([p.task.task_id for p in plan.needing_rereview()],
                         ["B", "C"])
        self.assertEqual(plan.landings[1].reason, LandingReason.BASE_MOVED_BY_PLAN)

    def test_a_stale_base_never_keeps_its_review_even_when_alone(self):
        plan = plan_landings("HEAD2", [ReadyTask("A", "HEAD1", ("a.py",))])
        self.assertEqual(plan.first.reason, LandingReason.STALE_BASE)
        self.assertFalse(plan.first.review_still_applies)

    def test_path_overlap_is_reported_with_the_task_and_the_files(self):
        plan = plan_landings("HEAD1", [
            ReadyTask("A", "HEAD1", ("lib.py", "app.py"), converged_at=1.0),
            ReadyTask("B", "HEAD1", ("lib.py", "extra.py"), converged_at=2.0),
        ])
        second = plan.landings[1]
        self.assertEqual(second.reason, LandingReason.PATH_OVERLAP)
        self.assertEqual(second.overlaps_with, ("A",))
        self.assertEqual(second.shared_paths, ("lib.py",))

    def test_the_plan_is_fifo_among_equals_and_deterministic(self):
        # Ordering by "smallest diff" or "fewest conflicts" would starve
        # large or unlucky tasks; nothing here has evidence for that.
        tasks = [
            ReadyTask("Z", "HEAD1", ("z.py",) * 1, converged_at=1.0),
            ReadyTask("A", "HEAD1", tuple(f"a{i}.py" for i in range(20)),
                      converged_at=2.0),
        ]
        first = plan_landings("HEAD1", tasks)
        second = plan_landings("HEAD1", list(reversed(tasks)))
        self.assertEqual([p.task.task_id for p in first.landings], ["Z", "A"])
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_ties_break_on_task_id_so_two_planners_agree(self):
        plan = plan_landings("HEAD1", [
            ReadyTask("B", "HEAD1", ("b.py",), converged_at=1.0),
            ReadyTask("A", "HEAD1", ("a.py",), converged_at=1.0),
        ])
        self.assertEqual([p.task.task_id for p in plan.landings], ["A", "B"])

    def test_a_nan_timestamp_is_refused_so_the_plan_stays_recomputable(self):
        # NaN compares neither less nor greater, so a stable sort would
        # let INPUT ORDER decide the plan (independent review).
        with self.assertRaises(ValueError):
            ReadyTask("A", "HEAD1", ("a.py",), converged_at=float("nan"))
        with self.assertRaises(TypeError):
            ReadyTask("A", "HEAD1", ("a.py",), converged_at=True)

    def test_a_duplicate_task_id_is_planned_once(self):
        # A duplicate planned as two entries reported a task overlapping
        # ITSELF and could integrate it twice in one pass.
        task = ReadyTask("T", "HEAD1", ("x.py",))
        plan = plan_landings("HEAD1", [task, task])
        self.assertEqual(len(plan.landings), 1)
        self.assertEqual(plan.first.overlaps_with, ())

    def test_every_applicable_reason_is_reported_not_just_the_headline(self):
        # A task can be BOTH path-overlapping and stale-based; showing
        # only PATH_OVERLAP let an operator read a merge-risk signal where
        # there was also a review-evidence failure.
        plan = plan_landings("HEAD2", [
            ReadyTask("A", "HEAD2", ("lib.py",), converged_at=1.0),
            ReadyTask("B", "HEAD1", ("lib.py",), converged_at=2.0),
        ])
        second = plan.landings[1]
        self.assertEqual(second.reason, LandingReason.PATH_OVERLAP)
        self.assertIn(LandingReason.STALE_BASE, second.reasons)
        self.assertIn(LandingReason.BASE_MOVED_BY_PLAN, second.reasons)

    def test_an_empty_batch_plans_nothing(self):
        plan = plan_landings("HEAD1", [])
        self.assertEqual(plan.landings, ())
        self.assertIsNone(plan.first)


class TestCoordination(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self._git("init")
        self._git("config", "user.email", "e@x.com")
        self._git("config", "user.name", "T")
        (self.repo / "lib.py").write_text("def greet():\n    return 'hi'\n",
                                          encoding="utf-8")
        (self.repo / "app.py").write_text(
            "from lib import greet\n\n\ndef main():\n    return greet()\n",
            encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", "init")

        self.worktrees = WorktreeManager(self.repo, self.root / "worktrees")
        self.integrator = WorkIntegrator(
            source_repo=self.repo, worktrees=self.worktrees,
            verifier=CommandVerifier("import-check", [
                sys.executable, "-c",
                ("import importlib, pathlib; "
                 "[importlib.import_module(p.stem) "
                 " for p in sorted(pathlib.Path('.').glob('*.py'))]"),
            ]),
            integration_root=self.root / "integration",
        )
        self.coordinator = LandingCoordinator(self.integrator)

    def tearDown(self):
        self.tmp.cleanup()

    def _git(self, *args):
        return subprocess.run(["git", *args], cwd=str(self.repo),
                              capture_output=True, text=True, check=False)

    def _head(self) -> str:
        return self._git("rev-parse", "HEAD").stdout.strip()

    def _work(self, task_id: str, write: dict[str, str]) -> None:
        handle = self.worktrees.create(task_id)
        for name, content in write.items():
            (Path(handle.path) / name).write_text(content, encoding="utf-8")

    def test_preview_reads_the_facts_without_touching_anything(self):
        self._work("TASK-A", {"new.py": "A = 1\n"})
        self._git("-C", str(self.worktrees.load_handle("TASK-A").path),
                  "add", "-A")
        before = self._head()
        base, changed = self.integrator.preview("TASK-A")
        self.assertEqual(base, before)
        self.assertEqual(self._head(), before)
        self.assertEqual(self.integrator.preview("TASK-A"), (base, changed))

    def test_preview_sees_uncommitted_work_because_that_is_what_lands(self):
        # Agents leave work UNCOMMITTED and `integrate` autosaves it, so a
        # preview of the committed diff reported nothing at all for a
        # freshly worked task — and the planner then saw no paths and
        # therefore no overlap. Verified before shipping: two tasks both
        # rewriting `lib.py` planned as disjoint.
        self._work("TASK-A", {"lib.py": "def greet():\n    return 'A'\n"})
        self._work("TASK-B", {"lib.py": "def greet():\n    return 'B'\n"})

        plan = self.coordinator.plan(self._head(), ["TASK-A", "TASK-B"])
        second = plan.landings[1]
        self.assertEqual(second.reason, LandingReason.PATH_OVERLAP)
        self.assertEqual(second.shared_paths, ("lib.py",))

    def test_preview_reads_paths_with_accents(self):
        # Same reason `content_fingerprint` needs `-z`: a planner that
        # cannot read a filename cannot reason about overlap on it.
        self._work("TASK-A", {"café.py": "VALUE = 1\n"})
        _, changed = self.integrator.preview("TASK-A")
        self.assertIn("café.py", changed)

    def test_the_coordinator_lands_one_and_stops(self):
        # Once one task lands, every remaining plan entry was computed
        # against a head that no longer exists. Continuing down a stale
        # plan would be planning theatre.
        for task_id, name in (("TASK-A", "a.py"), ("TASK-B", "b.py")):
            self._work(task_id, {name: f"VALUE = '{task_id}'\n"})

        plan = self.coordinator.plan(self._head(), ["TASK-A", "TASK-B"])
        results = self.coordinator.land(
            plan, {"TASK-A": _CONVERGED, "TASK-B": _CONVERGED})

        by_task = {a.planned.task.task_id: a for a in results}
        self.assertEqual(by_task["TASK-A"].status, AttemptStatus.LANDED)
        # Every entry gets a record, including the ones never tried: a
        # caller must be able to tell a refusal from a stop. B is BOTH —
        # never reached, and holding a review that no longer applies —
        # and both facts survive on the record.
        self.assertEqual(by_task["TASK-B"].status, AttemptStatus.NOT_ATTEMPTED)
        self.assertFalse(by_task["TASK-B"].planned.review_still_applies)
        self.assertIsNone(by_task["TASK-B"].result)
        self.assertEqual(len(results), len(plan.landings))

    def _stale_task(self, task_id: str = "TASK-A") -> None:
        """Fork a task, then move the branch — the real staleness case."""
        self._work(task_id, {"a.py": "A = 1" + chr(10)})
        (self.repo / "unrelated.py").write_text("U = 1" + chr(10), encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", "the branch moved on")

    def test_a_stale_review_is_refused_rather_than_quietly_landed(self):
        # Landing it anyway would keep the verification half of
        # convergence and silently drop the review half.
        self._stale_task()
        plan = self.coordinator.plan(self._head(), ["TASK-A"])
        self.assertEqual(plan.first.reason, LandingReason.STALE_BASE)
        self.assertFalse(plan.first.review_still_applies)

        before = self._head()
        results = self.coordinator.land(plan, {"TASK-A": _CONVERGED})
        self.assertEqual(results[0].status, AttemptStatus.SKIPPED_STALE_REVIEW)
        self.assertIsNone(results[0].result)
        self.assertEqual(self._head(), before)

    def test_an_operator_can_authorise_one_re_reviewed_task(self):
        self._stale_task()
        plan = self.coordinator.plan(self._head(), ["TASK-A"])
        permissive = LandingCoordinator(
            self.integrator, stale_review_authorised={"TASK-A"})
        results = permissive.land(plan, {"TASK-A": _CONVERGED})
        self.assertEqual(results[0].status, AttemptStatus.LANDED)
        self.assertTrue(results[0].result.integrated, results[0].result.reason)

    def test_authorising_one_task_does_not_authorise_another(self):
        self._stale_task("TASK-A")
        plan = self.coordinator.plan(self._head(), ["TASK-A"])
        # Authority names TASK-B; TASK-A is the one being planned.
        coordinator = LandingCoordinator(
            self.integrator, stale_review_authorised={"TASK-B"})
        before = self._head()
        results = coordinator.land(plan, {"TASK-A": _CONVERGED})
        self.assertEqual(results[0].status, AttemptStatus.SKIPPED_STALE_REVIEW)
        self.assertEqual(self._head(), before)

    def test_a_plan_computed_against_a_moved_head_is_refused_wholesale(self):
        # Every `review_still_applies=True` in a stale plan is about a
        # tree that no longer exists.
        self._work("TASK-A", {"a.py": "A = 1" + chr(10)})
        plan = self.coordinator.plan(self._head(), ["TASK-A"])
        self.assertTrue(plan.first.review_still_applies)

        # Someone else advances the branch after the plan was made.
        (self.repo / "unrelated.py").write_text("U = 1" + chr(10), encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-m", "moved on")
        before = self._head()

        results = self.coordinator.land(plan, {"TASK-A": _CONVERGED})
        self.assertEqual(results[0].status, AttemptStatus.PLAN_SUPERSEDED)
        self.assertEqual(self._head(), before)

    def test_ordering_cannot_save_a_semantic_conflict(self):
        """The limitation, pinned.

        ADR-0018's headline failure is two tasks with DISJOINT paths whose
        merge is textually clean and semantically broken. The planner sees
        no overlap, orders them happily, and post-merge verification stays
        the only thing that decides. A future change must not quietly
        claim that ordering prevents this.
        """
        self._work("TASK-A", {
            "lib.py": "def salute():\n    return 'hi'\n",
            "app.py": "from lib import salute\n\n\ndef main():\n    return salute()\n",
        })
        self._work("TASK-B", {
            "extra.py": "from lib import greet\n\n\ndef shout():\n    return greet()\n",
        })

        plan = self.coordinator.plan(self._head(), ["TASK-A", "TASK-B"])
        # No overlap is reported, because there is none.
        self.assertEqual(plan.landings[1].shared_paths, ())
        self.assertNotEqual(plan.landings[1].reason, LandingReason.PATH_OVERLAP)

        # A lands. B, re-reviewed or not, is caught only by the merge.
        permissive = LandingCoordinator(
            self.integrator, stale_review_authorised={"TASK-A", "TASK-B"})
        results = permissive.land(plan, {"TASK-A": _CONVERGED, "TASK-B": _CONVERGED})
        self.assertEqual(results[0].status, AttemptStatus.LANDED)

        second = self.integrator.integrate("TASK-B", _CONVERGED)
        self.assertEqual(second.outcome, IntegrationOutcome.VERIFICATION_FAILED)
        self.assertEqual(second.conflicts, ())


if __name__ == "__main__":
    unittest.main()
