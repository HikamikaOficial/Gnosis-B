"""Wires the Director inbox/outbox convention to the M0 TaskEngine.

run_pending() is the whole ingest -> execute -> report loop:
  1. list_pending() inbox files
  2. claim() each (validate, dedup, atomically move to processed/)
  3. create a BriefRecord (ASSIGNED), execute via TaskEngine (IN_PROGRESS),
     persist the outcome (COMPLETED/FAILED), write the EngineerReport to
     outbox/ (+ escalations/ if the report demands escalation)

resume_interrupted() is the recovery half: it runs RecoveryManager first
(reclassifying any run left RUNNING by a crashed process as CRASHED), then
finds BriefRecords stuck in ASSIGNED/IN_PROGRESS whose run(s) are no
longer live and marks them FAILED with an explanation. No silent limbo,
and no automatic re-execution: a human/Director decides whether to
resubmit as a new brief.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ..contracts.director_brief import DirectorBrief
from ..contracts.engineer_report import EngineerReport, ReportStatus
from ..kernel.claims import WorkAuthority
from ..kernel.engine import TaskEngine, TaskExecutionOutcome
from ..kernel.ids import new_task_id
from ..kernel.policy import ApprovalStore, PolicyEngine
from ..kernel.replay import InteractionStore, ReplayMode
from ..kernel.run_store import RunStore
from ..kernel.state_machine import RunState
from ..kernel.verification import Verifier
from ..kernel.worktree import WorktreeManager
from ..runner.recovery import RecoveryManager
from ..runner.replay_runner import ReplayingCLIRunner
from .brief_record import BriefRecord, BriefRecordState, BriefRecordStore
from .inbox import DirectorInbox


@dataclass(frozen=True)
class IngestOutcome:
    brief_id: str | None
    task_id: str | None
    accepted: bool
    reason: str
    execution: TaskExecutionOutcome | None = None


class DirectorOrchestrator:
    def __init__(
        self,
        director_root: Path,
        run_store: RunStore,
        repo_path: Path,
        task_engine: TaskEngine | None = None,
        prompt_builder: Callable[[DirectorBrief], str] | None = None,
        # The default verifier for every brief this orchestrator runs.
        # `run_pending` may still be handed one per call; what neither can
        # do is leave both unset and still execute, because a brief that
        # completes on a bare exit code is an unevidenced DONE (F-34).
        verifier: Verifier | None = None,
        authority: WorkAuthority | None = None,
        worker_id: str | None = None,
        worktrees: WorktreeManager | None = None,
        lease_ttl_s: float | None = None,
        policy: PolicyEngine | None = None,
        approvals: ApprovalStore | None = None,
        policy_actor: str | None = None,
        require_policy: bool = False,
    ) -> None:
        self.inbox = DirectorInbox(director_root)
        self.records = BriefRecordStore(director_root / "state" / "briefs")
        self.run_store = run_store
        self.repo_path = repo_path
        self.task_engine = task_engine or TaskEngine(run_store=run_store)
        # How a DirectorBrief becomes a CLI prompt string is a policy
        # decision left to the caller; default is a simple, literal
        # rendering good enough for M1 plumbing tests.
        self.prompt_builder = prompt_builder or _default_prompt_builder
        self.verifier = verifier
        # Governed mode (ADR-0006..0008 follow-up): when a WorkAuthority is
        # configured, every brief execution runs under a fenced grant (the
        # engine enforces the verifier-required evidence gate) and, when a
        # WorktreeManager is configured, inside the task's own worktree.
        # The inbox's best-effort brief claim remains as brief-level dedup;
        # task ownership authority is the claims/lease plane.
        if authority is not None and not worker_id:
            raise ValueError("worker_id is required when the orchestrator is given a WorkAuthority")
        if authority is not None and worktrees is None:
            # Governed briefs must be workspace-isolated: without a
            # WorktreeManager a deposed child keeps writing the SHARED repo
            # until it observes cooperative cancellation (Codex review).
            # The engine primitive still allows the combination; the
            # production entry point does not.
            raise ValueError(
                "a governed orchestrator requires a WorktreeManager: "
                "authority-fenced briefs must run in the task's own worktree"
            )
        self.authority = authority
        self.worker_id = worker_id
        self.worktrees = worktrees
        self.lease_ttl_s = lease_ttl_s
        # ADR-0013: the policy gate has to be reachable from the production
        # entry point or it is exactly the parallel fiction Directive 9
        # warned about. An approval store without an engine is a
        # configuration mistake worth refusing at construction: it reads as
        # "governed", authorises nothing, and would silently let everything
        # through.
        if approvals is not None and policy is None:
            raise ValueError("an ApprovalStore without a PolicyEngine gates nothing")
        # Deny-by-default is a constitution rule (13), but no default rule
        # set exists yet, so the gate is opt-in and an ungoverned run says
        # so on its own ledger. `require_policy` is how an operator gets
        # fail-closed TODAY rather than waiting for that rule set: without
        # it, the ungoverned path is a construction-time choice a reviewer
        # can only find by reading call sites (Codex review).
        if require_policy and policy is None:
            raise ValueError(
                "require_policy=True but no PolicyEngine was given: this "
                "orchestrator would launch agents with no verdict"
            )
        self.require_policy = require_policy
        self.policy = policy
        self.approvals = approvals
        # Whoever an approval is granted to is the identity the escalation
        # names, so it defaults to the fenced worker rather than the process.
        self.policy_actor = policy_actor or worker_id

    def run_pending(self, verifier: Verifier | None = None) -> list[IngestOutcome]:
        # Refuse BEFORE consuming anything. The engine already refuses a
        # verifier-less task, but by then the brief has been claimed out
        # of the inbox and has a durable record, so the refusal costs work
        # that has to be recovered. Asking here means an unverifiable
        # configuration cannot take a brief out of circulation at all.
        #
        # This is defence in depth, not the guarantee: the guarantee is
        # `completion_is_evidenced` in the engine, at the lowest point
        # that can authorise a DONE. A rule enforced only where callers
        # remember to enforce it is documentation (L-0035).
        effective_verifier = verifier if verifier is not None else self.verifier
        if effective_verifier is None:
            raise ValueError(
                "DirectorOrchestrator.run_pending requires a verifier: a brief "
                "cannot report COMPLETED on a bare CLI exit code (constitution "
                "rule 2). Pass one to run_pending(), or give the orchestrator a "
                "default at construction. No brief has been consumed."
            )
        outcomes: list[IngestOutcome] = []
        for path in self.inbox.list_pending():
            claim = self.inbox.claim(path)
            if not claim.accepted:
                outcomes.append(IngestOutcome(brief_id=None, task_id=None, accepted=False, reason=claim.reason))
                continue
            # An accepted claim always carries a brief; cast is a typing-only
            # no-op that tells mypy what ClaimResult.accepted guarantees.
            outcomes.append(self._execute_brief(
                cast(DirectorBrief, claim.brief), verifier=effective_verifier))
        return outcomes

    def _execute_brief(self, brief: DirectorBrief, verifier: Verifier) -> IngestOutcome:
        task_id = new_task_id()
        self.records.create(brief.brief_id, task_id, BriefRecordState.ASSIGNED)
        self.records.update(brief.brief_id, state=BriefRecordState.IN_PROGRESS)

        try:
            outcome = self.task_engine.execute_task(
                task_id=task_id,
                objective=brief.title,
                prompt=self.prompt_builder(brief),
                repo_path=self.repo_path,
                verifier=verifier,
                authority=self.authority,
                worker_id=self.worker_id,
                lease_ttl_s=self.lease_ttl_s,
                worktrees=self.worktrees,
                policy=self.policy,
                approvals=self.approvals,
                policy_actor=self.policy_actor,
            )
        except Exception as exc:  # noqa: BLE001 - see below: a consumed brief must never strand
            # Governed mode makes deposition, claim conflicts, workspace
            # failures and precondition violations EXPECTED outcomes of a
            # brief, not batch-aborting crashes: the brief was already
            # consumed from the inbox, so it must end in a durable, visible
            # FAILED state instead of stranding IN_PROGRESS with no report
            # and killing the rest of the batch (adversarial review).
            #
            # Widened from a named tuple of exceptions to everything: the
            # named list was a bet that the engine's failure modes were
            # fully enumerated, and a hostile rule detail falsified it
            # (Codex review). The brief is already gone from the inbox, so
            # an unanticipated exception either becomes a FAILED record
            # carrying its type, or becomes a brief that no operator and no
            # recovery pass can account for. The exception is not
            # swallowed: it is the record's `error`.
            self.records.update(
                brief.brief_id, state=BriefRecordState.FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )
            return IngestOutcome(
                brief_id=brief.brief_id, task_id=task_id, accepted=True,
                reason=f"execution failed: {type(exc).__name__}: {exc}",
            )

        report_path = self._write_report(outcome.report)
        final_state = (
            BriefRecordState.COMPLETED if outcome.report.status == ReportStatus.COMPLETED
            else BriefRecordState.ESCALATED if outcome.report.status == ReportStatus.ESCALATION_REQUIRED
            else BriefRecordState.FAILED
        )
        self.records.update(
            brief.brief_id, state=final_state, run_ids=list(outcome.run_ids), report_path=str(report_path),
        )

        return IngestOutcome(brief_id=brief.brief_id, task_id=task_id, accepted=True, reason="ok", execution=outcome)

    def _write_report(self, report: EngineerReport) -> Path:
        layout = self.inbox.layout
        payload = json.dumps(report.to_dict(), indent=2, sort_keys=True)
        markdown = report.to_markdown()
        json_path = layout.outbox / f"{report.task_id}.json"
        _atomic_write(json_path, payload)
        _atomic_write(layout.outbox / f"{report.task_id}.md", markdown)

        if report.status == ReportStatus.ESCALATION_REQUIRED:
            _atomic_write(layout.escalations / f"{report.task_id}.json", payload)
            _atomic_write(layout.escalations / f"{report.task_id}.md", markdown)

        return json_path

    def resume_interrupted(self, stale_after_s: float = 120.0) -> list[BriefRecord]:
        RecoveryManager(self.run_store, stale_after_s=stale_after_s).scan()

        recovered: list[BriefRecord] = []
        stuck = self.records.list_in_states({BriefRecordState.ASSIGNED, BriefRecordState.IN_PROGRESS})
        for record in stuck:
            if self._has_live_or_recoverable_run(record):
                continue
            updated = self.records.update(
                record.brief_id,
                state=BriefRecordState.FAILED,
                error="Interrupted: no successful run found after recovery scan; resubmit as a new brief if needed.",
            )
            recovered.append(updated)
        return recovered

    def _has_live_or_recoverable_run(self, record: BriefRecord) -> bool:
        for run_id in record.run_ids:
            try:
                meta = self.run_store.read_meta(run_id)
            except FileNotFoundError:
                continue
            if meta.state in (RunState.PENDING.value, RunState.RUNNING.value, RunState.SUCCEEDED.value):
                return True
        return False


def recording_orchestrator(
    director_root: Path,
    run_store: RunStore,
    repo_path: Path,
    cassette: Path,
    mode: ReplayMode | str = ReplayMode.RECORD,
    inner_runner: Any | None = None,
    **kwargs: Any,
) -> DirectorOrchestrator:
    """A Director whose agent calls go through a replay cassette.

    This exists because ADR-0014 shipped `ReplayingCLIRunner` with **no
    production construction anywhere** — reachable from tests only, which
    is the precise condition Directive 9 named a parallel fiction and
    which the independent review caught the ADR condemning in its own
    opening paragraph.

    `RECORD` runs the real agent and keeps a cassette beside the run;
    `REPLAY` re-runs the same briefs against it with no model, no network
    and no bill. The task engine is built here rather than accepted,
    because the whole point is that the runner it holds is the wrapped
    one.
    """
    engine = TaskEngine(
        run_store=run_store,
        cli_runner=ReplayingCLIRunner(
            InteractionStore(cassette, mode), inner=inner_runner,
        ),
    )
    return DirectorOrchestrator(
        director_root=director_root, run_store=run_store, repo_path=repo_path,
        task_engine=engine, **kwargs,
    )


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file and one rename.

    A reader polling `escalations/` sees the whole refusal or nothing —
    never a half-written record it then treats as the operator's copy of
    what happened (Codex review). `Path.replace` is atomic on both POSIX
    and Windows for a same-directory rename.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _default_prompt_builder(brief: DirectorBrief) -> str:
    parts = [brief.mission]
    if brief.constraints:
        parts.append("Constraints: " + "; ".join(brief.constraints))
    if brief.acceptance_criteria:
        parts.append("Acceptance criteria: " + "; ".join(brief.acceptance_criteria))
    return "\n\n".join(parts)
