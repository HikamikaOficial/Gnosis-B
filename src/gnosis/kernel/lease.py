"""Fenced, expiring resource leases (Directive 4, part one: the lease plane).

Assignment of a mutable resource to a worker is a *lease*, never a fact:
it has an owner, an expiry, a heartbeat, and — critically — a fencing
token that increases monotonically with every grant for the resource.
After a lease expires and is taken over, the old holder's lease_id fails
every subsequent operation (heartbeat/assert_current/release) with
StaleLeaseError, satisfying the survival invariant NO STALE WRITE: an
old worker cannot mutate anything guarded by `assert_current` after a
transfer, even if it wakes up believing it still owns the resource.

Fencing tokens survive release: `last_token` per resource is retained
after a lease ends, so every new grant is strictly greater than any
token ever issued for that resource. A downstream system that records
the highest token it has accepted can therefore reject late writes from
any deposed holder (the classic fencing pattern; see bernstein/beads in
docs/research/REFERENCE_REPOSITORY_FINDINGS.md §4).

Persistence is one JSON state file written with atomic_io (readers never
see a torn write) and serialized with a FileLock (kernel.file_lock), the
same cross-process pattern as the run store and ledger. Expiry uses this
machine's wall clock — acceptable for GNOSIS V1's single-workstation
scope, and revisit if the kernel ever spans hosts.

The durable *claims* plane (who is assigned a task, surviving restarts as
work-graph state) is a separate future layer; this module is only the
ephemeral operational lease.
"""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .atomic_io import atomic_write_text
from .file_lock import FileLock, lock_path_for


class LeaseError(RuntimeError):
    pass


class LeaseHeldError(LeaseError):
    """The resource is currently leased to a live holder."""

    def __init__(self, lease: Lease):
        super().__init__(
            f"Resource '{lease.resource}' is held by '{lease.holder}' "
            f"(lease {lease.lease_id}, token {lease.fencing_token}) "
            f"until {lease.expires_at:.3f}"
        )
        self.lease = lease


class StaleLeaseError(LeaseError):
    """The presented lease is no longer the current grant for the resource."""


@dataclass(frozen=True)
class Lease:
    resource: str
    lease_id: str
    holder: str
    fencing_token: int
    issued_at: float
    expires_at: float
    last_heartbeat_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "lease_id": self.lease_id,
            "holder": self.holder,
            "fencing_token": self.fencing_token,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "last_heartbeat_at": self.last_heartbeat_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Lease:
        return cls(
            resource=data["resource"],
            lease_id=data["lease_id"],
            holder=data["holder"],
            fencing_token=data["fencing_token"],
            issued_at=data["issued_at"],
            expires_at=data["expires_at"],
            last_heartbeat_at=data["last_heartbeat_at"],
        )


