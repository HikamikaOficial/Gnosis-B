"""Typed, bounded, compare-and-swap Director phase checkpoints.

Records are recovery inputs, not completion authority. The canonical caller must
keep this store inside the protected trust root and revalidate the saved subject
before reusing verification/review. No executable object or import name is read
from disk: the codec admits only the explicit internal data contracts below.
"""
from __future__ import annotations

import json
import math
import types
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.contracts.engineer_report import EngineerReport, ReportStatus
from gnosis.director.publication import GitTreeEvidence
from gnosis.kernel.atomic_io import atomic_write_text
from gnosis.kernel.canonical import hash_canonical
from gnosis.kernel.convergence import (
    ConvergenceOutcome,
    ConvergenceResult,
    EvidenceFailure,
    Finding,
    FixReport,
    GatedFinding,
    ReviewReport,
    ReviewVerdict,
    RoundRecord,
    Severity,
)
from gnosis.kernel.engine import TaskExecutionOutcome
from gnosis.kernel.execution_scope import ExecutionScope
from gnosis.kernel.failures import (
    EvidenceGrade,
    FailureClass,
    FailureClassification,
    HoldScope,
    RateLimitHold,
)
from gnosis.kernel.file_lock import FileLock, lock_path_for
from gnosis.kernel.integration import IntegrationOutcome, IntegrationResult, PreparedIntegration
from gnosis.kernel.scheduler import ScheduleOutcome
from gnosis.kernel.state_machine import TaskState
from gnosis.kernel.subject import SubjectIdentity
from gnosis.kernel.verification import MalformedEvidence, VerificationResult
from gnosis.runner.capture import ExecutionResult, RecordedAttempt
from gnosis.trust.launch_spec import LaunchSpec
from gnosis.trust.run_identity import is_storable_run_id
from gnosis.trust.worker_launcher import LaunchedWorkerIdentity

MAX_CHECKPOINT_BYTES = 16 * 1024**2
MAX_NESTING = 64


class CheckpointError(RuntimeError):
    """Missing, corrupt, incompatible or stale recovery state; never restart fresh."""


@dataclass(frozen=True)
class TrustedAttempt:
    spec: LaunchSpec
    launched: LaunchedWorkerIdentity
    epoch: int | None = None

    def __post_init__(self) -> None:
        if self.epoch is not None and (type(self.epoch) is not int or self.epoch < 1):
            raise CheckpointError("claimed attempt requires a positive fencing epoch")


@dataclass(frozen=True)
class CapturedProof:
    run_id: str
    attempt: int
    bundle_digest: str
    tree: GitTreeEvidence


