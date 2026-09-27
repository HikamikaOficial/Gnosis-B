from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.director import publication as publication_module
from gnosis.director import publication_checkpoint
from gnosis.director.publication import publish_governed_run
from gnosis.director.publication_checkpoint import PublicationCheckpointStore
from gnosis.kernel.claims import ClaimStore, StaleClaimError, WorkAuthority
from gnosis.kernel.execution_scope import ExecutionScope
from gnosis.kernel.lease import LeaseStore, StaleLeaseError
from gnosis.runner.claude_cli_runner import CancellationToken
from gnosis.trust.run_identity import PublicationState, TrustedRunIdentityStore
from tests import trust_fixtures as tf
from tests.test_publication_seam import _Base


class TestPublicationCheckpointFencing(_Base):
    def test_takeover_waits_for_admitted_publication_authorization(self):
        inputs = self._inputs()
        tf.capture_publishable_bundle(self.bundle_dir, inputs.tree)
        now = [100.0]
        authority = WorkAuthority(ClaimStore(self.root / "claims", clock=lambda: now[0]),
            LeaseStore(self.root / "leases", clock=lambda: now[0]),
            default_ttl_s=60, reclaim_grace_s=0, clock=lambda: now[0])
        grant = authority.acquire("brief", "old")
        scope = ExecutionScope.borrowed(authority, grant, CancellationToken())
        authorizing, competing, replaced = Event(), Event(), Event()
        original = publication_module.authorize_publishable
        client = self._client(inputs)

        def authorize(*args, **kwargs):
            authorizing.set()
            assert competing.wait(5)
            assert not replaced.wait(0.1)
            return original(*args, **kwargs)

        def take_over():
            assert authorizing.wait(5)
            now[0] = 200.0
            competing.set()
            authority.sweep()
            replacement = authority.acquire("brief", "new")
            replaced.set()
            record = TrustedRunIdentityStore(self.trust_state_root / "runidentity").read(inputs.run_id)
            assert record.publication_state is PublicationState.PUBLISHABLE
            assert record.identity.epoch == inputs.epoch
            return replacement

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(take_over)
            with (patch.object(publication_module, "authorize_publishable", side_effect=authorize),
                  patch.object(client, "publish") as send,
                  pytest.raises((StaleClaimError, StaleLeaseError))):
                publish_governed_run(trust_state_root=self.trust_state_root,
                    bundle_dir=self.bundle_dir, inputs=inputs,
                    publisher_client=client, scope=scope)
            replacement = future.result(timeout=10)
        send.assert_not_called()
        assert replacement.claim.epoch > grant.claim.epoch

    def test_replaced_controller_cannot_authorize_or_send_publication(self):
        inputs = self._inputs()
        tf.capture_publishable_bundle(self.bundle_dir, inputs.tree)
        authority = WorkAuthority(ClaimStore(self.root / "claims"),
                                  LeaseStore(self.root / "leases"), default_ttl_s=120)
        grant = authority.acquire("brief", "old")
        scope = ExecutionScope.borrowed(authority, grant, CancellationToken())
        authority.release(grant)
        authority.acquire("brief", "new")
        client = self._client(inputs)
        with (patch.object(client, "publish") as send,
              patch("gnosis.director.publication.create_trusted_run") as create,
              pytest.raises(StaleClaimError)):
            publish_governed_run(trust_state_root=self.trust_state_root,
                bundle_dir=self.bundle_dir, inputs=inputs, publisher_client=client,
                scope=scope)
        create.assert_not_called()
        send.assert_not_called()

    def test_takeover_during_reply_refuses_old_success_and_reconciles_exact_run(self):
        inputs = self._inputs()
        tf.capture_publishable_bundle(self.bundle_dir, inputs.tree)
        authority = WorkAuthority(ClaimStore(self.root / "claims"),
                                  LeaseStore(self.root / "leases"), default_ttl_s=120)
        grant = authority.acquire("brief", "old")
        old_scope = ExecutionScope.borrowed(authority, grant, CancellationToken())
        client = self._client(inputs)
        original = client.publish
        replacements = []

        def delayed_reply(run_id):
            reply = original(run_id)
            # These operations would deadlock if authority locks spanned RPC.
            authority.release(grant)
            replacements.append(authority.acquire("brief", "new"))
            return reply

        with (patch.object(client, "publish", side_effect=delayed_reply),
              pytest.raises(StaleLeaseError)):
            publish_governed_run(trust_state_root=self.trust_state_root,
                bundle_dir=self.bundle_dir, inputs=inputs, publisher_client=client,
                scope=old_scope)
        store = TrustedRunIdentityStore(self.trust_state_root / "runidentity")
        before = store.read(inputs.run_id)
        result = publish_governed_run(trust_state_root=self.trust_state_root,
            bundle_dir=self.bundle_dir, inputs=inputs, publisher_client=client,
            scope=ExecutionScope.borrowed(authority, replacements[0], CancellationToken()))
        assert result.anchored
        assert store.read(inputs.run_id) == before
        assert before.identity.epoch == inputs.epoch

    def test_takeover_after_verification_prevents_checkpoint_write(self):
        inputs = self._inputs()
        tf.capture_publishable_bundle(self.bundle_dir, inputs.tree)
        authority = WorkAuthority(ClaimStore(self.root / "claims"),
                                  LeaseStore(self.root / "leases"), default_ttl_s=120)
        grant = authority.acquire("brief", "old")
        token = CancellationToken()
        store = PublicationCheckpointStore(self.trust_state_root,
            self.bundle_dir.parent, ExecutionScope.borrowed(authority, grant, token))
        original = publication_checkpoint.verify_bundle

        def verify_and_replace(path):
            verified = original(path)
            assert verified.verified
            authority.release(grant)
            authority.acquire("brief", "new")
            return verified

        brief = DirectorBrief("brief", "work", "implement", BriefSource.MANUAL)
        with (patch.object(publication_checkpoint, "verify_bundle", side_effect=verify_and_replace),
              pytest.raises(StaleClaimError)):
            store.save(brief, inputs)
        assert not store.path_for("brief").exists()
        assert token.is_cancelled()
