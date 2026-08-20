"""Explicit, auditable task/run state machines.

No state transition happens implicitly — callers must go through
`TaskStateMachine.transition` / `RunStateMachine.transition`, which raise
`IllegalTransitionError` on anything not in the allowed table. This is the
mechanism that satisfies the constitution's "no silent architectural drift"
and "auditable actions" principles at the state level.
"""
from __future__ import annotations

from enum import Enum
from types import MappingProxyType


class IllegalTransitionError(RuntimeError):
    """Carries (current, target, allowed_next) so every surface — CLI,
    transport, adapter — can report the same complete verdict without
    re-deriving the rules (archaeology Directive 3)."""

    def __init__(self, current: Enum, target: Enum, kind: str, allowed_next: frozenset[Enum]):
        allowed = ", ".join(sorted(state.value for state in allowed_next)) or "(terminal)"
        super().__init__(
            f"Illegal {kind} transition: {current.value} -> {target.value}; "
            f"allowed next: {allowed}"
        )
        self.current = current
        self.target = target
        self.allowed_next = allowed_next


class TaskState(str, Enum):
    CREATED = "CREATED"
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFYING = "VERIFYING"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# The transition tables live once, as immutable data (MappingProxyType of
# frozensets): every surface imports them, none can mutate them.
TASK_TRANSITIONS: MappingProxyType[TaskState, frozenset[TaskState]] = MappingProxyType({
    TaskState.CREATED: frozenset({TaskState.PLANNED, TaskState.CANCELLED}),
    TaskState.PLANNED: frozenset({TaskState.IN_PROGRESS, TaskState.BLOCKED, TaskState.CANCELLED}),
    TaskState.IN_PROGRESS: frozenset({
        TaskState.VERIFYING, TaskState.BLOCKED, TaskState.ESCALATED,
        TaskState.FAILED, TaskState.CANCELLED,
    }),
    TaskState.VERIFYING: frozenset({TaskState.COMPLETED, TaskState.IN_PROGRESS, TaskState.FAILED}),
    TaskState.BLOCKED: frozenset({TaskState.IN_PROGRESS, TaskState.ESCALATED, TaskState.CANCELLED}),
    TaskState.ESCALATED: frozenset({TaskState.IN_PROGRESS, TaskState.BLOCKED, TaskState.CANCELLED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELLED: frozenset(),
})

TASK_TERMINAL_STATES = frozenset({TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED})


class RunState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    CRASHED = "CRASHED"
    # A durable PARK, not a failure (constitution rule 6): the run stopped
    # because a credential's window is shut, and it must be distinguishable
    # from FAILED on disk or the park exists only in memory (ADR-0012).
    # Non-terminal: it resumes when the window reopens.
    RATE_LIMITED = "RATE_LIMITED"


RUN_TRANSITIONS: MappingProxyType[RunState, frozenset[RunState]] = MappingProxyType({
    RunState.PENDING: frozenset({RunState.RUNNING, RunState.CANCELLED}),
    RunState.RUNNING: frozenset({
        RunState.SUCCEEDED, RunState.FAILED, RunState.TIMED_OUT,
        RunState.CANCELLED, RunState.CRASHED, RunState.RATE_LIMITED,
    }),
    # A parked run resumes through the normal path, or is cancelled.
    RunState.RATE_LIMITED: frozenset({RunState.RUNNING, RunState.CANCELLED}),
    RunState.SUCCEEDED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.TIMED_OUT: frozenset(),
    RunState.CANCELLED: frozenset(),
    RunState.CRASHED: frozenset(),
})

RUN_TERMINAL_STATES = frozenset({
    RunState.SUCCEEDED, RunState.FAILED, RunState.TIMED_OUT,
    RunState.CANCELLED, RunState.CRASHED,
})


# Generic over the concrete state enum so TaskStateMachine/RunStateMachine
# get back their own state type from _transition, not a bare Enum.
def _transition[StateT: Enum](
    current: StateT, target: StateT, table: MappingProxyType[StateT, frozenset[StateT]], kind: str,
) -> StateT:
    allowed = table.get(current, frozenset())
    if target not in allowed:
        raise IllegalTransitionError(current, target, kind, frozenset(allowed))
    return target


class TaskStateMachine:
    def __init__(self, initial: TaskState = TaskState.CREATED):
        self.state = initial

    def transition(self, target: TaskState) -> TaskState:
        self.state = _transition(self.state, target, TASK_TRANSITIONS, "task")
        return self.state

    def is_terminal(self) -> bool:
        return self.state in TASK_TERMINAL_STATES


class RunStateMachine:
    def __init__(self, initial: RunState = RunState.PENDING):
        self.state = initial

    def transition(self, target: RunState) -> RunState:
        self.state = _transition(self.state, target, RUN_TRANSITIONS, "run")
        return self.state

    def is_terminal(self) -> bool:
        return self.state in RUN_TERMINAL_STATES
