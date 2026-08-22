"""One brief, one governed and recorded run, one convergent result.

The integration milestone. Every piece it uses already existed and was
tested alone; nothing composed them, which is the shape Directive 9
named one level up — four real mechanisms and no path that runs a real
request through all of them.

    brief
      -> TaskScheduler        (is the credential's window open?)
      -> TaskEngine           (policy gate, worktree isolation, retries,
                               typed classification, durable evidence)
      -> ConvergenceLoop      (verify -> independent review -> fix, bounded)
           with CliReviewer / CliFixer behind a GatedAgentRunner
      -> EngineerReport       (one status covering BOTH halves)

Three decisions carry the weight:

**Convergence launches agents too, so convergence is gated.** The
reviewer and the fixer run once per round — usually more agents than the
implementation itself. Running them through `GatedAgentRunner` means the
policy gate and the rate-limit hold cover every launch a brief causes,
not just the first. A gate with partial coverage is worse than an absent
one, because it reads as governed.

**The report cannot say COMPLETED unless convergence converged.** The
implementation half can succeed while the review half finds blocking
defects; that is the normal case and the entire reason the loop exists.
Reporting the implementation's own opinion would be the agent's DONE
claim closing a task, which is the first thing ADR-0008 forbids.

**A park is not a failure anywhere along the path.** A held credential
before the implementation, or during a fix round, parks the brief with
its work intact (rules 6 and 7). `BriefRecordState.PARKED` exists so
that state is expressible; writing it as FAILED would both lose the
resumability and charge a provider's window to the agent.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..adapters.cli_review import CliFixer, CliReviewer
from ..contracts.director_brief import DirectorBrief
from ..contracts.engineer_report import EngineerReport, ReportStatus
from ..kernel.budget import Budget, BudgetExhausted, BudgetLedger, BudgetStore
from ..kernel.convergence import (
    ConvergenceLoop,
    ConvergenceOutcome,
    ConvergencePolicy,
    ConvergenceResult,
    EvidenceFailure,
    git_fingerprint,
)
from ..kernel.credentials import CredentialKind, CredentialPool
from ..kernel.engine import TaskExecutionOutcome
from ..kernel.ids import new_task_id
from ..kernel.integration import (
    IntegrationOutcome,
    IntegrationResult,
    WorkIntegrator,
)
from ..kernel.ordering import LandingCoordinator
from ..kernel.policy import ApprovalStore, PolicyDecision, PolicyEngine
from ..kernel.scheduler import ScheduleOutcome, TaskScheduler
from ..kernel.verification import (
    VerificationResult,
    VerificationVerdict,
    Verifier,
    verification_verdict,
)
from ..kernel.worktree import WorktreeError, WorktreeManager
from ..runner.gated_runner import CredentialHeld, GatedAgentRunner, LaunchRefused
from .brief_record import BriefRecordState, BriefRecordStore
from .inbox import DirectorInbox

REVIEW_STAGE = "convergence_review"
# A re-review is its own stage: an operator approving a convergence
# review has not approved re-judging a merged tree.
REREVIEW_STAGE = "integration_rereview"
FIX_STAGE = "convergence_fix"


# Deliberately not id-shaped: a report that never had a run says so.
_NO_RUN = "(no run: the brief never started)"


class BriefAlreadyRunning(RuntimeError):
    """This brief already has a live task; starting a second would
    overwrite the record and orphan the first one's evidence."""


@dataclass(frozen=True)
class PipelineOutcome:
    """What happened to one brief, end to end."""

    brief_id: str
    task_id: str
    status: ReportStatus
    reason_code: str
    report: EngineerReport
    schedule: ScheduleOutcome | None = None
    convergence: ConvergenceResult | None = None
    integration: IntegrationResult | None = None

    @property
    def implementation(self) -> TaskExecutionOutcome | None:
        return self.schedule.execution if self.schedule else None

    @property
    def parked(self) -> bool:
        return bool(self.schedule and self.schedule.parked)

    def to_dict(self) -> dict[str, Any]:
        return {
            "brief_id": self.brief_id, "task_id": self.task_id,
            "status": self.status.value, "reason_code": self.reason_code,
            "parked": self.parked,
            "convergence": self.convergence.to_dict() if self.convergence else None,
            "integration": self.integration.to_dict() if self.integration else None,
        }


