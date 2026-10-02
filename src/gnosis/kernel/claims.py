"""Durable task claims + the two-plane work authority (Directive 4, part two).

Two planes, deliberately separate (REFERENCE_REPOSITORY_FINDINGS §4):

- **Claims (this module's ClaimStore)** are history-worthy ownership state:
  who owns a task, durable, versioned. Every ownership mutation is a CAS
  on a ``version`` token and is recorded in the claim's history. Fencing
  ``epoch``s increment monotonically per task inside the claim mutation
  itself and survive any status change, so a later grant is always
  distinguishable from — and greater than — every earlier one.
- **Leases (kernel.lease)** are liveness chatter: TTL + heartbeats that
  never enter ownership history.

``WorkAuthority`` composes the two: acquiring work takes the durable
claim first, then the ephemeral lease; guarding a write checks both; the
TTL sweep reclaims claims whose lease has expired, re-evaluating the
expiry predicate under the claim store's lock at mutation time (beads'
rule: repeat the predicate at delete time, don't trust an earlier read).

Conflicts are typed data, never prose: ``ClaimConflictError`` carries the
full current claim; ``StaleClaimError`` means the presented (holder,
epoch, version) is no longer the live grant.

Lock ordering is claims → leases everywhere (LeaseStore never calls back
into ClaimStore), so the two FileLocks cannot deadlock.

Known, accepted race (single-workstation V1): a holder may heartbeat its
lease concurrently with a sweep that already entered the claim lock; the
sweep can then reclaim a claim whose lease just revived. The outcome is
safe — the deposed holder's next ``assert_current`` fails loudly and no
stale write lands — but the work is interrupted. Revisit if sweeps ever
run aggressively enough for this to matter.
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Any

from .atomic_io import atomic_write_text
from .file_lock import FileLock, lock_path_for
from .lease import Lease, LeaseHeldError, LeaseStore, StaleLeaseError


class ClaimStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    RESOLVED = "RESOLVED"
    RECLAIMED = "RECLAIMED"


class ClaimError(RuntimeError):
    pass


class ClaimConflictError(ClaimError):
    """The task is actively claimed by someone else. Carries the current
    claim as typed data — holder, status, epoch, version — never prose."""

    def __init__(self, claim: TaskClaim):
        super().__init__(
            f"Task '{claim.task_id}' is claimed by '{claim.holder}' "
            f"(status {claim.status.value}, epoch {claim.epoch}, version {claim.version})"
        )
        self.claim = claim


class StaleClaimError(ClaimError):
    """The presented (holder, epoch/version) is no longer the live grant."""


@dataclass(frozen=True)
class TaskClaim:
    task_id: str
    holder: str
    status: ClaimStatus
    epoch: int      # fencing epoch: monotonic per task across ALL grants
    version: int    # CAS token: rewritten by every ownership mutation
    claimed_at: float
    updated_at: float
    outcome: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "holder": self.holder,
            "status": self.status.value,
            "epoch": self.epoch,
            "version": self.version,
            "claimed_at": self.claimed_at,
            "updated_at": self.updated_at,
            "outcome": self.outcome,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskClaim:
        return cls(
            task_id=data["task_id"],
            holder=data["holder"],
            status=ClaimStatus(data["status"]),
            epoch=data["epoch"],
            version=data["version"],
            claimed_at=data["claimed_at"],
            updated_at=data["updated_at"],
            outcome=data.get("outcome"),
        )


class ClaimStore:
    """Durable, versioned task-ownership state with per-task history.

    Every operation is a read-modify-write of one JSON state file under a
    FileLock (atomic_io for the write), the kernel's established
    cross-process pattern.
    """

    def __init__(self, path: Path, lock_timeout_s: float = 30.0,
                 clock: Callable[[], float] = time.time):
        self.path = path
        self._lock_timeout_s = lock_timeout_s
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

    def claim(self, task_id: str, holder: str) -> TaskClaim:
        """CAS-claim a task. Idempotent for same-actor retries (an ACTIVE
        claim by the same holder is returned unchanged — retrying is not
        an ownership mutation, so neither version nor epoch move). An
        ACTIVE claim by anyone else raises ClaimConflictError with the
        current claim as typed data. Non-ACTIVE prior claims are
        superseded with a strictly greater fencing epoch."""
        with self._locked():
            state = self._load_locked()
            raw = state["claims"].get(task_id)
            now = float(self._clock())
            if raw is not None:
                current = TaskClaim.from_dict(raw)
                if current.status is ClaimStatus.ACTIVE:
                    if current.holder == holder:
                        return current
                    raise ClaimConflictError(current)
            next_epoch = int(state["last_epochs"].get(task_id, 0)) + 1
            next_version = (TaskClaim.from_dict(raw).version if raw is not None else 0) + 1
            claim = TaskClaim(
                task_id=task_id, holder=holder, status=ClaimStatus.ACTIVE,
                epoch=next_epoch, version=next_version,
                claimed_at=now, updated_at=now,
            )
            state["claims"][task_id] = claim.to_dict()
            state["last_epochs"][task_id] = next_epoch
            self._append_history_locked(state, claim, action="claim")
            self._save_locked(state)
            return claim

    def release(self, task_id: str, holder: str, expected_version: int, *,
                commit_guard: Callable[[Callable[[], None]], None] | None = None) -> TaskClaim:
        """Voluntary hand-back of an ACTIVE claim (ownership mutation)."""
        return self._mutate_locked(
            task_id, holder, expected_version, ClaimStatus.RELEASED,
            outcome=None, action="release", commit_guard=commit_guard,
        )

    def resolve(self, task_id: str, holder: str, expected_version: int,
                outcome: str, *,
                commit_guard: Callable[[Callable[[], None]], None] | None = None) -> TaskClaim:
        """Terminal: the claimed work concluded with ``outcome``."""
        return self._mutate_locked(
            task_id, holder, expected_version, ClaimStatus.RESOLVED,
            outcome=outcome, action="resolve", commit_guard=commit_guard,
        )

    def reclaim_if(self, task_id: str, expected_version: int,
                   predicate: Callable[[], bool], reason: str) -> TaskClaim | None:
        """TTL-sweep primitive: mark an ACTIVE claim RECLAIMED, but only if
        ``predicate()`` — re-evaluated here, under this store's lock, at
        mutation time — still holds and the version still matches. Returns
        None (not an error) when the claim moved or the predicate no
        longer holds: a sweep skipping is normal, not exceptional."""
        with self._locked():
            state = self._load_locked()
            raw = state["claims"].get(task_id)
            if raw is None:
                return None
            current = TaskClaim.from_dict(raw)
            if current.status is not ClaimStatus.ACTIVE or current.version != expected_version:
                return None
            if not predicate():
                return None
            reclaimed = TaskClaim(
                task_id=task_id, holder=current.holder, status=ClaimStatus.RECLAIMED,
                epoch=current.epoch, version=current.version + 1,
                claimed_at=current.claimed_at, updated_at=float(self._clock()),
                outcome=reason,
            )
            state["claims"][task_id] = reclaimed.to_dict()
            self._append_history_locked(state, reclaimed, action="reclaim")
            self._save_locked(state)
            return reclaimed

    def get(self, task_id: str) -> TaskClaim | None:
        with self._locked():
            raw = self._load_locked()["claims"].get(task_id)
            return TaskClaim.from_dict(raw) if raw is not None else None

    def active_claims(self) -> list[TaskClaim]:
        with self._locked():
            state = self._load_locked()
            claims = (TaskClaim.from_dict(raw) for raw in state["claims"].values())
            return [c for c in claims if c.status is ClaimStatus.ACTIVE]

    def assert_active(self, task_id: str, holder: str, epoch: int) -> TaskClaim:
        """Write guard: the live grant must be ACTIVE, by this holder, at
        this fencing epoch — anything else is a deposed worker."""
        with self._locked():
            return self._assert_active_locked(task_id, holder, epoch)

    def while_active(self, task_id: str, holder: str, epoch: int,
                     action: Callable[[], None]) -> None:
        """Run a bounded commit without allowing ownership replacement.

        Action must not reenter this store or acquire a lock ordered before it.
        """
        with self._locked():
            self._assert_active_locked(task_id, holder, epoch)
            action()

    def _assert_active_locked(self, task_id: str, holder: str, epoch: int) -> TaskClaim:
        raw = self._load_locked()["claims"].get(task_id)
        if raw is None:
            raise StaleClaimError(f"No claim exists for task '{task_id}'")
        current = TaskClaim.from_dict(raw)
        if current.status is not ClaimStatus.ACTIVE:
            raise StaleClaimError(
                f"Claim for task '{task_id}' is {current.status.value}, not ACTIVE"
            )
        if current.holder != holder or current.epoch != epoch:
            raise StaleClaimError(
                f"Claim for task '{task_id}' is held by '{current.holder}' at epoch "
                f"{current.epoch}; presented holder '{holder}' epoch {epoch} is stale"
            )
        return current

    def history(self, task_id: str) -> list[dict[str, Any]]:
        with self._locked():
            entries: list[dict[str, Any]] = list(
                self._load_locked()["history"].get(task_id, [])
            )
            return entries

    # -- internals ----------------------------------------------------------

    def _mutate_locked(self, task_id: str, holder: str, expected_version: int,
                       new_status: ClaimStatus, outcome: str | None,
                       action: str,
                       commit_guard: Callable[[Callable[[], None]], None] | None = None) -> TaskClaim:
        with self._locked():
            state = self._load_locked()
            raw = state["claims"].get(task_id)
            if raw is None:
                raise StaleClaimError(f"No claim exists for task '{task_id}'")
            current = TaskClaim.from_dict(raw)
            if current.status is not ClaimStatus.ACTIVE:
                raise StaleClaimError(
                    f"Cannot {action} task '{task_id}': claim is {current.status.value}"
                )
            if current.holder != holder:
                raise StaleClaimError(
                    f"Cannot {action} task '{task_id}': held by '{current.holder}', "
                    f"not '{holder}'"
                )
            if current.version != expected_version:
                raise StaleClaimError(
                    f"Cannot {action} task '{task_id}': version moved to "
                    f"{current.version} (expected {expected_version})"
                )
            mutated = TaskClaim(
                task_id=task_id, holder=holder, status=new_status,
                epoch=current.epoch, version=current.version + 1,
                claimed_at=current.claimed_at, updated_at=float(self._clock()),
                outcome=outcome,
            )
            state["claims"][task_id] = mutated.to_dict()
            self._append_history_locked(state, mutated, action=action)
            # The claims lock is already held. A two-plane caller acquires
            # the lease lock next and retains it through durable persistence.
            if commit_guard is None:
                self._save_locked(state)
            else:
                commit_guard(lambda: self._save_locked(state))
            return mutated

    def _append_history_locked(self, state: dict[str, Any], claim: TaskClaim,
                               action: str) -> None:
        state["history"].setdefault(claim.task_id, []).append(
            {"action": action, "at": claim.updated_at, **claim.to_dict()}
        )

    def _load_locked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "claims": {}, "last_epochs": {}, "history": {}}
        payload: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        payload.setdefault("claims", {})
        payload.setdefault("last_epochs", {})
        payload.setdefault("history", {})
        return payload

    def _save_locked(self, state: dict[str, Any]) -> None:
        atomic_write_text(self.path, json.dumps(state, sort_keys=True, indent=1))


# -- two-plane facade ---------------------------------------------------------


@dataclass(frozen=True)
class WorkGrant:
    """Proof-of-ownership a worker carries: the durable claim plus the
    live lease, and the TTL the grant was acquired with — renewals honor
    this TTL, never a facade-wide default (adversarial-review finding:
    renewals silently shrinking a caller's longer TTL)."""

    claim: TaskClaim
    lease: Lease
    ttl_s: float

    @property
    def task_id(self) -> str:
        return self.claim.task_id

    @property
    def holder(self) -> str:
        return self.claim.holder


def task_resource(task_id: str) -> str:
    return f"task/{task_id}"


class WorkAuthority:
    """Composes the durable claim plane with the ephemeral lease plane.

    ``reclaim_grace_s`` protects acquire()'s claim-then-lease window from
    the sweep (adversarial-review finding: "never leased yet" was
    indistinguishable from "lease expired"): a claim mutated more recently
    than the grace window is never sweep-eligible, so a freshly minted
    claim cannot be reclaimed before its holder finishes acquiring the
    lease. Healthy long-running work is protected by its lease, not by
    grace, so the grace window can stay short."""

    def __init__(self, claims: ClaimStore, leases: LeaseStore,
                 default_ttl_s: float = 300.0, reclaim_grace_s: float = 30.0,
                 clock: Callable[[], float] = time.time):
        self.claims = claims
        self.leases = leases
        self.default_ttl_s = default_ttl_s
        self.reclaim_grace_s = reclaim_grace_s
        self._clock = clock

    def acquire(self, task_id: str, holder: str, ttl_s: float | None = None) -> WorkGrant:
        """Durable claim first, then the liveness lease. Same-actor retry
        while its own lease is still live reuses the live lease."""
        ttl = self.default_ttl_s if ttl_s is None else ttl_s
        claim = self.claims.claim(task_id, holder)
        resource = task_resource(task_id)
        try:
            lease = self.leases.acquire(resource, holder, ttl_s=ttl)
        except LeaseHeldError as exc:
            if exc.lease.holder == holder:
                lease = exc.lease  # our own live lease: this is a retry
            else:
                # Claim says us, lease says them: a previous holder's lease
                # has not expired yet. Fail loudly; the sweep/TTL resolves it.
                raise
        return WorkGrant(claim=claim, lease=lease, ttl_s=ttl)

    def assert_current(self, grant: WorkGrant) -> None:
        """Write guard for both planes: live unexpired lease AND the exact
        ACTIVE claim at the granted fencing epoch. Raises StaleLeaseError
        or StaleClaimError — the NO STALE WRITE invariant."""
        self.leases.assert_current(task_resource(grant.task_id), grant.lease.lease_id)
        self.claims.assert_active(grant.task_id, grant.holder, grant.claim.epoch)

    def heartbeat(self, grant: WorkGrant, extend_s: float | None = None) -> Lease:
        """Renew the grant's lease. The extension defaults to the TTL the
        grant was acquired with, so a caller's longer window survives
        every renewal."""
        extend = grant.ttl_s if extend_s is None else extend_s
        return self.leases.heartbeat(
            task_resource(grant.task_id), grant.lease.lease_id, extend_s=extend,
        )

    def commit(self, grant: WorkGrant, action: Callable[[], None]) -> None:
        """Linearize short persistence under claims -> leases locks.

        Callbacks must not reenter authority/stores. A grant must be live on
        entry; replacement cannot interleave even if expiry crosses mid-write.
        Never hold these locks across agent execution.
        """
        self.claims.while_active(grant.task_id, grant.holder, grant.claim.epoch,
            lambda: self.leases.while_current(task_resource(grant.task_id),
                                              grant.lease.lease_id, action))

    def resolve(self, grant: WorkGrant, outcome: str) -> TaskClaim:
        """Terminal success path: verify both planes, resolve the claim,
        release the lease."""
        self.assert_current(grant)
        current = self.claims.assert_active(grant.task_id, grant.holder, grant.claim.epoch)
        resolved = self.claims.resolve(
            grant.task_id, grant.holder, expected_version=current.version, outcome=outcome,
            commit_guard=lambda action: self.leases.while_current(
                task_resource(grant.task_id), grant.lease.lease_id, action),
        )
        self._release_lease_after_commit(grant)
        return resolved

    def release(self, grant: WorkGrant) -> TaskClaim:
        """Voluntary hand-back (not for failures: a claim on failed work
        stays bound to its unresolved state until reclaimed or explicitly
        handed off — grit's merge-failure lesson)."""
        self.assert_current(grant)
        current = self.claims.assert_active(grant.task_id, grant.holder, grant.claim.epoch)
        released = self.claims.release(
            grant.task_id, grant.holder, expected_version=current.version,
            commit_guard=lambda action: self.leases.while_current(
                task_resource(grant.task_id), grant.lease.lease_id, action),
        )
        self._release_lease_after_commit(grant)
        return released

    def _release_lease_after_commit(self, grant: WorkGrant) -> None:
        # The claim mutation above is the durable truth and has already
        # committed. If the lease expired or was superseded in the window
        # since assert_current, there is simply nothing left to release —
        # raising here would convert completed work into a caller-visible
        # failure (adversarial-review finding). Absorb only staleness;
        # anything else still surfaces.
        try:
            self.leases.release(task_resource(grant.task_id), grant.lease.lease_id)
        except StaleLeaseError:
            pass

    def _lease_gone(self, resource: str) -> bool:
        return self.leases.current(resource) is None

    def sweep(self) -> list[TaskClaim]:
        """TTL reclaim: every ACTIVE claim whose lease is gone is marked
        RECLAIMED. The expiry predicate runs again inside the claim
        store's lock at mutation time, and claims younger than
        ``reclaim_grace_s`` are never touched (see class docstring)."""
        reclaimed: list[TaskClaim] = []
        now = float(self._clock())
        for claim in self.claims.active_claims():
            if now - claim.updated_at < self.reclaim_grace_s:
                continue  # freshly minted/mutated: inside acquire()'s window
            result = self.claims.reclaim_if(
                claim.task_id, expected_version=claim.version,
                predicate=partial(self._lease_gone, task_resource(claim.task_id)),
                reason="lease expired (TTL sweep)",
            )
            if result is not None:
                reclaimed.append(result)
        return reclaimed


class GrantHeartbeatPump:
    """Background thread that keeps a WorkGrant's lease alive for the
    grant's whole lifetime — CLI runs, retry backoffs, verification,
    resolve — not just while some inner loop happens to tick (the
    adversarial-review finding that a slow verifier self-deposed a
    healthy worker).

    On deposition (StaleLeaseError/StaleClaimError from a renewal) it
    records the error, invokes ``on_deposed`` once, and exits; the owner's
    guards then surface the recorded error deterministically. Any other
    renewal failure (e.g. a transient lock timeout) is recorded as
    ``last_error`` and the pump keeps trying — a hiccup must not depose a
    live worker; the guards remain the authority."""

    def __init__(self, authority: WorkAuthority, grant: WorkGrant,
                 interval_s: float,
                 on_deposed: Callable[[Exception], None] | None = None):
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        self._authority = authority
        self._grant = grant
        self._interval_s = interval_s
        self._on_deposed = on_deposed
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.deposed: Exception | None = None
        self.last_error: Exception | None = None

    def start(self) -> None:
        self._thread.start()

    def stop(self, join_timeout_s: float = 5.0) -> None:
        self._stop.set()
        self._thread.join(timeout=join_timeout_s)

    def _run(self) -> None:
        while not self._stop.wait(self._interval_s):
            if self._stop.is_set():
                return  # stop() raced the wait timeout: do not renew again
            try:
                # Known narrow race (Codex review): if stop() lands while
                # this call is already blocked on the store lock, one last
                # renewal can slip through, extending an unresolved task's
                # lease by at most one TTL. Liveness delay only — the sweep
                # reclaims one interval later; ownership is unaffected.
                self._authority.heartbeat(self._grant)
            except (StaleClaimError, StaleLeaseError) as exc:
                self.deposed = exc
                if self._on_deposed is not None:
                    self._on_deposed(exc)
                return
            except Exception as exc:  # noqa: BLE001 - transient renewal failure must not depose a live worker
                self.last_error = exc
