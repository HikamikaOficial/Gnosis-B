"""Director-owned publication checkpoints inside the protected trust-state root.

The Worker cannot write this root in a qualified deployment. A checkpoint saves
the already observed launch and the digest of the finished proof, before the
Publisher is contacted. Recovery reuses the existing publication gates; it does
not synthesize a new launch or treat an ANCHORED status file as an anchor.
"""
from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from gnosis.contracts.director_brief import DirectorBrief
from gnosis.director.publication import GitTreeEvidence, PublicationError, PublicationInputs
from gnosis.kernel.atomic_io import atomic_write_text
from gnosis.kernel.execution_scope import ExecutionScope
from gnosis.kernel.file_lock import FileLock, lock_path_for
from gnosis.kernel.subject import SubjectUnavailable, observe_subject
from gnosis.kernel.verification import CommandVerifier, Verifier
from gnosis.trust.bundle_verify import verify_bundle
from gnosis.trust.deployment import TrustPlaneDeploymentIdentity
from gnosis.trust.launch import AuthorityUnavailable
from gnosis.trust.launch_spec import LaunchSpec
from gnosis.trust.run_identity import is_storable_run_id
from gnosis.trust.worker_launcher import LaunchedWorkerIdentity

_MAX_BYTES = 16 * 1024**2


def _read(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        raw = handle.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise PublicationError("publication checkpoint exceeds its byte bound")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise PublicationError("publication checkpoint is not an object")
    return data


class PublicationCheckpointStore:
    def __init__(self, trust_state_root: Path, evidence_root: Path,
                 scope: ExecutionScope | None = None) -> None:
        self.root = trust_state_root / "director-publication"
        self.evidence_root = evidence_root
        self.scope = scope

    def path_for(self, brief_id: str) -> Path:
        if not is_storable_run_id(brief_id):
            raise PublicationError("invalid brief identifier for publication checkpoint")
        return self.root / f"{brief_id}.json"

    def save(self, brief: DirectorBrief, inputs: PublicationInputs) -> None:
        bundle = self.evidence_root / inputs.run_id
        verified = verify_bundle(bundle)
        if not verified.verified or verified.bundle_digest is None:
            raise PublicationError("cannot checkpoint an unverified proof bundle")
        payload = {"schema": "gnosis.director-publication.v1", "brief": brief.to_dict(),
                   "task_id": inputs.task_id, "run_id": inputs.run_id,
                   "repository_id": inputs.repository_id, "epoch": inputs.epoch,
                   "exit_code": inputs.exit_code, "deployment_digest": inputs.deployment.digest(),
                   "bundle_path": str(bundle.resolve()), "bundle_digest": verified.bundle_digest,
                   "launched": asdict(inputs.launched), "spec": inputs.spec.to_dict(),
                   "tree": asdict(inputs.tree)}
        raw = json.dumps(payload, indent=2, sort_keys=True)
        if len(raw.encode("utf-8")) > _MAX_BYTES:
            raise PublicationError("publication checkpoint exceeds its byte bound")
        path = self.path_for(brief.brief_id)
        self.root.mkdir(parents=True, exist_ok=True)
        with FileLock(lock_path_for(path)):
            def commit() -> None:
                if path.exists():
                    if _read(path) != json.loads(raw):
                        raise PublicationError("existing publication checkpoint cannot be replaced")
                else:
                    atomic_write_text(path, raw)
            if self.scope is not None:
                self.scope.commit(commit)
            else:
                commit()

    def load(self, brief: DirectorBrief, *, deployment: TrustPlaneDeploymentIdentity,
             repository_id: str, epoch: int, source_for: Callable[[str], Path],
             verifier: Verifier) -> PublicationInputs | None:
        """Validate a prior checkpoint and the current subject before reuse.

        The external digest lives under the protected root, outside the proof.
        Re-hashing a modified bundle cannot silently replace the original proof.
        """
        path = self.path_for(brief.brief_id)
        if not path.exists():
            return None
        try:
            data = _read(path)
            if (data.get("schema") != "gnosis.director-publication.v1"
                    or data.get("brief") != brief.to_dict()
                    or data.get("deployment_digest") != deployment.digest()
                    or data.get("repository_id") != repository_id
                    or type(data.get("epoch")) is not int or data["epoch"] != epoch
                    or type(data.get("exit_code")) is not int or data["exit_code"] != 0
                    or not is_storable_run_id(data.get("run_id"))
                    or not is_storable_run_id(data.get("task_id"))):
                raise PublicationError("publication checkpoint identity/configuration mismatch")
            bundle = self.evidence_root / data["run_id"]
            if str(bundle.resolve()) != data["bundle_path"]:
                raise PublicationError("publication checkpoint bundle path mismatch")
            digest = data["bundle_digest"]
            if not isinstance(digest, str) or not verify_bundle(bundle, digest).verified:
                raise PublicationError("publication checkpoint proof digest mismatch")
            packet = _read(bundle / "PROOF.json")
            source = source_for(data["task_id"])
            subject = observe_subject(source)
            spec = LaunchSpec.from_dict(data["spec"])
            if (packet.get("schema") != "gnosis.task-proof.v1"
                    or packet.get("task_id") != data["task_id"]
                    or packet.get("run_id") != data["run_id"]
                    or packet.get("brief") != brief.to_dict()
                    or packet.get("subject") != subject.to_dict()
                    or packet.get("subject_digest") != subject.digest()
                    or Path(packet["source"]).resolve() != source.resolve()
                    or Path(spec.cwd).resolve() != source.resolve()
                    or spec.run_id != data["run_id"]
                    or data["tree"]["head_sha"] != subject.head_sha
                    or data["tree"]["tree_identity"] != packet["capture_content_digest"]):
                raise PublicationError("publication checkpoint no longer matches reviewed work")
            if not isinstance(verifier, CommandVerifier):
                raise PublicationError("publication recovery requires the same command verifier")
            # The proof already normalized argv when it captured the check.
            argv = shlex.split(verifier.command) if isinstance(verifier.command, str) else list(verifier.command)
            if packet["verifier"] != {"name": verifier.name, "argv": argv,
                                      "timeout_s": verifier.timeout_s}:
                raise PublicationError("publication checkpoint verifier changed")
            launched_data = dict(data["launched"])
            launched_data["dangerous_privileges"] = tuple(launched_data["dangerous_privileges"])
            launched = LaunchedWorkerIdentity(**launched_data)
            if (launched.is_administrator is not False or launched.dangerous_privileges
                    or launched.contained_in_job is not True):
                raise PublicationError("publication checkpoint has no qualified Worker launch")
            return PublicationInputs(
                task_id=data["task_id"], run_id=data["run_id"], repository_id=repository_id,
                epoch=epoch, exit_code=0, launched=launched, spec=spec,
                deployment=deployment, tree=GitTreeEvidence(**data["tree"]))
        except (OSError, ValueError, KeyError, TypeError, AuthorityUnavailable,
                SubjectUnavailable) as exc:
            raise PublicationError(f"publication checkpoint could not be recovered: {exc}") from exc