@dataclass(frozen=True)
class PipelineCheckpoint:
    brief: DirectorBrief
    task_id: str
    context_digest: str
    revision: int = 0
    implementation: ScheduleOutcome | None = None
    convergence: ConvergenceResult | None = None
    subject: SubjectIdentity | None = None
    trusted_attempt: TrustedAttempt | None = None
    attempt_ids: tuple[str, ...] = ()
    rework_attempts: tuple[RecordedAttempt, ...] = ()
    implementation_attempts: int = 0
    rounds_started: int = 0
    launches: int = 0
    elapsed_s: float = 0.0
    proof_attempts: int = 0
    proof: CapturedProof | None = None
    prepared_integration: PreparedIntegration | None = None
    integration: IntegrationResult | None = None
    integration_attempts: int = 0

    def __post_init__(self) -> None:
        if (not is_storable_run_id(self.brief.brief_id)
                or not is_storable_run_id(self.task_id)
                or len(self.context_digest) != 64
                or any(c not in "0123456789abcdef" for c in self.context_digest)):
            raise CheckpointError("invalid checkpoint identity or context digest")
        for count in (self.revision, self.implementation_attempts, self.rounds_started,
                      self.launches, self.proof_attempts, self.integration_attempts):
            if type(count) is not int or count < 0:
                raise CheckpointError("invalid checkpoint counter")
        if (type(self.elapsed_s) not in (int, float)
                or not math.isfinite(self.elapsed_s) or self.elapsed_s < 0):
            raise CheckpointError("invalid checkpoint elapsed time")
        if (len(set(self.attempt_ids)) != len(self.attempt_ids)
                or any(not is_storable_run_id(rid) for rid in self.attempt_ids)):
            raise CheckpointError("invalid checkpoint attempt references")
        if self.implementation is not None:
            work = self.implementation.execution
            if (self.implementation.task_id != self.task_id
                    or (work is not None and (work.task_id != self.task_id
                        or work.report.task_id != self.task_id
                        or not set(work.run_ids) <= set(self.attempt_ids)))):
                raise CheckpointError("checkpoint implementation attribution mismatch")
        if any(a.task_id != self.task_id or a.run_id not in self.attempt_ids
               for a in self.rework_attempts):
            raise CheckpointError("checkpoint correction attribution mismatch")
        if (self.trusted_attempt is not None
                and self.trusted_attempt.spec.run_id not in self.attempt_ids):
            raise CheckpointError("checkpoint launch has no recorded attempt")
        if self.proof is not None and (self.trusted_attempt is None
                or self.proof.run_id != self.trusted_attempt.spec.run_id
                or type(self.proof.attempt) is not int
                or self.proof.attempt < 1 or self.proof.attempt != self.proof_attempts
                or len(self.proof.bundle_digest) != 64
                or any(c not in "0123456789abcdef" for c in self.proof.bundle_digest)):
            raise CheckpointError("checkpoint proof attribution mismatch")
        if self.prepared_integration is not None and (
                self.proof is None or self.prepared_integration.task_id != self.task_id):
            raise CheckpointError("integration preparation requires this task's proof")
        if self.integration is not None:
            if self.integration.task_id != self.task_id:
                raise CheckpointError("integration result attribution mismatch")
            if self.integration.integrated and (self.prepared_integration is None
                    or self.integration.merged_sha != self.prepared_integration.merged_sha):
                raise CheckpointError("completed integration has no matching preparation")


_DATA_TYPES: tuple[type[Any], ...] = (
    PipelineCheckpoint, TrustedAttempt, CapturedProof, GitTreeEvidence, DirectorBrief, EngineerReport,
    PreparedIntegration, IntegrationResult,
    ScheduleOutcome, TaskExecutionOutcome, ExecutionResult, RecordedAttempt,
    ConvergenceResult, RoundRecord, Finding, GatedFinding, ReviewReport, FixReport,
    EvidenceFailure, SubjectIdentity, VerificationResult, MalformedEvidence,
    FailureClassification, RateLimitHold, LaunchSpec, LaunchedWorkerIdentity,
)
_ENUM_TYPES: tuple[type[Enum], ...] = (
    BriefSource, ReportStatus, TaskState, ConvergenceOutcome, ReviewVerdict, IntegrationOutcome,
    Severity, FailureClass, EvidenceGrade, HoldScope,
)
_DATA = {kind.__name__: kind for kind in _DATA_TYPES}
_ENUMS = {kind.__name__: kind for kind in _ENUM_TYPES}


def _matches(value: Any, annotation: Any) -> bool:
    if annotation is Any:
        return True
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        return any(_matches(value, item) for item in args)
    if origin in (tuple, list):
        if type(value) is not origin:
            return False
        if origin is list or len(args) == 2 and args[1] is Ellipsis:
            return all(_matches(item, args[0]) for item in value)
        return len(value) == len(args) and all(_matches(v, t) for v, t in zip(value, args, strict=True))
    if origin is dict:
        return type(value) is dict and all(_matches(k, args[0]) and _matches(v, args[1])
                                          for k, v in value.items())
    if annotation is float:
        return type(value) in (int, float) and math.isfinite(value)
    return type(value) is annotation


