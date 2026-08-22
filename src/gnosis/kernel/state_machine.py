"""Explicit, auditable task/run state machines.

No state transition happens implicitly — callers must go through
`TaskStateMachine.transition` / `RunStateMachine.transition`, which raise
`IllegalTransitionError` on anything not in the allowed table. This is the
mechanism that satisfies the constitution's "no silent architectural drift"
and "auditable actions" principles at the state level.

**`COMPLETED` is not reachable through `transition()` at all.** It is the
one state that means "this task is DONE", and constitution rule 2 says a
DONE requires evidence. ADR-0025 put that check in the engine, and an
independent review was right that it left the authority itself open: the
generic transition still walked `VERIFYING -> COMPLETED` for anyone who
asked, so the guarantee held only for the one caller that happened to
carry the guard. It is now a property of this module:

- `transition()` REFUSES every target in `EVIDENCE_GATED_STATES`;
- `complete(verification)` is the only route, and it validates the
  `VerificationResult` it is handed rather than trusting a flag;
- a machine cannot be CONSTRUCTED in `COMPLETED` either;
- `state` and `completion_evidence` are READ-ONLY properties, so the
  guarded methods are not merely the recommended route but the only one
  the public API offers.

That last point was a second finding, and it is worth stating why it
was not obvious. Two rounds of review had hardened the doors —
constructor, `transition()`, `complete()` — while the field behind them
stayed a plain attribute. `sm.state = TaskState.COMPLETED` reached a
terminal DONE with `completion_evidence` still None, past every check.
A guard is only as good as the thing it guards being unreachable
otherwise.

**Scope of the guarantee, stated honestly.** What this module
guarantees is a property of its PUBLIC API: no sequence of public
attribute assignments and public method calls reaches `COMPLETED`
without a passing `VerificationResult`. It is NOT tamper-proofing.
`sm._state = ...`, `object.__setattr__`, `sm.__dict__`, monkeypatching
and every other deliberate reach past the underscore still work, and
Python offers no way to stop them that is worth the cost. The threat
this addresses is the realistic one — an agent, a refactor or a caller
taking the cheap route by accident — not an adversary inside the
process, who has already lost the game by being there.

The transitions table still lists `VERIFYING -> COMPLETED`, because that
edge really is part of the state graph. What the table describes is
which edges exist; what `EVIDENCE_GATED_STATES` describes is which of
them a caller may take without showing its work.
"""
from __future__ import annotations

from enum import Enum
from types import MappingProxyType

from .verification import VerificationResult, VerificationVerdict, verification_verdict


class IllegalTransitionError(RuntimeError):
    """Carries (current, target, allowed_next) so every surface — CLI,
    transport, adapter — can report the same complete verdict without
    re-deriving the rules (archaeology Directive 3)."""

    def __init__(self, current: Enum, target: Enum, kind: str, allowed_next: frozenset[Enum],
                 message: str | None = None):
        allowed = ", ".join(sorted(state.value for state in allowed_next)) or "(terminal)"
        super().__init__(message or (
            f"Illegal {kind} transition: {current.value} -> {target.value}; "
            f"allowed next: {allowed}"
        ))
        self.current = current
        self.target = target
        self.allowed_next = allowed_next


class UnevidencedCompletionError(IllegalTransitionError):
    """`COMPLETED` was requested without a passing `VerificationResult`.

    A subclass of `IllegalTransitionError` on purpose: anything already
    catching illegal transitions keeps failing closed rather than letting
    a new exception type escape as an unhandled crash. The distinct type
    exists so an operator can tell "you took the wrong route" and "your
    evidence does not hold" apart, which are different mistakes.
    """

    def __init__(self, current: TaskState, reason: str):
        allowed: frozenset[Enum] = frozenset(
            TASK_TRANSITIONS.get(current, frozenset()))
        super().__init__(
            current, TaskState.COMPLETED, "task", allowed,
            message=(
                f"Refused {current.value} -> COMPLETED: {reason}. A task reaches "
                "COMPLETED only through TaskStateMachine.complete(verification), "
                "which requires a VerificationResult whose `passed` is True "
                "(constitution rule 2: no DONE without evidence). "
                # Directive 3: every surface reports the same complete verdict,
                # so the gated refusal carries the same tail as the generic one.
                f"allowed next: "
                + (", ".join(sorted(s.value for s in allowed)) or "(terminal)")
            ),
        )
        self.reason = reason


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

# States the generic `transition()` may never take, because arriving at
# them is a CLAIM that has to be backed by evidence the state machine
# examines for itself. Each one needs its own admitting method.
#
# Only `COMPLETED` is listed, and that is the point: FAILED, CANCELLED
# and the rest are statements about work NOT finishing, which nobody has
# an incentive to forge. A DONE is the one an agent, a bug or a hopeful
# caller would like to reach cheaply.
EVIDENCE_GATED_STATES = frozenset({TaskState.COMPLETED})


