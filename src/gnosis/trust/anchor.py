"""The evidence anchor: record, store, and publication protocol (F-17).

This is the AUTHORITATIVE implementation of the anchor slice of the Trust
Plane (moved verbatim from `kernel.authority` in the Stage-1 trust-plane
split; `kernel.authority` is now a compatibility re-export). It depends only
on the single canonical hash primitive (`kernel.canonical`) and the launch /
identity slice (`trust.launch`) for the publisher-identity precondition and
the MIC label — never on worker-plane code.

The OS boundary — not this module — is what stops a worker rewriting an
anchor: under the frozen P2 model a worker (a distinct SID, DACL-denied)
cannot write the ledger; this module enforces the LOGICAL integrity
(append-only, chained, re-verified) on top. `AnchorStore.append` and
`publish_anchor`/`verify_anchored_bundle` fail closed on a chain that does not
verify, a bundle that is not self-consistent, or a bundle bound to a different
run's head.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gnosis.kernel.canonical import GENESIS_HASH, hash_canonical
from gnosis.trust.launch import (
    AuthorityUnavailable,
    assert_publisher_identity,
    label_high_no_write_up,
)

ANCHOR_SCHEMA = "gnosis.anchor.v1"


@dataclass(frozen=True)
class AnchorRecord:
    """One published anchor. Binds WHICH run + WHICH source + WHICH bundle +
    WHICH digest, chained to the previous record. No general-purpose fields."""

    task_id: str
    run_id: str
    repository_id: str          # canonical repository identity (Director-held)
    head_sha: str               # the commit the bundle is bound to
    tree_identity: str          # implementation/tree identity (content digest)
    bundle_path: str            # bundle identity, repo-relative
    bundle_digest: str          # the trusted expected_digest
    seq: int
    prev_record_digest: str
    schema: str = ANCHOR_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "task_id": self.task_id, "run_id": self.run_id,
            "repository_id": self.repository_id, "head_sha": self.head_sha,
            "tree_identity": self.tree_identity, "bundle_path": self.bundle_path,
            "bundle_digest": self.bundle_digest, "seq": self.seq,
            "prev_record_digest": self.prev_record_digest,
        }

    def digest(self) -> str:
        """This record's own digest — the next record chains to it."""
        return hash_canonical(json.dumps(self.to_dict(), sort_keys=True))


class AnchorStore:
    """An append-only, hash-chained anchor ledger inside a directory only the
    trusted publisher can write.

    The OS boundary — not this class — is what stops a worker rewriting it: the
    worker (a distinct SID under P2; a Medium process under same-user MIC)
    cannot write the ledger file or its directory. This class enforces the
    LOGICAL integrity (append-only, chained, re-verified) on top.
    """

    LEDGER = "anchors.jsonl"

    def __init__(self, root: Path, *, require_high: bool = True) -> None:
        self.root = root
        self.ledger = root / self.LEDGER
        root.mkdir(parents=True, exist_ok=True)
        # Fail closed unless the current process is the trusted publisher. The
        # precondition lives in trust.launch (Stage 1: the same-user-MIC HIGH
        # check; future: the RESTRICTED service-SID gate). This is defence in
        # depth on top of the OS-enforced boundary, never a bare bypass.
        assert_publisher_identity(require_high=require_high)
        label_high_no_write_up(root)

    def records(self) -> list[AnchorRecord]:
        if not self.ledger.exists():
            return []
        out: list[AnchorRecord] = []
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(AnchorRecord(**json.loads(line)))
        return out

    def verify_chain(self) -> bool:
        prev = GENESIS_HASH
        for i, rec in enumerate(self.records()):
            if rec.seq != i or rec.prev_record_digest != prev:
                return False
            prev = rec.digest()
        return True

    def append(self, record: AnchorRecord) -> None:
        """Append a record, re-verifying the whole chain first. Fails closed
        on a chain that does not verify or a record that does not extend it."""
        if not self.verify_chain():
            raise AuthorityUnavailable("the anchor chain does not verify; refusing to extend")
        existing = self.records()
        expected_prev = existing[-1].digest() if existing else GENESIS_HASH
        if record.seq != len(existing) or record.prev_record_digest != expected_prev:
            raise AuthorityUnavailable("record does not extend the chain")
        with self.ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")

    def lookup(self, run_id: str) -> AnchorRecord | None:
        found: AnchorRecord | None = None
        for rec in self.records():
            if rec.run_id == run_id:
                found = rec  # last wins, but run_id should be unique
        return found

    def next_seq_and_prev(self) -> tuple[int, str]:
        recs = self.records()
        return (len(recs), recs[-1].digest() if recs else GENESIS_HASH)


