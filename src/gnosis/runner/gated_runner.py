"""Every agent launch passes the gate, not just the first one.

ADR-0013 wired the policy gate into `TaskEngine.execute_task`, which
covers the launch that implements a task. A convergence loop then
launches a reviewer and a fixer once per round — potentially many more
agents than the task itself — and none of those went past a gate or a
rate-limit hold. The gate was real and its coverage was partial, which
is a worse position than it sounds: it reads as governed.

`GatedAgentRunner` duck-types a CLI runner and consults, before each
launch:

1. the **hold plane**, so a shut credential parks the round instead of
   burning it (rule 6), and
2. the **policy engine**, at the same `before_agent_run` intervention
   point and with the same snapshot shape the engine uses — so an
   operator approving an action approves one identity, not two.

A refusal raises. It does not return a fake result, because the caller's
contract is "here is what the agent said" and inventing that is the one
thing the whole review apparatus exists to prevent.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from ..kernel.budget import BudgetLedger
from ..kernel.engine import DEFAULT_PERMISSION_MODE, agent_launch_snapshot
from ..kernel.failures import (
    DEFAULT_CHAIN,
    FailureClassification,
    FailureClassifierChain,
    FailureSignal,
)
from ..kernel.policy import (
    ApprovalStore,
    PolicyDecision,
    PolicyEngine,
    Verdict,
    resolve_escalation,
)
from .capture import ExecutionResult
from .claude_cli_runner import DEFAULT_TIMEOUT_S, McpRunnerConfig


def _tail(path: Path, limit: int = 8192) -> str:
    """The end of a stream, bounded — enough for a classifier, never a
    reason to read a log dump into memory."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


class LaunchRefused(RuntimeError):
    """Policy refused this agent launch.

    Carries the decision so the caller records the policy's own reason
    code rather than paraphrasing it."""

    def __init__(self, decision: PolicyDecision) -> None:
        super().__init__(f"policy refused this launch: {decision.reason}")
        self.decision = decision


class CredentialHeld(RuntimeError):
    """The credential is rate-limit held, so no launch may happen.

    A park, not a failure: rule 6 says a shut window is not the agent
    misbehaving and rule 7 forbids charging it to agent quality."""


class HoldGate(Protocol):
    """The slice of the scheduler this needs.

    Three parts, because a gate that only asks is half a gate: `admits`
    before the launch, `observe` after it — so a rate limit hit by a
    REVIEW or FIX round reaches the hold plane the same way one hit by
    the implementation does — and `claim_probe`, so that a hold the
    kernel ESTIMATED can be tested by one launch instead of expiring
    into every parked round resuming at once.

    `claim_probe` is on this protocol and not only on `TaskScheduler.
    submit` because this is the path that actually launches agents in the
    pipeline. A probe caller wired only into `submit` would leave the
    reviewer, the fixer and the re-reviewer going through a gate that
    never probes — the same mechanism-nobody-calls it was meant to fix,
    one level up."""

    def admits(self, *, is_resume: bool = ..., probe_run_id: str | None = ...) -> bool: ...

    def observe(self, classification: FailureClassification | None,
                probe_run_id: str | None = ...) -> Any: ...

    def claim_probe(self, run_id: str) -> Any: ...


