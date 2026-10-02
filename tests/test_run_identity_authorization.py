"""F-17 Stage 3 — trusted RunIdentity, publication lifecycle, publish gate.

The property under test:

    knowing a run_id is NOT enough to produce ANCHORED.

A run may be anchored only if trusted state shows it is exactly the run that was
authorized — for that worker SID, that generation, that deployment, that
evidence identity and that lifecycle state. Every case below is a way that could
fail to hold: a worker claiming its own permission, an artifact from an earlier
generation, a bundle from another deployment, a run_id deleted and recreated
under a different identity, a V1 record read as though it carried a binding it
never had.

Nothing here installs anything: no worker account, no service, no launcher, no
pipe. The stores are temporary directories.
"""
from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from gnosis.kernel.canonical import GENESIS_HASH
from gnosis.trust.anchor import (
    ANCHOR_SCHEMA,
    ANCHOR_SCHEMA_V2,
    CURRENT_ANCHOR_SCHEMA,
    RUN_IDENTITY_SCHEMA,
    RUN_IDENTITY_SCHEMA_V2,
    AnchorRecord,
    AuthorityUnavailable,
    RunIdentity,
)
from gnosis.trust.run_identity import (
    PublicationDecision,
    PublicationRequest,
    PublicationState,
    PublicationVerdict,
    TrustedRunIdentityStore,
    TrustedRunRecord,
    authorize_publication,
    is_storable_run_id,
)

SID_A = "S-1-5-21-1111111111-2222222222-3333333333-1001"
SID_B = "S-1-5-21-1111111111-2222222222-3333333333-1002"
DEPLOY_1 = "d" * 64
DEPLOY_2 = "f" * 64
# Stage 6: the sealed launch intent a run was authorized from.
LAUNCH_1 = "a" * 64
LAUNCH_2 = "b" * 64
ANCHOR_DIGEST = "a" * 64


def _identity(run_id: str = "RUN-20260827T000000000Z-abcd1234", *,
              head: str = "h" * 40, tree: str = "t" * 64, sid: str = SID_A,
              deployment: str = DEPLOY_1, epoch: int = 3,
              repo: str = "repoX", task: str = "TASK-1",
              launch: str | None = LAUNCH_1,
              schema: str | None = None) -> RunIdentity:
    return RunIdentity(task_id=task, run_id=run_id, repository_id=repo,
                       head_sha=head, tree_identity=tree,
                       bundle_path=".gnosis/evidence/x", owner_worker_sid=sid,
                       deployment_digest=deployment, epoch=epoch,
                       launch_spec_digest=launch,
                       **({} if schema is None else {"schema": schema}))


def _request(identity: RunIdentity, **overrides: object) -> PublicationRequest:
    """The trusted context that MATCHES an identity, unless overridden."""
    base: dict[str, object] = {
        "run_id": identity.run_id,
        "expected_owner_worker_sid": identity.owner_worker_sid,
        "expected_deployment_digest": identity.deployment_digest,
        "expected_epoch": identity.epoch,
        "expected_repository_id": identity.repository_id,
        "expected_head_sha": identity.head_sha,
        "expected_tree_identity": identity.tree_identity,
        "expected_launch_spec_digest": identity.launch_spec_digest,
    }
    base.update(overrides)
    return PublicationRequest(**base)  # type: ignore[arg-type]


class _StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = TrustedRunIdentityStore(Path(self._tmp.name) / "runs")

    def publishable(self, identity: RunIdentity) -> RunIdentity:
        self.store.create(identity)
        self.store.mark_publishable(identity.run_id, identity.digest())
        return identity


