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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ..contracts.director_brief import DirectorBrief
from ..contracts.engineer_report import EngineerReport, ReportStatus
from ..kernel.engine import TaskEngine, TaskExecutionOutcome
from ..kernel.ids import new_task_id
from ..kernel.run_store import RunStore
from ..kernel.state_machine import RunState
from ..kernel.verification import Verifier
from ..runner.recovery import RecoveryManager
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

    def run_pending(self, verifier: Verifier | None = None) -> list[IngestOutcome]:
        outcomes: list[IngestOutcome] = []
        for path in self.inbox.list_pending():
            claim = self.inbox.claim(path)
            if not claim.accepted:
                outcomes.append(IngestOutcome(brief_id=None, task_id=None, accepted=False, reason=claim.reason))
                continue
            # An accepted claim always carries a brief; cast is a typing-only
            # no-op that tells mypy what ClaimResult.accepted guarantees.
            outcomes.append(self._execute_brief(cast(DirectorBrief, claim.brief), verifier=verifier))
        return outcomes

    def _execute_brief(self, brief: DirectorBrief, verifier: Verifier | None) -> IngestOutcome:
        task_id = new_task_id()
        self.records.create(brief.brief_id, task_id, BriefRecordState.ASSIGNED)
        self.records.update(brief.brief_id, state=BriefRecordState.IN_PROGRESS)

        outcome = self.task_engine.execute_task(
            task_id=task_id,
            objective=brief.title,
            prompt=self.prompt_builder(brief),
            repo_path=self.repo_path,
            verifier=verifier,
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
        json_path = layout.outbox / f"{report.task_id}.json"
        md_path = layout.outbox / f"{report.task_id}.md"
        json_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        md_path.write_text(report.to_markdown(), encoding="utf-8")

        if report.status == ReportStatus.ESCALATION_REQUIRED:
            esc_json = layout.escalations / f"{report.task_id}.json"
            esc_md = layout.escalations / f"{report.task_id}.md"
            esc_json.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
            esc_md.write_text(report.to_markdown(), encoding="utf-8")

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


def _default_prompt_builder(brief: DirectorBrief) -> str:
    parts = [brief.mission]
    if brief.constraints:
        parts.append("Constraints: " + "; ".join(brief.constraints))
    if brief.acceptance_criteria:
        parts.append("Acceptance criteria: " + "; ".join(brief.acceptance_criteria))
    return "\n\n".join(parts)
