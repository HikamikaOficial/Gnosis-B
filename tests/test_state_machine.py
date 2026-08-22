import unittest

from gnosis.kernel.state_machine import (
    EVIDENCE_GATED_STATES,
    IllegalTransitionError,
    RunState,
    RunStateMachine,
    TaskState,
    TaskStateMachine,
    UnevidencedCompletionError,
)
from gnosis.kernel.verification import VerificationResult


def _passed() -> VerificationResult:
    return VerificationResult(
        name="suite", passed=True, exit_code=0, duration_s=0.1,
        stdout_excerpt="ok", stderr_excerpt="",
    )


def _failed() -> VerificationResult:
    return VerificationResult(
        name="suite", passed=False, exit_code=1, duration_s=0.1,
        stdout_excerpt="", stderr_excerpt="2 failed",
    )


class TestTaskStateMachine(unittest.TestCase):
    def test_happy_path(self):
        # REWRITTEN. This test used to end with
        # `sm.transition(TaskState.COMPLETED)` and assert it worked — it
        # was the test that LEGITIMISED reaching a DONE with no evidence,
        # and an independent review of ADR-0025 used it as the proof that
        # the invariant lived in the engine rather than in the authority.
        # The happy path now goes through the only door there is.
        sm = TaskStateMachine()
        sm.transition(TaskState.PLANNED)
        sm.transition(TaskState.IN_PROGRESS)
        sm.transition(TaskState.VERIFYING)
        sm.complete(_passed())
        self.assertEqual(sm.state, TaskState.COMPLETED)
        self.assertTrue(sm.is_terminal())
        # And the machine can name what proved it, rather than only that
        # something did.
        self.assertIs(sm.completion_evidence.passed, True)
        self.assertEqual(sm.completion_evidence.name, "suite")

    def test_illegal_transition_raises(self):
        sm = TaskStateMachine()
        with self.assertRaises(IllegalTransitionError):
            sm.transition(TaskState.COMPLETED)

    def test_terminal_states_have_no_exits(self):
        # COMPLETED is reached the only way it can be; the others are
        # still constructible directly, because nothing forges a FAILED.
        completed = TaskStateMachine(TaskState.VERIFYING)
        completed.complete(_passed())
        machines = [completed]
        machines += [TaskStateMachine(t) for t in (TaskState.FAILED, TaskState.CANCELLED)]
        for sm in machines:
            with self.subTest(state=sm.state), self.assertRaises(IllegalTransitionError):
                sm.transition(TaskState.IN_PROGRESS)


