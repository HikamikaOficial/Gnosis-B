"""F-17 Stage 4 — durable publication, one commit point, crash recovery.

The property under test:

    THERE IS NO CRASH POINT AT WHICH THE TRUST PLANE SAYS ANCHORED WITHOUT A
    DURABLE COMMIT BEHIND IT, AND NO CRASH POINT FROM WHICH A RETRY PRODUCES A
    SECOND ANCHOR.

Every case below is a way that could fail to hold: a record on disk that was
never committed being read as published, a committed record whose state update
was lost being re-published, a watermark for one record validating another, a
malformed commit statement being read as "nothing is committed", committed
history being discarded as a crashed attempt, two trusted publishers racing.

WHAT THE CRASH TESTS ARE. `TestProcessCrashAtEveryFaultPoint` kills a REAL
child process with `os._exit`, which runs no cleanup, no `atexit` and no buffer
flush — a faithful process/service crash. It is NOT a power-loss test and is
never described as one: the guarantee this file evidences is
process-crash/service-crash, with physical power and storage failure explicitly
out of scope. The in-process fault tests model the same interruption points
more cheaply, by stopping the protocol dead at a point instead of killing the
interpreter; both are reported for what they are.

Nothing here installs anything: no worker account, no service, no launcher, no
pipe, no ACL. The stores are temporary directories on the real NTFS volume,
which is what makes the flush, the atomic replacement and the file locking real
rather than simulated.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from gnosis.kernel.canonical import GENESIS_HASH, canonical_json_bytes
from gnosis.kernel.evidence_capture import write_bundle_manifest
from gnosis.trust.anchor import (
    ANCHOR_SCHEMA,
    AnchorRecord,
    AnchorStore,
    AuthorityUnavailable,
    RunIdentity,
    record_line,
)
from gnosis.trust.launch import AuthorityUnavailable as LaunchUnavailable
from gnosis.trust.launch import process_integrity
from gnosis.trust.publication import (
    GENESIS_WATERMARK,
    WATERMARK_FILE,
    CommittedWatermark,
    LedgerNotUnderDurableProtocol,
    PublicationCorrupt,
    PublishOutcome,
    durable_publish,
    initialise_durable_store,
    read_watermark,
    reconcile_publication_state,
    split_ledger,
    watermark_path,
)
from gnosis.trust.run_identity import (
    PublicationRequest,
    PublicationState,
    TrustedRunIdentityStore,
)

SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"
SID_OTHER = "S-1-5-21-1111111111-2222222222-3333333333-1002"
DEPLOY = "d" * 64
DEPLOY_OTHER = "f" * 64
HEAD = "h" * 40


def _is_high() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return process_integrity() == "High"
    except LaunchUnavailable:
        return False


HIGH_ONLY = unittest.skipUnless(
    _is_high(), "an AnchorStore may only be created by a HIGH-integrity publisher")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _make_bundle(path: Path, head_sha: str = HEAD, content_digest: str = "cd0") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "pytest.stdout.txt").write_text("ok\n", encoding="utf-8")
    (path / "SUMMARY.json").write_text(json.dumps({
        "tree_identity": {"post": {"fingerprint": {"head_sha": head_sha}}},
        "boundary": {"protection": {"content_digest": content_digest}},
    }), encoding="utf-8")
    write_bundle_manifest(path)
    return path


def _request(identity: RunIdentity, **overrides: object) -> PublicationRequest:
    base: dict[str, object] = {
        "run_id": identity.run_id,
        "expected_owner_worker_sid": identity.owner_worker_sid,
        "expected_deployment_digest": identity.deployment_digest,
        "expected_epoch": identity.epoch,
        "expected_repository_id": identity.repository_id,
        "expected_head_sha": identity.head_sha,
        "expected_tree_identity": identity.tree_identity,
    }
    base.update(overrides)
    return PublicationRequest(**base)  # type: ignore[arg-type]


def _free_record(run_id: str, seq: int, prev: str, *, tree: str = "tr",
                 head: str = HEAD, deployment: str = DEPLOY,
                 identity_digest: str = "e" * 64) -> AnchorRecord:
    """A syntactically valid V2 record, for the byte-level ledger tests that
    care about chaining and not about a trusted identity behind it."""
    return AnchorRecord(task_id="F-17", run_id=run_id, repository_id="repoX",
                        head_sha=head, tree_identity=tree, bundle_path="b",
                        bundle_digest="bd", seq=seq, prev_record_digest=prev,
                        deployment_digest=deployment,
                        run_identity_digest=identity_digest)


def _chain(count: int, *, run_prefix: str = "run") -> list[AnchorRecord]:
    out: list[AnchorRecord] = []
    prev = GENESIS_HASH
    for i in range(count):
        record = _free_record(f"{run_prefix}-{i}", i, prev)
        out.append(record)
        prev = record.digest()
    return out


def _write_ledger(path: Path, records: list[AnchorRecord], *,
                  crlf: bool = False, trailing: bytes = b"") -> None:
    body = "".join(record_line(r) for r in records)
    raw = body.replace("\n", "\r\n").encode("utf-8") if crlf else body.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw + trailing)


class _Env:
    """An anchor store, a trusted run store and per-run bundles on real NTFS."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.anchors = tmp / "anchors"
        self.runs = tmp / "runs"
        self.store = AnchorStore(self.anchors)
        self.run_store = TrustedRunIdentityStore(self.runs)

    def reopen(self) -> AnchorStore:
        """A FRESH store object over the same directory — what a restarted
        publisher gets, with nothing cached from before the crash."""
        self.store = AnchorStore(self.anchors)
        return self.store

    def new_run(self, run_id: str = "run-1", *, head: str = HEAD, tree: str = "cd0",
                sid: str = SID, deployment: str = DEPLOY, epoch: int = 0,
                publishable: bool = True) -> RunIdentity:
        bundle = _make_bundle(self.tmp / f"bundle-{run_id}", head, tree)
        identity = RunIdentity(
            task_id="F-17", run_id=run_id, repository_id="repoX", head_sha=head,
            tree_identity=tree, bundle_path=str(bundle), owner_worker_sid=sid,
            deployment_digest=deployment, epoch=epoch)
        self.run_store.create(identity)
        if publishable:
            self.run_store.mark_publishable(run_id, identity.digest())
        return identity

    def publish(self, identity: RunIdentity, **kwargs: object):  # type: ignore[no-untyped-def]
        return durable_publish(self.store, self.run_store, _request(identity),
                               Path(identity.bundle_path), **kwargs)  # type: ignore[arg-type]

    def watermark(self) -> CommittedWatermark | None:
        return read_watermark(self.anchors)


class _EnvCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.env = _Env(Path(self._tmp.name))

    def assertNoFalseAnchored(self, run_id: str) -> None:
        """THE invariant, checkable at any instant: a run may only say ANCHORED
        if the committed watermark actually confirms the record it names."""
        trusted = self.env.run_store.read(run_id)
        if trusted.publication_state is not PublicationState.ANCHORED:
            return
        watermark = self.env.watermark()
        self.assertIsNotNone(watermark, "ANCHORED with no watermark at all")
        assert watermark is not None
        split = split_ledger(self.env.store.ledger, watermark)
        self.assertIn(trusted.anchor_record_digest, split.committed_digests,
                      "ANCHORED against a record the watermark does not commit")


