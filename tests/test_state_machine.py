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


if __name__ == "__main__":
    unittest.main()
