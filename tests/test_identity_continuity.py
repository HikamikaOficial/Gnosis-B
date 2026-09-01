"""F-33 Stage-2C-A — RunIdentity + deployment-identity continuity (I1-I5)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trust_fixtures as tf

from gnosis.director.composition import (
    AttributionInputs,
    CompositionError,
    OperatorInputs,
    ProductionCompositionConfig,
    PublicationCompositionInputs,
    build_production_deployment,
)
from gnosis.director.execution import ExecutionMode
from gnosis.director.publication import (
    PublicationError,
    PublicationInputs,
    capture_publishable_bundle,
    observe_git_tree,
    publish_governed_run,
)
from gnosis.director.publisher_client import InProcessPublisherClient, PublishResponse
from gnosis.kernel.engine import AGENT_RUN_INTERVENTION_POINT
from gnosis.kernel.policy import InterventionPoint, PolicyEngine, RuleOutcome, Verdict
from gnosis.kernel.verification import CommandVerifier
from gnosis.trust.worker_launcher import WorkerAccount


def _permissive() -> PolicyEngine:
    return PolicyEngine([InterventionPoint(
        name=AGENT_RUN_INTERVENTION_POINT, declared_tools=frozenset({"claude_cli"}),
        rules=(("r", lambda s: RuleOutcome(Verdict.ALLOW, "ok")),),
        requires_intent=True)])


class _Reviewer:
    @property
    def binary(self) -> str:
        return "claude-review"

    def run(self, *a: object, **k: object) -> object:  # pragma: no cover
        raise AssertionError("not invoked")


class _CapturingClient:
    """Records the run_id then delegates to the real in-process publish."""

    def __init__(self, inner: InProcessPublisherClient) -> None:
        self._inner = inner
        self.seen: list[str] = []

    def publish(self, run_id: str) -> PublishResponse:
        self.seen.append(run_id)
        return self._inner.publish(run_id)


class TestRunIdentityContinuity(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = tf.git_repo(self.root / "repo")
        self.tsr = self.root / "trust_state"
        self.bundle = self.tsr / "evidence" / "run-1"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _inputs(self, *, run_id: str = "run-1", spec_run_id: str | None = None,
                deployment: object | None = None) -> PublicationInputs:
        return PublicationInputs(
            task_id="T", run_id=run_id, repository_id="gnosis", epoch=0,
            exit_code=0, launched=tf.launched(), spec=tf.spec(spec_run_id or run_id),
            deployment=deployment or tf.v2_deployment(),
            tree=observe_git_tree(self.repo))

    def _client(self, inputs: PublicationInputs, *, digest: str | None = None
                ) -> InProcessPublisherClient:
        return InProcessPublisherClient(
            trust_state_root=self.tsr,
            expected_deployment_digest=digest or inputs.deployment.digest(),
            authorized_worker_sid=inputs.launched.observed_sid)

    def test_i1_same_run_id_reaches_publication(self) -> None:
        inputs = self._inputs()
        capture_publishable_bundle(self.bundle, inputs.tree)
        spy = _CapturingClient(self._client(inputs))
        publish_governed_run(trust_state_root=self.tsr, bundle_dir=self.bundle,
                             inputs=inputs, publisher_client=spy)
        self.assertEqual(spy.seen, ["run-1"])

    def test_i2_mismatched_run_id_fails(self) -> None:
        inputs = self._inputs(run_id="run-1", spec_run_id="run-OTHER")
        capture_publishable_bundle(self.bundle, inputs.tree)
        with self.assertRaises(PublicationError):
            publish_governed_run(trust_state_root=self.tsr, bundle_dir=self.bundle,
                                 inputs=inputs, publisher_client=self._client(inputs))

    def test_i3_deployment_digest_mismatch_fails(self) -> None:
        inputs = self._inputs()
        capture_publishable_bundle(self.bundle, inputs.tree)
        bad = self._client(inputs, digest="e" * 64)  # publisher expects a different deployment
        with self.assertRaises(PublicationError):
            publish_governed_run(trust_state_root=self.tsr, bundle_dir=self.bundle,
                                 inputs=inputs, publisher_client=bad)

    def test_i5_worker_output_cannot_replace_identity(self) -> None:
        fields = set(PublicationInputs.__dataclass_fields__)
        for forbidden in ("result", "parsed_json", "final_message", "worker_output"):
            self.assertNotIn(forbidden, fields)


class TestDeploymentRuntimeCrossBinding(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = tf.git_repo(self.root / "repo")
        (self.root / "blob.dpapi").write_bytes(b"x")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _config(self) -> ProductionCompositionConfig:
        from gnosis.director.composition import TrustedDeploymentInputs
        dep = TrustedDeploymentInputs(
            runtime_executable=Path(sys.executable),
            worker_account=WorkerAccount("W", ".", "S-1-5-21-x-1", "Medium"),
            credential_blob_path=self.root / "blob.dpapi",
            launch_root=self.root / "launch")
        return ProductionCompositionConfig(
            deployment=dep,
            attribution=AttributionInputs("reviewer@team", "agent://dir"),
            operator=OperatorInputs(director_root=self.root / "dir", repo_path=self.repo),
            verifier=CommandVerifier("c", [sys.executable, "-c", "raise SystemExit(0)"]),
            review_runner=_Reviewer(), policy=_permissive(),
            execution_mode=ExecutionMode.DETERMINISTIC)

    def _publication(self, deployment: object) -> PublicationCompositionInputs:
        return PublicationCompositionInputs(
            trust_state_root=self.root / "ts", evidence_root=self.root / "ts" / "evidence",
            deployment=deployment, repository_id="gnosis",
            pipe_name=r"\\.\pipe\gnosis-2c")

    def test_i4_runtime_deployment_mismatch_fails_closed(self) -> None:
        # publication deployment's runtime digest != the execution runtime digest.
        with self.assertRaises(CompositionError):
            build_production_deployment(self._config(),
                                        self._publication(tf.v2_deployment()))

    def test_i4_matched_runtime_builds(self) -> None:
        comp = build_production_deployment(
            self._config(),
            self._publication(tf.v2_deployment_for_runtime(Path(sys.executable))))
        self.assertEqual(type(comp).__name__, "ProductionComposition")


if __name__ == "__main__":
    unittest.main()