# ---------------------------------------------------------------------------
# The watermark contract
# ---------------------------------------------------------------------------
class TestTheCommittedWatermarkContract(unittest.TestCase):
    def test_a_watermark_round_trips_through_its_dict(self):
        watermark = CommittedWatermark(committed_seq=7, committed_record_digest="a" * 64)
        self.assertEqual(CommittedWatermark.from_dict(watermark.to_dict()), watermark)

    def test_genesis_says_nothing_is_committed(self):
        self.assertTrue(GENESIS_WATERMARK.commits_nothing)
        self.assertEqual(GENESIS_WATERMARK.committed_record_digest, GENESIS_HASH)
        self.assertFalse(
            CommittedWatermark(committed_seq=0,
                               committed_record_digest="a" * 64).commits_nothing)

    def test_the_sequence_must_be_a_real_index(self):
        for bad in (-2, True, "0", 1.0, None):
            with self.assertRaises(PublicationCorrupt, msg=repr(bad)):
                CommittedWatermark(committed_seq=bad,  # type: ignore[arg-type]
                                   committed_record_digest="a" * 64)

    def test_the_digest_must_be_a_real_digest(self):
        for bad in ("", "not-a-digest", "A" * 64, "a" * 63, "a" * 65, None, 5):
            with self.assertRaises(PublicationCorrupt, msg=repr(bad)):
                CommittedWatermark(committed_seq=0,
                                   committed_record_digest=bad)  # type: ignore[arg-type]

    def test_genesis_and_a_record_digest_cannot_be_mixed(self):
        # a watermark that commits nothing may not name a record ...
        with self.assertRaises(PublicationCorrupt):
            CommittedWatermark(committed_seq=-1, committed_record_digest="a" * 64)
        # ... and one that commits a record may not name genesis
        with self.assertRaises(PublicationCorrupt):
            CommittedWatermark(committed_seq=3, committed_record_digest=GENESIS_HASH)

    def test_an_unknown_schema_is_refused(self):
        with self.assertRaises(PublicationCorrupt):
            CommittedWatermark(committed_seq=0, committed_record_digest="a" * 64,
                               schema="gnosis.trust.watermark.v99")

    def test_unknown_or_missing_fields_are_refused(self):
        good = CommittedWatermark(committed_seq=0, committed_record_digest="a" * 64)
        with self.assertRaises(PublicationCorrupt):
            CommittedWatermark.from_dict({**good.to_dict(), "extra": 1})
        for drop in ("schema", "committed_seq", "committed_record_digest"):
            data = good.to_dict()
            del data[drop]
            with self.assertRaises(PublicationCorrupt, msg=drop):
                CommittedWatermark.from_dict(data)
        for bad in ("string", 5, None, [1, 2]):
            with self.assertRaises(PublicationCorrupt, msg=repr(bad)):
                CommittedWatermark.from_dict(bad)

    def test_a_commit_moves_the_watermark_by_exactly_one_record(self):
        """Pinned as a DIRECT contract test, deliberately and with the reason
        stated. Under the protocol this guard is unreachable: `AnchorStore.append`
        refuses a record that does not extend the chain, and any tail is
        discarded before the append, so the sequence committed can only ever be
        the next one. A guard nothing can reach is exactly the kind that rots
        into a check that cannot fail — mutant RM13's lesson in Stage 3 — so its
        contract is stated here rather than left to a scenario nobody can build.
        It is defence in depth, and it is labelled as defence in depth."""
        from gnosis.trust.publication import _assert_watermark_advances

        at_zero = CommittedWatermark(committed_seq=0, committed_record_digest="a" * 64)
        at_one = CommittedWatermark(committed_seq=1, committed_record_digest="b" * 64)
        _assert_watermark_advances(GENESIS_WATERMARK, at_zero)  # must not raise
        _assert_watermark_advances(at_zero, at_one)             # must not raise
        for bad in (GENESIS_WATERMARK, at_zero,
                    CommittedWatermark(committed_seq=2, committed_record_digest="c" * 64),
                    CommittedWatermark(committed_seq=9, committed_record_digest="d" * 64)):
            with self.assertRaises(PublicationCorrupt, msg=repr(bad)):
                _assert_watermark_advances(at_zero, bad)

    def test_a_watermark_for_one_record_cannot_validate_another_at_the_same_seq(self):
        """The binding property: sequence alone is not identity."""
        first = _free_record("run-a", 0, GENESIS_HASH)
        other = _free_record("run-b", 0, GENESIS_HASH)
        self.assertNotEqual(first.digest(), other.digest())
        watermark = CommittedWatermark(committed_seq=0,
                                       committed_record_digest=first.digest())
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "anchors.jsonl"
            _write_ledger(ledger, [other])
            with self.assertRaises(PublicationCorrupt):
                split_ledger(ledger, watermark)
            _write_ledger(ledger, [first])
            self.assertEqual(split_ledger(ledger, watermark).committed[0].digest(),
                             first.digest())


