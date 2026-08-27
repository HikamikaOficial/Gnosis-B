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
import re
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
ANCHOR_SCHEMA_V2 = "gnosis.anchor.v2"

# The production writer emits V2 ONLY. V1 is recognised because historical
# anchors are historical evidence and breaking them would destroy it — but a V1
# record carries no deployment binding, so it can never satisfy the final F-17
# guarantee. The two are kept unable to masquerade as each other: a V1 record is
# refused if it carries V2 fields, a V2 record is refused if it lacks them, and
# `to_dict` emits the V2 keys ONLY for V2 — so a historical V1 digest still
# re-derives byte for byte.
CURRENT_ANCHOR_SCHEMA = ANCHOR_SCHEMA_V2
SUPPORTED_ANCHOR_SCHEMAS = frozenset({ANCHOR_SCHEMA, ANCHOR_SCHEMA_V2})

RUN_IDENTITY_SCHEMA = "gnosis.trust.run_identity.v1"
SUPPORTED_RUN_IDENTITY_SCHEMAS = frozenset({RUN_IDENTITY_SCHEMA})

# A Windows SID in its canonical string form. The authoritative worker identity
# is a SID and nothing else: a username, a display name, an environment
# variable or any caller-chosen label is refused, because those are not what the
# OS enforces against and are exactly what a worker could influence.
_SID_PATTERN = re.compile(r"^S-1-\d{1,10}(-\d{1,10}){1,15}$")
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class AnchorNotDeploymentBound(AuthorityUnavailable):
    """The anchor carries NO deployment binding at all — it is a V1 record.

    Deliberately distinct from "bound to a DIFFERENT deployment". They are not
    the same finding and must not produce the same answer: one is historical
    evidence that predates the binding and can be re-anchored under the current
    trust plane, the other is an attempt to verify evidence against a trust
    plane that did not produce it. Collapsing them into one error is what let
    mutant RM13 survive — the check read as load-bearing while the refusal
    actually came from `None != <digest>` by coincidence."""


