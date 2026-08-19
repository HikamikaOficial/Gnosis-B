import unittest

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.contracts.engineer_report import EngineerReport, ReportStatus


class TestDirectorBrief(unittest.TestCase):
    def _make(self, **overrides):
        defaults = dict(
            brief_id="BRIEF-1", title="M0 Bootstrap", mission="Bootstrap the kernel.",
            source=BriefSource.MANUAL,
        )
        defaults.update(overrides)
        return DirectorBrief(**defaults)

    def test_round_trip(self):
        brief = self._make(constraints=("no API billing",), acceptance_criteria=("tests pass",))
        restored = DirectorBrief.from_dict(brief.to_dict())
        self.assertEqual(brief, restored)

    def test_rejects_empty_mission(self):
        with self.assertRaises(ValueError):
            self._make(mission="   ")

    def test_rejects_non_enum_source(self):
        with self.assertRaises(ValueError):
            DirectorBrief(brief_id="X", title="X", mission="X", source="manual")


class TestEngineerReport(unittest.TestCase):
    def test_round_trip(self):
        report = EngineerReport(
            task_id="TASK-1", run_id="RUN-1", status=ReportStatus.COMPLETED,
            objective="Do the thing.", work_completed=("Did it.",),
        )
        restored = EngineerReport.from_dict(report.to_dict())
        self.assertEqual(report, restored)

    def test_markdown_contains_sections(self):
        report = EngineerReport(
            task_id="TASK-1", run_id="RUN-1", status=ReportStatus.BLOCKED, objective="X",
        )
        md = report.to_markdown()
        for heading in ("## Status", "## Objective", "## Files changed", "## Recommended next step"):
            self.assertIn(heading, md)

    def test_rejects_empty_objective(self):
        with self.assertRaises(ValueError):
            EngineerReport(task_id="T", run_id="R", status=ReportStatus.COMPLETED, objective="")


if __name__ == "__main__":
    unittest.main()
