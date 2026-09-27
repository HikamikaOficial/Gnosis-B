"""Persistent V1 installation orchestration; no implicit privileged entrypoint.

Consumes the existing provisioning and observation gates. This module performs
no provider request or login, and successful installation is not V1 acceptance.
"""
from __future__ import annotations

import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from stage2cb import (
    LiveCallBudget,
    OperationsBackend,
    OrchestrationError,
    ResidueStore,
    Stage2CBConfig,
    make_base_provision,
    preflight,
)
from v1_maintenance_security import verify_maintenance_directory
from v1_source import inspect_install_source

from gnosis.kernel.file_lock import FileLock
from gnosis.provision.codex_package import codex_package_entrypoint
from gnosis.provision.git_package import git_package_entrypoint
from gnosis.provision.gnosis_deployment import (
    ComposedDeployment,
    GnosisDeploymentProvisioner,
    composed_record_path,
    read_composed_record,
)
from gnosis.provision.operator_stack import (
    DeployedApplication,
    canonical_package_root,
    load_application_manifest,
)
from gnosis.provision.provisioner import (
    WELL_KNOWN_ADMINISTRATORS,
    WELL_KNOWN_SYSTEM,
    Provisioner,
    ResolvedSids,
)
from gnosis.trust.publisher_service import ServiceConfig


def install_pinned(config: Stage2CBConfig, ops: OperationsBackend, *,
                   observe_effective: Callable[[], str],
                   observe_fn: Any = None) -> ComposedDeployment:
    """Observe the executing checkout rather than accepting claimed provenance.

    The maintenance caller must approve the expected commit/tree in protected
    config. Clean, exact Git identity includes the trust source: f17_stable below
    means no divergence from that snapshot, not inherited production qualification.
    """
    repository = Path(__file__).resolve().parents[1]
    source = inspect_install_source(repository, expected_commit=config.source_commit,
                                    expected_tree=config.source_tree)
    verify_maintenance_directory(Path(config.residue_record_dir()))
    return install_persistent(config, ops, expected_head=config.source_commit,
        actual_head=source.commit, f17_stable=True, source_root=source.repository / "src",
        observe_effective=observe_effective, observe_fn=observe_fn)


def _verify_composed(config: Stage2CBConfig, *,
                      observe_effective: Callable[[], str]) -> ComposedDeployment:
    """Reconstruct from canonical paths and freshly verify a persisted install.

    The maintenance caller must establish that the configuration and journal
    location are protected. A stored digest alone is never fresh observation.
    This validates deployment integrity, not account login or provider readiness.
    """
    ownership = ResidueStore(config.residue_record_path(), config.run_id).load()
    expected = {("worker", config.worker_username), ("service", config.service_name),
                *(("root", root) for root in config.owned_roots())}
    if (ownership is None or ownership.run_id != config.run_id
            or ownership.status != "active"
            or {(r.kind, r.identity) for r in ownership.resources} != expected
            or len(ownership.resources) != len(expected)
            or not all(r.intended and r.acquired for r in ownership.resources)):
        raise OrchestrationError("persistent installation ownership is incomplete or mismatched")
    root = canonical_package_root(config.layout)
    record_path = composed_record_path(config.layout)
    record = read_composed_record(record_path)
    if (Path(record.package_root) != root
            or record.operator_entry_relpath != "operator_entry.py"
            or record.worker_image_relpath != "gnosis/director/deterministic_worker.py"):
        raise OrchestrationError("persistent installation record names unexpected paths")
    manifest = load_application_manifest(root)
    entry = root / "operator_entry.py"
    worker = root / "gnosis" / "director" / "deterministic_worker.py"
    comp = ComposedDeployment(config.layout, root, entry, worker,
        DeployedApplication(root, entry, worker, manifest), record.f17_deployment_digest,
        record.effective_deployment_digest, record.composed_deployment_digest, record_path,
        (str(Path(config.layout.runtime_executable)), "-I", "-B", str(entry)))
    GnosisDeploymentProvisioner.verify(comp, expect_effective=observe_effective())
    return comp


def verify_persistent(config: Stage2CBConfig, *,
                      observe_effective: Callable[[], str]) -> ComposedDeployment:
    """Verify both the assembled release and the Publisher's active expectation."""
    comp = _verify_composed(config, observe_effective=observe_effective)
    publisher = ServiceConfig.load(Path(config.layout.config_path))
    if publisher.expected_deployment_digest != comp.effective_deployment_digest:
        raise OrchestrationError("Publisher expectation differs from verified composed deployment")
    return comp


