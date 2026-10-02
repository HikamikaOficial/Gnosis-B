"""Durable immutable project plans, dispatched into the existing work queue.

Plans establish dependencies, never task completion. Claims and the governed
pipeline retain ownership and completion authority. A crash during dispatch is
resumed from the stored plan with the queue's idempotent enqueue operation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gnosis.contracts.director_brief import DirectorBrief
from gnosis.director.work_queue import WorkQueue
from gnosis.kernel.atomic_io import atomic_write_text
from gnosis.kernel.file_lock import FileLock, lock_path_for

MAX_PLAN_BYTES = 4 * 1024 * 1024
MAX_PROJECT_TASKS = 1000


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key in project plan")
        result[key] = value
    return result


@dataclass(frozen=True)
class ProjectTask:
    brief: DirectorBrief
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectPlan:
    project_id: str
    tasks: tuple[ProjectTask, ...]

    @classmethod
    def read(cls, path: Path) -> ProjectPlan:
        with path.open("rb") as stream:
            raw = stream.read(MAX_PLAN_BYTES + 1)
        if len(raw) > MAX_PLAN_BYTES:
            raise ValueError("project plan exceeds byte bound")
        data = json.loads(raw, object_pairs_hook=_unique_object)
        if (not isinstance(data, dict)
                or set(data) != {"schema", "project_id", "tasks"}
                or data["schema"] != "gnosis.project.v1"
                or not isinstance(data["project_id"], str)
                or not isinstance(data["tasks"], list)
                or not 1 <= len(data["tasks"]) <= MAX_PROJECT_TASKS):
            raise ValueError("invalid project envelope")
        for item in data["tasks"]:
            if (not isinstance(item, dict) or set(item) != {"brief", "dependencies"}
                    or not isinstance(item["brief"], dict)
                    or not isinstance(item["dependencies"], list)
                    or any(not isinstance(dep, str) for dep in item["dependencies"])):
                raise ValueError("invalid project task")
        plan = cls(data["project_id"], tuple(
            ProjectTask(DirectorBrief.from_dict(item["brief"]), tuple(item["dependencies"]))
            for item in data["tasks"]))
        plan.ordered()
        return plan

    def ordered(self) -> tuple[ProjectTask, ...]:
        if re.fullmatch(r"[A-Za-z0-9_]{1,64}", self.project_id) is None:
            raise ValueError("invalid project identifier")
        if not 1 <= len(self.tasks) <= MAX_PROJECT_TASKS:
            raise ValueError("project task count exceeds bounds")
        remaining = {task.brief.brief_id: task for task in self.tasks}
        if len(remaining) != len(self.tasks):
            raise ValueError("duplicate project task")
        # Namespace tasks to prevent projects from adopting one another's work.
        for name, task in remaining.items():
            if (not name.startswith(self.project_id + "--")
                    or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", name) is None):
                raise ValueError("task identifier must be namespaced by project_id--")
            if (len(set(task.dependencies)) != len(task.dependencies)
                    or any(dep not in remaining for dep in task.dependencies)):
                raise ValueError("duplicate or missing project dependency")
        ordered: list[ProjectTask] = []
        ready: set[str] = set()
        while remaining:
            batch = [name for name, task in remaining.items()
                     if set(task.dependencies) <= ready]
            if not batch:
                raise ValueError("cyclic project dependencies")
            for name in sorted(batch):
                ordered.append(remaining.pop(name))
                ready.add(name)
        return tuple(ordered)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": "gnosis.project.v1", "project_id": self.project_id,
                "tasks": [{"brief": task.brief.to_dict(),
                           "dependencies": list(task.dependencies)}
                          for task in self.ordered()]}


class ProjectStore:
    def __init__(self, root: Path, queue: WorkQueue) -> None:
        self.root = root
        self.queue = queue
        self.root.mkdir(parents=True, exist_ok=True)

    def submit(self, plan: ProjectPlan) -> None:
        payload = json.dumps(plan.to_dict(), sort_keys=True, ensure_ascii=True)
        if len(payload.encode("utf-8")) > MAX_PLAN_BYTES:
            raise ValueError("project plan exceeds byte bound")
        path = self.root / f"{plan.project_id}.json"
        with FileLock(lock_path_for(path)):
            if path.exists():
                if self.load(plan.project_id).to_dict() != plan.to_dict():
                    raise ValueError("existing project plan cannot be replaced")
            else:
                atomic_write_text(path, payload)
            self._dispatch(plan)

    def load(self, project_id: str) -> ProjectPlan:
        if re.fullmatch(r"[A-Za-z0-9_]{1,64}", project_id) is None:
            raise ValueError("invalid project identifier")
        plan = ProjectPlan.read(self.root / f"{project_id}.json")
        if plan.project_id != project_id:
            raise ValueError("invalid project envelope")
        return plan

    def resume(self, project_id: str) -> None:
        self.submit(self.load(project_id))

    def _dispatch(self, plan: ProjectPlan) -> None:
        for task in plan.ordered():
            self.queue.enqueue(task.brief, dependencies=task.dependencies, require_matching=True)
