"""The narrow trusted seam between ordinary orchestration and trusted state.

WHAT THIS IS NOT. It is not the engine moved into the trust plane. The Director
keeps its scheduling, its retries and its business logic where they are; what
lives here is the handful of decisions whose corruption would let an
unauthorized run be anchored:

    which worker actually ran        -> from the OS-observed token, only
    which sealed intent it ran from  -> from the launcher's seal, only
    which deployment produced it     -> from an observation, only
    whether it may be published      -> from a trusted gate, never the Worker

THE ORDER IS ENFORCED BY TYPES, NOT BY A COMMENT.

`create_trusted_run` cannot be called before the Worker exists, because it
requires a `LaunchedWorkerIdentity` - and that value is only ever constructed
after `verify_worker_token` has accepted the child's token. There is no code
path that invents an `owner_worker_sid` in advance, because there is no code
path that produces this argument in advance.

A NOTE THE REVIEW SHOULD SEE. Stage 5's launcher creates the process suspended,
verifies its token, contains it in the job and THEN resumes it, all inside
`launch()`. So when `launch()` returns, the Worker is already executing, and the
trusted identity is created immediately afterwards rather than strictly before
the first instruction. That window is closed by consequence rather than by
sequencing: until the identity exists, a publish request for it is answered
`unknown-run`, and until a trusted gate marks it PUBLISHABLE, a request is
refused. Making the launcher hand back a still-suspended process would reopen a
frozen Stage 5 interface, so the fail-closed consequence is the chosen answer
and is stated rather than hidden.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gnosis.trust.anchor import CURRENT_RUN_IDENTITY_SCHEMA, RunIdentity
from gnosis.trust.bundle_verify import verify_bundle
from gnosis.trust.deployment import TrustPlaneDeploymentIdentity
from gnosis.trust.launch import AuthorityUnavailable
from gnosis.trust.launch_spec import LaunchSpec
from gnosis.trust.run_identity import TrustedRunIdentityStore, TrustedRunRecord
from gnosis.trust.worker_launcher import LaunchedWorkerIdentity


class RunNotPublishable(AuthorityUnavailable):
    """A completion gate refused; the run stays NOT_PUBLISHABLE."""


@dataclass(frozen=True)
class RunPlan:
    """What the Director intends, BEFORE any worker exists.

    Deliberately missing from this structure: `owner_worker_sid`,
    `launch_spec_digest` and `deployment_digest`. They are not intentions, they
    are observations, and a plan that could carry them is a plan that could
    assert them.
    """

    task_id: str
    run_id: str
    repository_id: str
    head_sha: str
    tree_identity: str
    bundle_path: str
    epoch: int


def create_trusted_run(store: TrustedRunIdentityStore, plan: RunPlan, *,
                       spec: LaunchSpec,
                       deployment: TrustPlaneDeploymentIdentity,
                       launched: LaunchedWorkerIdentity) -> TrustedRunRecord:
    """Freeze the immutable identity of a run that has already been launched.

    The three authority-bearing fields are taken from the only places that can
    know them:

        owner_worker_sid    `launched.observed_sid` - read off the child's own
                            token by the launcher. Never a configured username.
        launch_spec_digest  `launched.launch_spec_digest` - the seal the
                            launcher computed over the LaunchSpec it executed.
        deployment_digest   `deployment.digest()` - an observation of what is
                            actually installed.

    A deployment identity that does not bind the runtime tree is refused: an
    anchor whose deployment binding leaves the interpreter's library
    unmeasured does not carry the guarantee Stage 6 requires.
    """
    if not deployment.binds_runtime_tree:
        raise AuthorityUnavailable(
            "this deployment identity does not bind the runtime tree, so a run "
            "created under it could not be anchored to a fully measured "
            "deployment; observe a V2 deployment identity first")
    if spec.run_id != plan.run_id:
        # The SEAL names the run it was sealed for (Stage 5 put `run_id` in the
        # LaunchSpec for exactly this binding). If the plan and the seal name
        # different runs, one of them describes something else and neither may
        # be trusted to identify what just executed.
        raise AuthorityUnavailable(
            f"the plan is for run {plan.run_id!r} but the executed LaunchSpec was "
            f"sealed for {spec.run_id!r}; refusing to bind them together")
    identity = RunIdentity(
        task_id=plan.task_id,
        run_id=plan.run_id,
        repository_id=plan.repository_id,
        head_sha=plan.head_sha,
        tree_identity=plan.tree_identity,
        bundle_path=plan.bundle_path,
        owner_worker_sid=launched.observed_sid,
        deployment_digest=deployment.digest(),
        epoch=plan.epoch,
        schema=CURRENT_RUN_IDENTITY_SCHEMA,
        launch_spec_digest=launched.launch_spec_digest,
    )
    return store.create(identity)


@dataclass(frozen=True)
class CompletionEvidence:
    """What the trusted gate is shown about a finished run."""

    exit_code: int
    timed_out: bool
    cancelled: bool
    bundle_dir: Path


def authorize_publishable(store: TrustedRunIdentityStore,
                          identity: RunIdentity,
                          evidence: CompletionEvidence) -> TrustedRunRecord:
    """The ONLY path from NOT_PUBLISHABLE to PUBLISHABLE.

    Worker completion is not authorization. A run becomes publishable when a
    TRUSTED party has looked at the evidence and accepted it, which is why this
    lives here and why the Worker's IPC grammar has no verb that reaches it.

    The gates, all fail-closed:

        the worker exited cleanly, was not cancelled and did not time out;
        the bundle lies where the trusted identity says it does;
        the bundle verifies byte for byte against its own manifest.

    The bundle digest is NOT compared to a worker-supplied expectation here -
    there is none. Publication re-derives it and binds it into the anchor.
    """
    if evidence.timed_out:
        raise RunNotPublishable(f"run {identity.run_id} timed out")
    if evidence.cancelled:
        raise RunNotPublishable(f"run {identity.run_id} was cancelled")
    if evidence.exit_code != 0:
        raise RunNotPublishable(
            f"run {identity.run_id} exited {evidence.exit_code}")
    if Path(identity.bundle_path) != evidence.bundle_dir:
        raise RunNotPublishable(
            f"run {identity.run_id} produced a bundle at {evidence.bundle_dir}, "
            f"but its trusted identity names {identity.bundle_path}")
    result = verify_bundle(evidence.bundle_dir)
    if not result.verified:
        raise RunNotPublishable(
            f"run {identity.run_id} has an unverifiable bundle: "
            f"{'; '.join(result.problems)}")
    return store.mark_publishable(identity.run_id, identity.digest())
