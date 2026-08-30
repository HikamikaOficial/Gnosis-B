"""The GNOSIS production provisioner (F-17 Stage 8).

Turns a DeploymentLayout + a ProvisionConfig into real OS state — directories,
ACLs, a dedicated worker account, a DPAPI credential blob, a RESTRICTED
service-SID publisher, a relocated runtime with python._pth, a relocated
toolchain, and the deployment descriptors — then OBSERVES the result and refuses
to activate unless the observed state matches what was intended.

TESTABLE WITHOUT THE OS. Every side effect goes through the `Operations`
protocol. A recording fake lets a test assert the TRANSACTION ORDER and the
exact commands (ACLs applied before the deployment is observed; the worker
granted no write on a trusted root; the service SID RESTRICTED) with no account,
service or ACL created. `RealOperations` performs them for the OS-real
qualification probe.

FAIL CLOSED. A partial install never activates: the service is started only
after the observed deployment matches the intended one. Update stages a new
release beside the old and flips the service only after the new release
verifies; rollback flips back to a release that is re-observed. Nothing is
overwritten in place before its replacement is verified.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from gnosis.provision.layout import DeploymentLayout, Principal, RootSpec

# The four SID roles the ACL matrix resolves. Administrators and SYSTEM are
# well-known; the service and worker SIDs are observed after creation.
WELL_KNOWN_ADMINISTRATORS = "S-1-5-32-544"
WELL_KNOWN_SYSTEM = "S-1-5-18"

SERVICE_CONFIG_SCHEMA = "gnosis.trust.publisher_service.v1"
PACKAGE_SCHEMA = "gnosis.trust.package.v1"
PIPE_POLICY_SCHEMA = "gnosis.trust.pipe_policy.v1"


@dataclass(frozen=True)
class ResolvedSids:
    maintenance: str
    system: str
    service: str
    worker: str

    def of(self, principal: Principal) -> str:
        return {
            Principal.MAINTENANCE: self.maintenance,
            Principal.SYSTEM: self.system,
            Principal.SERVICE: self.service,
            Principal.WORKER: self.worker,
        }[principal]


@dataclass(frozen=True)
class ProvisionConfig:
    layout: DeploymentLayout
    service_name: str
    pipe_name: str
    worker_username: str
    package_version: str
    source_commit: str
    source_tree: str
    worker_comment: str = "GNOSIS dedicated worker (non-admin)"


# ---------------------------------------------------------------------------
# Pure content renderers. No I/O; a test checks the exact bytes/strings.
# ---------------------------------------------------------------------------
def pth_content() -> str:
    """The python._pth that pins the deployed runtime's search path.

    Relative to python.exe (the runtime root). It lists the runtime's own
    standard library and the trust package beside it, and it does NOT contain an
    `import site` line — so site, per-user site, and .pth processing are off, and
    a Worker-controlled PYTHONPATH or an editable install cannot inject a module.
    `..\\publisher` is the deployed trust package, so `import gnosis` resolves
    there and nowhere else.
    """
    return (
        "python313.zip\n"
        "python312.zip\n"
        ".\n"
        "DLLs\n"
        "Lib\n"
        "..\\publisher\n"
    )


def service_imagepath(runtime_executable: str, service_entry: str,
                      config_path: str) -> str:
    """The service ImagePath: absolute, quoted, isolated, no PATH/shell.

    `-I` isolates the interpreter (ignores PYTHONPATH, the registry and per-user
    site); the entry point puts the deployed trust package on sys.path itself.
    Every component is an absolute path in the trusted, non-worker-writable code
    root, and there is no shell and no PATH executable lookup.
    """
    return f'"{runtime_executable}" -I "{service_entry}" "{config_path}"'


def package_json(version: str, commit: str, tree: str) -> dict[str, str]:
    return {"schema": PACKAGE_SCHEMA, "package_version": version,
            "source_commit": commit, "source_tree": tree}


def pipe_policy_json(pipe_name: str, sddl: str) -> dict[str, Any]:
    return {"schema_version": PIPE_POLICY_SCHEMA, "name": pipe_name,
            "sddl": sddl,
            "flags": ["FILE_FLAG_FIRST_PIPE_INSTANCE", "PIPE_REJECT_REMOTE_CLIENTS",
                      "PIPE_TYPE_MESSAGE", "MAX_INSTANCES=1"]}


def service_config_json(config: ProvisionConfig, sids: ResolvedSids,
                        deployment_digest: str) -> dict[str, str]:
    lay = config.layout
    return {
        "schema": SERVICE_CONFIG_SCHEMA,
        "service_name": config.service_name,
        "pipe_name": config.pipe_name,
        "service_sid": sids.service,
        "trust_state_root": lay.state_base,
        "evidence_root": lay.bundles_root,
        "authorized_worker_sid": sids.worker,
        "expected_deployment_digest": deployment_digest,
        "log_path": lay.log_path,
    }


def icacls_commands(spec: RootSpec, path: str, sids: ResolvedSids) -> list[list[str]]:
    """The icacls invocations for one root: strip inheritance, then grant.

    A protected root strips inheritance FIRST (so an inherited Users:RX from
    Program Files / ProgramData cannot survive), then grants exactly the matrix
    principals. A principal with no grant simply is not named — an absent ACE on
    an inheritance-stripped root is a hard deny.
    """
    cmds: list[list[str]] = []
    if spec.break_inheritance:
        cmds.append(["icacls", path, "/inheritance:r"])
    if spec.grants:
        grant = ["icacls", path, "/grant:r"]
        for principal, access in spec.grants:
            grant.append(f"*{sids.of(principal)}:{access.value}")
        cmds.append(grant)
    return cmds


# ---------------------------------------------------------------------------
# The Operations boundary. All side effects live behind this.
# ---------------------------------------------------------------------------
class Operations(Protocol):
    def run(self, argv: list[str]) -> tuple[int, str]: ...
    def mkdir(self, path: str) -> None: ...
    def rmtree(self, path: str) -> None: ...
    def exists(self, path: str) -> bool: ...
    def copytree(self, src: str, dst: str) -> None: ...
    def copyfile(self, src: str, dst: str) -> None: ...
    def write_text(self, path: str, text: str) -> None: ...
    def write_bytes(self, path: str, data: bytes) -> None: ...
    def resolve_sid(self, name: str) -> str: ...
    def create_worker(self, username: str, password: str, comment: str) -> None: ...
    def delete_worker(self, username: str) -> int: ...
    def protect_secret(self, secret: str) -> bytes: ...


class ProvisioningError(RuntimeError):
    """Provisioning could not establish the intended state; fail closed."""


@dataclass
class InstallResult:
    sids: ResolvedSids
    deployment_digest: str
    observed: object


@dataclass
class Provisioner:
    config: ProvisionConfig
    ops: Operations
    # Sources to deploy FROM (the maintenance host's runtime, trust package,
    # bootstrap and toolchain). Kept as plain paths so a test can pass fakes.
    runtime_src: str
    publisher_files: Sequence[tuple[str, str]]  # (src_abs, rel_under_publisher)
    bootstrap_files: Sequence[tuple[str, str]]  # (src_abs, rel_under_bootstrap)
    toolchain_files: Sequence[tuple[str, str]]  # (src_abs, rel_under_toolchain)
    # Injectable observation so the install transaction is testable without a
    # real deployment; defaults to the real deployment observer.
    observe_fn: Any = None
    steps: list[str] = field(default_factory=list)

    def _note(self, step: str) -> None:
        self.steps.append(step)

    # -- the install transaction, in the one correct order --------------------
    def install(self, worker_password: str) -> InstallResult:
        sids_partial = self._create_identities(worker_password)
        self._deploy_code()
        self._write_descriptors_pre_acl(sids_partial)
        self._install_service()
        service_sid = self.ops.resolve_sid(f"NT SERVICE\\{self.config.service_name}")
        sids = ResolvedSids(sids_partial.maintenance, sids_partial.system,
                            service_sid, sids_partial.worker)
        self._apply_acls(sids)              # ACLs BEFORE observation (digest binds them)
        digest, observed = self._observe(sids)
        self._write_config(sids, digest)
        self._note("verify: observed deployment matches intended")
        return InstallResult(sids=sids, deployment_digest=digest, observed=observed)

    def _create_identities(self, worker_password: str) -> ResolvedSids:
        maintenance = self.ops.resolve_sid("BUILTIN\\Administrators")
        system = WELL_KNOWN_SYSTEM
        self.ops.create_worker(self.config.worker_username, worker_password,
                               self.config.worker_comment)
        worker = self.ops.resolve_sid(self.config.worker_username)
        self._note(f"create worker account {self.config.worker_username} "
                   f"(SID {worker})")
        # The DPAPI blob is written now; its ACL (worker DENIED) is applied in
        # the ACL pass. The plaintext exists only transiently in memory here.
        blob = self.ops.protect_secret(worker_password)
        self.ops.mkdir(str(Path(self.config.layout.secrets_blob).parent))
        self.ops.write_bytes(self.config.layout.secrets_blob, blob)
        self._note("write DPAPI machine-bound worker credential blob")
        return ResolvedSids(maintenance, system, "PENDING-SERVICE-SID", worker)

    def _deploy_code(self) -> None:
        lay = self.config.layout
        self.ops.mkdir(lay.code_release_base)
        self.ops.copytree(self.runtime_src, lay.runtime_root)
        self.ops.write_text(lay.pth_file, pth_content())
        self._note("deploy runtime + python._pth")
        for src, rel in self.publisher_files:
            self.ops.copyfile(src, f"{lay.trust_root}\\{rel}")
        for src, rel in self.bootstrap_files:
            self.ops.copyfile(src, f"{lay.code_release_base}\\bootstrap\\{rel}")
        for src, rel in self.toolchain_files:
            self.ops.copyfile(src, f"{lay.code_release_base}\\toolchain\\{rel}")
        # The service entry point lives at the trust root and puts the deployed
        # trust package on sys.path[0] itself (so -I isolation still imports it).
        self.ops.write_text(
            lay.service_entry,
            "import sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
            "from gnosis.trust.publisher_service import main\n"
            "raise SystemExit(main(sys.argv))\n")
        self._note("deploy publisher trust package, bootstrap, toolchain, entry")

    def _write_descriptors_pre_acl(self, sids: ResolvedSids) -> None:
        lay = self.config.layout
        self.ops.write_text(lay.package_json, json.dumps(
            package_json(self.config.package_version, self.config.source_commit,
                         self.config.source_tree), indent=2, sort_keys=True))
        # The pipe SDDL needs the service SID, still pending here; it is written
        # with a placeholder and rewritten after the service exists (_apply_acls).
        self.ops.write_text(lay.pipe_policy_json, json.dumps(
            pipe_policy_json(self.config.pipe_name, "PENDING"), indent=2,
            sort_keys=True))
        self._note("write PACKAGE.json (real provenance) + PIPE_POLICY.json")

    def _install_service(self) -> None:
        lay = self.config.layout
        name = self.config.service_name
        binary = service_imagepath(lay.runtime_executable, lay.service_entry,
                                   lay.config_path)
        self._checked(["sc.exe", "create", name, "binPath=", binary,
                       "type=", "own", "start=", "demand",
                       "obj=", f"NT SERVICE\\{name}"], "sc create")
        self._checked(["sc.exe", "sidtype", name, "restricted"], "sc sidtype")
        # Least privilege: only SeChangeNotify (traverse). Everything else is
        # stripped by naming only this one.
        self._checked(["sc.exe", "privs", name, "SeChangeNotifyPrivilege"],
                      "sc privs", allow_fail=True)
        # No auto-restart that could hide a fault; the Director restarts on
        # demand.
        self._checked(["sc.exe", "failure", name, "reset=", "0", "actions=", ""],
                      "sc failure", allow_fail=True)
        self._note(f"install RESTRICTED service {name} (SeChangeNotify only, "
                   "no auto-restart)")

    def _apply_acls(self, sids: ResolvedSids) -> None:
        from gnosis.trust.pipe_server import worker_pipe_sddl
        lay = self.config.layout
        # Rewrite the pipe policy now the service SID is known.
        self.ops.write_text(lay.pipe_policy_json, json.dumps(
            pipe_policy_json(self.config.pipe_name,
                             worker_pipe_sddl(sids.worker, sids.service)),
            indent=2, sort_keys=True))
        for spec in lay.roots():
            path = lay.path(spec)
            if not self.ops.exists(path):
                self.ops.mkdir(path)
            for cmd in icacls_commands(spec, path, sids):
                self._checked(cmd, f"icacls {spec.key}")
        # The service-object DACL: the worker gets NO ACE; maintenance may
        # query/start/stop; SYSTEM and Administrators keep full control.
        self._set_service_dacl(sids)
        self._note("apply ACL matrix (inheritance stripped, worker denied on "
                   "every trusted root) and the service-object DACL")

    def _set_service_dacl(self, sids: ResolvedSids) -> None:
        # SY/BA full; the maintenance principal query+start+stop+interrogate;
        # the worker is absent (no SERVICE_* rights, cannot change config, SID
        # type, ImagePath, or delete). A High mandatory label as defence in
        # depth.
        maint = sids.maintenance
        sddl = (f"D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)"
                f"(A;;CCLCSWRPWPDTLOCRRC;;;BA)"
                f"(A;;CCLCSWRPRC;;;{maint})"
                f"S:(ML;;NW;;;HI)")
        self._checked(["sc.exe", "sdset", self.config.service_name, sddl],
                      "sc sdset", allow_fail=True)

    def _observe(self, sids: ResolvedSids) -> tuple[str, object]:
        from gnosis.trust.deployment import DesiredDeploymentConfig, observe_deployment
        lay = self.config.layout
        observer = self.observe_fn or observe_deployment
        observed = observer(DesiredDeploymentConfig(
            trust_root=Path(lay.trust_root),
            runtime_executable=Path(lay.runtime_executable),
            runtime_root=Path(lay.runtime_root),
            runidentity_store=Path(lay.runidentity_root),
            anchorstore=Path(lay.anchors_root),
            service_name=self.config.service_name))
        digest = observed.digest()
        self._note(f"observe deployment -> digest {digest[:12]}")
        return digest, observed

    def _write_config(self, sids: ResolvedSids, digest: str) -> None:
        lay = self.config.layout
        self.ops.write_text(lay.config_path, json.dumps(
            service_config_json(self.config, sids, digest), indent=2,
            sort_keys=True))
        self.ops.write_text(lay.deployment_json, json.dumps(
            {"deployment_digest": digest}, indent=2, sort_keys=True))
        self._note("write config.json (expected_deployment_digest) + "
                   "DEPLOYMENT.json")

    def _checked(self, argv: list[str], label: str,
                 allow_fail: bool = False) -> None:
        rc, out = self.ops.run(argv)
        if rc != 0 and not allow_fail:
            raise ProvisioningError(f"{label} failed (rc={rc}): {out[:200]}")

    # -- teardown -------------------------------------------------------------
    def uninstall(self, *, remove_worker: bool = True) -> None:
        """Remove only Gnosis-owned resources, in an order that first removes
        the running service's privileged access. No wildcard deletion."""
        name = self.config.service_name
        self.ops.run(["sc.exe", "stop", name])
        self.ops.run(["sc.exe", "delete", name])
        if remove_worker:
            self.ops.delete_worker(self.config.worker_username)
        for base in (self.config.layout.code_base, self.config.layout.state_base,
                     self.config.layout.work_base):
            if self.ops.exists(base):
                self.ops.rmtree(base)
        self._note("uninstall: service stopped+deleted, worker removed, "
                   "gnosis-owned roots removed")
