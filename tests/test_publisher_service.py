"""F-17 Stage 6 — the trusted publisher, judged as the Worker's adversary.

Every test here asks the same question from a different angle: can a compromised
Worker, which may say anything the grammar allows and may retry forever, cause a
publication that the trusted plane did not authorize?

The happy path is one test. The rest are refusals, because under T2 the refusals
are the product.
"""
from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gnosis.trust.anchor import (
    RUN_IDENTITY_SCHEMA,
    AnchorStore,
    RunIdentity,
)
from gnosis.trust.bundle_verify import verify_bundle, write_bundle_manifest
from gnosis.trust.launch import AuthorityUnavailable
from gnosis.trust.pipe_server import (
    MAX_INSTANCES,
    MAX_MESSAGE_BYTES,
    PIPE_REJECT_REMOTE_CLIENTS,
    WORKER_PIPE_ACCESS,
    worker_pipe_sddl,
)
from gnosis.trust.publication import initialise_durable_store, read_watermark
from gnosis.trust.publisher import Publisher, PublisherConfig
from gnosis.trust.publisher_service import (
    SERVICE_CONFIG_SCHEMA,
    ServiceConfig,
    run_service,
)
from gnosis.trust.run_identity import TrustedRunIdentityStore

SID_WORKER = "S-1-5-21-1111111111-2222222222-3333333333-1001"
SID_OTHER_WORKER = "S-1-5-21-1111111111-2222222222-3333333333-1002"
SID_SERVICE = "S-1-5-80-3880718322-2925127279-1682361242-2461660535-3372060997"
DEPLOY_1 = "d" * 64
DEPLOY_2 = "e" * 64
LAUNCH_1 = "a" * 64
LAUNCH_2 = "b" * 64
HEAD = "h" * 40
TREE = "t" * 64


def _make_bundle(path: Path, *, head: str = HEAD, tree: str = TREE) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SUMMARY.json").write_text(json.dumps({
        "tree_identity": {"post": {"fingerprint": {"head_sha": head}}},
        "boundary": {"protection": {"content_digest": tree}},
    }), encoding="utf-8")
    write_bundle_manifest(path)
    return path


