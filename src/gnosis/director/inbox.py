"""Durable DirectorBrief inbox/outbox convention.

    <root>/
      inbox/         new DirectorBrief JSON files land here
      processed/     briefs already claimed, moved here keyed by brief_id;
                      presence of processed/<brief_id>.json *is* the
                      durable "already ingested" marker (no separate index
                      needed, and it is resume-safe: a crash before this
                      move leaves the file in inbox/ to be retried, a
                      crash after leaves unambiguous evidence it was seen)
      rejected/      malformed brief files, or duplicate submissions of an
                      already-processed brief_id, moved here for audit
                      rather than silently dropped
      outbox/        EngineerReport JSON + rendered Markdown
      escalations/   EngineerReports whose status is ESCALATION_REQUIRED,
                      duplicated here so a Director sweep only needs to
                      watch one directory

The move from inbox/ to processed/ (via os.replace, atomic on the same
volume) is what makes ingestion idempotent: claim() checks processed/
first, so re-dropping the same brief_id is rejected rather than
re-executed.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..contracts.director_brief import DirectorBrief


class DirectorInboxLayout:
    def __init__(self, root: Path):
        self.root = root
        self.inbox = root / "inbox"
        self.processed = root / "processed"
        self.rejected = root / "rejected"
        self.outbox = root / "outbox"
        self.escalations = root / "escalations"
        for d in (self.inbox, self.processed, self.rejected, self.outbox, self.escalations):
            d.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class ClaimResult:
    brief: DirectorBrief | None
    accepted: bool
    reason: str


class DirectorInbox:
    def __init__(self, root: Path):
        self.layout = DirectorInboxLayout(root)

    def list_pending(self) -> list[Path]:
        return sorted(self.layout.inbox.glob("*.json"))

    def is_processed(self, brief_id: str) -> bool:
        return (self.layout.processed / f"{brief_id}.json").exists()

    def claim(self, path: Path) -> ClaimResult:
        """Validate and atomically move one inbox file. Never leaves the
        file in inbox/ on return, it always ends up in processed/ or
        rejected/, so a crashed-and-restarted sweep cannot see it twice
        and disagree with itself about whether it was handled."""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            brief = DirectorBrief.from_dict(raw)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            self._move(path, self.layout.rejected / f"malformed-{path.name}")
            return ClaimResult(brief=None, accepted=False, reason=f"malformed: {exc}")

        if self.is_processed(brief.brief_id):
            self._move(path, self.layout.rejected / f"duplicate-{uuid.uuid4().hex[:8]}-{path.name}")
            return ClaimResult(brief=None, accepted=False, reason="duplicate brief_id")

        destination = self.layout.processed / f"{brief.brief_id}.json"
        try:
            self._move(path, destination, exclusive=True)
        except FileExistsError:
            # Lost a race with another claimant for the same brief_id.
            self._move(path, self.layout.rejected / f"duplicate-{uuid.uuid4().hex[:8]}-{path.name}")
            return ClaimResult(brief=None, accepted=False, reason="duplicate brief_id (race)")

        return ClaimResult(brief=brief, accepted=True, reason="ok")

    def _move(self, src: Path, dst: Path, exclusive: bool = False) -> None:
        # Best-effort exclusive check: os.replace() itself always
        # succeeds by overwriting, it is not a true atomic
        # create-if-absent. That is acceptable under M1's explicit
        # single-writer orchestrator model (no parallel scheduler yet);
        # if a second orchestrator process is ever introduced, this
        # needs os.link()+os.remove() (fails atomically if dst exists)
        # instead of exists()-then-replace().
        dst.parent.mkdir(parents=True, exist_ok=True)
        if exclusive and dst.exists():
            raise FileExistsError(str(dst))
        os.replace(src, dst)
