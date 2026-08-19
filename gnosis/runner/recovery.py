"""Crash/restart detection and basic resume/recovery.

A run is "stale" if its meta.json says RUNNING but its heartbeat file
has not been touched recently. On kernel startup (or on demand),
RecoveryManager.scan() sweeps runs/ for stale RUNNING runs, transitions
them to CRASHED (a terminal run state, see kernel.state_machine), and
appends a ledger event recording the detection. This is bootstrap-level
recovery: it detects and marks crashes deterministically; deciding whether
to spawn a fresh retry run is left to the caller (kernel.engine or a
future orchestrator), since that decision may need task-level context.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ..kernel.run_store import RunStore
from ..kernel.state_machine import RunState


@dataclass(frozen=True)
class CrashReport:
    run_id: str
    task_id: str
    last_heartbeat_ts: Optional[str]
    stale_for_s: Optional[float]


class RecoveryManager:
    def __init__(self, run_store: RunStore, stale_after_s: float = 120.0):
        self.run_store = run_store
        self.stale_after_s = stale_after_s

    def scan(self) -> list:
        crashed: list = []
        for run_id in self.run_store.list_run_ids():
            meta = self.run_store.read_meta(run_id)
            if meta.state != RunState.RUNNING.value:
                continue
            heartbeat = self.run_store.read_heartbeat(run_id)
            stale_for = self._staleness(heartbeat)
            if stale_for is None or stale_for >= self.stale_after_s:
                self.run_store.update_state(run_id, RunState.CRASHED)
                ledger = self.run_store.ledger_for(run_id)
                ledger.append(run_id, "run.crashed_detected", {
                    "last_heartbeat_ts": heartbeat.get("ts") if heartbeat else None,
                    "stale_for_s": stale_for,
                })
                crashed.append(CrashReport(
                    run_id=run_id, task_id=meta.task_id,
                    last_heartbeat_ts=heartbeat.get("ts") if heartbeat else None,
                    stale_for_s=stale_for,
                ))
        return crashed

    def _staleness(self, heartbeat: Optional[dict]) -> Optional[float]:
        if not heartbeat or not heartbeat.get("ts"):
            return None
        ts = datetime.fromisoformat(heartbeat["ts"])
        now = datetime.now(timezone.utc)
        return (now - ts).total_seconds()