class _PublisherCase(unittest.TestCase):
    """A publisher over disposable roots. Nothing is installed."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.evidence_root = self.root / "evidence"
        self.evidence_root.mkdir()
        self.config = PublisherConfig(
            trust_state_root=self.root / "state",
            evidence_root=self.evidence_root,
            authorized_worker_sid=SID_WORKER,
            expected_deployment_digest=DEPLOY_1)
        self.publisher = Publisher(self.config)
        initialise_durable_store(
            AnchorStore(self.config.anchors_root, require_high=False))
        self.run_store = TrustedRunIdentityStore(self.config.runidentity_root)

    def identity(self, run_id: str = "run-1", *, sid: str = SID_WORKER,
                 deployment: str = DEPLOY_1, launch: str | None = LAUNCH_1,
                 epoch: int = 0, bundle: Path | None = None,
                 schema: str | None = None) -> RunIdentity:
        bundle_dir = bundle or _make_bundle(self.evidence_root / run_id)
        kwargs = {}
        if schema is not None:
            kwargs["schema"] = schema
        return RunIdentity(
            task_id="F-17", run_id=run_id, repository_id="repoX", head_sha=HEAD,
            tree_identity=TREE, bundle_path=str(bundle_dir), owner_worker_sid=sid,
            deployment_digest=deployment, epoch=epoch,
            launch_spec_digest=launch, **kwargs)

    def publishable(self, identity: RunIdentity) -> RunIdentity:
        self.run_store.create(identity)
        self.run_store.mark_publishable(identity.run_id, identity.digest())
        return identity


class TestTheRequestGrammarIsTheDefence(_PublisherCase):
    """The Worker's whole vocabulary, and what it cannot say."""

    def test_the_happy_path_anchors_exactly_once(self):
        self.publishable(self.identity())
        reply = self.publisher.handle("PUBLISH run-1")
        self.assertTrue(reply.startswith("ANCHORED:"), reply)

    def test_a_repeated_request_is_idempotent_not_a_second_anchor(self):
        self.publishable(self.identity())
        first = self.publisher.handle("PUBLISH run-1")
        second = self.publisher.handle("PUBLISH run-1")
        third = self.publisher.handle("PUBLISH run-1")
        self.assertTrue(first.startswith("ANCHORED:"))
        self.assertTrue(second.startswith("ALREADY_ANCHORED:"), second)
        self.assertTrue(third.startswith("ALREADY_ANCHORED:"), third)
        store = AnchorStore(self.config.anchors_root, require_high=False)
        self.assertEqual(len(store.records()), 1, "a retry must not append again")

    def test_no_other_verb_exists(self):
        self.publishable(self.identity())
        for request in ("DELETE run-1", "publish run-1", "PUBLISH", "",
                        "PUBLISH run-1 extra", "ANCHOR run-1",
                        "PUBLISH run-1\nPUBLISH run-1"):
            with self.subTest(request=request):
                self.assertEqual(self.publisher.handle(request),
                                 "REJECTED:bad-request")

    def test_a_run_id_cannot_be_a_path(self):
        # Traversal is not filtered out afterwards; the grammar cannot express it.
        for run_id in ("../../etc/passwd", "..\\..\\windows", "C:/Windows",
                       "run/../../x", "\\\\server\\share", "run:stream",
                       ".hidden", "-leading"):
            with self.subTest(run_id=run_id):
                self.assertEqual(self.publisher.handle(f"PUBLISH {run_id}"),
                                 "REJECTED:bad-request")

    def test_an_oversized_request_is_refused_before_parsing(self):
        self.assertEqual(self.publisher.handle("PUBLISH " + "a" * 4096),
                         "REJECTED:oversized")

    def test_an_unknown_run_authorizes_nothing(self):
        self.assertEqual(self.publisher.handle("PUBLISH run-does-not-exist"),
                         "REJECTED:unknown-run")

    def test_a_malformed_request_never_crashes_the_handler(self):
        # Availability is a security property here: a Worker that can crash the
        # publisher at will has a denial of service on the whole trust plane.
        for request in ("\x00\x01\x02", "PUBLISH " + "\uffff" * 8, " " * 100):
            with self.subTest(request=request):
                self.assertTrue(self.publisher.handle(request).startswith("REJECTED:"))


class TestTheWorkerCannotPublishAnotherRun(_PublisherCase):
    def test_a_run_owned_by_another_worker_is_refused(self):
        # Worker A knows B's run_id. Knowing it is not authorization.
        self.publishable(self.identity("run-b", sid=SID_OTHER_WORKER))
        self.assertEqual(self.publisher.handle("PUBLISH run-b"),
                         "REJECTED:owner-mismatch")

    def test_the_owner_check_is_against_configuration_not_the_record(self):
        # The load-bearing comparison: the service was provisioned for ONE
        # worker, and that value does not come from the run being published.
        self.publishable(self.identity("run-b", sid=SID_OTHER_WORKER))
        other = Publisher(PublisherConfig(
            trust_state_root=self.config.trust_state_root,
            evidence_root=self.evidence_root,
            authorized_worker_sid=SID_OTHER_WORKER,
            expected_deployment_digest=DEPLOY_1))
        self.assertTrue(other.handle("PUBLISH run-b").startswith("ANCHORED:"))

    def test_a_run_from_another_deployment_is_refused(self):
        self.publishable(self.identity("run-d2", deployment=DEPLOY_2))
        self.assertEqual(self.publisher.handle("PUBLISH run-d2"),
                         "REJECTED:deployment-mismatch")

    def test_an_identity_with_no_sealed_launch_intent_is_refused(self):
        # A V1 identity is readable history; it cannot satisfy Stage 6, because
        # its anchor would be untraceable to an authorized launch.
        self.publishable(self.identity("run-v1", launch=None,
                                       schema=RUN_IDENTITY_SCHEMA))
        self.assertEqual(self.publisher.handle("PUBLISH run-v1"),
                         "REJECTED:no-launch-binding")