def finalize_existing(config: Stage2CBConfig, ops: OperationsBackend, *,
                      observe_effective: Callable[[], str],
                      observe_fn: Any = None) -> ComposedDeployment:
    """Repair only the known pre-assembly binding on an intact owned installation.

    Maintenance callers must stop the service before this operation and restart
    it only after success. No account, application, credential or record is
    replaced. An arbitrary mismatched expectation is refused, never adopted.
    """
    if not ops.is_elevated():
        raise OrchestrationError("finalization requires elevated maintenance")
    store = ResidueStore(config.residue_record_path(), config.run_id)
    with FileLock(store.path.parent / "installation.lock", timeout_s=30):
        comp = _verify_composed(config, observe_effective=observe_effective)
        publisher = ServiceConfig.load(Path(config.layout.config_path))
        sids = ResolvedSids(WELL_KNOWN_ADMINISTRATORS, WELL_KNOWN_SYSTEM,
            ops.resolve_sid(f"NT SERVICE\\{config.service_name}"),
            ops.resolve_sid(config.worker_username))
        if (publisher.service_name != config.service_name
                or publisher.pipe_name != config.pipe_name
                or publisher.service_sid != sids.service
                or publisher.authorized_worker_sid != sids.worker
                or publisher.trust_state_root != Path(config.layout.state_base)
                or publisher.evidence_root != Path(config.layout.bundles_root)
                or publisher.log_path != Path(config.layout.log_path)
                or publisher.expected_deployment_digest not in
                    (comp.f17_deployment_digest, comp.effective_deployment_digest)):
            raise OrchestrationError("existing Publisher configuration is not the known assembly binding")
        provisioner = Provisioner(config=config.provision_config(), ops=ops,
            runtime_src=config.runtime_src, publisher_files=(), bootstrap_files=(),
            toolchain_files=(), observe_fn=observe_fn)
        digest, _ = provisioner.activate_release(config.layout, sids)
        if digest != comp.effective_deployment_digest:
            raise OrchestrationError("deployment changed during existing-install finalization")
        return verify_persistent(config, observe_effective=observe_effective)


def install_persistent(config: Stage2CBConfig, ops: OperationsBackend, *,
                       expected_head: str, actual_head: str, f17_stable: bool,
                       source_root: Path, observe_effective: Callable[[], str],
                       observe_fn: Any = None) -> ComposedDeployment:
    """Install once, retaining the protected resource journal on success/failure.

    The maintenance caller supplies trusted configuration and observed source
    state, as in the existing qualification orchestrator. Existing resources or
    active recovery records are refused; recovery is an explicit separate action.
    The real backend must already have passed its authorization constructor.
    """
    if not config.codex_runtime_src:
        raise OrchestrationError("persistent V1 installation requires a native provider package")
    codex_package_entrypoint(Path(config.codex_runtime_src))
    if not config.git_runtime_src:
        raise OrchestrationError("persistent V1 installation requires a complete Git package")
    git_package_entrypoint(Path(config.git_runtime_src))
    store = ResidueStore(config.residue_record_path(), config.run_id)

    def check() -> None:
        result = preflight(config, ops, expected_head=expected_head,
            actual_head=actual_head, f17_stable=f17_stable,
            budget=LiveCallBudget(0), store=store)
        if not result.ok:
            raise OrchestrationError(f"installation preflight refused: {result.failures}")

    check()
    with FileLock(store.path.parent / "installation.lock", timeout_s=30):
        check()
        store.write_initial(config)
        # Never accept a fixed test password on this persistent route. Plaintext
        # is handed only to the existing account/DPAPI provisioning operation.
        provision, handle = make_base_provision(config, ops, observe_fn=observe_fn,
                                                worker_password=secrets.token_urlsafe(36))
        base = provision()
        store.mark_acquired({config.worker_username, config.service_name, *config.owned_roots()})
        composed = GnosisDeploymentProvisioner(source_root, base_provision=lambda: base,
            observe_effective=observe_effective).provision()
        # The base identity predates application assembly. Use the maintenance
        # activation path to observe the complete release and bind the Publisher
        # before starting it; never substitute a stored digest for observation.
        digest, _ = handle["provisioner"].activate_release(
            config.layout, handle["install"].sids)
        if digest != composed.effective_deployment_digest:
            raise OrchestrationError("deployment changed during application finalization")
        verify_persistent(config, observe_effective=observe_effective)
        ops.service_start(config.service_name)
        if not ops.pipe_ready(config.pipe_name, config.service_name):
            raise OrchestrationError("installed Publisher is not ready; retain journal for recovery")
        verified = verify_persistent(config, observe_effective=observe_effective)
        # Deliberately no success-path rollback: service and deployment remain.
        # The original qualification orchestrator retains its always-clean behavior.
        return verified