class TestReadingTheWatermarkFailsClosed(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_an_absent_watermark_is_the_only_none(self):
        self.assertIsNone(read_watermark(self.root))

    def test_a_malformed_watermark_is_never_read_as_empty(self):
        """CASE J. Every damaged form fails closed. Reading any of them as
        'nothing is committed' would re-publish a committed anchor or demote
        committed history to debris."""
        path = watermark_path(self.root)
        good = canonical_json_bytes(
            CommittedWatermark(committed_seq=0,
                               committed_record_digest="a" * 64).to_dict())
        for name, payload in (
            ("empty", b""),
            ("whitespace", b"   "),
            ("truncated", good[: len(good) // 2]),
            ("not json", b"not json at all"),
            ("not an object", b"[1, 2, 3]"),
            ("bad utf-8", b'{"schema": "\xff\xfe"}'),
            ("unknown schema", canonical_json_bytes(
                {"schema": "other", "committed_seq": 0,
                 "committed_record_digest": "a" * 64})),
            ("extra field", canonical_json_bytes(
                {"schema": "gnosis.trust.watermark.v1", "committed_seq": 0,
                 "committed_record_digest": "a" * 64, "committed_run_id": "x"})),
            ("bad digest", canonical_json_bytes(
                {"schema": "gnosis.trust.watermark.v1", "committed_seq": 0,
                 "committed_record_digest": "nope"})),
        ):
            path.write_bytes(payload)
            with self.assertRaises(PublicationCorrupt, msg=name):
                read_watermark(self.root)

    def test_a_leftover_temp_file_is_never_adopted(self):
        """A crash during the watermark write can leave a `.tmp-*` beside the
        authoritative file. Nothing reads it — not even when it is complete and
        newer than the real one."""
        path = watermark_path(self.root)
        old = CommittedWatermark(committed_seq=0, committed_record_digest="a" * 64)
        newer = CommittedWatermark(committed_seq=1, committed_record_digest="b" * 64)
        path.write_bytes(canonical_json_bytes(old.to_dict()))
        path.with_name(path.name + ".tmp-abc123").write_bytes(
            canonical_json_bytes(newer.to_dict()))
        path.with_name(path.name + ".tmp-def456").write_bytes(b'{"schema": "gno')
        self.assertEqual(read_watermark(self.root), old)


# ---------------------------------------------------------------------------
# The ledger, cut at the commit point
# ---------------------------------------------------------------------------
class TestSplittingTheLedgerAtTheCommitPoint(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = Path(self._tmp.name) / "anchors.jsonl"

    def _watermark(self, records: list[AnchorRecord], seq: int) -> CommittedWatermark:
        return CommittedWatermark(committed_seq=seq,
                                  committed_record_digest=records[seq].digest())

    def test_an_empty_ledger_under_genesis_has_no_committed_history(self):
        split = split_ledger(self.ledger, GENESIS_WATERMARK)
        self.assertEqual(split.committed, ())
        self.assertFalse(split.has_tail)

    def test_the_committed_prefix_is_exactly_what_the_watermark_names(self):
        records = _chain(4)
        _write_ledger(self.ledger, records)
        split = split_ledger(self.ledger, self._watermark(records, 1))
        self.assertEqual([r.digest() for r in split.committed],
                         [records[0].digest(), records[1].digest()])
        self.assertEqual(split.tail_complete_records, 2)
        self.assertTrue(split.has_tail)

    def test_crlf_line_endings_are_read_correctly(self):
        """Ledgers written before Stage 4 went through Python text mode on
        Windows, so the byte-level reader must accept CRLF as well as LF or a
        historical chain would stop being readable."""
        records = _chain(3)
        _write_ledger(self.ledger, records, crlf=True)
        split = split_ledger(self.ledger, self._watermark(records, 2))
        self.assertEqual(len(split.committed), 3)
        self.assertFalse(split.has_tail)

    def test_case_f_a_watermark_naming_a_record_the_ledger_lacks(self):
        records = _chain(2)
        _write_ledger(self.ledger, records[:1])
        with self.assertRaises(PublicationCorrupt) as ctx:
            split_ledger(self.ledger, self._watermark(records, 1))
        self.assertIn("holds only 1", str(ctx.exception))

    def test_case_g_a_watermark_whose_digest_is_not_the_record_there(self):
        records = _chain(2)
        _write_ledger(self.ledger, records)
        forged = CommittedWatermark(committed_seq=1,
                                    committed_record_digest=records[0].digest())
        with self.assertRaises(PublicationCorrupt):
            split_ledger(self.ledger, forged)

    def test_case_h_a_chain_break_inside_the_committed_prefix(self):
        records = _chain(3)
        watermark = self._watermark(records, 2)
        broken = [records[0], _free_record("run-x", 1, "0" * 64), records[2]]
        _write_ledger(self.ledger, broken)
        with self.assertRaises(PublicationCorrupt) as ctx:
            split_ledger(self.ledger, watermark)
        self.assertIn("chain breaks", str(ctx.exception))

    def test_an_unreadable_line_inside_the_committed_prefix_fails_closed(self):
        records = _chain(2)
        watermark = self._watermark(records, 1)
        self.ledger.write_bytes(
            (record_line(records[0]) + '{"schema": "gnosis.anchor.v2"}\n').encode("utf-8"))
        with self.assertRaises(AuthorityUnavailable):
            split_ledger(self.ledger, watermark)

    def test_case_b_one_complete_uncommitted_record_is_a_tail(self):
        records = _chain(2)
        _write_ledger(self.ledger, records)
        split = split_ledger(self.ledger, self._watermark(records, 0))
        self.assertEqual(split.tail_complete_records, 1)
        self.assertEqual(split.tail_partial_bytes, 0)

    def test_case_i_a_partial_line_is_a_tail(self):
        records = _chain(1)
        partial = record_line(_free_record("run-9", 1, records[0].digest()))[:20]
        _write_ledger(self.ledger, records, trailing=partial.encode("utf-8"))
        split = split_ledger(self.ledger, self._watermark(records, 0))
        self.assertEqual(split.tail_complete_records, 0)
        self.assertEqual(split.tail_partial_bytes, len(partial))
        self.assertTrue(split.has_tail)

    def test_a_partial_first_line_under_genesis_is_a_tail(self):
        """A crash during the FIRST append. The genesis watermark is what makes
        this decidable: nothing is committed, so the bytes are debris."""
        self.ledger.write_bytes(record_line(_free_record("r", 0, GENESIS_HASH))[:30]
                                .encode("utf-8"))
        split = split_ledger(self.ledger, GENESIS_WATERMARK)
        self.assertEqual(split.committed, ())
        self.assertEqual(split.tail_complete_records, 0)
        self.assertTrue(split.has_tail)


# ---------------------------------------------------------------------------
# Store initialisation: where "no watermark" is allowed to mean anything
# ---------------------------------------------------------------------------
@HIGH_ONLY
class TestInitialisingADurableStore(_EnvCase):
    def test_an_empty_store_gets_a_genesis_watermark(self):
        self.assertIsNone(self.env.watermark())
        self.assertEqual(initialise_durable_store(self.env.store), GENESIS_WATERMARK)
        self.assertEqual(self.env.watermark(), GENESIS_WATERMARK)

    def test_initialising_twice_keeps_the_existing_watermark(self):
        identity = self.env.new_run()
        self.env.publish(identity)
        before = self.env.watermark()
        self.assertEqual(initialise_durable_store(self.env.store), before)
        self.assertEqual(self.env.watermark(), before)

    def test_a_ledger_with_records_and_no_watermark_is_refused(self):
        """The V1 / pre-Stage-4 ledger. It is NOT adopted, and NO watermark is
        invented from its last record — that would declare a record committed
        which may only ever have been a crashed attempt."""
        _write_ledger(self.env.store.ledger, _chain(2))
        with self.assertRaises(LedgerNotUnderDurableProtocol):
            initialise_durable_store(self.env.store)
        identity = self.env.new_run()
        with self.assertRaises(LedgerNotUnderDurableProtocol):
            self.env.publish(identity)
        self.assertIsNone(self.env.watermark())

    def test_a_v1_ledger_is_not_given_a_modern_binding_by_recovery(self):
        v1 = AnchorRecord(task_id="F-17", run_id="old-run", repository_id="repoX",
                          head_sha=HEAD, tree_identity="tr", bundle_path="b",
                          bundle_digest="bd", seq=0, prev_record_digest=GENESIS_HASH,
                          schema=ANCHOR_SCHEMA)
        _write_ledger(self.env.store.ledger, [v1])
        watermark = CommittedWatermark(committed_seq=0,
                                       committed_record_digest=v1.digest())
        watermark_path(self.env.anchors).write_bytes(
            canonical_json_bytes(watermark.to_dict()))
        report = reconcile_publication_state(
            self.env.store, self.env.run_store, expected_deployment_digest=DEPLOY)
        # counted, left exactly as it is, and no state was invented for it
        self.assertEqual(report.legacy_v1_records, 1)
        self.assertEqual(report.reconciled_run_ids, ())
        self.assertEqual(self.env.run_store.run_ids(), ())


# ---------------------------------------------------------------------------
# The durable protocol
# ---------------------------------------------------------------------------
@HIGH_ONLY
class TestDurablePublication(_EnvCase):
    def test_a_publication_commits_exactly_one_record(self):
        identity = self.env.new_run()
        result = self.env.publish(identity)
        self.assertIs(result.outcome, PublishOutcome.ANCHORED)
        self.assertEqual(len(self.env.store.records()), 1)
        self.assertTrue(self.env.store.verify_chain())
        watermark = self.env.watermark()
        assert watermark is not None
        self.assertEqual(watermark.committed_seq, 0)
        self.assertEqual(watermark.committed_record_digest, result.record.digest())
        trusted = self.env.run_store.read(identity.run_id)
        self.assertIs(trusted.publication_state, PublicationState.ANCHORED)
        self.assertEqual(trusted.anchor_record_digest, result.record.digest())

    def test_a_retry_is_already_anchored_and_never_a_second_record(self):
        identity = self.env.new_run()
        first = self.env.publish(identity)
        for _ in range(3):
            again = self.env.publish(identity)
            self.assertIs(again.outcome, PublishOutcome.ALREADY_ANCHORED)
            self.assertEqual(again.record.digest(), first.record.digest())
        self.assertEqual(len(self.env.store.records()), 1)

    def test_two_runs_share_one_ledger_with_a_unique_seq_and_an_intact_chain(self):
        first = self.env.publish(self.env.new_run("run-1"))
        second = self.env.publish(self.env.new_run("run-2", tree="cd1"))
        self.assertEqual([first.record.seq, second.record.seq], [0, 1])
        self.assertEqual(second.record.prev_record_digest, first.record.digest())
        self.assertTrue(self.env.store.verify_chain())
        watermark = self.env.watermark()
        assert watermark is not None
        self.assertEqual(watermark.committed_seq, 1)

    def test_the_watermark_moves_by_exactly_one_record(self):
        seqs = []
        for i in range(3):
            self.env.publish(self.env.new_run(f"run-{i}", tree=f"cd{i}"))
            watermark = self.env.watermark()
            assert watermark is not None
            seqs.append(watermark.committed_seq)
        self.assertEqual(seqs, [0, 1, 2])

    def test_the_ledger_is_flushed_and_readable_from_a_fresh_store_object(self):
        identity = self.env.new_run()
        result = self.env.publish(identity)
        fresh = self.env.reopen()
        self.assertEqual([r.digest() for r in fresh.records()], [result.record.digest()])
        self.assertTrue(fresh.verify_chain())

    def test_both_the_ledger_and_the_watermark_are_flushed_to_the_storage_stack(self):
        """WHAT THIS PROVES AND WHAT IT DOES NOT. It proves the durable flush is
        REQUESTED at both commit steps — os.fsync, i.e. FlushFileBuffers on
        Windows — for the ledger append and for the watermark's temp file. It
        does NOT prove the storage hardware honoured it: that would be a
        power-loss test, which is explicitly out of scope. Requesting the flush
        is the part this code is responsible for, so it is the part asserted."""
        import os
        import traceback

        from gnosis.trust import publication

        # `os` is ONE module object, so patching it through two importers would
        # patch the same attribute twice. The ledger call site is told apart by
        # WHO called; the watermark write is bracketed instead, because
        # `atomic_io` also writes the trusted run state in the same publication
        # and a bare "atomic_io fsynced at some point" would be satisfied by
        # that one alone.
        callers: list[str] = []
        real_fsync = os.fsync
        real_write = publication.atomic_write_bytes
        during_watermark: list[int] = []

        def recording(fd: int) -> None:
            callers.append(Path(traceback.extract_stack(limit=2)[0].filename).name)
            real_fsync(fd)

        def bracketed(path: Path, data: bytes) -> None:
            before = len(callers)
            real_write(path, data)
            during_watermark.append(len(callers) - before)

        os.fsync = recording  # type: ignore[assignment]
        publication.atomic_write_bytes = bracketed  # type: ignore[assignment]
        try:
            self.env.publish(self.env.new_run())
        finally:
            os.fsync = real_fsync  # type: ignore[assignment]
            publication.atomic_write_bytes = real_write  # type: ignore[assignment]
        self.assertIn("anchor.py", callers, "the ledger append was not flushed")
        self.assertTrue(during_watermark, "the watermark was never written atomically")
        self.assertTrue(all(n >= 1 for n in during_watermark),
                        "a watermark write reached the storage stack without a flush")

    def test_a_retry_returns_this_runs_record_not_the_ledger_head(self):
        """ALREADY_ANCHORED must resolve the record the RUN is anchored against.
        Answering with whatever sits at the head of the ledger would be right by
        coincidence for the most recent run and wrong for every earlier one."""
        identity = self.env.new_run("run-1")
        first = self.env.publish(identity)
        second = self.env.publish(self.env.new_run("run-2", tree="cd1"))
        self.assertNotEqual(first.record.digest(), second.record.digest())
        again = self.env.publish(identity)
        self.assertIs(again.outcome, PublishOutcome.ALREADY_ANCHORED)
        self.assertEqual(again.record.digest(), first.record.digest())
        self.assertEqual(again.record.run_id, "run-1")

    def test_an_uncommitted_tail_fails_closed_when_repair_is_not_authorized(self):
        """Appending after bytes nobody committed would chain them into the
        committed history — so without the authority to discard them, the
        publication refuses rather than building on top of them."""
        self.env.publish(self.env.new_run("run-1"))
        committed = self.env.store.records()[0]
        with self.env.store.ledger.open("ab") as fh:
            fh.write(record_line(_free_record("ghost", 1, committed.digest()))
                     .encode("utf-8"))
        second = self.env.new_run("run-2", tree="cd1")
        with self.assertRaises(AuthorityUnavailable) as ctx:
            self.env.publish(second, repair_uncommitted_tail=False)
        self.assertIn("uncommitted", str(ctx.exception))
        self.assertEqual(len(self.env.store.records()), 2)  # nothing was appended
        self.assertIs(self.env.run_store.read("run-2").publication_state,
                      PublicationState.PUBLISHABLE)

    def test_the_publication_lock_is_held_for_the_whole_protocol(self):
        """Trusted-writer coordination, asserted rather than assumed. Probed
        from the deepest point of the protocol: if the lock were not held there,
        a second trusted publisher could append at the same sequence."""
        from gnosis.kernel.file_lock import FileLock, LockTimeoutError, lock_path_for
        from gnosis.trust import publication

        held: list[bool] = []

        def hook(fired: str, **_: object) -> None:
            if fired != "F4":
                return
            try:
                FileLock(lock_path_for(self.env.store.ledger), timeout_s=0.3).acquire()
                held.append(False)
            except LockTimeoutError:
                held.append(True)

        previous = publication._FAULT_HOOK
        publication._FAULT_HOOK = hook
        try:
            self.env.publish(self.env.new_run())
        finally:
            publication._FAULT_HOOK = previous
        self.assertEqual(held, [True], "the publication lock was not held")

    def test_a_ledger_that_changes_before_the_commit_is_never_committed_over(self):
        """The ledger is re-read and re-verified from disk BEFORE the watermark
        moves, so a chain that no longer checks out is refused while nothing has
        been committed — rather than committed first and noticed afterwards."""
        from gnosis.trust import publication

        first = self.env.publish(self.env.new_run("run-1"))
        second_identity = self.env.new_run("run-2", tree="cd1")

        def hook(fired: str, **_: object) -> None:
            if fired != "F3":
                return
            # rewrite the ALREADY COMMITTED record 0, leaving the record just
            # appended untouched: only a chain check can see this.
            records = self.env.store.records()
            tampered = _free_record("run-1", 0, GENESIS_HASH, tree="tampered")
            _write_ledger(self.env.store.ledger, [tampered, records[1]])

        previous = publication._FAULT_HOOK
        publication._FAULT_HOOK = hook
        try:
            with self.assertRaises(PublicationCorrupt):
                self.env.publish(second_identity)
        finally:
            publication._FAULT_HOOK = previous
        watermark = self.env.watermark()
        assert watermark is not None
        self.assertEqual(watermark.committed_record_digest, first.record.digest(),
                         "a broken ledger was committed over")
        self.assertIs(self.env.run_store.read("run-2").publication_state,
                      PublicationState.PUBLISHABLE)


@HIGH_ONLY
class TestWhatTheDurablePathRefuses(_EnvCase):
    def test_a_run_that_is_not_publishable_is_refused(self):
        identity = self.env.new_run(publishable=False)
        with self.assertRaises(AuthorityUnavailable):
            self.env.publish(identity)
        self.assertEqual(self.env.store.records(), [])

    def test_an_unknown_run_is_refused(self):
        identity = self.env.new_run()
        request = _request(identity, run_id="never-created")
        with self.assertRaises(AuthorityUnavailable):
            durable_publish(self.env.store, self.env.run_store, request,
                            Path(identity.bundle_path))

    def test_a_different_deployment_is_refused(self):
        identity = self.env.new_run()
        request = _request(identity, expected_deployment_digest=DEPLOY_OTHER)
        with self.assertRaises(AuthorityUnavailable):
            durable_publish(self.env.store, self.env.run_store, request,
                            Path(identity.bundle_path))
        self.assertEqual(self.env.store.records(), [])

    def test_a_different_epoch_is_refused(self):
        identity = self.env.new_run(epoch=2)
        request = _request(identity, expected_epoch=3)
        with self.assertRaises(AuthorityUnavailable):
            durable_publish(self.env.store, self.env.run_store, request,
                            Path(identity.bundle_path))

    def test_a_different_owner_worker_sid_is_refused(self):
        identity = self.env.new_run()
        request = _request(identity, expected_owner_worker_sid=SID_OTHER)
        with self.assertRaises(AuthorityUnavailable):
            durable_publish(self.env.store, self.env.run_store, request,
                            Path(identity.bundle_path))

    def test_a_bundle_bound_to_another_head_is_refused(self):
        identity = self.env.new_run()
        other = _make_bundle(self.env.tmp / "other", head_sha="z" * 40, content_digest="cd0")
        with self.assertRaises(AuthorityUnavailable):
            durable_publish(self.env.store, self.env.run_store, _request(identity), other)
        self.assertEqual(self.env.store.records(), [])


# ---------------------------------------------------------------------------
# The recovery matrix
# ---------------------------------------------------------------------------
@HIGH_ONLY
class TestTheRecoveryMatrix(_EnvCase):
    def _reconcile(self, *, deployment: str = DEPLOY, repair: bool = False):  # type: ignore[no-untyped-def]
        return reconcile_publication_state(
            self.env.store, self.env.run_store,
            expected_deployment_digest=deployment, repair_uncommitted_tail=repair)

    def test_case_a_nothing_committed_is_a_normal_retry(self):
        self.env.new_run()
        initialise_durable_store(self.env.store)
        report = self._reconcile()
        self.assertEqual(report.committed_seq, -1)
        self.assertEqual(report.reconciled_run_ids, ())
        self.assertFalse(report.has_uncommitted_tail)

    def test_case_d_a_committed_and_anchored_run_is_healthy(self):
        identity = self.env.new_run()
        self.env.publish(identity)
        report = self._reconcile()
        self.assertEqual(report.healthy_run_ids, (identity.run_id,))
        self.assertEqual(report.reconciled_run_ids, ())

    def test_case_c_a_committed_record_with_a_publishable_run_is_reconciled(self):
        """The crash window Stage 4 exists to close: the commit landed, the
        consequence did not. Recovery completes it WITHOUT a second anchor."""
        identity = self.env.new_run()
        result = self.env.publish(identity)
        self._force_state_back_to_publishable(identity)
        report = self._reconcile()
        self.assertEqual(report.reconciled_run_ids, (identity.run_id,))
        trusted = self.env.run_store.read(identity.run_id)
        self.assertIs(trusted.publication_state, PublicationState.ANCHORED)
        self.assertEqual(trusted.anchor_record_digest, result.record.digest())
        self.assertEqual(len(self.env.store.records()), 1)

    def test_case_e_anchored_without_a_confirming_watermark_fails_closed(self):
        identity = self.env.new_run()
        self.env.publish(identity)
        # roll the commit point back: the state now runs ahead of the commit
        watermark_path(self.env.anchors).write_bytes(
            canonical_json_bytes(GENESIS_WATERMARK.to_dict()))
        with self.assertRaises(PublicationCorrupt) as ctx:
            self._reconcile()
        self.assertIn("no durable commit", str(ctx.exception))
        # and it is NOT repaired by inventing the anchor that would make it true
        self.assertEqual(self.env.watermark(), GENESIS_WATERMARK)

    def test_case_f_a_watermark_pointing_at_a_missing_record_fails_closed(self):
        identity = self.env.new_run()
        self.env.publish(identity)
        self.env.store.ledger.write_bytes(b"")
        with self.assertRaises(PublicationCorrupt):
            self._reconcile()

    def test_case_g_a_watermark_digest_that_is_not_the_record_fails_closed(self):
        identity = self.env.new_run()
        self.env.publish(identity)
        watermark_path(self.env.anchors).write_bytes(canonical_json_bytes(
            CommittedWatermark(committed_seq=0,
                               committed_record_digest="a" * 64).to_dict()))
        with self.assertRaises(PublicationCorrupt):
            self._reconcile()

    def test_case_h_a_broken_committed_chain_fails_closed(self):
        self.env.publish(self.env.new_run("run-1"))
        self.env.publish(self.env.new_run("run-2", tree="cd1"))
        records = self.env.store.records()
        _write_ledger(self.env.store.ledger,
                      [_free_record("run-1", 0, GENESIS_HASH), records[1]])
        with self.assertRaises(PublicationCorrupt):
            self._reconcile()

    def test_case_j_a_malformed_watermark_fails_closed(self):
        identity = self.env.new_run()
        self.env.publish(identity)
        watermark_path(self.env.anchors).write_bytes(b'{"schema": "gnosis.tr')
        with self.assertRaises(PublicationCorrupt):
            self._reconcile()
        with self.assertRaises(PublicationCorrupt):
            self.env.publish(identity)

    def test_case_b_a_complete_uncommitted_record_is_detected_then_discarded(self):
        identity = self.env.new_run()
        self.env.publish(identity)
        committed = self.env.store.records()[0]
        orphan = _free_record("ghost", 1, committed.digest())
        with self.env.store.ledger.open("ab") as fh:
            fh.write(record_line(orphan).encode("utf-8"))
        detected = self._reconcile()
        self.assertEqual(detected.uncommitted_tail_records, 1)
        self.assertFalse(detected.tail_discarded)
        self.assertEqual(len(self.env.store.records()), 2)  # untouched without repair
        repaired = self._reconcile(repair=True)
        self.assertTrue(repaired.tail_discarded)
        self.assertEqual([r.digest() for r in self.env.store.records()],
                         [committed.digest()])

    def test_case_i_a_partial_line_is_detected_then_discarded(self):
        identity = self.env.new_run()
        self.env.publish(identity)
        committed = self.env.store.records()[0]
        with self.env.store.ledger.open("ab") as fh:
            fh.write(b'{"bundle_digest": "half-a-rec')
        detected = self._reconcile()
        self.assertEqual(detected.uncommitted_tail_records, 0)
        self.assertGreater(detected.uncommitted_tail_bytes, 0)
        repaired = self._reconcile(repair=True)
        self.assertTrue(repaired.tail_discarded)
        self.assertEqual([r.digest() for r in self.env.store.records()],
                         [committed.digest()])
        self.assertTrue(self.env.store.verify_chain())

    def test_more_than_one_uncommitted_record_is_never_discarded_on_a_guess(self):
        """The durable protocol truncates before it appends, so at any instant
        it can leave at most ONE uncommitted record. More than that did not come
        from this protocol, and deleting several records on a guess is exactly
        the dangerous version of tail truncation."""
        identity = self.env.new_run()
        self.env.publish(identity)
        prev = self.env.store.records()[0]
        with self.env.store.ledger.open("ab") as fh:
            for seq in (1, 2):
                extra = _free_record(f"ghost-{seq}", seq, prev.digest())
                fh.write(record_line(extra).encode("utf-8"))
                prev = extra
        for repair in (False, True):
            with self.assertRaises(PublicationCorrupt, msg=f"repair={repair}"):
                self._reconcile(repair=repair)
        self.assertEqual(len(self.env.store.records()), 3)

    def test_a_complete_record_followed_by_a_partial_line_fails_closed(self):
        identity = self.env.new_run()
        self.env.publish(identity)
        committed = self.env.store.records()[0]
        with self.env.store.ledger.open("ab") as fh:
            fh.write(record_line(_free_record("ghost", 1, committed.digest()))
                     .encode("utf-8"))
            fh.write(b'{"bundle_digest": "hal')
        with self.assertRaises(PublicationCorrupt):
            self._reconcile(repair=True)

    def test_committed_history_is_never_truncated(self):
        """The tail rules cut AFTER the committed record, never through it."""
        first = self.env.publish(self.env.new_run("run-1"))
        second = self.env.publish(self.env.new_run("run-2", tree="cd1"))
        with self.env.store.ledger.open("ab") as fh:
            fh.write(record_line(_free_record("ghost", 2, second.record.digest()))
                     .encode("utf-8"))
        self._reconcile(repair=True)
        self.assertEqual([r.digest() for r in self.env.store.records()],
                         [first.record.digest(), second.record.digest()])

    def test_recovery_refuses_to_reconcile_across_deployments(self):
        """D1 committed, D2 asking. The record already being on disk is not a
        reason to ignore what it is bound to."""
        identity = self.env.new_run(deployment=DEPLOY)
        self.env.publish(identity)
        self._force_state_back_to_publishable(identity)
        with self.assertRaises(PublicationCorrupt) as ctx:
            self._reconcile(deployment=DEPLOY_OTHER)
        self.assertIn("across deployments", str(ctx.exception))
        self.assertIs(self.env.run_store.read(identity.run_id).publication_state,
                      PublicationState.PUBLISHABLE)

    def test_a_run_id_rebound_to_another_identity_is_not_reconciled(self):
        """Same run_id, different immutable identity: no cross recovery and no
        cross ALREADY_ANCHORED. The ledger record names the identity it was
        published for, and a different one cannot claim it."""
        identity = self.env.new_run("run-1", epoch=0)
        self.env.publish(identity)
        self._force_state_back_to_publishable(identity)
        # delete and recreate the trusted record under a DIFFERENT identity
        self.env.run_store.path_for("run-1").unlink()
        other = self.env.new_run("run-1", epoch=9)
        self.assertNotEqual(other.digest(), identity.digest())
        with self.assertRaises(PublicationCorrupt) as ctx:
            self._reconcile()
        self.assertIn("run_identity_digest", str(ctx.exception))

    def test_a_committed_anchor_whose_run_the_trust_plane_lost_fails_closed(self):
        identity = self.env.new_run()
        self.env.publish(identity)
        self.env.run_store.path_for(identity.run_id).unlink()
        with self.assertRaises(PublicationCorrupt):
            self._reconcile()

    def _force_state_back_to_publishable(self, identity: RunIdentity) -> None:
        """Reproduce the post-crash state directly: the anchor is committed but
        the trusted state never advanced. `transition` is monotonic and refuses
        to go backwards, which is the point — so the file is rewritten the way a
        crash would have left it: never written in the first place."""
        path = self.env.run_store.path_for(identity.run_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["publication_state"] = PublicationState.PUBLISHABLE.value
        data["anchor_record_digest"] = None
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Fault injection: the protocol stopped dead at each point
# ---------------------------------------------------------------------------
class _Interrupted(RuntimeError):
    """Stops the protocol at a fault point without unwinding any state."""


@HIGH_ONLY
class TestInProcessFaultInjection(_EnvCase):
    """The same interruption points as the process-crash tests, reached by
    stopping the protocol instead of killing the interpreter. Cheaper, and it
    proves the same post-fault states are recoverable; the REAL process kill is
    `TestProcessCrashAtEveryFaultPoint`."""

    def _publish_interrupted(self, identity: RunIdentity, point: str) -> None:
        from gnosis.trust import publication

        def hook(fired: str, **_: object) -> None:
            if fired == point:
                raise _Interrupted(point)

        previous = publication._FAULT_HOOK
        publication._FAULT_HOOK = hook
        try:
            with self.assertRaises(_Interrupted):
                self.env.publish(identity)
        finally:
            publication._FAULT_HOOK = previous

    def test_no_fault_point_leaves_a_false_anchored(self):
        for point in ("F0", "F3", "F4", "F5", "F6", "F7", "F8", "F9"):
            with (self.subTest(point=point),
                    tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp):
                    self.env = _Env(Path(tmp))
                    identity = self.env.new_run()
                    self._publish_interrupted(identity, point)
                    self.assertNoFalseAnchored(identity.run_id)

    def test_before_the_commit_nothing_is_committed_and_a_retry_anchors(self):
        for point in ("F0", "F3", "F4", "F5", "F6"):
            with (self.subTest(point=point),
                    tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp):
                    self.env = _Env(Path(tmp))
                    identity = self.env.new_run()
                    self._publish_interrupted(identity, point)
                    watermark = self.env.watermark()
                    assert watermark is not None
                    self.assertTrue(watermark.commits_nothing, point)
                    self.assertIs(
                        self.env.run_store.read(identity.run_id).publication_state,
                        PublicationState.PUBLISHABLE)
                    result = self.env.publish(identity)
                    self.assertIs(result.outcome, PublishOutcome.ANCHORED)
                    self.assertEqual(len(self.env.store.records()), 1)

    def test_after_the_commit_a_retry_is_already_anchored(self):
        for point in ("F7", "F8"):
            with (self.subTest(point=point),
                    tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp):
                    self.env = _Env(Path(tmp))
                    identity = self.env.new_run()
                    self._publish_interrupted(identity, point)
                    watermark = self.env.watermark()
                    assert watermark is not None
                    self.assertFalse(watermark.commits_nothing, point)
                    self.assertIs(
                        self.env.run_store.read(identity.run_id).publication_state,
                        PublicationState.PUBLISHABLE)
                    result = self.env.publish(identity)
                    self.assertIs(result.outcome, PublishOutcome.ALREADY_ANCHORED)
                    self.assertEqual(len(self.env.store.records()), 1)

    def test_a_crash_on_the_second_publication_keeps_the_first_committed(self):
        first = self.env.publish(self.env.new_run("run-1"))
        second_identity = self.env.new_run("run-2", tree="cd1")
        self._publish_interrupted(second_identity, "F4")
        self.assertEqual(len(self.env.store.records()), 2)  # the tail is there
        result = self.env.publish(second_identity)
        self.assertIs(result.outcome, PublishOutcome.ANCHORED)
        self.assertEqual([r.digest() for r in self.env.store.records()],
                         [first.record.digest(), result.record.digest()])
        self.assertTrue(self.env.store.verify_chain())


# ---------------------------------------------------------------------------
# REAL process crashes
# ---------------------------------------------------------------------------
_CHILD = '''
import os, sys
from pathlib import Path
sys.path.insert(0, SRC)
import gnosis.trust.publication as pub
from gnosis.kernel.canonical import canonical_json_bytes
from gnosis.trust.anchor import AnchorStore
from gnosis.trust.run_identity import PublicationRequest, TrustedRunIdentityStore

point, tmp, run_id, out = sys.argv[1], Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
store = AnchorStore(tmp / "anchors")
run_store = TrustedRunIdentityStore(tmp / "runs")
identity = run_store.read(run_id).identity
request = PublicationRequest(
    run_id=run_id,
    expected_owner_worker_sid=identity.owner_worker_sid,
    expected_deployment_digest=identity.deployment_digest,
    expected_epoch=identity.epoch,
    expected_repository_id=identity.repository_id,
    expected_head_sha=identity.head_sha,
    expected_tree_identity=identity.tree_identity)

target = point.split("@")[0]

def hook(fired, **ctx):
    if fired != target:
        return
    if point == "F1":
        # a genuinely partial ledger line: half the bytes, flushed to the OS
        ctx["handle"].write(ctx["payload"][: len(ctx["payload"]) // 2])
        ctx["handle"].flush()
    elif point == "F5":
        # crashed while writing the watermark temp: a PARTIAL temp is left
        path = pub.watermark_path(ctx["root"])
        path.with_name(path.name + ".tmp-crash").write_bytes(b'"{"schema": "gnosis.tru"')
    elif point == "F6":
        # temp fully written and flushed, replace not reached: a COMPLETE temp
        path = pub.watermark_path(ctx["root"])
        path.with_name(path.name + ".tmp-crash").write_bytes(
            canonical_json_bytes(ctx["watermark"].to_dict()))
    elif point == "F8@late":
        # the atomic state write landed; the process dies before it is read back
        ctx["run_store"].mark_anchored(
            ctx["identity"].run_id, ctx["identity"].digest(), ctx["record"].digest())
    os._exit(77)

pub._FAULT_HOOK = None if point == "NONE" else hook
out.write_text(pub.durable_publish(store, run_store, request,
                                   Path(identity.bundle_path)).outcome.value,
               encoding="utf-8")
'''


def _child_source() -> str:
    return _CHILD.replace("SRC)", repr(str(REPO / "src")) + ")", 1)


@HIGH_ONLY
class TestProcessCrashAtEveryFaultPoint(_EnvCase):
    """F0-F9 as REAL process kills: `os._exit` runs no cleanup, no atexit and
    flushes no buffer. Process/service crash — NOT power loss."""

    # point -> (the watermark commits something, the run state, the ledger shape)
    #
    # The ledger shape is asserted rather than assumed, because it is what
    # separates the fault points from one another: F2 crashes with the record
    # written into a Python buffer that `os._exit` never flushes, so the bytes
    # never reach the filesystem at all, while F3 crashes AFTER the fsync, so
    # they do — and are still not committed. "Durable" and "committed" are
    # different properties, and this is where that shows.
    EMPTY, PARTIAL, ONE_RECORD = "empty", "partial", "one record"
    EXPECTED: ClassVar[dict[str, tuple[bool, PublicationState, str]]] = {
        "F0": (False, PublicationState.PUBLISHABLE, EMPTY),
        "F1": (False, PublicationState.PUBLISHABLE, PARTIAL),
        "F2": (False, PublicationState.PUBLISHABLE, EMPTY),
        "F3": (False, PublicationState.PUBLISHABLE, ONE_RECORD),
        "F4": (False, PublicationState.PUBLISHABLE, ONE_RECORD),
        "F5": (False, PublicationState.PUBLISHABLE, ONE_RECORD),
        "F6": (False, PublicationState.PUBLISHABLE, ONE_RECORD),
        "F7": (True, PublicationState.PUBLISHABLE, ONE_RECORD),
        "F8": (True, PublicationState.PUBLISHABLE, ONE_RECORD),
        "F8@late": (True, PublicationState.ANCHORED, ONE_RECORD),
        "F9": (True, PublicationState.ANCHORED, ONE_RECORD),
    }

    def assertLedgerShape(self, ledger: Path, shape: str, point: str) -> None:
        raw = ledger.read_bytes() if ledger.exists() else b""
        if shape == self.EMPTY:
            self.assertEqual(raw, b"", f"{point}: expected nothing on disk")
        elif shape == self.PARTIAL:
            self.assertTrue(raw, f"{point}: the partial write never reached disk")
            self.assertFalse(raw.endswith(b"\n"), f"{point}: the line is not partial")
        else:
            self.assertTrue(raw.endswith(b"\n"), f"{point}: the record is incomplete")
            self.assertEqual(raw.count(b"\n"), 1, f"{point}: expected exactly one record")

    def _crash(self, tmp: Path, point: str, run_id: str) -> None:
        proc = subprocess.run(
            [sys.executable, "-c", _child_source(), point, str(tmp), run_id,
             str(tmp / "outcome.txt")],
            capture_output=True, text=True, check=False, cwd=str(REPO))
        self.assertEqual(proc.returncode, 77,
                         f"{point}: child did not crash at the fault point\n"
                         f"{proc.stdout}\n{proc.stderr}")
        self.assertFalse((tmp / "outcome.txt").exists(),
                         f"{point}: the child returned a result despite crashing")

    def test_every_fault_point_survives_a_real_process_crash(self):
        for point, (commits, state, shape) in self.EXPECTED.items():
            with (self.subTest(point=point),
                    tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp):
                    root = Path(tmp)
                    self.env = _Env(root)
                    identity = self.env.new_run()
                    self._crash(root, point, identity.run_id)

                    self.env.reopen()
                    # 1. the required post-crash shape
                    self.assertLedgerShape(self.env.store.ledger, shape, point)
                    watermark = self.env.watermark()
                    self.assertIsNotNone(watermark, point)
                    assert watermark is not None
                    self.assertEqual(not watermark.commits_nothing, commits, point)
                    self.assertIs(
                        self.env.run_store.read(identity.run_id).publication_state,
                        state, point)
                    # 2. NEVER a false ANCHORED, at any point
                    self.assertNoFalseAnchored(identity.run_id)

                    # 3. recovery converges, and never to a second anchor
                    result = self.env.publish(identity)
                    self.assertIs(
                        result.outcome,
                        PublishOutcome.ALREADY_ANCHORED if commits
                        else PublishOutcome.ANCHORED, point)
                    self.assertEqual(len(self.env.store.records()), 1, point)
                    self.assertTrue(self.env.store.verify_chain(), point)
                    final = self.env.watermark()
                    assert final is not None
                    self.assertEqual(final.committed_record_digest,
                                     result.record.digest(), point)
                    trusted = self.env.run_store.read(identity.run_id)
                    self.assertIs(trusted.publication_state,
                                  PublicationState.ANCHORED, point)
                    self.assertEqual(trusted.anchor_record_digest,
                                     result.record.digest(), point)

    def test_a_crash_during_the_watermark_write_leaves_the_temp_unadopted(self):
        for point in ("F5", "F6"):
            with (self.subTest(point=point),
                    tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp):
                    root = Path(tmp)
                    self.env = _Env(root)
                    identity = self.env.new_run()
                    self._crash(root, point, identity.run_id)
                    leftovers = list(self.env.anchors.glob(WATERMARK_FILE + ".tmp-*"))
                    self.assertTrue(leftovers, f"{point}: no temp was left behind")
                    watermark = self.env.watermark()
                    assert watermark is not None
                    self.assertTrue(watermark.commits_nothing,
                                    f"{point}: a temp file became the commit point")

    def test_a_crash_after_the_ledger_flush_leaves_the_record_durable(self):
        """F3 specifically: the record IS on disk and survives the process, and
        it is still NOT committed. Durability of the write and commitment of the
        record are different things, which is the whole point of the watermark."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            self.env = _Env(root)
            identity = self.env.new_run()
            self._crash(root, "F3", identity.run_id)
            self.env.reopen()
            self.assertEqual(len(self.env.store.records()), 1)
            watermark = self.env.watermark()
            assert watermark is not None
            self.assertTrue(watermark.commits_nothing)
            report = reconcile_publication_state(
                self.env.store, self.env.run_store,
                expected_deployment_digest=DEPLOY, repair_uncommitted_tail=False)
            self.assertEqual(report.uncommitted_tail_records, 1)

    def test_a_partial_ledger_line_survives_the_crash_and_is_recoverable(self):
        """F1 specifically: the half-written line really is on disk, it makes
        the ledger unreadable to the record parser, and recovery still cuts it
        off cleanly instead of failing forever."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            self.env = _Env(root)
            identity = self.env.new_run()
            self._crash(root, "F1", identity.run_id)
            self.env.reopen()
            raw = self.env.store.ledger.read_bytes()
            self.assertTrue(raw, "the partial write did not reach the filesystem")
            self.assertFalse(raw.endswith(b"\n"), "the line is not partial")
            with self.assertRaises(AuthorityUnavailable):
                self.env.store.records()  # unreadable as records, by design
            result = self.env.publish(identity)
            self.assertIs(result.outcome, PublishOutcome.ANCHORED)
            self.assertEqual(len(self.env.store.records()), 1)


@HIGH_ONLY
class TestConcurrentTrustedPublishers(_EnvCase):
    """Trusted-writer coordination. FileLock is NOT claimed as a security
    boundary against a worker — Stage 6/8 ACLs are that — but it must stop two
    trusted publishers producing two records at one sequence, two commits, or a
    watermark race."""

    def _spawn(self, run_id: str, out: Path) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [sys.executable, "-c", _child_source(), "NONE", str(self.env.tmp),
             run_id, str(out)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(REPO))

    def test_two_publishers_racing_on_one_run_commit_exactly_one_anchor(self):
        identity = self.env.new_run("run-1")
        outs = [self.env.tmp / f"out-{i}.txt" for i in range(2)]
        procs = [self._spawn(identity.run_id, out) for out in outs]
        for proc in procs:
            _, err = proc.communicate(timeout=180)
            self.assertEqual(proc.returncode, 0, err)
        outcomes = sorted(out.read_text(encoding="utf-8") for out in outs)
        self.assertEqual(outcomes, ["ALREADY_ANCHORED", "ANCHORED"])
        self.env.reopen()
        self.assertEqual(len(self.env.store.records()), 1)
        self.assertTrue(self.env.store.verify_chain())

    def test_two_publishers_racing_on_two_runs_keep_the_chain_intact(self):
        first = self.env.new_run("run-1", tree="cd0")
        second = self.env.new_run("run-2", tree="cd1")
        outs = [self.env.tmp / "out-a.txt", self.env.tmp / "out-b.txt"]
        procs = [self._spawn(first.run_id, outs[0]), self._spawn(second.run_id, outs[1])]
        for proc in procs:
            _, err = proc.communicate(timeout=180)
            self.assertEqual(proc.returncode, 0, err)
        self.assertEqual([out.read_text(encoding="utf-8") for out in outs],
                         ["ANCHORED", "ANCHORED"])
        self.env.reopen()
        records = self.env.store.records()
        self.assertEqual([r.seq for r in records], [0, 1])
        self.assertEqual(records[1].prev_record_digest, records[0].digest())
        self.assertEqual({r.run_id for r in records}, {"run-1", "run-2"})
        self.assertTrue(self.env.store.verify_chain())
        watermark = self.env.watermark()
        assert watermark is not None
        self.assertEqual(watermark.committed_seq, 1)


# ---------------------------------------------------------------------------
# The fault seam is not a production surface
# ---------------------------------------------------------------------------
class TestTheFaultSeamIsNotReachableFromAnyInput(unittest.TestCase):
    SOURCES = (REPO / "src" / "gnosis" / "trust" / "publication.py",
               REPO / "src" / "gnosis" / "trust" / "anchor.py")

    def test_the_hook_is_none_in_a_clean_interpreter(self):
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, r'%s');"
             "import gnosis.trust.publication as p; print(p._FAULT_HOOK)"
             % (REPO / "src")],
            capture_output=True, text=True, check=True, cwd=str(REPO))
        self.assertEqual(out.stdout.strip(), "None")

    def test_no_environment_or_argument_can_switch_a_fault_on(self):
        """The seam may only be installed by in-process code that already
        imports the Trust Plane — which is inside the TCB by definition. There
        must be no path to it from the environment, a config file, the command
        line or anything a worker can influence."""
        forbidden = {"environ", "getenv", "argv", "input", "stdin", "argparse",
                     "environb", "get_config", "getvar"}
        for source in self.SOURCES:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            used |= {node.attr for node in ast.walk(tree)
                     if isinstance(node, ast.Attribute)}
            used |= {alias.name.split(".")[0] for node in ast.walk(tree)
                     if isinstance(node, ast.Import) for alias in node.names}
            offenders = sorted(used & forbidden)
            self.assertEqual(offenders, [], f"{source.name} reads {offenders}")

    def test_the_seam_is_inert_with_no_hook_installed(self):
        from gnosis.trust import publication

        self.assertIsNone(publication._FAULT_HOOK)
        publication._fault("F0", note="probe")   # no hook installed -> does nothing

    def test_the_seam_is_a_parameter_the_caller_passes_not_a_global_switch(self):
        """`AnchorStore.append` takes its fault hook as an argument that
        defaults to None, so an ordinary append — the Stage-3 path included —
        cannot fire one however the module-level hook is set."""
        from gnosis.trust import anchor

        fired: list[str] = []
        anchor._fire(None, "F1")
        self.assertEqual(fired, [])
        anchor._fire(lambda point, **_: fired.append(point), "F1")
        self.assertEqual(fired, ["F1"])


if __name__ == "__main__":
    unittest.main()
