"""Canonical composed Gnosis-B deployment (F-33 Stage 2C-PACK-R1).

ONE production-supported composed operation that CONSUMES the qualified F-17
`Provisioner` (trust plane + runtime, into the canonical package root) and then
adds the operator/application stack into that SAME `gnosis/` package via
`operator_stack.deploy_operator_stack` — so Stage-2C-B calls one API, not
probe-only glue of two deployers. It reimplements no F-17 provisioning and owns
no trust bytes; the trust tree is deployed and measured entirely by F-17.

Composed deployment identity binds the F-17 deployment digest and the application
tree digest (which already includes the measured operator entry). The canonical
launch spec is emitted here so the caller cannot omit `-I` isolation.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gnosis.provision.layout import DeploymentLayout
from gnosis.provision.operator_stack import (
    DeployedApplication,
    OperatorStackError,
    canonical_package_root,
    deploy_operator_stack,
    f17_provided_closure,
    verify_application_tree,
)

COMPOSED_IDENTITY_SCHEMA = "gnosis.composed_deployment.v1"


class GnosisDeploymentError(Exception):
    """The composed deployment failed / did not verify (fail closed)."""


@dataclass(frozen=True)
class BaseDeployment:
    """What the F-17 base provisioning produced. `rollback` is the F-17 uninstall
    (consumed, not reimplemented)."""

    layout: DeploymentLayout
    deployment_digest: str
    rollback: Callable[[], None]


@dataclass(frozen=True)
class ComposedDeployment:
    layout: DeploymentLayout
    package_root: Path
    operator_entry: Path
    worker_image: Path
    application: DeployedApplication
    f17_deployment_digest: str
    composed_deployment_digest: str
    launch_argv: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "package_root": str(self.package_root),
            "operator_entry": str(self.operator_entry),
            "worker_image": str(self.worker_image),
            "f17_deployment_digest": self.f17_deployment_digest,
            "application_tree_digest": self.application.manifest.tree_digest,
            "composed_deployment_digest": self.composed_deployment_digest,
            "launch_argv": list(self.launch_argv),
        }


def composed_deployment_digest(f17_deployment_digest: str,
                               application_tree_digest: str) -> str:
    """One deterministic digest binding both deployment surfaces (domain-separated;
    no F-17 identity semantics changed — this is an additive composition digest)."""
    canonical = json.dumps({
        "schema": COMPOSED_IDENTITY_SCHEMA,
        "f17_deployment_digest": f17_deployment_digest,
        "application_tree_digest": application_tree_digest,
    }, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def f17_publisher_files(source_root: Path) -> list[tuple[str, str]]:
    """The trust-plane closure to hand the F-17 Provisioner as `publisher_files`
    so the ONE authoritative trust tree contains every trust module the Director
    needs. `(abs_src, rel_under_package_root)` pairs."""
    return sorted(
        (str(path), path.relative_to(source_root).as_posix())
        for path in f17_provided_closure(source_root).values())


class GnosisDeploymentProvisioner:
    """The one canonical composed provisioner. `base_provision` runs/consumes the
    F-17 Provisioner (privileged in production; a controlled fixture in tests)."""

    def __init__(self, source_root: Path, *,
                 base_provision: Callable[[], BaseDeployment]) -> None:
        self._source_root = Path(source_root)
        self._base_provision = base_provision

    def provision(self) -> ComposedDeployment:
        base = self._base_provision()  # F-17: runtime + trust plane + service/account
        package_root = canonical_package_root(base.layout)
        try:
            app = deploy_operator_stack(self._source_root, package_root)
        except OperatorStackError as exc:
            # App deployment failed AFTER base provisioning → fail closed + roll back
            # the F-17 base (never return a half-composed deployment).
            try:
                base.rollback()
            except Exception as rbexc:  # noqa: BLE001
                raise GnosisDeploymentError(
                    f"application deploy failed ({exc}); base rollback ALSO failed "
                    f"({rbexc}); deployment is in an unknown state") from exc
            raise GnosisDeploymentError(
                f"application deploy failed; base rolled back: {exc}") from exc
        digest = composed_deployment_digest(base.deployment_digest,
                                            app.manifest.tree_digest)
        launch_argv = (str(Path(base.layout.runtime_executable)), "-I", "-B",
                       str(app.entry_path))
        return ComposedDeployment(
            layout=base.layout, package_root=package_root,
            operator_entry=app.entry_path, worker_image=app.worker_image,
            application=app, f17_deployment_digest=base.deployment_digest,
            composed_deployment_digest=digest, launch_argv=launch_argv)

    @staticmethod
    def verify(comp: ComposedDeployment) -> None:
        """Fail closed unless the deployed application matches its manifest AND the
        composed identity re-derives. Called at startup before operator work."""
        ok, problems = verify_application_tree(comp.package_root,
                                               comp.application.manifest)
        if not ok:
            raise GnosisDeploymentError(
                f"application tree does not match its manifest: {problems}")
        redigest = composed_deployment_digest(comp.f17_deployment_digest,
                                              comp.application.manifest.tree_digest)
        if redigest != comp.composed_deployment_digest:
            raise GnosisDeploymentError("composed deployment identity mismatch")
        if "-I" not in comp.launch_argv:
            raise GnosisDeploymentError("canonical launch is not isolated (-I missing)")

    @staticmethod
    def cleanup(comp: ComposedDeployment) -> None:
        """Remove the application-provided files (leaving the F-17 base to its own
        rollback). Best-effort, used on teardown."""
        for f in comp.application.manifest.files:
            target = comp.package_root / f.relpath
            if f.relpath.startswith("gnosis/trust/"):
                continue  # never touch F-17-owned trust
            if target.is_file():
                target.unlink()
        shutil.rmtree(comp.package_root / "gnosis" / "director", ignore_errors=True)
