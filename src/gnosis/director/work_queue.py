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
import math
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..contracts.director_brief import DirectorBrief
from ..kernel.atomic_io import atomic_write_text
from ..kernel.claims import (
    ClaimConflictError,
    ClaimStatus,
    StaleClaimError,
    WorkAuthority,
    WorkGrant,
)
from ..kernel.file_lock import FileLock, lock_path_for
from ..runner.claude_cli_runner import CancellationToken

PENDING = "pending"
RUNNING = "running"
DONE = "done"
# Terminal until an operator requeues. A brief that has exhausted its
# attempts must LEAVE the queue: leaving it in `pending` and skipping it
# forever is a decision nobody can see.
BLOCKED = "blocked"


@dataclass(frozen=True)
class ClaimedWork:
    """A brief this worker provably owns, and the grant that proves it."""

    brief: DirectorBrief
    grant: WorkGrant
    enqueued_at: float
    attempts: int
    cancellation_token: CancellationToken = field(default_factory=CancellationToken,
                                                  compare=False, repr=False)

    @property
    def brief_id(self) -> str:
        return self.brief.brief_id


class WorkQueue:
    """Durable pending work. Ownership is the claims plane's business."""

    def __init__(self, root: Path, authority: WorkAuthority,
                 lease_ttl_s: float | None = None,
                 max_attempts: int | None = 5,
                 clock: Callable[[], float] = time.time) -> None:
        self.root = Path(root)
        self.authority = authority
        self.lease_ttl_s = lease_ttl_s
        # WALL CLOCK, like the hold plane and for the same reason: a
        # `not_before` is written to a durable record and read by another
        # process, possibly after a restart. A monotonic reading means
        # nothing to either.
        self.clock = clock
        # Recovery and claiming both move records between directories, and
        # `replace` alone cannot separate them: it proves the origin was
        # still there, not that it was still the SAME record. A recovery
        # that listed `running/` before a claim landed would happily move
        # the file a live owner had just re-created, leaving an ACTIVE
        # grant over a record sitting in `pending/` for anyone to take
        # (found by the concurrent test written for the previous fix).
        # One lock, taken in one order — queue before claims plane — so
        # the two operations cannot interleave.
        self._lock_path = lock_path_for(self.root / "queue")
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
        for state in (PENDING, RUNNING, DONE, BLOCKED):
            (self.root / state).mkdir(parents=True, exist_ok=True)

    # -- putting work in ---------------------------------------------------

    def enqueue(self, brief: DirectorBrief, *, dependencies: tuple[str, ...] = (),
                require_matching: bool = False) -> bool:
        """Add a brief. Idempotent by brief id.

        Returns False when the brief is already queued, running or done —
        re-enqueuing live work would create a second task for it and
        orphan the first one's evidence, which is the defect ADR-0017's
        review found in `run_brief`.
        """
        with FileLock(self._lock_path, timeout_s=30.0):
            return self._enqueue_locked(brief, dependencies, require_matching)

    def _enqueue_locked(self, brief: DirectorBrief, dependencies: tuple[str, ...],
                        require_matching: bool) -> bool:
        if not isinstance(dependencies, tuple) or any(
            not isinstance(dep, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", dep) is None
            for dep in dependencies
        ):
            raise ValueError("dependencies must be a tuple of safe brief identifiers")
        if brief.brief_id in dependencies or len(set(dependencies)) != len(dependencies):
            raise ValueError("self or duplicate dependency")
        # Edges only point at existing immutable queue records. Consequently a
        # newly inserted node cannot introduce a cycle. A project submits in
        # topological order, preserving this invariant across crash recovery.
        if any(self._locate(dep) is None for dep in dependencies):
            raise ValueError("dependency is not enqueued")
        existing_state = self._locate(brief.brief_id)
        if existing_state is not None:
            if require_matching:
                existing = _read(self.root / existing_state / f"{brief.brief_id}.json")
                if (existing is None or existing.get("brief") != brief.to_dict()
                        or existing.get("dependencies", []) != list(dependencies)):
                    raise ValueError("existing task differs from project plan or moved; retry")
            return False
        payload = {
            "brief": brief.to_dict(),
            "enqueued_at": time.time(),
            "attempts": 0,
            "dependencies": list(dependencies),
        }
        # The queue lock serializes insertion with every move. The atomic
        # writer prevents a killed enqueuer from leaving a partial brief.
        target = self.root / PENDING / f"{brief.brief_id}.json"
        _atomic_write(target, json.dumps(payload, indent=2, sort_keys=True))
        return True

    # -- taking work out ---------------------------------------------------

    def claim(self, worker_id: str) -> ClaimedWork | None:
        """Take ownership of one pending brief, or return None.

        Every worker scans the same directory; the CAS in
        `WorkAuthority.acquire` is what makes exactly one of them the
        owner. A `ClaimConflictError` here means another worker won the
        race — the mechanism working, not a failure — so this moves on.
        """
        with FileLock(self._lock_path, timeout_s=30.0):
            return self._claim_locked(worker_id)

    def _claim_locked(self, worker_id: str) -> ClaimedWork | None:
        for path in sorted((self.root / PENDING).glob("*.json")):
            record = _read(path)
            if record is None:
                continue
            if not self._dependencies_ready(record):
                continue
            brief_id = str(record["brief"]["brief_id"])
            attempts = int(record.get("attempts", 0))
            if self.max_attempts is not None and attempts >= self.max_attempts:
                # Exhausted. It LEAVES the queue rather than being skipped
                # on every future scan: a brief nobody will ever claim,
                # sitting in `pending` forever, is a decision no operator
                # can see.
                self.skipped.append(
                    (brief_id, f"attempts_exhausted:{attempts}/{self.max_attempts}"))
                self._move(brief_id, PENDING, BLOCKED,
                           {"blocked_because": f"attempts_exhausted:{attempts}"})
                continue

            wait_until = _finite_time(record.get("not_before"))
            if record.get("not_before") is not None and wait_until is None:
                # A `not_before` that is not a finite number cannot pace
                # anything, and honouring it literally (NaN, inf, a
                # string) would leave the brief unclaimable forever while
                # still sitting in `pending` — invisible, not blocked,
                # which is the ghost rule 4 forbids. Ignored and recorded.
                self.skipped.append(
                    (brief_id, f"unusable not_before: {record.get('not_before')!r}"))
            elif wait_until is not None and self.clock() < wait_until:
                # Not an error and not a skip worth recording on every
                # scan — the wait IS the mechanism.
                continue
            # Parse before taking authority: a corrupt brief must not strand
            # a new ACTIVE claim. All record reads and moves share this lock.
            brief = DirectorBrief.from_dict(record["brief"])
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
            record["claim_holder"] = grant.holder
            record["claim_epoch"] = grant.claim.epoch
            record.pop("pending_transition", None)
            record.pop("outcome", None)
            _atomic_write(moved, json.dumps(record, indent=2, sort_keys=True))
            # The record is in `running/` with a live grant: recovery can
            # no longer mistake it for a stranded one.

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
                brief=brief,
                grant=grant,
                enqueued_at=float(record.get("enqueued_at", 0.0)),
                attempts=int(record["attempts"]),
            )
        return None

    def _dependencies_ready(self, record: dict[str, Any]) -> bool:
        dependencies = record.get("dependencies", [])
        if not isinstance(dependencies, list):
            return False
        for dep in dependencies:
            if (not isinstance(dep, str)
                    or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", dep) is None):
                return False
            previous = _read(self.root / DONE / f"{dep}.json")
            claim = self.authority.claims.get(dep)
            if (previous is None or previous.get("outcome") != "COMPLETED"
                    or claim is None or claim.status is not ClaimStatus.RESOLVED
                    or claim.outcome != "COMPLETED"):
                return False
        return True

    def recover(self, pace: Callable[[int], float] | None = None) -> list[str]:
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
        the sweep that decides that lives in `WorkAuthority` — and until
        ADR-0022's addendum nothing in production called it, so this
        method skipped every crashed brief on every boot.

        `pace` maps a brief's attempt count to a delay, so work that comes
        back from a crash is paced like work that came back from a park.
        """
        returned: list[str] = []
        with FileLock(self._lock_path, timeout_s=30.0):
            returned = self._recover_locked(pace)
        return returned

    def _recover_locked(self, pace: Callable[[int], float] | None) -> list[str]:
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
            # Intent alone is not a commit. A worker can die or lose its
            # lease between stamping and the authority CAS. Honour only
            # the transition committed by the same holder and epoch.
            intent = record.pop("pending_transition", None)
            same_claim = claim is not None and (
                record.get("claim_holder") == claim.holder
                and record.get("claim_epoch") == claim.epoch)
            resolved = same_claim and claim is not None and claim.status is ClaimStatus.RESOLVED
            released = same_claim and claim is not None and claim.status is ClaimStatus.RELEASED
            target = DONE if resolved else BLOCKED if released and intent == BLOCKED else PENDING
            # THE MOVE IS THE CLAIM, exactly as in `claim()`. Writing the
            # target and then unlinking the origin let two supervisors
            # both act on one stale read: the first moved the record to
            # `pending` and re-claimed it, and the second — still holding
            # its earlier read — wrote `pending` again and deleted the
            # `running` record the first now owned, leaving one brief in
            # both directories and, once the claim resolved, running it a
            # second time (independent review). `replace` has exactly one
            # winner; the loser's origin is simply gone.
            destination = self.root / target / path.name
            try:
                path.replace(destination)
            except OSError:
                self.skipped.append((brief_id, "recovered by another worker"))
                continue

            # Annotate AFTER winning. The record is ours now, so this
            # cannot land on somebody else's file.
            moved = _read(destination) or record
            moved.pop("pending_transition", None)
            if resolved:
                assert claim is not None
                moved["outcome"] = claim.outcome
            elif not released:
                for key in ("outcome", "not_before", "blocked_because", "released_because"):
                    moved.pop(key, None)
            moved["recovered_from"] = RUNNING
            moved["recovered_because"] = (
                claim.status.value if claim is not None else "no_claim")
            if target == PENDING and pace is not None:
                # A crash that was NOT a park came back unpaced: a park's
                # `not_before` survives on the record, but a worker that
                # simply died left none, so a crash loop re-launched
                # agents at full speed — bounded only by `max_attempts`,
                # which is not pacing (independent review). What is being
                # paced is the same thing in both cases: another launch.
                delay = pace(int(moved.get("attempts", 0)))
                if delay > 0:
                    moved["not_before"] = self.clock() + delay
                    moved["paced_because"] = "recovered"
            _atomic_write(destination, json.dumps(moved, indent=2, sort_keys=True))
            returned.append(brief_id)
        return returned

    def complete(self, work: ClaimedWork, outcome: str) -> None:
        """Finish the brief: the claim resolves and the work leaves the queue."""
        with FileLock(self._lock_path, timeout_s=30.0):
            self._stamp(work, {"pending_transition": DONE, "outcome": outcome})
            self.authority.resolve(work.grant, outcome=outcome)
            self._move(work.brief_id, RUNNING, DONE, {"outcome": outcome})

    def release(self, work: ClaimedWork, reason: str,
                not_before: float | None = None) -> None:
        """Hand the brief back, still pending, optionally not just yet.

        A park is not a completion: rule 6 says a shut window leaves the
        work untouched and resumable, so it has to become claimable
        again — by this worker later, or by another one now.

        `not_before` is DURABLE on the record, which is the whole point.
        Backoff held in a worker's memory is backoff a restart forgets,
        and the thing it is pacing — an agent launch against a shut
        window — is exactly what should not resume at full speed after a
        crash (L-0024's shape).
        """
        extra: dict[str, Any] = {"released_because": reason}
        if not_before is not None:
            extra["not_before"] = float(not_before)
        with FileLock(self._lock_path, timeout_s=30.0):
            self._stamp(work, {**extra, "pending_transition": PENDING})
            self.authority.release(work.grant)
            self._move(work.brief_id, RUNNING, PENDING, extra)

    def block(self, work: ClaimedWork, reason: str) -> None:
        """Take the brief out of circulation for a human to look at."""
        with FileLock(self._lock_path, timeout_s=30.0):
            self._stamp(work, {"pending_transition": BLOCKED, "blocked_because": reason})
            self.authority.release(work.grant)
            self._move(work.brief_id, RUNNING, BLOCKED, {"blocked_because": reason})

    def requeue(self, brief_id: str, reason: str = "operator") -> bool:
        """An operator's decision to try a blocked brief again.

        Attempts reset here and nowhere else: a bound an automated path
        could clear is not a bound.
        """
        with FileLock(self._lock_path, timeout_s=30.0):
            return self._requeue_locked(brief_id, reason)

    def _requeue_locked(self, brief_id: str, reason: str) -> bool:
        origin = self.root / BLOCKED / f"{brief_id}.json"
        record = _read(origin)
        if record is None:
            return False
        record["attempts"] = 0
        record.pop("not_before", None)
        record.pop("blocked_because", None)
        record.pop("pending_transition", None)
        record["requeued_because"] = reason
        _atomic_write(origin, json.dumps(record, indent=2, sort_keys=True))
        origin.replace(self.root / PENDING / f"{brief_id}.json")
        return True

    def blocked_ids(self) -> list[str]:
        return sorted(p.stem for p in (self.root / BLOCKED).glob("*.json"))

    def dependency_waiting_ids(self) -> list[str]:
        """Pending tasks whose predecessor evidence is not complete."""
        return [path.stem for path in sorted((self.root / PENDING).glob("*.json"))
                if (record := _read(path)) is not None
                and not self._dependencies_ready(record)]

    def waiting(self) -> list[tuple[str, float]]:
        """Briefs that are pending but backing off, and until when.

        `pending_ids()` alone would show a brief nobody can claim as
        available. An operator asking "why is nothing moving" needs the
        wait to be visible, not inferred.
        """
        out: list[tuple[str, float]] = []
        now = self.clock()
        for path in sorted((self.root / PENDING).glob("*.json")):
            record = _read(path)
            if record is None:
                continue
            wait_until = _finite_time(record.get("not_before"))
            if wait_until is not None and now < wait_until:
                out.append((str(record["brief"]["brief_id"]), wait_until))
        return out

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
        for state in (PENDING, RUNNING, DONE, BLOCKED):
            if (self.root / state / f"{brief_id}.json").exists():
                return state
        return None

    def _stamp(self, work: ClaimedWork, extra: dict[str, Any]) -> None:
        """Persist intent under the queue lock, after checking ownership.

        A failed write aborts the transition: a committed release without
        its block/backoff intent cannot be correctly recovered.
        """
        self.authority.assert_current(work.grant)
        path = self.root / RUNNING / f"{work.brief_id}.json"
        record = _read(path)
        if record is None:
            return
        if (record.get("claim_holder") != work.grant.holder
                or record.get("claim_epoch") != work.grant.claim.epoch):
            raise StaleClaimError("running record belongs to another claim")
        record.update(extra)
        payload = json.dumps(record, indent=2, sort_keys=True)
        self.authority.commit(work.grant, lambda: _atomic_write(path, payload))

    def _move(self, brief_id: str, source: str, target: str,
              extra: dict[str, Any]) -> None:
        origin = self.root / source / f"{brief_id}.json"
        record = _read(origin)
        if record is None:
            # The origin is GONE — another worker's recovery moved it, or
            # it was damaged. The old code invented `{"brief": {"brief_id":
            # ...}}` here and wrote it on, which was worse than doing
            # nothing in two ways: the stub has no `attempts`, so the next
            # `claim` read 0 and the max-attempts bound was cleared by an
            # automated path the module swears cannot clear it; and the
            # stub has no title/mission, so `DirectorBrief.from_dict`
            # raised inside `claim` AFTER the grant was taken, poisoning
            # the brief permanently (independent review).
            #
            # A vanished record is not a licence to guess. It is recorded
            # and the move is abandoned: whoever moved it owns it now.
            self.skipped.append((brief_id, f"record vanished from {source}/"))
            return
        record.update(extra)
        # Persist details before the one atomic move, retaining intent
        # until arrival. A crash never leaves records in two buckets.
        _atomic_write(origin, json.dumps(record, indent=2, sort_keys=True))
        destination = self.root / target / f"{brief_id}.json"
        origin.replace(destination)
        record.pop("pending_transition", None)
        _atomic_write(destination, json.dumps(record, indent=2, sort_keys=True))


def _finite_time(value: Any) -> float | None:
    """A usable timestamp, or None. `bool` is `int` in Python, and NaN
    compares false against everything — neither can pace a queue."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


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
    # Reuse the fsynced, unique-temp writer and its bounded Windows sharing
    # retry. A PID-only temporary path collides between threads in one process.
    atomic_write_text(path, text)


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