def completion_is_evidenced(verification: VerificationResult | None) -> bool:
    """The predicate `complete()` applies. Nothing reaches COMPLETED past it.

    Constitution rule 2: no task reaches DONE without evidence. This
    lives beside the state authority rather than in a caller, because
    ADR-0025 put it in `TaskEngine` and an independent review
    demonstrated the gap that leaves — the machine itself still walked
    `VERIFYING -> COMPLETED` for anybody who asked, so the invariant was
    a property of one caller rather than of the kernel.

    What it refuses, and why each refusal is load-bearing:

    - **`None`.** The original defect read
      ``verification_result.passed if verification_result else True``,
      converting "nobody checked" into "it passed". Absence of evidence
      is not success.
    - **Anything that is not a `VerificationResult`.** `Verifier` is an
      ABC but a duck-typed one costs nothing to pass, and a stand-in that
      returns `None` — or a truthy object — must not mint a DONE the
      kernel cannot read. Typing is not enforcement (L-0039).
    - **A `passed` that is not exactly `True`.** `bool` IS an `int` in
      Python, so `1`, a non-empty string and every other truthy value
      would pass a bare check. `failures.py` already had to learn this
      for exit codes; the flag that closes a task deserves the same care.

    The rules above are no longer spelled out here: `verification_verdict`
    is the one function that interprets `passed`, and this predicate is
    the question "did it say PASSED?" asked of it. They used to be two
    independent readings of the same field, which is how a second review
    found the authority refusing a `passed` of `1` while the report of
    that same task printed it as a pass.
    """
    return verification_verdict(verification) is VerificationVerdict.PASSED


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
        # A machine cannot START in an evidence-gated state either. Without
        # this, `TaskStateMachine(TaskState.COMPLETED)` is a side door that
        # makes the guarantee below carry an asterisk, and the whole reason
        # this unit exists is that the previous claim carried one nobody
        # had written down. There is no rehydration-from-durable-state path
        # in this repo today (TaskState is not persisted — F-07); when one
        # arrives it must arrive WITH the evidence, through `complete()`.
        if initial in EVIDENCE_GATED_STATES:
            raise UnevidencedCompletionError(
                initial, "a task cannot be constructed already COMPLETED"
            )
        self._state = initial
        # The evidence that authorised this task's DONE, or None while it
        # has not earned one. Set only by `complete()`, so a caller can ask
        # WHAT proved the task rather than trusting that something did.
        self._completion_evidence: VerificationResult | None = None

    @property
    def state(self) -> TaskState:
        """Read-only. Every write goes through `transition()`/`complete()`.

        The second independent review of ADR-0025 found the gate closed
        and the wall missing: `transition()` and `complete()` both
        refused an unevidenced DONE, and then

            sm = TaskStateMachine(TaskState.VERIFYING)
            sm.state = TaskState.COMPLETED

        put the machine in a terminal COMPLETED with
        `completion_evidence` still None. A guard on the doors is not a
        guarantee while the field they guard is public.
        """
        return self._state

    @property
    def completion_evidence(self) -> VerificationResult | None:
        """Read-only, and set only by `complete()`.

        Writable, this was the other half of the same hole: evidence
        could be attached to a task that never earned it, or detached
        from one that did, without the authority ever being asked.
        """
        return self._completion_evidence

    def transition(self, target: TaskState) -> TaskState:
        # The generic route may not reach an evidence-gated state. This is
        # the hole the independent review of ADR-0025 found: the engine
        # carried the guard, so the invariant was true of ONE caller and
        # of nothing else. `sm.transition(TaskState.COMPLETED)` walked
        # straight through, and a test asserted that it did.
        if target in EVIDENCE_GATED_STATES:
            raise UnevidencedCompletionError(
                self.state, "transition() carries no evidence"
            )
        self._state = _transition(self._state, target, TASK_TRANSITIONS, "task")
        return self._state

    def complete(self, verification: VerificationResult) -> TaskState:
        """The ONLY route to `COMPLETED`, and it validates what it is handed.

        Takes the `VerificationResult` itself, never a boolean: a flag
        computed by the caller moves the decision back to the caller,
        which is exactly the arrangement that failed. The object is
        re-examined here, so a caller that miscomputed — or never
        computed — is refused rather than believed.

        The ordinary transition rules still apply on top: reaching
        COMPLETED from anywhere other than `VERIFYING` is an illegal edge
        whatever evidence accompanies it, because a task that never
        verified has nothing this result could be evidence *of*.
        """
        if not completion_is_evidenced(verification):
            raise UnevidencedCompletionError(
                self.state,
                f"the verification offered is not a passing VerificationResult "
                f"({type(verification).__name__})",
            )
        # `_transition` is still consulted: evidence authorises the CLAIM,
        # it does not authorise skipping the graph.
        self._state = _transition(self._state, TaskState.COMPLETED, TASK_TRANSITIONS, "task")
        self._completion_evidence = verification
        return self._state

    def is_terminal(self) -> bool:
        return self._state in TASK_TERMINAL_STATES


class RunStateMachine:
    """Same read-only discipline as `TaskStateMachine`, for the same reason.

    No run state is evidence-gated — nothing forges a SUCCEEDED into a
    DONE, the task authority still has to be satisfied separately — so
    this is consistency, not a second gate. It is here because "the
    state of a state machine is not publicly writable" should be a
    property of this module rather than of whichever class a reviewer
    happened to probe.
    """

    def __init__(self, initial: RunState = RunState.PENDING):
        self._state = initial

    @property
    def state(self) -> RunState:
        return self._state

    def transition(self, target: RunState) -> RunState:
        self._state = _transition(self._state, target, RUN_TRANSITIONS, "run")
        return self._state

    def is_terminal(self) -> bool:
        return self._state in RUN_TERMINAL_STATES
