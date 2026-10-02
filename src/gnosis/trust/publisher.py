"""The trusted publisher: one verb, and every authority-bearing fact derived.

WHAT THE WORKER IS ALLOWED TO SAY.

    PUBLISH <run_id>

That is the entire request surface, and the bound is the point. Under T2 the
Worker is assumed compromised, so anything it can put on the wire is attacker
input; the defence is not to validate that input carefully but to have almost
none of it. A `run_id` is a selector, not an authorization: it says WHICH run to
look up and confers nothing by being said.

Everything the publication is judged on comes from somewhere the Worker cannot
reach:

    from the SERVICE'S OWN CONFIGURATION   the authorized worker SID, the
                                           expected deployment digest, the
                                           trusted state root, the evidence root
    from the TRUSTED RUN IDENTITY STORE    owner SID, deployment digest, launch
                                           spec digest, repository, head, tree,
                                           epoch, bundle path, publication state
    from the BUNDLE ITSELF, re-derived     the bundle digest

The Worker supplies none of them. It cannot name a path, a digest, a HEAD, a
tree, a SID, an epoch, a watermark or an operation - not because each is
filtered, but because the grammar has nowhere to put them.

WHY A CONFUSED DEPUTY IS THE THREAT. The publisher writes to state the Worker
cannot write to. Any argument the Worker can influence is therefore a lever on a
privileged writer, which is why `bundle_path` is read from the trusted record
rather than the request, and then still required to lie inside the configured
evidence root: the store is trusted, but a privileged process that opens
arbitrary paths on request is one store defect away from being a write oracle.

WHAT THIS MODULE DOES NOT DO. It does not capture evidence, observe the
filesystem, collect Git evidence, lock inputs, run tools, or launch anything.
Its import closure is measured, not asserted - see the Stage 6 closure probe.
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gnosis.trust.anchor import AnchorStore, RunIdentity
from gnosis.trust.bundle_verify import verify_bundle
from gnosis.trust.launch import AuthorityUnavailable
from gnosis.trust.publication import PublishOutcome, durable_publish
from gnosis.trust.run_identity import (
    PublicationRequest,
    TrustedRunIdentityStore,
)

# The one verb, and a run id that cannot be a path. The character class excludes
# `/`, `\`, `:` and `.` sequences by construction rather than by scanning for
# traversal afterwards: a run id that cannot express a path cannot traverse one.
_REQUEST = re.compile(r"^PUBLISH (?P<run_id>[A-Za-z0-9][A-Za-z0-9._-]{0,127})$")

# Re-checked here even though the pipe layer already bounds it. The parser must
# be safe when called by anything, not only by the transport that happens to
# front it today.
MAX_REQUEST_BYTES = 512


def _refused(reason: str) -> str:
    return f"REJECTED:{reason}"


@dataclass(frozen=True)
class PublisherConfig:
    """Everything the service knows WITHOUT being told by a client.

    Provisioned, not negotiated: the service is installed for exactly one
    worker identity and one deployment, and a request cannot change either.
    """

    trust_state_root: Path
    evidence_root: Path
    authorized_worker_sid: str
    expected_deployment_digest: str

    @property
    def anchors_root(self) -> Path:
        return self.trust_state_root / "anchors"

    @property
    def runidentity_root(self) -> Path:
        return self.trust_state_root / "runidentity"


def _resolved(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path))).rstrip("\\")


def _inside(root: Path, candidate: Path) -> bool:
    """Component-wise containment, so a sibling sharing a textual prefix fails.

    `C:\\evidence-old` starts with `C:\\evidence` as a string and is a different
    directory; comparing whole path components is what tells them apart.
    """
    root_parts = _resolved(root).split("\\")
    candidate_parts = _resolved(candidate).split("\\")
    return candidate_parts[: len(root_parts)] == root_parts


class Publisher:
    """Handles one bounded request at a time. Holds no per-client state."""

    def __init__(self, config: PublisherConfig,
                 log: Callable[[str], None] | None = None) -> None:
        self.config = config
        self._log = log
        self.store = AnchorStore(config.anchors_root, require_high=False)
        self.run_store = TrustedRunIdentityStore(config.runidentity_root)

    def _note(self, message: str) -> None:
        if self._log is not None:
            self._log(message)

    def handle(self, request: str, client_pid: int = 0) -> str:
        """Answer one request. Never raises: a crash is an availability bug the
        Worker could trigger at will, so every failure becomes a refusal."""
        try:
            return self._handle(request, client_pid)
        except Exception as exc:  # noqa: BLE001 - a refusal, never a crash
            self._note(f"handler error: {exc!r}")
            return _refused("handler-error")

    def publication_request(self, run_id: str,
                            identity: RunIdentity) -> PublicationRequest:
        """Build the trusted context this publication is judged against.

        PUBLIC AND SEPARATE ON PURPOSE. Mutation testing found that changing
        these two fields to read the run instead of the service changed nothing
        observable, because the refusals above already caught the mismatch -
        so the fields were untested, and an untested field is one refactor away
        from being wrong in a way nothing notices. Here they can be asserted
        directly: `expected_owner_worker_sid` and `expected_deployment_digest`
        come from the SERVICE'S configuration, never from the run being asked
        about, while the run-scoped fields come from the trusted record.
        """
        return PublicationRequest(
            run_id=run_id,
            expected_owner_worker_sid=self.config.authorized_worker_sid,
            expected_deployment_digest=self.config.expected_deployment_digest,
            expected_epoch=identity.epoch,
            expected_repository_id=identity.repository_id,
            expected_head_sha=identity.head_sha,
            expected_tree_identity=identity.tree_identity,
            expected_launch_spec_digest=identity.launch_spec_digest,
        )

    def _handle(self, request: str, client_pid: int) -> str:
        if len(request.encode("utf-8", errors="ignore")) > MAX_REQUEST_BYTES:
            return _refused("oversized")
        match = _REQUEST.match(request.strip())
        if match is None:
            # One message for every shape of malformed input: an attacker
            # learns nothing about which part offended.
            return _refused("bad-request")
        run_id = match.group("run_id")

        try:
            record = self.run_store.read(run_id)
        except AuthorityUnavailable as exc:
            self._note(f"unknown or unreadable run {run_id}: {exc}")
            return _refused("unknown-run")
        identity = record.identity

        # THE ONE INDEPENDENT IDENTITY CHECK. The service was installed for a
        # single worker; a run owned by anyone else is another worker's run, and
        # this is what makes `PUBLISH <someone else's run_id>` useless.
        if identity.owner_worker_sid != self.config.authorized_worker_sid:
            self._note(f"owner mismatch run={run_id}")
            return _refused("owner-mismatch")

        # THE DEPLOYMENT THE SERVICE IS RUNNING UNDER, compared against the one
        # the run was created under. Detection, on top of the ACL prevention
        # that stops the Worker changing either.
        if identity.deployment_digest != self.config.expected_deployment_digest:
            self._note(f"deployment mismatch run={run_id}")
            return _refused("deployment-mismatch")

        # A run whose identity carries no sealed launch intent cannot satisfy
        # Stage 6: its anchor would be untraceable to an authorized launch.
        if not identity.binds_launch_intent:
            return _refused("no-launch-binding")

        bundle_dir = Path(identity.bundle_path)
        if not _inside(self.config.evidence_root, bundle_dir):
            # The trusted store said a path outside the evidence root. Refuse
            # rather than open it: a privileged process that opens whatever a
            # record names is one store defect from being a write oracle.
            self._note(f"bundle outside the evidence root for run {run_id}")
            return _refused("bundle-outside-evidence-root")

        request_context = self.publication_request(run_id, identity)
        try:
            result = durable_publish(self.store, self.run_store, request_context,
                                     bundle_dir, verify=verify_bundle)
        except AuthorityUnavailable as exc:
            self._note(f"publication refused for run {run_id}: {exc}")
            return _refused(type(exc).__name__)

        if result.outcome is PublishOutcome.ALREADY_ANCHORED:
            return f"ALREADY_ANCHORED:seq={result.record.seq}"
        return (f"ANCHORED:{result.record.bundle_digest[:12]}:"
                f"seq={result.record.seq}")
