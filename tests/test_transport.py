import json
import tempfile
import unittest
from pathlib import Path

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.contracts.engineer_report import EngineerReport, ReportStatus
from gnosis.transport.manual_transport import ManualDirectorTransport
from gnosis.transport.mcp_transport import McpDirectorTransport


class TestManualDirectorTransport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_receive_brief_missing_file_raises(self):
        transport = ManualDirectorTransport(self.root / "inbox.json", self.root / "outbox")
        with self.assertRaises(FileNotFoundError):
            transport.receive_brief()

    def test_receive_brief_round_trip(self):
        brief = DirectorBrief(
            brief_id="BRIEF-1", title="M0", mission="Bootstrap.", source=BriefSource.MANUAL,
        )
        inbox = self.root / "inbox.json"
        inbox.write_text(json.dumps(brief.to_dict()), encoding="utf-8")
        transport = ManualDirectorTransport(inbox, self.root / "outbox")
        received = transport.receive_brief()
        self.assertEqual(received, brief)

    def test_send_report_writes_json_and_markdown(self):
        transport = ManualDirectorTransport(self.root / "inbox.json", self.root / "outbox")
        report = EngineerReport(
            task_id="TASK-1", run_id="RUN-1", status=ReportStatus.COMPLETED, objective="X",
        )
        transport.send_report(report)
        json_path = self.root / "outbox" / "TASK-1.json"
        md_path = self.root / "outbox" / "TASK-1.md"
        self.assertTrue(json_path.exists())
        self.assertTrue(md_path.exists())
        self.assertEqual(EngineerReport.from_dict(json.loads(json_path.read_text())), report)


class TestMcpDirectorTransportPlaceholder(unittest.TestCase):
    def test_raises_not_implemented(self):
        transport = McpDirectorTransport(endpoint="mcp://future")
        with self.assertRaises(NotImplementedError):
            transport.receive_brief()
        report = EngineerReport(task_id="T", run_id="R", status=ReportStatus.COMPLETED, objective="x")
        with self.assertRaises(NotImplementedError):
            transport.send_report(report)


if __name__ == "__main__":
    unittest.main()