class GovernedPipeline:
    """Runs a brief through the whole kernel, once."""

    def __init__(
        self,
        director_root: Path,
        scheduler: TaskScheduler,
        repo_path: Path,
        verifier: Verifier,
        policy: PolicyEngine,
        review_runner: Any,
        convergence_policy: ConvergencePolicy | None = None,
        approvals: ApprovalStore | None = None,
        policy_actor: str = "agent://unattributed",
        worktrees: WorktreeManager | None = None,
        # Rotation for the GATED launches (review, fix, re-review). The
        # implementation launch rotates through the scheduler's own pool,
        # which is configured where the scheduler is built — two places
        # because they are two different launch paths, and wiring only one
        # of them would leave the other running on a single credential
        # while the mechanism claimed otherwise.
        credentials: CredentialPool | None = None,
        authorised_kinds: frozenset[CredentialKind] = frozenset(),
        prompt_builder: Callable[[DirectorBrief], str] | None = None,
        reviewer_id: str = "claude-cli",
        focus: Sequence[str] | None = None,
        integrator: WorkIntegrator | None = None,
        budget: Budget | None = None,
        stale_review_authorised: set[str] | None = None,
    ) -> None:
        self.inbox = DirectorInbox(director_root)
        self.records = BriefRecordStore(director_root / "state" / "briefs")
        self.scheduler = scheduler
        self.credentials = credentials
        self.authorised_kinds = authorised_kinds
        self.repo_path = repo_path
        # A verifier is REQUIRED, not optional. Convergence is defined as
        # "deterministic verification passed AND an independent review
        # passed"; without the first half the loop would converge on an
        # agent's opinion alone, which is the failure ADR-0008 exists to
        # prevent. The engine already refuses a governed task with no
        # verifier; this refuses it one level up, at construction, where
        # the mistake is visible.
        self.verifier = verifier
        self.policy = policy
        # Rule 10, INDEPENDENT BEFORE INTERACTION. Nothing here can verify
        # that a reviewer is genuinely a different mind — same provider,
        # same model, different process is still weak independence, and
        # the kernel cannot tell. What it CAN refuse is the degenerate
        # case an operator reaches by accident: the implementing runner
        # reviewing its own work. `reviewer_id` was only a label, and my
        # own test fixture used one agent for both halves (Codex review).
        implementer = getattr(scheduler.engine, "cli_runner", None)
        if implementer is not None and implementer is review_runner:
            raise ValueError(
                "the review runner is the SAME object as the implementation "
                "runner: a task cannot close on its own author's review "
                "(constitution rule 10). Pass a separate runner — ideally a "
                "different provider."
            )
        self.review_runner = review_runner
        self.convergence_policy = convergence_policy or ConvergencePolicy(max_rounds=3)
        self.approvals = approvals
        self.policy_actor = policy_actor
        self.worktrees = worktrees
        self.prompt_builder = prompt_builder or _default_prompt_builder
        self.reviewer_id = reviewer_id
        self.focus = tuple(focus or ())
        # Opt-in, deliberately. Landing work moves the branch everyone
        # else builds on, and the constitution says irreversible-ish acts
        # on shared state are PREPARED but not executed without higher
        # authority. Without an integrator a converged brief still reports
        # COMPLETED, with its reviewed work sitting on `gnosis/<task_id>`
        # and the next step naming what to do about it.
        self.integrator = integrator
        # Every loop here is individually bounded and none of that bounds
        # a BRIEF: three implementation attempts, then three convergence
        # rounds each launching a reviewer and a fixer, is a dozen agent
        # launches nobody authorised as a total. Rule 8 names wall-time
        # and budget as circuit breakers; this is where they live.
        self.budget = budget
        # Task ids whose review an operator has re-done deliberately. Per
        # task, never a global switch: authorising every stale landing at
        # once is how an opt-out becomes the default.
        self.stale_review_authorised = set(stale_review_authorised or ())
        # DURABLE, keyed by brief. An in-memory ledger tracked one
        # INVOCATION, so a parked brief that was released and re-claimed
        # started from zero and could launch agents forever while every
        # individual run looked bounded (independent review). Rule 4: the
        # state that matters survives the process.
        self.budget_store = BudgetStore(director_root / "state" / "budget")

    # -- the whole path ---------------------------------------------------

    def run_pending(self) -> list[PipelineOutcome]:
        outcomes: list[PipelineOutcome] = []
        for path in self.inbox.list_pending():
            claim = self.inbox.claim(path)
            if not claim.accepted or claim.brief is None:
                continue
            outcomes.append(self.run_brief(claim.brief))
        return outcomes

    def run_brief(self, brief: DirectorBrief) -> PipelineOutcome:
        # `run_pending` dedups through the inbox claim, but this is the
        # public method and it did not: a second call minted a new task id
        # and OVERWROTE the record, making the first task's runs and
        # report unreachable from the brief (Codex review). A brief whose
        # record is still live is refused; one that finished or parked may
        # legitimately be resubmitted.
        existing = self._live_record(brief.brief_id)
        if existing is not None:
            raise BriefAlreadyRunning(
                f"brief {brief.brief_id} is already {existing} as task "
                f"{self.records.get(brief.brief_id).task_id}"
            )
        task_id = new_task_id()
        self.records.create(brief.brief_id, task_id, BriefRecordState.ASSIGNED)
        self.records.update(brief.brief_id, state=BriefRecordState.IN_PROGRESS)

        ledger = self.budget_store.ledger_for(brief.brief_id, self.budget)
        try:
            # Checked BEFORE the implementation too. The implementation's
            # launches can only be charged after the fact (the pipeline
            # does not own the engine's runner), so this is what stops a
            # brief that has already spent everything from starting yet
            # another implementation phase.
            ledger.check()
            schedule = self._implement(brief, task_id)
        except Exception as exc:  # noqa: BLE001 - a consumed brief must never strand
            return self._finish(brief, task_id, ReportStatus.BLOCKED,
                                f"pipeline_error:{type(exc).__name__}",
                                problems=(f"{type(exc).__name__}: {exc}",))

        if schedule.parked:
            # Untouched and resumable. Not a failure, not an escalation.
            return self._finish(
                brief, task_id, ReportStatus.PARTIAL, schedule.reason_code,
                schedule=schedule, brief_state=BriefRecordState.PARKED,
                problems=(("The credential's rate-limit window is shut; "
                           "this brief was not started."),),
                next_step="Resubmit when the hold expires, or probe it.",
            )

        implementation = schedule.execution
        if implementation is not None:
            # The implementation's launches are charged to the ledger too,
            # or the budget would bound only half a brief. They are
            # charged AFTER the fact — unlike a convergence launch, which
            # is refused before it costs anything — because the pipeline
            # does not own the engine's runner and cannot gate it. That is
            # sound only because the engine has its own hard bound
            # (`RetryPolicy.max_attempts`), so this phase cannot run away;
            # what the budget then bounds exactly is everything after it.
            for _ in implementation.run_ids:
                ledger.spend_launch()
            self.budget_store.record(brief.brief_id, ledger)

        if implementation is None or implementation.execution_result is None:
            # No child ever ran (refused, crashed, or exhausted before
            # launching). Converging on nothing would be theatre.
            return self._finish(
                brief, task_id,
                implementation.report.status if implementation else ReportStatus.BLOCKED,
                schedule.reason_code, schedule=schedule,
                problems=("The implementation never produced a run to review.",),
            )

        try:
            # Inside the guard, not before it: `_exec_root` raises when the
            # worktree is gone, and outside the try that escaped
            # `run_brief` and stranded the consumed brief — reintroducing
            # the exact defect the guard exists to prevent.
            convergence = self._converge(
                brief, task_id, self._exec_root(task_id), ledger)
        except CredentialHeld as held:
            return self._finish(
                brief, task_id, ReportStatus.PARTIAL, "rate_limited:convergence",
                schedule=schedule, brief_state=BriefRecordState.PARKED,
                problems=(str(held),),
                next_step="The implementation stands; resume review when the window reopens.",
            )
        except LaunchRefused as refused:
            return self._finish(
                brief, task_id, ReportStatus.ESCALATION_REQUIRED,
                refused.decision.reason, schedule=schedule,
                problems=(f"Policy refused a convergence launch: {refused.decision.reason}",),
                next_step="Approve the exact action id, or change it, then resubmit.",
            )
        except BudgetExhausted as spent:
            self.budget_store.record(brief.brief_id, ledger)
            # Nobody did anything wrong: the work cost more than it was
            # authorised to cost. PARTIAL with the implementation intact,
            # never a FAIL that reads as the agent's fault.
            return self._finish(
                brief, task_id, ReportStatus.PARTIAL, f"budget:{spent.kind}",
                schedule=schedule, problems=(str(spent),),
                next_step="Raise the brief's budget, or split the work, then resubmit.",
            )
        except Exception as exc:  # noqa: BLE001 - see below
            # ADR-0008 deliberately lets `fix_fn` exceptions propagate:
            # a crashing fixer is an agent failure for the caller's
            # taxonomy, not something the loop absorbs into a fake
            # verdict. THIS is that caller — and it caught only the two
            # refusal types, so a crashing fixer escaped `run_brief`
            # entirely and left an already-consumed brief IN_PROGRESS
            # with no report at all (Codex review). The exception is not
            # swallowed: it is the report.
            return self._finish(
                brief, task_id, ReportStatus.BLOCKED,
                f"convergence_error:{type(exc).__name__}", schedule=schedule,
                problems=(f"Convergence failed: {type(exc).__name__}: {exc}",),
                next_step="Inspect the convergence evidence before resubmitting.",
            )

        # A refusal inside the review half never reaches the `except`
        # above: `ConvergenceLoop` catches everything `review_fn` raises
        # and files it as evidence collection failing — correctly, since
        # no verdict was collected. But "the policy said no" and "the
        # reviewer crashed" demand different answers, and reporting a
        # governance refusal as an ordinary exhausted loop would hide it.
        # This is what the typed `evidence_failures` are for.
        # THIRD typed condition needing an explicit mapping here, which
        # is the pattern rather than an accident: `ConvergenceLoop`
        # catches everything `review_fn` raises, so any condition an
        # adapter expresses as an exception arrives as an untyped evidence
        # failure unless this end names it. Budget exhaustion is not a
        # convergence outcome — it is a park.
        # Not named `spent`: that name is bound by `except BudgetExhausted
        # as spent` above, and Python deletes it when the block exits. The
        # second time this collision has bitten in this file.
        # Whatever convergence spent is now the brief's total, whichever
        # way this ends.
        self.budget_store.record(brief.brief_id, ledger)

        budget_failure = _first_failure_of(convergence, "BudgetExhausted")
        if budget_failure is not None:
            return self._finish(
                brief, task_id, ReportStatus.PARTIAL, "budget:convergence",
                schedule=schedule, convergence=convergence,
                problems=(budget_failure.message,),
                next_step="Raise the brief's budget, or split the work, then resubmit.",
            )

        refusal = _first_failure_of(convergence, "LaunchRefused")
        if refusal is not None:
            return self._finish(
                brief, task_id, ReportStatus.ESCALATION_REQUIRED,
                _reason_from(refusal.message), schedule=schedule,
                convergence=convergence,
                next_step="Approve the exact action id, or change it, then resubmit.",
            )
        # Not named `held`: that name is bound by the `except CredentialHeld
        # as held` above, and Python deletes it when the block exits.
        hold_failure = _first_failure_of(convergence, "CredentialHeld")
        if hold_failure is not None:
            return self._finish(
                brief, task_id, ReportStatus.PARTIAL, "rate_limited:convergence",
                schedule=schedule, convergence=convergence,
                brief_state=BriefRecordState.PARKED,
                next_step="The implementation stands; resume review when the window reopens.",
            )

        try:
            integration = self._integrate(task_id, convergence, ledger)
        except CredentialHeld as held:
            # A re-review is a launch, so it can be parked like any other.
            # Escaping `_integrate` would have stranded the brief after
            # convergence with no report (independent review).
            return self._finish(
                brief, task_id, ReportStatus.PARTIAL, "rate_limited:rereview",
                schedule=schedule, convergence=convergence,
                brief_state=BriefRecordState.PARKED, problems=(str(held),),
                next_step="The work converged; re-review and land when the window reopens.",
            )
        except LaunchRefused as refused:
            return self._finish(
                brief, task_id, ReportStatus.ESCALATION_REQUIRED,
                refused.decision.reason, schedule=schedule, convergence=convergence,
                problems=(f"Policy refused the re-review launch: {refused.decision.reason}",),
                next_step="Approve the exact action id, or waive the stale review, then resubmit.",
            )
        except BudgetExhausted as spent:
            self.budget_store.record(brief.brief_id, ledger)
            return self._finish(
                brief, task_id, ReportStatus.PARTIAL, f"budget:{spent.kind}",
                schedule=schedule, convergence=convergence, problems=(str(spent),),
                next_step="Raise the brief's budget, or waive the stale review, then resubmit.",
            )
        status = _status_for(convergence)
        if integration is not None and not integration.integrated:
            # Converged work that will not land is not COMPLETED. A merge
            # conflict or a merged tree that fails verification means a
            # human has to decide something, and reporting COMPLETED with
            # the work stranded on a branch would be the report describing
            # an intention rather than an outcome.
            status = ReportStatus.ESCALATION_REQUIRED
        return self._finish(
            brief, task_id, status,
            integration.reason if integration is not None else convergence.outcome.value,
            schedule=schedule, convergence=convergence, integration=integration,
        )

    # -- halves -----------------------------------------------------------

    def _live_record(self, brief_id: str) -> str | None:
        """The state of an in-flight record for this brief, if any."""
        try:
            record = self.records.get(brief_id)
        except (FileNotFoundError, KeyError, ValueError):
            return None
        live = {BriefRecordState.ASSIGNED.value, BriefRecordState.IN_PROGRESS.value}
        return record.state if record.state in live else None

    def _implement(self, brief: DirectorBrief, task_id: str) -> ScheduleOutcome:
        return self.scheduler.submit(
            task_id=task_id,
            objective=brief.title,
            prompt=self.prompt_builder(brief),
            repo_path=self.repo_path,
            verifier=self.verifier,
            worktrees=self.worktrees,
            policy=self.policy,
            approvals=self.approvals,
            policy_actor=self.policy_actor,
        )

    def _exec_root(self, task_id: str) -> Path:
        """Where the work actually landed.

        Convergence must review the WORKTREE, not the source repo: the
        implementation's changes are not in the source tree, so reviewing
        it would judge code nobody wrote and report a clean bill for work
        that never happened.

        A missing handle therefore RAISES rather than falling back. The
        fallback was the dangerous branch: with a corrupt handle, the
        reviewer and the FIXER would have run in the shared source tree,
        and a PASS there would have reported COMPLETED for code nobody
        looked at (Codex review). Failing closed costs a brief; falling
        back costs the guarantee.
        """
        if self.worktrees is None:
            return self.repo_path
        handle = self.worktrees.load_handle(task_id)   # raises if absent/corrupt
        path = Path(handle.path)
        if not path.exists():
            raise WorktreeError(
                f"worktree for {task_id} is registered at {path} but does not exist; "
                "refusing to review the source repository instead"
            )
        return path

    def _converge(self, brief: DirectorBrief, task_id: str,
                  exec_root: Path, ledger: BudgetLedger) -> ConvergenceResult:
        evidence_dir = self.inbox.layout.outbox / f"{task_id}-convergence"
        objective = brief.title

        # Every verdict on a convergence launch is written down, allowed
        # ones included. `GatedAgentRunner.decisions` was transient and
        # nothing consumed it, so an operator could not later prove which
        # review or fix launches were authorised — in a path this ADR
        # calls "governed and recorded" (Codex review).
        decisions: list[dict[str, Any]] = []

        def record(stage: str, decision: PolicyDecision) -> None:
            decisions.append({"stage": stage, **decision.to_dict()})

        def gated(stage: str) -> GatedAgentRunner:
            return GatedAgentRunner(
                on_decision=record,
                inner=self.review_runner, policy=self.policy, exec_root=exec_root,
                stage=stage, task_id=task_id, approvals=self.approvals,
                policy_actor=self.policy_actor, holds=self.scheduler,
                budget=ledger, credentials=self.credentials,
                authorised_kinds=self.authorised_kinds,
                worktree_branch=(
                    self.worktrees.planned_branch(task_id) if self.worktrees else None
                ),
            )

        result = ConvergenceLoop(
            policy=self.convergence_policy,
            verify_fn=lambda: self.verifier.run(exec_root),
            review_fn=CliReviewer(
                gated(REVIEW_STAGE), exec_root, evidence_dir, objective,
                reviewer_id=self.reviewer_id, focus=self.focus,
            ),
            fix_fn=CliFixer(
                gated(FIX_STAGE), exec_root, evidence_dir, objective,
                fixer_id=self.reviewer_id,
            ),
            fingerprint_fn=lambda: git_fingerprint(exec_root),
        ).run()

        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "convergence.json").write_text(
            json.dumps({**result.to_dict(), "policy_decisions": decisions},
                       indent=2, sort_keys=True),
            encoding="utf-8")
        return result

    def _integrate(self, task_id: str, convergence: ConvergenceResult,
                   ledger: BudgetLedger | None = None) -> IntegrationResult | None:
        """Land through the coordinator, so the review-validity gate is real.

        Calling `integrator.integrate` directly bypassed
        `review_still_applies` entirely: ordinary pipeline landings kept
        the exact silent stale-review behaviour ADR-0020 says it prevents,
        and `LandingCoordinator` was referenced only by its own tests —
        Directive 9's parallel fiction, one more time (independent
        review).

        A task whose base moved since its review is refused here rather
        than landed. Verification would be re-run by the integrator; the
        REVIEW would not, and keeping half a guarantee while reporting a
        whole one is the failure this project keeps correcting.
        """
        if self.integrator is None:
            return None
        head, _ = self.integrator.preview_head()
        if head is None:
            return self.integrator.integrate(task_id, convergence)

        # The reviewer is built PER TASK and passed per call, never
        # assigned onto the shared integrator. The closure captures
        # `task_id` for its policy identity and its evidence directory, so
        # an integrator that kept the first one would have gated and
        # recorded every later task's re-review under the FIRST task's
        # name (self-review, before the verdict). Mutating shared state
        # to carry per-call context is how that happens.

        coordinator = LandingCoordinator(
            self.integrator,
            stale_review_authorised=self.stale_review_authorised,
            re_reviewer_for=lambda tid: self._rereviewer_for(tid, ledger),
        )
        plan = coordinator.plan(head, [task_id])
        attempts = coordinator.land(plan, {task_id: convergence})
        if not attempts:
            return None
        attempt = attempts[0]
        if isinstance(attempt.result, IntegrationResult):
            return attempt.result
        return IntegrationResult(
            IntegrationOutcome.REVIEW_STALE, task_id,
            self.integrator.worktrees.planned_branch(task_id),
            reason=f"review_stale:{attempt.status.value}",
            base_sha=attempt.planned.task.base_sha,
            changed_paths=attempt.planned.task.changed_paths,
        )

    def _rereviewer_for(self, task_id: str,
                        ledger: BudgetLedger | None = None) -> Callable[[Path], Any]:
        """An independent reviewer that judges whatever tree it is handed.

        Deliberately built per task and pointed at the STAGING tree the
        integrator supplies, not at the task worktree: the question a
        re-review answers is "is this correct in the tree that will
        land", and the task worktree is not that tree.
        """
        def review(tree: Path) -> Any:
            runner = GatedAgentRunner(
                inner=self.review_runner, policy=self.policy, exec_root=tree,
                stage=REREVIEW_STAGE, task_id=task_id, approvals=self.approvals,
                policy_actor=self.policy_actor, holds=self.scheduler,
                credentials=self.credentials,
                authorised_kinds=self.authorised_kinds,
                # A re-review is an agent launch like any other: gated,
                # held AND budgeted. The first version passed no ledger, so
                # a brief with an exhausted budget could still spend one
                # more launch here — while a comment claimed it was
                # budgeted (independent review).
                budget=ledger,
            )
            reviewer = CliReviewer(
                runner, tree,
                self.inbox.layout.outbox / f"{task_id}-rereview",
                objective=f"Re-review {task_id} against the merged tree",
                reviewer_id=self.reviewer_id, focus=self.focus,
            )
            return reviewer(0)

        return review

    # -- reporting --------------------------------------------------------

    def _finish(
        self,
        brief: DirectorBrief,
        task_id: str,
        status: ReportStatus,
        reason_code: str,
        schedule: ScheduleOutcome | None = None,
        convergence: ConvergenceResult | None = None,
        integration: IntegrationResult | None = None,
        brief_state: BriefRecordState | None = None,
        problems: tuple[str, ...] = (),
        next_step: str = "",
    ) -> PipelineOutcome:
        implementation = schedule.execution if schedule else None
        run_ids = list(implementation.run_ids) if implementation else []
        report = EngineerReport(
            task_id=task_id,
            # A report needs a non-empty run id, and a brief parked
            # before the engine was even called genuinely has no run. The
            # first version wrote `<task_id>-no-run`, which LOOKS like a
            # run id and resolves to nothing — the comment beside it even
            # said inventing a reference was the thing to avoid (Codex
            # review). The marker is now unmistakably not an id, so a
            # reader cannot mistake it for one and a lookup cannot be
            # attempted with it.
            run_id=run_ids[-1] if run_ids else _NO_RUN,
            status=status,
            objective=brief.title,
            verification=_verification_lines(implementation, convergence, integration),
            problems_encountered=problems or _problem_lines(convergence),
            remaining_risks=_dissent_lines(convergence),
            recommended_next_step=next_step or _next_step_for(status, convergence, integration),
        )
        self._write_report(report)
        self.records.update(
            brief.brief_id,
            state=brief_state or _brief_state_for(status),
            run_ids=run_ids,
            report_path=str(self.inbox.layout.outbox / f"{task_id}.json"),
        )
        return PipelineOutcome(
            brief_id=brief.brief_id, task_id=task_id, status=status,
            reason_code=reason_code, report=report, schedule=schedule,
            convergence=convergence, integration=integration,
        )

    def _write_report(self, report: EngineerReport) -> None:
        layout = self.inbox.layout
        payload = json.dumps(report.to_dict(), indent=2, sort_keys=True)
        _atomic_write(layout.outbox / f"{report.task_id}.json", payload)
        _atomic_write(layout.outbox / f"{report.task_id}.md", report.to_markdown())
        if report.status == ReportStatus.ESCALATION_REQUIRED:
            _atomic_write(layout.escalations / f"{report.task_id}.json", payload)
            _atomic_write(layout.escalations / f"{report.task_id}.md", report.to_markdown())


