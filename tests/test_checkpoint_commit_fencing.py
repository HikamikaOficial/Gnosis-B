from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch

import pytest

from gnosis.director import checkpoint
from gnosis.director.checkpoint import PipelineCheckpointStore
from gnosis.kernel.claims import ClaimStore, StaleClaimError, WorkAuthority
from gnosis.kernel.execution_scope import ExecutionCancelled, ExecutionScope
from gnosis.kernel.lease import LeaseStore, StaleLeaseError
from gnosis.runner.claude_cli_runner import CancellationToken
from tests.test_phase_checkpoint import _record


def authority_at(root: Path, clock) -> WorkAuthority:
    return WorkAuthority(ClaimStore(root / "claims", clock=clock),
        LeaseStore(root / "leases", clock=clock), clock=clock,
        default_ttl_s=60, reclaim_grace_s=0)


def test_deposition_during_encoding_refuses_all_checkpoint_writes(tmp_path: Path) -> None:
    authority = authority_at(tmp_path, lambda: 100.0)
    grant = authority.acquire("brief-1", "old")
    token = CancellationToken()
    store = PipelineCheckpointStore(tmp_path / "phases", ExecutionScope.borrowed(authority, grant, token))
    original = checkpoint.hash_canonical

    def replace_owner(payload):
        authority.release(grant)
        authority.acquire("brief-1", "new")
        return original(payload)

    with (patch.object(checkpoint, "hash_canonical", side_effect=replace_owner),
          pytest.raises(StaleClaimError)):
        store.create(_record())
    assert token.is_cancelled()
    assert not store.path_for("brief-1").exists()
    assert not (tmp_path / "phases" / "history").exists()


def test_expiry_and_replacement_cannot_split_generation_and_selector(tmp_path: Path) -> None:
    now = [100.0]
    clock = lambda: now[0]
    authority = authority_at(tmp_path, clock)
    competitor = authority_at(tmp_path, clock)
    grant = authority.acquire("brief-1", "old")
    store = PipelineCheckpointStore(tmp_path / "phases",
        ExecutionScope.borrowed(authority, grant, CancellationToken()))
    writing, competing, replaced = Event(), Event(), Event()
    original = checkpoint.atomic_write_text
    record = _record()

    def write(path, raw):
        if "history" in path.parts:
            writing.set()
            assert competing.wait(5)
            # The competing sweep is now attempted while both commit locks hold.
            assert not replaced.wait(0.1)
        original(path, raw)

    def replace_owner():
        assert writing.wait(5)
        now[0] = 200.0  # expiry during the already-linearized commit
        competing.set()
        competitor.sweep()
        replacement = competitor.acquire("brief-1", "new")
        replaced.set()
        # Acquiring the newer epoch implies BOTH old writes already finished.
        assert PipelineCheckpointStore(store.root).load("brief-1") == record
        return replacement

    with ThreadPoolExecutor(max_workers=2) as pool:
        replacement = pool.submit(replace_owner)
        with patch.object(checkpoint, "atomic_write_text", side_effect=write):
            store.create(record)
        assert replacement.result(timeout=10).claim.epoch > grant.claim.epoch
    with pytest.raises(StaleClaimError):
        store.update(record, launches=record.launches + 1)
    assert PipelineCheckpointStore(store.root).load("brief-1") == record


@pytest.mark.parametrize("cancelled", [False, True])
def test_invalid_entry_never_calls_commit_and_releases_locks(tmp_path: Path, cancelled: bool) -> None:
    now = [100.0]
    authority = authority_at(tmp_path, lambda: now[0])
    grant = authority.acquire("brief-1", "old")
    token = CancellationToken()
    scope = ExecutionScope.borrowed(authority, grant, token)
    written = []
    if cancelled:
        token.cancel()
    else:
        now[0] = 200.0
    with pytest.raises(ExecutionCancelled if cancelled else StaleLeaseError):
        scope.commit(lambda: written.append("invalid"))
    assert not written
    # A refused callback must release both locks so recovery can proceed.
    if cancelled:
        authority.release(grant)
    else:
        authority.sweep()
    replacement = authority.acquire("brief-1", "new")
    authority.commit(replacement, lambda: written.append("valid"))
    assert written == ["valid"]
