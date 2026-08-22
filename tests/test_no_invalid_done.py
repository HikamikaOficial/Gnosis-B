"""NO INVALID DONE — the invariant, tested by name (F-34).

The audit found the constitution's most absolute rule (rule 2: no task
reaches DONE without evidence) enforced only on the GOVERNED path. The
default `DirectorOrchestrator` supplies neither a `WorkAuthority` nor a
verifier, and the engine then read

    verification_result.passed if verification_result else True

which turns "nobody checked" into "it passed". A default-constructed
orchestrator could report COMPLETED having proved nothing.

This file exists so that regression is not possible silently. It tests
the invariant at three heights:

1. the predicate — `completion_is_evidenced`, the single authority for
   the transition;
2. the engine — refusing before the agent launches, and refusing to
   complete on a verifier that produced nothing;
3. the Director entry point — refusing before a brief is consumed.

Every test here is written so that restoring the old expression, or
loosening the predicate, turns it red.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.contracts.engineer_report import ReportStatus
from gnosis.director.brief_record import BriefRecordState
from gnosis.director.orchestrator import DirectorOrchestrator
from gnosis.kernel.engine import TaskEngine, completion_is_evidenced
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.state_machine import (
    EVIDENCE_GATED_STATES,
    TaskState,
    TaskStateMachine,
    UnevidencedCompletionError,
)
from gnosis.kernel.verification import CommandVerifier, VerificationResult, Verifier
from gnosis.runner.capture import ExecutionResult
from gnosis.runner.retry import RetryPolicy

_FAST_RETRY = RetryPolicy(max_attempts=2, backoff_base_s=0.01, backoff_factor=2.0, max_backoff_s=0.02)


def passing_verifier() -> CommandVerifier:
    """Real deterministic verification: a child process, and its exit code.

    Not a stand-in that returns a hard-coded `passed=True` — a fixture
    incapable of exhibiting the failure is how L-0013 was earned. This
    actually spawns a process and reads what the OS reports.
    """
    return CommandVerifier("always-pass", [sys.executable, "-c", "raise SystemExit(0)"])


def failing_verifier() -> CommandVerifier:
    return CommandVerifier("always-fail", [sys.executable, "-c", "raise SystemExit(1)"])


class _SilentVerifier(Verifier):
    """A verifier that runs and answers with nothing.

    Deliberately duck-typed past its own annotation: this is the shape
    the old code turned into a PASS. `Verifier.run` DECLARES a
    VerificationResult, so a type checker cannot catch this — L-0039.
    """

    name = "silent"
    # The answer is DATA, not a bare `return None`: the emptiness is the
    # subject of the test, and a linter that removes it would remove the
    # thing being tested.
    answer = None

    def __init__(self) -> None:
        self.calls = 0

    def run(self, cwd: Path):  # type: ignore[override]
        self.calls += 1
        return self.answer


class _TruthyVerifier(Verifier):
    """Answers with something truthy that is not a VerificationResult."""

    name = "truthy"

    def run(self, cwd: Path):  # type: ignore[override]
        return "everything looks fine to me"


class _NotQuiteTrue:
    """A `passed` that is truthy but not `True` — `bool` IS an `int`."""

    name = "not-quite"
    passed = 1
    exit_code = 0


class _CountingRunner:
    """Duck-types the CLI runner and records whether it was ever asked to run."""

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


class _RepoTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        self.store = RunStore(self.root / "runs")

    def tearDown(self):
        self.tmp.cleanup()


class TestTheAuthorisingPredicate(unittest.TestCase):
    """`completion_is_evidenced` is the only thing that may authorise a DONE.

    Testing it directly matters because it is the mutation target: the
    defect was one word inside an expression, and an invariant that can
    only be observed through a full engine run is one nobody checks when
    editing that word.
    """

    def test_absent_evidence_is_not_success(self):
        # THE regression. `... if verification_result else True` returned
        # True here; this assertion is what turns that edit red.
        self.assertFalse(completion_is_evidenced(None))

    def test_a_passing_result_authorises(self):
        self.assertTrue(completion_is_evidenced(VerificationResult(
            name="v", passed=True, exit_code=0, duration_s=0.0,
            stdout_excerpt="", stderr_excerpt="",
        )))

    def test_a_failing_result_does_not_authorise(self):
        self.assertFalse(completion_is_evidenced(VerificationResult(
            name="v", passed=False, exit_code=1, duration_s=0.0,
            stdout_excerpt="", stderr_excerpt="boom",
        )))

    def test_something_that_is_not_a_verification_result_never_authorises(self):
        for impostor in ("PASSED", 1, True, object(), {"passed": True}, _NotQuiteTrue()):
            with self.subTest(impostor=type(impostor).__name__):
                self.assertFalse(completion_is_evidenced(impostor))  # type: ignore[arg-type]

    def test_a_truthy_passed_is_not_true(self):
        # `bool` is an `int`, so `if result.passed` would admit this.
        # Only the exact object True is evidence of a pass.
        result = VerificationResult(
            name="v", passed=1, exit_code=0, duration_s=0.0,  # type: ignore[arg-type]
            stdout_excerpt="", stderr_excerpt="",
        )
        self.assertFalse(completion_is_evidenced(result))


class TestTheStateAuthorityRefusesUnevidencedCompletion(unittest.TestCase):
    """The layer BELOW the engine, which is where the invariant belongs.

    The first version of this file tested the predicate and the engine
    and called the predicate "the single authority". It was not: an
    independent review walked a bare `TaskStateMachine` from CREATED to
    COMPLETED with no evidence at all, because `transition()` accepted
    COMPLETED from anyone and this file never asked it to refuse.

    These tests exist so that "the authority enforces it" is a claim with
    a falsifier attached, at the level the claim is about.
    """

    def _verifying(self) -> TaskStateMachine:
        sm = TaskStateMachine()
        sm.transition(TaskState.PLANNED)
        sm.transition(TaskState.IN_PROGRESS)
        sm.transition(TaskState.VERIFYING)
        return sm

    def test_the_direct_transition_to_completed_is_refused(self):
        sm = self._verifying()
        with self.assertRaises(UnevidencedCompletionError):
            sm.transition(TaskState.COMPLETED)
        self.assertEqual(sm.state, TaskState.VERIFYING)

    def test_none_is_refused_by_the_authority(self):
        sm = self._verifying()
        with self.assertRaises(UnevidencedCompletionError):
            sm.complete(None)
        self.assertNotEqual(sm.state, TaskState.COMPLETED)

    def test_a_failing_verification_result_is_refused_by_the_authority(self):
        sm = self._verifying()
        with self.assertRaises(UnevidencedCompletionError):
            sm.complete(VerificationResult(
                name="v", passed=False, exit_code=1, duration_s=0.0,
                stdout_excerpt="", stderr_excerpt="boom",
            ))
        self.assertNotEqual(sm.state, TaskState.COMPLETED)

    def test_an_impostor_is_refused_by_the_authority(self):
        for impostor in ("PASSED", 1, True, object(), {"passed": True}, _NotQuiteTrue()):
            with self.subTest(impostor=type(impostor).__name__):
                sm = self._verifying()
                with self.assertRaises(UnevidencedCompletionError):
                    sm.complete(impostor)
                self.assertNotEqual(sm.state, TaskState.COMPLETED)

    def test_only_a_passing_verification_result_completes(self):
        sm = self._verifying()
        evidence = VerificationResult(
            name="v", passed=True, exit_code=0, duration_s=0.0,
            stdout_excerpt="", stderr_excerpt="",
        )
        sm.complete(evidence)
        self.assertEqual(sm.state, TaskState.COMPLETED)
        self.assertIs(sm.completion_evidence, evidence)

    def test_a_machine_cannot_start_in_completed(self):
        with self.assertRaises(UnevidencedCompletionError):
            TaskStateMachine(TaskState.COMPLETED)

    def test_completed_is_the_gated_state(self):
        self.assertEqual(EVIDENCE_GATED_STATES, frozenset({TaskState.COMPLETED}))


class TestTheEngineRefusesBeforeItSpends(_RepoTestCase):
    def test_no_verifier_is_refused_before_the_runner_is_invoked(self):
        # Fail closed BEFORE launching: refusing after the child has run
        # costs a launch and leaves a half-finished task.
        runner = _CountingRunner(["succeed"])
        engine = TaskEngine(run_store=self.store, cli_runner=runner)
        with self.assertRaises(ValueError) as ctx:
            engine.execute_task(
                task_id="TASK-1", objective="Demo", prompt="do it",
                repo_path=self.repo, verifier=None,
            )
        self.assertIn("verifier", str(ctx.exception))
        self.assertEqual(runner.calls, 0)

    def test_no_verifier_leaves_no_run_on_disk(self):
        # Nothing was spent, so nothing should have to be recovered.
        engine = TaskEngine(run_store=self.store, cli_runner=_CountingRunner(["succeed"]))
        with self.assertRaises(ValueError):
            engine.execute_task(
                task_id="TASK-2", objective="Demo", prompt="do it",
                repo_path=self.repo, verifier=None,
            )
        self.assertEqual(self.store.list_run_ids(), [])

    def test_omitting_the_argument_entirely_is_also_refused(self):
        # The parameter has no default, so an omission cannot quietly
        # become "verification is optional".
        engine = TaskEngine(run_store=self.store, cli_runner=_CountingRunner(["succeed"]))
        with self.assertRaises(TypeError):
            engine.execute_task(  # type: ignore[call-arg]
                task_id="TASK-3", objective="Demo", prompt="do it", repo_path=self.repo,
            )


class TestNoInvalidDoneInTheEngine(_RepoTestCase):
    def test_a_successful_cli_with_no_evidence_cannot_complete(self):
        # The heart of F-34: exit code 0 from the agent, and a verifier
        # that produced no VerificationResult. The old code read that as
        # a pass.
        verifier = _SilentVerifier()
        engine = TaskEngine(run_store=self.store, cli_runner=_CountingRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-1", objective="Demo", prompt="do it",
            repo_path=self.repo, verifier=verifier,
        )
        self.assertEqual(verifier.calls, 1)               # it really ran
        self.assertIsNone(outcome.verification)           # and produced nothing
        self.assertNotEqual(outcome.final_task_state, TaskState.COMPLETED)
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertNotEqual(outcome.report.status, ReportStatus.COMPLETED)

    def test_a_truthy_non_result_cannot_complete_either(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_CountingRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-2", objective="Demo", prompt="do it",
            repo_path=self.repo, verifier=_TruthyVerifier(),
        )
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)

    def test_the_missing_evidence_is_stated_not_silent(self):
        # A refusal an operator cannot see is a refusal they will
        # misdiagnose as an ordinary failure.
        engine = TaskEngine(run_store=self.store, cli_runner=_CountingRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-3", objective="Demo", prompt="do it",
            repo_path=self.repo, verifier=_SilentVerifier(),
        )
        blob = " ".join(outcome.report.problems_encountered) + " ".join(outcome.report.verification)
        self.assertIn("evidence", blob.lower())

    def test_a_failing_verifier_does_not_complete(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_CountingRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-4", objective="Demo", prompt="do it",
            repo_path=self.repo, verifier=failing_verifier(),
        )
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertIsNotNone(outcome.verification)
        self.assertFalse(outcome.verification.passed)
        self.assertNotEqual(outcome.report.status, ReportStatus.COMPLETED)

    def test_only_a_successful_cli_and_a_passing_verifier_complete(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_CountingRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-5", objective="Demo", prompt="do it",
            repo_path=self.repo, verifier=passing_verifier(),
        )
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        self.assertIsNotNone(outcome.verification)
        self.assertTrue(outcome.verification.passed)
        self.assertEqual(outcome.report.status, ReportStatus.COMPLETED)

    def test_a_failed_cli_never_reaches_verification_or_completion(self):
        engine = TaskEngine(
            run_store=self.store, cli_runner=_CountingRunner(["fail", "fail"]),
            retry_policy=_FAST_RETRY,
        )
        outcome = engine.execute_task(
            task_id="TASK-6", objective="Demo", prompt="do it",
            repo_path=self.repo, verifier=passing_verifier(),
        )
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertIsNone(outcome.verification)

    def test_every_completed_outcome_carries_the_evidence_that_authorised_it(self):
        # The report and the outcome must agree: a COMPLETED that cannot
        # produce its own verification is exactly the state this
        # invariant forbids, whatever produced it.
        engine = TaskEngine(run_store=self.store, cli_runner=_CountingRunner(["succeed"]))
        for task_id, verifier in (
            ("TASK-A", passing_verifier()),
            ("TASK-B", failing_verifier()),
            ("TASK-C", _SilentVerifier()),
        ):
            with self.subTest(task=task_id):
                outcome = engine.execute_task(
                    task_id=task_id, objective="Demo", prompt="do it",
                    repo_path=self.repo, verifier=verifier,
                )
                if outcome.final_task_state == TaskState.COMPLETED:
                    self.assertTrue(completion_is_evidenced(outcome.verification))
                if outcome.report.status == ReportStatus.COMPLETED:
                    self.assertTrue(completion_is_evidenced(outcome.verification))


class TestNoInvalidDoneAtTheDirectorEntryPoint(_RepoTestCase):
    def setUp(self):
        super().setUp()
        self.director_root = self.root / "director"
        self.inbox = self.director_root / "inbox"
        self.inbox.mkdir(parents=True)

    def _drop(self, brief_id: str) -> Path:
        brief = DirectorBrief(
            brief_id=brief_id, title="Do a thing", mission="Ship it.",
            source=BriefSource.MANUAL,
        )
        import json
        path = self.inbox / f"{brief_id}.json"
        path.write_text(json.dumps(brief.to_dict()), encoding="utf-8")
        return path

    def _orchestrator(self, runner, **kwargs) -> DirectorOrchestrator:
        return DirectorOrchestrator(
            director_root=self.director_root, run_store=self.store,
            repo_path=self.repo,
            task_engine=TaskEngine(run_store=self.store, cli_runner=runner),
            **kwargs,
        )

    def test_the_default_orchestrator_refuses_and_consumes_nothing(self):
        # F-34 exactly: default construction, default run_pending, a CLI
        # that succeeds. This used to produce a COMPLETED brief.
        runner = _CountingRunner(["succeed"])
        path = self._drop("BRIEF-1")
        orchestrator = self._orchestrator(runner)

        with self.assertRaises(ValueError) as ctx:
            orchestrator.run_pending()

        self.assertIn("verifier", str(ctx.exception))
        self.assertEqual(runner.calls, 0)               # no agent launched
        self.assertTrue(path.exists())                  # brief still in the inbox
        self.assertFalse(orchestrator.records.exists("BRIEF-1"))  # no durable record
        self.assertEqual(self.store.list_run_ids(), [])

    def test_an_explicit_none_is_refused_too(self):
        runner = _CountingRunner(["succeed"])
        self._drop("BRIEF-2")
        with self.assertRaises(ValueError):
            self._orchestrator(runner).run_pending(verifier=None)
        self.assertEqual(runner.calls, 0)

    def test_a_constructor_verifier_is_enough(self):
        runner = _CountingRunner(["succeed"])
        self._drop("BRIEF-3")
        orchestrator = self._orchestrator(runner, verifier=passing_verifier())
        outcomes = orchestrator.run_pending()
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].execution.final_task_state, TaskState.COMPLETED)
        self.assertEqual(
            orchestrator.records.get("BRIEF-3").state, BriefRecordState.COMPLETED.value)

    def test_a_per_call_verifier_overrides_the_constructor_default(self):
        runner = _CountingRunner(["succeed"])
        self._drop("BRIEF-4")
        orchestrator = self._orchestrator(runner, verifier=passing_verifier())
        outcomes = orchestrator.run_pending(verifier=failing_verifier())
        self.assertNotEqual(outcomes[0].execution.final_task_state, TaskState.COMPLETED)
        self.assertNotEqual(
            orchestrator.records.get("BRIEF-4").state, BriefRecordState.COMPLETED.value)

    def test_a_verifier_that_produces_nothing_does_not_complete_a_brief(self):
        # The whole chain: engine predicate -> report status -> brief
        # record. All three must refuse together, or the brief record
        # would say COMPLETED while the task did not.
        runner = _CountingRunner(["succeed"])
        self._drop("BRIEF-5")
        orchestrator = self._orchestrator(runner, verifier=_SilentVerifier())
        outcomes = orchestrator.run_pending()
        self.assertEqual(outcomes[0].execution.final_task_state, TaskState.FAILED)
        self.assertNotEqual(outcomes[0].execution.report.status, ReportStatus.COMPLETED)
        self.assertEqual(
            orchestrator.records.get("BRIEF-5").state, BriefRecordState.FAILED.value)

    def test_a_refused_run_leaves_the_queue_replayable(self):
        # Refusing must not be destructive: after configuring a verifier
        # the same brief runs normally.
        runner = _CountingRunner(["succeed"])
        self._drop("BRIEF-6")
        orchestrator = self._orchestrator(runner)
        with self.assertRaises(ValueError):
            orchestrator.run_pending()
        outcomes = orchestrator.run_pending(verifier=passing_verifier())
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].execution.final_task_state, TaskState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