# ---------------------------------------------------------------------------
# The immutable identity contract
# ---------------------------------------------------------------------------
class TestTheRunIdentityContract(unittest.TestCase):
    def test_owner_worker_sid_must_be_a_canonical_sid(self):
        for bad in ("nicol", "GNOSIS\\GnosisWorker", "%USERNAME%", "",
                    "S-1", "s-1-5-21-1-2-3-1001", "S-1-5-21-1-2-3-1001 ",
                    "NT SERVICE\\GnosisWorker"):
            with self.assertRaises(AuthorityUnavailable, msg=bad):
                _identity(sid=bad)
        # a real SID shape is accepted
        self.assertEqual(_identity(sid=SID_B).owner_worker_sid, SID_B)

    def test_deployment_digest_must_be_a_real_digest(self):
        for bad in ("", "not-a-digest", "D" * 64, "a" * 63, "a" * 65):
            with self.assertRaises(AuthorityUnavailable, msg=bad):
                _identity(deployment=bad)

    def test_epoch_must_be_a_non_negative_integer(self):
        for bad in (-1, True, "3", 1.0, None):
            with self.assertRaises(AuthorityUnavailable, msg=repr(bad)):
                _identity(epoch=bad)  # type: ignore[arg-type]
        self.assertEqual(_identity(epoch=0).epoch, 0)

    def test_every_identity_component_must_be_present(self):
        for field in ("task_id", "repository_id", "head_sha", "tree_identity",
                      "bundle_path"):
            with self.assertRaises(AuthorityUnavailable, msg=field):
                dataclasses.replace(_identity(), **{field: ""})

    def test_an_unknown_identity_schema_is_refused(self):
        with self.assertRaises(AuthorityUnavailable):
            dataclasses.replace(_identity(), schema="gnosis.trust.run_identity.v9")

    def test_the_identity_is_immutable_and_its_digest_is_stable(self):
        identity = _identity()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            identity.owner_worker_sid = SID_B  # type: ignore[misc]
        self.assertEqual(identity.digest(), _identity().digest())
        self.assertEqual(len(identity.digest()), 64)

    def test_changing_any_immutable_field_changes_the_identity(self):
        base = _identity().digest()
        for change in ({"head": "0" * 40}, {"tree": "1" * 64}, {"sid": SID_B},
                       {"deployment": DEPLOY_2}, {"epoch": 4}, {"repo": "other"},
                       {"task": "TASK-2"}, {"run_id": "RUN-other"}):
            self.assertNotEqual(base, _identity(**change).digest(), change)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Anchor V1 / V2 — schema confusion defences
