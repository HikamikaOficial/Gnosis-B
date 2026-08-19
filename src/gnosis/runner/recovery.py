"""Crash/restart detection and basic resume/recovery.

Two independent signals decide whether a RUNNING run is actually dead:

1. Process liveness (kernel.liveness): does the PID + start-time
   fingerprint recorded in the last heartbeat still correspond to a live
   process? This catches abnormal termination immediately, no need to
   wait out a staleness window, and is immune to PID reuse because the
   fingerprint includes process start time, not just the PID.
2. Heartbeat staleness: has *any* heartbeat been written recently? This
   catches the case liveness alone cannot: a process that is alive but
   hung/deadlocked and no longer making progress.

A run is declared CRASHED if either signal fires. On kernel startup (or
on demand), RecoveryManager.scan() sweeps runs/ for such runs, transitions
them to CRASHED (a terminal run state, see kernel.state_machine), and
appends a ledger event recording which signal(s) fired. This is
bootstrap-level recovery: it detects and marks crashes deterministically;
deciding whether to spawn a fresh retry run is left to the caller
(kernel.engine, or the director orchestrator), since that decision may
need task-level context.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..kernel.run_store import RunStore
from ..kernel.state_machine import RunState
from .liveness import ProcessFingerprint, is_alive


@dataclass(frozen=True)
class CrashReport:
    run_id: str
    task_id: str
    last_heartbeat_ts: str | None
    stale_for_s: float | None
    process_alive: bool | None
    reason: str


class RecoveryManager:
    def __init__(self, run_store: RunStore, stale_after_s: float = 120.0):
        self.run_store = run_store
        self.stale_after_s = stale_after_s

    def scan(self) -> list[CrashReport]:
        crashed: list[CrashReport] = []
        for run_id in self.run_store.list_run_ids():
            meta = self.run_store.read_meta(run_id)
            if meta.state != RunState.RUNNING.value:
                continue
            heartbeat = self.run_store.read_heartbeat(run_id)
            stale_for = self._staleness(heartbeat)
            process_alive = self._process_alive(heartbeat)

            reason = None
            if process_alive is False:
                reason = "process_not_alive"
            elif stale_for is None:
                reason = "no_heartbeat"
            elif stale_for >= self.stale_after_s:
                reason = "heartbeat_stale"

            if reason is not None:
                self.run_store.update_state(run_id, RunState.CRASHED)
                ledger = self.run_store.ledger_for(run_id)
                ledger.append(run_id, "run.crashed_detected", {
                    "reason": reason,
                    "last_heartbeat_ts": heartbeat.get("ts") if heartbeat else None,
                    "stale_for_s": stale_for,
                    "process_alive": process_alive,
                })
                crashed.append(CrashReport(
                    run_id=run_id, task_id=meta.task_id,
                    last_heartbeat_ts=heartbeat.get("ts") if heartbeat else None,
                    stale_for_s=stale_for, process_alive=process_alive, reason=reason,
                ))
        return crashed

    def _staleness(self, heartbeat: dict | None) -> float | None:
        if not heartbeat or not heartbeat.get("ts"):
            return None
        ts = datetime.fromisoformat(heartbeat["ts"])
        now = datetime.now(UTC)
        return (now - ts).total_seconds()

    def _process_alive(self, heartbeat: dict | None) -> bool | None:
        if not heartbeat or "pid" not in heartbeat:
            return None
        fingerprint = ProcessFingerprint.from_dict(heartbeat)
        return is_alive(fingerprint)
