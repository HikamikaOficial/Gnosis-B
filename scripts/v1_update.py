"""Stage a composed V1 release beside the active one without switching services.

Activation is a separate maintenance transaction. A staged directory alone is
never accepted by the existing self-verifying operator entry.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from stage2cb import OperationsBackend, OrchestrationError, Stage2CBConfig
from v1_installation import verify_persistent

from gnosis.kernel.atomic_io import atomic_write_bytes, atomic_write_text
from gnosis.kernel.file_lock import FileLock
from gnosis.provision.gnosis_deployment import (
    COMPOSED_RECORD_SCHEMA,
    ComposedRecord,
    composed_deployment_digest,
    composed_record_path,
    f17_publisher_files,
)
from gnosis.provision.operator_stack import (
    canonical_package_root,
    deploy_operator_stack,
    load_application_manifest,
    measure_application_tree,
    verify_application_tree,
    worker_bootstrap_files,
)
from gnosis.provision.provisioner import (
    WELL_KNOWN_ADMINISTRATORS,
    WELL_KNOWN_SYSTEM,
    Provisioner,
    ResolvedSids,
)
from gnosis.trust.publisher_service import ServiceConfig


def _digest(path: Path) -> str:
    if not path.is_file() or path.is_symlink() or path.is_junction() or path.stat().st_nlink != 1:
        raise OrchestrationError("Claude source must be an ordinary single-link file")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@dataclass(frozen=True)
class StagedUpdate:
    release_root: Path
    journal: Path
    application_digest: str
    staged_digest: str


def stage_update(current: Stage2CBConfig, candidate: Stage2CBConfig,
                 ops: OperationsBackend, *, source_root: Path, claude_binary: Path,
                 claude_digest: str, observe_current: Callable[[], str],
                 observe_fn: Any = None) -> StagedUpdate:
    """Require an intact current install, retain failed staging, never reset auth.

    The maintenance entry must establish protected configuration and source pins.
    This operation writes only a new release and its protected update journal.
    """
    if not ops.is_elevated():
        raise OrchestrationError("update staging requires elevated maintenance")
    if (current.owned_roots() != candidate.owned_roots()
            or any(getattr(current, key) != getattr(candidate, key) for key in
                   ("service_name", "pipe_name", "worker_username", "run_id", "residue_root"))):
        raise OrchestrationError("update cannot change resource ownership or account identity")
    if current.layout.release_id == candidate.layout.release_id:
        raise OrchestrationError("update requires a distinct release identifier")
    release = Path(candidate.layout.code_release_base)
    releases = Path(current.layout.code_release_base).parent.resolve()
    if release.resolve().parent != releases:
        raise OrchestrationError("candidate release escapes the existing releases directory")
    if not claude_binary.is_absolute() or _digest(claude_binary) != claude_digest:
        raise OrchestrationError("Claude source differs from approved digest")
    journal = Path(current.residue_record_dir()) / f"update-{candidate.layout.release_id}.json"
    with FileLock(journal.parent / "installation.lock", timeout_s=30):
        if release.exists() or journal.exists():
            raise OrchestrationError("candidate or journal already exists; inspect retained update")
        previous = verify_persistent(current, observe_effective=observe_current)
        service = ServiceConfig.load(Path(current.layout.config_path))
        sids = ResolvedSids(WELL_KNOWN_ADMINISTRATORS, WELL_KNOWN_SYSTEM,
            ops.resolve_sid(f"NT SERVICE\\{current.service_name}"),
            ops.resolve_sid(current.worker_username))
        if service.service_sid != sids.service or service.authorized_worker_sid != sids.worker:
            raise OrchestrationError("installed account identity differs from observed identity")
        record = {"schema": "gnosis.staged-update.v1", "status": "staging",
            "previous_release": current.layout.release_id,
            "candidate_release": candidate.layout.release_id,
            "previous_effective_digest": previous.effective_deployment_digest,
            "candidate_commit": candidate.source_commit, "candidate_tree": candidate.source_tree,
            "previous_configuration": asdict(current), "candidate_configuration": asdict(candidate),
            "claude_digest": claude_digest}
        atomic_write_text(journal, json.dumps(record, indent=2))
        try:
            provisioner = Provisioner(candidate.provision_config(), ops, candidate.runtime_src,
                f17_publisher_files(source_root), (), (), observe_fn=observe_fn,
                codex_runtime_src=candidate.codex_runtime_src,
                git_runtime_src=candidate.git_runtime_src,
                runtime_bootstrap_files=worker_bootstrap_files(source_root))
            provisioner.stage_release(candidate.layout, sids)
            destination = Path(candidate.layout.runtime_root) / "providers/claude/claude.exe"
            if destination.exists():
                raise OrchestrationError("candidate runtime already contains an unapproved Claude binary")
            ops.mkdir(str(destination.parent))
            ops.copyfile(str(claude_binary), str(destination))
            if _digest(destination) != claude_digest:
                raise OrchestrationError("staged Claude bytes differ from approved source")
            base_digest, _ = provisioner.observe_release(candidate.layout)
            app = deploy_operator_stack(source_root, canonical_package_root(candidate.layout),
                                        composed_record_path(candidate.layout))
            valid, problems = verify_application_tree(app.package_root, app.manifest)
            if not valid:
                raise OrchestrationError(f"staged application invalid: {problems}")
            application_digest = measure_application_tree(app.package_root, app.manifest)
            valid, reason = provisioner.verify_release(candidate.layout)
            if not valid:
                raise OrchestrationError(f"staged substrate invalid: {reason}")
            staged_digest, _ = provisioner.observe_release(candidate.layout)
            # Shared state and the active service have not changed. Prove that
            # staging did not silently invalidate the existing deployment.
            verify_persistent(current, observe_effective=observe_current)
            record.update(status="staged-not-active", base_digest=base_digest,
                application_digest=application_digest, staged_digest=staged_digest)
            atomic_write_text(journal, json.dumps(record, indent=2))
            return StagedUpdate(release, journal, application_digest, staged_digest)
        except BaseException as exc:
            record.update(status="staging-failed-retained", error_type=type(exc).__name__)
            atomic_write_text(journal, json.dumps(record, indent=2))
            raise


def activate_update(current: Stage2CBConfig, candidate: Stage2CBConfig,
                    ops: OperationsBackend, *, configuration_path: Path,
                    observe_current: Callable[[], str],
                    observe_candidate: Callable[[], str],
                    stop_service: Callable[[], None], start_service: Callable[[], None],
                    observe_fn: Any = None) -> None:
    """Activate only a verified staged release; restore the old release on error.

    stop_service must wait for STOPPED; start_service must wait for readiness and
    raise on failure. Both refer to the same existing service. Durable snapshots
    precede the switch so interruption leaves an inspectable recovery point.
    """
    if not ops.is_elevated():
        raise OrchestrationError("activation requires elevated maintenance")
    journal = Path(current.residue_record_dir()) / f"update-{candidate.layout.release_id}.json"
    if configuration_path.parent.resolve() != journal.parent.resolve():
        raise OrchestrationError("configuration is outside the protected maintenance directory")
    with FileLock(journal.parent / "installation.lock", timeout_s=30):
        record = json.loads(journal.read_text(encoding="utf-8"))
        if (record.get("schema") != "gnosis.staged-update.v1"
                or record.get("status") != "staged-not-active"
                or record.get("candidate_commit") != candidate.source_commit
                or record.get("candidate_tree") != candidate.source_tree
                or record.get("candidate_release") != candidate.layout.release_id
                or record.get("previous_release") != current.layout.release_id
                or record.get("previous_configuration") != asdict(current)
                or record.get("candidate_configuration") != asdict(candidate)
                or current.owned_roots() != candidate.owned_roots()
                or any(getattr(current, key) != getattr(candidate, key) for key in
                       ("service_name", "pipe_name", "worker_username", "run_id", "residue_root"))):
            raise OrchestrationError("candidate does not match staged update")
        previous = verify_persistent(current, observe_effective=observe_current)
        if previous.effective_deployment_digest != record["previous_effective_digest"]:
            raise OrchestrationError("active deployment changed since staging")
        service = ServiceConfig.load(Path(current.layout.config_path))
        sids = ResolvedSids(WELL_KNOWN_ADMINISTRATORS, WELL_KNOWN_SYSTEM,
            ops.resolve_sid(f"NT SERVICE\\{current.service_name}"),
            ops.resolve_sid(current.worker_username))
        if (service.service_sid != sids.service or service.authorized_worker_sid != sids.worker):
            raise OrchestrationError("active account identity changed")
        provisioner = Provisioner(candidate.provision_config(), ops, candidate.runtime_src,
            (), (), (), observe_fn=observe_fn)
        staged_digest, _ = provisioner.observe_release(candidate.layout)
        if staged_digest != record["staged_digest"]:
            raise OrchestrationError("staged release changed before activation")
        root = canonical_package_root(candidate.layout)
        manifest = load_application_manifest(root)
        measured = measure_application_tree(root, manifest)
        if measured != record["application_digest"]:
            raise OrchestrationError("staged application changed before activation")
        snapshots = [Path(current.layout.config_path), Path(current.layout.deployment_json),
                     composed_record_path(current.layout), configuration_path]
        backup = journal.with_suffix(".rollback")
        backup.mkdir(exist_ok=False)
        for index, path in enumerate(snapshots):
            atomic_write_bytes(backup / f"{index}.json", path.read_bytes())
        record.update(status="activating", rollback_directory=str(backup))
        atomic_write_text(journal, json.dumps(record, indent=2))
        try:
            stop_service()
            effective, _ = provisioner.activate_release(candidate.layout, sids)
            composed = ComposedRecord(COMPOSED_RECORD_SCHEMA, record["base_digest"], measured,
                effective, composed_deployment_digest(record["base_digest"], measured, effective),
                str(root), "operator_entry.py", "gnosis/director/deterministic_worker.py")
            atomic_write_text(composed_record_path(candidate.layout), json.dumps(composed.to_dict(), indent=2))
            verify_persistent(candidate, observe_effective=observe_candidate)
            start_service()
            atomic_write_text(configuration_path, json.dumps(asdict(candidate), indent=2))
            record.update(status="active", effective_digest=effective)
            atomic_write_text(journal, json.dumps(record, indent=2))
        except BaseException as exc:
            record.update(status="rolling-back", error_type=type(exc).__name__)
            atomic_write_text(journal, json.dumps(record, indent=2))
            try:
                stop_service()
                restored, _ = provisioner.activate_release(current.layout, sids)
                if restored != previous.effective_deployment_digest:
                    raise OrchestrationError("previous release drifted; service must remain stopped")
                for index, path in enumerate(snapshots):
                    atomic_write_bytes(path, (backup / f"{index}.json").read_bytes())
                verify_persistent(current, observe_effective=observe_current)
                start_service()
                record.update(status="rolled-back")
            except BaseException as rollback_error:
                record.update(status="recovery-required", rollback_error_type=type(rollback_error).__name__)
                atomic_write_text(journal, json.dumps(record, indent=2))
                raise OrchestrationError("update failed and rollback requires maintenance") from rollback_error
            atomic_write_text(journal, json.dumps(record, indent=2))
            raise
