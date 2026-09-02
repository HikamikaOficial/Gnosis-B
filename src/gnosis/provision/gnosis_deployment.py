"""Canonical composed Gnosis-B deployment (F-33 Stage 2C-PACK-R1 / R2).

ONE production-supported composed operation that CONSUMES the qualified F-17
`Provisioner` (trust plane + runtime, into the canonical package root) and then
adds the operator/application stack into that SAME `gnosis/` package via
`operator_stack.deploy_operator_stack` — so Stage-2C-B calls one API, not
probe-only glue of two deployers. It reimplements no F-17 provisioning and owns
no trust bytes; the trust tree is deployed and measured entirely by F-17.

R2 — MANDATORY COMPOSED-IDENTITY ENFORCEMENT. The composed deployment identity
(F-17 deployment digest + application tree digest) is no longer merely computed
and optionally checkable; it is enforced at three points that a production caller
cannot bypass:

  * PROVISION TIME  — `provision()` deploys, measures, verifies, atomically writes
    a TRUSTED composed-deployment record, re-verifies the complete deployment and
    only THEN returns a usable result. A failure at any step fails closed and
    rolls the F-17 base back; no valid-looking record is left pointing at an
    incomplete deployment.
  * PRE-LAUNCH      — `canonical_launch()` is the ONE supported production launch
    operation. It reads the trusted record, re-observes the F-17 deployment
    identity, re-measures the application tree, recomputes the composed digest and
    compares it against the trusted expected digest, failing closed on any
    mismatch, and only then executes the isolated `-I -B` launch. It never returns
    an unchecked argv.
  * STARTUP         — the measured `operator_entry.py` self-verifies against the
    trusted record before importing the application package (defence in depth).

The TRUSTED RECORD lives in the F-17 STATE base (ProgramData; protected,
inheritance-stripped, worker-denied by the Stage-8 ACL matrix), OUTSIDE the
application tree it authenticates. Its authority is the deployment-authority
ownership of that location, not any self-hash: `APPLICATION.json` living inside
the measured tree can never be the root of trust, because a coherent tamper of
both the application bytes and the local manifest is internally consistent.

No F-17 code is modified. `layout.py` is not modified: the record path is derived
from the layout's existing public `state_base`. F-17 identity semantics
(RunIdentity, deployment digest format, Anchor V2, PublicationState, Publisher
authorisation) are unchanged; the composed identity is an ADDITIVE gate. F-17
Anchor V2 does NOT newly claim to bind the F-33 composed deployment digest.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from gnosis.provision.layout import DeploymentLayout
from gnosis.provision.operator_stack import (
    DeployedApplication,
    OperatorStackError,
    canonical_package_root,
    deploy_operator_stack,
    f17_provided_closure,
    load_application_manifest,
    measure_application_tree,
    verify_application_tree,
)

# R3D: v2 introduces the effective (post-application) whole-root deployment
# identity as a first-class operand. v1 records/digests are NOT auto-upgraded — a
# v1 record fails closed under the new production path (no silent migration).
COMPOSED_IDENTITY_SCHEMA = "gnosis.composed_deployment.v2"
COMPOSED_RECORD_SCHEMA = "gnosis.composed_record.v2"
_COMPOSED_RECORD_NAME = "GNOSIS_COMPOSED.json"
_WORKER_IMAGE_REL = "gnosis/director/deterministic_worker.py"
_MAX_RECORD_BYTES = 65_536


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
    effective_deployment_digest: str
    composed_deployment_digest: str
    composed_record_path: Path
    launch_argv: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "package_root": str(self.package_root),
            "operator_entry": str(self.operator_entry),
            "worker_image": str(self.worker_image),
            "f17_deployment_digest": self.f17_deployment_digest,
            "application_tree_digest": self.application.manifest.tree_digest,
            "effective_deployment_digest": self.effective_deployment_digest,
            "composed_deployment_digest": self.composed_deployment_digest,
            "composed_record_path": str(self.composed_record_path),
            "launch_argv": list(self.launch_argv),
        }


def composed_deployment_digest(f17_deployment_digest: str,
                               application_tree_digest: str,
                               effective_deployment_digest: str) -> str:
    """One deterministic digest binding ALL THREE deployment identities
    (domain-separated by `COMPOSED_IDENTITY_SCHEMA`): the immutable base F-17
    provenance, the closed-world application identity, and the effective whole-root
    identity of the FINAL executable one-tree. No F-17 identity semantics changed —
    `f17_deployment_digest` keeps its historical meaning as base provenance; the
    effective identity is the additive R3D operand. A record that omits or mismatches
    any operand cannot reproduce this digest (fail closed)."""
    canonical = json.dumps({
        "schema": COMPOSED_IDENTITY_SCHEMA,
        "f17_deployment_digest": f17_deployment_digest,
        "application_tree_digest": application_tree_digest,
        "effective_deployment_digest": effective_deployment_digest,
    }, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def composed_record_path(layout: DeploymentLayout) -> Path:
    """The trusted composed-record location: the F-17 STATE base (deployment-
    authority owned, worker-denied), OUTSIDE the application tree it authenticates.
    Derived from the layout's existing public `state_base` (layout.py unchanged)."""
    return Path(layout.state_base) / _COMPOSED_RECORD_NAME


