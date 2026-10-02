import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from gnosis.director.projects import ProjectPlan, ProjectStore, ProjectTask
from tests.test_task_dependencies import brief, queue_at


def plan() -> ProjectPlan:
    return ProjectPlan("project", (
        ProjectTask(brief("project--child"), ("project--root",)),
        ProjectTask(brief("project--root")),
    ))


def test_project_dispatch_restart_and_dependency_execution(tmp_path: Path) -> None:
    queue = queue_at(tmp_path)
    store = ProjectStore(tmp_path / "projects", queue)
    store.submit(plan())
    restored = ProjectStore(tmp_path / "projects", queue_at(tmp_path))
    restored.resume("project")
    root = restored.queue.claim("worker")
    assert root is not None and root.brief_id == "project--root"
    restored.queue.complete(root, "COMPLETED")
    child = restored.queue.claim("worker")
    assert child is not None and child.brief_id == "project--child"


def test_partial_dispatch_is_resumable(tmp_path: Path) -> None:
    queue = queue_at(tmp_path)
    store = ProjectStore(tmp_path / "projects", queue)
    enqueue = queue.enqueue

    def crash(brief, **kwargs):
        if brief.brief_id.endswith("child"):
            raise OSError("simulated crash")
        return enqueue(brief, **kwargs)

    with patch.object(queue, "enqueue", side_effect=crash), pytest.raises(OSError):
        store.submit(plan())
    assert queue.pending_ids() == ["project--root"]
    restored = ProjectStore(tmp_path / "projects", queue_at(tmp_path))
    restored.resume("project")
    assert restored.queue.pending_ids() == ["project--child", "project--root"]


def test_replacing_project_is_refused(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects", queue_at(tmp_path))
    original = plan()
    store.submit(original)
    changed = replace(original, tasks=(ProjectTask(brief("project--different")),))
    with pytest.raises(ValueError, match="cannot be replaced"):
        store.submit(changed)
    assert store.load("project").to_dict() == original.to_dict()


def test_existing_foreign_task_cannot_be_adopted(tmp_path: Path) -> None:
    queue = queue_at(tmp_path)
    queue.enqueue(replace(brief("project--root"), mission="different work"))
    with pytest.raises(ValueError, match="differs"):
        ProjectStore(tmp_path / "projects", queue).submit(plan())


def test_cycle_rejected_without_dispatch(tmp_path: Path) -> None:
    queue = queue_at(tmp_path)
    store = ProjectStore(tmp_path / "projects", queue)
    cyclic = ProjectPlan("project", (
        ProjectTask(brief("project--a"), ("project--b",)),
        ProjectTask(brief("project--b"), ("project--a",)),
    ))
    with pytest.raises(ValueError, match="cyclic"):
        store.submit(cyclic)
    assert queue.pending_ids() == []
    assert list(store.root.glob("*.json")) == []


@pytest.mark.parametrize("mutation", ["unknown_field", "string_dependencies", "non_object"])
def test_malformed_stored_plan_cannot_dispatch(tmp_path: Path, mutation: str) -> None:
    store = ProjectStore(tmp_path / "projects", queue_at(tmp_path))
    data = plan().to_dict()
    if mutation == "unknown_field":
        data["tasks"][0]["command"] = "untrusted"
    elif mutation == "string_dependencies":
        data["tasks"][0]["dependencies"] = "project--root"
    else:
        data = []
    (store.root / "project.json").write_text(json.dumps(data))
    with pytest.raises(ValueError):
        store.resume("project")
    assert store.queue.pending_ids() == []