# ---------------------------------------------------------------------------
class TestTheAnchorSchemas(unittest.TestCase):
    def _v2(self, **overrides: object) -> AnchorRecord:
        base: dict[str, object] = {
            "task_id": "t", "run_id": "r", "repository_id": "repo",
            "head_sha": "h", "tree_identity": "tr", "bundle_path": "b",
            "bundle_digest": "d", "seq": 0, "prev_record_digest": GENESIS_HASH,
            "deployment_digest": DEPLOY_1, "run_identity_digest": "e" * 64,
            "schema": ANCHOR_SCHEMA_V2}
        base.update(overrides)
        return AnchorRecord(**base)  # type: ignore[arg-type]

    def test_1_a_v2_record_without_a_deployment_digest_is_refused(self):
        with self.assertRaises(AuthorityUnavailable):
            self._v2(deployment_digest=None)
        with self.assertRaises(AuthorityUnavailable):
            self._v2(run_identity_digest=None)

    def test_4_a_v2_record_with_a_malformed_digest_is_refused(self):
        for bad in ("", "nope", "D" * 64, "a" * 63):
            with self.assertRaises(AuthorityUnavailable, msg=bad):
                self._v2(deployment_digest=bad)

    def test_2_a_v1_record_cannot_masquerade_as_a_v2_one(self):
        # carrying V2 fields under the V1 schema is refused outright...
        with self.assertRaises(AuthorityUnavailable):
            self._v2(schema=ANCHOR_SCHEMA)
        # ...and a genuine V1 record never grows them by serialisation.
        v1 = AnchorRecord("t", "r", "repo", "h", "tr", "b", "d", 0, GENESIS_HASH,
                          schema=ANCHOR_SCHEMA)
        self.assertNotIn("deployment_digest", v1.to_dict())
        self.assertNotIn("run_identity_digest", v1.to_dict())
        self.assertFalse(v1.is_deployment_bound)
        # round-tripping a V1 dict yields a V1 record, never a defaulted V2 one
        self.assertEqual(AnchorRecord(**v1.to_dict()).schema, ANCHOR_SCHEMA)
        self.assertIsNone(AnchorRecord(**v1.to_dict()).deployment_digest)

    def test_3_an_unknown_anchor_schema_is_refused(self):
        for bad in ("gnosis.anchor.v3", "", "anchor", None):
            with self.assertRaises(AuthorityUnavailable, msg=repr(bad)):
                self._v2(schema=bad)

    def test_7_a_historical_v1_digest_still_re_derives_byte_for_byte(self):
        # V1 evidence is historical evidence: if serialising a V1 record changed
        # its bytes, every historical chain would stop verifying.
        v1 = AnchorRecord("t", "r", "repo", "h", "tr", "b", "d", 0, GENESIS_HASH,
                          schema=ANCHOR_SCHEMA)
        self.assertEqual(v1.to_dict(), {
            "schema": ANCHOR_SCHEMA, "task_id": "t", "run_id": "r",
            "repository_id": "repo", "head_sha": "h", "tree_identity": "tr",
            "bundle_path": "b", "bundle_digest": "d", "seq": 0,
            "prev_record_digest": GENESIS_HASH})
        self.assertEqual(v1.digest(), AnchorRecord(**v1.to_dict()).digest())

    def test_the_production_writer_emits_v2(self):
        self.assertEqual(CURRENT_ANCHOR_SCHEMA, ANCHOR_SCHEMA_V2)
        self.assertTrue(self._v2().is_deployment_bound)
        self.assertEqual(self._v2().digest(), AnchorRecord(**self._v2().to_dict()).digest())


