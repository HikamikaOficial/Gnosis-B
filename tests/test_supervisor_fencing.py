from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_queue_fencing import fixture

from gnosis.director.supervisor import Disposition, StopReason, WorkerSupervisor
from gnosis.kernel.budget import BudgetExhausted
from gnosis.kernel.lease import StaleLeaseError


@pytest.mark.parametrize("mode", ["completed", "block", "park", "invalid", "raised", "budget"])
@pytest.mark.parametrize("pump_noticed", [False, True])
def test_every_handler_exit_respects_replacement_owner(tmp_path, mode, pump_noticed):
    queue, now = fixture(tmp_path)
    heartbeat = Mock(deposed=None)
    new = None
    before = None
    path = queue.root / "running/task.json"

    def handler(work):
        nonlocal new, before
        now[0] += 11
        queue.authority.sweep()
        queue.recover()
        new = queue.claim("replacement")
        assert new is not None
        before = path.read_bytes()
        if pump_noticed:
            heartbeat.deposed = StaleLeaseError("claim replaced during handler")
        if mode == "raised":
            raise OSError("worker exited")
        if mode == "budget":
            raise BudgetExhausted("launches", 3, 3)
        return {"completed": Disposition.COMPLETED, "block": Disposition.BLOCK,
                "park": Disposition.PARK, "invalid": None}[mode]

    with patch("gnosis.director.supervisor.GrantHeartbeatPump", return_value=heartbeat):
        report = WorkerSupervisor(queue).run("old", handler)
    assert report.stopped_because is (StopReason.DEPOSED if pump_noticed else StopReason.OWNERSHIP_LOST)
    assert report.completed == report.parked == report.blocked == ()
    assert report.errors
    assert path.read_bytes() == before
    assert queue.running_ids() == ["task"]
    assert queue.pending_ids() == queue.done_ids() == queue.blocked_ids() == []
    queue.authority.assert_current(new.grant)
    heartbeat.stop.assert_called_once()
