"""Recovery serialization must preserve types, identities and bounded spend."""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.contracts.engineer_report import EngineerReport, ReportStatus
from gnosis.director.checkpoint import CheckpointError, PipelineCheckpoint, PipelineCheckpointStore
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
from gnosis.kernel.scheduler import ScheduleOutcome
from gnosis.kernel.state_machine import TaskState
from gnosis.kernel.subject import SubjectIdentity
from gnosis.kernel.verification import MalformedEvidence, VerificationResult
from gnosis.runner.capture import ExecutionResult, RecordedAttempt


def _record() -> PipelineCheckpoint:
    brief = DirectorBrief("brief-1", "task", "implement", BriefSource.MANUAL,
                          metadata={"type": "arbitrary metadata", "nested": [True, None, {"tuple": []}]})
    verification = VerificationResult("test", True, 0, 0.2, "passed", "")
    raw = ExecutionResult(("provider",), 0, False, False, 0.1, "stdout", "stderr", "t0", "t1",
                          {"result": {"dict": "not a codec tag"}})
    report = EngineerReport("task-1", "run-1", ReportStatus.COMPLETED, "task")
    implementation = TaskExecutionOutcome("task-1", ["run-1"], TaskState.COMPLETED,
                                           verification, raw, report)
    schedule = ScheduleOutcome("task-1", True, "ok", implementation)
    finding = Finding(Severity.INFO, "style", "document later", "reviewer", confidence=0.8)
    gate = GatedFinding(finding, "non_blocking", 1)
    subject = SubjectIdentity("a" * 40, (("file.py", "b" * 64),), (), ())
    review = ReviewReport(ReviewVerdict.PASS, (finding,), "reviewer", "observed")
    round_record = RoundRecord(1, subject.digest(), True, verification, review,
                              (), (gate,), FixReport(False, False, "prior attempt"), (), 0, subject)
    correction = RecordedAttempt("run-2", "task-1", "convergence_fix", "SUCCEEDED", raw)
    convergence = ConvergenceResult(ConvergenceOutcome.CONVERGED, (round_record,), (gate,),
                                    (finding,), ("retained warning",),
                                    (EvidenceFailure("review", "TimeoutError", "prior timeout"),),
                                    (correction,))
    return PipelineCheckpoint(brief, "task-1", "c" * 64, implementation=schedule,
        convergence=convergence, subject=subject, attempt_ids=("run-1", "run-2"),
        rework_attempts=(correction,), launches=3, rounds_started=1, implementation_attempts=1)


def test_every_evidence_type_and_raw_payload_survives_fresh_store(tmp_path: Path):
    original = _record()
    PipelineCheckpointStore(tmp_path).create(original)
    restored = PipelineCheckpointStore(tmp_path).load("brief-1")
    assert restored == original
    assert restored.convergence.rounds[0].review.verdict is ReviewVerdict.PASS
    assert restored.implementation.execution.final_task_state is TaskState.COMPLETED
    assert restored.implementation.execution.execution_result.command == ("provider",)
    assert restored.brief.metadata == original.brief.metadata


def test_malformed_evidence_remains_malformed(tmp_path: Path):
    record = _record()
    bad = MalformedEvidence("broken verifier", "no readable verdict", ({"passed": 1},))
    execution = replace(record.implementation.execution, verification=bad)
    record = replace(record, implementation=replace(record.implementation, execution=execution))
    PipelineCheckpointStore(tmp_path).create(record)
    assert isinstance(PipelineCheckpointStore(tmp_path).load("brief-1").implementation.execution.verification,
                      MalformedEvidence)


def test_retry_of_creation_returns_original_task_not_a_new_assignment(tmp_path: Path):
    store = PipelineCheckpointStore(tmp_path)
    original = store.create(_record())
    candidate = PipelineCheckpoint(original.brief, "task-OTHER", original.context_digest)
    assert store.create(candidate) == original
    with pytest.raises(CheckpointError, match="cannot be replaced"):
        store.create(replace(candidate, brief=replace(candidate.brief, mission="different request")))


def test_stale_writer_cannot_replace_a_new_revision(tmp_path: Path):
    store = PipelineCheckpointStore(tmp_path)
    original = store.create(_record())
    new = store.update(original, launches=4, elapsed_s=5.0)
    with pytest.raises(CheckpointError, match="stale"):
        PipelineCheckpointStore(tmp_path).update(original, launches=5)
    assert store.load("brief-1") == new
    assert len(list((tmp_path / "history/brief-1").glob("*.json"))) == 2


@pytest.mark.parametrize("changes", [{"attempt_ids": ("run-1",)}, {"launches": 2},
    {"rounds_started": 0}, {"implementation_attempts": 0}, {"task_id": "new"}])
