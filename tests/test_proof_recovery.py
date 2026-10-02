from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trust_fixtures as tf
from test_task_proof import _inputs

from gnosis.director.checkpoint import PipelineCheckpoint, PipelineCheckpointStore, TrustedAttempt
from gnosis.director.composition import ProductionComposition, PublicationCompositionInputs
from gnosis.director.publication import PublicationError
from gnosis.trust.bundle_verify import write_bundle_manifest


def _composition(root):
    inputs = _inputs(root)
    work = inputs["work"]
    checkpoints = PipelineCheckpointStore(root / "protected")
    checkpoints.create(PipelineCheckpoint(inputs["brief"], work.task_id, "a" * 64,
        implementation=work.schedule, convergence=work.convergence,
        subject=work.convergence.rounds[-1].subject, attempt_ids=(inputs["run_id"],),
        trusted_attempt=TrustedAttempt(inputs["spec"], tf.launched())))
    # The composition's source and convergence paths are real files. Worker and
    # publisher are unused: these tests concern the post-review crash boundary.
    outbox = root / "outbox"
    outbox.mkdir()
    inputs["convergence_dir"].rename(outbox / f"{work.task_id}-convergence")
    pipeline = SimpleNamespace(checkpoints=checkpoints, checkpoint_context="a" * 64,
        verifier=inputs["verifier"], _exec_root=lambda _: inputs["source"],
        inbox=SimpleNamespace(layout=SimpleNamespace(outbox=outbox)))
    publication = PublicationCompositionInputs(root / "protected", root / "evidence",
        tf.v2_deployment(), "repository", "unused")
    composition = ProductionComposition(pipeline, Mock(), publication, inputs["source"], Mock())
    return composition, inputs


def _capture(composition, inputs):
    return composition._capture_proof(inputs["work"], inputs["brief"], inputs["run_id"], inputs["spec"])


def test_failed_capture_is_bounded_across_fresh_compositions_and_keeps_artifacts(tmp_path):
    composition, inputs = _composition(tmp_path)
    calls = []
    def fail(**kwargs):
        path = kwargs["bundle_dir"]
        path.mkdir(parents=True)
        (path / "failure.txt").write_text("retained capture failure")
        calls.append(path)
        raise PublicationError("capture unavailable")
    with patch("gnosis.director.composition.capture_task_proof", side_effect=fail):
        for _ in range(3):
            with pytest.raises(PublicationError, match="capture unavailable"):
                _capture(composition, inputs)
            composition.pipeline.checkpoints = PipelineCheckpointStore(tmp_path / "protected")
        with pytest.raises(PublicationError, match="budget exhausted"):
            _capture(composition, inputs)
    assert len(set(calls)) == 3
    assert all((path / "failure.txt").read_text() == "retained capture failure" for path in calls)
    assert not inputs["bundle_dir"].exists()


def test_reservation_failure_prevents_capture(tmp_path):
    composition, inputs = _composition(tmp_path)
    with (patch.object(composition.pipeline.checkpoints, "update", side_effect=OSError("disk full")),
          patch("gnosis.director.composition.capture_task_proof") as capture,
          pytest.raises(OSError, match="disk full")):
        _capture(composition, inputs)
    capture.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="real Windows capture")
def test_staged_proof_cannot_be_resealed_after_its_protected_receipt(tmp_path):
    composition, inputs = _composition(tmp_path)
    original_update = composition.pipeline.checkpoints.update
    def killed(prior, **changes):
        result = original_update(prior, **changes)
        if changes.get("proof") is not None:
            raise SystemExit("process died after receipt")
        return result
    with (patch.object(composition.pipeline.checkpoints, "update", side_effect=killed),
          pytest.raises(SystemExit)):
        _capture(composition, inputs)
    record = composition.pipeline.checkpoints.load(inputs["brief"].brief_id)
    assert record.proof is not None
    stage = inputs["bundle_dir"].parent / f".{inputs['run_id']}-proof-1"
    (stage / "raw" / "worker.stdout").write_text("replaced")
    write_bundle_manifest(stage)
    with (patch("gnosis.director.composition.capture_task_proof") as capture,
          pytest.raises(PublicationError, match="digest changed")):
        _capture(composition, inputs)
    capture.assert_not_called()
    assert not inputs["bundle_dir"].exists()
