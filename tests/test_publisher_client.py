"""F-33 Stage-2C-A — Publisher service client (PC1-PC10)."""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trust_fixtures as tf

from gnosis.director import publication as publication_mod
from gnosis.director.publication import (
    PublicationError,
    PublicationInputs,
    capture_publishable_bundle,
    observe_git_tree,
    publish_governed_run,
)
from gnosis.director.publisher_client import (
    MAX_RESPONSE_BYTES,
    PipePublisherClient,
    PublisherClientError,
    build_publish_request,
    parse_publish_response,
)


class TestRequestResponseBounds(unittest.TestCase):
    def test_pc2_bounded_publish_request(self) -> None:
        self.assertEqual(build_publish_request("run-1"), "PUBLISH run-1")

    def test_pc3_arbitrary_command_impossible(self) -> None:
        for bad in ("run 1; rm", "../etc", "PUBLISH x", "run\nid", "a" * 200):
            with self.subTest(bad=bad), self.assertRaises(PublisherClientError):
                build_publish_request(bad)

    def test_pc5_malformed_response_fails_closed(self) -> None:
        for bad in ("garbage", "OK", "ANCHORED:xyz", "PUBLISHED"):
            with self.subTest(bad=bad), self.assertRaises(PublisherClientError):
                parse_publish_response(bad)

    def test_pc_rejected_response_fails_closed(self) -> None:
        with self.assertRaises(PublisherClientError):
            parse_publish_response("REJECTED:owner-mismatch")

    def test_pc6_oversized_response_fails_closed(self) -> None:
        with self.assertRaises(PublisherClientError):
            parse_publish_response("ANCHORED:" + "a" * (MAX_RESPONSE_BYTES + 10))

    def test_valid_responses_parse(self) -> None:
        self.assertTrue(parse_publish_response("ANCHORED:0123456789ab:seq=3").anchored)
        self.assertTrue(parse_publish_response("ALREADY_ANCHORED:seq=7").anchored)


class TestPipeClientBinding(unittest.TestCase):
    def test_pc1_endpoint_from_trusted_config(self) -> None:
        client = PipePublisherClient(r"\\.\pipe\gnosis-2c")
        self.assertEqual(client.endpoint, r"\\.\pipe\gnosis-2c")

    def test_pc1_non_pipe_endpoint_rejected(self) -> None:
        with self.assertRaises(PublisherClientError):
            PipePublisherClient(r"C:\evil\path")

    def test_pc4_service_unavailable_fails_closed(self) -> None:
        # No service is running on this pipe → connect fails → fail closed.
        client = PipePublisherClient(r"\\.\pipe\gnosis-2c-nonexistent-probe",
                                     connect_timeout_ms=200)
        with self.assertRaises(PublisherClientError):
            client.publish("run-1")


class _SpyClient:
    """Returns an ANCHORED reply WITHOUT actually anchoring (a lying service)."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def publish(self, run_id: str):  # type: ignore[no-untyped-def]
        from gnosis.director.publisher_client import PublishResponse
        self.seen.append(run_id)
        return PublishResponse(raw="ANCHORED:deadbeefcafe:seq=1", anchored=True)


class TestPersistedAnchorAuthority(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = tf.git_repo(self.root / "repo")
        self.trust_state_root = self.root / "trust_state"
        self.bundle = self.trust_state_root / "evidence" / "run-1"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _inputs(self) -> PublicationInputs:
        tree = observe_git_tree(self.repo)
        return PublicationInputs(
            task_id="T-1", run_id="run-1", repository_id="gnosis", epoch=0,
            exit_code=0, launched=tf.launched(), spec=tf.spec("run-1"),
            deployment=tf.v2_deployment(), tree=tree)

    def test_pc8_pc10_response_text_is_not_authority(self) -> None:
        # A client that REPLIES ANCHORED but never anchors must NOT yield success:
        # publish_governed_run re-reads the persisted state and fails closed.
        inputs = self._inputs()
        capture_publishable_bundle(self.bundle, inputs.tree)
        with self.assertRaises(PublicationError):
            publish_governed_run(trust_state_root=self.trust_state_root,
                                 bundle_dir=self.bundle, inputs=inputs,
                                 publisher_client=_SpyClient())


class TestNoDirectDurablePublishBypass(unittest.TestCase):
    def test_pc9_publication_module_does_not_call_durable_publish(self) -> None:
        # The canonical publication path goes through the client, never a direct
        # durable_publish import/call in the composition publication module.
        tree = ast.parse(Path(publication_mod.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and \
                    "publication" in node.module:
                self.assertNotIn("durable_publish", {a.name for a in node.names})
            if isinstance(node, ast.Name):
                self.assertNotEqual(node.id, "durable_publish")


if __name__ == "__main__":
    unittest.main()