def _encode(value: Any, depth: int = 0) -> Any:
    if depth > MAX_NESTING:
        raise CheckpointError("checkpoint nesting exceeds bound")
    cls = type(value)
    if cls in _ENUM_TYPES:
        return {"enum": cls.__name__, "value": value.value}
    if cls in _DATA_TYPES:
        hints = get_type_hints(cls)
        data = {}
        for field in fields(value):
            item = getattr(value, field.name)
            if not _matches(item, hints[field.name]):
                raise CheckpointError(f"invalid {cls.__name__}.{field.name} type")
            data[field.name] = _encode(item, depth + 1)
        return {"type": cls.__name__, "fields": data}
    if is_dataclass(value) or isinstance(value, Enum):
        raise CheckpointError("unregistered checkpoint contract")
    if cls is tuple:
        return {"tuple": [_encode(item, depth + 1) for item in value]}
    if cls is dict:
        if any(type(key) is not str for key in value):
            raise CheckpointError("checkpoint mapping keys must be strings")
        return {"dict": {key: _encode(item, depth + 1) for key, item in value.items()}}
    if cls is list:
        return [_encode(item, depth + 1) for item in value]
    if value is None or cls in (str, int, bool) or cls is float and math.isfinite(value):
        return value
    raise CheckpointError("unsupported checkpoint value")


def _decode(value: Any, depth: int = 0) -> Any:
    if depth > MAX_NESTING:
        raise CheckpointError("checkpoint nesting exceeds bound")
    if type(value) is list:
        return [_decode(item, depth + 1) for item in value]
    if type(value) is not dict:
        if (value is None or type(value) in (str, int, bool)
                or type(value) is float and math.isfinite(value)):
            return value
        raise CheckpointError("invalid checkpoint primitive")
    keys = set(value)
    if keys == {"tuple"} and type(value["tuple"]) is list:
        return tuple(_decode(item, depth + 1) for item in value["tuple"])
    if keys == {"dict"} and type(value["dict"]) is dict:
        return {key: _decode(item, depth + 1) for key, item in value["dict"].items()}
    if keys == {"enum", "value"} and value["enum"] in _ENUMS:
        return _ENUMS[value["enum"]](value["value"])
    if keys == {"type", "fields"} and value["type"] in _DATA:
        cls = _DATA[value["type"]]
        data = value["fields"]
        if type(data) is not dict or set(data) != {field.name for field in fields(cls)}:
            raise CheckpointError("checkpoint contract fields differ")
        hints = get_type_hints(cls)
        kwargs = {key: _decode(item, depth + 1) for key, item in data.items()}
        if any(not _matches(item, hints[key]) for key, item in kwargs.items()):
            raise CheckpointError(f"invalid {cls.__name__} field type")
        return cls(**kwargs)
    raise CheckpointError("unknown checkpoint contract")


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, item in pairs:
        if key in data:
            raise CheckpointError("duplicate checkpoint key")
        data[key] = item
    return data