def f17_publisher_files(source_root: Path) -> list[tuple[str, str]]:
    """The trust-plane closure to hand the F-17 Provisioner as `publisher_files`
    so the ONE authoritative trust tree contains every trust module the Director
    needs. `(abs_src, rel_under_package_root)` pairs."""
    return sorted(
        (str(path), path.relative_to(source_root).as_posix())
        for path in f17_provided_closure(source_root).values())


@dataclass(frozen=True)
class ComposedRecord:
    schema: str
    f17_deployment_digest: str          # immutable base F-17 provenance (pre-app)
    application_tree_digest: str        # closed-world F-33 application identity
    effective_deployment_digest: str    # R3D: final whole-root identity (post-app)
    composed_deployment_digest: str     # binds base + application + effective
    package_root: str
    operator_entry_relpath: str
    worker_image_relpath: str

    def to_dict(self) -> dict[str, str]:
        return {
            "schema": self.schema,
            "f17_deployment_digest": self.f17_deployment_digest,
            "application_tree_digest": self.application_tree_digest,
            "effective_deployment_digest": self.effective_deployment_digest,
            "composed_deployment_digest": self.composed_deployment_digest,
            "package_root": self.package_root,
            "operator_entry_relpath": self.operator_entry_relpath,
            "worker_image_relpath": self.worker_image_relpath,
        }


_RECORD_KEYS = frozenset({
    "schema", "f17_deployment_digest", "application_tree_digest",
    "effective_deployment_digest", "composed_deployment_digest", "package_root",
    "operator_entry_relpath", "worker_image_relpath",
})