class LeaseStore:
    """Durable store of current leases plus per-resource token history.

    Safe for concurrent use across threads and processes: every operation
    is a read-modify-write of the state file under one FileLock.
    """

    def __init__(self, path: Path, lock_timeout_s: float = 30.0,
                 clock: Callable[[], float] = time.time):
        self.path = path
        self._lock_timeout_s = lock_timeout_s
        # Injectable clock (a callable returning float seconds) so expiry
        # behavior is deterministically testable without sleeping.
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _locked(self) -> FileLock:
        # One FileLock instance PER critical section, per the FileLock
        # contract: a shared instance raises on concurrent acquire from a
        # second thread instead of waiting its turn. Multi-threaded use is
        # real (heartbeat pump + guards + sweeps), and the OS-level lock
        # still serializes across both threads and processes.
        return FileLock(lock_path_for(self.path), timeout_s=self._lock_timeout_s)

    # -- operations ---------------------------------------------------------

    def acquire(self, resource: str, holder: str, ttl_s: float) -> Lease:
        """Grant a lease, or raise LeaseHeldError while a live one exists.

        An expired lease is taken over with a strictly greater fencing
        token. Renewal of a live lease is heartbeat()'s job, deliberately
        not acquire()'s, so double-acquire bugs surface loudly even for
        the same holder.
        """
        if ttl_s <= 0:
            raise ValueError("ttl_s must be positive")
        with self._locked():
            state = self._load_locked()
            now = float(self._clock())
            current = state["leases"].get(resource)
            if current is not None:
                lease = Lease.from_dict(current)
                if lease.expires_at > now:
                    raise LeaseHeldError(lease)
                # Expired: record the takeover as an eviction, then fall
                # through to grant with the next token.
                del state["leases"][resource]
            next_token = int(state["last_tokens"].get(resource, 0)) + 1
            lease = Lease(
                resource=resource,
                lease_id=f"LEASE-{uuid.uuid4().hex[:12]}",
                holder=holder,
                fencing_token=next_token,
                issued_at=now,
                expires_at=now + ttl_s,
                last_heartbeat_at=now,
            )
            state["leases"][resource] = lease.to_dict()
            state["last_tokens"][resource] = next_token
            self._save_locked(state)
            return lease

    def heartbeat(self, resource: str, lease_id: str, extend_s: float) -> Lease:
        """Extend a live, current lease; stale or unknown leases fail loudly."""
        if extend_s <= 0:
            raise ValueError("extend_s must be positive")
        with self._locked():
            state = self._load_locked()
            lease = self._current_locked(state, resource, lease_id)
            now = float(self._clock())
            renewed = Lease(
                resource=lease.resource,
                lease_id=lease.lease_id,
                holder=lease.holder,
                fencing_token=lease.fencing_token,
                issued_at=lease.issued_at,
                expires_at=now + extend_s,
                last_heartbeat_at=now,
            )
            state["leases"][resource] = renewed.to_dict()
            self._save_locked(state)
            return renewed

    def release(self, resource: str, lease_id: str) -> None:
        """Release a current lease. Releasing a stale lease raises: the
        caller believed it held something it did not, which is exactly
        the condition that must surface, not be absorbed."""
        with self._locked():
            state = self._load_locked()
            self._current_locked(state, resource, lease_id)
            del state["leases"][resource]
            self._save_locked(state)

    def assert_current(self, resource: str, lease_id: str) -> Lease:
        """Guard for writes: raise StaleLeaseError unless lease_id is the
        live, unexpired grant for the resource."""
        with self._locked():
            state = self._load_locked()
            return self._current_locked(state, resource, lease_id)

    def current(self, resource: str) -> Lease | None:
        """The live lease for a resource, or None (expired counts as None)."""
        with self._locked():
            state = self._load_locked()
            raw = state["leases"].get(resource)
            if raw is None:
                return None
            lease = Lease.from_dict(raw)
            if lease.expires_at <= float(self._clock()):
                return None
            return lease

    # -- internals ----------------------------------------------------------

    def _current_locked(self, state: dict[str, Any], resource: str, lease_id: str) -> Lease:
        raw = state["leases"].get(resource)
        if raw is None:
            raise StaleLeaseError(f"No live lease for resource '{resource}'")
        lease = Lease.from_dict(raw)
        if lease.lease_id != lease_id:
            raise StaleLeaseError(
                f"Lease {lease_id} for resource '{resource}' was superseded "
                f"(current: {lease.lease_id}, token {lease.fencing_token})"
            )
        if lease.expires_at <= float(self._clock()):
            raise StaleLeaseError(
                f"Lease {lease_id} for resource '{resource}' has expired"
            )
        return lease

    def _load_locked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "leases": {}, "last_tokens": {}}
        payload: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        payload.setdefault("leases", {})
        payload.setdefault("last_tokens", {})
        return payload

    def _save_locked(self, state: dict[str, Any]) -> None:
        atomic_write_text(self.path, json.dumps(state, sort_keys=True, indent=1))
