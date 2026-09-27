"""Project scheduling composed from the canonical production task lifecycle.

A queue completion means published AND incorporated work. Dependencies cannot
start merely because an agent returned a successful implementation report.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from gnosis.director.brief_record import BriefRecordState
from gnosis.director.composition import (
    ProductionCompositionConfig,
    PublicationCompositionInputs,
    build_production_deployment,
)
from gnosis.director.projects import MAX_PROJECT_TASKS, ProjectPlan, ProjectStore
from gnosis.director.supervisor import (
    Disposition,
    SupervisionReport,
    SupervisorPolicy,
    WorkerSupervisor,
)
from gnosis.director.work_queue import ClaimedWork, WorkQueue
from gnosis.kernel.claims import ClaimStore, WorkAuthority
from gnosis.kernel.execution_scope import ExecutionScope
from gnosis.kernel.lease import LeaseStore


class ProjectExecutor:
    def __init__(self, project_id: str, config: ProductionCompositionConfig,
                 publication: PublicationCompositionInputs) -> None:
        if re.fullmatch(r"[A-Za-z0-9_]{1,64}", project_id) is None:
            raise ValueError("invalid project identifier")
        if not config.integration_target:
            raise ValueError("project execution requires a trusted integration target")
        self.project_id = project_id
        self.config = replace(config, operator=replace(config.operator,
            director_root=config.operator.director_root / "projects" / project_id))
        self.publication = publication
        # Coordination state is protected from Worker writes, like phase proofs.
        root = publication.trust_state_root / "projects" / project_id
        authority = WorkAuthority(ClaimStore(root / "claims.json"),
                                  LeaseStore(root / "leases.json"), default_ttl_s=120)
        self.queue = WorkQueue(root / "queue", authority, max_attempts=5)
        self.store = ProjectStore(root / "plans", self.queue)

    def submit(self, plan: ProjectPlan) -> None:
        if plan.project_id != self.project_id:
            raise ValueError("plan belongs to a different project")
        self.store.submit(plan)

    def run(self, worker_id: str) -> SupervisionReport:
        # Re-dispatch an interrupted submission without replacing its plan.
        self.store.resume(self.project_id)
        supervisor = WorkerSupervisor(self.queue,
            policy=SupervisorPolicy(max_briefs=MAX_PROJECT_TASKS, wall_clock_s=3600))
        return supervisor.run(worker_id, self._execute)

    def _execute(self, work: ClaimedWork) -> Disposition:
        scope = ExecutionScope.borrowed(self.queue.authority, work.grant,
                                        work.cancellation_token)
        scope.check()
        composition = build_production_deployment(self.config, self.publication, scope=scope)
        outcome = composition.run_brief(work.brief)
        scope.check()
        if outcome.success and outcome.publication_state == "ANCHORED":
            return Disposition.COMPLETED
        # Quota/budget holds are not code failures. Publication/integration
        # refusals preserve their evidence and do not release dependent work.
        records = composition.pipeline.records
        if (records.exists(work.brief_id)
                and records.get(work.brief_id).state is BriefRecordState.PARKED):
            return Disposition.PARK
        return Disposition.BLOCK

    def status(self) -> dict[str, Any]:
        plan = self.store.load(self.project_id)
        completed = self.queue.done_ids()
        return {"project_id": self.project_id, "task_count": len(plan.tasks),
                "completed": completed, "pending": self.queue.pending_ids(),
                "running": self.queue.running_ids(), "blocked": self.queue.blocked_ids(),
                "dependencies_waiting": self.queue.dependency_waiting_ids(),
                "complete": len(completed) == len(plan.tasks)}
