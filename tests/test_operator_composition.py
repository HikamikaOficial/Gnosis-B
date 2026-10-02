"""F-33 Stage-2B.2 — ProductionComposition operator-success invariant.

operator success = governed work COMPLETED **and** publication ANCHORED (§14).
Drives the wrapper with a controlled work outcome and the REAL publication seam
(real trust chain -> ANCHORED), so the composite guarantee is proven both ways.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trust_fixtures as tf

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.contracts.engineer_report import ReportStatus
from gnosis.director.composition import (
    OperatorOutcome,
    ProductionComposition,
    PublicationCompositionInputs,
)
from gnosis.director.publication import observe_git_tree
from gnosis.director.publisher_client import InProcessPublisherClient


def _brief() -> DirectorBrief:
    return DirectorBrief("B-1", "task", "implement", BriefSource.MANUAL)


@dataclass
class _Report:
    # minimal stand-in for EngineerReport (R4A surfaces problems_encountered).
    problems_encountered: tuple[str, ...] = ()


@dataclass
class _Work:
    status: ReportStatus
    task_id: str = "T-1"
    reason_code: str = "ok"
    report: _Report = field(default_factory=_Report)


class _FakePipeline:
    def __init__(self, status: ReportStatus, runner: _RecordedRunner, repo: Path) -> None:
        self._status = status
        self._runner = runner
        self.calls = 0
        self.repo = repo
        self.verifier = object()
        self.inbox = SimpleNamespace(layout=SimpleNamespace(outbox=repo.parent))

    def _exec_root(self, task_id: str) -> Path:
        return self.repo

    def run_brief(self, brief: object) -> _Work:
        self.calls += 1
        self._runner.record_launch()
        return _Work(self._status)


class _RecordedRunner:
    """Stands in for the TrustedExecutionRunner's recorded launch artefacts."""

    def __init__(self, *, run_id: str | None = "run-1") -> None:
        self._run_id = run_id
        self.record_launch()

    def clear_launch(self) -> None:
        self.last_run_id = None
        self.last_spec = None
        self.last_launched = None

    def record_launch(self) -> None:
        run_id = self._run_id
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
        # This suite tests composition + real publication, not OS observation.
        # The separately tested proof capture supplies a synthetic sealed bundle.
        def proof(**kwargs):
            tree = observe_git_tree(kwargs["source"])
            tf.capture_publishable_bundle(kwargs["bundle_dir"], tree)
            return tree
        capture = patch("gnosis.director.composition.capture_task_proof", side_effect=proof)
        capture.start()
        self.addCleanup(capture.stop)
        runner = _RecordedRunner(run_id=run_id)
        return ProductionComposition(
            pipeline=_FakePipeline(status, runner, repo or self.repo), runner=runner,
            publication=self.pub, repo_path=repo or self.repo,
            publisher_client=self._client())


class TestOperatorSuccessInvariant(_Base):
    def test_work_completed_and_anchored_is_success(self) -> None:
        out = self._comp(ReportStatus.COMPLETED).run_brief(_brief())
        self.assertTrue(out.success)
        self.assertEqual(out.publication_state, "ANCHORED")

    def test_failed_work_is_not_success_and_not_published(self) -> None:
        out = self._comp(ReportStatus.PARTIAL).run_brief(_brief())
        self.assertFalse(out.success)
        self.assertIsNone(out.publication_state)  # P1: no publication attempted
        self.assertIn("not COMPLETED", out.reason)

    def test_escalation_work_is_not_published(self) -> None:
        out = self._comp(ReportStatus.ESCALATION_REQUIRED).run_brief(_brief())
        self.assertFalse(out.success)
        self.assertIsNone(out.publication_state)

    def test_no_recorded_launch_fails_closed(self) -> None:
        # Work "COMPLETED" but the trusted runner recorded no launch: fail closed.
        out = self._comp(ReportStatus.COMPLETED, run_id=None).run_brief(_brief())
        self.assertFalse(out.success)
        self.assertIn("no trusted launch", out.reason)

    def test_publication_failure_is_not_success(self) -> None:
        # A second composition sharing the SAME trust_state_root + run_id but a
        # tampered bundle: publish fails -> operator failure (P3/P4).
        first = self._comp(ReportStatus.COMPLETED).run_brief(_brief())
        self.assertTrue(first.success)
        # A fresh run whose repo cannot be observed → publication fails closed.
        bad = self._comp(ReportStatus.COMPLETED, run_id="run-2",
                         repo=self.root / "no-such-repo")
        out = bad.run_brief(_brief())
        self.assertFalse(out.success)


class TestOutcomeShape(_Base):
    def test_outcome_is_operator_outcome(self) -> None:
        out = self._comp(ReportStatus.COMPLETED).run_brief(_brief())
        self.assertIsInstance(out, OperatorOutcome)
        self.assertEqual(out.task_id, "T-1")
        self.assertEqual(out.run_id, "run-1")


if __name__ == "__main__":
    unittest.main()
