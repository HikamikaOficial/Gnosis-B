r"""F-33 Stage 2C-B1-R4A.1 — scoped worker-launch diagnostic surface.

R4A's acceptance FAILED narrowly: it forwarded the whole
`PipelineOutcome.report.problems_encountered` (a GENERAL governance/evidence channel
that can carry reviewer finding descriptions, provider-derived content, evidence-
failure messages, and unrelated exception strings) through `OperatorOutcome.problems`
into the operator record. R4A.1 replaces that broad surface with a MINIMAL, DEDICATED,
reason-scoped field `OperatorOutcome.worker_launch_diagnostic` that exposes ONLY the
single authoritative `WorkerLaunchFailed` attribution line (failing WinAPI call/stage +
native winerr) and NOTHING else.

These tests prove behaviorally (R4A.1 §11-§20):
  * reviewer / provider / evidence-failure content CANNOT enter the field;
  * arbitrary other pipeline errors CANNOT enter the field;
  * a co-present sensitive problem line is NOT copied (selection, not whole-list);
  * activation is reason/type-bound, not substring-driven;
  * the real WorkerLaunchFailed / Job-assign attribution IS surfaced (API + winerr);
  * governed BLOCKED / success semantics are unchanged;
  * the CLI record exposes ONLY the dedicated field, never `problems`.

Filesystem/mock only; no OS provisioning, no provider calls, no F-17 change.
"""
from __future__ import annotations

import json
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
from gnosis.director.composition import (
    _WORKER_LAUNCH_DIAG_MAX,
    OperatorOutcome,
    ProductionComposition,
    _worker_launch_diagnostic,
)
from gnosis.director.pipeline import PipelineOutcome

# Distinctive sentinels that must NEVER appear in the worker-launch diagnostic.
REVIEWER_SENTINEL = "REVIEWER_SECRET_SENTINEL_a1b2c3"
PROVIDER_SENTINEL = "PROVIDER_DERIVED_SENTINEL_d4e5f6"
EVIDENCE_SENTINEL = "SENSITIVE_EVIDENCE_SENTINEL_9x8y7z"
UNRELATED_SENTINEL = "UNRELATED_SENSITIVE_SENTINEL_q0w9e8"

CREATEPROC = "WorkerLaunchFailed: CreateProcessWithLogonW failed (winerr 1326)"
JOB_ASSIGN = "WorkerLaunchFailed: AssignProcessToJobObject failed (winerr 5)"


def _outcome(status: ReportStatus, reason_code: str,
             problems: tuple[str, ...]) -> PipelineOutcome:
    report = EngineerReport(task_id="TASK-1", run_id="RUN-1", status=status,
                            objective="qualification", problems_encountered=problems)
    return PipelineOutcome(brief_id="B1", task_id="TASK-1", status=status,
                           reason_code=reason_code, report=report)


def _finish(work: PipelineOutcome) -> OperatorOutcome:
    comp = ProductionComposition(pipeline=None, runner=None,  # type: ignore[arg-type]
                                 publication=None, repo_path=Path("."),  # type: ignore[arg-type]
                                 publisher_client=None)  # type: ignore[arg-type]
    return comp._finish(work)


class _FakeComposition:
    def __init__(self, outcome: OperatorOutcome) -> None:
        self._outcome = outcome

    def run_brief(self, brief: object) -> OperatorOutcome:
        return self._outcome


def _cli_record(outcome: OperatorOutcome) -> tuple[int, dict[str, object], str]:
    with mock.patch.object(cli, "build_operator_composition",
                           return_value=_FakeComposition(outcome)), \
            mock.patch.object(cli, "_load_brief", return_value=object()):
        code, record = cli._run(Path("cfg"), Path("brief"))
    return code, record, json.dumps(record)


# ---------------------------------------------------------------- §11-§14 NEGATIVES
class TestPrivacyNegatives(unittest.TestCase):
    def test_reviewer_blocked_does_not_leak(self) -> None:                    # §11
        # a review-block reaches the same non-COMPLETED branch; its problems carry a
        # reviewer finding.description. The dedicated field MUST stay None and the
        # serialized CLI record MUST NOT contain the reviewer sentinel.
        work = _outcome(ReportStatus.BLOCKED, "review_blocked",
                        (f"round 1: blocking security — {REVIEWER_SENTINEL}",))
        out = _finish(work)
        self.assertIsNone(out.worker_launch_diagnostic)
        _code, record, blob = _cli_record(out)
        self.assertIsNone(record["worker_launch_diagnostic"])
        self.assertNotIn(REVIEWER_SENTINEL, blob)

    def test_provider_derived_does_not_leak(self) -> None:                    # §12
        work = _outcome(ReportStatus.BLOCKED, "review_blocked",
                        (f"round 2: blocking correctness — {PROVIDER_SENTINEL}",))
        self.assertIsNone(_finish(work).worker_launch_diagnostic)

    def test_evidence_failure_does_not_leak(self) -> None:                    # §13
        work = _outcome(ReportStatus.BLOCKED, "evidence_failed",
                        (f"verify evidence failed [AssertionError]: {EVIDENCE_SENTINEL}",))
        out = _finish(work)
        self.assertIsNone(out.worker_launch_diagnostic)
        _code, _record, blob = _cli_record(out)
        self.assertNotIn(EVIDENCE_SENTINEL, blob)

    def test_other_pipeline_error_does_not_activate(self) -> None:            # §14
        work = _outcome(ReportStatus.BLOCKED, "pipeline_error:SomeOtherFailure",
                        (f"SomeOtherFailure: {UNRELATED_SENTINEL}",))
        self.assertIsNone(_finish(work).worker_launch_diagnostic)


