"""Durable publication and crash recovery for the evidence anchor (F-17 Stage 4).

THE WINDOW THIS CLOSES. Stage 3 left a declared ambiguity: a run is
PUBLISHABLE, the publisher appends the anchor, the process dies, and the
trusted `RunIdentity` has not yet been marked ANCHORED. Nothing on disk then
says whether that anchor was authoritatively published or was the debris of an
attempt. Stage 4 removes the ambiguity.

ONE AUTHORITATIVE COMMIT POINT. The mistake this module refuses to make is
modelling "the anchor line is on disk" and "the publication state says
ANCHORED" as two independent decisions; two independent decisions are two
sources of truth, and after a crash they can disagree with nothing to arbitrate
between them. There is exactly ONE commit:

    THE DURABLE, RE-READ, LEDGER-VERIFIED COMMITTED WATERMARK.

The watermark names the record that is authoritatively published. Everything
else is derived from it:

    ledger        holds candidates. A record's presence proves nothing.
    watermark     says which record is COMMITTED. This is the commit.
    RunIdentity   PublicationState.ANCHORED is the CONSEQUENCE of the commit,
                  never a second authority. Recovery may complete it; recovery
                  may never manufacture it.

So the crash window has exactly two sides, and both are decidable:

    crash BEFORE the watermark commit   the record is NOT committed. The run
                                        stays PUBLISHABLE and a provably
                                        uncommitted tail may be discarded.
    crash AFTER the watermark commit    the record IS committed. Even with the
                                        state still PUBLISHABLE, recovery
                                        reconciles it to ANCHORED — WITHOUT
                                        writing a second anchor.

NEVER ANCHORED FIRST. Marking `RunIdentity` ANCHORED before the durable
watermark commit is forbidden. An ANCHORED state with no corresponding commit
is corruption, and the response is to fail closed, never to fabricate the
anchor that would make it true.

GUARANTEE SCOPE, STATED HONESTLY.

    process crash          GUARANTEED.
    service crash          GUARANTEED.
    power loss / storage   BEST EFFORT, EXPLICITLY BOUNDED — NOT guaranteed.

Data is flushed to the storage stack (os.fsync, i.e. FlushFileBuffers on
Windows) before each commit step, and the watermark is replaced atomically
(temp + os.replace, the reused `kernel.atomic_io` primitive). What is NOT on
offer is a durability barrier for the rename's own metadata: Windows exposes no
directory fsync, NTFS journals the rename, and a journalled rename is not a
proof. Nothing here is power-loss proof and nothing here claims to be. The
fault injection in this module is PROCESS/SERVICE CRASH injection; it is never
described as an OS-real power-loss test.

TRUST. The watermark belongs to the Trust Plane. It lives beside the ledger in
the publisher-owned root, is never read from an IPC message, a bundle, a
worker-writable location or any worker-supplied value, and it is never inferred
from the ledger's own tail — inferring it would promote an uncommitted record
to committed, which is precisely the failure this module exists to prevent.
`Worker WRITE = DENIED` on that root is an ACL property Stage 6/8 must
establish; this module assumes it and does not simulate it. `FileLock` here is
TRUSTED-WRITER COORDINATION — it stops two trusted publishers racing — and is
NOT a security boundary against a worker; it is not claimed to be one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from gnosis.kernel.atomic_io import atomic_write_bytes
from gnosis.kernel.canonical import GENESIS_HASH, canonical_json_bytes
from gnosis.kernel.file_lock import FileLock, lock_path_for
from gnosis.trust.anchor import (
    AnchorRecord,
    AnchorStore,
    RunIdentity,
    build_anchor_record,
    parse_record_line,
)
from gnosis.trust.launch import AuthorityUnavailable
from gnosis.trust.run_identity import (
    PublicationRequest,
    PublicationState,
    PublicationVerdict,
    TrustedRunIdentityStore,
    authorize_publication,
)

WATERMARK_SCHEMA = "gnosis.trust.watermark.v1"
SUPPORTED_WATERMARK_SCHEMAS = frozenset({WATERMARK_SCHEMA})
WATERMARK_FILE = "anchors.watermark.json"


class PublicationCorrupt(AuthorityUnavailable):
    """The durable publication state is internally inconsistent.

    Deliberately distinct from an ordinary refusal, because the operator
    response is different: a refusal means "not now, this request is not
    authorized"; this means "the trust plane's own record of what is published
    does not add up, and no retry can fix it". Retrying is meaningless and
    repairing it automatically would mean guessing at which of two
    contradictory statements is true. Fail closed and require a human.
    """


class LedgerNotUnderDurableProtocol(AuthorityUnavailable):
    """The ledger holds records but no committed watermark.

    NOT corruption — it is what a pre-Stage-4 ledger looks like. It is still
    refused, because the only way to proceed would be to infer a watermark from
    the ledger's last record, and that would silently promote a record that may
    never have been committed. Adopting an existing ledger into the durable
    protocol is a deliberate operator act with the committed record named
    explicitly; it is not something this module may do on anyone's behalf.
    """


# ---------------------------------------------------------------------------
# The deterministic fault seam. TESTS ONLY.
#
# `_FAULT_HOOK` is a module-private global that DEFAULTS TO None. There is no
# environment variable, no configuration file, no command-line flag, no IPC
# message and no worker-supplied value anywhere in this module that can set it:
# the only way to install one is for in-process code to assign the private name
# after importing this module, and any code that can do that is already inside
# the TCB. The seam therefore grants a worker nothing.
#
# The points, in protocol order:
#   F0 before the append            F5 watermark temp write
#   F1 the ledger write itself      F6 watermark temp flushed, before replace
#   F2 written, before flush        F7 watermark committed, before the state
#   F3 after the ledger flush       F8 during the RunIdentity transition
#   F4 after the ledger re-verify   F9 state durably ANCHORED, before the reply
# ---------------------------------------------------------------------------
_FAULT_HOOK: Any = None


def _fault(point: str, **context: Any) -> None:
    hook = _FAULT_HOOK
    if hook is not None:
        hook(point, **context)


# ---------------------------------------------------------------------------
# The committed watermark
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CommittedWatermark:
    """The single authoritative statement of what is published.

    WHY THESE FIELDS AND NO OTHERS. The requirement is that a watermark for
    record A can never validate record B, even when they share a sequence
    number. `committed_record_digest` gives exactly that: the digest covers the
    WHOLE record, so it already binds — unambiguously, and with no way for the
    two to drift apart — the chain position (`prev_record_digest`), the trust
    plane (`deployment_digest`), the exact authorized run
    (`run_identity_digest`, itself covering owner SID, epoch, head and tree),
    the run_id and the bundle digest.

    Every one of those was therefore evaluated and DELIBERATELY NOT COPIED
    here. A copy could not detect anything the digest does not already detect,
    and the project has learned once already (mutant RM13) what an unfailable
    check costs: it reads as load-bearing while the real refusal comes from
    somewhere else. A watermark field that cannot disagree is not a check, it
    is a second place for the truth to live.

    `committed_seq` is not a copy: it is the INDEX. It says which ledger line
    to look at, and the digest then says whether that line is the right one, so
    editing it alone is caught.

    GENESIS. `committed_seq = -1` with `committed_record_digest = GENESIS_HASH`
    is the watermark of a store where NOTHING has been committed yet. It exists
    so that "this store is under the durable protocol and has committed
    nothing" is a written statement rather than an absence — see
    `initialise_durable_store` for why an absence could not be trusted to mean
    the same thing. It reuses the chain's own convention for "before the first
    record" instead of inventing a second one.
    """

    committed_seq: int
    committed_record_digest: str
    schema: str = WATERMARK_SCHEMA

    def __post_init__(self) -> None:
        if self.schema not in SUPPORTED_WATERMARK_SCHEMAS:
            raise PublicationCorrupt(f"unknown watermark schema {self.schema!r}")
        if (isinstance(self.committed_seq, bool)
                or not isinstance(self.committed_seq, int) or self.committed_seq < -1):
            raise PublicationCorrupt(
                f"committed_seq must be -1 (genesis) or a record index; "
                f"got {self.committed_seq!r}")
        digest = self.committed_record_digest
        if not isinstance(digest, str) or len(digest) != 64 or any(
                c not in "0123456789abcdef" for c in digest):
            raise PublicationCorrupt(
                "committed_record_digest must be a 64-character lowercase hex "
                f"digest; got {digest!r}")
        # The two fields must tell the same story. A watermark that commits
        # nothing while naming a record, or commits a record while naming
        # GENESIS, is not a statement anyone can act on.
        if (self.committed_seq < 0) != (digest == GENESIS_HASH):
            raise PublicationCorrupt(
                f"a watermark at sequence {self.committed_seq} cannot carry digest "
                f"{digest}; genesis and only genesis names the genesis hash")

    @property
    def commits_nothing(self) -> bool:
        return self.committed_seq < 0

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "committed_seq": self.committed_seq,
                "committed_record_digest": self.committed_record_digest}

    @classmethod
    def from_dict(cls, data: Any) -> CommittedWatermark:
        if not isinstance(data, dict):
            raise PublicationCorrupt("a watermark must be a JSON object")
        unknown = set(data) - {"schema", "committed_seq", "committed_record_digest"}
        if unknown:
            raise PublicationCorrupt(
                f"the watermark carries unknown fields {sorted(unknown)}; an "
                "ambiguous commit statement is not a commit statement")
        missing = {"schema", "committed_seq", "committed_record_digest"} - set(data)
        if missing:
            raise PublicationCorrupt(f"the watermark is missing {sorted(missing)}")
        return cls(committed_seq=data["committed_seq"],
                   committed_record_digest=data["committed_record_digest"],
                   schema=data["schema"])


GENESIS_WATERMARK = CommittedWatermark(committed_seq=-1,
                                       committed_record_digest=GENESIS_HASH)


def watermark_path(root: Path) -> Path:
    return root / WATERMARK_FILE


def read_watermark(root: Path) -> CommittedWatermark | None:
    """The committed watermark, or None when NOTHING has ever been committed.

    None means EXACTLY ONE thing: the file is absent. A watermark that exists
    but cannot be understood — truncated, empty, not JSON, wrong schema, extra
    fields, a malformed digest — is NEVER read as None. Treating a damaged
    commit statement as "nothing is committed" would let an already-committed
    record be re-published, or a committed history be discarded as a tail.
    """
    path = watermark_path(root)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PublicationCorrupt(f"the committed watermark is unreadable: {exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicationCorrupt(
            f"the committed watermark is malformed ({exc}); it is NOT treated as "
            "an empty watermark, and it is never rebuilt from the ledger's last "
            "record — that would commit a record that may never have been "
            "committed") from exc
    return CommittedWatermark.from_dict(data)


def _commit_watermark(root: Path, watermark: CommittedWatermark) -> None:
    """Replace the authoritative watermark, durably and atomically.

    Reuses `kernel.atomic_io` — temp file, write, flush, fsync, single atomic
    os.replace — rather than re-implementing a second atomic-replace primitive
    inside the Trust Plane. The authoritative file is NEVER overwritten in
    place, so it cannot be observed half-written: a reader sees the whole old
    watermark or the whole new one. A crash leaves at most a stray `.tmp-*`
    beside it, which nothing ever reads.
    """
    atomic_write_bytes(watermark_path(root), canonical_json_bytes(watermark.to_dict()))


def initialise_durable_store(store: AnchorStore) -> CommittedWatermark:
    """Make sure this store has a watermark, and return it.

    WHY AN EXPLICIT GENESIS WATERMARK RATHER THAN "no file means nothing
    committed". Because those are two different situations that a missing file
    cannot tell apart. A publisher that crashes mid-way through the FIRST
    publication leaves a record — or half of one — in a ledger that has no
    watermark yet; so does a ledger written before this protocol existed, whose
    records may be perfectly committed history. Reading "no file" as "nothing
    is committed" would let the first case be repaired and the second be
    silently demoted to debris. Writing the genesis watermark BEFORE anything
    can be appended removes the ambiguity at its source: from then on the
    absence of a watermark means only one thing — this store is not under the
    durable protocol.

    Initialising is therefore allowed in EXACTLY one situation, where it can
    commit nothing: an empty ledger. A store that already holds records and has
    no watermark is refused. Adopting such a ledger is an operator act that
    names the committed record explicitly; it is never inferred here.
    """
    existing = read_watermark(store.root)
    if existing is not None:
        return existing
    try:
        raw = store.ledger.read_bytes()
    except FileNotFoundError:
        raw = b""
    except OSError as exc:
        raise PublicationCorrupt(f"the anchor ledger is unreadable: {exc}") from exc
    if raw.strip():
        raise LedgerNotUnderDurableProtocol(
            "this anchor ledger already holds content but no committed watermark, "
            "so which of its records were authoritatively published is unknown. A "
            "watermark is never inferred from the ledger's last record: that would "
            "declare a record committed which may only ever have been a crashed "
            "attempt. Adopting an existing ledger into the durable protocol is an "
            "explicit operator act that names the committed record.")
    _commit_watermark(store.root, GENESIS_WATERMARK)
    written = read_watermark(store.root)
    if written != GENESIS_WATERMARK:
        raise PublicationCorrupt("the genesis watermark did not read back as written")
    return written


# ---------------------------------------------------------------------------
# The ledger, read as BYTES
#
# `AnchorStore.records()` fails closed on any unreadable line, which is right
# for the chain but useless after a crash: a half-written tail line would make
# the whole ledger unreadable, including the committed history that is
# perfectly intact in front of it. Recovery therefore reads the ledger at the
# byte level, cuts it at the committed record's line boundary, and treats what
# follows as opaque bytes it has not yet earned the right to interpret.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _ScannedLine:
    index: int          # record index; blank lines are not counted
    data: bytes         # the line WITHOUT its terminator
    end_offset: int     # byte offset just past this line's terminator


def _scan_ledger(raw: bytes) -> tuple[tuple[_ScannedLine, ...], bytes]:
    """Split raw ledger bytes into COMPLETE lines and a trailing partial.

    A line is complete only if it is terminated. Whatever follows the last
    terminator is a partial write by definition — the writer did not finish.
    Both LF and CRLF are accepted because ledgers written before Stage 4 went
    through Python text mode on Windows.
    """
    lines: list[_ScannedLine] = []
    index = 0
    start = 0
    while True:
        newline = raw.find(b"\n", start)
        if newline < 0:
            break
        end = newline + 1
        chunk = raw[start:newline]
        if chunk.endswith(b"\r"):
            chunk = chunk[:-1]
        if chunk.strip():
            lines.append(_ScannedLine(index=index, data=chunk, end_offset=end))
            index += 1
        start = end
    return tuple(lines), raw[start:]


def _parse_scanned(line: _ScannedLine) -> AnchorRecord:
    try:
        text = line.data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicationCorrupt(
            f"anchor ledger record {line.index} is not valid UTF-8: {exc}") from exc
    return parse_record_line(text, where=f"anchor ledger record {line.index}")


@dataclass(frozen=True)
class LedgerSplit:
    """The ledger cut at the commit point: committed history, then a tail."""

    committed: tuple[AnchorRecord, ...]
    committed_end_offset: int
    tail_complete_records: int
    tail_partial_bytes: int
    raw: bytes

    @property
    def tail_bytes(self) -> int:
        return len(self.raw) - self.committed_end_offset

    @property
    def has_tail(self) -> bool:
        return self.tail_bytes > 0

    @property
    def committed_digests(self) -> frozenset[str]:
        return frozenset(record.digest() for record in self.committed)


def split_ledger(ledger: Path, watermark: CommittedWatermark) -> LedgerSplit:
    """Cut the ledger at the committed record, verifying everything in front.

    Fails closed — never guesses — on every way the two can disagree:
      * a watermark naming a record the ledger does not have (case F);
      * a watermark whose digest is not the record at that sequence (case G);
      * a chain that does not verify inside the committed prefix (case H).

    A GENESIS watermark commits nothing, so the committed prefix is empty and
    the whole ledger is tail. That is not a licence to delete it: the tail rules
    below still have to prove the bytes came from a single interrupted attempt.
    """
    try:
        raw = ledger.read_bytes()
    except FileNotFoundError:
        raw = b""
    except OSError as exc:
        raise PublicationCorrupt(f"the anchor ledger is unreadable: {exc}") from exc
    scanned, partial = _scan_ledger(raw)

    if watermark.commits_nothing:
        return LedgerSplit(committed=(), committed_end_offset=0,
                           tail_complete_records=len(scanned),
                           tail_partial_bytes=len(partial), raw=raw)

    if watermark.committed_seq >= len(scanned):
        raise PublicationCorrupt(
            f"the watermark commits record {watermark.committed_seq} but the ledger "
            f"holds only {len(scanned)} complete record(s); the committed history "
            "is missing and must not be reconstructed")

    committed: list[AnchorRecord] = []
    prev = GENESIS_HASH
    for line in scanned[: watermark.committed_seq + 1]:
        record = _parse_scanned(line)
        if record.seq != line.index or record.prev_record_digest != prev:
            raise PublicationCorrupt(
                f"the anchor chain breaks at committed record {line.index}: it "
                f"carries seq {record.seq} and prev {record.prev_record_digest}, "
                f"expected {line.index} and {prev}. Committed history is never "
                "truncated to make a chain verify.")
        prev = record.digest()
        committed.append(record)

    head_digest = committed[-1].digest()
    if head_digest != watermark.committed_record_digest:
        raise PublicationCorrupt(
            f"the watermark commits digest {watermark.committed_record_digest} at "
            f"sequence {watermark.committed_seq}, but the record there digests to "
            f"{head_digest}. A watermark for one record can never validate another.")

    end = scanned[watermark.committed_seq].end_offset
    return LedgerSplit(
        committed=tuple(committed), committed_end_offset=end,
        tail_complete_records=len(scanned) - (watermark.committed_seq + 1),
        tail_partial_bytes=len(partial), raw=raw)


def _assert_tail_is_provably_uncommitted(split: LedgerSplit) -> None:
    """The tail-truncation gate. Deliberately narrow.

    "Anything after the watermark may be truncated" is the dangerous version of
    this primitive, and it is not what this does. Discarding bytes is only
    allowed when they can be shown to belong to a single interrupted attempt,
    which the protocol bounds tightly: a publication appends EXACTLY ONE record
    and truncates any leftover tail BEFORE appending, so at any instant the
    ledger can hold at most one uncommitted record, or one partial line, and
    never both. Anything richer than that did not come from this protocol, so
    it is not "a tail" — it is an inconsistency, and it fails closed.

    That no ANCHORED run depends on these bytes is NOT re-checked here: the
    caller has already refused any run whose ANCHORED state names a digest
    outside the committed prefix, and every tail record is outside it by
    construction. Re-asserting it would add a check that cannot fail.
    """
    if not split.has_tail:
        return
    if split.tail_complete_records > 1:
        raise PublicationCorrupt(
            f"the ledger holds {split.tail_complete_records} complete records beyond "
            "the committed watermark. A single publication can leave at most one, so "
            "this did not come from the durable protocol; refusing to discard "
            "records on a guess.")
    if split.tail_complete_records == 1 and split.tail_partial_bytes:
        raise PublicationCorrupt(
            "the ledger holds a complete uncommitted record AND a partial line "
            "after it; the durable protocol cannot produce both, so the tail "
            "cannot be shown to be uncommitted debris")


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RecoveryReport:
    """What recovery found and what it did. Every field is observed, not assumed."""

    committed_seq: int
    committed_record_digest: str
    reconciled_run_ids: tuple[str, ...] = ()
    healthy_run_ids: tuple[str, ...] = ()
    foreign_deployment_run_ids: tuple[str, ...] = ()
    legacy_v1_records: int = 0
    uncommitted_tail_records: int = 0
    uncommitted_tail_bytes: int = 0
    tail_discarded: bool = False

    @property
    def has_uncommitted_tail(self) -> bool:
        return self.uncommitted_tail_bytes > 0


def _assert_record_matches_identity(record: AnchorRecord, identity: RunIdentity) -> None:
    """A committed record must be the record of EXACTLY this authorized run.

    `run_identity_digest` alone would answer the question, but the record also
    carries its own copies of the run's task, repository, head, tree and bundle
    path, and those copies are what a reader of the ledger actually sees. A
    record whose visible fields disagree with the identity its digest claims is
    inconsistent whichever half is wrong, so every one of them is compared:
    each comparison can genuinely fail, and each failure means something
    different to whoever has to read the message.
    """
    if not record.is_deployment_bound:
        raise PublicationCorrupt(
            f"the committed record for run {record.run_id} is a {record.schema} "
            "record: it carries no deployment or run-identity binding, so it can "
            "never be reconciled against a trusted identity")
    for actual, expected, what in (
        (record.run_id, identity.run_id, "run_id"),
        (record.task_id, identity.task_id, "task_id"),
        (record.repository_id, identity.repository_id, "repository_id"),
        (record.head_sha, identity.head_sha, "head_sha"),
        (record.tree_identity, identity.tree_identity, "tree_identity"),
        (record.bundle_path, identity.bundle_path, "bundle_path"),
        (record.deployment_digest, identity.deployment_digest, "deployment_digest"),
        (record.run_identity_digest, identity.digest(), "run_identity_digest"),
    ):
        if actual != expected:
            raise PublicationCorrupt(
                f"the committed record for run {record.run_id} names {what} "
                f"{actual!r}, but the trusted identity holds {expected!r}; a "
                "committed anchor and the run it claims to publish may not disagree")


def reconcile_publication_state(
        store: AnchorStore, run_store: TrustedRunIdentityStore, *,
        expected_deployment_digest: str,
        repair_uncommitted_tail: bool = False) -> RecoveryReport:
    """Bring durable publication state into agreement with the commit point.

    The recovery matrix, in the order the checks run:

      E  a run says ANCHORED, the watermark does not confirm it   FAIL CLOSED
      F  the watermark names a record the ledger does not hold    FAIL CLOSED
      G  the watermark's digest is not the record at that seq     FAIL CLOSED
      H  the chain breaks inside the committed prefix             FAIL CLOSED
      J  the watermark is malformed                               FAIL CLOSED
      D  committed, and the run already says ANCHORED             healthy
      C  committed, and the run still says PUBLISHABLE            RECONCILE
      A  nothing committed for the run                            normal retry
      B  a complete uncommitted record past the watermark         tail
      I  a partial line past the watermark                        tail

    A tail is DETECTED and validated whether or not repair was authorized;
    `repair_uncommitted_tail` only decides whether it is discarded.
    """
    watermark = read_watermark(store.root)
    if watermark is None:
        raise LedgerNotUnderDurableProtocol(
            "this anchor store has no committed watermark, so there is no commit "
            "point to reconcile against; it is not under the durable protocol")
    split = split_ledger(store.ledger, watermark)
    committed_digests = split.committed_digests

    # --- E: no run may claim to be anchored against something uncommitted ---
    # Run FIRST and over the WHOLE store: this is the direction that catches a
    # state which has run ahead of the commit point, and it is also what makes
    # discarding a tail safe further down (no ANCHORED run can name a record
    # outside the committed prefix once this has passed).
    for run_id in run_store.run_ids():
        try:
            trusted = run_store.read(run_id)
        except AuthorityUnavailable as exc:
            raise PublicationCorrupt(
                f"the trusted store holds an unreadable record for run {run_id}: "
                f"{exc}") from exc
        if trusted.publication_state is not PublicationState.ANCHORED:
            continue
        if trusted.anchor_record_digest not in committed_digests:
            raise PublicationCorrupt(
                f"run {run_id} is ANCHORED against record "
                f"{trusted.anchor_record_digest}, which the committed watermark "
                "does not confirm. An ANCHORED state with no durable commit behind "
                "it is corruption; it is NOT repaired by fabricating the anchor "
                "that would make it true.")

    reconciled: list[str] = []
    healthy: list[str] = []
    foreign: list[str] = []
    legacy = 0

    for record in split.committed:
        if not record.is_deployment_bound:
            # Historical V1 evidence. It carries no binding, so it can neither
            # prove nor produce a modern ANCHORED state. It is counted and left
            # exactly as it is; no default is invented to make it look bound.
            legacy += 1
            continue
        try:
            trusted = run_store.read(record.run_id)
        except AuthorityUnavailable as exc:
            raise PublicationCorrupt(
                f"committed record {record.seq} publishes run {record.run_id}, for "
                f"which the trust plane holds no readable identity: {exc}") from exc
        identity = trusted.identity
        _assert_record_matches_identity(record, identity)

        if identity.deployment_digest != expected_deployment_digest:
            # Committed by ANOTHER trust-plane deployment. Recovery does not get
            # to ignore the binding just because the record is already on disk.
            if trusted.publication_state is PublicationState.ANCHORED:
                foreign.append(record.run_id)
                continue
            raise PublicationCorrupt(
                f"run {record.run_id} has a committed anchor bound to deployment "
                f"{identity.deployment_digest}, but this is deployment "
                f"{expected_deployment_digest}; refusing to reconcile a "
                "publication across deployments")

        state = trusted.publication_state
        if state is PublicationState.ANCHORED:
            if trusted.anchor_record_digest != record.digest():
                raise PublicationCorrupt(
                    f"run {record.run_id} is ANCHORED against "
                    f"{trusted.anchor_record_digest}, but its committed record "
                    f"digests to {record.digest()}")
            healthy.append(record.run_id)
        elif state is PublicationState.PUBLISHABLE:
            # CASE C. The commit happened; only the consequence is missing.
            run_store.mark_anchored(record.run_id, identity.digest(), record.digest())
            after = run_store.read(record.run_id)
            if (after.publication_state is not PublicationState.ANCHORED
                    or after.anchor_record_digest != record.digest()):
                raise PublicationCorrupt(
                    f"the reconciled ANCHORED state for run {record.run_id} did not "
                    "read back as written")
            reconciled.append(record.run_id)
        else:
            raise PublicationCorrupt(
                f"run {record.run_id} has a committed anchor but is "
                f"{state.value}: a run that was never PUBLISHABLE cannot have been "
                "authoritatively published")

    _assert_tail_is_provably_uncommitted(split)
    tail_records = split.tail_complete_records
    tail_bytes = split.tail_bytes
    discarded = False
    if split.has_tail and repair_uncommitted_tail:
        atomic_write_bytes(store.ledger, split.raw[: split.committed_end_offset])
        after_split = split_ledger(store.ledger, watermark)
        if after_split.has_tail or after_split.committed_digests != committed_digests:
            raise PublicationCorrupt(
                "discarding the uncommitted tail did not leave exactly the "
                "committed history behind")
        discarded = True

    return RecoveryReport(
        committed_seq=watermark.committed_seq,
        committed_record_digest=watermark.committed_record_digest,
        reconciled_run_ids=tuple(reconciled), healthy_run_ids=tuple(healthy),
        foreign_deployment_run_ids=tuple(foreign), legacy_v1_records=legacy,
        uncommitted_tail_records=tail_records, uncommitted_tail_bytes=tail_bytes,
        tail_discarded=discarded)


# ---------------------------------------------------------------------------
# The durable publication protocol
# ---------------------------------------------------------------------------
class PublishOutcome(str, Enum):
    ANCHORED = "ANCHORED"
    ALREADY_ANCHORED = "ALREADY_ANCHORED"


@dataclass(frozen=True)
class PublicationResult:
    outcome: PublishOutcome
    record: AnchorRecord
    watermark: CommittedWatermark
    recovery: RecoveryReport


def _assert_watermark_advances(
        old: CommittedWatermark, new: CommittedWatermark) -> None:
    """One publication commits exactly one record, so the watermark moves by
    exactly one. A jump would mean records nobody verified became committed;
    standing still or going back would mean a commit was undone."""
    expected = old.committed_seq + 1
    if new.committed_seq != expected:
        raise PublicationCorrupt(
            f"a commit moves the watermark from {old.committed_seq} to {expected}, "
            f"not to {new.committed_seq}")


def durable_publish(
        store: AnchorStore, run_store: TrustedRunIdentityStore,
        request: PublicationRequest, bundle_dir: Path, *,
        verify: Any = None, repair_uncommitted_tail: bool = True) -> PublicationResult:
    """Publish run `request.run_id`'s evidence, durably, exactly once.

    Holds the trusted publication lock for the whole protocol so two trusted
    publishers cannot produce two records at the same sequence, two commits, or
    a watermark race. Returns ALREADY_ANCHORED — never a second anchor — when
    the run is already committed, including when the previous attempt's reply
    was lost after the commit point.
    """
    with FileLock(lock_path_for(store.ledger)):
        return _publish_locked(store, run_store, request, bundle_dir,
                               verify=verify,
                               repair_uncommitted_tail=repair_uncommitted_tail)


def _publish_locked(
        store: AnchorStore, run_store: TrustedRunIdentityStore,
        request: PublicationRequest, bundle_dir: Path, *,
        verify: Any, repair_uncommitted_tail: bool) -> PublicationResult:
    # 0. A store with no watermark at all is either brand new (safe to
    #    initialise: an empty ledger commits nothing) or a ledger this protocol
    #    did not write (refused; see initialise_durable_store).
    initialise_durable_store(store)

    # 1. Reconcile FIRST. A crash may have committed this very run's anchor
    #    while leaving its state PUBLISHABLE, and authorizing before reconciling
    #    would read that state at face value and write a SECOND anchor.
    report = reconcile_publication_state(
        store, run_store, expected_deployment_digest=request.expected_deployment_digest,
        repair_uncommitted_tail=repair_uncommitted_tail)
    if report.has_uncommitted_tail and not report.tail_discarded:
        raise AuthorityUnavailable(
            f"the ledger holds {report.uncommitted_tail_bytes} uncommitted byte(s) "
            "past the committed watermark; appending after them would chain a "
            "record nobody committed into the committed history. Repair was not "
            "authorized, so this fails closed.")

    # 2. Identity and lifecycle authorization, from the trusted store only.
    decision = authorize_publication(run_store, request)
    if decision.verdict is PublicationVerdict.REFUSED or decision.record is None:
        raise AuthorityUnavailable(f"publication refused: {decision.reason}")
    trusted = decision.record
    identity = trusted.identity

    watermark = read_watermark(store.root)
    if watermark is None:  # pragma: no cover - initialise_durable_store wrote it
        raise PublicationCorrupt("the committed watermark vanished under the lock")
    split = split_ledger(store.ledger, watermark)

    # 3. Already committed -> the deterministic idempotent answer. The record
    #    it names was validated against this exact identity during reconcile;
    #    a run_id that merely appears in the ledger never gets this answer,
    #    because the verdict itself comes from the trusted store after the full
    #    identity comparison (owner SID, deployment, epoch, head, tree).
    if decision.verdict is PublicationVerdict.ALREADY_ANCHORED:
        for record in split.committed:
            if record.digest() == trusted.anchor_record_digest:
                return PublicationResult(PublishOutcome.ALREADY_ANCHORED, record,
                                         watermark, report)
        raise PublicationCorrupt(
            f"run {identity.run_id} is ANCHORED against "
            f"{trusted.anchor_record_digest}, which is not in the committed history")

    # 4. Build the record from the DIRECTOR'S identity and the bundle bytes.
    _fault("F0", store=store, identity=identity)
    record = build_anchor_record(store, identity, bundle_dir, verify)

    # 5. Append exactly one record, durably. F1/F2 live inside the write.
    store.append(record, fault=_FAULT_HOOK)
    _fault("F3", store=store, record=record)

    # 6. Re-open the ledger, re-read it FROM DISK and verify it against the
    #    watermark this publication is about to commit — BEFORE committing it.
    #    `split_ledger` is the whole of steps "verify the chain" and "the exact
    #    expected record is present": it re-parses every record up to the new
    #    sequence, re-checks every chain link, and confirms that the record at
    #    that sequence digests to exactly the record that was written. Doing it
    #    here rather than after the commit is what stops a ledger that changed
    #    underneath the publisher from being committed and only then noticed.
    new_watermark = CommittedWatermark(committed_seq=record.seq,
                                       committed_record_digest=record.digest())
    _assert_watermark_advances(watermark, new_watermark)
    prospective = split_ledger(store.ledger, new_watermark)
    if prospective.has_tail:
        # Under the publication lock nothing else can have appended, so this is
        # the concurrency backstop rather than an expected outcome: it says the
        # append added exactly one record and nothing else arrived beside it.
        raise PublicationCorrupt(
            "the ledger grew beyond the record that was just appended; another "
            "writer is active and this publication will not commit over it")
    _fault("F4", store=store, record=record)

    # 7. THE COMMIT. Until the watermark is durable, re-read and confirmed
    #    against the ledger, the record above is a candidate and nothing more.
    # F5 and F6 share this locus deliberately. The temp write, its flush and the
    # atomic replace all happen inside the REUSED kernel primitive, and Stage 4
    # does not add a test seam to a kernel module the worker plane also uses. Each
    # point is instead modelled by the filesystem state a crash there leaves
    # behind — F5 a partial temp file, F6 a complete one — beside an untouched
    # authoritative watermark. That is the state recovery must survive, and the
    # property proven is the one that matters: a crash anywhere in the watermark
    # write leaves the OLD watermark authoritative and no temp is ever adopted.
    _fault("F5", root=store.root, watermark=new_watermark)
    _fault("F6", root=store.root, watermark=new_watermark)
    _commit_watermark(store.root, new_watermark)
    committed = read_watermark(store.root)
    if committed != new_watermark:
        raise PublicationCorrupt("the committed watermark did not read back as written")
    # And the value that is NOW authoritative must still resolve against the
    # ledger. `split_ledger` is the verification: it re-reads from disk and
    # raises unless the whole chain checks out and the record at the committed
    # sequence is exactly the one named. It is called for that refusal.
    split_ledger(store.ledger, committed)
    # ------------------- COMMITTED. The anchor is published. -------------------

    # 8. The CONSEQUENCE of the commit, never a second commit. A crash from here
    #    on leaves recovery able to complete it from the watermark alone.
    _fault("F7", run_store=run_store, identity=identity, record=record)
    _fault("F8", run_store=run_store, identity=identity, record=record)
    run_store.mark_anchored(identity.run_id, identity.digest(), record.digest())
    final = run_store.read(identity.run_id)
    if (final.publication_state is not PublicationState.ANCHORED
            or final.anchor_record_digest != record.digest()):
        raise PublicationCorrupt("the ANCHORED transition did not read back as written")
    _fault("F9", run_store=run_store, identity=identity, record=record)
    return PublicationResult(PublishOutcome.ANCHORED, record, committed, report)