def _first_failure_of(convergence: ConvergenceResult, error_type: str) -> EvidenceFailure | None:
    return next((f for f in convergence.evidence_failures
                 if f.error_type == error_type), None)


def _reason_from(message: str) -> str:
    """The policy's OWN reason code, not a paraphrase of it.

    `LaunchRefused` formats as "policy refused this launch: <reason>";
    the reason is what an operator searches the ledger for."""
    marker = "policy refused this launch: "
    return message.split(marker, 1)[1].strip() if marker in message else message


def _status_for(convergence: ConvergenceResult) -> ReportStatus:
    """Only a converged loop is COMPLETED.

    The implementation's own verdict does not appear here on purpose. A
    task closes on evidence — deterministic verification AND an
    independent review — never on the claim of the agent that did the
    work."""
    if convergence.outcome is ConvergenceOutcome.CONVERGED:
        return ReportStatus.COMPLETED
    if convergence.outcome is ConvergenceOutcome.CANNOT_FIX:
        return ReportStatus.ESCALATION_REQUIRED
    # STALEMATE and ROUNDS_EXHAUSTED: work happened, it did not finish.
    return ReportStatus.PARTIAL


def _brief_state_for(status: ReportStatus) -> BriefRecordState:
    if status is ReportStatus.COMPLETED:
        return BriefRecordState.COMPLETED
    if status is ReportStatus.ESCALATION_REQUIRED:
        return BriefRecordState.ESCALATED
    if status is ReportStatus.PARTIAL:
        return BriefRecordState.IN_PROGRESS
    return BriefRecordState.FAILED