class TestCompletedIsEvidenceGated(unittest.TestCase):
    """The authority itself refuses a DONE it cannot see evidence for.

    ADR-0025 placed this check in `TaskEngine`. That made it true of one
    caller. An independent review reproduced `CREATED -> PLANNED ->
    IN_PROGRESS -> VERIFYING -> COMPLETED` on a bare `TaskStateMachine`
    and got COMPLETED, with no evidence anywhere. These tests are what
    make the claim a property of the kernel instead.
    """

    def _verifying(self) -> TaskStateMachine:
        sm = TaskStateMachine()
        sm.transition(TaskState.PLANNED)
        sm.transition(TaskState.IN_PROGRESS)
        sm.transition(TaskState.VERIFYING)
        return sm

    def test_the_generic_transition_can_never_reach_completed(self):
        # THE regression, from every state the graph allows it from.
        sm = self._verifying()
        with self.assertRaises(UnevidencedCompletionError) as ctx:
            sm.transition(TaskState.COMPLETED)
        self.assertEqual(sm.state, TaskState.VERIFYING)   # nothing moved
        self.assertIn("complete(verification)", str(ctx.exception))

    def test_the_reproduction_from_the_independent_review_now_fails(self):
        sm = TaskStateMachine()
        for target in (TaskState.PLANNED, TaskState.IN_PROGRESS, TaskState.VERIFYING):
            sm.transition(target)
        with self.assertRaises(UnevidencedCompletionError):
            sm.transition(TaskState.COMPLETED)
        self.assertNotEqual(sm.state, TaskState.COMPLETED)

    def test_an_unevidenced_completion_is_still_an_illegal_transition(self):
        # Subclassing matters: a caller that already catches
        # IllegalTransitionError keeps failing closed.
        sm = self._verifying()
        with self.assertRaises(IllegalTransitionError):
            sm.transition(TaskState.COMPLETED)

    def test_none_is_refused(self):
        sm = self._verifying()
        with self.assertRaises(UnevidencedCompletionError):
            sm.complete(None)
        self.assertEqual(sm.state, TaskState.VERIFYING)
        self.assertIsNone(sm.completion_evidence)

    def test_a_failing_verification_is_refused(self):
        sm = self._verifying()
        with self.assertRaises(UnevidencedCompletionError):
            sm.complete(_failed())
        self.assertEqual(sm.state, TaskState.VERIFYING)

    def test_an_impostor_object_is_refused(self):
        class _LooksRight:
            name = "suite"
            passed = True
            exit_code = 0

        for impostor in (_LooksRight(), {"passed": True}, "PASSED", 1, True, object()):
            with self.subTest(impostor=type(impostor).__name__):
                sm = self._verifying()
                with self.assertRaises(UnevidencedCompletionError):
                    sm.complete(impostor)
                self.assertEqual(sm.state, TaskState.VERIFYING)

    def test_a_truthy_passed_is_not_true_enough(self):
        sm = self._verifying()
        with self.assertRaises(UnevidencedCompletionError):
            sm.complete(VerificationResult(
                name="suite", passed=1, exit_code=0, duration_s=0.0,
                stdout_excerpt="", stderr_excerpt="",
            ))
        self.assertEqual(sm.state, TaskState.VERIFYING)

    def test_only_a_passing_verification_result_completes(self):
        sm = self._verifying()
        self.assertEqual(sm.complete(_passed()), TaskState.COMPLETED)
        self.assertEqual(sm.state, TaskState.COMPLETED)

    def test_evidence_does_not_authorise_skipping_the_graph(self):
        # A task that never verified has nothing this result is evidence
        # OF. Real evidence, illegal edge, still refused.
        sm = TaskStateMachine()
        sm.transition(TaskState.PLANNED)
        with self.assertRaises(IllegalTransitionError):
            sm.complete(_passed())
        self.assertEqual(sm.state, TaskState.PLANNED)

    def test_a_machine_cannot_be_constructed_already_completed(self):
        # The side door. Without this the guarantee carries an asterisk,
        # and an unwritten asterisk is what this whole unit is repairing.
        with self.assertRaises(UnevidencedCompletionError):
            TaskStateMachine(TaskState.COMPLETED)

    def test_the_gate_names_exactly_which_states_it_covers(self):
        # Pinned, so widening or narrowing it is a deliberate edit.
        self.assertEqual(EVIDENCE_GATED_STATES, frozenset({TaskState.COMPLETED}))

    def test_the_graph_still_describes_the_edge_it_gates(self):
        # The table says which edges EXIST; the gate says which a caller
        # may take unaided. Removing the edge would make the table lie.
        from gnosis.kernel.state_machine import TASK_TRANSITIONS
        self.assertIn(TaskState.COMPLETED, TASK_TRANSITIONS[TaskState.VERIFYING])


class TestRunStateMachine(unittest.TestCase):
    def test_happy_path(self):
        sm = RunStateMachine()
        sm.transition(RunState.RUNNING)
        sm.transition(RunState.SUCCEEDED)
        self.assertTrue(sm.is_terminal())

    def test_crash_path(self):
        sm = RunStateMachine()
        sm.transition(RunState.RUNNING)
        sm.transition(RunState.CRASHED)
        self.assertTrue(sm.is_terminal())

    def test_illegal_transition_raises(self):
        sm = RunStateMachine()
        with self.assertRaises(IllegalTransitionError):
            sm.transition(RunState.SUCCEEDED)


class TestTransitionTableHardening(unittest.TestCase):
    """Directive 3: the allow-list is immutable data, and the typed error
    carries (from, to, allowed_next) so every surface reports the same
    complete verdict."""

    def test_transition_tables_are_immutable(self):
        from gnosis.kernel.state_machine import RUN_TRANSITIONS, TASK_TRANSITIONS
        with self.assertRaises(TypeError):
            TASK_TRANSITIONS[TaskState.COMPLETED] = frozenset({TaskState.CREATED})
        with self.assertRaises(TypeError):
            RUN_TRANSITIONS[RunState.SUCCEEDED] = frozenset({RunState.PENDING})

    def test_illegal_transition_error_carries_allowed_next(self):
        # Uses an edge that is illegal for GRAPH reasons. COMPLETED is
        # now refused for EVIDENCE reasons before the table is even
        # consulted, which is a different verdict and has its own test.
        sm = TaskStateMachine()
        try:
            sm.transition(TaskState.VERIFYING)
        except IllegalTransitionError as exc:
            self.assertEqual(exc.current, TaskState.CREATED)
            self.assertEqual(exc.target, TaskState.VERIFYING)
            self.assertEqual(exc.allowed_next, frozenset({TaskState.PLANNED, TaskState.CANCELLED}))
            self.assertIn("allowed next:", str(exc))
        else:
            self.fail("expected IllegalTransitionError")

    def test_terminal_state_error_reports_terminal(self):
        sm = RunStateMachine(initial=RunState.SUCCEEDED)
        try:
            sm.transition(RunState.RUNNING)
        except IllegalTransitionError as exc:
            self.assertEqual(exc.allowed_next, frozenset())
            self.assertIn("(terminal)", str(exc))
        else:
            self.fail("expected IllegalTransitionError")


if __name__ == "__main__":
    unittest.main()
