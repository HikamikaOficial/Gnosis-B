import unittest

from gnosis.kernel.state_machine import (
    IllegalTransitionError,
    RunState,
    RunStateMachine,
    TaskState,
    TaskStateMachine,
)


class TestTaskStateMachine(unittest.TestCase):
    def test_happy_path(self):
        sm = TaskStateMachine()
        sm.transition(TaskState.PLANNED)
        sm.transition(TaskState.IN_PROGRESS)
        sm.transition(TaskState.VERIFYING)
        sm.transition(TaskState.COMPLETED)
        self.assertEqual(sm.state, TaskState.COMPLETED)
        self.assertTrue(sm.is_terminal())

    def test_illegal_transition_raises(self):
        sm = TaskStateMachine()
        with self.assertRaises(IllegalTransitionError):
            sm.transition(TaskState.COMPLETED)

    def test_terminal_states_have_no_exits(self):
        for terminal in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
            sm = TaskStateMachine(terminal)
            with self.assertRaises(IllegalTransitionError):
                sm.transition(TaskState.IN_PROGRESS)


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
        sm = TaskStateMachine()
        try:
            sm.transition(TaskState.COMPLETED)
        except IllegalTransitionError as exc:
            self.assertEqual(exc.current, TaskState.CREATED)
            self.assertEqual(exc.target, TaskState.COMPLETED)
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