def _verification_lines(implementation: TaskExecutionOutcome | None,
                        convergence: ConvergenceResult | None,
                        integration: IntegrationResult | None = None) -> tuple[str, ...]:
    lines: list[str] = []
    if implementation is not None and implementation.verification is not None:
        lines.append(_verification_line("implementation", implementation.verification))
    if convergence is not None:
        lines.append(f"convergence: {convergence.outcome.value} "
                     f"over {len(convergence.rounds)} round(s)")
        for record in convergence.rounds:
            if record.verification is not None:
                lines.append(_verification_line(f"round {record.index}", record.verification))
            if record.review is not None:
                lines.append(
                    f"round {record.index} review [{record.review.reviewer}]: "
                    f"{record.review.verdict.value}"
                )
    if integration is None:
        # Said explicitly. COMPLETED means "done and independently
        # verified"; a reader must not be able to infer from silence that
        # the work reached the shared branch (Codex review).
        lines.append("integration: NOT ATTEMPTED (no integrator configured)")
    else:
        lines.append(f"integration: {integration.outcome.value} ({integration.reason})")
        if integration.verification is not None:
            # The one that matters most: the MERGED tree, not either side
            # of it. Rule 16.
            lines.append(_verification_line("merged tree", integration.verification))
        if integration.checkpoint_ref:
            lines.append(f"checkpoint: {integration.checkpoint_ref}")
    return tuple(lines)


