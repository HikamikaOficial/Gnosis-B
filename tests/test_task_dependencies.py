"""Dependency scheduling uses durable queue state and resolved claims together."""
import json
from pathlib import Path

import pytest

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.director.work_queue import WorkQueue
from gnosis.kernel.claims import ClaimStore, WorkAuthority
from gnosis.kernel.lease import LeaseStore


def queue_at(root: Path) -> WorkQueue:
    return WorkQueue(root / "queue", WorkAuthority(
        ClaimStore(root / "claims.json"), LeaseStore(root / "leases.json"),
        default_ttl_s=60))


def brief(identifier: str) -> DirectorBrief:
    return DirectorBrief(identifier, "task", "implement", BriefSource.MANUAL)


def test_chain_survives_restart_and_waits_for_success(tmp_path: Path) -> None:
    queue = queue_at(tmp_path)
    queue.enqueue(brief("Z-root"))
    queue.enqueue(brief("A-child"), dependencies=("Z-root",))
    first = queue.claim("worker")
    assert first is not None and first.brief_id == "Z-root"
    assert queue_at(tmp_path).claim("other") is None
    queue.complete(first, "COMPLETED")
    second = queue_at(tmp_path).claim("other")
    assert second is not None and second.brief_id == "A-child"


def test_failed_dependency_never_unblocks_child(tmp_path: Path) -> None:
    queue = queue_at(tmp_path)
    queue.enqueue(brief("root"))
    queue.enqueue(brief("child"), dependencies=("root",))
    work = queue.claim("worker")
    assert work is not None
    queue.complete(work, "FAILED")
    assert queue_at(tmp_path).claim("other") is None


def test_done_file_alone_cannot_satisfy_dependency(tmp_path: Path) -> None:
    queue = queue_at(tmp_path)
    queue.enqueue(brief("root"))
    queue.enqueue(brief("child"), dependencies=("root",))
    work = queue.claim("worker")
    assert work is not None
    record = {"brief": brief("root").to_dict(), "outcome": "COMPLETED"}
    (queue.root / "done" / "root.json").write_text(json.dumps(record))
    assert queue.claim("other") is None


@pytest.mark.parametrize("deps", [("missing",), ("child",), ("../escape",),
                                  ("root", "root")])
def test_invalid_dependencies_are_rejected(tmp_path: Path, deps: tuple[str, ...]) -> None:
    queue = queue_at(tmp_path)
    queue.enqueue(brief("root"))
    with pytest.raises(ValueError):
        queue.enqueue(brief("child"), dependencies=deps)
    assert "child" not in queue.pending_ids()


def test_fan_in_requires_every_predecessor(tmp_path: Path) -> None:
    queue = queue_at(tmp_path)
    queue.enqueue(brief("first"))
    queue.enqueue(brief("second"))
    queue.enqueue(brief("child"), dependencies=("first", "second"))
    a = queue.claim("a")
    b = queue.claim("b")
    assert a is not None and b is not None
    queue.complete(a, "COMPLETED")
    assert queue.claim("c") is None
    queue.complete(b, "COMPLETED")
    c = queue.claim("c")
    assert c is not None and c.brief_id == "child"


def test_supervisor_reports_waiting_dependencies_not_empty(tmp_path: Path) -> None:
    from gnosis.director.supervisor import StopReason, WorkerSupervisor

    queue = queue_at(tmp_path)
    queue.enqueue(brief("root"))
    queue.enqueue(brief("child"), dependencies=("root",))
    root = queue.claim("first")
    assert root is not None
    queue.block(root, "requires attention")
    report = WorkerSupervisor(queue).run("second", lambda work: pytest.fail("ran child"))
    assert report.stopped_because == StopReason.DEPENDENCIES_WAITING
