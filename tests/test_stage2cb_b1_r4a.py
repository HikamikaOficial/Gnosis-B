r"""F-33 Stage 2C-B1-R4A — worker-launch failure attribution (retained under R4A.1).

The R3E.1 OS-real run reached the real Worker-launch frontier and BLOCKED with
`pipeline_error:WorkerLaunchFailed`. F-17 preserves the native failure IN the
exception message (e.g. "CreateProcessWithLogonW failed (winerr NNNN)"), and the
pipeline preserves it in `report.problems_encountered`. R4A.1 surfaces ONLY that
authoritative launcher line through the dedicated, reason-scoped
`OperatorOutcome.worker_launch_diagnostic` (NOT the general problems channel), so a
future OS-real run attributes the exact failing call (stage) + winerr — WITHOUT
changing F-17, the pipeline, or the governed BLOCKED decision.

This module keeps the R4A *attribution* coverage under the R4A.1 scoped field; the
privacy/selection negatives live in `test_stage2cb_b1_r4a1.py`.

Filesystem/mock only; no OS provisioning, no provider calls, no F-17 change.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO / "src",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from gnosis.contracts.engineer_report import EngineerReport, ReportStatus
from gnosis.director import cli
from gnosis.director.composition import OperatorOutcome, ProductionComposition
from gnosis.director.pipeline import PipelineOutcome

# A faithful F-17 WorkerLaunchFailed message shape (failing call + native winerr).
WINERR_MSG = "WorkerLaunchFailed: CreateProcessWithLogonW failed (winerr 1385)"


def _blocked_pipeline_outcome(problems: tuple[str, ...]) -> PipelineOutcome:
    report = EngineerReport(task_id="TASK-1", run_id="RUN-1",
                            status=ReportStatus.BLOCKED, objective="qualification",
                            problems_encountered=problems)
    return PipelineOutcome(brief_id="B1", task_id="TASK-1",
                           status=ReportStatus.BLOCKED,
                           reason_code="pipeline_error:WorkerLaunchFailed",
                           report=report)


def _finish(work: PipelineOutcome) -> OperatorOutcome:
    # the BLOCKED branch returns before touching runner/publication -> dummy args ok.
    comp = ProductionComposition(pipeline=None, runner=None,  # type: ignore[arg-type]
                                 publication=None, repo_path=Path("."),  # type: ignore[arg-type]
                                 publisher_client=None)  # type: ignore[arg-type]
    return comp._finish(work)


class TestAttribution(unittest.TestCase):
    def test_worker_failure_stage_and_winerr_surfaced(self) -> None:
        out = _finish(_blocked_pipeline_outcome((WINERR_MSG,)))
        self.assertEqual(out.worker_launch_diagnostic, WINERR_MSG)          # verbatim
        assert out.worker_launch_diagnostic is not None
        self.assertIn("CreateProcessWithLogonW", out.worker_launch_diagnostic)  # stage
        self.assertIn("winerr 1385", out.worker_launch_diagnostic)          # native error

    def test_only_launcher_line_selected_no_transform(self) -> None:
        # the launcher line passes through untouched (no truncation/rewrite that could
        # corrupt the stage or winerr); an UNRELATED problem line is NOT copied.
        probs = ("WorkerLaunchFailed: LogonUser failed (winerr 1326)",
                 "context: worker=GnosisWkrS2CB")
        out = _finish(_blocked_pipeline_outcome(probs))
        self.assertEqual(out.worker_launch_diagnostic, probs[0])
        assert out.worker_launch_diagnostic is not None
        self.assertNotIn("GnosisWkrS2CB", out.worker_launch_diagnostic)

    def test_governed_blocked_preserved(self) -> None:
        out = _finish(_blocked_pipeline_outcome((WINERR_MSG,)))
        self.assertFalse(out.success)                # NOT converted to success
        self.assertEqual(out.work_status, "BLOCKED")
        self.assertIsNone(out.publication_state)     # no publication attempted

    def test_no_matching_line_yields_none(self) -> None:
        self.assertIsNone(_finish(_blocked_pipeline_outcome(())).worker_launch_diagnostic)

    def test_secret_safety_scoped_launcher_line_only(self) -> None:
        # the diagnostic exposes only the audited launcher line; it carries no
        # credential material (the report's launcher message never contains it).
        out = _finish(_blocked_pipeline_outcome((WINERR_MSG,)))
        blob = (out.worker_launch_diagnostic or "").lower()
        for banned in ("password", "dpapi", "secret", "plaintext"):
            self.assertNotIn(banned, blob)


class _FakeComposition:
    def __init__(self, outcome: OperatorOutcome) -> None:
        self._outcome = outcome

    def run_brief(self, brief: object) -> OperatorOutcome:
        return self._outcome


class TestCliRecordSurfacesDiagnostic(unittest.TestCase):
    def test_run_record_includes_diagnostic_and_blocked_exit(self) -> None:
        outcome = OperatorOutcome(
            success=False, task_id="TASK-1", run_id=None, work_status="BLOCKED",
            publication_state=None,
            reason="governed work not COMPLETED (pipeline_error:WorkerLaunchFailed); "
                   "no publication attempted",
            worker_launch_diagnostic=WINERR_MSG)
        with mock.patch.object(cli, "build_operator_composition",
                               return_value=_FakeComposition(outcome)), \
                mock.patch.object(cli, "_load_brief", return_value=object()):
            code, record = cli._run(Path("cfg"), Path("brief"))
        self.assertEqual(record["worker_launch_diagnostic"], WINERR_MSG)
        self.assertIn("winerr 1385", record["worker_launch_diagnostic"])
        self.assertNotIn("problems", record)                 # no broad problems channel
        self.assertEqual(record["success"], False)
        self.assertEqual(record["work_status"], "BLOCKED")
        self.assertEqual(code, cli.EXIT_WORK_FAILED)   # governed BLOCKED exit unchanged


if __name__ == "__main__":
    unittest.main()