class TestPublishableIsATrustedTransition(_PublisherCase):
    def test_a_request_before_publishable_is_refused(self):
        identity = self.identity("run-early")
        self.run_store.create(identity)          # created, NOT marked publishable
        reply = self.publisher.handle("PUBLISH run-early")
        self.assertTrue(reply.startswith("REJECTED:"), reply)
        store = AnchorStore(self.config.anchors_root, require_high=False)
        self.assertEqual(store.records(), [])

    def test_worker_completion_is_not_authorization(self):
        # There is no request, in any grammar this publisher accepts, that
        # moves a run to PUBLISHABLE.
        identity = self.identity("run-early")
        self.run_store.create(identity)
        for attempt in ("PUBLISH run-early", "PUBLISHABLE run-early",
                        "MARK run-early", "PUBLISH run-early PUBLISHABLE"):
            with self.subTest(attempt=attempt):
                self.publisher.handle(attempt)
        self.assertEqual(self.run_store.read("run-early").publication_state.value,
                         "NOT_PUBLISHABLE")


class TestTheEvidencePathIsResolvedByTheTrustPlane(_PublisherCase):
    def test_a_bundle_outside_the_evidence_root_is_refused(self):
        outside = _make_bundle(self.root / "elsewhere" / "run-x")
        self.publishable(self.identity("run-x", bundle=outside))
        self.assertEqual(self.publisher.handle("PUBLISH run-x"),
                         "REJECTED:bundle-outside-evidence-root")

    def test_a_sibling_prefix_of_the_evidence_root_does_not_count_as_inside(self):
        sibling = _make_bundle(Path(str(self.evidence_root) + "-old") / "run-y")
        self.publishable(self.identity("run-y", bundle=sibling))
        self.assertEqual(self.publisher.handle("PUBLISH run-y"),
                         "REJECTED:bundle-outside-evidence-root")

    def test_the_worker_cannot_name_the_bundle_at_all(self):
        # The grammar has nowhere to put a path, so there is nothing to filter.
        self.publishable(self.identity())
        for attempt in (f"PUBLISH run-1 {self.evidence_root}",
                        "PUBLISH run-1 --bundle=C:/x",
                        f"PUBLISH {self.evidence_root}"):
            with self.subTest(attempt=attempt):
                self.assertEqual(self.publisher.handle(attempt),
                                 "REJECTED:bad-request")


class TestTheBundleMustBeTheRecordedBundle(_PublisherCase):
    def test_a_tampered_bundle_is_refused(self):
        identity = self.publishable(self.identity())
        (Path(identity.bundle_path) / "SUMMARY.json").write_text(
            "{}", encoding="utf-8")
        reply = self.publisher.handle("PUBLISH run-1")
        self.assertTrue(reply.startswith("REJECTED:"), reply)

    def test_a_bundle_bound_to_another_head_is_refused(self):
        bundle = _make_bundle(self.evidence_root / "run-z", head="0" * 40)
        self.publishable(self.identity("run-z", bundle=bundle))
        reply = self.publisher.handle("PUBLISH run-z")
        self.assertTrue(reply.startswith("REJECTED:"), reply)


class TestThePipeWithholdsTheDangerousBit(unittest.TestCase):
    def test_the_worker_is_not_granted_the_create_pipe_instance_bit(self):
        # For a named pipe FILE_APPEND_DATA (0x4) IS FILE_CREATE_PIPE_INSTANCE.
        # Granting it would let the Worker become a server on the trusted name.
        self.assertFalse(WORKER_PIPE_ACCESS & 0x0004)

    def test_the_worker_gets_only_what_one_request_needs(self):
        self.assertEqual(WORKER_PIPE_ACCESS,
                         0x0001 | 0x0002 | 0x0080 | 0x00020000 | 0x00100000)

    def test_the_sddl_is_protected_and_names_the_worker_explicitly(self):
        sddl = worker_pipe_sddl(SID_WORKER, SID_SERVICE)
        self.assertIn("D:P", sddl)                      # no inheritance
        self.assertIn(SID_WORKER, sddl)
        self.assertNotIn("(A;;GA;;;WD)", sddl)          # never Everyone
        self.assertNotIn("GW", sddl)
        self.assertNotIn("FW", sddl)

    def test_the_pipe_is_single_instance_bounded_and_local(self):
        self.assertEqual(MAX_INSTANCES, 1)
        self.assertEqual(MAX_MESSAGE_BYTES, 512)
        self.assertEqual(PIPE_REJECT_REMOTE_CLIENTS, 0x00000008)


