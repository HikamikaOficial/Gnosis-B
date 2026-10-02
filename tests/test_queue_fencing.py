"""Queue writes are fenced and recovery requires a committed transition."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.director.work_queue import WorkQueue
from gnosis.kernel.claims import ClaimStatus, ClaimStore, WorkAuthority
from gnosis.kernel.lease import LeaseStore, StaleLeaseError


def fixture(root: Path) -> tuple[WorkQueue, list[float]]:
    now = [1000.0]
    clock = lambda: now[0]
    authority = WorkAuthority(
        ClaimStore(root / "claims.json", clock=clock),
        LeaseStore(root / "leases.json", clock=clock),
        default_ttl_s=10, reclaim_grace_s=0, clock=clock)
    queue = WorkQueue(root / "queue", authority, clock=clock)
    queue.enqueue(DirectorBrief("task", "test", "implement", BriefSource.MANUAL))
    return queue, now


@pytest.mark.parametrize("transition,args", [
    ("complete", {"outcome": "COMPLETED"}),
    ("release", {"reason": "old worker", "not_before": 99999}),
    ("block", {"reason": "old worker"}),
])
def test_stale_worker_cannot_touch_new_owner_record(tmp_path, transition, args):
    queue, now = fixture(tmp_path)
    old = queue.claim("old")
    assert old is not None
    now[0] += 11
    queue.authority.sweep()
    queue.recover()
    new = queue.claim("new")
    assert new is not None
    path = queue.root / "running/task.json"
    before = path.read_bytes()
    with pytest.raises(StaleLeaseError):
        getattr(queue, transition)(old, **args)
    assert path.read_bytes() == before
    assert queue.done_ids() == queue.pending_ids() == queue.blocked_ids() == []
    queue.authority.assert_current(new.grant)
    queue.complete(new, "COMPLETED")


@pytest.mark.parametrize("transition,args", [
    ("complete", {"outcome": "COMPLETED"}),
    ("block", {"reason": "uncommitted block"}),
    ("release", {"reason": "uncommitted park", "not_before": 99999}),
])
def test_expiry_after_intent_does_not_commit_a_transition(tmp_path, transition, args):
    queue, now = fixture(tmp_path)
    work = queue.claim("old")
    assert work is not None
    original = queue._stamp

    def expire_after_stamp(*a, **kw):
        original(*a, **kw)
        now[0] += 11

    with (patch.object(queue, "_stamp", side_effect=expire_after_stamp),
          pytest.raises(StaleLeaseError)):
        getattr(queue, transition)(work, **args)
    queue.authority.sweep()
    assert queue.authority.claims.get("task").status is ClaimStatus.RECLAIMED
    queue.recover()
    assert queue.done_ids() == queue.blocked_ids() == []
    recovered = json.loads((queue.root / "pending/task.json").read_text())
    for key in ("outcome", "pending_transition", "not_before", "blocked_because"):
        assert key not in recovered
    assert queue.claim("new") is not None


def test_intent_write_failure_prevents_claim_commit(tmp_path):
    queue, _ = fixture(tmp_path)
    work = queue.claim("worker")
    assert work is not None
    with (patch("gnosis.director.work_queue._atomic_write", side_effect=OSError("disk full")),
          pytest.raises(OSError, match="disk full")):
        queue.block(work, "needs human")
    queue.authority.assert_current(work.grant)
    assert queue.running_ids() == ["task"]
    assert queue.blocked_ids() == []


def test_recovery_does_not_borrow_another_epochs_completion(tmp_path):
    queue, _ = fixture(tmp_path)
    old = queue.claim("old")
    assert old is not None
    queue.authority.release(old.grant)
    # A different epoch is resolved externally; the old record has no
    # evidence that its own execution completed.
    new = queue.authority.acquire("task", "new")
    queue.authority.resolve(new, "COMPLETED")
    queue.recover()
    assert queue.done_ids() == []
    assert queue.pending_ids() == ["task"]


def test_crash_after_move_never_leaves_two_queue_records(tmp_path):
    queue, _ = fixture(tmp_path)
    work = queue.claim("worker")
    assert work is not None
    from gnosis.director.work_queue import _atomic_write

    def interrupt_arrival(path, content):
        if path.parent.name == "done":
            raise OSError("crash after move")
        _atomic_write(path, content)

    with (patch("gnosis.director.work_queue._atomic_write", side_effect=interrupt_arrival),
          pytest.raises(OSError, match="crash after move")):
        queue.complete(work, "COMPLETED")
    assert queue.done_ids() == ["task"]
    assert queue.running_ids() == queue.pending_ids() == []
    queue.recover()
    assert queue.claim("other") is None