def _verification_line(label: str, result: VerificationResult) -> str:
    """One line of the Director's report, read through the shared verdict.

    It used to be `'PASS' if result.passed else 'FAIL'`. That is the same
    truthiness read the second F-34 review caught in the engine's report:
    a `passed` of `1` is not a pass, and a report is a claim that must be
    as strict as the gate. `REJECTED` is deliberately neither of the two
    words a reader scans for.
    """
    verdict = verification_verdict(result)
    shown = {
        VerificationVerdict.PASSED: "PASS",
        VerificationVerdict.FAILED: "FAIL",
    }.get(verdict, "REJECTED (invalid evidence, no verdict recorded)")
    return f"{label} verification [{result.name}]: {shown}"


def _problem_lines(convergence: ConvergenceResult | None) -> tuple[str, ...]:
    if convergence is None:
        return ()
    problems = [
        f"round {record.index}: {finding.severity.value} {finding.category} — "
        f"{finding.description}"
        for record in convergence.rounds for finding in record.blocking
    ]
    # Typed evidence failures are reported as themselves: "review
    # collection failed" reads the same whether an agent produced
    # unreadable output or edited the code it was judging.
    problems.extend(
        f"{failure.stage} evidence failed [{failure.error_type}]: {failure.message}"
        for failure in convergence.evidence_failures
    )
    return tuple(problems)


