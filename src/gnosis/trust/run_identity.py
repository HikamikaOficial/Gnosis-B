"""Trusted run identity, publication lifecycle and the publish gate (F-17 Stage 3).

The property this exists for:

    knowing a run_id is NOT enough to produce ANCHORED.

A publisher may anchor run R only if trusted state shows R is exactly the run
that was authorized — for that worker SID, that generation, that deployment,
that evidence identity, and that lifecycle state. Every one of those is checked
against the trust plane's own record, never against anything the worker said.

WHY A SEPARATE PUBLICATION STATE. `RunState` (PENDING/RUNNING/SUCCEEDED/…) and
`TaskState` (…/COMPLETED) already exist and were inspected first. Neither is
reused here, and the reason is not vocabulary — it is WHERE THEY LIVE.
`RunState` is persisted in `RunStore`'s `meta.json`, inside the run directory
the worker owns and can write; a worker that could write `SUCCEEDED` into its
own meta would be writing its own publication permission. The trusted publish
gate must read state from a store the worker cannot write, so publication
authorization is the minimum separate primitive: it models ONLY "may this run's
evidence be authoritatively published", and nothing else. It adds no RUNNING,
no FAILED, no vocabulary that another state machine already owns.

IMMUTABLE vs MONOTONIC, kept structurally apart:

    RunIdentity (trust.anchor)      IMMUTABLE. Frozen at creation: run_id, task,
                                    repository, HEAD, tree, bundle path,
                                    owner_worker_sid, deployment_digest, epoch.
    TrustedRunRecord (here)         the identity PLUS the monotonic trusted
                                    state. A transition may only move the state
                                    forward; it cannot rewrite an identity field,
                                    because it never carries one.

Every state change is a compare-and-set on `expected_identity_digest`, so a
stale updater — or an identity that was deleted and recreated under the same
run_id — is refused instead of silently overwriting.

WHAT THIS DELIBERATELY IS NOT. No worker account, no DPAPI, no launcher, no
Windows service, no named pipe, no provisioning, no engine/runner change, no
durable-ordering protocol. The store is torn-write-safe and mutually excluded
(reusing the kernel's `atomic_io` + `file_lock`, not a second implementation),
but crash-ordering and the write-through watermark are Stage 4 and are NOT
pretended here. Windows ACLs are Stage 6/8; the model already assumes
`Worker WRITE = denied` on this store.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from gnosis.kernel.atomic_io import atomic_write_text
from gnosis.kernel.canonical import hash_canonical
from gnosis.kernel.file_lock import FileLock, lock_path_for
from gnosis.trust.anchor import RunIdentity
from gnosis.trust.launch import AuthorityUnavailable

TRUSTED_RUN_RECORD_SCHEMA = "gnosis.trust.run_record.v1"
SUPPORTED_RUN_RECORD_SCHEMAS = frozenset({TRUSTED_RUN_RECORD_SCHEMA})

# A run_id becomes a filename in the trusted store. Anything that could climb
# out of it — a separator, a drive letter, `..`, a reserved name — is refused
# before it is ever joined to a path.
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def is_storable_run_id(run_id: object) -> bool:
    """True for a run_id the trusted store will accept as a record name."""
    return (isinstance(run_id, str) and bool(_SAFE_RUN_ID.match(run_id))
            and ".." not in run_id)


class PublicationState(str, Enum):
    """Permission for authoritative evidence publication. Nothing else."""

    NOT_PUBLISHABLE = "NOT_PUBLISHABLE"
    PUBLISHABLE = "PUBLISHABLE"
    ANCHORED = "ANCHORED"


# Monotonic by construction: there is no edge back. A regression is not a
# transition this table merely omits — it is refused, loudly, by `transition`.
PUBLICATION_TRANSITIONS: MappingProxyType[PublicationState, frozenset[PublicationState]] = (
    MappingProxyType({
        PublicationState.NOT_PUBLISHABLE: frozenset({PublicationState.PUBLISHABLE}),
        PublicationState.PUBLISHABLE: frozenset({PublicationState.ANCHORED}),
        PublicationState.ANCHORED: frozenset(),
    }))


class PublicationVerdict(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    ALREADY_ANCHORED = "ALREADY_ANCHORED"
    REFUSED = "REFUSED"


@dataclass(frozen=True)
class TrustedRunRecord:
    """One run's immutable identity plus its monotonic publication state."""

    identity: RunIdentity
    publication_state: PublicationState
    anchor_record_digest: str | None = None
    schema: str = TRUSTED_RUN_RECORD_SCHEMA

    def __post_init__(self) -> None:
        if self.schema not in SUPPORTED_RUN_RECORD_SCHEMAS:
            raise AuthorityUnavailable(f"unknown trusted-run-record schema {self.schema!r}")
        if self.publication_state is PublicationState.ANCHORED:
            # ANCHORED is a claim that a valid AnchorRecord was produced AND
            # confirmed. It may not be reached without naming that record.
            if not isinstance(self.anchor_record_digest, str) or not _DIGEST.match(
                    self.anchor_record_digest):
                raise AuthorityUnavailable(
                    "ANCHORED requires the digest of the confirmed AnchorRecord; "
                    f"got {self.anchor_record_digest!r}")
        elif self.anchor_record_digest is not None:
            raise AuthorityUnavailable(
                f"a {self.publication_state.value} run cannot name an anchor record")

    @property
    def identity_digest(self) -> str:
        return self.identity.digest()

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "identity": self.identity.to_dict(),
                "publication_state": self.publication_state.value,
                "anchor_record_digest": self.anchor_record_digest}

    @classmethod
    def from_dict(cls, data: Any) -> TrustedRunRecord:
        if not isinstance(data, dict):
            raise AuthorityUnavailable("a trusted run record must be a JSON object")
        unknown = set(data) - {"schema", "identity", "publication_state",
                               "anchor_record_digest"}
        if unknown:
            raise AuthorityUnavailable(
                f"trusted run record carries unknown fields {sorted(unknown)}; "
                "an ambiguous trusted record is not a trusted record")
        identity = data.get("identity")
        if not isinstance(identity, dict):
            raise AuthorityUnavailable("trusted run record has no identity object")
        try:
            state = PublicationState(data.get("publication_state"))
        except ValueError as exc:
            raise AuthorityUnavailable(
                f"unknown publication state {data.get('publication_state')!r}") from exc
        try:
            run_identity = RunIdentity(**identity)
        except TypeError as exc:
            raise AuthorityUnavailable(f"trusted run identity is malformed: {exc}") from exc
        return cls(identity=run_identity, publication_state=state,
                   anchor_record_digest=data.get("anchor_record_digest"),
                   schema=data.get("schema", ""))