class PipelineCheckpointStore:
    def __init__(self, root: Path, scope: ExecutionScope | None = None) -> None:
        self.root = root
        self.scope = scope

    def path_for(self, brief_id: str) -> Path:
        if not is_storable_run_id(brief_id):
            raise CheckpointError("invalid checkpoint brief identifier")
        return self.root / f"{brief_id}.json"

    def load(self, brief_id: str) -> PipelineCheckpoint | None:
        path = self.path_for(brief_id)
        try:
            with path.open("rb") as handle:
                raw = handle.read(MAX_CHECKPOINT_BYTES + 1)
        except FileNotFoundError:
            history = self.root / "history" / brief_id
            if history.is_dir() and any(history.glob("*.json")):
                raise CheckpointError("checkpoint selector missing; preserved generations require recovery")
            return None
        try:
            if len(raw) > MAX_CHECKPOINT_BYTES:
                raise CheckpointError("checkpoint exceeds byte bound")
            data = json.loads(raw, object_pairs_hook=_unique)
            if (not isinstance(data, dict) or set(data) != {"schema", "record"}
                    or data["schema"] != "gnosis.pipeline-checkpoint.v1"):
                raise CheckpointError("unknown checkpoint envelope")
            record = _decode(data["record"])
            if not isinstance(record, PipelineCheckpoint) or record.brief.brief_id != brief_id:
                raise CheckpointError("checkpoint filed under a different brief")
            generation = (self.root / "history" / brief_id
                          / f"{record.revision:08d}-{hash_canonical(data)}.json")
            with generation.open("rb") as handle:
                saved = handle.read(MAX_CHECKPOINT_BYTES + 1)
            if saved != json.dumps(data, sort_keys=True, allow_nan=False).encode("utf-8"):
                raise CheckpointError("checkpoint differs from its immutable generation")
            return record
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            raise CheckpointError(f"invalid checkpoint: {type(exc).__name__}") from exc

    def create(self, record: PipelineCheckpoint) -> PipelineCheckpoint:
        path = self.path_for(record.brief.brief_id)
        with FileLock(lock_path_for(path)):
            existing = self.load(record.brief.brief_id)
            if existing is not None:
                if (existing.brief != record.brief
                        or existing.context_digest != record.context_digest):
                    raise CheckpointError("existing brief/context cannot be replaced")
                return existing
            if record.revision != 0:
                raise CheckpointError("initial checkpoint revision must be zero")
            self._write(record)
            return record

    def update(self, prior: PipelineCheckpoint, **changes: Any) -> PipelineCheckpoint:
        if set(changes) & {"brief", "task_id", "context_digest", "revision"}:
            raise CheckpointError("checkpoint assignment is immutable")
        with FileLock(lock_path_for(self.path_for(prior.brief.brief_id))):
            current = self.load(prior.brief.brief_id)
            if current != prior:
                raise CheckpointError("stale checkpoint update")
            updated = replace(prior, revision=prior.revision + 1, **changes)
            if (not set(prior.attempt_ids) <= set(updated.attempt_ids)
                    or updated.launches < prior.launches
                    or updated.rounds_started < prior.rounds_started
                    or updated.implementation_attempts < prior.implementation_attempts
                    or updated.proof_attempts < prior.proof_attempts
                    or updated.integration_attempts < prior.integration_attempts
                    or updated.elapsed_s < prior.elapsed_s):
                raise CheckpointError("checkpoint cannot forget attempts or spend")
            if prior.proof is not None and updated.proof != prior.proof:
                raise CheckpointError("captured proof is immutable")
            if (prior.prepared_integration is not None
                    and updated.prepared_integration != prior.prepared_integration):
                raise CheckpointError("prepared integration is immutable")
            if (prior.integration is not None and prior.integration.integrated
                    and updated.integration != prior.integration):
                raise CheckpointError("completed integration is immutable")
            self._write(updated)
            return updated

    def _write(self, record: PipelineCheckpoint) -> None:
        payload = {"schema": "gnosis.pipeline-checkpoint.v1", "record": _encode(record)}
        raw = json.dumps(payload, sort_keys=True, allow_nan=False)
        if len(raw.encode("utf-8")) > MAX_CHECKPOINT_BYTES:
            raise CheckpointError("checkpoint exceeds byte bound")
        # Immutable generations preserve the recovery/audit trail. A crash before
        # replacing the selector leaves only an unused generation, not lost work.
        generation = (self.root / "history" / record.brief.brief_id
                      / f"{record.revision:08d}-{hash_canonical(payload)}.json")

        def commit() -> None:
            generation.parent.mkdir(parents=True, exist_ok=True)
            if generation.exists() and generation.read_text(encoding="utf-8") != raw:
                raise CheckpointError("checkpoint generation was modified")
            if not generation.exists():
                atomic_write_text(generation, raw)
            atomic_write_text(self.path_for(record.brief.brief_id), raw)

        if self.scope is None:
            commit()
        else:
            self.scope.commit(commit)


@dataclass
class CheckpointSession:
    """One invocation's CAS cursor; callers hold the brief's operation lock."""

    store: PipelineCheckpointStore
    current: PipelineCheckpoint

    def save(self, **changes: Any) -> None:
        self.current = self.store.update(self.current, **changes)
