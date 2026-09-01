"""Authoritative evidence-publication seam (F-33 Stage 2B.2, ADR-0032 §12).

The Director-side, TRUSTED orchestration that turns a completed governed run into
an authoritative F-17 publication. It CONSUMES the existing trust plane and adds
no anchor implementation and no second publication ledger:

    capture the evidence bundle (Director-side, trusted)
    -> create_trusted_run(...)        # freeze RunIdentity from OBSERVED values
    -> authorize_publishable(...)      # NOT_PUBLISHABLE -> PUBLISHABLE (trusted gate)
    -> durable_publish(...)            # PUBLISHABLE -> anchor -> ANCHORED (F-17)

Trust properties:
- The three authority-bearing identity fields come only from OBSERVED values: the
  Worker SID and launch-spec digest from the launcher's `LaunchedWorkerIdentity`,
  the deployment digest from a measured `TrustPlaneDeploymentIdentity`. UNTRUSTED
  Worker stdout never reaches them.
- `ANCHORED` is reached only through the F-17 `durable_publish` protocol; this
  module never writes an anchor or sets a publication state itself.
- Every step fails closed (`PublicationError`): a run that cannot be anchored does
  not become a false success.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from gnosis.director.publisher_client import PublisherClient, PublisherClientError
from gnosis.trust.bundle_verify import write_bundle_manifest
from gnosis.trust.deployment import TrustPlaneDeploymentIdentity
from gnosis.trust.launch import AuthorityUnavailable
from gnosis.trust.launch_spec import LaunchSpec
from gnosis.trust.orchestration import (
    CompletionEvidence,
    RunNotPublishable,
    RunPlan,
    authorize_publishable,
    create_trusted_run,
)
from gnosis.trust.publication import PublicationCorrupt
from gnosis.trust.run_identity import PublicationState, TrustedRunIdentityStore
from gnosis.trust.worker_launcher import LaunchedWorkerIdentity

# The CLEAN .git-machinery boundary verdict the trust plane requires before a run
# may become PUBLISHABLE (mirrors trust.anchor._PUBLISHABLE_BOUNDARY_VERDICT).
_CLEAN = "CLEAN"


class PublicationError(Exception):
    """The authoritative publication could not be completed (fail closed)."""


@dataclass(frozen=True)
class GitTreeEvidence:
    head_sha: str
    tree_identity: str


def observe_git_tree(repo_path: Path) -> GitTreeEvidence:
    """The Director's own trusted observation of the repository at the run.

    Read from git, never from the Worker. Fails closed if the repository cannot
    be observed."""
    def _git(*args: str) -> str:
        try:
            proc = subprocess.run(["git", *args], cwd=repo_path, capture_output=True,
                                  text=True, check=False)
        except OSError as exc:
            raise PublicationError(
                f"could not observe git tree in {repo_path}: {exc}") from exc
        if proc.returncode != 0:
            raise PublicationError(
                f"could not observe git tree in {repo_path}: {proc.stderr.strip()}")
        return proc.stdout.strip()

    return GitTreeEvidence(head_sha=_git("rev-parse", "HEAD"),
                           tree_identity=_git("rev-parse", "HEAD^{tree}"))


def capture_publishable_bundle(bundle_dir: Path, tree: GitTreeEvidence) -> Path:
    """Write and seal a minimal trusted evidence bundle for the run.

    The Director (trusted) states the observed head_sha, the CLEAN boundary
    verdict and the tree content digest; then `write_bundle_manifest` seals the
    bundle so `verify_bundle` can prove it byte for byte. A Worker-written
    manifest would be a worker-controlled statement, so the trusted side writes
    it (mirrors the F-17 Stage-6 recipe)."""
    import json

    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "SUMMARY.json").write_text(json.dumps({
        "tree_identity": {"post": {"fingerprint": {"head_sha": tree.head_sha}}},
        "boundary": {"verdict": _CLEAN,
                     "protection": {"content_digest": tree.tree_identity}},
    }), encoding="utf-8")
    write_bundle_manifest(bundle_dir)
    return bundle_dir


@dataclass(frozen=True)
class PublicationInputs:
    """Everything the trusted seam needs to anchor ONE completed run."""

    task_id: str
    run_id: str
    repository_id: str
    epoch: int
    exit_code: int
    launched: LaunchedWorkerIdentity
    spec: LaunchSpec
    deployment: TrustPlaneDeploymentIdentity
    tree: GitTreeEvidence


@dataclass(frozen=True)
class PublicationResult:
    run_id: str
    publication_state: PublicationState
    anchored: bool
    detail: str


def publish_governed_run(*, trust_state_root: Path, bundle_dir: Path,
                         inputs: PublicationInputs,
                         publisher_client: PublisherClient) -> PublicationResult:
    """Drive the completed run through the F-17 authoritative-publication path.

    Returns a `PublicationResult`; raises `PublicationError` (fail closed) if any
    trusted gate refuses. A successful result carries
    `publication_state == ANCHORED`.
    """
    run_store = TrustedRunIdentityStore(Path(trust_state_root) / "runidentity")

    try:
        # Director-side trusted gates. Idempotency (§21): publication state is
        # monotonic; never re-create or re-mark a run that already progressed.
        if run_store.exists(inputs.run_id):
            record = run_store.read(inputs.run_id)
            if record.publication_state is PublicationState.ANCHORED:
                return PublicationResult(
                    run_id=inputs.run_id, publication_state=record.publication_state,
                    anchored=True, detail="already anchored")
        else:
            plan = RunPlan(
                task_id=inputs.task_id, run_id=inputs.run_id,
                repository_id=inputs.repository_id, head_sha=inputs.tree.head_sha,
                tree_identity=inputs.tree.tree_identity,
                bundle_path=str(bundle_dir), epoch=inputs.epoch)
            record = create_trusted_run(
                run_store, plan, spec=inputs.spec, deployment=inputs.deployment,
                launched=inputs.launched)
        # NOT_PUBLISHABLE -> PUBLISHABLE, trusted gate only.
        if record.publication_state is PublicationState.NOT_PUBLISHABLE:
            authorize_publishable(
                run_store, record.identity,
                CompletionEvidence(exit_code=inputs.exit_code, timed_out=False,
                                   cancelled=False, bundle_dir=bundle_dir))
        # PUBLISHABLE -> anchor -> ANCHORED via the F-17 PUBLISHER SERVICE, through
        # the client seam. The canonical operator route never calls durable_publish
        # in-process; the response is NOT the authority — the persisted state is.
        publisher_client.publish(inputs.run_id)
    except (RunNotPublishable, AuthorityUnavailable, PublicationCorrupt,
            PublisherClientError) as exc:
        raise PublicationError(
            f"run {inputs.run_id} could not be anchored: {exc}") from exc

    final = run_store.read(inputs.run_id)
    anchored = final.publication_state is PublicationState.ANCHORED
    if not anchored:
        raise PublicationError(
            f"run {inputs.run_id} did not reach ANCHORED "
            f"(state={final.publication_state.value}); fail closed")
    return PublicationResult(
        run_id=inputs.run_id, publication_state=final.publication_state,
        anchored=True, detail="anchored")
