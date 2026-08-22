"""NO INVALID DONE — the invariant, tested by name (F-34).

The audit found the constitution's most absolute rule (rule 2: no task
reaches DONE without evidence) enforced only on the GOVERNED path. The
default `DirectorOrchestrator` supplies neither a `WorkAuthority` nor a
verifier, and the engine then read

    verification_result.passed if verification_result else True

which turns "nobody checked" into "it passed". A default-constructed
orchestrator could report COMPLETED having proved nothing.

A THIRD independent review found the invariant broken again, one level
up. `CompositeVerifier` read its members with `all(r.passed for r in
results)` and returned a NEW `VerificationResult(passed=True)`: every
strict reader downstream was then correct about a well-formed object
computed from evidence the kernel refuses. The same review found
`CompositeVerifier("empty", [])` passing on `all([]) is True` — a DONE
minted by running no check at all. Aggregation was the hole: the
verdict has three states and `passed` has two, so a composite had
nowhere to say "a member returned nothing readable".

This file exists so that regression is not possible silently. It tests
the invariant at four heights:

1. the predicate — `completion_is_evidenced`, the single authority for
   the transition;
2. the aggregator — `CompositeVerifier`, which may not convert a
   member's malformed evidence into a verdict of its own;
3. the engine — refusing before the agent launches, and refusing to
   complete on a verifier that produced nothing;
4. the Director entry point — refusing before a brief is consumed.

The other three production readers of `passed` are tested where their
harnesses live, and are part of this invariant:

- `ConvergenceLoop` — `TestConvergenceRefusesMalformedEvidence` below;
- `GovernedPipeline` — `tests/test_pipeline.py::TestABriefDoesNotCompleteOnMalformedEvidence`;
- `WorkIntegrator` — `tests/test_integration.py::TestMalformedEvidenceDoesNotLand`.

Every test here is written so that restoring the old expression, or
loosening the predicate, turns it red.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gnosis.adapters.cli_review import verification_prompt_line
from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.contracts.engineer_report import ReportStatus
from gnosis.director.brief_record import BriefRecordState
from gnosis.director.orchestrator import DirectorOrchestrator
from gnosis.kernel.convergence import (
    ConvergenceLoop,
    ConvergenceOutcome,
    ConvergencePolicy,
    FixReport,
    ReviewReport,
    ReviewVerdict,
)
from gnosis.kernel.engine import (
    MALFORMED_EVIDENCE_PROBLEM,
    NO_EVIDENCE_PROBLEM,
    TaskEngine,
    completion_is_evidenced,
)
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.state_machine import (
    EVIDENCE_GATED_STATES,
    TaskState,
    TaskStateMachine,
    UnevidencedCompletionError,
)
from gnosis.kernel.verification import (
    CommandVerifier,
    CompositeVerifier,
    EmptyCompositeError,
    MalformedEvidence,
    VerificationResult,
    VerificationVerdict,
    Verifier,
    verification_verdict,
)
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


class _MalformedResultVerifier(Verifier):
    """Returns a REAL `VerificationResult` whose `passed` is `1`.

    The exact reproduction from the second independent review, and the
    one shape the `isinstance` check cannot catch: this IS a
    VerificationResult, so it is not "missing evidence" — it is evidence
    the kernel refuses to read, which the report then described as a
    pass.

    `passed=1` is data, not a typo: a linter or a type checker
    "correcting" it to `True` would delete the defect under test.
    """

    name = "malformed"

    def __init__(self, passed: object = 1) -> None:
        self._passed = passed
        self.calls = 0

    def run(self, cwd: Path) -> VerificationResult:
        self.calls += 1
        return VerificationResult(
            name="malformed-suite", passed=self._passed,  # type: ignore[arg-type]
            exit_code=0, duration_s=0.0,
            stdout_excerpt="looks fine", stderr_excerpt="",
        )


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


class TestTheVerdictIsReadByIdentityNotTruthiness(unittest.TestCase):
    """One function decides what `passed` means, and it says three things.

    The second review found the predicate and the report reading the
    same field independently and disagreeing. `verification_verdict` is
    now the only reader; these tests pin its answers, because everything
    downstream is derived from them.
    """

    def _result(self, passed: object) -> VerificationResult:
        return VerificationResult(
            name="v", passed=passed,  # type: ignore[arg-type]
            exit_code=0, duration_s=0.0, stdout_excerpt="", stderr_excerpt="",
        )

    def test_only_the_object_true_is_passed(self):
        self.assertIs(verification_verdict(self._result(True)), VerificationVerdict.PASSED)

    def test_only_the_object_false_is_failed(self):
        self.assertIs(verification_verdict(self._result(False)), VerificationVerdict.FAILED)

    def test_truthy_non_bools_are_malformed_not_passed(self):
        for passed in (1, 2, "PASSED", [1], {"ok": True}, object()):
            with self.subTest(passed=repr(passed)):
                self.assertIs(
                    verification_verdict(self._result(passed)), VerificationVerdict.MALFORMED)

    def test_falsy_non_bools_are_malformed_not_failed(self):
        # A `0` says no more than a `1` does. Reporting it as a FAILURE
        # would invent a verdict too, just a less flattering one.
        for passed in (0, "", None, [], {}):
            with self.subTest(passed=repr(passed)):
                self.assertIs(
                    verification_verdict(self._result(passed)), VerificationVerdict.MALFORMED)

    def test_non_results_are_malformed(self):
        for impostor in (None, "PASSED", 1, True, object(), {"passed": True}, _NotQuiteTrue()):
            with self.subTest(impostor=type(impostor).__name__):
                self.assertIs(verification_verdict(impostor), VerificationVerdict.MALFORMED)

    def test_the_completion_predicate_agrees_with_the_verdict(self):
        # They must not be able to drift: one is defined in terms of the
        # other, and this is the assertion that keeps it that way.
        for passed in (True, False, 1, 0, "PASSED", None):
            with self.subTest(passed=repr(passed)):
                result = self._result(passed)
                self.assertEqual(
                    completion_is_evidenced(result),
                    verification_verdict(result) is VerificationVerdict.PASSED,
                )


class TestARejectedResultIsNeverReportedAsAPass(_RepoTestCase):
    """End-to-end through `TaskEngine`, with `passed=1` (second review).

    Verified reproduction, before the repair:

        TaskState.FAILED
        ReportStatus.PARTIAL
        verification=("malformed: PASSED",)
        problems_encountered=()

    The gate held and the report lied. A human reading that report sees
    a suite that passed and an empty problems list, and has no way to
    learn that the kernel threw the evidence out.
    """

    def _run(self, task_id: str, passed: object = 1):
        verifier = _MalformedResultVerifier(passed)
        engine = TaskEngine(run_store=self.store, cli_runner=_CountingRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id=task_id, objective="Demo", prompt="do it",
            repo_path=self.repo, verifier=verifier,
        )
        self.assertEqual(verifier.calls, 1)     # the verifier really ran
        return outcome

    def _recorded_verification(self, run_id: str) -> dict:
        """The single `task.verification_result` entry this run wrote."""
        events = [e for e in self.store.ledger_for(run_id).read_all()
                  if e.event_type == "task.verification_result"]
        self.assertEqual(len(events), 1)
        return events[0].data

    def test_the_task_does_not_complete(self):
        outcome = self._run("TASK-M1")
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertNotEqual(outcome.report.status, ReportStatus.COMPLETED)

    def test_the_report_never_shows_the_rejected_result_as_a_pass(self):
        # THE regression. Scanning the whole report, not just the
        # verification tuple: the claim is that the word does not appear
        # anywhere a reader could take it from.
        outcome = self._run("TASK-M2")
        blob = " ".join((
            *outcome.report.verification,
            *outcome.report.problems_encountered,
            *outcome.report.work_completed,
            outcome.report.recommended_next_step,
        ))
        self.assertNotIn("PASSED", blob)
        self.assertNotIn("PASS", blob)

    def test_the_report_says_the_evidence_is_invalid(self):
        # Not merely silent about the pass: it must NAME the problem, or
        # the operator debugs their code instead of their verifier.
        outcome = self._run("TASK-M3")
        verification = " ".join(outcome.report.verification)
        self.assertIn("REJECTED", verification)
        self.assertIn("malformed-suite", verification)
        self.assertIn("invalid evidence", verification.lower())

    def test_the_problems_list_is_not_empty(self):
        # It was `()` in the reproduction, which is what made the report
        # read as an ordinary partial result.
        outcome = self._run("TASK-M4")
        self.assertEqual(outcome.report.problems_encountered, (MALFORMED_EVIDENCE_PROBLEM,))
        self.assertIn("neither True nor False", MALFORMED_EVIDENCE_PROBLEM)

    def test_a_malformed_result_is_not_confused_with_a_missing_one(self):
        # Two different broken states, two different messages: evidence
        # that arrived and was rejected is not evidence that never came.
        malformed = self._run("TASK-M5").report
        engine = TaskEngine(run_store=self.store, cli_runner=_CountingRunner(["succeed"]))
        missing = engine.execute_task(
            task_id="TASK-M6", objective="Demo", prompt="do it",
            repo_path=self.repo, verifier=_SilentVerifier(),
        ).report
        self.assertEqual(missing.problems_encountered, (NO_EVIDENCE_PROBLEM,))
        self.assertNotEqual(malformed.problems_encountered, missing.problems_encountered)
        self.assertNotEqual(malformed.verification, missing.verification)

    def test_the_ledger_does_not_present_it_as_a_valid_verification(self):
        outcome = self._run("TASK-M7")
        run_id = outcome.run_ids[-1]
        events = [e for e in self.store.ledger_for(run_id).read_all()
                  if e.event_type == "task.verification_result"]
        self.assertEqual(len(events), 1)
        recorded = events[0].data
        self.assertIs(recorded["passed"], False)
        self.assertEqual(recorded["verdict"], VerificationVerdict.MALFORMED.value)
        self.assertIn("neither True nor False", recorded["evidence"])
        # The rejected object is KEPT, but quarantined: a reader scanning
        # the top level for `passed` cannot pick up the `1`.
        self.assertEqual(recorded["rejected_result"]["passed"], 1)

    def test_a_real_pass_is_still_recorded_as_one(self):
        # The repair must not make every verification unreadable.
        engine = TaskEngine(run_store=self.store, cli_runner=_CountingRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-M8", objective="Demo", prompt="do it",
            repo_path=self.repo, verifier=passing_verifier(),
        )
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        self.assertEqual(outcome.report.verification, ("always-pass: PASSED",))
        run_id = outcome.run_ids[-1]
        recorded = self._recorded_verification(run_id)
        self.assertIs(recorded["passed"], True)
        self.assertEqual(recorded["verdict"], VerificationVerdict.PASSED.value)
        self.assertNotIn("rejected_result", recorded)

    def test_a_real_failure_is_still_recorded_as_one(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_CountingRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-M9", objective="Demo", prompt="do it",
            repo_path=self.repo, verifier=failing_verifier(),
        )
        self.assertEqual(outcome.report.verification, ("always-fail: FAILED",))
        run_id = outcome.run_ids[-1]
        recorded = self._recorded_verification(run_id)
        self.assertIs(recorded["passed"], False)
        self.assertEqual(recorded["verdict"], VerificationVerdict.FAILED.value)

    def test_a_falsy_malformed_passed_is_also_rejected_not_called_a_failure(self):
        # `passed=0` is the mirror case: still no verdict, and reporting
        # it as FAILED would invent one.
        outcome = self._run("TASK-M10", passed=0)
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertNotIn("FAILED", " ".join(outcome.report.verification))
        self.assertIn("REJECTED", " ".join(outcome.report.verification))

    def test_the_outcome_still_carries_the_rejected_object_for_forensics(self):
        # Rejecting it is not the same as hiding it. What must not
        # happen is a caller reading it as a pass, and the predicate is
        # what answers that question.
        outcome = self._run("TASK-M11")
        self.assertIsNotNone(outcome.verification)
        self.assertEqual(outcome.verification.passed, 1)
        self.assertFalse(completion_is_evidenced(outcome.verification))
        self.assertIs(
            verification_verdict(outcome.verification), VerificationVerdict.MALFORMED)


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


class _FixedVerifier(Verifier):
    """Answers with whatever it was handed, and counts its calls.

    Takes the ANSWER rather than a `passed` flag, so a member can return
    a malformed `VerificationResult`, a `MalformedEvidence`, or something
    that is neither — the three cases a composite has to tell apart.
    """

    def __init__(self, name: str, answer: object) -> None:
        self.name = name
        self.answer = answer
        self.calls = 0

    def run(self, cwd: Path):  # type: ignore[override]
        self.calls += 1
        return self.answer


def _result(name: str, passed: object) -> VerificationResult:
    """A `VerificationResult` whose `passed` is whatever was asked for.

    `passed=1` is DATA here, not a typo. A linter or a type checker
    "correcting" it to `True` would delete the defect under test.
    """
    return VerificationResult(
        name=name, passed=passed,  # type: ignore[arg-type]
        exit_code=0, duration_s=0.5,
        stdout_excerpt=f"{name} said so", stderr_excerpt=f"{name} stderr",
    )


def _member(name: str, passed: object) -> _FixedVerifier:
    return _FixedVerifier(name, _result(name, passed))


class TestACompositeCannotLaunderMalformedEvidence(unittest.TestCase):
    """The third F-34 review, at the level where it happened.

    Verified reproduction, before the repair:

        CompositeVerifier("composite", [child_with_passed_1]).run(...)
        -> VerificationResult(name='composite', passed=True, exit_code=0)
        -> verification_verdict(...) is PASSED
        -> TaskState.COMPLETED, ReportStatus.COMPLETED

    and

        CompositeVerifier("empty", []).run(...)
        -> VerificationResult(name='empty', passed=True)   # all([]) is True

    Both are DONEs minted from evidence nobody produced.
    """

    # -- an empty composite may not exist ---------------------------------

    def test_an_empty_composite_is_refused_at_construction(self):
        # Refused BEFORE anything can run, because a composite that can
        # never say anything meaningful is a construction error and not a
        # verification outcome.
        with self.assertRaises(EmptyCompositeError) as caught:
            CompositeVerifier("empty", [])
        self.assertIn("no verifiers", str(caught.exception))

    def test_the_empty_refusal_is_a_value_error(self):
        # Callers that guard broadly must still catch it.
        with self.assertRaises(ValueError):
            CompositeVerifier("empty", [])

    def test_an_empty_composite_never_reaches_run(self):
        # The reproduction ran `.run()` and got a pass. There is now no
        # object on which that call could be made.
        try:
            composite = CompositeVerifier("empty", ())
        except EmptyCompositeError:
            return
        self.fail(f"an empty composite was constructed: {composite!r}")

    def test_the_members_cannot_be_emptied_after_construction(self):
        # A refusal that holds only until somebody holds the object is
        # not a refusal: `verifiers.clear()` would restore `all([])`.
        composite = CompositeVerifier("composite", [_member("a", True)])
        self.assertIsInstance(composite.verifiers, tuple)
        with self.assertRaises(AttributeError):
            composite.verifiers.clear()  # type: ignore[attr-defined]

    def test_a_mutable_argument_is_copied_not_aliased(self):
        members = [_member("a", True)]
        composite = CompositeVerifier("composite", members)
        members.clear()
        self.assertEqual(len(composite.verifiers), 1)

    # -- aggregation, by verdict -----------------------------------------

    def test_two_passing_members_pass(self):
        composite = CompositeVerifier("composite", [_member("a", True),
                                                    _member("b", True)])
        evidence = composite.run(Path("."))
        self.assertIs(verification_verdict(evidence), VerificationVerdict.PASSED)
        self.assertIsInstance(evidence, VerificationResult)
        self.assertIs(evidence.passed, True)
        self.assertEqual(evidence.exit_code, 0)

    def test_a_passing_and_a_failing_member_fail(self):
        composite = CompositeVerifier("composite", [_member("a", True),
                                                    _member("b", False)])
        evidence = composite.run(Path("."))
        self.assertIs(verification_verdict(evidence), VerificationVerdict.FAILED)
        self.assertIs(evidence.passed, False)
        # The failing member's stderr is what an operator needs; the
        # passing one's is noise.
        self.assertIn("b stderr", evidence.stderr_excerpt)
        self.assertNotIn("a stderr", evidence.stderr_excerpt)

    def test_a_malformed_member_makes_the_composite_invalid_not_passed(self):
        # THE regression. `all(r.passed ...)` turned this into passed=True.
        composite = CompositeVerifier("composite", [_member("a", True),
                                                    _member("b", 1)])
        evidence = composite.run(Path("."))
        self.assertIs(verification_verdict(evidence), VerificationVerdict.MALFORMED)
        self.assertNotIsInstance(evidence, VerificationResult)
        self.assertIsInstance(evidence, MalformedEvidence)
        self.assertFalse(completion_is_evidenced(evidence))

    def test_a_lone_malformed_member_is_the_verbatim_reproduction(self):
        composite = CompositeVerifier("composite", [_member("only", 1)])
        self.assertIs(verification_verdict(composite.run(Path("."))),
                      VerificationVerdict.MALFORMED)

    def test_invalid_evidence_is_not_reported_as_an_ordinary_failure(self):
        # "your code is broken" and "your verifier is broken" send an
        # operator to different files. Collapsing them wastes the day.
        malformed = CompositeVerifier(
            "composite", [_member("a", True), _member("b", 1)]).run(Path("."))
        failed = CompositeVerifier(
            "composite", [_member("a", True), _member("b", False)]).run(Path("."))
        self.assertIsNot(verification_verdict(malformed),
                         verification_verdict(failed))
        self.assertIn("invalid evidence", malformed.reason)
        self.assertIn("b", malformed.reason)

    def test_a_falsy_malformed_member_is_also_invalid(self):
        # `passed=0` is the mirror case: still no verdict. Reading it as a
        # failure would invent one.
        composite = CompositeVerifier("composite", [_member("b", 0)])
        self.assertIs(verification_verdict(composite.run(Path("."))),
                      VerificationVerdict.MALFORMED)

    def test_a_member_that_is_not_a_result_at_all_is_invalid(self):
        composite = CompositeVerifier(
            "composite", [_member("a", True),
                          _FixedVerifier("ducky", "looks fine to me")])
        self.assertIs(verification_verdict(composite.run(Path("."))),
                      VerificationVerdict.MALFORMED)

    def test_a_member_that_answers_with_nothing_is_invalid(self):
        composite = CompositeVerifier(
            "composite", [_member("a", True), _FixedVerifier("silent", None)])
        self.assertIs(verification_verdict(composite.run(Path("."))),
                      VerificationVerdict.MALFORMED)

    def test_a_nested_composite_cannot_launder_through_a_layer(self):
        # One level of aggregation is not special. A composite whose
        # member is a composite whose member is malformed must still be
        # invalid, or the hole reopens one indirection down.
        inner = CompositeVerifier("inner", [_member("bad", 1)])
        outer = CompositeVerifier("outer", [_member("a", True), inner])
        self.assertIs(verification_verdict(outer.run(Path("."))),
                      VerificationVerdict.MALFORMED)

    # -- what is preserved -------------------------------------------------

    def test_the_rejected_members_are_kept_for_forensics(self):
        composite = CompositeVerifier("composite", [_member("a", True),
                                                    _member("b", 1)])
        evidence = composite.run(Path("."))
        raws = [child["raw"] for child in evidence.children]
        # The raw child may still carry `passed: 1` — that is the point of
        # keeping it. What must not happen is anything DECIDING on it,
        # which is why the verdict travels beside it already read.
        self.assertIn(1, [raw.get("passed") for raw in raws])
        self.assertIn(VerificationVerdict.MALFORMED.value,
                      [child["verdict"] for child in evidence.children])

    def test_the_serialized_composite_has_no_passed_key_to_misread(self):
        evidence = CompositeVerifier("composite", [_member("b", 1)]).run(Path("."))
        payload = evidence.to_dict()
        self.assertNotIn("passed", payload)
        self.assertEqual(payload["verdict"], VerificationVerdict.MALFORMED.value)

    def test_every_member_still_runs_before_the_verdict_is_formed(self):
        # A composite that short-circuits on the first malformed member
        # would hide the state of the others, and the operator would fix
        # them one round at a time.
        good, bad = _member("a", True), _member("b", 1)
        CompositeVerifier("composite", [bad, good]).run(Path("."))
        self.assertEqual((good.calls, bad.calls), (1, 1))


class TestTheEngineDoesNotCompleteOnACompositeVerifier(_RepoTestCase):
    """Reproduction 1 of the third review, end to end through `TaskEngine`."""

    def _run(self, task_id: str, verifier: Verifier):
        engine = TaskEngine(run_store=self.store, cli_runner=_CountingRunner(["succeed"]))
        return engine.execute_task(
            task_id=task_id, objective="Demo", prompt="do it",
            repo_path=self.repo, verifier=verifier,
        )

    def test_a_composite_with_a_malformed_member_does_not_complete(self):
        outcome = self._run("TASK-C1",
                            CompositeVerifier("composite", [_member("bad", 1)]))
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertNotEqual(outcome.report.status, ReportStatus.COMPLETED)

    def test_the_report_never_calls_it_a_pass(self):
        outcome = self._run("TASK-C2",
                            CompositeVerifier("composite", [_member("bad", 1)]))
        blob = " ".join((
            *outcome.report.verification,
            *outcome.report.problems_encountered,
            *outcome.report.work_completed,
            outcome.report.recommended_next_step,
        ))
        self.assertNotIn("PASSED", blob)
        self.assertNotIn("PASS", blob)

    def test_the_report_names_the_member_that_broke_it(self):
        outcome = self._run("TASK-C3",
                            CompositeVerifier("composite", [_member("bad", 1)]))
        verification = " ".join(outcome.report.verification)
        self.assertIn("REJECTED", verification)
        self.assertIn("invalid evidence", verification.lower())
        self.assertIn("bad", verification)

    def test_the_problems_list_is_not_empty(self):
        outcome = self._run("TASK-C4",
                            CompositeVerifier("composite", [_member("bad", 1)]))
        self.assertTrue(outcome.report.problems_encountered)
        self.assertIn("records no verdict",
                      " ".join(outcome.report.problems_encountered))

    def test_the_ledger_does_not_present_it_as_a_valid_verification(self):
        outcome = self._run("TASK-C5",
                            CompositeVerifier("composite", [_member("bad", 1)]))
        events = [e for e in self.store.ledger_for(outcome.run_ids[-1]).read_all()
                  if e.event_type == "task.verification_result"]
        self.assertEqual(len(events), 1)
        recorded = events[0].data
        self.assertIs(recorded["passed"], False)
        self.assertEqual(recorded["verdict"], VerificationVerdict.MALFORMED.value)
        self.assertIn("records no verdict", recorded["evidence"])
        # Kept, quarantined: the rejected members remain inspectable.
        self.assertIn("children", recorded["rejected_result"])

    def test_a_composite_of_real_passing_verifiers_still_completes(self):
        # The repair must not make every composite unusable.
        outcome = self._run("TASK-C6", CompositeVerifier(
            "composite", [passing_verifier(), passing_verifier()]))
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        self.assertEqual(outcome.report.verification, ("composite: PASSED",))

    def test_a_composite_with_a_real_failure_still_fails_as_a_failure(self):
        outcome = self._run("TASK-C7", CompositeVerifier(
            "composite", [passing_verifier(), failing_verifier()]))
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertEqual(outcome.report.verification, ("composite: FAILED",))


class TestConvergenceRefusesMalformedEvidence(unittest.TestCase):
    """`ConvergenceLoop` may not converge on evidence that states no verdict.

    Before the repair the loop's clean predicate read
    `verification is not None and verification.passed`, so a `passed` of
    `1` converged the loop — and a converged loop is what the Director
    turns into `ReportStatus.COMPLETED`.
    """

    def _loop(self, verification: object, max_rounds: int = 2) -> ConvergenceLoop:
        return ConvergenceLoop(
            ConvergencePolicy(max_rounds=max_rounds, max_unchanged_rounds=3),
            verify_fn=lambda: verification,  # type: ignore[arg-type,return-value]
            review_fn=lambda index: ReviewReport(verdict=ReviewVerdict.PASS,
                                                 reviewer="independent"),
            fix_fn=lambda request: FixReport(claims_done=True),
            fingerprint_fn=lambda: "fp-unchanged",
        )

    def test_a_truthy_passed_does_not_converge(self):
        result = self._loop(_result("suite", 1)).run()
        self.assertIsNot(result.outcome, ConvergenceOutcome.CONVERGED)

    def test_a_malformed_evidence_object_does_not_converge(self):
        malformed = CompositeVerifier("composite", [_member("bad", 1)]).run(Path("."))
        self.assertIsNot(self._loop(malformed).run().outcome,
                         ConvergenceOutcome.CONVERGED)

    def test_the_failure_is_typed_and_named(self):
        result = self._loop(_result("suite", 1)).run()
        stages = {(f.stage, f.error_type) for f in result.evidence_failures}
        self.assertIn(("verification", "MalformedEvidence"), stages)

    def test_a_round_on_invalid_evidence_does_not_count_toward_stalemate(self):
        # A broken verifier is not a stuck repo. Counting it would file a
        # STALEMATE that sends the operator to look at the diff.
        result = self._loop(_result("suite", 1), max_rounds=6).run()
        self.assertIsNot(result.outcome, ConvergenceOutcome.STALEMATE)
        self.assertTrue(all(record.unchanged_streak == 0
                            for record in result.rounds))

    def test_no_round_is_marked_as_having_complete_evidence(self):
        result = self._loop(_result("suite", 1)).run()
        self.assertTrue(all(not record.evidence_ok for record in result.rounds))

    def test_a_real_pass_still_converges(self):
        result = self._loop(_result("suite", True)).run()
        self.assertIs(result.outcome, ConvergenceOutcome.CONVERGED)

    def test_a_real_failure_still_produces_an_ordinary_round(self):
        # Not an evidence failure: a FAILED verification IS evidence, and
        # the fixer must be asked to act on it.
        fixes: list[object] = []
        loop = ConvergenceLoop(
            ConvergencePolicy(max_rounds=1),
            verify_fn=lambda: _result("suite", False),
            review_fn=lambda index: ReviewReport(verdict=ReviewVerdict.PASS,
                                                 reviewer="independent"),
            fix_fn=lambda request: (fixes.append(request), FixReport())[1],
            fingerprint_fn=lambda: "fp",
        )
        result = loop.run()
        self.assertIsNot(result.outcome, ConvergenceOutcome.CONVERGED)
        self.assertEqual(len(fixes), 1)
        self.assertEqual(result.evidence_failures, ())


class TestTheFixPromptTellsTheAgentWhichThingIsBroken(unittest.TestCase):
    """Rule: a review message may not describe MALFORMED as a code failure.

    `build_fix_prompt` tested `not request.verification.passed`, so a
    `passed` of `1` printed nothing at all — the fixer was told the round
    was clean while the kernel had thrown the evidence out.
    """

    def test_a_failing_verification_says_the_code_must_pass(self):
        line = verification_prompt_line(_result("suite", False))
        self.assertIsNotNone(line)
        self.assertIn("FAILING", line)

    def test_invalid_evidence_says_the_verifier_is_the_problem(self):
        line = verification_prompt_line(_result("suite", 1))
        self.assertIsNotNone(line)
        self.assertIn("INVALID EVIDENCE", line)
        self.assertIn("do not start by editing it", line)

    def test_the_two_messages_are_not_the_same(self):
        self.assertNotEqual(verification_prompt_line(_result("suite", False)),
                            verification_prompt_line(_result("suite", 1)))

    def test_invalid_evidence_is_not_described_as_failing(self):
        line = verification_prompt_line(_result("suite", 1))
        self.assertNotIn("currently FAILING", line)

    def test_a_composite_that_states_no_verdict_is_described_as_invalid(self):
        malformed = CompositeVerifier("composite", [_member("bad", 1)]).run(Path("."))
        line = verification_prompt_line(malformed)
        self.assertIn("INVALID EVIDENCE", line)
        self.assertIn("records no verdict", line)

    def test_a_passing_verification_says_nothing(self):
        self.assertIsNone(verification_prompt_line(_result("suite", True)))

    def test_no_verification_says_nothing(self):
        self.assertIsNone(verification_prompt_line(None))
