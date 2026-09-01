"""Canonical production composition root (F-33 Stage 2B.1, ADR-0032 §6).

`build_production_composition(config)` is the ONE canonical factory that assembles
the strong-governance production dependency graph. It owns **assembly/lifecycle
only** (ADR-0032 §6): it constructs the run store, engine, scheduler, trusted
execution seam, launcher and `GovernedPipeline`, and it reimplements no policy,
worker isolation, credential authority, RunIdentity, publication, or verifier
semantics.

Guarantees (this stage):
- The canonical implementer execution flows GovernedPipeline -> scheduler -> engine
  -> `TrustedExecutionRunner` -> `TrustedExecutionPort` -> the existing F-17
  `TrustedWindowsWorkerLauncher`. The legacy `ClaudeCodeCLIRunner` is NEVER the
  canonical implementer; the trusted runner is injected explicitly.
- The Worker interpreter is **deployment-derived**: it is the trusted runtime named
  by the F-17 deployment (`DeploymentLayout.runtime_executable`) and measured by the
  existing `trust.deployment.observe_runtime` qualification contract. It is never a
  PATH lookup, an operator flag, or an environment override.
- Startup **fails closed** (ADR-0032 §20) on: missing verifier; implementer==reviewer;
  invalid/absent deployment runtime; unavailable/invalid worker-launch config;
  placeholder/missing attribution; unsupported execution mode; invalid state/repo path.
- No operator CLI, no publication seam, no ANCHORED path are wired here (Stage 2B.2).

Deployment-source note (honest disclosure): F-17 does not persist a single manifest
bundling every launcher input. This factory consumes the EXISTING artifacts — the
`DeploymentLayout` path algebra, the persisted `config.json` (`ServiceConfig`,
`authorized_worker_sid`), and `trust.deployment.observe_runtime` — via
`trusted_deployment_from_layout`. No second trusted-runtime registry is created.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gnosis.contracts.director_brief import DirectorBrief
from gnosis.contracts.engineer_report import ReportStatus
from gnosis.director.execution import ExecutionMode, TrustedExecutionPort
from gnosis.director.pipeline import GovernedPipeline, PipelineOutcome
from gnosis.director.publication import (
    PublicationError,
    PublicationInputs,
    capture_publishable_bundle,
    observe_git_tree,
    publish_governed_run,
)
from gnosis.director.publisher_client import PipePublisherClient, PublisherClient
from gnosis.director.trusted_runner import TrustedExecutionRunner
from gnosis.kernel.convergence import ConvergencePolicy
from gnosis.kernel.engine import TaskEngine
from gnosis.kernel.policy import PolicyEngine
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.scheduler import HoldStore, TaskScheduler
from gnosis.kernel.verification import Verifier
from gnosis.kernel.worktree import WorktreeManager
from gnosis.provision.layout import DeploymentLayout
from gnosis.trust.deployment import TrustPlaneDeploymentIdentity, observe_runtime
from gnosis.trust.launch import AuthorityUnavailable
from gnosis.trust.publisher_service import ServiceConfig
from gnosis.trust.worker_launcher import TrustedWindowsWorkerLauncher, WorkerAccount

# ADR-0032 §17: known anonymous/unattributed placeholders the canonical production
# composition MUST reject. A run under either is invalid (attribution-hygiene gate).
_PLACEHOLDER_REVIEWER_IDS = frozenset({"claude-cli"})
_PLACEHOLDER_POLICY_ACTORS = frozenset({"agent://unattributed"})

# Only the deterministic, OS-real-qualified mode is selectable in Stage 2B.1.
_SUPPORTED_MODES = frozenset({ExecutionMode.DETERMINISTIC})


class CompositionError(Exception):
    """The canonical production composition refuses to be constructed (fail closed)."""


# --------------------------------------------------------------------------- #
# Typed configuration (ADR-0032 §12/§22): explicit trust classes, no dict[str, Any].
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TrustedDeploymentInputs:
    """TRUSTED / SERVICE-DERIVED (§22). The trusted execution plane, sourced from
    the F-17 deployment — never asserted by an operator CLI flag.

    - `runtime_executable`: the deployment's trusted interpreter (absolute; measured
      by `observe_runtime`). In production this is `DeploymentLayout.runtime_executable`.
    - `worker_account`: the authorized Worker identity; its `expected_sid` is the
      SERVICE-DERIVED `authorized_worker_sid` from the provisioned `config.json`.
    - `credential_blob_path` / `launch_root`: the DPAPI blob and worker-writable launch
      plane, from the `DeploymentLayout`.
    """

    runtime_executable: Path
    worker_account: WorkerAccount
    credential_blob_path: Path
    launch_root: Path


@dataclass(frozen=True)
class AttributionInputs:
    """Identity attribution (§17). MUST be explicit and non-placeholder."""

    reviewer_id: str
    policy_actor: str


@dataclass(frozen=True)
class OperatorInputs:
    """OPERATOR-PROVIDED (§22), validated: where work happens and state lives."""

    director_root: Path
    repo_path: Path


@dataclass(frozen=True)
class ProductionCompositionConfig:
    deployment: TrustedDeploymentInputs
    attribution: AttributionInputs
    operator: OperatorInputs
    verifier: Verifier
    review_runner: Any
    policy: PolicyEngine
    credential: str = "claude://default"
    execution_mode: ExecutionMode = ExecutionMode.DETERMINISTIC
    convergence_policy: ConvergencePolicy | None = None


def trusted_deployment_from_layout(layout: DeploymentLayout, worker_username: str,
                                   *, worker_integrity: str = "Medium"
                                   ) -> TrustedDeploymentInputs:
    """Derive the trusted deployment inputs from the EXISTING F-17 artifacts.

    Consumes the `DeploymentLayout` path algebra and the persisted `config.json`
    (`ServiceConfig`) for the authorized Worker SID. Creates no new registry and
    persists nothing. Fails closed if `config.json` is absent/invalid.
    """
    try:
        service_config = ServiceConfig.load(Path(layout.config_path))
    except AuthorityUnavailable as exc:
        raise CompositionError(
            f"deployment config {layout.config_path} unavailable/invalid: {exc}") from exc
    account = WorkerAccount(
        username=worker_username, domain=".",
        expected_sid=service_config.authorized_worker_sid,
        expected_integrity=worker_integrity)
    return TrustedDeploymentInputs(
        runtime_executable=Path(layout.runtime_executable),
        worker_account=account,
        credential_blob_path=Path(layout.secrets_blob),
        launch_root=Path(layout.work_base))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CompositionError(message)


def _validate_attribution(attr: AttributionInputs) -> None:
    reviewer = (attr.reviewer_id or "").strip()
    actor = (attr.policy_actor or "").strip()
    _require(bool(reviewer), "reviewer_id attribution is required (§17)")
    _require(bool(actor), "policy_actor attribution is required (§17)")
    _require(reviewer not in _PLACEHOLDER_REVIEWER_IDS,
             f"reviewer_id {reviewer!r} is a known placeholder; production "
             "attribution must be explicit (§17)")
    _require(actor not in _PLACEHOLDER_POLICY_ACTORS,
             f"policy_actor {actor!r} is a known placeholder; production "
             "attribution must be explicit (§17)")


def _bind_deployment_runtime(dep: TrustedDeploymentInputs) -> Path:
    """Return the absolute, deployment-derived, byte-measured trusted interpreter.

    The path is validated by the existing `trust.deployment.observe_runtime`
    qualification contract (it runs and measures the interpreter). A relative path,
    a PATH lookup or a non-interpreter fails closed here — there is no fallback.
    """
    exe = dep.runtime_executable
    _require(exe.is_absolute(),
             f"trusted runtime must be an absolute deployment path; got {exe!r}")
    try:
        identity = observe_runtime(exe)
    except Exception as exc:
        raise CompositionError(
            f"trusted runtime {exe} could not be measured/qualified: {exc}") from exc
    return Path(identity.executable_path)


def build_production_composition(config: ProductionCompositionConfig) -> GovernedPipeline:
    """Assemble the ONE canonical strong-governance production orchestration.

    Returns a `GovernedPipeline` (ADR-0032 §8 — the single production orchestration
    root; `DirectorOrchestrator` is never built here). Raises `CompositionError`
    (fail closed) on any invalid/insufficient input.
    """
    # --- fail-closed startup matrix (§20) --------------------------------------
    _require(config.verifier is not None, "a verifier is required (§16); no optional mode")
    _require(config.review_runner is not None, "a review runner is required")
    _require(config.execution_mode in _SUPPORTED_MODES,
             f"execution mode {config.execution_mode!r} is not selectable in Stage 2B.1")
    _validate_attribution(config.attribution)

    op = config.operator
    _require(op.repo_path.exists() and op.repo_path.is_dir(),
             f"repository path {op.repo_path} is not an existing directory")
    op.director_root.mkdir(parents=True, exist_ok=True)

    # --- trusted execution seam (deployment-derived runtime) -------------------
    dep = config.deployment
    python_executable = _bind_deployment_runtime(dep)
    # C2: the worker-launch infrastructure must be present (DPAPI credential blob
    # written by provisioning; a usable worker-writable launch plane).
    _require(dep.credential_blob_path.is_file(),
             f"worker credential blob {dep.credential_blob_path} is absent; "
             "worker-launch infrastructure is unavailable (fail closed)")
    try:
        dep.launch_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CompositionError(
            f"worker launch plane {dep.launch_root} is unusable: {exc}") from exc
    launcher = TrustedWindowsWorkerLauncher(
        account=dep.worker_account,
        credential_blob_path=dep.credential_blob_path,
        launch_root=dep.launch_root,
        runtime=python_executable)
    port = TrustedExecutionPort(launcher=launcher, python_executable=python_executable)
    trusted_runner = TrustedExecutionRunner(port, workspace=dep.launch_root)

    # --- engine/scheduler: the trusted runner is the EXPLICIT implementer ------
    run_store = RunStore(op.director_root / "runs")
    engine = TaskEngine(run_store=run_store, cli_runner=trusted_runner)
    # Defence in depth: never leave the legacy default in the canonical graph.
    _require(engine.cli_runner is trusted_runner,
             "canonical engine must run the trusted execution runner, not a legacy "
             "direct runner")
    scheduler = TaskScheduler(
        engine=engine, run_store=run_store,
        holds=HoldStore(op.director_root / "state" / "holds.jsonl"),
        credential=config.credential)

    # --- identity floor (§17): construction-time refusal, additive to pipeline -
    _require(config.review_runner is not trusted_runner,
             "the review runner is the same object as the implementer runner; a task "
             "cannot close on its own author's review (rule 10 / §17)")

    pipeline = GovernedPipeline(
        director_root=op.director_root, scheduler=scheduler, repo_path=op.repo_path,
        verifier=config.verifier, policy=config.policy,
        review_runner=config.review_runner,
        policy_actor=config.attribution.policy_actor,
        reviewer_id=config.attribution.reviewer_id,
        convergence_policy=config.convergence_policy,
        worktrees=WorktreeManager(op.repo_path, op.director_root / "worktrees"))
    return pipeline


# --------------------------------------------------------------------------- #
# Stage 2B.2 — operator-reachable composition with the authoritative publication
# seam. `build_production_composition` above still returns the canonical governed
# GovernedPipeline unchanged; this wrapper adds the publication lifecycle and the
# operator-success guarantee ON TOP, without a second orchestration engine.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PublicationCompositionInputs:
    """TRUSTED (§22): the authoritative-publication plane for operator runs.

    `deployment` is a measured V2 `TrustPlaneDeploymentIdentity` (binds the
    runtime tree); the stores live under the trust state root. None is operator
    input.
    """

    trust_state_root: Path
    evidence_root: Path
    deployment: TrustPlaneDeploymentIdentity
    repository_id: str
    pipe_name: str          # trusted F-17 Publisher service endpoint (not operator input)
    epoch: int = 0


@dataclass(frozen=True)
class OperatorOutcome:
    """The operator-visible result. `success` is TRUE only when governed work
    COMPLETED **and** the evidence reached ANCHORED (ADR-0032 §14)."""

    success: bool
    task_id: str
    run_id: str | None
    work_status: str
    publication_state: str | None
    reason: str


class ProductionComposition:
    """The single operator-reachable production object. Governed work still runs
    through the canonical `GovernedPipeline`; this adds the publication step and
    the composite operator-success invariant. It builds no second orchestrator."""

    def __init__(self, pipeline: GovernedPipeline,
                 runner: TrustedExecutionRunner,
                 publication: PublicationCompositionInputs,
                 repo_path: Path,
                 publisher_client: PublisherClient) -> None:
        self._pipeline = pipeline
        self._runner = runner
        self._publication = publication
        self._repo_path = repo_path
        self._publisher_client = publisher_client

    @property
    def pipeline(self) -> GovernedPipeline:
        return self._pipeline

    def run_brief(self, brief: DirectorBrief) -> OperatorOutcome:
        work: PipelineOutcome = self._pipeline.run_brief(brief)
        return self._finish(work)

    def _finish(self, work: PipelineOutcome) -> OperatorOutcome:
        # Governed work must succeed FIRST; a non-COMPLETED run is never published.
        if work.status is not ReportStatus.COMPLETED:
            return OperatorOutcome(
                success=False, task_id=work.task_id, run_id=None,
                work_status=work.status.value, publication_state=None,
                reason=f"governed work not COMPLETED ({work.reason_code}); "
                       "no publication attempted")
        launched = self._runner.last_launched
        spec = self._runner.last_spec
        run_id = self._runner.last_run_id
        if launched is None or spec is None or run_id is None:
            return OperatorOutcome(
                success=False, task_id=work.task_id, run_id=run_id,
                work_status=work.status.value, publication_state=None,
                reason="no trusted launch was recorded for the governed run")
        try:
            tree = observe_git_tree(self._repo_path)
            bundle_dir = self._publication.evidence_root / run_id
            capture_publishable_bundle(bundle_dir, tree)
            result = publish_governed_run(
                trust_state_root=self._publication.trust_state_root,
                bundle_dir=bundle_dir,
                inputs=PublicationInputs(
                    task_id=work.task_id, run_id=run_id,
                    repository_id=self._publication.repository_id,
                    epoch=self._publication.epoch, exit_code=0,
                    launched=launched, spec=spec,
                    deployment=self._publication.deployment, tree=tree),
                publisher_client=self._publisher_client)
        except PublicationError as exc:
            return OperatorOutcome(
                success=False, task_id=work.task_id, run_id=run_id,
                work_status=work.status.value, publication_state=None,
                reason=f"authoritative publication failed: {exc}")
        # operator success = work COMPLETED AND publication ANCHORED (§14).
        return OperatorOutcome(
            success=True, task_id=work.task_id, run_id=run_id,
            work_status=work.status.value,
            publication_state=result.publication_state.value, reason="anchored")


def build_production_deployment(config: ProductionCompositionConfig,
                                publication: PublicationCompositionInputs
                                ) -> ProductionComposition:
    """Assemble the operator-reachable production composition (governed work +
    authoritative publication). Reuses the canonical `build_production_composition`
    for the governed graph, then binds the publication seam on top."""
    pipeline = build_production_composition(config)
    runner = pipeline.scheduler.engine.cli_runner
    if not isinstance(runner, TrustedExecutionRunner):  # defence in depth
        raise CompositionError(
            "canonical implementer is not the trusted execution runner")
    # Cross-binding (§18): the interpreter the trusted execution runs MUST be the
    # same measured runtime bound into the publication deployment identity. One
    # digest scheme (trust.deployment); mismatch fails closed before any run.
    try:
        exec_runtime_digest = observe_runtime(
            config.deployment.runtime_executable).executable_digest
    except Exception as exc:
        raise CompositionError(
            f"could not measure the execution runtime for cross-binding: {exc}") from exc
    if exec_runtime_digest != publication.deployment.runtime.executable_digest:
        raise CompositionError(
            "execution runtime does not match the publication deployment runtime "
            "(digest mismatch); refusing to compose a run whose worker interpreter "
            "is not the anchored deployment's interpreter")
    # Canonical production publication goes through the F-17 Publisher SERVICE via
    # the pipe client (never in-process durable_publish on the operator route).
    publisher_client = PipePublisherClient(publication.pipe_name)
    return ProductionComposition(pipeline, runner, publication,
                                 config.operator.repo_path, publisher_client)