class TestTheServiceRefusesToStartUnconfigured(unittest.TestCase):
    def _write(self, path: Path, **overrides: object) -> Path:
        base = {
            "schema": SERVICE_CONFIG_SCHEMA, "service_name": "GnosisPub",
            "pipe_name": r"\\.\pipe\gnosis-publish", "service_sid": SID_SERVICE,
            "trust_state_root": r"C:\state", "evidence_root": r"C:\evidence",
            "authorized_worker_sid": SID_WORKER,
            "expected_deployment_digest": DEPLOY_1, "log_path": r"C:\state\log.txt",
        }
        base.update(overrides)
        path.write_text(json.dumps(base), encoding="utf-8")
        return path

    def test_a_complete_configuration_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = ServiceConfig.load(self._write(Path(tmp) / "c.json"))
            self.assertEqual(config.authorized_worker_sid, SID_WORKER)

    def test_every_authority_bearing_field_is_required(self):
        for field in ("authorized_worker_sid", "expected_deployment_digest",
                      "trust_state_root", "evidence_root", "service_sid",
                      "pipe_name", "service_name", "log_path"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                path = self._write(Path(tmp) / "c.json", **{field: ""})
                with self.assertRaises(AuthorityUnavailable):
                    ServiceConfig.load(path)

    def test_an_unknown_schema_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp) / "c.json", schema="something.else")
            with self.assertRaises(AuthorityUnavailable):
                ServiceConfig.load(path)

    def test_a_missing_configuration_is_a_startup_failure(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(AuthorityUnavailable):
            ServiceConfig.load(Path(tmp) / "absent.json")


class TestTheJudgementContextComesFromTheService(_PublisherCase):
    """Mutation testing found these two fields untested and shadowed.

    Changing them to read the run instead of the service changed nothing
    observable, because the earlier refusals already caught the mismatch. An
    untested field is one refactor away from being wrong in a way nothing
    notices, so it is asserted directly here.
    """

    def test_the_owner_and_deployment_expectations_are_the_services_own(self):
        identity = self.identity("run-x", sid=SID_OTHER_WORKER,
                                 deployment=DEPLOY_2, launch=LAUNCH_2, epoch=5)
        request = self.publisher.publication_request("run-x", identity)
        # From CONFIGURATION, not from the run being asked about:
        self.assertEqual(request.expected_owner_worker_sid, SID_WORKER)
        self.assertEqual(request.expected_deployment_digest, DEPLOY_1)
        self.assertNotEqual(request.expected_owner_worker_sid,
                            identity.owner_worker_sid)
        self.assertNotEqual(request.expected_deployment_digest,
                            identity.deployment_digest)

    def test_the_run_scoped_expectations_come_from_the_trusted_record(self):
        identity = self.identity("run-y", launch=LAUNCH_2, epoch=7)
        request = self.publisher.publication_request("run-y", identity)
        self.assertEqual(request.expected_epoch, 7)
        self.assertEqual(request.expected_launch_spec_digest, LAUNCH_2)
        self.assertEqual(request.expected_head_sha, identity.head_sha)
        self.assertEqual(request.expected_tree_identity, identity.tree_identity)
        self.assertEqual(request.expected_repository_id, identity.repository_id)


@unittest.skipUnless(sys.platform == "win32", "Windows-only")
class TestOpeningTheStoreDoesNotRewriteWhatTheIdentityMeasures(unittest.TestCase):
    """Found OS-real by the Stage 6 composition probe.

    `deployment_digest` binds the observed security descriptor of the anchor
    store's directory. `AnchorStore.__init__` used to apply a mandatory
    integrity label unconditionally, so merely OPENING the store rewrote the
    thing the deployment identity is a hash of: the probe watched the digest
    move between two observations of a machine nobody had reconfigured, and
    every publication then failed closed with `deployment-mismatch`.

    Under P2 the boundary is the NTFS DACL granted to the restricted service
    SID, not a label, so the relabel now happens only where it IS the boundary.
    """

    def test_a_non_high_store_leaves_the_directory_descriptor_alone(self):
        from gnosis.trust.deployment import observe_path_security
        with tempfile.TemporaryDirectory() as tmp:
            anchors = Path(tmp) / "anchors"
            anchors.mkdir()
            before = observe_path_security(anchors).to_dict()
            AnchorStore(anchors, require_high=False)
            after = observe_path_security(anchors).to_dict()
            self.assertEqual(before, after,
                             "opening the store rewrote the descriptor that "
                             "deployment_digest binds")

    def test_the_store_is_still_usable_afterwards(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AnchorStore(Path(tmp) / "anchors", require_high=False)
            initialise_durable_store(store)
            self.assertEqual(store.records(), [])
            self.assertTrue(store.verify_chain())


class TestRecoveryHappensBeforeTheEndpointExists(unittest.TestCase):
    """The order in `run_service` is a security property, so it is tested.

    A publisher that answered requests while its own committed state was
    unreconciled could report ALREADY_ANCHORED for a record that was never
    committed. A mutant that simply deleted the recovery call survived, because
    nothing ever called `run_service`.
    """

    def test_the_durable_store_is_settled_before_the_service_host_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            evidence.mkdir()
            config_path = root / "publisher.json"
            config_path.write_text(json.dumps({
                "schema": SERVICE_CONFIG_SCHEMA, "service_name": "GnosisNotAService",
                "pipe_name": r"\.\pipe\gnosis-never-served",
                "service_sid": SID_SERVICE,
                "trust_state_root": str(root / "state"),
                "evidence_root": str(evidence),
                "authorized_worker_sid": SID_WORKER,
                "expected_deployment_digest": DEPLOY_1,
                "log_path": str(root / "publisher.log"),
            }), encoding="utf-8")

            # This process is not a service, so the SCM dispatcher refuses and
            # `run_service` raises - AFTER recovery has already run.
            with self.assertRaises(OSError):
                run_service(config_path)

            watermark = read_watermark(root / "state" / "anchors")
            self.assertIsNotNone(watermark,
                                 "the endpoint would have opened over unsettled state")
            assert watermark is not None
            self.assertEqual(watermark.committed_seq, -1)


class TestTheExternalAnchorIsCompared(unittest.TestCase):
    """A manifest inside the bundle proves self-consistency, not tamper-evidence.

    The `expected_digest` comparison is what raises it to tamper-evidence
    against a value recorded OUTSIDE the bundle - and a mutant that removed the
    comparison survived, because nothing in this suite ever passed one.
    """

    def test_a_bundle_that_is_not_the_expected_one_fails_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _make_bundle(Path(tmp) / "b")
            honest = verify_bundle(bundle)
            self.assertTrue(honest.verified)
            assert honest.bundle_digest is not None

            self.assertTrue(verify_bundle(bundle, honest.bundle_digest).verified)
            wrong = verify_bundle(bundle, "0" * 64)
            self.assertFalse(wrong.verified)
            self.assertTrue(any("does not match the expected" in problem
                                for problem in wrong.problems), wrong.problems)

    def test_a_recomputed_manifest_still_fails_against_the_external_anchor(self):
        # The editor rewrites a file AND the manifest, so the bundle is
        # internally consistent again. Only the external value catches it.
        with tempfile.TemporaryDirectory() as tmp:
            bundle = _make_bundle(Path(tmp) / "b")
            recorded = verify_bundle(bundle).bundle_digest
            assert recorded is not None
            (bundle / "SUMMARY.json").write_text("{}", encoding="utf-8")
            write_bundle_manifest(bundle)
            self.assertTrue(verify_bundle(bundle).verified,
                            "the tampered bundle is internally consistent")
            self.assertFalse(verify_bundle(bundle, recorded).verified)


class TestTheFaultSeamIsNotReachableFromARequest(_PublisherCase):
    """Stage 4 left a deterministic crash seam in the publication protocol.

    It is a module-private global with no setter. These tests are the
    composition check the review asked for: that no request, however shaped,
    selects a fault point - and that no code outside the tests can install one.
    """

    def test_no_request_installs_a_fault_hook(self):
        from gnosis.trust import publication
        self.publishable(self.identity())
        attempts = [f"PUBLISH {point}" for point in
                    ("F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9")]
        attempts += ["PUBLISH run-1 F5", "PUBLISH run-1;F5", "FAULT F5",
                     "PUBLISH run-1 --fault=F5", "_FAULT_HOOK F5"]
        for attempt in attempts:
            with self.subTest(attempt=attempt):
                self.publisher.handle(attempt)
                self.assertIsNone(publication._FAULT_HOOK,
                                  "a request installed a fault hook")

    def test_the_seam_reads_no_environment_and_no_configuration(self):
        # A seam that could be armed by an environment variable would be armed
        # by the WORKER, whose profile environment is attacker-controlled.
        source = (Path(__file__).resolve().parents[1]
                  / "src" / "gnosis" / "trust" / "publication.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}:
                self.fail("the publication module reads the environment")

    def test_only_the_publication_module_assigns_the_hook(self):
        trust = Path(__file__).resolve().parents[1] / "src" / "gnosis" / "trust"
        writers = []
        for path in sorted(trust.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                # AnnAssign matters: the seam is DEFINED as `_FAULT_HOOK: Any
                # = None`, and a scan that only knew about plain assignment
                # would report zero writers and pass while seeing nothing.
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target]
                           if isinstance(node, (ast.AugAssign, ast.AnnAssign))
                           else [])
                for target in targets:
                    if isinstance(target, ast.Name) and target.id == "_FAULT_HOOK":
                        writers.append(path.name)
        self.assertEqual(sorted(set(writers)), ["publication.py"],
                         "only the module that owns the seam may assign it")


class TestSomeAttacksAreNotEvenExpressible(_PublisherCase):
    """The strongest answer to a whole class of attacks is a missing field.

    A grammar of `PUBLISH <run_id>` gives the Worker no way to name an epoch, a
    deployment, a launch digest or an expected bundle digest, so those values
    cannot be mismatched by a request - only by the trusted store, which the
    Worker cannot write. These tests record that as a property rather than
    leaving it as an assumption.
    """

    def test_the_worker_cannot_name_an_epoch_a_digest_or_a_deployment(self):
        self.publishable(self.identity())
        for attempt in ("PUBLISH run-1 epoch=9",
                        f"PUBLISH run-1 {DEPLOY_2}",
                        f"PUBLISH run-1 {LAUNCH_2}",
                        "PUBLISH run-1 --expected-digest=" + "0" * 64,
                        f"PUBLISH run-1 owner={SID_OTHER_WORKER}"):
            with self.subTest(attempt=attempt):
                self.assertEqual(self.publisher.handle(attempt),
                                 "REJECTED:bad-request")

    def test_the_anchor_carries_the_epoch_and_the_launch_through_the_identity(self):
        # Not repeated as anchor fields: bound once, in run_identity_digest.
        identity = self.publishable(self.identity("run-e", epoch=7))
        self.assertTrue(self.publisher.handle("PUBLISH run-e").startswith("ANCHORED:"))
        store = AnchorStore(self.config.anchors_root, require_high=False)
        record = store.lookup("run-e")
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.run_identity_digest, identity.digest())
        self.assertEqual(record.schema, "gnosis.anchor.v2")


if __name__ == "__main__":
    unittest.main()
