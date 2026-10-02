import json
from unittest.mock import patch

import pytest

from gnosis.director import work_queue
from gnosis.kernel.claims import StaleClaimError
from gnosis.kernel.lease import StaleLeaseError
from tests.test_work_queue import _brief, _QueueTestCase


class TestQueueCommitFencing(_QueueTestCase):
    def test_takeover_after_record_read_cannot_stamp_completion_intent(self):
        self.queue.enqueue(_brief("brief"))
        work = self.queue.claim("old")
        path = self.queue.root / "running" / "brief.json"
        before = path.read_bytes()
        original = work_queue._read

        def read_and_replace(target):
            record = original(target)
            if target == path:
                self.authority.release(work.grant)
                self.authority.acquire("brief", "new")
            return record

        with (patch.object(work_queue, "_read", side_effect=read_and_replace),
              pytest.raises((StaleClaimError, StaleLeaseError))):
            self.queue.complete(work, "COMPLETED")
        assert path.read_bytes() == before
        assert "pending_transition" not in json.loads(path.read_text())
        assert self.queue.done_ids() == []
