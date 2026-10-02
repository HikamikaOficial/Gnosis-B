"""F-17 Stage 6 — the Director-side seam: what may become a trusted run.

The publisher tests ask what a hostile Worker can talk the service into. These
ask the other half: whether the trusted plane can be talked into creating a run
identity that says something it did not observe, or into calling a run
publishable that no trusted party accepted.
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gnosis.trust.anchor import RUN_IDENTITY_SCHEMA_V2
from gnosis.trust.bundle_verify import write_bundle_manifest
from gnosis.trust.deployment import (
    DEPLOYMENT_SCHEMA,
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
from gnosis.trust.launch import AuthorityUnavailable
from gnosis.trust.launch_spec import LaunchSpec
from gnosis.trust.orchestration import (
    CompletionEvidence,
    RunNotPublishable,
    RunPlan,
    authorize_publishable,
    create_trusted_run,
)
from gnosis.trust.run_identity import PublicationState, TrustedRunIdentityStore
from gnosis.trust.worker_launcher import LaunchedWorkerIdentity

SID_OBSERVED = "S-1-5-21-1111111111-2222222222-3333333333-1001"
LAUNCH_DIGEST = "a" * 64
HEAD = "h" * 40
TREE = "t" * 64


def _sd(owner: str = "S-1-5-18") -> SecurityDescriptorIdentity:
    return SecurityDescriptorIdentity(
        owner_sid=owner, group_sid=owner, control=0x8004, dacl_present=True,
        aces=(AceIdentity(ace_type="ALLOWED", ace_flags=0,
                          access_mask=0x1F01FF, sid=owner),),
        mandatory_label=None)


def _deployment(*, schema: str = DEPLOYMENT_SCHEMA_V2,
                runtime_files: tuple[FileIdentity, ...] = (),
                ) -> TrustPlaneDeploymentIdentity:
    """A real identity object, so `digest()` is a real digest.

    Built by construction rather than by observation because observing a
    deployment needs an installed service; the SHAPE is what these tests are
    about, and the shape is the real one.
    """
    files = runtime_files or (
        FileIdentity(path="python.exe", size=1, digest="0" * 64),
        FileIdentity(path="Lib/os.py", size=2, digest="1" * 64),
    )
    tree = (FileTreeManifest(schema=FILE_TREE_SCHEMA, label="python-runtime",
                             files=files)
            if schema == DEPLOYMENT_SCHEMA_V2 else None)
    return TrustPlaneDeploymentIdentity(
        schema=schema,
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
            schema_version="gnosis.trust.pipe_policy.v1",
            name="gnosis-publish",
            flags=("PIPE_REJECT_REMOTE_CLIENTS", "FIRST_PIPE_INSTANCE"),
            security_descriptor=_sd()),
        runtime_tree=tree)


def _launched(sid: str = SID_OBSERVED,
              launch_digest: str = LAUNCH_DIGEST) -> LaunchedWorkerIdentity:
    return LaunchedWorkerIdentity(
        pid=4242, observed_sid=sid, integrity="Medium", is_administrator=False,
        dangerous_privileges=(), launch_spec_digest=launch_digest,
        logical_command_digest="f" * 64, transport_command_length=264,
        contained_in_job=True)


def _spec(run_id: str = "run-1") -> LaunchSpec:
    return LaunchSpec(
        launch_id="L-1", executable=r"C:\rt\python.exe",
        argv=(r"C:\rt\python.exe", "-c", "pass"), cwd=r"C:\work",
        stdout_path=r"C:\work\out.txt", stderr_path=r"C:\work\err.txt",
        run_id=run_id)


def _bundle(path: Path, *, head: str = HEAD) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SUMMARY.json").write_text(json.dumps({
        "tree_identity": {"post": {"fingerprint": {"head_sha": head}}},
        "boundary": {"verdict": "CLEAN", "protection": {"content_digest": TREE}},
    }), encoding="utf-8")
    write_bundle_manifest(path)
    return path


class _SeamCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = TrustedRunIdentityStore(self.root / "runs")
        self.bundle = _bundle(self.root / "evidence" / "run-1")

    def plan(self, run_id: str = "run-1", **overrides: object) -> RunPlan:
        base: dict[str, object] = {
            "task_id": "F-17", "run_id": run_id, "repository_id": "repoX",
            "head_sha": HEAD, "tree_identity": TREE,
            "bundle_path": str(self.bundle), "epoch": 0,
        }
        base.update(overrides)
        return RunPlan(**base)  # type: ignore[arg-type]


class TestTheIdentityIsObservedNotDeclared(_SeamCase):
    def test_the_owner_sid_comes_from_the_launched_token(self):
        record = create_trusted_run(self.store, self.plan(), spec=_spec(),
                                    deployment=_deployment(),
                                    launched=_launched(SID_OBSERVED))
        self.assertEqual(record.identity.owner_worker_sid, SID_OBSERVED)

    def test_a_plan_cannot_even_express_an_owner_a_deployment_or_a_launch(self):
        # Structural, not behavioural: a field that does not exist cannot be
        # set by a caller who would rather assert than observe.
        names = {f.name for f in dataclasses.fields(RunPlan)}
        for forbidden in ("owner_worker_sid", "deployment_digest",
                          "launch_spec_digest", "schema"):
            self.assertNotIn(forbidden, names)

    def test_the_launch_binding_comes_from_the_launcher(self):
        record = create_trusted_run(self.store, self.plan(), spec=_spec(),
                                    deployment=_deployment(),
                                    launched=_launched(launch_digest="b" * 64))
        self.assertEqual(record.identity.launch_spec_digest, "b" * 64)
        self.assertEqual(record.identity.schema, RUN_IDENTITY_SCHEMA_V2)

    def test_the_deployment_digest_is_the_observed_identitys_own_digest(self):
        deployment = _deployment()
        record = create_trusted_run(self.store, self.plan(), spec=_spec(),
                                    deployment=deployment, launched=_launched())
        self.assertEqual(record.identity.deployment_digest, deployment.digest())

    def test_a_different_runtime_tree_is_a_different_deployment(self):
        # The whole point of the V2 expansion: change a library file and the
        # digest moves, even though python.exe is byte-identical.
        one = _deployment()
        other = _deployment(runtime_files=(
            FileIdentity(path="python.exe", size=1, digest="0" * 64),
            FileIdentity(path="Lib/os.py", size=2, digest="9" * 64),
        ))
        self.assertNotEqual(one.digest(), other.digest())


class TestTheSeamRefusesWhatItCannotStandBehind(_SeamCase):
    def test_a_deployment_that_does_not_bind_the_runtime_tree_is_refused(self):
        with self.assertRaises(AuthorityUnavailable):
            create_trusted_run(self.store, self.plan(), spec=_spec(),
                               deployment=_deployment(schema=DEPLOYMENT_SCHEMA),
                               launched=_launched())

    def test_a_seal_for_another_run_cannot_be_bound_to_this_plan(self):
        with self.assertRaises(AuthorityUnavailable):
            create_trusted_run(self.store, self.plan("run-1"),
                               spec=_spec("run-2"), deployment=_deployment(),
                               launched=_launched())

    def test_a_refused_creation_leaves_no_identity_behind(self):
        with self.assertRaises(AuthorityUnavailable):
            create_trusted_run(self.store, self.plan(), spec=_spec("other"),
                               deployment=_deployment(), launched=_launched())
        self.assertFalse(self.store.exists("run-1"))


class TestPublishableIsAJudgementNotAnEvent(_SeamCase):
    def _created(self):  # type: ignore[no-untyped-def]
        return create_trusted_run(self.store, self.plan(), spec=_spec(),
                                  deployment=_deployment(),
                                  launched=_launched()).identity

    def test_a_clean_run_with_a_verifying_bundle_becomes_publishable(self):
        identity = self._created()
        record = authorize_publishable(
            self.store, identity,
            CompletionEvidence(0, False, False, self.bundle))
        self.assertIs(record.publication_state, PublicationState.PUBLISHABLE)

    def test_a_failed_timed_out_or_cancelled_run_is_refused(self):
        identity = self._created()
        for evidence in (CompletionEvidence(1, False, False, self.bundle),
                         CompletionEvidence(0, True, False, self.bundle),
                         CompletionEvidence(0, False, True, self.bundle)):
            with self.subTest(evidence=evidence):
                with self.assertRaises(RunNotPublishable):
                    authorize_publishable(self.store, identity, evidence)
                self.assertIs(self.store.read("run-1").publication_state,
                              PublicationState.NOT_PUBLISHABLE)

    def test_a_bundle_somewhere_else_is_refused(self):
        identity = self._created()
        elsewhere = _bundle(self.root / "evidence" / "not-the-one")
        with self.assertRaises(RunNotPublishable):
            authorize_publishable(self.store, identity,
                                  CompletionEvidence(0, False, False, elsewhere))

    def test_a_tampered_bundle_is_refused(self):
        identity = self._created()
        (self.bundle / "SUMMARY.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(RunNotPublishable):
            authorize_publishable(self.store, identity,
                                  CompletionEvidence(0, False, False, self.bundle))
        self.assertIs(self.store.read("run-1").publication_state,
                      PublicationState.NOT_PUBLISHABLE)


class TestTheSeamIsNotReachableFromTheService(unittest.TestCase):
    """The service must not be able to mark anything publishable, and the
    cheapest guarantee is that the code to do so is not in its closure.

    MEASURED IN A SUBPROCESS, and the reason is a defect this test used to
    have. The first version popped `gnosis.trust.worker_launcher` and friends
    out of `sys.modules` to get a clean measurement - and never put them back.
    Anything that imported them afterwards got a NEW module object holding NEW
    class objects, so a later file's `assertRaises(WorkerLaunchFailed)` stopped
    catching the `WorkerLaunchFailed` being raised: same name, two classes.
    Two files passed alone and failed together.

    A test that corrupts the interpreter to take its measurement is measuring
    something nobody runs. A fresh process is both honest and cheap.
    """

    FORBIDDEN = ("gnosis.trust.orchestration", "gnosis.trust.deployment",
                 "gnosis.trust.worker_launcher", "gnosis.kernel.evidence_capture")

    def test_the_publisher_does_not_import_the_writers_seam(self):
        src = Path(__file__).resolve().parents[1] / "src"
        program = (
            "import sys, json;"
            f"sys.path.insert(0, {str(src)!r});"
            "import gnosis.trust.publisher_service;"
            "print(json.dumps(sorted(m for m in sys.modules if m.startswith('gnosis'))))"
        )
        proc = subprocess.run([sys.executable, "-c", program],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr[:400])
        closure = set(json.loads(proc.stdout.strip().splitlines()[-1]))
        for forbidden in self.FORBIDDEN:
            self.assertNotIn(forbidden, closure,
                             f"{forbidden} reached the publisher's closure")
        # And the measurement is not vacuous: the service itself IS in there.
        self.assertIn("gnosis.trust.publisher_service", closure)
        self.assertIn("gnosis.trust.bundle_verify", closure)


if __name__ == "__main__":
    unittest.main()