def test_resume_cannot_forget_attempts_reset_bounds_or_reassign(tmp_path: Path, changes):
    store = PipelineCheckpointStore(tmp_path)
    original = store.create(_record())
    with pytest.raises(CheckpointError):
        store.update(original, **changes)
    assert store.load("brief-1") == original


@pytest.mark.parametrize("field,value", [("passed", 1), ("passed", "yes"), ("exit_code", False)])
def test_malformed_verification_is_never_laundered_by_serialization(tmp_path: Path, field, value):
    record = _record()
    execution = record.implementation.execution
    malformed = replace(execution.verification, **{field: value})
    record = replace(record, implementation=replace(record.implementation,
                     execution=replace(execution, verification=malformed)))
    with pytest.raises(CheckpointError, match="invalid VerificationResult"):
        PipelineCheckpointStore(tmp_path).create(record)
    assert not (tmp_path / "brief-1.json").exists()


@pytest.mark.parametrize("payload", ["{broken", '{"schema":1,"schema":2}',
    '{"schema":"gnosis.pipeline-checkpoint.v1","record":{"type":"os.system","fields":{}}}'])
def test_corrupt_or_unknown_state_is_not_treated_as_a_fresh_task(tmp_path: Path, payload):
    (tmp_path / "brief-1.json").write_text(payload)
    with pytest.raises(CheckpointError):
        PipelineCheckpointStore(tmp_path).load("brief-1")


def test_missing_selector_with_retained_history_cannot_start_fresh(tmp_path: Path):
    store = PipelineCheckpointStore(tmp_path)
    store.create(_record())
    (tmp_path / "brief-1.json").unlink()
    with pytest.raises(CheckpointError, match="selector missing"):
        store.load("brief-1")


def test_selector_edit_cannot_silently_replace_recorded_state(tmp_path: Path):
    store = PipelineCheckpointStore(tmp_path)
    store.create(_record())
    path = tmp_path / "brief-1.json"
    data = json.loads(path.read_text())
    data["record"]["fields"]["launches"] = 4
    path.write_text(json.dumps(data))
    with pytest.raises(CheckpointError):
        store.load("brief-1")


def test_crash_between_generation_and_selector_keeps_previous_complete_state(tmp_path: Path):
    from gnosis.kernel.atomic_io import atomic_write_text

    store = PipelineCheckpointStore(tmp_path)
    before = store.create(_record())

    def interrupted(path, data):
        if path == tmp_path / "brief-1.json":
            raise OSError("crash before selector")
        atomic_write_text(path, data)

    with (patch("gnosis.director.checkpoint.atomic_write_text", side_effect=interrupted),
          pytest.raises(OSError)):
        store.update(before, launches=4)
    assert PipelineCheckpointStore(tmp_path).load("brief-1") == before
    assert len(list((tmp_path / "history/brief-1").glob("*.json"))) == 2
    after = store.update(before, launches=4)
    assert after.revision == before.revision + 1


def test_killed_checkpoint_writer_releases_lock_and_preserves_original_work(tmp_path: Path):
    store = PipelineCheckpointStore(tmp_path)
    original = store.create(_record())
    code = """
import os
import sys
from pathlib import Path
import gnosis.director.checkpoint as module
store = module.PipelineCheckpointStore(Path(sys.argv[1]))
original = store.load('brief-1')
write = module.atomic_write_text
def killed(path, data):
    if path == store.path_for('brief-1'):
        os._exit(77)
    write(path, data)
module.atomic_write_text = killed
store.update(original, launches=4)
"""
    child = subprocess.run([sys.executable, "-c", code, str(tmp_path)],
                           cwd=Path(__file__).resolve().parents[1],
                           capture_output=True, timeout=20, check=False)
    assert child.returncode == 77, child.stderr.decode(errors="replace")
    restarted = PipelineCheckpointStore(tmp_path)
    assert restarted.load("brief-1") == original
    updated = restarted.update(original, launches=4)
    assert updated.task_id == original.task_id
    assert updated.attempt_ids == original.attempt_ids
    assert updated.convergence == original.convergence


def test_oversized_state_is_refused_before_json_parsing(tmp_path: Path):
    from gnosis.director.checkpoint import MAX_CHECKPOINT_BYTES

    (tmp_path / "brief-1.json").write_bytes(b" " * (MAX_CHECKPOINT_BYTES + 1))
    with pytest.raises(CheckpointError, match="byte bound"):
        PipelineCheckpointStore(tmp_path).load("brief-1")


def test_unknown_new_fields_are_not_silently_ignored(tmp_path: Path):
    store = PipelineCheckpointStore(tmp_path)
    store.create(_record())
    path = store.path_for("brief-1")
    data = json.loads(path.read_text())
    data["record"]["fields"]["trust_me_done"] = True
    path.write_text(json.dumps(data))
    with pytest.raises(CheckpointError, match="fields differ"):
        store.load("brief-1")
