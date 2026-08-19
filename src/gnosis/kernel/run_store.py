"""Durable, filesystem-backed run directories.

Layout per run:
  runs/<run_id>/
    meta.json          RunMeta snapshot (state, task_id, timestamps)
    heartbeat.json      liveness signal: ts + a ProcessFingerprint
    ledger.jsonl         append-only RunLedger
    raw/stdout.log         immutable raw stdout capture
    raw/stderr.log         immutable raw stderr capture
    result.json             structured ExecutionResult, once finished
    git/                      captured git evidence snapshots (pre/post)

This directory *is* the durable state, no external database. Restarting
the kernel process is safe: everything needed to audit or reason about a
run is on disk. meta.json/heartbeat.json are written via atomic_write_text
(write-tmp + os.replace) so a reader never observes a torn write; the
meta.json read-modify-write cycle (update_state) is additionally guarded
by a FileLock so two concurrent updaters cannot silently drop one
another's transition, single-writer-per-run is enforced structurally, not
by convention.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .atomic_io import atomic_write_text
from .file_lock import FileLock, lock_path_for
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
    def from_dict(cls, data: dict[str, Any]) -> RunMeta:
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
        now = datetime.now(UTC).isoformat()
        meta = RunMeta(
            run_id=run_id, task_id=task_id, state=RunState.PENDING.value,
            created_at=now, updated_at=now,
        )
        self._write_meta_locked(paths, meta)
        RunLedger(paths.ledger)
        return paths

    def write_meta(self, run_id: str, meta: RunMeta) -> None:
        paths = self.paths_for(run_id)
        self._write_meta_locked(paths, meta)

    def _write_meta_locked(self, paths: RunPaths, meta: RunMeta) -> None:
        meta.updated_at = datetime.now(UTC).isoformat()
        with FileLock(lock_path_for(paths.meta)):
            atomic_write_text(paths.meta, json.dumps(meta.to_dict(), indent=2, sort_keys=True))

    def read_meta(self, run_id: str) -> RunMeta:
        paths = self.paths_for(run_id)
        return RunMeta.from_dict(json.loads(paths.meta.read_text(encoding="utf-8")))

    def update_state(self, run_id: str, state: RunState) -> RunMeta:
        """Atomic read-modify-write of a run's state, guarded by the same
        lock write_meta uses, so two concurrent callers cannot race and
        silently overwrite each other's transition."""
        paths = self.paths_for(run_id)
        with FileLock(lock_path_for(paths.meta)):
            meta = RunMeta.from_dict(json.loads(paths.meta.read_text(encoding="utf-8")))
            meta.state = state.value
            meta.updated_at = datetime.now(UTC).isoformat()
            atomic_write_text(paths.meta, json.dumps(meta.to_dict(), indent=2, sort_keys=True))
            return meta

    def heartbeat(self, run_id: str, fingerprint: Any | None = None) -> None:
        from ..runner.liveness import ProcessFingerprint, current_fingerprint

        paths = self.paths_for(run_id)
        fp: ProcessFingerprint = fingerprint or current_fingerprint()
        payload = {"ts": datetime.now(UTC).isoformat(), **fp.to_dict()}
        atomic_write_text(paths.heartbeat, json.dumps(payload))

    def read_heartbeat(self, run_id: str) -> dict[str, Any] | None:
        paths = self.paths_for(run_id)
        if not paths.heartbeat.exists():
            return None
        # json.loads returns Any; annotate a local so strict mypy sees the
        # declared payload shape instead of returning Any.
        payload: dict[str, Any] = json.loads(paths.heartbeat.read_text(encoding="utf-8"))
        return payload

    def list_run_ids(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())

    def ledger_for(self, run_id: str) -> RunLedger:
        return RunLedger(self.paths_for(run_id).ledger)