def _is_hex64(s: object) -> bool:
    return isinstance(s, str) and len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def _atomic_write_json(path: Path, obj: dict[str, str]) -> None:
    """Transactional write: temp file in the same directory, flush + fsync, then
    atomic replace. A partial/truncated record can never be observed as valid."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, indent=2, sort_keys=True).encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".gnosis_composed_",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_composed_record(path: Path) -> ComposedRecord:
    """Fail-closed reader for the trusted composed record (schema, exact keys, no
    duplicate keys, 64-hex digests, bounded size). No self-signature is claimed —
    the record's authority is its deployment-authority-owned location."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise GnosisDeploymentError(f"cannot read composed record {path}: {exc}") from exc
    if len(raw) > _MAX_RECORD_BYTES:
        raise GnosisDeploymentError(f"composed record too large: {path}")

    def _no_dupes(pairs: list[tuple[str, object]]) -> dict[str, object]:
        seen: dict[str, object] = {}
        for k, v in pairs:
            if k in seen:
                raise GnosisDeploymentError(f"duplicate key in composed record: {k}")
            seen[k] = v
        return seen

    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_dupes)
    except GnosisDeploymentError:
        raise
    except Exception as exc:
        raise GnosisDeploymentError(f"malformed composed record {path}: {exc}") from exc
    if not isinstance(data, dict) or set(data.keys()) != set(_RECORD_KEYS):
        raise GnosisDeploymentError("composed record has unexpected key set")
    if data["schema"] != COMPOSED_RECORD_SCHEMA:
        raise GnosisDeploymentError(f"unexpected composed record schema {data['schema']!r}")
    for k in ("f17_deployment_digest", "application_tree_digest",
              "effective_deployment_digest", "composed_deployment_digest"):
        if not _is_hex64(data[k]):
            raise GnosisDeploymentError(f"composed record {k} is not a 64-hex digest")
    for k in ("package_root", "operator_entry_relpath", "worker_image_relpath"):
        if not isinstance(data[k], str) or not data[k]:
            raise GnosisDeploymentError(f"composed record {k} is not a non-empty string")
    # Internal consistency: the record's own composed digest must derive from its
    # own THREE identities (base + application + effective). A record that lies
    # about its composition — or mixes operands from different deployments — cannot
    # reproduce the binding and fails closed.
    if composed_deployment_digest(data["f17_deployment_digest"],
                                  data["application_tree_digest"],
                                  data["effective_deployment_digest"]) != data[
            "composed_deployment_digest"]:
        raise GnosisDeploymentError("composed record composed digest is inconsistent")
    return ComposedRecord(**data)


