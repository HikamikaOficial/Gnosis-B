"""Manual Director transport: a human (or the Director, copy-pasting) drops
a JSON brief on disk; reports are written back as JSON plus rendered
Markdown."""
from __future__ import annotations

import json
from pathlib import Path

from ..contracts.director_brief import DirectorBrief
from ..contracts.engineer_report import EngineerReport
from .base import DirectorTransport


class ManualDirectorTransport(DirectorTransport):
    def __init__(self, inbox_path: Path, outbox_dir: Path):
        self.inbox_path = inbox_path
        self.outbox_dir = outbox_dir
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

    def receive_brief(self) -> DirectorBrief:
        if not self.inbox_path.exists():
            raise FileNotFoundError(f"No brief found at {self.inbox_path}")
        data = json.loads(self.inbox_path.read_text(encoding="utf-8"))
        return DirectorBrief.from_dict(data)

    def send_report(self, report: EngineerReport) -> None:
        json_path = self.outbox_dir / f"{report.task_id}.json"
        md_path = self.outbox_dir / f"{report.task_id}.md"
        json_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        md_path.write_text(report.to_markdown(), encoding="utf-8")