@dataclass(frozen=True)
class RunIdentity:
    """The Director's OWN trusted record of a run. The publisher reconstructs
    the anchor from THIS, never from worker-supplied values — that is what
    stops the worker using the publisher as a confused-deputy write oracle."""

    task_id: str
    run_id: str
    repository_id: str
    head_sha: str
    bundle_path: str  # where the Director expects this run's bundle


def _bundle_head_sha(bundle_dir: Path) -> str | None:
    try:
        summary = json.loads((bundle_dir / "SUMMARY.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    post = summary.get("tree_identity", {}).get("post", {})
    fp = post.get("fingerprint") or {}
    value = fp.get("head_sha")
    return value if isinstance(value, str) else None


def _bundle_content_digest(bundle_dir: Path) -> str:
    try:
        summary = json.loads((bundle_dir / "SUMMARY.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    value = summary.get("boundary", {}).get("protection", {}).get("content_digest")
    return value if isinstance(value, str) else ""


def publish_anchor(store: AnchorStore, identity: RunIdentity, bundle_dir: Path,
                   verify: Any = None) -> AnchorRecord:
    """The publication protocol, run by the trusted publisher. It NEVER trusts
    a worker-supplied digest, path or identity:

    1. the bundle path comes from the Director's `identity`, not the worker;
    2. `verify_bundle` RECOMPUTES the digest from the bundle bytes;
    3. the bundle's own bound `head_sha` must equal the Director's `head_sha`
       (rejects a bundle from another run / a replayed old bundle);
    4. the record binds the Director-held identity, is chained, and is
       re-read after the write.
    """
    if verify is None:
        from gnosis.kernel.evidence_capture import verify_bundle  # lazy: avoid import cycle
        verify = verify_bundle
    result = verify(bundle_dir)
    if not getattr(result, "verified", False):
        raise AuthorityUnavailable("bundle is not self-consistent; refusing to anchor it")
    bound = _bundle_head_sha(bundle_dir)
    if bound is None or bound != identity.head_sha:
        raise AuthorityUnavailable(
            f"bundle is bound to {bound}, not the run's head {identity.head_sha}; "
            "refusing to anchor (cross-run / replay)")
    seq, prev = store.next_seq_and_prev()
    record = AnchorRecord(
        task_id=identity.task_id, run_id=identity.run_id,
        repository_id=identity.repository_id, head_sha=identity.head_sha,
        tree_identity=_bundle_content_digest(bundle_dir),
        bundle_path=identity.bundle_path, bundle_digest=result.bundle_digest,
        seq=seq, prev_record_digest=prev)
    store.append(record)
    reread = store.lookup(identity.run_id)
    if reread is None or reread.bundle_digest != record.bundle_digest:
        raise AuthorityUnavailable("the anchor did not read back as written")
    return record


def verify_anchored_bundle(store: AnchorStore, run_id: str, bundle_dir: Path,
                           verify: Any = None) -> bool:
    """Verify a bundle against the AUTHORITATIVE digest from the store — not a
    caller-supplied one. Fails closed on a missing record or a broken chain."""
    if verify is None:
        from gnosis.kernel.evidence_capture import verify_bundle  # lazy: avoid import cycle
        verify = verify_bundle
    if not store.verify_chain():
        raise AuthorityUnavailable("the anchor chain does not verify")
    record = store.lookup(run_id)
    if record is None:
        raise AuthorityUnavailable(f"no anchor record for run {run_id}; fail closed")
    result = verify(bundle_dir, expected_digest=record.bundle_digest)
    return bool(getattr(result, "verified", False))