# ---------------------------------------------------------------------------
# The trusted store
# ---------------------------------------------------------------------------
class TestTheTrustedStore(_StoreCase):
    def test_a_new_run_starts_not_publishable(self):
        record = self.store.create(_identity())
        self.assertIs(record.publication_state, PublicationState.NOT_PUBLISHABLE)
        self.assertIsNone(record.anchor_record_digest)

    def test_create_is_idempotent_for_an_identical_identity_and_does_not_reset_state(self):
        identity = self.publishable(_identity())
        again = self.store.create(identity)
        self.assertIs(again.publication_state, PublicationState.PUBLISHABLE)

    def test_n_a_run_id_is_never_rebound_to_a_different_identity(self):
        # create -> (worker-plane run directory deleted) -> recreate with a
        # different identity. The trusted store still holds the original, so the
        # ABA recreation is refused rather than accepted as a fresh run.
        identity = _identity()
        self.store.create(identity)
        for different in (_identity(head="0" * 40), _identity(sid=SID_B),
                          _identity(epoch=4), _identity(deployment=DEPLOY_2)):
            with self.assertRaises(AuthorityUnavailable):
                self.store.create(different)

    def test_k_publication_state_cannot_regress_or_skip(self):
        identity = _identity()
        self.store.create(identity)
        digest = identity.digest()
        # skipping straight to ANCHORED is not a permitted transition
        with self.assertRaises(AuthorityUnavailable):
            self.store.mark_anchored(identity.run_id, digest, ANCHOR_DIGEST)
        self.store.mark_publishable(identity.run_id, digest)
        with self.assertRaises(AuthorityUnavailable):
            self.store.transition(identity.run_id, digest,
                                  PublicationState.NOT_PUBLISHABLE)
        self.store.mark_anchored(identity.run_id, digest, ANCHOR_DIGEST)
        for target in (PublicationState.PUBLISHABLE, PublicationState.NOT_PUBLISHABLE,
                       PublicationState.ANCHORED):
            with self.assertRaises(AuthorityUnavailable, msg=target):
                self.store.transition(identity.run_id, digest, target,
                                      anchor_record_digest=ANCHOR_DIGEST)

    def test_anchored_cannot_be_reached_without_naming_the_anchor_record(self):
        identity = self.publishable(_identity())
        for bad in (None, "", "not-a-digest", "a" * 63):
            with self.assertRaises(AuthorityUnavailable, msg=repr(bad)):
                self.store.mark_anchored(identity.run_id, identity.digest(), bad)  # type: ignore[arg-type]
        with self.assertRaises(AuthorityUnavailable):
            TrustedRunRecord(identity=identity,
                             publication_state=PublicationState.ANCHORED)
        with self.assertRaises(AuthorityUnavailable):
            TrustedRunRecord(identity=identity,
                             publication_state=PublicationState.PUBLISHABLE,
                             anchor_record_digest=ANCHOR_DIGEST)

    def test_j_a_transition_carries_no_identity_so_it_cannot_rewrite_one(self):
        identity = self.publishable(_identity())
        self.store.mark_anchored(identity.run_id, identity.digest(), ANCHOR_DIGEST)
        stored = self.store.read(identity.run_id)
        self.assertEqual(stored.identity, identity)
        self.assertEqual(stored.identity_digest, identity.digest())

    def test_j_a_tampered_stored_identity_is_refused_by_the_compare_and_set(self):
        identity = self.publishable(_identity())
        path = self.store.path_for(identity.run_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["identity"]["owner_worker_sid"] = SID_B      # a rewritten immutable field
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(AuthorityUnavailable):
            self.store.mark_anchored(identity.run_id, identity.digest(), ANCHOR_DIGEST)

    def test_i_a_corrupted_record_fails_closed(self):
        identity = self.publishable(_identity())
        path = self.store.path_for(identity.run_id)
        for corrupt in ("{not json",
                        json.dumps({"schema": "gnosis.trust.run_record.v9"}),
                        json.dumps({"identity": {}, "publication_state": "PUBLISHABLE"}),
                        json.dumps({"identity": _identity().to_dict(),
                                    "publication_state": "SOMETHING"}),
                        json.dumps({"identity": _identity().to_dict(),
                                    "publication_state": "PUBLISHABLE",
                                    "surprise": 1})):
            path.write_text(corrupt, encoding="utf-8")
            with self.assertRaises(AuthorityUnavailable, msg=corrupt[:40]):
                self.store.read(identity.run_id)

    def test_a_record_filed_under_the_wrong_run_id_is_refused(self):
        identity = self.publishable(_identity())
        path = self.store.path_for(identity.run_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["identity"]["run_id"] = "RUN-somebody-else"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(AuthorityUnavailable):
            self.store.read(identity.run_id)

    def test_a_run_id_that_is_not_a_safe_record_name_is_refused(self):
        for bad in ("../escape", "a/b", "a\\b", "..", ".", "", "C:evil",
                    "x" * 129, "-leading", "run id"):
            self.assertFalse(is_storable_run_id(bad), bad)
            with self.assertRaises(AuthorityUnavailable, msg=bad):
                self.store.path_for(bad)
        self.assertTrue(is_storable_run_id("RUN-20260827T000000000Z-abcd1234"))

    def test_a_stale_expected_digest_is_refused(self):
        identity = self.publishable(_identity())
        with self.assertRaises(AuthorityUnavailable):
            self.store.mark_anchored(identity.run_id, "0" * 64, ANCHOR_DIGEST)


# ---------------------------------------------------------------------------
# The publish authorization gate
# ---------------------------------------------------------------------------
class TestThePublishAuthorizationGate(_StoreCase):
    def _decide(self, identity: RunIdentity, **overrides: object) -> PublicationDecision:
        return authorize_publication(self.store, _request(identity, **overrides))

    def test_a_a_publishable_run_with_matching_trusted_context_is_authorized(self):
        identity = self.publishable(_identity())
        decision = self._decide(identity)
        self.assertIs(decision.verdict, PublicationVerdict.AUTHORIZED)
        self.assertTrue(decision.authorized)
        self.assertEqual(decision.reason, "")

    def test_b_a_not_publishable_run_is_refused(self):
        identity = _identity()
        self.store.create(identity)
        decision = self._decide(identity)
        self.assertIs(decision.verdict, PublicationVerdict.REFUSED)
        self.assertIn("NOT_PUBLISHABLE", decision.reason)

    def test_c_a_different_worker_sid_is_refused(self):
        identity = self.publishable(_identity())
        decision = self._decide(identity, expected_owner_worker_sid=SID_B)
        self.assertIs(decision.verdict, PublicationVerdict.REFUSED)
        self.assertIn("owner_worker_sid", decision.reason)

    def test_d_a_different_deployment_is_refused(self):
        identity = self.publishable(_identity())
        decision = self._decide(identity, expected_deployment_digest=DEPLOY_2)
        self.assertIs(decision.verdict, PublicationVerdict.REFUSED)
        self.assertIn("deployment_digest", decision.reason)

    def test_e_and_m_a_different_generation_is_refused(self):
        identity = self.publishable(_identity(epoch=3))
        for other in (2, 4, 0):
            decision = self._decide(identity, expected_epoch=other)
            self.assertIs(decision.verdict, PublicationVerdict.REFUSED)
            self.assertIn("epoch", decision.reason)

    def test_f_a_head_mismatch_is_refused(self):
        identity = self.publishable(_identity())
        decision = self._decide(identity, expected_head_sha="0" * 40)
        self.assertIs(decision.verdict, PublicationVerdict.REFUSED)
        self.assertIn("head_sha", decision.reason)

    def test_g_a_tree_mismatch_is_refused(self):
        identity = self.publishable(_identity())
        decision = self._decide(identity, expected_tree_identity="0" * 64)
        self.assertIs(decision.verdict, PublicationVerdict.REFUSED)
        self.assertIn("tree_identity", decision.reason)

    def test_a_repository_mismatch_is_refused(self):
        identity = self.publishable(_identity())
        decision = self._decide(identity, expected_repository_id="other-repo")
        self.assertIs(decision.verdict, PublicationVerdict.REFUSED)
        self.assertIn("repository_id", decision.reason)

    def test_h_an_unknown_run_is_refused(self):
        decision = authorize_publication(
            self.store, _request(_identity(run_id="RUN-never-created")))
        self.assertIs(decision.verdict, PublicationVerdict.REFUSED)
        self.assertIsNone(decision.record)

    def test_h_an_unsafe_run_id_is_refused_without_touching_the_store(self):
        decision = authorize_publication(self.store, _request(_identity(), run_id="../x"))
        self.assertIs(decision.verdict, PublicationVerdict.REFUSED)

    def test_i_a_corrupted_identity_authorizes_nothing(self):
        identity = self.publishable(_identity())
        self.store.path_for(identity.run_id).write_text("{corrupt", encoding="utf-8")
        self.assertIs(self._decide(identity).verdict, PublicationVerdict.REFUSED)

    def test_l_a_second_publication_is_explicitly_already_anchored(self):
        identity = self.publishable(_identity())
        self.store.mark_anchored(identity.run_id, identity.digest(), ANCHOR_DIGEST)
        decision = self._decide(identity)
        self.assertIs(decision.verdict, PublicationVerdict.ALREADY_ANCHORED)
        self.assertFalse(decision.authorized)
        self.assertIn(ANCHOR_DIGEST, decision.reason)

    def test_a_mismatched_request_is_never_answered_already_anchored(self):
        # a wrong-identity request must not receive a state-flavoured verdict
        identity = self.publishable(_identity())
        self.store.mark_anchored(identity.run_id, identity.digest(), ANCHOR_DIGEST)
        decision = self._decide(identity, expected_owner_worker_sid=SID_B)
        self.assertIs(decision.verdict, PublicationVerdict.REFUSED)

    def test_q_nothing_a_worker_controls_can_make_a_run_publishable(self):
        # A worker's bundle, evidence, return code or self-reported status has
        # no field in the trusted request and no route into the trusted store.
        identity = _identity()
        self.store.create(identity)
        worker_claim = {"publication_state": "PUBLISHABLE", "lifecycle": "PUBLISHABLE",
                        "authorized": True, "exit_code": 0}
        self.assertIs(self._decide(identity).verdict, PublicationVerdict.REFUSED)
        self.assertEqual(
            [f for f in worker_claim if hasattr(_request(identity), f)], [])
        # every field of the trusted request is an EXPECTED trusted value
        for field in dataclasses.fields(_request(identity)):
            self.assertTrue(field.name == "run_id" or field.name.startswith("expected_"),
                            field.name)
        # and the only route to PUBLISHABLE is a trusted transition
        self.store.mark_publishable(identity.run_id, identity.digest())
        self.assertIs(self._decide(identity).verdict, PublicationVerdict.AUTHORIZED)

    def test_r_a_deployed_package_claim_cannot_override_the_deployment_digest(self):
        # Stage 2 records package_version/source_commit/source_tree as OBSERVED
        # DEPLOYED PACKAGE CLAIMS. They are claims: they cannot stand in for the
        # deployment digest, and there is no field through which they could.
        identity = self.publishable(_identity(deployment=DEPLOY_1))
        package_claim = {"source_commit": "c" * 40, "package_version": "9.9.9",
                         "deployment_digest": DEPLOY_2}
        decision = self._decide(identity,
                                expected_deployment_digest=package_claim["deployment_digest"])
        self.assertIs(decision.verdict, PublicationVerdict.REFUSED)
        self.assertIn("deployment_digest", decision.reason)
        for claim in ("source_commit", "package_version"):
            self.assertFalse(hasattr(_request(identity), claim))

    def test_the_gate_changes_nothing(self):
        identity = self.publishable(_identity())
        before = self.store.path_for(identity.run_id).read_text(encoding="utf-8")
        self._decide(identity)
        self._decide(identity, expected_epoch=99)
        self.assertEqual(before,
                         self.store.path_for(identity.run_id).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Cross-worker / cross-deployment / cross-generation, stated as such
# ---------------------------------------------------------------------------
class TestConfusedIdentityIsRefused(_StoreCase):
    def test_cross_worker_a_run_owned_by_sid_a_is_not_publishable_as_sid_b(self):
        run_a = self.publishable(_identity(run_id="RUN-a", sid=SID_A))
        self.assertIs(authorize_publication(
            self.store, _request(run_a, expected_owner_worker_sid=SID_B)).verdict,
            PublicationVerdict.REFUSED)
        self.assertIs(authorize_publication(self.store, _request(run_a)).verdict,
                      PublicationVerdict.AUTHORIZED)

    def test_cross_deployment_evidence_stays_bound_to_the_trust_plane_that_made_it(self):
        run = self.publishable(_identity(deployment=DEPLOY_1))
        decision = authorize_publication(
            self.store, _request(run, expected_deployment_digest=DEPLOY_2))
        self.assertIs(decision.verdict, PublicationVerdict.REFUSED)
        # "the bundle verifies" is not an argument the gate accepts: it never
        # looks at a bundle at all.
        self.assertIsNone(getattr(decision, "bundle", None))

    def test_cross_generation_an_older_epoch_cannot_publish_as_a_newer_one(self):
        old = self.publishable(_identity(run_id="RUN-old", epoch=1))
        self.assertIs(authorize_publication(
            self.store, _request(old, expected_epoch=2)).verdict,
            PublicationVerdict.REFUSED)


class TestTheSealedLaunchIntentIsPartOfTheAuthorization(_StoreCase):
    """F-17 Stage 6. A run is authorized for the launch it came from.

    Two runs of the same worker, under the same deployment, at the same epoch,
    differ only in what the Director actually sealed. Without this comparison
    the evidence could not tell them apart.
    """

    def test_a_matching_launch_intent_authorizes(self):
        run = self.publishable(_identity(launch=LAUNCH_1))
        self.assertIs(authorize_publication(self.store, _request(run)).verdict,
                      PublicationVerdict.AUTHORIZED)

    def test_a_different_sealed_launch_is_refused(self):
        run = self.publishable(_identity(launch=LAUNCH_1))
        decision = authorize_publication(
            self.store, _request(run, expected_launch_spec_digest=LAUNCH_2))
        self.assertIs(decision.verdict, PublicationVerdict.REFUSED)
        self.assertIn("launch_spec_digest", decision.reason)

    def test_a_launch_binding_is_not_satisfied_by_declining_to_check_it(self):
        # The failure mode this exists for: a caller that simply omits the
        # expectation would otherwise skip the binding entirely.
        run = self.publishable(_identity(launch=LAUNCH_1))
        decision = authorize_publication(
            self.store, _request(run, expected_launch_spec_digest=None))
        self.assertIs(decision.verdict, PublicationVerdict.REFUSED)
        # The REASON is asserted, not merely the refusal. Without the guard the
        # comparison below would also refuse, so only the diagnosis
        # distinguishes them - and a mutant that deleted the guard survived
        # precisely because nothing looked at the diagnosis.
        self.assertIn("carries no expected launch_spec_digest", decision.reason)

    def test_a_v1_identity_cannot_satisfy_a_launch_expectation(self):
        run = self.publishable(_identity(run_id="RUN-v1", launch=None,
                                         schema=RUN_IDENTITY_SCHEMA))
        decision = authorize_publication(
            self.store, _request(run, expected_launch_spec_digest=LAUNCH_1))
        self.assertIs(decision.verdict, PublicationVerdict.REFUSED)

    def test_the_launch_binding_is_refused_before_a_state_flavoured_verdict(self):
        # A mismatched request must never be answered ALREADY_ANCHORED, which
        # would read as though it nearly succeeded and leak that the run exists
        # in a published state.
        run = _identity(run_id="RUN-anch", launch=LAUNCH_1)
        self.store.create(run)
        self.store.mark_publishable("RUN-anch", run.digest())
        self.store.mark_anchored("RUN-anch", run.digest(), "0" * 64)
        decision = authorize_publication(
            self.store, _request(run, expected_launch_spec_digest=LAUNCH_2))
        self.assertIs(decision.verdict, PublicationVerdict.REFUSED)


class TestTheV2IdentityContract(unittest.TestCase):
    """Asserted directly because nothing else constructs an invalid V2.

    The orchestration seam always supplies a launch digest, so a mutant that
    removed the requirement changed no observable behaviour anywhere. The
    contract has to be tested where it lives.
    """

    def test_a_v2_identity_without_a_launch_binding_is_refused(self):
        with self.assertRaises(AuthorityUnavailable):
            _identity(launch=None, schema=RUN_IDENTITY_SCHEMA_V2)

    def test_a_v2_identity_with_a_malformed_launch_digest_is_refused(self):
        for bad in ("", "not-a-digest", "A" * 64, "a" * 63, "a" * 65):
            with self.assertRaises(AuthorityUnavailable, msg=bad):
                _identity(launch=bad, schema=RUN_IDENTITY_SCHEMA_V2)

    def test_a_v1_identity_carrying_a_launch_binding_is_refused(self):
        with self.assertRaises(AuthorityUnavailable):
            _identity(launch=LAUNCH_1, schema=RUN_IDENTITY_SCHEMA)

    def test_the_launch_binding_changes_the_identity_digest(self):
        self.assertNotEqual(_identity(launch=LAUNCH_1).digest(),
                            _identity(launch=LAUNCH_2).digest())

    def test_a_v1_identity_emits_exactly_the_v1_keys(self):
        v1 = _identity(launch=None, schema=RUN_IDENTITY_SCHEMA)
        self.assertNotIn("launch_spec_digest", v1.to_dict())


if __name__ == "__main__":
    unittest.main()
