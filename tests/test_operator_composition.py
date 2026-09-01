"""F-33 Stage-2B.2 — ProductionComposition operator-success invariant.

operator success = governed work COMPLETED **and** publication ANCHORED (§14).
Drives the wrapper with a controlled work outcome and the REAL publication seam
(real trust chain -> ANCHORED), so the composite guarantee is proven both ways.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trust_fixtures as tf

from gnosis.contracts.engineer_report import ReportStatus
from gnosis.director.composition import (
    OperatorOutcome,
    ProductionComposition,
    PublicationCompositionInputs,
)
from gnosis.director.publisher_client import InProcessPublisherClient


@dataclass
class _Work:
    status: ReportStatus
    task_id: str = "T-1"
    reason_code: str = "ok"


class _FakePipeline:
    def __init__(self, status: ReportStatus) -> None:
        self._status = status
        self.calls = 0

    def run_brief(self, brief: object) -> _Work:
        self.calls += 1
        return _Work(self._status)


class _RecordedRunner:
    """Stands in for the TrustedExecutionRunner's recorded launch artefacts."""

    def __init__(self, *, run_id: str | None = "run-1") -> None:
        self.last_run_id = run_id
        self.last_spec = tf.spec(run_id) if run_id else None
        self.last_launched = tf.launched() if run_id else None


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = tf.git_repo(self.root / "repo")
        self.pub = PublicationCompositionInputs(
            trust_state_root=self.root / "trust_state",
            evidence_root=self.root / "trust_state" / "evidence",
            deployment=tf.v2_deployment(), repository_id="gnosis",
            pipe_name=r"\\.\pipe\gnosis-test", epoch=0)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _client(self) -> InProcessPublisherClient:
        return InProcessPublisherClient(
            trust_state_root=self.pub.trust_state_root,
            expected_deployment_digest=self.pub.deployment.digest(),
            authorized_worker_sid=tf.SID_OBSERVED)

    def _comp(self, status: ReportStatus, *, run_id: str | None = "run-1",
              repo: Path | None = None) -> ProductionComposition:
        return ProductionComposition(
            pipeline=_FakePipeline(status), runner=_RecordedRunner(run_id=run_id),
            publication=self.pub, repo_path=repo or self.repo,
            publisher_client=self._client())


class TestOperatorSuccessInvariant(_Base):
    def test_work_completed_and_anchored_is_success(self) -> None:
        out = self._comp(ReportStatus.COMPLETED).run_brief(object())
        self.assertTrue(out.success)
        self.assertEqual(out.publication_state, "ANCHORED")

    def test_failed_work_is_not_success_and_not_published(self) -> None:
        out = self._comp(ReportStatus.PARTIAL).run_brief(object())
        self.assertFalse(out.success)
        self.assertIsNone(out.publication_state)  # P1: no publication attempted
        self.assertIn("not COMPLETED", out.reason)

    def test_escalation_work_is_not_published(self) -> None:
        out = self._comp(ReportStatus.ESCALATION_REQUIRED).run_brief(object())
        self.assertFalse(out.success)
        self.assertIsNone(out.publication_state)

    def test_no_recorded_launch_fails_closed(self) -> None:
        # Work "COMPLETED" but the trusted runner recorded no launch: fail closed.
        out = self._comp(ReportStatus.COMPLETED, run_id=None).run_brief(object())
        self.assertFalse(out.success)
        self.assertIn("no trusted launch", out.reason)

    def test_publication_failure_is_not_success(self) -> None:
        # A second composition sharing the SAME trust_state_root + run_id but a
        # tampered bundle: publish fails -> operator failure (P3/P4).
        first = self._comp(ReportStatus.COMPLETED).run_brief(object())
        self.assertTrue(first.success)
        # A fresh run whose repo cannot be observed → publication fails closed.
        bad = self._comp(ReportStatus.COMPLETED, run_id="run-2",
                         repo=self.root / "no-such-repo")
        out = bad.run_brief(object())
        self.assertFalse(out.success)


class TestOutcomeShape(_Base):
    def test_outcome_is_operator_outcome(self) -> None:
        out = self._comp(ReportStatus.COMPLETED).run_brief(object())
        self.assertIsInstance(out, OperatorOutcome)
        self.assertEqual(out.task_id, "T-1")
        self.assertEqual(out.run_id, "run-1")


if __name__ == "__main__":
    unittest.main()
