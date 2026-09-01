"""F-33 publication seam — drives the REAL trust chain in-process via the client seam.

create_trusted_run -> authorize_publishable -> (PublisherClient) durable_publish ->
ANCHORED, using real local stores and a real sealed bundle. The in-process client
(InProcessPublisherClient) stands in for the F-17 Publisher SERVICE at component
level (ADR-0032 §16); the production route uses the pipe client.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trust_fixtures as tf

from gnosis.director.publication import (
    PublicationError,
    PublicationInputs,
    capture_publishable_bundle,
    observe_git_tree,
    publish_governed_run,
)
from gnosis.director.publisher_client import InProcessPublisherClient
from gnosis.trust.run_identity import PublicationState


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = tf.git_repo(self.root / "repo")
        self.trust_state_root = self.root / "trust_state"
        self.bundle_dir = self.trust_state_root / "evidence" / "run-1"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _inputs(self, *, run_id: str = "run-1", exit_code: int = 0,
                spec_run_id: str | None = None) -> PublicationInputs:
        tree = observe_git_tree(self.repo)
        return PublicationInputs(
            task_id="T-1", run_id=run_id, repository_id="gnosis", epoch=0,
            exit_code=exit_code, launched=tf.launched(),
            spec=tf.spec(spec_run_id or run_id), deployment=tf.v2_deployment(),
            tree=tree)

    def _client(self, inputs: PublicationInputs) -> InProcessPublisherClient:
        return InProcessPublisherClient(
            trust_state_root=self.trust_state_root,
            expected_deployment_digest=inputs.deployment.digest(),
            authorized_worker_sid=inputs.launched.observed_sid)

    def _publish(self, inputs: PublicationInputs) -> object:
        capture_publishable_bundle(self.bundle_dir, inputs.tree)
        return publish_governed_run(
            trust_state_root=self.trust_state_root, bundle_dir=self.bundle_dir,
            inputs=inputs, publisher_client=self._client(inputs))


class TestPublishesToAnchored(_Base):
    def test_full_chain_reaches_anchored(self) -> None:
        result = self._publish(self._inputs())
        self.assertTrue(result.anchored)
        self.assertIs(result.publication_state, PublicationState.ANCHORED)

    def test_idempotent_republish_stays_anchored(self) -> None:
        inputs = self._inputs()
        self._publish(inputs)
        again = self._publish(inputs)  # second publish must not double-anchor
        self.assertIs(again.publication_state, PublicationState.ANCHORED)


class TestFailClosed(_Base):
    def test_nonzero_exit_is_not_publishable(self) -> None:
        with self.assertRaises(PublicationError):
            self._publish(self._inputs(exit_code=13))

    def test_run_id_seal_mismatch_fails_closed(self) -> None:
        with self.assertRaises(PublicationError):
            self._publish(self._inputs(run_id="run-1", spec_run_id="run-OTHER"))

    def test_tampered_bundle_fails_closed(self) -> None:
        inputs = self._inputs()
        capture_publishable_bundle(self.bundle_dir, inputs.tree)
        (self.bundle_dir / "SUMMARY.json").write_text('{"tampered": true}',
                                                      encoding="utf-8")
        with self.assertRaises(PublicationError):
            publish_governed_run(
                trust_state_root=self.trust_state_root, bundle_dir=self.bundle_dir,
                inputs=inputs, publisher_client=self._client(inputs))

    def test_worker_data_cannot_reach_publication_authority(self) -> None:
        fields = set(PublicationInputs.__dataclass_fields__)
        for forbidden in ("result", "parsed_json", "final_message", "stdout",
                          "cassette", "worker_output"):
            self.assertNotIn(forbidden, fields)


if __name__ == "__main__":
    unittest.main()
