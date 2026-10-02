"""Integration milestone: one brief through the whole kernel.

The defects worth hunting here are not in the parts — each has its own
suite — but in the seams: coverage that stops halfway, a status that
reports one half's opinion as the whole, and a park that turns into a
failure on the way through.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.contracts.engineer_report import ReportStatus
from gnosis.director.brief_record import BriefRecordState
from gnosis.director.pipeline import (
    FIX_STAGE,
    REVIEW_STAGE,
    GovernedPipeline,
    _status_for,
)
from gnosis.kernel.convergence import (
    ConvergenceOutcome,
    ConvergencePolicy,
    ConvergenceResult,
    RoundRecord,
)
from gnosis.kernel.credentials import (
    Credential,
    CredentialKind,
    CredentialPool,
    CredentialUnavailable,
)
from gnosis.kernel.engine import AGENT_RUN_INTERVENTION_POINT, TaskEngine
from gnosis.kernel.failures import HoldScope, RateLimitHold
from gnosis.kernel.policy import (
    ApprovalStore,
    InterventionPoint,
    PolicyEngine,
    RuleOutcome,
    Verdict,
)
from gnosis.kernel.replay import InteractionStore, ReplayMode
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.scheduler import HoldStore, TaskScheduler
from gnosis.kernel.verification import (
    CommandVerifier,
    CompositeVerifier,
    VerificationResult,
    Verifier,
)
from gnosis.kernel.worktree import WorktreeManager
from gnosis.runner.capture import ExecutionResult
from gnosis.runner.gated_runner import CredentialHeld, GatedAgentRunner
from gnosis.runner.replay_runner import ReplayingCLIRunner
from gnosis.runner.retry import RetryPolicy

_FAST_RETRY = RetryPolicy(max_attempts=1, backoff_base_s=0.01, backoff_factor=2.0, max_backoff_s=0.02)
_PASS_REVIEW = '```json\n{"verdict": "PASS", "findings": [], "notes": "clean"}\n```'
_FAIL_REVIEW = ('```json\n{"verdict": "FAIL", "findings": [{"severity": "MAJOR", '
                '"category": "correctness", "description": "off by one"}]}\n```')
_FIX_DONE = '```json\n{"claims_done": true, "notes": "fixed"}\n```'


class _Agent:
    """One fake CLI standing in for implementation, review and fix.

    Answers are chosen by what the prompt asks for, the way a real agent
    would: the pipeline is what decides which prompt goes where, and the
    test must not decide that for it.
    """

    def __init__(self, review_answers=(_PASS_REVIEW,), fix_answer=_FIX_DONE,
                 on_fix=None, implementation_exit=0):
        self.review_answers = list(review_answers)
        self.fix_answer = fix_answer
        self.on_fix = on_fix
        self.implementation_exit = implementation_exit
        self.prompts: list[str] = []
        self.reviews = 0
        self.fixes = 0

    @property
    def binary(self) -> str:
        return "claude"

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s=1800.0, **kwargs):
        self.prompts.append(prompt)
        exit_code = 0
        if "INDEPENDENT reviewer" in prompt:
            self.reviews += 1
            answer = self.review_answers[min(self.reviews, len(self.review_answers)) - 1]
        elif "fixing defects" in prompt:
            self.fixes += 1
            if self.on_fix is not None:
                self.on_fix(Path(cwd))
            answer = self.fix_answer
        else:
            exit_code = self.implementation_exit
            answer = "implemented"
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(json.dumps({"result": answer}), encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return ExecutionResult(
            command=("claude",), exit_code=exit_code, timed_out=False,
            cancelled=False, duration_s=0.1, stdout_path=str(stdout_path),
            stderr_path=str(stderr_path), started_at="t0", ended_at="t1",
            parsed_json={"result": answer},
        )


def _permissive(rule=None) -> PolicyEngine:
    return PolicyEngine([InterventionPoint(
        name=AGENT_RUN_INTERVENTION_POINT,
        declared_tools=frozenset({"claude_cli"}),
        rules=(("rule", rule or (lambda s: RuleOutcome(Verdict.ALLOW, "ok:permitted"))),),
        requires_intent=True,
    )])


class _PipelineTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        run = lambda *a: subprocess.run(["git", *a], cwd=self.repo, check=True,
                                        capture_output=True)
        run("init")
        run("config", "user.email", "e@x.com")
        run("config", "user.name", "T")
        (self.repo / "code.py").write_text("x = 1\n", encoding="utf-8")
        run("add", "-A")
        run("commit", "-m", "init")

        self.director_root = self.root / "director"
        self.run_store = RunStore(self.root / "runs")
        self.holds = HoldStore(self.root / "holds.jsonl")
        self.worktrees = WorktreeManager(self.repo, self.root / "worktrees")
        self.now = 1_000_000.0

    def tearDown(self):
        self.tmp.cleanup()

    def _verifier(self, passes=True):
        code = "import sys; sys.exit(0)" if passes else "import sys; sys.exit(1)"
        return CommandVerifier("check", [sys.executable, "-c", code])

    def _pipeline(self, agent, policy=None, verifier=None, implementer=None, **kwargs):
        # A SEPARATE implementer by default. The first version of this
        # fixture used one agent for both halves, which is precisely the
        # degenerate case rule 10 forbids — and it is why nothing noticed
        # that no code enforced independence (Codex review).
        engine = TaskEngine(run_store=self.run_store,
                            cli_runner=implementer or _Agent(),
                            retry_policy=_FAST_RETRY)
        scheduler = TaskScheduler(
            engine=engine, run_store=self.run_store, holds=self.holds,
            credential="claude://default", clock=lambda: self.now,
        )
        return GovernedPipeline(
            director_root=self.director_root, scheduler=scheduler,
            repo_path=self.repo, verifier=verifier or self._verifier(),
            policy=policy or _permissive(), review_runner=agent,
            worktrees=self.worktrees,
            convergence_policy=ConvergencePolicy(max_rounds=2),
            policy_actor="agent://worker-a", **kwargs,
        )

    def _brief(self, brief_id="BRIEF-1"):
        return DirectorBrief(brief_id=brief_id, title="Ship it",
                             mission="Make it work.", source=BriefSource.MANUAL)


class TestTheWholePath(_PipelineTestCase):
    def test_a_brief_implements_then_converges_and_reports_once(self):
        agent = _Agent()
        pipeline = self._pipeline(agent)
        outcome = pipeline.run_brief(self._brief())

        self.assertEqual(outcome.status, ReportStatus.COMPLETED)
        self.assertEqual(outcome.convergence.outcome, ConvergenceOutcome.CONVERGED)
        # Implementation AND review both ran, from one brief.
        self.assertGreaterEqual(agent.reviews, 1)
        self.assertIsNotNone(outcome.implementation)
        # One report, covering both halves.
        report = json.loads(
            (pipeline.inbox.layout.outbox / f"{outcome.task_id}.json").read_text(
                encoding="utf-8"))
        self.assertEqual(report["status"], "COMPLETED")
        self.assertTrue(any("convergence:" in line for line in report["verification"]))
        self.assertEqual(
            pipeline.records.get("BRIEF-1").state, BriefRecordState.COMPLETED.value)

    def test_convergence_reviews_the_worktree_not_the_source_repo(self):
        # The implementation's changes live in the worktree. Reviewing the
        # source tree would judge code nobody wrote and report a clean
        # bill for work that never happened.
        seen: list[Path] = []

        class _Recording(_Agent):
            def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s=1800.0, **kw):
                if "INDEPENDENT reviewer" in prompt:
                    seen.append(Path(cwd))
                return super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kw)

        agent = _Recording()
        outcome = self._pipeline(agent).run_brief(self._brief())
        expected = Path(self.worktrees.load_handle(outcome.task_id).path)
        self.assertEqual(seen[0], expected)
        self.assertNotEqual(seen[0], self.repo)

    def test_a_failing_review_does_not_report_completed(self):
        # The implementation half can succeed while the review half finds
        # blocking defects. Reporting the implementation's own opinion
        # would be an agent's DONE claim closing a task.
        agent = _Agent(review_answers=(_FAIL_REVIEW, _FAIL_REVIEW),
                       fix_answer='{"claims_done": false}')
        outcome = self._pipeline(agent).run_brief(self._brief())
        self.assertNotEqual(outcome.status, ReportStatus.COMPLETED)
        self.assertTrue(any("off by one" in p
                            for p in outcome.report.problems_encountered))

    def test_a_review_that_passes_after_a_fix_converges(self):
        def fix(cwd):
            (cwd / "code.py").write_text("x = 2  # fixed\n", encoding="utf-8")

        agent = _Agent(review_answers=(_FAIL_REVIEW, _PASS_REVIEW))
        implementer = _Agent(on_fix=fix)
        outcome = self._pipeline(agent, implementer=implementer).run_brief(self._brief())
        self.assertEqual(agent.fixes, 0)
        self.assertEqual(implementer.fixes, 1)
        self.assertEqual(outcome.status, ReportStatus.COMPLETED)

    def test_a_cannot_fix_escalates_and_lands_in_escalations(self):
        agent = _Agent(review_answers=(_FAIL_REVIEW,))
        implementer = _Agent(fix_answer='{"cannot_fix": true, "notes": "needs a human"}')
        pipeline = self._pipeline(agent, implementer=implementer)
        outcome = pipeline.run_brief(self._brief())
        self.assertEqual(outcome.status, ReportStatus.ESCALATION_REQUIRED)
        self.assertTrue(
            (pipeline.inbox.layout.escalations / f"{outcome.task_id}.json").exists())
        self.assertEqual(
            pipeline.records.get("BRIEF-1").state, BriefRecordState.ESCALATED.value)

    def test_convergence_evidence_is_written_beside_the_report(self):
        agent = _Agent()
        pipeline = self._pipeline(agent)
        outcome = pipeline.run_brief(self._brief())
        evidence = (pipeline.inbox.layout.outbox / f"{outcome.task_id}-convergence"
                    / "convergence.json")
        self.assertTrue(evidence.exists())
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        self.assertEqual(payload["outcome"], "CONVERGED")
        # Allowed launches are evidence too. Without this an operator
        # could not prove which review or fix launches were authorised,
        # in a path this ADR calls governed AND recorded (Codex review).
        stages = {d["stage"] for d in payload["policy_decisions"]}
        self.assertIn(REVIEW_STAGE, stages)
        self.assertTrue(all("verdict" in d for d in payload["policy_decisions"]))

    def test_a_report_with_no_run_says_so_instead_of_inventing_an_id(self):
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 600,
            placed_at=self.now,
        ))
        outcome = self._pipeline(_Agent()).run_brief(self._brief())
        # `<task_id>-no-run` LOOKED like a run id and resolved to nothing.
        self.assertNotIn(outcome.task_id, outcome.report.run_id)
        self.assertIn("no run", outcome.report.run_id)


class TestABriefIsBounded(_PipelineTestCase):
    """Every loop is bounded individually; nothing bounded a BRIEF."""

    def test_a_launch_budget_stops_convergence_and_parks_the_brief(self):
        from gnosis.kernel.budget import Budget
        # The implementation's one attempt is charged to the ledger, so
        # the budget allows nothing more and the first review round is
        # refused before it costs anything.
        agent = _Agent(review_answers=(_FAIL_REVIEW,))
        pipeline = self._pipeline(agent, budget=Budget(max_agent_launches=1))
        outcome = pipeline.run_brief(self._brief())

        self.assertEqual(agent.reviews, 0)
        self.assertEqual(outcome.status, ReportStatus.PARTIAL)
        self.assertTrue(outcome.reason_code.startswith("budget:"))
        # Nobody did anything wrong, so this is not the agent's failure.
        self.assertNotEqual(
            pipeline.records.get("BRIEF-1").state, BriefRecordState.FAILED.value)

    def test_an_ample_budget_changes_nothing(self):
        from gnosis.kernel.budget import Budget
        agent = _Agent()
        outcome = self._pipeline(
            agent, budget=Budget(max_agent_launches=50)).run_brief(self._brief())
        self.assertEqual(outcome.status, ReportStatus.COMPLETED)

    def test_the_budget_refuses_before_the_launch_not_after(self):
        # Refusing after the money is gone is not a budget.
        from gnosis.kernel.budget import Budget
        agent = _Agent(review_answers=(_FAIL_REVIEW, _PASS_REVIEW))
        pipeline = self._pipeline(agent, budget=Budget(max_agent_launches=2))
        pipeline.run_brief(self._brief())
        # One review got through; the fix round did not.
        self.assertEqual(agent.reviews, 1)
        self.assertEqual(agent.fixes, 0)


class TestLandingTheWork(_PipelineTestCase):
    """A converged brief may land — and only then, and only if the MERGED
    tree verifies."""

    def _integrator(self, verifier=None):
        from gnosis.kernel.integration import WorkIntegrator
        return WorkIntegrator(
            source_repo=self.repo, worktrees=self.worktrees,
            verifier=verifier or self._verifier(),
            integration_root=self.root / "integration",
        )

    def _head(self) -> str:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo,
                              capture_output=True, text=True, check=True).stdout.strip()

    def test_without_an_integrator_the_work_stays_on_its_branch(self):
        # Landing moves the branch everyone builds on: prepared by
        # default, executed only when an operator wires it.
        before = self._head()
        outcome = self._pipeline(_Agent()).run_brief(self._brief())
        self.assertEqual(outcome.status, ReportStatus.COMPLETED)
        self.assertIsNone(outcome.integration)
        self.assertEqual(self._head(), before)
        # COMPLETED means "done and independently verified", not "it
        # landed" — and the report says which, rather than leaving a
        # reader to infer it from silence (Codex review).
        self.assertTrue(any("integration: NOT ATTEMPTED" in line
                            for line in outcome.report.verification))
        self.assertIn("task branch", outcome.report.recommended_next_step)

    def test_a_converged_brief_lands_and_the_report_says_so(self):
        class _Writing(_Agent):
            def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s=1800.0, **kw):
                if "INDEPENDENT reviewer" not in prompt and "fixing defects" not in prompt:
                    (Path(cwd) / "landed.py").write_text("VALUE = 1\n", encoding="utf-8")
                return super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kw)

        before = self._head()
        pipeline = self._pipeline(_Agent(), implementer=_Writing(),
                                  integrator=self._integrator())
        outcome = pipeline.run_brief(self._brief())

        self.assertEqual(outcome.status, ReportStatus.COMPLETED, outcome.reason_code)
        self.assertTrue(outcome.integration.integrated, outcome.integration.reason)
        self.assertNotEqual(self._head(), before)
        self.assertTrue((self.repo / "landed.py").exists())
        self.assertTrue(any("integration: INTEGRATED" in line
                            for line in outcome.report.verification))

    def test_work_that_breaks_the_merged_tree_escalates_instead_of_landing(self):
        # Converged, reviewed, and it still must not land: the report
        # would otherwise describe an intention rather than an outcome.
        class _Writing(_Agent):
            def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s=1800.0, **kw):
                if "INDEPENDENT reviewer" not in prompt and "fixing defects" not in prompt:
                    (Path(cwd) / "broken.py").write_text("syntax ( error\n", encoding="utf-8")
                return super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kw)

        # A verifier that compiles every file in the tree.
        strict = CommandVerifier("compile-all", [
            sys.executable, "-c",
            ("import pathlib, py_compile; "
             "[py_compile.compile(str(p), doraise=True) "
             " for p in pathlib.Path('.').glob('*.py')]"),
        ])
        before = self._head()
        pipeline = self._pipeline(_Agent(), implementer=_Writing(),
                                  integrator=self._integrator(verifier=strict))
        outcome = pipeline.run_brief(self._brief())

        self.assertEqual(outcome.integration.outcome.value, "VERIFICATION_FAILED")
        self.assertEqual(outcome.status, ReportStatus.ESCALATION_REQUIRED)
        self.assertEqual(self._head(), before, "the shared branch must not have moved")

    def test_unconverged_work_is_never_offered_for_integration(self):
        agent = _Agent(review_answers=(_FAIL_REVIEW, _FAIL_REVIEW),
                       fix_answer='{"claims_done": false}')
        before = self._head()
        outcome = self._pipeline(agent, integrator=self._integrator()).run_brief(
            self._brief())
        self.assertNotEqual(outcome.status, ReportStatus.COMPLETED)
        self.assertEqual(self._head(), before)


class TestTheGateCoversEveryLaunch(_PipelineTestCase):
    """A gate with partial coverage is worse than an absent one: it reads
    as governed. Convergence launches MORE agents than the task does."""

    def test_every_launch_including_review_and_fix_passes_the_gate(self):
        stages: list[str] = []

        def capture(snapshot):
            stages.append(snapshot.payload["stage"])
            return RuleOutcome(Verdict.ALLOW, "ok:seen")

        agent = _Agent(review_answers=(_FAIL_REVIEW, _PASS_REVIEW))
        self._pipeline(agent, policy=_permissive(capture)).run_brief(self._brief())
        self.assertIn("pre_context", stages)          # the implementation
        self.assertIn(REVIEW_STAGE, stages)
        self.assertIn(FIX_STAGE, stages)

    def test_a_policy_that_denies_review_never_launches_a_reviewer(self):
        agent = _Agent()

        def deny_reviews(snapshot):
            if snapshot.payload["stage"] == REVIEW_STAGE:
                return RuleOutcome(Verdict.DENY, "security:no-reviewers")
            return RuleOutcome(Verdict.ALLOW, "ok:permitted")

        outcome = self._pipeline(agent, policy=_permissive(deny_reviews)).run_brief(
            self._brief())
        self.assertEqual(agent.reviews, 0)
        self.assertEqual(outcome.status, ReportStatus.ESCALATION_REQUIRED)
        self.assertEqual(outcome.reason_code, "security:no-reviewers")

    def test_a_denied_fixer_never_edits_the_worktree(self):
        agent = _Agent(review_answers=(_FAIL_REVIEW,))

        def deny_fixes(snapshot):
            if snapshot.payload["stage"] == FIX_STAGE:
                return RuleOutcome(Verdict.DENY, "security:no-fixers")
            return RuleOutcome(Verdict.ALLOW, "ok:permitted")

        outcome = self._pipeline(agent, policy=_permissive(deny_fixes)).run_brief(
            self._brief())
        self.assertEqual(agent.fixes, 0)
        self.assertEqual(outcome.status, ReportStatus.ESCALATION_REQUIRED)

    def test_the_review_launch_carries_the_same_snapshot_shape_as_the_engine(self):
        # One gate, one identity. Two snapshot builders would drift on the
        # first field either side forgot.
        payloads: list[dict] = []

        def capture(snapshot):
            payloads.append(dict(snapshot.payload))
            return RuleOutcome(Verdict.ALLOW, "ok:seen")

        self._pipeline(_Agent(), policy=_permissive(capture)).run_brief(self._brief())
        engine_keys = {k for p in payloads if p["stage"] == "pre_context" for k in p}
        review_keys = {k for p in payloads if p["stage"] == REVIEW_STAGE for k in p}
        self.assertEqual(engine_keys, review_keys)


class TestParksAreNotFailures(_PipelineTestCase):
    def test_a_held_credential_parks_the_brief_before_any_work(self):
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 600,
            placed_at=self.now,
        ))
        agent = _Agent()
        pipeline = self._pipeline(agent)
        outcome = pipeline.run_brief(self._brief())

        self.assertTrue(outcome.parked)
        self.assertEqual(agent.prompts, [])           # nothing ran at all
        self.assertEqual(outcome.status, ReportStatus.PARTIAL)
        # PARKED, not FAILED: the work is untouched and resumable, and
        # rule 7 forbids charging a provider's window to the agent.
        self.assertEqual(
            pipeline.records.get("BRIEF-1").state, BriefRecordState.PARKED.value)

    def test_a_rate_limit_hit_by_a_review_round_reaches_the_hold_plane(self):
        # Before this, a rate limit during convergence was invisible to
        # the hold plane: the reviewer's output was unparseable, the loop
        # filed it as INVALID_AGENT_OUTPUT, no hold was placed, and the
        # next round launched straight into the same shut window.
        class _RateLimited(_Agent):
            def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s=1800.0, **kw):
                result = super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kw)
                if "INDEPENDENT reviewer" not in prompt:
                    return result
                Path(result.stderr_path).write_text("Error: usage limit reached",
                                                    encoding="utf-8")
                return ExecutionResult(
                    command=result.command, exit_code=1, timed_out=False,
                    cancelled=False, duration_s=0.1,
                    stdout_path=result.stdout_path, stderr_path=result.stderr_path,
                    started_at="t0", ended_at="t1", parsed_json=None,
                )

        agent = _RateLimited()
        pipeline = self._pipeline(agent)
        outcome = pipeline.run_brief(self._brief())

        self.assertEqual(agent.reviews, 1)            # it did not retry into the wall
        self.assertEqual(outcome.status, ReportStatus.PARTIAL)
        self.assertEqual(
            pipeline.records.get("BRIEF-1").state, BriefRecordState.PARKED.value)
        # And a durable hold now exists for the next process to see.
        self.assertTrue(self.holds.read().holds)

    def test_a_hold_placed_during_convergence_parks_rather_than_failing(self):
        agent = _Agent(review_answers=(_FAIL_REVIEW,))
        holds = self.holds
        now = self.now

        class _HoldMidway(_Agent):
            def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s=1800.0, **kw):
                result = super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kw)
                if "INDEPENDENT reviewer" in prompt:
                    holds.place(RateLimitHold(
                        credential="claude://default", scope=HoldScope.ACCOUNT,
                        reason_code="rate_limited:usage", reset_at=now + 600,
                        placed_at=now,
                    ))
                return result

        agent = _HoldMidway(review_answers=(_FAIL_REVIEW,))
        pipeline = self._pipeline(agent)
        outcome = pipeline.run_brief(self._brief())

        self.assertEqual(agent.fixes, 0)              # the fix round was refused
        self.assertEqual(outcome.status, ReportStatus.PARTIAL)
        self.assertEqual(
            pipeline.records.get("BRIEF-1").state, BriefRecordState.PARKED.value)


class TestFailuresNeverStrandABrief(_PipelineTestCase):
    def test_an_implementation_that_never_ran_is_not_converged_on(self):
        # Converging on nothing would be theatre: there is no work to
        # review.
        agent = _Agent()

        def deny_everything(snapshot):
            return RuleOutcome(Verdict.DENY, "security:frozen")

        outcome = self._pipeline(agent, policy=_permissive(deny_everything)).run_brief(
            self._brief())
        self.assertEqual(agent.prompts, [])
        self.assertIsNone(outcome.convergence)
        self.assertEqual(outcome.status, ReportStatus.ESCALATION_REQUIRED)

    def test_an_unexpected_error_leaves_a_visible_record_not_limbo(self):
        class _Exploding:
            binary = "claude"

            def run(self, *a, **kw):
                raise RuntimeError("nobody enumerated this")

        pipeline = self._pipeline(_Agent(), implementer=_Exploding())
        outcome = pipeline.run_brief(self._brief())
        self.assertEqual(outcome.status, ReportStatus.BLOCKED)
        record = pipeline.records.get("BRIEF-1")
        self.assertEqual(record.state, BriefRecordState.FAILED.value)
        self.assertTrue(any("RuntimeError" in p
                            for p in outcome.report.problems_encountered))

    def test_a_crashing_fixer_does_not_strand_a_consumed_brief(self):
        # ADR-0008 lets fix_fn exceptions propagate on purpose. THIS is
        # the caller that was supposed to handle them, and it caught only
        # the two refusal types — so a crashing fixer escaped run_brief
        # and left an already-consumed brief IN_PROGRESS with no report
        # at all (Codex review).
        class _ExplodingFixer(_Agent):
            def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s=1800.0, **kw):
                if "fixing defects" in prompt:
                    raise RuntimeError("the fixer fell over")
                return super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kw)

        pipeline = self._pipeline(_Agent(review_answers=(_FAIL_REVIEW,)),
                                  implementer=_ExplodingFixer())
        outcome = pipeline.run_brief(self._brief())

        self.assertEqual(outcome.status, ReportStatus.BLOCKED)
        record = pipeline.records.get("BRIEF-1")
        self.assertNotEqual(record.state, BriefRecordState.IN_PROGRESS.value)
        self.assertEqual(len(record.run_ids), 2)  # original + interrupted correction
        failed = self.run_store.paths_for(record.run_ids[-1]).root / "attempt.json"
        self.assertEqual(json.loads(failed.read_text())["error_type"], "RuntimeError")
        self.assertTrue(
            (pipeline.inbox.layout.outbox / f"{outcome.task_id}.json").exists())
        self.assertTrue(any("the fixer fell over" in p
                            for p in outcome.report.problems_encountered))

    def test_a_lost_worktree_refuses_rather_than_reviewing_the_source_repo(self):
        # The fallback was the dangerous branch: reviewer AND fixer would
        # have run in the shared source tree, and a PASS there reports
        # COMPLETED for code nobody looked at.
        agent = _Agent()
        pipeline = self._pipeline(agent)
        original = self.worktrees.load_handle

        def vanish(task_id):
            handle = original(task_id)
            import shutil
            shutil.rmtree(handle.path, ignore_errors=True)
            return handle

        self.worktrees.load_handle = vanish
        outcome = pipeline.run_brief(self._brief())
        self.assertEqual(agent.reviews, 0)
        self.assertEqual(outcome.status, ReportStatus.BLOCKED)

    def test_the_same_runner_cannot_implement_and_review(self):
        # Rule 10. `reviewer_id` was only a label; nothing stopped the
        # implementing agent from reviewing its own work, and the test
        # fixture did exactly that.
        shared = _Agent()
        with self.assertRaises(ValueError):
            self._pipeline(shared, implementer=shared)

    def test_a_brief_already_running_is_refused_rather_than_overwritten(self):
        from gnosis.director.pipeline import BriefAlreadyRunning
        pipeline = self._pipeline(_Agent())
        brief = self._brief()
        pipeline.records.create(brief.brief_id, "TASK-EARLIER",
                                BriefRecordState.IN_PROGRESS)
        with self.assertRaises(BriefAlreadyRunning):
            pipeline.run_brief(brief)
        # The earlier task's linkage survives.
        self.assertEqual(pipeline.records.get(brief.brief_id).task_id, "TASK-EARLIER")

    def test_run_pending_processes_the_inbox(self):
        pipeline = self._pipeline(_Agent())
        brief = self._brief("BRIEF-INBOX")
        (pipeline.inbox.layout.inbox / "BRIEF-INBOX.json").write_text(
            json.dumps(brief.to_dict()), encoding="utf-8")
        outcomes = pipeline.run_pending()
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].brief_id, "BRIEF-INBOX")


class TestNothingIsLost(_PipelineTestCase):
    def test_non_blocking_findings_survive_into_the_report(self):
        info_finding = ('```json\n{"verdict": "PASS", "findings": [{"severity": "INFO", '
                        '"category": "style", "description": "naming could be clearer"}]}\n```')
        agent = _Agent(review_answers=(info_finding,))
        outcome = self._pipeline(agent).run_brief(self._brief())
        self.assertEqual(outcome.status, ReportStatus.COMPLETED)
        self.assertTrue(any("naming could be clearer" in r
                            for r in outcome.report.remaining_risks))

    def test_an_approval_lets_an_escalated_review_launch_through(self):
        approvals = ApprovalStore()

        def escalate_reviews(snapshot):
            if snapshot.payload["stage"] == REVIEW_STAGE:
                return RuleOutcome(Verdict.ESCALATE, "needs_human:review")
            return RuleOutcome(Verdict.ALLOW, "ok:permitted")

        agent = _Agent()
        blocked = self._pipeline(agent, policy=_permissive(escalate_reviews),
                                 approvals=approvals).run_brief(self._brief())
        self.assertEqual(blocked.status, ReportStatus.ESCALATION_REQUIRED)
        self.assertEqual(agent.reviews, 0)


class TestTheProbeReachesThePathThatLaunches(_PipelineTestCase):
    """`submit()` is not how the pipeline launches agents. A probe caller
    wired only there would leave the reviewer, the fixer and the
    re-reviewer going through a gate that never probes — the same
    mechanism-nobody-calls defect it was written to fix, one level up."""

    def _gate(self):
        engine = TaskEngine(run_store=self.run_store, cli_runner=_Agent(),
                            retry_policy=_FAST_RETRY)
        return TaskScheduler(
            engine=engine, run_store=self.run_store, holds=self.holds,
            credential="claude://default", clock=lambda: self.now,
        )

    def _runner(self, gate, stage="review", task_id="TASK-1"):
        return GatedAgentRunner(
            inner=_Agent(), policy=_permissive(), exec_root=self.repo,
            stage=stage, task_id=task_id, policy_actor="agent://worker-a",
            holds=gate,
        )

    def _estimated_hold(self):
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:prose", reset_at=self.now + 900,
            placed_at=self.now, window_estimated=True,
        ))

    def _run(self, runner, name):
        return runner.run(
            prompt="review it", cwd=self.repo,
            stdout_path=self.root / f"{name}.out", stderr_path=self.root / f"{name}.err",
            timeout_s=30,
        )

    def test_a_gated_launch_probes_a_guessed_window_instead_of_parking_forever(self):
        self._estimated_hold()
        self.now += 900 - 30
        gate = self._gate()
        self._run(self._runner(gate), "probe")          # does not raise
        self.assertEqual(gate.live_holds(), [],
                         "a clean probe did not reopen the credential")

    def test_only_one_gated_launch_gets_through_the_guess(self):
        self._estimated_hold()
        self.now += 900 - 30
        gate = self._gate()
        first = self._runner(gate, task_id="TASK-1")
        second = self._runner(gate, task_id="TASK-2")
        # The first claims the probe and holds it until it answers; a
        # second launch arriving meanwhile is parked, not admitted.
        self.assertIsNotNone(gate.claim_probe("SOMEONE-ELSE"))
        with self.assertRaises(CredentialHeld):
            self._run(second, "second")
        del first

    def test_a_provider_window_still_parks_the_round(self):
        # Not a guess: nothing to probe, and a park is a park.
        self.holds.place(RateLimitHold(
            credential="claude://default", scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 900,
            placed_at=self.now, window_estimated=False,
        ))
        self.now += 900 - 30
        with self.assertRaises(CredentialHeld):
            self._run(self._runner(self._gate()), "parked")

    def test_two_rounds_of_one_stage_never_share_a_probe(self):
        # A convergence loop runs the same stage for the same task
        # repeatedly. A reused identity would let a later round ride an
        # earlier round's probe, which is the defect this mechanism has
        # already been repaired for once.
        self._estimated_hold()
        self.now += 900 - 30
        gate = self._gate()
        runner = self._runner(gate)
        self._run(runner, "round-1")
        self._estimated_hold()
        self.now += 900 - 30
        self._run(runner, "round-2")
        rows = [json.loads(line) for line
                in self.holds.path.read_text(encoding="utf-8").splitlines()]
        holders = [r["hold"]["probe_holder"] for r in rows if r.get("row") == "narrow"]
        self.assertEqual(len(holders), 2)
        self.assertEqual(len(set(holders)), 2, f"a probe identity was reused: {holders}")


class _EnvRecordingAgent(_Agent):
    """Records the environment each launch was actually given."""

    def __init__(self):
        super().__init__()
        self.environments: list = []

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        self.environments.append(kwargs.get("env"))
        return super().run(prompt, cwd, stdout_path, stderr_path, timeout_s,
                           **{k: v for k, v in kwargs.items() if k != "env"})


class _RateLimitedAgent(_EnvRecordingAgent):
    """A launch that comes back as a provider rate limit."""

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        self.environments.append(kwargs.get("env"))
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"error": {"type": "rate_limit_error"}, "rate_limited": True}
        stdout_path.write_text(json.dumps(payload), encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return ExecutionResult(
            command=("claude",), exit_code=1, timed_out=False, cancelled=False,
            duration_s=0.1, stdout_path=str(stdout_path),
            stderr_path=str(stderr_path), started_at="t0", ended_at="t1",
            parsed_json=payload,
        )


class TestRotationReachesTheLaunch(_PipelineTestCase):
    """Deciding which credential to use and then launching with the ambient
    environment is not rotation: the child authenticates as whatever is
    configured and the audit trail records the decision instead of what
    happened."""

    BASE: ClassVar[dict[str, str]] = {
        "PATH": "/usr/bin", "SEAT_A_TOKEN": "aaa", "SEAT_B_TOKEN": "bbb",
        "METERED_TOKEN": "mmm"}

    def _gate(self):
        engine = TaskEngine(run_store=self.run_store, cli_runner=_Agent(),
                            retry_policy=_FAST_RETRY)
        return TaskScheduler(
            engine=engine, run_store=self.run_store, holds=self.holds,
            credential="seat-a", clock=lambda: self.now,
        )

    def _pool(self):
        return CredentialPool([
            Credential("seat-a", CredentialKind.SUBSCRIPTION,
                       env_from={"CLAUDE_TOKEN": "SEAT_A_TOKEN"}),
            Credential("seat-b", CredentialKind.SUBSCRIPTION,
                       env_from={"CLAUDE_TOKEN": "SEAT_B_TOKEN"}),
            Credential("metered", CredentialKind.METERED,
                       env_from={"ANTHROPIC_API_KEY": "METERED_TOKEN"}),
        ])

    def _runner(self, gate, agent, **kwargs):
        return GatedAgentRunner(
            inner=agent, policy=_permissive(), exec_root=self.repo,
            stage="review", task_id="TASK-1", policy_actor="agent://worker-a",
            holds=gate, credentials=self._pool(), base_environment=self.BASE,
            **kwargs,
        )

    def _hold(self, credential):
        self.holds.place(RateLimitHold(
            credential=credential, scope=HoldScope.ACCOUNT,
            reason_code="rate_limited:usage", reset_at=self.now + 900,
            placed_at=self.now,
        ))

    def _run(self, runner, name="r"):
        return runner.run(
            prompt="review it", cwd=self.repo,
            stdout_path=self.root / f"{name}.out",
            stderr_path=self.root / f"{name}.err", timeout_s=30,
        )

    def test_the_child_is_launched_with_the_selected_credential(self):
        agent = _EnvRecordingAgent()
        self._run(self._runner(self._gate(), agent))
        env = agent.environments[0]
        self.assertIsNotNone(env, "the launch inherited the ambient environment")
        self.assertEqual(env["CLAUDE_TOKEN"], "aaa")
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_a_held_seat_rotates_to_the_next_seat_and_binds_it(self):
        self._hold("seat-a")
        agent = _EnvRecordingAgent()
        runner = self._runner(self._gate(), agent)
        self._run(runner)
        self.assertEqual(agent.environments[0]["CLAUDE_TOKEN"], "bbb")
        self.assertEqual(runner.rotations[0]["credential"]["credential_id"], "seat-b")

    def test_every_seat_held_parks_rather_than_reaching_for_the_metered_key(self):
        # THE test. An exhausted plan is a reason to wait; billing is a
        # decision, and no decision was made here.
        self._hold("seat-a")
        self._hold("seat-b")
        agent = _EnvRecordingAgent()
        with self.assertRaises(CredentialHeld):
            self._run(self._runner(self._gate(), agent))
        self.assertEqual(agent.environments, [], "it launched anyway")

    def test_crossing_is_possible_when_a_caller_holds_the_authority(self):
        self._hold("seat-a")
        self._hold("seat-b")
        agent = _EnvRecordingAgent()
        runner = self._runner(
            self._gate(), agent,
            authorised_kinds=frozenset({CredentialKind.METERED}),
        )
        self._run(runner)
        self.assertEqual(agent.environments[0]["ANTHROPIC_API_KEY"], "mmm")
        self.assertNotIn("CLAUDE_TOKEN", agent.environments[0])
        self.assertEqual(
            [pair[0] for pair in runner.rotations[0]["skipped"]], ["seat-a", "seat-b"])

    def test_a_rate_limit_holds_only_the_credential_that_hit_it(self):
        # "The account is held" and "this key is held" stopped being the
        # same statement, which is the point of the whole unit.
        limited = _RateLimitedAgent()
        gate = self._gate()
        runner = self._runner(gate, limited)
        with self.assertRaises(CredentialHeld):
            self._run(runner)                       # the round parks...
        self.assertFalse(gate.admits(credential="seat-a"))
        self.assertTrue(gate.admits(credential="seat-b"))

    def test_an_unbindable_credential_refuses_instead_of_running_as_anyone(self):
        pool = CredentialPool([Credential(
            "seat-a", CredentialKind.SUBSCRIPTION,
            env_from={"CLAUDE_TOKEN": "NOT_SET_ANYWHERE"})])
        agent = _EnvRecordingAgent()
        runner = GatedAgentRunner(
            inner=agent, policy=_permissive(), exec_root=self.repo,
            stage="review", task_id="TASK-1", policy_actor="agent://worker-a",
            holds=self._gate(), credentials=pool, base_environment=self.BASE,
        )
        with self.assertRaises(CredentialUnavailable):
            self._run(runner)
        self.assertEqual(agent.environments, [])

    def test_provenance_records_the_identity_and_never_the_secret(self):
        runner = self._runner(self._gate(), _EnvRecordingAgent())
        self._run(runner)
        payload = json.dumps(runner.rotations)
        self.assertIn("seat-a", payload)
        self.assertIn("SEAT_A_TOKEN", payload)      # the variable NAME
        self.assertNotIn("aaa", payload)            # never the value

    def test_a_pool_without_a_hold_gate_still_binds(self):
        # It used to be ignored entirely — no rotation, no binding, no
        # error — because the check was `holds is not None AND credentials
        # is not None`. The one guarantee the mechanism sells was given
        # away by a missing collaborator.
        agent = _EnvRecordingAgent()
        runner = GatedAgentRunner(
            inner=agent, policy=_permissive(), exec_root=self.repo,
            stage="review", task_id="TASK-1", policy_actor="agent://worker-a",
            credentials=self._pool(), base_environment=self.BASE,
        )
        self._run(runner)
        self.assertIsNotNone(agent.environments[0], "the pool was ignored")
        self.assertEqual(agent.environments[0]["CLAUDE_TOKEN"], "aaa")

    def test_a_recording_runner_forwards_the_binding_to_the_real_child(self):
        # RECORD is the default mode and a cassette miss runs a real
        # child that really spends a credential. Accepting `env` and
        # dropping it meant the kernel decided one identity and the child
        # authenticated as the ambient one.
        inner = _EnvRecordingAgent()
        recording = ReplayingCLIRunner(
            store=InteractionStore(self.root / "cassette.json", ReplayMode.RECORD),
            inner=inner,
        )
        runner = GatedAgentRunner(
            inner=recording, policy=_permissive(), exec_root=self.repo,
            stage="review", task_id="TASK-1", policy_actor="agent://worker-a",
            holds=self._gate(), credentials=self._pool(),
            base_environment=self.BASE,
        )
        self._run(runner, "recorded")
        self.assertEqual(inner.environments[0]["CLAUDE_TOKEN"], "aaa")
        # And the secret is not in the cassette key.
        cassette = (self.root / "cassette.json").read_text(encoding="utf-8")
        self.assertNotIn("aaa", cassette)

    def test_without_a_pool_nothing_changes(self):
        # A runner with no credential configuration behaves exactly as it
        # did before: ambient environment, single-credential gate.
        agent = _EnvRecordingAgent()
        runner = GatedAgentRunner(
            inner=agent, policy=_permissive(), exec_root=self.repo,
            stage="review", task_id="TASK-1", policy_actor="agent://worker-a",
            holds=self._gate(),
        )
        self._run(runner)
        self.assertIsNone(agent.environments[0])
        self.assertEqual(runner.rotations, [])


if __name__ == "__main__":
    unittest.main()


class _MalformedMember(Verifier):
    """A member verifier whose `passed` records no verdict.

    `passed=1` is DATA, not a typo: `bool` IS an `int` in Python, so a
    linter "correcting" it to `True` would delete the defect under test.
    """

    name = "bad-suite"

    def run(self, cwd):  # type: ignore[override]
        return VerificationResult(
            name=self.name, passed=1,  # type: ignore[arg-type]
            exit_code=0, duration_s=0.0,
            stdout_excerpt="looks fine", stderr_excerpt="",
        )


class TestABriefDoesNotCompleteOnMalformedEvidence(_PipelineTestCase):
    """F-34, third independent review, at the level a human reads.

    Verified reproduction, before the repair: a `CompositeVerifier` whose
    member returned `passed=1` produced `VerificationResult(passed=True)`,
    the loop converged on it, and the Director filed
    `ReportStatus.COMPLETED` with `BriefRecordState.COMPLETED` — the
    durable record of a brief that proved nothing.

    Two ends are asserted, not one. `ConvergenceLoop` refuses to converge
    on such evidence, and `GovernedPipeline` refuses to derive COMPLETED
    from a convergence whose evidence it cannot read. An invariant
    enforced at exactly one end is a property of that end (ADR-0025).
    """

    def _run_malformed(self):
        agent = _Agent()
        pipeline = self._pipeline(
            agent, verifier=CompositeVerifier("composite", [_MalformedMember()]))
        return pipeline, pipeline.run_brief(self._brief())

    def test_the_brief_does_not_report_completed(self):
        _, outcome = self._run_malformed()
        self.assertNotEqual(outcome.status, ReportStatus.COMPLETED)

    def test_the_loop_does_not_converge(self):
        _, outcome = self._run_malformed()
        self.assertIsNot(outcome.convergence.outcome, ConvergenceOutcome.CONVERGED)

    def test_the_durable_record_is_not_completed(self):
        # The report can be re-read; the record store is what the next
        # session believes.
        pipeline, _ = self._run_malformed()
        self.assertNotEqual(pipeline.records.get("BRIEF-1").state,
                            BriefRecordState.COMPLETED.value)

    def test_the_written_report_never_shows_a_pass(self):
        pipeline, outcome = self._run_malformed()
        report = json.loads(
            (pipeline.inbox.layout.outbox / f"{outcome.task_id}.json").read_text(
                encoding="utf-8"))
        self.assertNotEqual(report["status"], "COMPLETED")
        # Every VERIFICATION line, and only those: the reviewer really did
        # answer PASS and the report must keep saying so. What may never
        # appear is a pass attributed to evidence the kernel refused.
        lines = [line for line in report["verification"] if "verification [" in line]
        self.assertTrue(lines)
        for line in lines:
            self.assertIn("REJECTED", line)
            self.assertNotIn("PASS", line)

    def test_the_operator_is_told_the_evidence_was_invalid(self):
        _, outcome = self._run_malformed()
        blob = " ".join(outcome.report.problems_encountered)
        self.assertIn("invalid evidence", blob.lower())

    def test_a_converged_result_with_unreadable_evidence_is_escalated(self):
        # The Director's own end of the invariant, exercised directly: a
        # loop outcome that SAYS converged while its final round records
        # no passing verdict is a kernel contradiction, and a
        # contradiction is a human's decision, not a PARTIAL to retry.
        forged = ConvergenceResult(
            outcome=ConvergenceOutcome.CONVERGED,
            rounds=(RoundRecord(
                index=1, fingerprint="fp", evidence_ok=True,
                verification=VerificationResult(
                    name="suite", passed=1,  # type: ignore[arg-type]
                    exit_code=0, duration_s=0.0,
                    stdout_excerpt="", stderr_excerpt=""),
                review=None, blocking=(), gated=(), fix=None, warnings=(),
                unchanged_streak=0),),
            gate_ledger=(), dissent=(), warnings=(),
        )
        self.assertEqual(_status_for(forged), ReportStatus.ESCALATION_REQUIRED)

    def test_a_converged_result_over_zero_rounds_is_not_completed(self):
        # CONVERGED with no rounds is `all([])` wearing a different coat.
        empty = ConvergenceResult(
            outcome=ConvergenceOutcome.CONVERGED, rounds=(), gate_ledger=(),
            dissent=(), warnings=(),
        )
        self.assertNotEqual(_status_for(empty), ReportStatus.COMPLETED)

    def test_a_sound_composite_still_completes_a_brief(self):
        # The repair must not make a legitimate composite unusable.
        agent = _Agent()
        pipeline = self._pipeline(agent, verifier=CompositeVerifier(
            "composite", [self._verifier(), self._verifier()]))
        outcome = pipeline.run_brief(self._brief())
        self.assertEqual(outcome.status, ReportStatus.COMPLETED)
        self.assertEqual(pipeline.records.get("BRIEF-1").state,
                         BriefRecordState.COMPLETED.value)
