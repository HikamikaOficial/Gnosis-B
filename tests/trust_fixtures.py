"""Shared in-process trust-plane fixtures for F-33 publication tests.

Builds a V2 `TrustPlaneDeploymentIdentity`, a `LaunchedWorkerIdentity`, a
`LaunchSpec` and a sealed evidence bundle by CONSTRUCTION (no installed service),
mirroring the qualified pattern in `test_trusted_orchestration.py`. This lets
Stage-2B.2 publication tests drive the REAL trust code (create_trusted_run ->
authorize_publishable -> durable_publish -> ANCHORED) in-process.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from gnosis.director.publication import GitTreeEvidence
from gnosis.trust.bundle_verify import write_bundle_manifest
from gnosis.trust.deployment import (
    DEPLOYMENT_SCHEMA_V2,
    FILE_TREE_SCHEMA,
    MANIFEST_SCHEMA,
    AceIdentity,
    FileIdentity,
    FileTreeManifest,
    PathSecurityIdentity,
    PipePolicyIdentity,
    RuntimeIdentity,
    SecurityDescriptorIdentity,
    ServiceIdentity,
    TrustPackageManifest,
    TrustPlaneDeploymentIdentity,
)
from gnosis.trust.launch_spec import LaunchSpec
from gnosis.trust.worker_launcher import LaunchedWorkerIdentity

SID_OBSERVED = "S-1-5-21-1111111111-2222222222-3333333333-1001"
LAUNCH_DIGEST = "a" * 64


def _sd(owner: str = "S-1-5-18") -> SecurityDescriptorIdentity:
    return SecurityDescriptorIdentity(
        owner_sid=owner, group_sid=owner, control=0x8004, dacl_present=True,
        aces=(AceIdentity(ace_type="ALLOWED", ace_flags=0,
                          access_mask=0x1F01FF, sid=owner),),
        mandatory_label=None)


def v2_deployment(*, runtime_files: tuple[FileIdentity, ...] = ()
                  ) -> TrustPlaneDeploymentIdentity:
    files = runtime_files or (
        FileIdentity(path="python.exe", size=1, digest="0" * 64),
        FileIdentity(path="Lib/os.py", size=2, digest="1" * 64),
    )
    return TrustPlaneDeploymentIdentity(
        schema=DEPLOYMENT_SCHEMA_V2,
        package=TrustPackageManifest(
            schema=MANIFEST_SCHEMA, package_version="1.0.0",
            source_commit="c" * 40, source_tree="d" * 64,
            files=(FileIdentity(path="publisher.py", size=3, digest="2" * 64),)),
        runtime=RuntimeIdentity(
            executable_path=r"C:\rt\python.exe", executable_size=1,
            executable_digest="0" * 64, version="3.12.0", implementation="cpython",
            architecture="64bit", machine="AMD64"),
        service=ServiceIdentity(
            name="GnosisPub", account=r"NT SERVICE\GnosisPub",
            image_path=r"C:\rt\python.exe svc.py", start_type="DEMAND",
            service_sid="S-1-5-80-1-2-3-4-5", sid_type="RESTRICTED",
            required_privileges=(), security_descriptor=_sd()),
        trust_root=PathSecurityIdentity(path=r"C:\trust", security_descriptor=_sd()),
        runidentity_store=PathSecurityIdentity(path=r"C:\state\runidentity",
                                               security_descriptor=_sd()),
        anchorstore=PathSecurityIdentity(path=r"C:\state\anchors",
                                         security_descriptor=_sd()),
        pipe_policy=PipePolicyIdentity(
            schema_version="gnosis.trust.pipe_policy.v1", name="gnosis-publish",
            flags=("PIPE_REJECT_REMOTE_CLIENTS", "FIRST_PIPE_INSTANCE"),
            security_descriptor=_sd()),
        runtime_tree=FileTreeManifest(schema=FILE_TREE_SCHEMA,
                                      label="python-runtime", files=files))


def v2_deployment_for_runtime(runtime_executable: Path) -> TrustPlaneDeploymentIdentity:
    """A V2 deployment identity whose runtime is the REAL measured `runtime_executable`,
    so composition's execution-runtime cross-binding digest matches."""
    from gnosis.trust.deployment import observe_runtime
    base = v2_deployment()
    return TrustPlaneDeploymentIdentity(
        schema=base.schema, package=base.package,
        runtime=observe_runtime(runtime_executable), service=base.service,
        trust_root=base.trust_root, runidentity_store=base.runidentity_store,
        anchorstore=base.anchorstore, pipe_policy=base.pipe_policy,
        runtime_tree=base.runtime_tree)


def launched(sid: str = SID_OBSERVED,
             launch_digest: str = LAUNCH_DIGEST) -> LaunchedWorkerIdentity:
    return LaunchedWorkerIdentity(
        pid=4242, observed_sid=sid, integrity="Medium", is_administrator=False,
        dangerous_privileges=(), launch_spec_digest=launch_digest,
        logical_command_digest="f" * 64, transport_command_length=264,
        contained_in_job=True)


def spec(run_id: str = "run-1") -> LaunchSpec:
    return LaunchSpec(
        launch_id="L-1", executable=r"C:\rt\python.exe",
        argv=(r"C:\rt\python.exe", "-c", "pass"), cwd=r"C:\work",
        stdout_path=r"C:\work\out.txt", stderr_path=r"C:\work\err.txt",
        run_id=run_id)


def git_repo(path: Path) -> Path:
    """A real, committed git repo so `observe_git_tree` returns a real HEAD/tree."""
    path.mkdir(parents=True, exist_ok=True)
    for cmd in (["init"], ["config", "user.email", "e@x.com"],
                ["config", "user.name", "T"]):
        subprocess.run(["git", *cmd], cwd=path, capture_output=True, check=False)
    (path / "code.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True, check=False)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True,
                   check=False)
    return path


def sealed_bundle(path: Path, *, head_sha: str, tree_identity: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SUMMARY.json").write_text(json.dumps({
        "tree_identity": {"post": {"fingerprint": {"head_sha": head_sha}}},
        "boundary": {"verdict": "CLEAN",
                     "protection": {"content_digest": tree_identity}},
    }), encoding="utf-8")
    write_bundle_manifest(path)
    return path


def capture_publishable_bundle(path: Path, tree: GitTreeEvidence) -> Path:
    """Synthetic boundary evidence for component tests ONLY, not an OS capture."""
    return sealed_bundle(path, head_sha=tree.head_sha, tree_identity=tree.tree_identity)
