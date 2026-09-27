from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest

from gnosis.kernel.claims import ClaimStatus, ClaimStore, WorkAuthority
from gnosis.kernel.lease import LeaseStore, StaleLeaseError


@pytest.mark.parametrize("operation", ["resolve", "release"])
def test_expiry_before_terminal_claim_commit_refuses_mutation(tmp_path, operation):
    now = [100.0]
    authority = WorkAuthority(ClaimStore(tmp_path / "claims", clock=lambda: now[0]),
        LeaseStore(tmp_path / "leases", clock=lambda: now[0]),
        default_ttl_s=60, clock=lambda: now[0], reclaim_grace_s=0)
    grant = authority.acquire("task", "old")
    original = getattr(authority.claims, operation)

    def expire_before_commit(*args, **kwargs):
        now[0] = 200.0
        return original(*args, **kwargs)

    with (patch.object(authority.claims, operation, side_effect=expire_before_commit),
          pytest.raises(StaleLeaseError)):
        if operation == "resolve":
            authority.resolve(grant, "COMPLETED")
        else:
            authority.release(grant)
    assert authority.claims.get("task").status is ClaimStatus.ACTIVE
    assert [entry["action"] for entry in authority.claims.history("task")] == ["claim"]
    authority.sweep()
    assert authority.acquire("task", "new").claim.epoch > grant.claim.epoch


@pytest.mark.parametrize("operation", ["resolve", "release"])
def test_admitted_terminal_commit_holds_lease_until_persisted(tmp_path, operation):
    now = [100.0]
    authority = WorkAuthority(ClaimStore(tmp_path / "claims", clock=lambda: now[0]),
        LeaseStore(tmp_path / "leases", clock=lambda: now[0]), default_ttl_s=60)
    grant = authority.acquire("task", "old")
    writing, competing, replaced = Event(), Event(), Event()
    original = authority.claims._save_locked
    terminal = ClaimStatus.RESOLVED if operation == "resolve" else ClaimStatus.RELEASED

    def persist(state):
        writing.set()
        assert competing.wait(5)
        assert not replaced.wait(0.1)
        original(state)

    def replace_lease():
        assert writing.wait(5)
        now[0] = 200.0
        competing.set()
        lease = authority.leases.acquire("task/task", "new", ttl_s=60)
        replaced.set()
        assert authority.claims.get("task").status is terminal
        return lease

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(replace_lease)
        with patch.object(authority.claims, "_save_locked", side_effect=persist):
            if operation == "resolve":
                result = authority.resolve(grant, "COMPLETED")
            else:
                result = authority.release(grant)
        lease = future.result(timeout=10)
    assert result.status is terminal
    assert authority.leases.current("task/task") == lease
