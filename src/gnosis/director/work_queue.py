"""A durable queue whose ownership is decided by the claims plane.

Everything before this ran one brief at a time, synchronously. The
multi-worker plane needs two things the single-worker path never did:
somewhere for work to WAIT, and a way for two workers reaching for the
same brief to disagree safely.

The second one is already solved. ADR-0006 built durable CAS claims with
fencing epochs and expiring leases, and `WorkAuthority.acquire` is
exactly "exactly one holder, provably". Writing a second ownership
mechanism here would mean two answers to "who owns this" and a bug the
day they disagree — so the queue is a *place to put briefs*, and
ownership stays where ownership already lives.

What that leaves this module responsible for is small and specific:

- **The claim decides, not the scan.** Every worker sees the same pending
  files; they all try to acquire, and the CAS lets exactly one through.
  A loser gets `ClaimConflictError`, which is not an error condition here
  — it is the mechanism working — so it moves to the next brief.
- **A released brief returns to the queue.** A park (rule 6) must leave
  the work claimable again, not consumed. That is why `release` exists
  separately from `complete`.
- **A crashed worker's brief is reclaimable.** The lease expires and
  `WorkAuthority.sweep` reclaims the claim; the queue does not need its
  own liveness notion, and inventing one would be a second answer again.
  But reclaimed ownership is not enough on its own: the queue keeps file
  state separately, so `recover()` moves records whose owner is gone back
  to `pending`. Without it a killed worker's brief sat in `running/`
  where no worker looks — ownership free, record unreachable, which is
  the ghost rule 4 forbids.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..contracts.director_brief import DirectorBrief
from ..kernel.claims import (
    ClaimConflictError,
    ClaimStatus,
    WorkAuthority,
    WorkGrant,
)

PENDING = "pending"
RUNNING = "running"
DONE = "done"


@dataclass(frozen=True)
class ClaimedWork:
    """A brief this worker provably owns, and the grant that proves it."""

    brief: DirectorBrief
    grant: WorkGrant
    enqueued_at: float
    attempts: int

    @property
    def brief_id(self) -> str:
        return self.brief.brief_id


class WorkQueue:
    """Durable pending work. Ownership is the claims plane's business."""

    def __init__(self, root: Path, authority: WorkAuthority,
                 lease_ttl_s: float | None = None,
                 max_attempts: int | None = 5) -> None:
        self.root = Path(root)
        self.authority = authority
        self.lease_ttl_s = lease_ttl_s
        # Rule 8: no loop is unlimited. `release` returns a brief to
        # `pending` and `drain` re-offers it immediately, so a caller that
        # parks every time would spin forever — and the per-brief budget
        # does NOT bound that, because parking launches nothing and spends
        # nothing (independent review). Attempts are durable on the
        # record, so the bound survives a restart too.
        self.max_attempts = max_attempts
        # (brief_id, reason) for briefs this queue declined to claim. A
        # worker that skipped work and cannot say why is exactly the
        # silence every review of this project has punished.
        self.skipped: list[tuple[str, str]] = []
        for state in (PENDING, RUNNING, DONE):
            (self.root / state).mkdir(parents=True, exist_ok=True)

    # -- putting work in ---------------------------------------------------

    def enqueue(self, brief: DirectorBrief) -> bool:
        """Add a brief. Idempotent by brief id.

        Returns False when the brief is already queued, running or done —
        re-enqueuing live work would create a second task for it and
        orphan the first one's evidence, which is the defect ADR-0017's
        review found in `run_brief`.
        """
        if self._locate(brief.brief_id) is not None:
            return False
        payload = {
            "brief": brief.to_dict(),
            "enqueued_at": time.time(),
            "attempts": 0,
        }
        # EXCLUSIVE create, not write-then-replace. Two enqueuers racing
        # on the same brief id both passed `_locate` before either wrote,
        # and replace-based writing let the later one silently win — so
        # "idempotent by brief id" held only when nobody raced
        # (independent review). `x` mode makes the filesystem the
        # arbiter: exactly one creator, the other is told no.
        target = self.root / PENDING / f"{brief.brief_id}.json"
        try:
            with target.open("x", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, indent=2, sort_keys=True))
        except FileExistsError:
            return False
        return True

    # -- taking work out ---------------------------------------------------

    def claim(self, worker_id: str) -> ClaimedWork | None:
        """Take ownership of one pending brief, or return None.

        Every worker scans the same directory; the CAS in
        `WorkAuthority.acquire` is what makes exactly one of them the
        owner. A `ClaimConflictError` here means another worker won the
        race — the mechanism working, not a failure — so this moves on.
        """
        for path in sorted((self.root / PENDING).glob("*.json")):
            record = _read(path)
            if record is None:
                continue
            brief_id = str(record["brief"]["brief_id"])
            attempts = int(record.get("attempts", 0))
            if self.max_attempts is not None and attempts >= self.max_attempts:
                # Exhausted, and said so rather than silently skipped
                # forever. An operator requeues it deliberately.
                self.skipped.append(
                    (brief_id, f"attempts_exhausted:{attempts}/{self.max_attempts}"))
                continue
            try:
                grant = self.authority.acquire(
                    brief_id, worker_id, ttl_s=self.lease_ttl_s)
            except ClaimConflictError:
                continue
            except Exception as exc:  # noqa: BLE001 - see below
                # Claim taken but the lease is still held by a previous
                # holder whose TTL has not expired: the sweep resolves it.
                # Trying the next brief beats blocking the worker.
                #
                # Kept as data rather than logged: a worker that skipped a
                # brief and cannot say why is the kind of silence this
                # project keeps finding, and `skipped` is readable by
                # whoever asks the queue what it did.
                self.skipped.append((brief_id, f"{type(exc).__name__}: {exc}"))
                continue

            moved = self.root / RUNNING / path.name
            try:
                path.replace(moved)
            except OSError:
                # Another worker moved the file between the scan and here.
                # Ownership is the grant, not the file — but proceeding on
                # a record we no longer hold would be acting on a guess,
                # so hand the grant back and move on.
                self.authority.release(grant)
                continue

            record["attempts"] = int(record.get("attempts", 0)) + 1
            _atomic_write(moved, json.dumps(record, indent=2, sort_keys=True))

            try:
                # The grant was taken before the file moved, and a stalled
                # worker can have its lease expire and its claim reclaimed
                # inside that gap — then win the move anyway and hand out
                # work it no longer owns (independent review). This is the
                # claims plane's own NO STALE WRITE guard, asked at the
                # last moment before the work leaves this function.
                self.authority.assert_current(grant)
            except Exception as exc:  # noqa: BLE001 - not ours any more
                self.skipped.append((brief_id, f"stale grant: {type(exc).__name__}"))
                moved.replace(self.root / PENDING / path.name)
                continue

            return ClaimedWork(
                brief=DirectorBrief.from_dict(record["brief"]),
                grant=grant,
                enqueued_at=float(record.get("enqueued_at", 0.0)),
                attempts=int(record["attempts"]),
            )
        return None

    def recover(self) -> list[str]:
        """Return briefs whose owner is gone to `pending`.

        The claims plane reclaims a dead worker's CLAIM through the lease
        TTL, which is what ADR-0006 promises — and the queue kept its own
        file state separately, so the brief stayed in `running/` where no
        worker ever looks. Reclaimed ownership plus an unreachable record
        is precisely the ghost rule 4 forbids: not progressing, not
        terminal, invisible (verified before shipping — a killed worker's
        brief was never claimable again).

        Liveness is still not this module's notion. It asks the claims
        plane whether the claim is ACTIVE and moves the ones that are not;
        the sweep that decides that lives in `WorkAuthority`.
        """
        returned: list[str] = []
        for path in sorted((self.root / RUNNING).glob("*.json")):
            record = _read(path)
            if record is None:
                continue
            brief_id = str(record["brief"]["brief_id"])
            claim = self.authority.claims.get(brief_id)
            if claim is not None and claim.status is ClaimStatus.ACTIVE:
                continue  # someone still owns it

            # WHERE it goes depends on what the claim says HAPPENED, not
            # merely that nobody holds it. `complete` resolves the claim
            # and then moves the file; a crash between those leaves a
            # RESOLVED claim with the record still in `running/`, and
            # returning that to `pending` would re-execute finished work —
            # worse than the ghost this recovery exists to prevent, and
            # exactly the mistake ADR-0016's boot sweep already had to
            # learn (independent review caught it in this fix).
            resolved = claim is not None and claim.status is ClaimStatus.RESOLVED
            target = DONE if resolved else PENDING
            record["recovered_from"] = RUNNING
            record["recovered_because"] = (
                claim.status.value if claim is not None else "no_claim")
            _atomic_write(self.root / target / path.name,
                          json.dumps(record, indent=2, sort_keys=True))
            path.unlink(missing_ok=True)
            returned.append(brief_id)
        return returned

    def complete(self, work: ClaimedWork, outcome: str) -> None:
        """Finish the brief: the claim resolves and the work leaves the queue."""
        self.authority.resolve(work.grant, outcome=outcome)
        self._move(work.brief_id, RUNNING, DONE, {"outcome": outcome})

    def release(self, work: ClaimedWork, reason: str) -> None:
        """Hand the brief back, still pending.

        A park is not a completion: rule 6 says a shut window leaves the
        work untouched and resumable, so it has to become claimable
        again — by this worker later, or by another one now.
        """
        self.authority.release(work.grant)
        self._move(work.brief_id, RUNNING, PENDING, {"released_because": reason})

    # -- inspection --------------------------------------------------------

    def pending_ids(self) -> list[str]:
        return sorted(p.stem for p in (self.root / PENDING).glob("*.json"))

    def running_ids(self) -> list[str]:
        return sorted(p.stem for p in (self.root / RUNNING).glob("*.json"))

    def done_ids(self) -> list[str]:
        return sorted(p.stem for p in (self.root / DONE).glob("*.json"))

    def depth(self) -> int:
        return len(self.pending_ids())

    def _locate(self, brief_id: str) -> str | None:
        for state in (PENDING, RUNNING, DONE):
            if (self.root / state / f"{brief_id}.json").exists():
                return state
        return None

    def _move(self, brief_id: str, source: str, target: str,
              extra: dict[str, Any]) -> None:
        origin = self.root / source / f"{brief_id}.json"
        record = _read(origin) or {"brief": {"brief_id": brief_id}}
        record.update(extra)
        _atomic_write(self.root / target / f"{brief_id}.json",
                      json.dumps(record, indent=2, sort_keys=True))
        origin.unlink(missing_ok=True)


def _read(path: Path) -> dict[str, Any] | None:
    """A half-written or vanished record is skipped, never fatal.

    A queue that refuses to run because one file is damaged turns a single
    bad record into a total outage; the record stays where it is for an
    operator to look at.
    """
    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) and "brief" in payload else None


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def drain(queue: WorkQueue, worker_id: str,
          recover_first: bool = True) -> Iterator[ClaimedWork]:
    """Claim briefs until the queue has none left for this worker.

    Recovery runs once before the first claim, because a mechanism
    nothing calls is a parallel fiction (Directive 9) and this is the only
    routine path a worker takes. A worker starting up is exactly when a
    previous worker's stranded record should come back — the same moment
    ADR-0016 chose for its boot sweep.

    Bounded by the queue emptying, not by a count: every iteration either
    removes a brief from `pending` or returns None. A brief released back
    to pending is re-offered — which is the point of a park — so a caller
    that releases forever is the one that needs a circuit breaker, and
    `Budget` is where that lives.
    """
    if recover_first:
        queue.recover()
    while True:
        work = queue.claim(worker_id)
        if work is None:
            return
        yield work