class GatedAgentRunner:
    """Wraps a runner so every launch is gated and recorded.

    Composable with `ReplayingCLIRunner` in either order; putting the
    cassette *inside* is the useful arrangement, since a replayed launch
    is still a launch an operator may want to have authorised.
    """

    def __init__(
        self,
        inner: Any,
        policy: PolicyEngine,
        exec_root: Path,
        stage: str,
        task_id: str,
        approvals: ApprovalStore | None = None,
        policy_actor: str = "agent://unattributed",
        holds: HoldGate | None = None,
        worktree_branch: str | None = None,
        on_decision: Callable[[str, PolicyDecision], None] | None = None,
        failure_chain: FailureClassifierChain | None = None,
        budget: BudgetLedger | None = None,
    ) -> None:
        self.inner = inner
        self.policy = policy
        self.exec_root = exec_root
        self.stage = stage
        self.task_id = task_id
        self.approvals = approvals
        self.policy_actor = policy_actor
        self.holds = holds
        self.worktree_branch = worktree_branch
        # Every verdict is handed to the caller to record. An allowed
        # launch is evidence too, not just a refused one.
        self.on_decision = on_decision
        self.failure_chain = failure_chain or DEFAULT_CHAIN
        # Consulted at the same moment as the policy gate, for the same
        # reason: it is the last point at which refusing still costs
        # nothing.
        self.budget = budget
        self.classification: FailureClassification | None = None
        self.decisions: list[tuple[str, PolicyDecision]] = []
        # Per-launch, so two rounds of the same stage cannot share a probe.
        self._probe_seq = 0

    @property
    def binary(self) -> str:
        """Pass through, so the gate sees the program that really runs.

        ADR-0014 learned this the hard way: a wrapper without `.binary`
        reported `<unknown-runner>`, silently changing the action identity
        an approval is bound to."""
        inner_binary = getattr(self.inner, "binary", None)
        return inner_binary if isinstance(inner_binary, str) and inner_binary else "<unknown-runner>"

    def run(
        self,
        prompt: str,
        cwd: Path,
        stdout_path: Path,
        stderr_path: Path,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        permission_mode: str = DEFAULT_PERMISSION_MODE,
        mcp: McpRunnerConfig | None = None,
        model: str | None = None,
        extra_args: Sequence[str] | None = None,
        **kwargs: Any,
    ) -> ExecutionResult:
        if self.budget is not None:
            # BEFORE the hold question and before the verdict: a brief
            # that has spent its budget must not consume a policy
            # evaluation or a credential check either, and `check` raises
            # BudgetExhausted, which is nobody's failure.
            self.budget.check()

        probe_run_id: str | None = None
        if self.holds is not None and not self.holds.admits():
            # Held — but if the hold is the kernel's own GUESS about when
            # the window reopens, one launch should test it rather than
            # every parked round resuming together when the guess elapses.
            # The claim has exactly one winner; everyone else parks.
            #
            # The identity is per LAUNCH, not per task or per stage: a
            # convergence loop runs the same stage for the same task
            # repeatedly, and a reused id would let a later round ride an
            # earlier round's probe. A shared identity is the defect this
            # mechanism has already been repaired for once.
            self._probe_seq += 1
            candidate = f"{self.task_id}:{self.stage}:{self._probe_seq}"
            if (self.holds.claim_probe(candidate) is not None
                    and self.holds.admits(probe_run_id=candidate)):
                probe_run_id = candidate
            else:
                # Checked BEFORE the policy question: spending a verdict on
                # an action that cannot run anyway is noise in the audit
                # trail, and a park is not a policy event.
                raise CredentialHeld(
                    f"credential is held; {self.stage} for task {self.task_id} is parked"
                )

        snapshot = agent_launch_snapshot(
            stage=self.stage, task_id=self.task_id, prompt=prompt,
            binary=self.binary, exec_root=cwd, planned_root=cwd, mcp=mcp,
            worktree_branch=self.worktree_branch, policy_actor=self.policy_actor,
            permission_mode=permission_mode, model=model,
        )
        decision = self.policy.decide(snapshot)
        if self.approvals is not None:
            decision = resolve_escalation(decision, snapshot, self.approvals)
        self.decisions.append((self.stage, decision))
        if self.on_decision is not None:
            self.on_decision(self.stage, decision)
        if decision.verdict not in (Verdict.ALLOW, Verdict.WARN):
            # No child is launched. TRANSFORM is refused here for the same
            # reason ADR-0013 refuses it in the engine: this point cannot
            # rewrite an agent invocation, and silently dropping a
            # mitigation it cannot apply is worse than stopping.
            raise LaunchRefused(decision)

        if self.budget is not None:
            # Counted before the child starts. A launch that crashes still
            # consumed the thing being bounded, and counting on the way
            # out would let a crash-looping brief spend forever.
            self.budget.spend_launch()
        result: ExecutionResult = self.inner.run(
            prompt=prompt, cwd=cwd, stdout_path=stdout_path,
            stderr_path=stderr_path, timeout_s=timeout_s,
            permission_mode=permission_mode, mcp=mcp, model=model,
            extra_args=extra_args, **kwargs,
        )

        # Classify what came back, and tell the hold plane. Without this a
        # rate limit hit by a review or fix round was invisible to it: the
        # reviewer's output was unparseable, the loop filed
        # INVALID_AGENT_OUTPUT, no hold was placed, and the next round
        # launched straight into the same shut window. Rule 6 says a shut
        # window is a park, not agent output.
        self.classification = self.failure_chain.classify(FailureSignal(
            exit_code=result.exit_code, timed_out=result.timed_out,
            cancelled=result.cancelled,
            structured=result.parsed_json if isinstance(result.parsed_json, dict) else {},
            stderr_text=_tail(stderr_path), stdout_text=_tail(stdout_path),
        ))
        if self.holds is not None:
            # The probe id goes with it: a launch that did NOT hit the
            # limit is the answer the probe was asking for, and without
            # it the narrowing stands until its own deadline while the
            # window is demonstrably open — every other round still
            # parked on a question that has been answered.
            self.holds.observe(self.classification, probe_run_id=probe_run_id)
        if self.classification.is_park:
            # Park the round rather than handing the caller a "review"
            # that is really a provider refusal.
            raise CredentialHeld(
                f"{self.stage} for task {self.task_id} hit a rate limit: "
                f"{self.classification.reason_code}"
            )
        return result
