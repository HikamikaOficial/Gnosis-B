r"""F-33 Stage 2C-B1-R4A — worker-launch failure attribution.

The R3E.1 OS-real run reached the real Worker-launch frontier and BLOCKED with
`pipeline_error:WorkerLaunchFailed`. F-17 preserves the native failure IN the
exception message (e.g. "CreateProcessWithLogonW failed (winerr NNNN)"), and the
pipeline preserves it in `report.problems_encountered`; but `composition._finish`
dropped it and the operator summary omitted it. R4A surfaces `problems` through
`OperatorOutcome` -> the operator record, so a future OS-real run attributes the exact
failing call (stage) + winerr — WITHOUT changing F-17, the pipeline, or the governed
BLOCKED decision.

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
        self.assertEqual(out.problems, (WINERR_MSG,))                 # verbatim
        self.assertIn("CreateProcessWithLogonW", out.problems[0])     # failing stage
        self.assertIn("winerr 1385", out.problems[0])                 # native error

    def test_problems_surfaced_verbatim_no_transform(self) -> None:
        # multiple problem lines pass through untouched (no truncation/rewrite that
        # could corrupt the stage or the winerr).
        probs = ("WorkerLaunchFailed: LogonUser failed (winerr 1326)",
                 "context: worker=GnosisWkrS2CB")
        self.assertEqual(_finish(_blocked_pipeline_outcome(probs)).problems, probs)

    def test_governed_blocked_preserved(self) -> None:
        out = _finish(_blocked_pipeline_outcome((WINERR_MSG,)))
        self.assertFalse(out.success)                # NOT converted to success
        self.assertEqual(out.work_status, "BLOCKED")
        self.assertIsNone(out.publication_state)     # no publication attempted

    def test_no_problems_defaults_empty(self) -> None:
        self.assertEqual(_finish(_blocked_pipeline_outcome(())).problems, ())

    def test_secret_safety_passthrough_only(self) -> None:
        # the diagnostic passes problems through verbatim and adds no new source; it
        # cannot introduce credential material the report did not already contain.
        out = _finish(_blocked_pipeline_outcome((WINERR_MSG,)))
        blob = " ".join(out.problems).lower()
        for banned in ("password", "dpapi", "secret", "plaintext"):
            self.assertNotIn(banned, blob)


class _FakeComposition:
    def __init__(self, outcome: OperatorOutcome) -> None:
        self._outcome = outcome

    def run_brief(self, brief: object) -> OperatorOutcome:
        return self._outcome


class TestCliRecordSurfacesProblems(unittest.TestCase):
    def test_run_record_includes_problems_and_blocked_exit(self) -> None:
        outcome = OperatorOutcome(
            success=False, task_id="TASK-1", run_id=None, work_status="BLOCKED",
            publication_state=None,
            reason="governed work not COMPLETED (pipeline_error:WorkerLaunchFailed); "
                   "no publication attempted",
            problems=(WINERR_MSG,))
        with mock.patch.object(cli, "build_operator_composition",
                               return_value=_FakeComposition(outcome)), \
                mock.patch.object(cli, "_load_brief", return_value=object()):
            code, record = cli._run(Path("cfg"), Path("brief"))
        self.assertEqual(record["problems"], [WINERR_MSG])
        self.assertIn("winerr 1385", record["problems"][0])
        self.assertEqual(record["success"], False)
        self.assertEqual(record["work_status"], "BLOCKED")
        self.assertEqual(code, cli.EXIT_WORK_FAILED)   # governed BLOCKED exit unchanged


if __name__ == "__main__":
    unittest.main()