class GnosisDeploymentProvisioner:
    """The one canonical composed provisioner. `base_provision` runs/consumes the
    F-17 Provisioner (privileged in production; a controlled fixture in tests)."""

    def __init__(self, source_root: Path, *,
                 base_provision: Callable[[], BaseDeployment],
                 observe_effective: Callable[[], str]) -> None:
        self._source_root = Path(source_root)
        self._base_provision = base_provision
        # R3D: the canonical whole-root observer, called AFTER the application tree
        # is deployed, to measure the effective (final executable) deployment
        # identity. Production wires it to observe_deployment(...).digest() — the
        # SAME observer canonical_launch re-runs before spawn.
        self._observe_effective = observe_effective

    def provision(self) -> ComposedDeployment:
        base = self._base_provision()  # F-17: runtime + trust plane + service/account
        package_root = canonical_package_root(base.layout)
        record_path = composed_record_path(base.layout)
        try:
            # stage application (with the measured, self-verifying entry that bakes
            # in the trusted record path) ...
            app = deploy_operator_stack(self._source_root, package_root, record_path)
            # ... verify the freshly staged application tree ...
            ok, problems = verify_application_tree(package_root, app.manifest)
            if not ok:
                raise OperatorStackError(f"post-deploy application tree invalid: {problems}")
            # ... re-measure from bytes on disk (never trust an in-memory digest) ...
            measured = measure_application_tree(package_root, app.manifest)
            if measured != app.manifest.tree_digest:
                raise OperatorStackError("post-deploy re-measure disagrees with manifest")
        except OperatorStackError as exc:
            self._rollback_or_unknown(base, exc)

        # R3D: measure the EFFECTIVE whole-root identity AFTER the application tree
        # is deployed and verified — the identity of the final executable one-tree.
        try:
            effective = self._observe_effective()
        except Exception as exc:  # noqa: BLE001
            self._rollback_or_unknown(base, exc)
        if not _is_hex64(effective):
            self._rollback_or_unknown(
                base, GnosisDeploymentError("effective deployment digest is invalid"))

        digest = composed_deployment_digest(base.deployment_digest, measured, effective)
        record = ComposedRecord(
            schema=COMPOSED_RECORD_SCHEMA,
            f17_deployment_digest=base.deployment_digest,
            application_tree_digest=measured,
            effective_deployment_digest=effective,
            composed_deployment_digest=digest,
            package_root=str(package_root),
            operator_entry_relpath=app.entry_path.name,
            worker_image_relpath=_WORKER_IMAGE_REL)
        try:
            # write the trusted record atomically AFTER the application is staged,
            # measured and verified — never before.
            _atomic_write_json(record_path, record.to_dict())
        except Exception as exc:  # noqa: BLE001
            self._rollback_or_unknown(base, exc)

        launch_argv = (str(Path(base.layout.runtime_executable)), "-I", "-B",
                       str(app.entry_path))
        comp = ComposedDeployment(
            layout=base.layout, package_root=package_root,
            operator_entry=app.entry_path, worker_image=app.worker_image,
            application=app, f17_deployment_digest=base.deployment_digest,
            effective_deployment_digest=effective,
            composed_deployment_digest=digest, composed_record_path=record_path,
            launch_argv=launch_argv)

        # final complete-deployment verification: read the record BACK from disk and
        # re-verify the whole composition. Only a fully verified deployment is
        # returned usable.
        try:
            self.verify(comp, expect_f17_digest=base.deployment_digest,
                        expect_effective=effective)
        except GnosisDeploymentError as exc:
            self._rollback_or_unknown(base, exc)
        return comp

    @staticmethod
    def _rollback_or_unknown(base: BaseDeployment, exc: Exception) -> NoReturn:
        try:
            base.rollback()
        except Exception as rbexc:  # noqa: BLE001
            raise GnosisDeploymentError(
                f"composed provisioning failed ({exc}); base rollback ALSO failed "
                f"({rbexc}); deployment is in an unknown state") from exc
        raise GnosisDeploymentError(
            f"composed provisioning failed; base rolled back: {exc}") from exc

    @staticmethod
    def verify(comp: ComposedDeployment, *, expect_f17_digest: str | None = None,
               expect_effective: str | None = None) -> None:
        """Fail closed unless: the deployed application matches its manifest; the
        re-measured tree digest matches; the trusted record (read from disk) agrees
        on the application digest, the base F-17 provenance, the effective whole-root
        identity and the composed binding of all three; and the launch is isolated.
        `expect_f17_digest` is the base F-17 provenance; `expect_effective` is the
        freshly observed effective whole-root identity that must equal the record's."""
        ok, problems = verify_application_tree(comp.package_root,
                                               comp.application.manifest)
        if not ok:
            raise GnosisDeploymentError(
                f"application tree does not match its manifest: {problems}")
        try:
            measured = measure_application_tree(comp.package_root,
                                                comp.application.manifest)
        except OperatorStackError as exc:
            raise GnosisDeploymentError(str(exc)) from exc
        record = read_composed_record(comp.composed_record_path)
        if record.application_tree_digest != measured:
            raise GnosisDeploymentError(
                "re-measured application tree digest does not match the trusted record")
        f17_digest = expect_f17_digest if expect_f17_digest is not None else \
            comp.f17_deployment_digest
        if record.f17_deployment_digest != f17_digest:
            raise GnosisDeploymentError(
                "F-17 base provenance does not match the trusted record")
        effective = expect_effective if expect_effective is not None else \
            comp.effective_deployment_digest
        if record.effective_deployment_digest != effective:
            raise GnosisDeploymentError(
                "effective deployment identity does not match the trusted record")
        redigest = composed_deployment_digest(f17_digest, measured, effective)
        if redigest != record.composed_deployment_digest:
            raise GnosisDeploymentError("composed deployment identity mismatch")
        if record.worker_image_relpath != _WORKER_IMAGE_REL:
            raise GnosisDeploymentError("trusted record names an unexpected worker image")
        if "-I" not in comp.launch_argv:
            raise GnosisDeploymentError("canonical launch is not isolated (-I missing)")

    @staticmethod
    def canonical_launch(comp: ComposedDeployment, *,
                         reobserve_f17: Callable[[], str],
                         spawn: bool = False,
                         operator_args: tuple[str, ...] = ()) -> tuple[str, ...]:
        """The ONE supported production launch. Immediately before process
        creation it: (1) reads the trusted composed record; (2) re-observes the
        current F-17 deployment identity via the injected observer (production
        wires this to `gnosis.trust.deployment.observe_deployment(...).digest()`);
        (3) re-measures the application manifest/tree from CURRENT bytes (never an
        in-memory digest); (4) verifies the measured operator entry and canonical
        Worker image; (5) recomputes the composed digest; (6) compares against the
        trusted expected digest; (7) fails closed on any mismatch; (8) only then
        returns/executes the isolated `-I -B` launch of the measured entry.

        The entry path, package root and interpreter are taken from the trusted
        `comp`/record and the deployment-bound runtime — never from caller input —
        and verification cannot be disabled.
        """
        record = read_composed_record(comp.composed_record_path)
        # (2) fresh EFFECTIVE whole-root re-observation. `reobserve_f17` is the
        # canonical whole-root observer; because the application tree is co-located
        # under trust_root (one-tree), what it observes at launch is the EFFECTIVE
        # final deployment identity — which must equal the record's effective digest
        # (NOT the pre-application base provenance: that was the R3A/R3C collision).
        observed_effective = reobserve_f17()
        if not _is_hex64(observed_effective):
            raise GnosisDeploymentError("re-observed effective deployment digest is invalid")
        if observed_effective != record.effective_deployment_digest:
            raise GnosisDeploymentError(
                "re-observed effective deployment identity does not match the trusted "
                "record")
        # (3) re-load the deployed manifest fail-closed and re-measure from bytes.
        try:
            manifest = load_application_manifest(comp.package_root)
            measured = measure_application_tree(comp.package_root, manifest)
        except OperatorStackError as exc:
            raise GnosisDeploymentError(str(exc)) from exc
        if measured != record.application_tree_digest:
            raise GnosisDeploymentError(
                "re-measured application tree digest does not match the trusted record")
        # (4) measured operator entry + canonical worker image present & measured.
        rels = {f.relpath for f in manifest.files}
        if record.operator_entry_relpath not in rels:
            raise GnosisDeploymentError("operator entry is not a measured manifest file")
        if record.worker_image_relpath not in rels:
            raise GnosisDeploymentError("worker image is not a measured manifest file")
        if not (comp.package_root / record.worker_image_relpath).is_file():
            raise GnosisDeploymentError("canonical worker image is not deployed")
        # (5)+(6) recompute the composed binding from ALL THREE identities — the
        # record's immutable base F-17 provenance, the freshly re-measured
        # application identity and the freshly observed effective identity — and
        # compare against the trusted composed digest. Any substrate/app/injected-
        # file mutation or record operand mix fails closed here or above.
        redigest = composed_deployment_digest(record.f17_deployment_digest, measured,
                                              observed_effective)
        if redigest != record.composed_deployment_digest:
            raise GnosisDeploymentError("composed deployment identity mismatch")
        # (8) canonical isolated launch of the MEASURED entry only.
        entry = comp.package_root / record.operator_entry_relpath
        argv = (str(Path(comp.layout.runtime_executable)), "-I", "-B",
                str(entry), *operator_args)
        if "-I" not in argv:
            raise GnosisDeploymentError("canonical launch is not isolated (-I missing)")
        if spawn:
            completed = subprocess.run(list(argv), check=False)
            raise SystemExit(completed.returncode)
        return argv

    @staticmethod
    def cleanup(comp: ComposedDeployment) -> None:
        """Remove the application-provided files (leaving the F-17 base to its own
        rollback) and the trusted composed record. Best-effort, used on teardown."""
        for f in comp.application.manifest.files:
            target = comp.package_root / f.relpath
            if f.relpath.startswith("gnosis/trust/"):
                continue  # never touch F-17-owned trust
            if target.is_file():
                target.unlink()
        shutil.rmtree(comp.package_root / "gnosis" / "director", ignore_errors=True)
        try:
            comp.composed_record_path.unlink()
        except OSError:
            pass