def _require_digest(value: object, what: str) -> str:
    if not isinstance(value, str) or not _DIGEST_PATTERN.match(value):
        raise AuthorityUnavailable(
            f"{what} must be a 64-character lowercase hex digest; got {value!r}")
    return value


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
    # V2 ONLY. Two fields, each carrying a distinct guarantee that V1 could not:
    #   deployment_digest    WHICH trust plane produced this anchor (Stage 2)
    #   run_identity_digest  WHICH exact authorized run it belongs to — the whole
    #                        immutable identity, owner SID and epoch included, in
    #                        one value, so the record cannot be verified against a
    #                        different identity without the mismatch showing.
    # owner_worker_sid and epoch are NOT repeated here: they are already bound,
    # unambiguously, by run_identity_digest.
    deployment_digest: str | None = None
    run_identity_digest: str | None = None
    schema: str = CURRENT_ANCHOR_SCHEMA

    def __post_init__(self) -> None:
        if self.schema not in SUPPORTED_ANCHOR_SCHEMAS:
            raise AuthorityUnavailable(
                f"unknown anchor schema {self.schema!r}; refusing to read or write it")
        if self.schema == ANCHOR_SCHEMA_V2:
            _require_digest(self.deployment_digest, "a V2 anchor's deployment_digest")
            _require_digest(self.run_identity_digest, "a V2 anchor's run_identity_digest")
        elif self.deployment_digest is not None or self.run_identity_digest is not None:
            # A V1 record carrying V2 fields is the masquerade this refuses: it
            # would let an unbound anchor be read as a deployment-bound one.
            raise AuthorityUnavailable(
                f"a {ANCHOR_SCHEMA} record cannot carry V2 deployment binding; "
                "it is either a V1 record or a V2 one, never both")

    def to_dict(self) -> dict[str, Any]:
        out = {
            "schema": self.schema, "task_id": self.task_id, "run_id": self.run_id,
            "repository_id": self.repository_id, "head_sha": self.head_sha,
            "tree_identity": self.tree_identity, "bundle_path": self.bundle_path,
            "bundle_digest": self.bundle_digest, "seq": self.seq,
            "prev_record_digest": self.prev_record_digest,
        }
        if self.schema == ANCHOR_SCHEMA_V2:
            out["deployment_digest"] = self.deployment_digest
            out["run_identity_digest"] = self.run_identity_digest
        # A V1 record emits EXACTLY the V1 keys — no `deployment_digest: null`.
        # Historical digests must re-derive byte for byte or the historical
        # chains stop verifying, which would destroy the evidence V1 exists for.
        return out

    def digest(self) -> str:
        """This record's own digest — the next record chains to it."""
        return hash_canonical(json.dumps(self.to_dict(), sort_keys=True))

    @property
    def is_deployment_bound(self) -> bool:
        """True only for a record that names the trust plane that produced it.
        A V1 record is readable and verifiable under its historical contract,
        but it can never satisfy the final F-17 deployment-binding guarantee."""
        return self.schema == ANCHOR_SCHEMA_V2


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
        for number, line in enumerate(
                self.ledger.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                out.append(AnchorRecord(**json.loads(line)))
            except AuthorityUnavailable:
                raise
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                # A line with an unknown or missing field is ambiguous, and an
                # ambiguous anchor is not an anchor. Fail closed rather than let
                # a partially-understood record into the chain.
                raise AuthorityUnavailable(
                    f"anchor ledger line {number} is not a readable record: {exc}") from exc
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
    """The Director's OWN trusted record of a run — the IMMUTABLE identity.

    The publisher reconstructs the anchor from THIS, never from worker-supplied
    values; that is what stops the worker using the publisher as a
    confused-deputy write oracle. Extended in place for Stage 3 rather than
    duplicated into a parallel model: there is one run identity.

    Every field here is immutable by construction (a frozen dataclass) and
    fixed at creation. The MONOTONIC trusted state — whether this run may be
    published, and whether it has been anchored — deliberately lives OUTSIDE
    this object, in `trust.run_identity.TrustedRunIdentityStore`, so a lifecycle
    transition has no way to rewrite an identity field.

    `owner_worker_sid` provenance is FROZEN: it is set by the trusted launcher /
    Director from the OS-observed `TokenUser` SID of the token the worker was
    actually launched with (Stage 5). It is never a worker input, never a
    username, never an environment variable. Stage 3 validates the FORM
    strictly; Stage 5 supplies the real value.

    `deployment_digest` binds the run to the exact observed Trust Plane
    deployment (Stage 2). It is validated here by form only — this module does
    NOT import `trust.deployment`, so the publisher does not inherit that
    module's ~1052 lines to carry a digest it merely compares.
    """

    task_id: str
    run_id: str
    repository_id: str
    head_sha: str
    tree_identity: str      # Director-held tree/content identity, CROSS-CHECKED
                            # against the bundle rather than adopted from it
    bundle_path: str        # where the Director expects this run's bundle
    owner_worker_sid: str   # OS-observed TokenUser SID of the authorized worker
    deployment_digest: str  # the Stage-2 deployment this run belongs to
    epoch: int              # the EXISTING fencing generation (claims.TaskClaim.epoch)
    schema: str = RUN_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema not in SUPPORTED_RUN_IDENTITY_SCHEMAS:
            raise AuthorityUnavailable(f"unknown run-identity schema {self.schema!r}")
        for name in ("task_id", "run_id", "repository_id", "head_sha",
                     "tree_identity", "bundle_path"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise AuthorityUnavailable(
                    f"RunIdentity.{name} must be a non-empty string; got {value!r}")
        if not isinstance(self.owner_worker_sid, str) or not _SID_PATTERN.match(
                self.owner_worker_sid):
            raise AuthorityUnavailable(
                "owner_worker_sid must be a canonical Windows SID string "
                f"(S-1-...); got {self.owner_worker_sid!r}. A username, display "
                "name or label is not an identity the OS enforces against.")
        _require_digest(self.deployment_digest, "RunIdentity.deployment_digest")
        if isinstance(self.epoch, bool) or not isinstance(self.epoch, int) or self.epoch < 0:
            raise AuthorityUnavailable(
                f"RunIdentity.epoch must be a non-negative integer; got {self.epoch!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "task_id": self.task_id, "run_id": self.run_id,
            "repository_id": self.repository_id, "head_sha": self.head_sha,
            "tree_identity": self.tree_identity, "bundle_path": self.bundle_path,
            "owner_worker_sid": self.owner_worker_sid,
            "deployment_digest": self.deployment_digest, "epoch": self.epoch,
        }

    def digest(self) -> str:
        """The canonical digest of the WHOLE immutable identity.

        One value that answers "is this still exactly the run that was
        authorized?" — which is what makes a stale update, an ABA recreation and
        a cross-identity anchor all detectable by a single comparison. Uses the
        ONE canonical primitive (ADR-0004); no second hashing implementation."""
        return hash_canonical(self.to_dict())


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
    4. the bundle's own content digest must equal the Director's
       `tree_identity`. Until Stage 3 this field was ADOPTED from the bundle —
       a worker-supplied value written into the authoritative record. It is now
       cross-checked exactly like the head, and a mismatch refuses;
    5. the record binds the Director-held identity, names the deployment and
       the exact run identity (V2), is chained, and is re-read after the write.
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
    bundle_tree = _bundle_content_digest(bundle_dir)
    if bundle_tree != identity.tree_identity:
        raise AuthorityUnavailable(
            f"bundle carries tree identity {bundle_tree!r}, not the run's "
            f"{identity.tree_identity!r}; refusing to anchor a tree the Director "
            "did not dispatch")
    seq, prev = store.next_seq_and_prev()
    record = AnchorRecord(
        task_id=identity.task_id, run_id=identity.run_id,
        repository_id=identity.repository_id, head_sha=identity.head_sha,
        tree_identity=identity.tree_identity,
        bundle_path=identity.bundle_path, bundle_digest=result.bundle_digest,
        seq=seq, prev_record_digest=prev,
        deployment_digest=identity.deployment_digest,
        run_identity_digest=identity.digest(),
        schema=CURRENT_ANCHOR_SCHEMA)
    store.append(record)
    reread = store.lookup(identity.run_id)
    if reread is None or reread.bundle_digest != record.bundle_digest:
        raise AuthorityUnavailable("the anchor did not read back as written")
    return record


def verify_anchored_bundle(store: AnchorStore, run_id: str, bundle_dir: Path,
                           verify: Any = None, *,
                           expected_deployment_digest: str | None = None,
                           expected_run_identity_digest: str | None = None) -> bool:
    """Verify a bundle against the AUTHORITATIVE digest from the store — not a
    caller-supplied one. Fails closed on a missing record or a broken chain.

    Passing `expected_deployment_digest` (or `expected_run_identity_digest`)
    asserts the F-17 deployment binding: the record must be V2 and must name
    exactly that deployment / identity. A V1 record cannot satisfy it — it
    carries no binding at all — and is refused rather than being read as though
    it matched. Omitting both verifies under the historical contract (chain +
    authoritative bundle digest), which is what keeps existing V1 evidence
    verifiable.
    """
    if verify is None:
        from gnosis.kernel.evidence_capture import verify_bundle  # lazy: avoid import cycle
        verify = verify_bundle
    if not store.verify_chain():
        raise AuthorityUnavailable("the anchor chain does not verify")
    record = store.lookup(run_id)
    if record is None:
        raise AuthorityUnavailable(f"no anchor record for run {run_id}; fail closed")
    for expected, actual, what in (
            (expected_deployment_digest, record.deployment_digest, "deployment"),
            (expected_run_identity_digest, record.run_identity_digest, "run identity"),
    ):
        if expected is None:
            continue
        if not record.is_deployment_bound:
            raise AnchorNotDeploymentBound(
                f"anchor for run {run_id} is a {record.schema} record and carries no "
                f"{what} binding; it cannot satisfy a bound verification")
        if actual != expected:
            raise AuthorityUnavailable(
                f"anchor for run {run_id} names {what} {actual!r}, not the expected "
                f"{expected!r}; refusing (cross-{what.replace(' ', '-')})")
    result = verify(bundle_dir, expected_digest=record.bundle_digest)
    return bool(getattr(result, "verified", False))
