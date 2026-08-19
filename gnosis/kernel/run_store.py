"""Durable, filesystem-backed run directories.

Layout per run:
  runs/<run_id>/
    meta.json          RunMeta snapshot (state, task_id, timestamps)
    heartbeat.json      liveness signal updated while the run is active
    ledger.jsonl         append-only RunLedger
    raw/stdout.log         immutable raw stdout capture
    raw/stderr.log         immutable raw stderr capture
    result.json             structured ExecutionResult, once finished
    git/                      captured git evidence snapshots (pre/post)

This directory *is* the durable state, no external database. Restarting
the kernel process is safe: everything needed to audit or reason about a
run is on disk.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .ledger import RunLedger
from .state_machine import RunState


@dataclass
class RunMeta:
    run_id: str
    task_id: str
    state: str
    created_at: str
    updated_at: str
    attempt: int = 1
    extra: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["extra"] = self.extra or {}
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunMeta":
        return cls(**data)


class RunPaths:
    def __init__(self, root: Path):
        self.root = root
        self.meta = root / "meta.json"
        self.heartbeat = root / "heartbeat.json"
        self.ledger = root / "ledger.jsonl"
        self.raw_dir = root / "raw"
        self.stdout = self.raw_dir / "stdout.log"
        self.stderr = self.raw_dir / "stderr.log"
        self.result = root / "result.json"
        self.git_dir = root / "git"


class RunStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def paths_for(self, run_id: str) -> RunPaths:
        return RunPaths(self.root / run_id)

    def create_run(self, run_id: str, task_id: str) -> RunPaths:
        paths = self.paths_for(run_id)
        paths.root.mkdir(parents=True, exist_ok=False)
        paths.raw_dir.mkdir(parents=True, exist_ok=True)
        paths.git_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        meta = RunMeta(
            run_id=run_id, task_id=task_id, state=RunState.PENDING.value,
            created_at=now, updated_at=now,
        )
        self.write_meta(run_id, meta)
        RunLedger(paths.ledger)
        return paths

    def write_meta(self, run_id: str, meta: RunMeta) -> None:
        paths = self.paths_for(run_id)
        meta.updated_at = datetime.now(timezone.utc).isoformat()
        paths.meta.write_text(json.dumps(meta.to_dict(), indent=2, sort_keys=True), encoding="utf-8")

    def read_meta(self, run_id: str) -> RunMeta:
        paths = self.paths_for(run_id)
        return RunMeta.from_dict(json.loads(paths.meta.read_text(encoding="utf-8")))

    def update_state(self, run_id: str, state: RunState) -> RunMeta:
        meta = self.read_meta(run_id)
        meta.state = state.value
        self.write_meta(run_id, meta)
        return meta

    def heartbeat(self, run_id: str, pid: Optional[int] = None) -> None:
        paths = self.paths_for(run_id)
        payload = {"ts": datetime.now(timezone.utc).isoformat(), "pid": pid}
        paths.heartbeat.write_text(json.dumps(payload), encoding="utf-8")

    def read_heartbeat(self, run_id: str) -> Optional[dict[str, Any]]:
        paths = self.paths_for(run_id)
        if not paths.heartbeat.exists():
            return None
        return json.loads(paths.heartbeat.read_text(encoding="utf-8"))

    def list_run_ids(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())

    def ledger_for(self, run_id: str) -> RunLedger:
        return RunLedger(self.paths_for(run_id).ledger)
