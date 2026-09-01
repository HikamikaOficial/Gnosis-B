"""F-33 Stage-2B.2 publication seam — drives the REAL trust chain in-process.

create_trusted_run -> authorize_publishable -> durable_publish -> ANCHORED, using
real local stores and a real sealed bundle. The Director-side identity inputs
(deployment/launched/spec) are constructed via the qualified fixture pattern; the
trust code exercised is the real thing.
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
from gnosis.trust.run_identity import PublicationState


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = tf.git_repo(self.root / "repo")
        self.trust_state_root = self.root / "trust_state"
        self.evidence_root = self.root / "evidence"
        self.bundle_dir = self.evidence_root / "run-1"

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

    def _capture(self, inputs: PublicationInputs) -> Path:
        return capture_publishable_bundle(self.bundle_dir, inputs.tree)


class TestPublishesToAnchored(_Base):
    def test_full_chain_reaches_anchored(self) -> None:
        inputs = self._inputs()
        self._capture(inputs)
        result = publish_governed_run(
            trust_state_root=self.trust_state_root, evidence_root=self.evidence_root,
            bundle_dir=self.bundle_dir, inputs=inputs)
        self.assertTrue(result.anchored)
        self.assertIs(result.publication_state, PublicationState.ANCHORED)

    def test_idempotent_republish_stays_anchored(self) -> None:
        inputs = self._inputs()
        self._capture(inputs)
        publish_governed_run(trust_state_root=self.trust_state_root,
                             evidence_root=self.evidence_root,
                             bundle_dir=self.bundle_dir, inputs=inputs)
        # A second publish of the same run must not fabricate a second anchor.
        again = publish_governed_run(trust_state_root=self.trust_state_root,
                                     evidence_root=self.evidence_root,
                                     bundle_dir=self.bundle_dir, inputs=inputs)
        self.assertIs(again.publication_state, PublicationState.ANCHORED)


class TestFailClosed(_Base):
    def test_nonzero_exit_is_not_publishable(self) -> None:
        inputs = self._inputs(exit_code=13)
        self._capture(inputs)
        with self.assertRaises(PublicationError):
            publish_governed_run(trust_state_root=self.trust_state_root,
                                 evidence_root=self.evidence_root,
                                 bundle_dir=self.bundle_dir, inputs=inputs)

    def test_run_id_seal_mismatch_fails_closed(self) -> None:
        # The executed LaunchSpec was sealed for a different run than the plan.
        inputs = self._inputs(run_id="run-1", spec_run_id="run-OTHER")
        self._capture(inputs)
        with self.assertRaises(PublicationError):
            publish_governed_run(trust_state_root=self.trust_state_root,
                                 evidence_root=self.evidence_root,
                                 bundle_dir=self.bundle_dir, inputs=inputs)

    def test_tampered_bundle_fails_closed(self) -> None:
        inputs = self._inputs()
        self._capture(inputs)
        # Corrupt the sealed bundle after capture: verify_bundle must reject it.
        (self.bundle_dir / "SUMMARY.json").write_text('{"tampered": true}',
                                                      encoding="utf-8")
        with self.assertRaises(PublicationError):
            publish_governed_run(trust_state_root=self.trust_state_root,
                                 evidence_root=self.evidence_root,
                                 bundle_dir=self.bundle_dir, inputs=inputs)

    def test_worker_data_cannot_reach_publication_authority(self) -> None:
        # P6 (structural): the publication seam takes only trusted inputs; there
        # is no worker-result / parsed_json / final_message field anywhere in it.
        fields = set(PublicationInputs.__dataclass_fields__)
        for forbidden in ("result", "parsed_json", "final_message", "stdout",
                          "cassette", "worker_output"):
            self.assertNotIn(forbidden, fields)


if __name__ == "__main__":
    unittest.main()
