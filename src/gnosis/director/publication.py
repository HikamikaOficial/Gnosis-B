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
from gnosis.kernel.execution_scope import ExecutionScope
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
                         publisher_client: PublisherClient,
                         scope: ExecutionScope | None = None) -> PublicationResult:
    """Drive the completed run through the F-17 authoritative-publication path.

    Returns a `PublicationResult`; raises `PublicationError` (fail closed) if any
    trusted gate refuses. A successful result carries
    `publication_state == ANCHORED`.
    """
    run_store = TrustedRunIdentityStore(Path(trust_state_root) / "runidentity")

    try:
        if inputs.exit_code != 0:
            raise RunNotPublishable(f"run {inputs.run_id} exited {inputs.exit_code}")
        # The existing create operation is idempotent for IDENTICAL identities.
        # Always cross-check it: an already-anchored ID cannot stand in for a
        # different task, tree, deployment or launch during retry/recovery.
        plan = RunPlan(
            task_id=inputs.task_id, run_id=inputs.run_id,
            repository_id=inputs.repository_id, head_sha=inputs.tree.head_sha,
            tree_identity=inputs.tree.tree_identity,
            bundle_path=str(bundle_dir), epoch=inputs.epoch)
        def authorize() -> None:
            record = create_trusted_run(
                run_store, plan, spec=inputs.spec, deployment=inputs.deployment,
                launched=inputs.launched)
            # Preserve the observed launch epoch, including on recovery.
            if record.publication_state is PublicationState.NOT_PUBLISHABLE:
                authorize_publishable(
                    run_store, record.identity,
                    CompletionEvidence(exit_code=inputs.exit_code, timed_out=False,
                                       cancelled=False, bundle_dir=bundle_dir))

        if scope is None:
            authorize()
        else:
            scope.commit(authorize)
            scope.check()
        # PUBLISHABLE -> anchor -> ANCHORED via the F-17 PUBLISHER SERVICE, through
        # the client seam. The canonical operator route never calls durable_publish
        # in-process; the response is NOT the authority — the persisted state is.
        # Even an ANCHORED retry goes through the Publisher's committed-watermark
        # reconciliation. A status file alone is not proof of a committed anchor.
        publisher_client.publish(inputs.run_id)
        # RPC can outlive ownership. An immutable historical anchor does not
        # grant the former controller authority to report task success.
        if scope is not None:
            scope.check()
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
