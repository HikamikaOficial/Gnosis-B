"""Bind a real reviewed task to F-17's existing observed evidence capture.

Linked worktrees are not F-17 capture topologies. A separate clone preserves the
reviewed HEAD and file bytes, then verification is re-run under the existing
locks/observer. CLEAN comes only from that mechanism, never from this module.
"""
from __future__ import annotations

import json
import shlex
import stat
from pathlib import Path

from gnosis.contracts.director_brief import DirectorBrief
from gnosis.contracts.engineer_report import ReportStatus
from gnosis.director.pipeline import PipelineOutcome, converged_on_valid_evidence
from gnosis.director.publication import GitTreeEvidence, PublicationError
from gnosis.kernel.canonical import hash_canonical
from gnosis.kernel.convergence import ReviewVerdict
from gnosis.kernel.evidence_capture import CheckCommand, ChecksVerdict, run_capture
from gnosis.kernel.subject import SubjectUnavailable, copy_subject, observe_subject
from gnosis.kernel.verification import CommandVerifier, Verifier
from gnosis.trust.bundle_verify import verify_bundle, write_bundle_manifest
from gnosis.trust.launch_spec import LaunchSpec

_MAX_ARTIFACT_BYTES = 16 * 1024**2


def _copy_artifact(source: Path, target: Path) -> None:
    info = source.lstat()
    if (not stat.S_ISREG(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
            or info.st_size > _MAX_ARTIFACT_BYTES):
        raise PublicationError("proof artifact is not a bounded regular file")
    with source.open("rb") as handle:
        data = handle.read(_MAX_ARTIFACT_BYTES + 1)
    if len(data) > _MAX_ARTIFACT_BYTES:
        raise PublicationError("proof artifact grew beyond its limit")
    after = source.lstat()
    if (len(data) != info.st_size or info.st_mtime_ns != after.st_mtime_ns
            or info.st_ino != after.st_ino):
        raise PublicationError("proof artifact changed during capture")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def capture_task_proof(*, bundle_dir: Path, source: Path, brief: DirectorBrief,
                       work: PipelineOutcome, run_id: str, spec: LaunchSpec,
                       verifier: Verifier, convergence_dir: Path) -> GitTreeEvidence:
    """Create a fresh proof packet or fail closed, retaining failed evidence.

    This proves the reviewed filesystem content, not that it was merged into the
    base branch. The source worktree and its history remain available for recovery.
    """
    convergence = work.convergence
    if (work.status is not ReportStatus.COMPLETED or convergence is None
            or not converged_on_valid_evidence(convergence)):
        raise PublicationError("task has no successful verification/convergence")
    final = convergence.rounds[-1]
    subject = final.subject
    if (not final.evidence_ok or final.review is None
            or final.review.verdict is not ReviewVerdict.PASS or final.blocking
            or subject is None or final.fingerprint != subject.digest()):
        raise PublicationError("task has no byte-bound passing independent review")
    if work.brief_id != brief.brief_id or work.report.task_id != work.task_id:
        raise PublicationError("proof task/brief attribution mismatch")
    implementation = work.implementation
    if implementation is None or not implementation.run_ids:
        raise PublicationError("proof has no original implementation attempt")
    final_run_id = implementation.run_ids[-1]
    final_result = implementation.execution_result
    if convergence.rework_attempts:
        last = convergence.rework_attempts[-1]
        if any(a.task_id != work.task_id or a.stage != "convergence_fix"
               for a in convergence.rework_attempts):
            raise PublicationError("proof correction belongs to a different task/stage")
        final_run_id, final_result = last.run_id, last.result
    if (run_id != final_run_id or work.report.run_id != final_run_id
            or final_result is None or not final_result.succeeded
            or spec.run_id != run_id or Path(spec.cwd).resolve() != source.resolve()):
        raise PublicationError("proof subject differs from the recorded Worker launch")
    if not isinstance(verifier, CommandVerifier):
        raise PublicationError("publication requires a reproducible command verifier")
    timeout: object = verifier.timeout_s
    if not isinstance(timeout, int | float):
        raise PublicationError("publication requires a finite verifier deadline")
    if bundle_dir.exists():
        raise PublicationError("proof bundle already exists; refusing overwrite")
    try:
        argv = tuple(shlex.split(verifier.command) if isinstance(verifier.command, str)
                     else verifier.command)
        if not argv:
            raise PublicationError("publication requires a nonempty verifier command")
        command = CheckCommand("verification", argv, timeout_s=timeout)
        snapshot = copy_subject(source, bundle_dir.parent / f".{bundle_dir.name}-subject", subject)
        bundle_dir.mkdir(parents=True, exist_ok=False)
        # Raw output is forensic data. It cannot set any authority-bearing field.
        _copy_artifact(Path(final_result.stdout_path), bundle_dir / "raw" / "worker.stdout")
        _copy_artifact(Path(final_result.stderr_path), bundle_dir / "raw" / "worker.stderr")
        if implementation.execution_result is not None:
            _copy_artifact(Path(implementation.execution_result.stdout_path),
                           bundle_dir / "raw" / "implementation.stdout")
            _copy_artifact(Path(implementation.execution_result.stderr_path),
                           bundle_dir / "raw" / "implementation.stderr")
        for attempt in convergence.rework_attempts:
            if attempt.result is not None:
                _copy_artifact(Path(attempt.result.stdout_path),
                               bundle_dir / "raw" / f"{attempt.run_id}.stdout")
                _copy_artifact(Path(attempt.result.stderr_path),
                               bundle_dir / "raw" / f"{attempt.run_id}.stderr")
        if not convergence_dir.is_dir():
            raise PublicationError("raw convergence evidence is absent")
        artifacts = sorted(convergence_dir.iterdir())
        if len(artifacts) > 1000:
            raise PublicationError("too many convergence artifacts")
        for item in artifacts:
            _copy_artifact(item, bundle_dir / "raw" / "convergence" / item.name)
        if not artifacts:
            raise PublicationError("raw convergence evidence is empty")
        capture = run_capture(snapshot, [command], bundle_dir)
        if (not capture.evidence_valid or capture.checks_verdict is not ChecksVerdict.ALL_CLEAN
                or capture.exit_code != 0):
            raise PublicationError(
                f"proof capture refused: boundary={capture.boundary.verdict.value}; "
                f"checks={capture.checks_verdict.value}")
        # Compare the hashes read THROUGH the lock handles to the bytes reviewed.
        # An endpoint comparison alone is never substituted for this check.
        manifest = json.loads((bundle_dir / "input-manifest.json").read_text(encoding="utf-8"))
        inputs = manifest.get("inputs")
        digest = capture.boundary.protection.get("content_digest")
        if (inputs != dict(subject.files) or digest != hash_canonical(list(subject.files))
                or capture.binding.post.fingerprint.get("head_sha") != subject.head_sha
                or observe_subject(snapshot) != subject or observe_subject(source) != subject):
            raise PublicationError("locked capture no longer matches the reviewed subject")
        proof = {"schema": "gnosis.task-proof.v1", "task_id": work.task_id,
                 "run_id": run_id, "brief": brief.to_dict(), "source": str(source),
                 "proof_copy": str(snapshot), "subject": subject.to_dict(),
                 "subject_digest": subject.digest(), "convergence": convergence.to_dict(),
                 "report": work.report.to_dict(), "work": work.to_dict(),
                 "verifier": {"name": verifier.name, "argv": list(argv),
                              "timeout_s": verifier.timeout_s},
                 "capture_content_digest": digest,
                 "scope": "reviewed task content; base-branch integration is separate"}
        packet = json.dumps(proof, indent=2, sort_keys=True).encode("utf-8")
        if len(packet) > _MAX_ARTIFACT_BYTES:
            raise PublicationError("proof packet exceeds its size limit")
        (bundle_dir / "PROOF.json").write_bytes(packet)
        write_bundle_manifest(bundle_dir)
        if not verify_bundle(bundle_dir).verified:
            raise PublicationError("completed proof packet failed its integrity check")
        return GitTreeEvidence(subject.head_sha, str(digest))
    except (OSError, ValueError, SubjectUnavailable) as exc:
        raise PublicationError(f"task proof could not be captured: {exc}") from exc