class TrustedRunIdentityStore:
    """The trust plane's own record of which runs exist and may be published.

    One JSON file per run, written torn-write-safe and under the kernel's
    established cross-process FileLock, so two trusted writers cannot silently
    drop one another's transition. `Worker WRITE = denied` is an ACL property
    the Stage-6/8 provisioning must establish; this class assumes it and does
    not simulate it.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def path_for(self, run_id: str) -> Path:
        if not is_storable_run_id(run_id):
            raise AuthorityUnavailable(
                f"run_id {run_id!r} is not a storable record name; refusing to "
                "build a trusted-store path from it")
        return self.root / f"{run_id}.json"

    def exists(self, run_id: str) -> bool:
        return self.path_for(run_id).is_file()

    def run_ids(self) -> tuple[str, ...]:
        """Every run this store holds a trusted record for.

        Needed by Stage-4 recovery, which must be able to ask the question the
        other direction — "does any run claim to be ANCHORED against a record
        that is not committed?" — and that question cannot be answered from a
        run_id the caller already knows. Only names the store itself could have
        written are returned: a lock file, a crash-leftover `.tmp-*` and any
        stray name that would not survive `is_storable_run_id` are skipped, so
        a foreign file dropped into the directory cannot become a run.
        """
        return tuple(sorted(p.stem for p in self.root.glob("*.json")
                            if p.is_file() and is_storable_run_id(p.stem)))

    def read(self, run_id: str) -> TrustedRunRecord:
        path = self.path_for(run_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise AuthorityUnavailable(f"no trusted identity for run {run_id}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthorityUnavailable(
                f"the trusted identity for run {run_id} is unreadable: {exc}") from exc
        record = TrustedRunRecord.from_dict(raw)
        if record.identity.run_id != run_id:
            raise AuthorityUnavailable(
                f"trusted record filed under {run_id} carries identity for "
                f"{record.identity.run_id}; refusing")
        return record

    def create(self, identity: RunIdentity) -> TrustedRunRecord:
        """Bind a run_id to its immutable identity, once.

        Idempotent for an IDENTICAL identity — a retry re-reads the existing
        record WITHOUT resetting its state. A DIFFERENT identity under a run_id
        that already exists is refused: that is exactly the delete-and-recreate
        (ABA) route by which old evidence could be presented as a new run's.
        """
        path = self.path_for(identity.run_id)
        with FileLock(lock_path_for(path)):
            if path.is_file():
                existing = self.read(identity.run_id)
                if existing.identity_digest != identity.digest():
                    raise AuthorityUnavailable(
                        f"run_id {identity.run_id} is already bound to a different "
                        "trusted identity; a run_id is never reused")
                return existing
            record = TrustedRunRecord(identity=identity,
                                      publication_state=PublicationState.NOT_PUBLISHABLE)
            atomic_write_text(path, json.dumps(record.to_dict(), indent=2, sort_keys=True))
            return record

    def transition(self, run_id: str, expected_identity_digest: str,
                   target: PublicationState, *,
                   anchor_record_digest: str | None = None) -> TrustedRunRecord:
        """Move a run's publication state FORWARD, under a compare-and-set.

        `expected_identity_digest` is what makes this safe: the caller states
        which identity it believes it is updating, and a record that is no
        longer exactly that one refuses the update rather than accepting a
        stale or ABA'd write. The identity itself is never carried in, so no
        transition can rewrite an immutable field.
        """
        path = self.path_for(run_id)
        with FileLock(lock_path_for(path)):
            current = self.read(run_id)
            if current.identity_digest != expected_identity_digest:
                raise AuthorityUnavailable(
                    f"run {run_id} no longer holds the expected identity "
                    f"({expected_identity_digest}); refusing a stale update")
            allowed = PUBLICATION_TRANSITIONS[current.publication_state]
            if target not in allowed:
                raise AuthorityUnavailable(
                    f"publication state {current.publication_state.value} -> "
                    f"{target.value} is not a permitted transition for run {run_id}; "
                    "publication state is monotonic")
            record = TrustedRunRecord(identity=current.identity,
                                      publication_state=target,
                                      anchor_record_digest=anchor_record_digest)
            atomic_write_text(path, json.dumps(record.to_dict(), indent=2, sort_keys=True))
            return record

    def mark_publishable(self, run_id: str, expected_identity_digest: str) -> TrustedRunRecord:
        """The ONLY route to PUBLISHABLE, and it is inside the trust plane.

        There is deliberately no path to this state from a bundle, a piece of
        evidence, an IPC message, a worker-writable file, a process return code
        or a self-reported status. In production the Director calls this after
        the required gates are satisfied; Stage 3 implements the contract, not
        that wiring.
        """
        return self.transition(run_id, expected_identity_digest,
                               PublicationState.PUBLISHABLE)

    def mark_anchored(self, run_id: str, expected_identity_digest: str,
                      anchor_record_digest: str) -> TrustedRunRecord:
        """Record that a valid AnchorRecord was produced and confirmed.

        Called AFTER the publisher has written and re-read the record — never
        before. The durable ORDERING of that write against this mark (the
        write-through watermark, crash recovery) is Stage 4 and is not
        simulated here.
        """
        if not isinstance(anchor_record_digest, str) or not _DIGEST.match(
                anchor_record_digest):
            raise AuthorityUnavailable(
                "marking ANCHORED requires the confirmed AnchorRecord digest; "
                f"got {anchor_record_digest!r}")
        return self.transition(run_id, expected_identity_digest,
                               PublicationState.ANCHORED,
                               anchor_record_digest=anchor_record_digest)


@dataclass(frozen=True)
class PublicationRequest:
    """The TRUSTED context a publication is judged against.

    Every field is supplied by the trust plane — the Director's own record of
    what it dispatched and the publisher's own view of its deployment. The only
    worker-influenced value anywhere in the flow is the bounded `run_id` that
    Stage 6 will carry over IPC, and by itself it authorizes nothing.
    """

    run_id: str
    expected_owner_worker_sid: str
    expected_deployment_digest: str
    expected_epoch: int
    expected_repository_id: str
    expected_head_sha: str
    expected_tree_identity: str


@dataclass(frozen=True)
class PublicationDecision:
    verdict: PublicationVerdict
    reason: str
    record: TrustedRunRecord | None = None

    @property
    def authorized(self) -> bool:
        return self.verdict is PublicationVerdict.AUTHORIZED


def authorize_publication(store: TrustedRunIdentityStore,
                          request: PublicationRequest) -> PublicationDecision:
    """Decide whether run `request.run_id` may be authoritatively anchored.

    A pure decision over trusted inputs: it reads the trusted store and compares
    it against the trusted request. It performs no I/O on the bundle, consults
    no worker-supplied field, and changes nothing — the caller performs the
    publication and the ANCHORED transition separately, so a refusal cannot
    leave half a state behind.
    """
    if not is_storable_run_id(request.run_id):
        return PublicationDecision(PublicationVerdict.REFUSED,
                                   f"run_id {request.run_id!r} is not a valid run id")
    try:
        record = store.read(request.run_id)
    except AuthorityUnavailable as exc:
        # Unknown, unreadable, mis-filed or schema-invalid all land here: an
        # identity that cannot be read authorizes nothing.
        return PublicationDecision(PublicationVerdict.REFUSED, str(exc))

    identity = record.identity
    if identity.run_id != request.run_id:
        return PublicationDecision(PublicationVerdict.REFUSED,
                                   "trusted identity is for a different run")

    # Identity binding first: a mismatched request must never be answered with
    # a state-flavoured verdict like ALREADY_ANCHORED, which would leak that a
    # different run exists and read as though the request nearly succeeded.
    for expected, actual, what in (
        (request.expected_owner_worker_sid, identity.owner_worker_sid, "owner_worker_sid"),
        (request.expected_deployment_digest, identity.deployment_digest, "deployment_digest"),
        (request.expected_repository_id, identity.repository_id, "repository_id"),
        (request.expected_head_sha, identity.head_sha, "head_sha"),
        (request.expected_tree_identity, identity.tree_identity, "tree_identity"),
    ):
        if expected != actual:
            return PublicationDecision(
                PublicationVerdict.REFUSED,
                f"{what} mismatch: run holds {actual!r}, expected {expected!r}",
                record)
    if request.expected_epoch != identity.epoch:
        return PublicationDecision(
            PublicationVerdict.REFUSED,
            f"epoch mismatch: run holds {identity.epoch}, expected "
            f"{request.expected_epoch} (an artifact authorized for one generation "
            "cannot be published as a later one)", record)

    if record.publication_state is PublicationState.ANCHORED:
        return PublicationDecision(
            PublicationVerdict.ALREADY_ANCHORED,
            f"run {request.run_id} is already anchored "
            f"({record.anchor_record_digest})", record)
    if record.publication_state is not PublicationState.PUBLISHABLE:
        return PublicationDecision(
            PublicationVerdict.REFUSED,
            f"run {request.run_id} is {record.publication_state.value}; only a "
            "trusted transition can make it PUBLISHABLE", record)
    return PublicationDecision(PublicationVerdict.AUTHORIZED, "", record)


def run_identity_digest(identity: RunIdentity) -> str:
    """The canonical digest of a run's immutable identity.

    Re-exported so a caller does not have to reach into the dataclass to get
    the value it must present to `transition`. Same ONE canonical primitive
    (ADR-0004) — there is no second hashing implementation."""
    return hash_canonical(identity.to_dict())