def _dissent_lines(convergence: ConvergenceResult | None) -> tuple[str, ...]:
    """Nothing-lost rule: gated and non-blocking findings still surface."""
    if convergence is None:
        return ()
    risks = [f"dissent: {f.severity.value} {f.category} — {f.description}"
             for f in convergence.dissent]
    risks.extend(
        f"gated ({g.gate_reason}): {g.finding.severity.value} {g.finding.category} — "
        f"{g.finding.description}"
        for g in convergence.gate_ledger
    )
    return tuple(risks)


def _next_step_for(status: ReportStatus, convergence: ConvergenceResult | None,
                   integration: IntegrationResult | None = None) -> str:
    if status is ReportStatus.COMPLETED:
        if integration is not None and integration.integrated:
            return f"Landed on {integration.branch}; checkpoint {integration.checkpoint_ref}."
        return "Reviewed work is on the task branch; integrate it when ready."
    if convergence is None:
        return "Inspect the run evidence before resubmitting."
    if convergence.outcome is ConvergenceOutcome.CANNOT_FIX:
        return "A fixer reported it cannot address a blocking finding; a human decides."
    if convergence.outcome is ConvergenceOutcome.STALEMATE:
        return "The tree stopped changing while findings stand; change strategy."
    return "Rounds were exhausted with findings outstanding; resubmit or raise max_rounds."


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _default_prompt_builder(brief: DirectorBrief) -> str:
    parts = [brief.mission]
    if brief.constraints:
        parts.append("Constraints: " + "; ".join(brief.constraints))
    if brief.acceptance_criteria:
        parts.append("Acceptance criteria: " + "; ".join(brief.acceptance_criteria))
    return "\n\n".join(parts)