# ---------------------------------------------------------------- §15-§18 POSITIVES / SELECTION
class TestWorkerPositivesAndSelection(unittest.TestCase):
    def test_createprocess_positive(self) -> None:                           # §15
        out = _finish(_outcome(ReportStatus.BLOCKED,
                               "pipeline_error:WorkerLaunchFailed", (CREATEPROC,)))
        self.assertEqual(out.worker_launch_diagnostic, CREATEPROC)
        self.assertEqual(out.work_status, "BLOCKED")
        assert out.worker_launch_diagnostic is not None
        self.assertIn("CreateProcessWithLogonW", out.worker_launch_diagnostic)
        self.assertIn("winerr 1326", out.worker_launch_diagnostic)

    def test_job_assign_positive(self) -> None:                              # §16
        out = _finish(_outcome(ReportStatus.BLOCKED,
                               "pipeline_error:WorkerLaunchFailed", (JOB_ASSIGN,)))
        self.assertEqual(out.worker_launch_diagnostic, JOB_ASSIGN)
        assert out.worker_launch_diagnostic is not None
        self.assertIn("AssignProcessToJobObject", out.worker_launch_diagnostic)
        self.assertIn("winerr 5", out.worker_launch_diagnostic)

    def test_worker_identity_mismatch_family(self) -> None:                  # family
        line = "WorkerIdentityMismatch: launched worker SID did not match expected"
        out = _finish(_outcome(ReportStatus.BLOCKED,
                               "pipeline_error:WorkerIdentityMismatch", (line,)))
        self.assertEqual(out.worker_launch_diagnostic, line)

    def test_multiple_problems_selects_only_launcher_line(self) -> None:     # §17
        work = _outcome(ReportStatus.BLOCKED, "pipeline_error:WorkerLaunchFailed",
                        (CREATEPROC, UNRELATED_SENTINEL))
        out = _finish(work)
        self.assertEqual(out.worker_launch_diagnostic, CREATEPROC)     # only #1
        _code, _record, blob = _cli_record(out)
        self.assertNotIn(UNRELATED_SENTINEL, blob)                     # never #2

    def test_multiple_problems_launcher_line_second(self) -> None:           # §17 order
        # even when the launcher line is NOT first, only it is selected (prefix-bound),
        # never the preceding sensitive line.
        work = _outcome(ReportStatus.BLOCKED, "pipeline_error:WorkerLaunchFailed",
                        (UNRELATED_SENTINEL, CREATEPROC))
        self.assertEqual(_finish(work).worker_launch_diagnostic, CREATEPROC)

    def test_false_positive_text_not_activated(self) -> None:                # §18
        # a NON-WorkerLaunchFailed reason whose problems merely CONTAIN launcher-like
        # text must not activate the field (reason/type-bound, not substring).
        work = _outcome(ReportStatus.BLOCKED, "pipeline_error:SomeOtherFailure",
                        (CREATEPROC,))
        self.assertIsNone(_finish(work).worker_launch_diagnostic)

    def test_wrong_prefix_within_family_yields_none(self) -> None:           # selection
        # reason says WorkerLaunchFailed but the only line carries a different type
        # prefix -> no line matches the authoritative type -> None (never a guess).
        work = _outcome(ReportStatus.BLOCKED, "pipeline_error:WorkerLaunchFailed",
                        ("WorkerIdentityMismatch: SID mismatch",))
        self.assertIsNone(_finish(work).worker_launch_diagnostic)


# ---------------------------------------------------------------- §8 / §19 / §20 / §23
class TestBoundingSuccessAndGovernance(unittest.TestCase):
    def test_overlong_line_rejected_not_truncated(self) -> None:             # §8
        long_line = "WorkerLaunchFailed: " + "A" * (_WORKER_LAUNCH_DIAG_MAX + 50)
        work = _outcome(ReportStatus.BLOCKED, "pipeline_error:WorkerLaunchFailed",
                        (long_line,))
        self.assertIsNone(_worker_launch_diagnostic(work))   # unavailable > misleading

    def test_boundary_line_exposed(self) -> None:                            # §8 edge
        line = "WorkerLaunchFailed: " + "A" * (_WORKER_LAUNCH_DIAG_MAX
                                               - len("WorkerLaunchFailed: "))
        work = _outcome(ReportStatus.BLOCKED, "pipeline_error:WorkerLaunchFailed",
                        (line,))
        self.assertEqual(_worker_launch_diagnostic(work), line)

    def test_success_path_no_diagnostic(self) -> None:                       # §19
        work = _outcome(ReportStatus.COMPLETED, "ok", ())
        self.assertIsNone(_worker_launch_diagnostic(work))

    def test_governed_blocked_semantics_preserved(self) -> None:             # §20
        out = _finish(_outcome(ReportStatus.BLOCKED,
                               "pipeline_error:WorkerLaunchFailed", (CREATEPROC,)))
        self.assertFalse(out.success)
        self.assertEqual(out.work_status, "BLOCKED")
        self.assertIsNone(out.publication_state)
        _code, record, _blob = _cli_record(out)
        self.assertEqual(record["success"], False)
        self.assertEqual(_code, cli.EXIT_WORK_FAILED)

    def test_cli_record_omits_general_problems(self) -> None:                # §23
        out = _finish(_outcome(ReportStatus.BLOCKED,
                               "pipeline_error:WorkerLaunchFailed", (CREATEPROC,)))
        _code, record, _blob = _cli_record(out)
        self.assertIn("worker_launch_diagnostic", record)
        self.assertNotIn("problems", record)              # broad channel GONE
        self.assertEqual(record["worker_launch_diagnostic"], CREATEPROC)


if __name__ == "__main__":
    unittest.main()
