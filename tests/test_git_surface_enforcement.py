"""F-17 Stage 7 — the classifier is connected to publication.

A closed-world classifier that no publication consults is decoration. These
tests prove the wiring: a capture whose .git boundary verdict is anything but
CLEAN — a Stage-7 MACHINERY_UNQUALIFIED, a MACHINERY_MUTATED, or an ABSENT
verdict (a pre-Stage-7 bundle) — cannot become an Anchor V2, at the
build_anchor_record chokepoint, at the authorize_publishable gate, and end to
end through the durable protocol.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gnosis.trust.anchor import (
    AnchorStore,
    RunIdentity,
    build_anchor_record,
)
from gnosis.trust.bundle_verify import write_bundle_manifest
from gnosis.trust.launch import AuthorityUnavailable
from gnosis.trust.orchestration import (
    CompletionEvidence,
    RunNotPublishable,
    authorize_publishable,
)
from gnosis.trust.publication import (
    PublicationResult,
    durable_publish,
    initialise_durable_store,
    read_watermark,
)
from gnosis.trust.run_identity import (
    PublicationRequest,
    PublicationState,
    TrustedRunIdentityStore,
)

SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"
DEPLOY = "d" * 64
LAUNCH = "a" * 64
HEAD = "h" * 40
TREE = "t" * 64

# A sentinel object never used: the class is UNKNOWN so this omission means
# "leave the boundary verdict out entirely".
_ABSENT = object()


def _make_bundle(path: Path, *, verdict: object = "CLEAN", head: str = HEAD,
                 tree: str = TREE) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    boundary: dict[str, object] = {"protection": {"content_digest": tree}}
    if verdict is not _ABSENT:
        boundary["verdict"] = verdict
    (path / "SUMMARY.json").write_text(json.dumps({
        "tree_identity": {"post": {"fingerprint": {"head_sha": head}}},
        "boundary": boundary,
    }), encoding="utf-8")
    write_bundle_manifest(path)
    return path


def _identity(run_id: str, bundle: Path) -> RunIdentity:
    return RunIdentity(
        task_id="F-17", run_id=run_id, repository_id="repoX", head_sha=HEAD,
        tree_identity=TREE, bundle_path=str(bundle), owner_worker_sid=SID,
        deployment_digest=DEPLOY, epoch=0, launch_spec_digest=LAUNCH)


# Every boundary verdict the capture can record that is NOT publishable, plus
# the absent case. A reviewer can see exactly what the gate refuses.
_NON_PUBLISHABLE = (
    "MACHINERY_UNQUALIFIED",   # the Stage 7 verdict: an unqualified .git surface
    "MACHINERY_MUTATED",       # a known trust-sensitive tamper
    "MACHINERY_REDIRECTED",    # resolution redirected
    "INPUTS_MUTATED",          # a covered input changed
    "UNOBSERVED",              # the interval was not observed
    "TREE_MUTATED",            # not a boundary verdict, but still not CLEAN
    "",                        # empty string
)


class TestBuildAnchorRecordGate(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = AnchorStore(self.root / "anchors", require_high=False)

    def test_a_clean_boundary_can_be_anchored(self):
        bundle = _make_bundle(self.root / "run-clean", verdict="CLEAN")
        record = build_anchor_record(self.store, _identity("run-clean", bundle),
                                     bundle)
        self.assertEqual(record.run_id, "run-clean")

    def test_a_non_clean_boundary_is_refused(self):
        for verdict in _NON_PUBLISHABLE:
            with self.subTest(verdict=verdict):
                bundle = _make_bundle(self.root / f"run-{verdict or 'empty'}",
                                      verdict=verdict)
                with self.assertRaises(AuthorityUnavailable) as caught:
                    build_anchor_record(self.store,
                                        _identity("run-x", bundle), bundle)
                self.assertIn("boundary verdict", str(caught.exception))

    def test_an_absent_boundary_verdict_is_refused(self):
        # A pre-Stage-7 bundle carries no verdict; it must not read as CLEAN.
        bundle = _make_bundle(self.root / "run-absent", verdict=_ABSENT)
        with self.assertRaises(AuthorityUnavailable):
            build_anchor_record(self.store, _identity("run-absent", bundle),
                                bundle)

    def test_the_gate_precedes_the_identity_cross_checks(self):
        # An unqualified bundle bound to the WRONG head must still be refused for
        # the boundary, so the machinery gate cannot be sidestepped by also
        # failing a later check — belt and suspenders, deterministic reason.
        bundle = _make_bundle(self.root / "run-both", verdict="MACHINERY_UNQUALIFIED",
                              head="0" * 40)
        with self.assertRaises(AuthorityUnavailable) as caught:
            build_anchor_record(self.store, _identity("run-both", bundle), bundle)
        self.assertIn("boundary verdict", str(caught.exception))


class TestAuthorizePublishableGate(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.run_store = TrustedRunIdentityStore(self.root / "runs")

    def _created(self, run_id: str, bundle: Path) -> RunIdentity:
        identity = _identity(run_id, bundle)
        self.run_store.create(identity)
        return identity

    def test_a_clean_capture_becomes_publishable(self):
        bundle = _make_bundle(self.root / "evidence" / "run-1", verdict="CLEAN")
        identity = self._created("run-1", bundle)
        record = authorize_publishable(
            self.run_store, identity,
            CompletionEvidence(0, False, False, bundle))
        self.assertIs(record.publication_state, PublicationState.PUBLISHABLE)

    def test_an_unqualified_capture_never_becomes_publishable(self):
        bundle = _make_bundle(self.root / "evidence" / "run-2",
                              verdict="MACHINERY_UNQUALIFIED")
        identity = self._created("run-2", bundle)
        with self.assertRaises(RunNotPublishable):
            authorize_publishable(self.run_store, identity,
                                  CompletionEvidence(0, False, False, bundle))
        self.assertIs(self.run_store.read("run-2").publication_state,
                      PublicationState.NOT_PUBLISHABLE)

    def test_an_absent_verdict_never_becomes_publishable(self):
        bundle = _make_bundle(self.root / "evidence" / "run-3", verdict=_ABSENT)
        identity = self._created("run-3", bundle)
        with self.assertRaises(RunNotPublishable):
            authorize_publishable(self.run_store, identity,
                                  CompletionEvidence(0, False, False, bundle))


class TestUnknownCannotReachAnchorV2(unittest.TestCase):
    """End to end through the durable protocol: the whole point of Stage 7."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = AnchorStore(self.root / "anchors", require_high=False)
        initialise_durable_store(self.store)
        self.run_store = TrustedRunIdentityStore(self.root / "runs")

    def _request(self, identity: RunIdentity) -> PublicationRequest:
        return PublicationRequest(
            run_id=identity.run_id,
            expected_owner_worker_sid=identity.owner_worker_sid,
            expected_deployment_digest=identity.deployment_digest,
            expected_epoch=identity.epoch,
            expected_repository_id=identity.repository_id,
            expected_head_sha=identity.head_sha,
            expected_tree_identity=identity.tree_identity,
            expected_launch_spec_digest=identity.launch_spec_digest)

    def _publishable_run(self, run_id: str, bundle: Path) -> RunIdentity:
        identity = _identity(run_id, bundle)
        self.run_store.create(identity)
        self.run_store.mark_publishable(run_id, identity.digest())
        return identity

    def test_a_clean_run_reaches_an_anchor(self):
        bundle = _make_bundle(self.root / "run-ok", verdict="CLEAN")
        identity = self._publishable_run("run-ok", bundle)
        result = durable_publish(self.store, self.run_store,
                                 self._request(identity), bundle)
        self.assertIsInstance(result, PublicationResult)
        self.assertEqual(len(self.store.records()), 1)

    def test_an_unqualified_run_produces_no_anchor_and_no_watermark_advance(self):
        bundle = _make_bundle(self.root / "run-unq", verdict="MACHINERY_UNQUALIFIED")
        identity = self._publishable_run("run-unq", bundle)
        before = read_watermark(self.store.root)
        with self.assertRaises(AuthorityUnavailable):
            durable_publish(self.store, self.run_store,
                            self._request(identity), bundle)
        self.assertEqual(self.store.records(), [],
                         "an unqualified capture must leave no anchor")
        after = read_watermark(self.store.root)
        self.assertEqual(before.committed_seq, after.committed_seq,
                         "the watermark must not advance for a refused publish")


if __name__ == "__main__":
    unittest.main()
