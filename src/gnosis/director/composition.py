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

import re
import shlex
import subprocess
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from gnosis.contracts.director_brief import DirectorBrief
from gnosis.contracts.engineer_report import ReportStatus
from gnosis.director.checkpoint import (
    CapturedProof,
    CheckpointError,
    CheckpointSession,
    PipelineCheckpointStore,
)
from gnosis.director.execution import (
    CodexWorkerConfiguration,
    ExecutionMode,
    TrustedExecutionPort,
)
from gnosis.director.pipeline import GovernedPipeline, PipelineOutcome
from gnosis.director.proof import capture_task_proof
from gnosis.director.publication import (
    GitTreeEvidence,
    PublicationError,
    PublicationInputs,
    publish_governed_run,
)
from gnosis.director.publication_checkpoint import PublicationCheckpointStore
from gnosis.director.publisher_client import PipePublisherClient, PublisherClient
from gnosis.director.trusted_runner import TrustedExecutionRunner
from gnosis.kernel.budget import BudgetLedger
from gnosis.kernel.canonical import hash_canonical
from gnosis.kernel.convergence import ConvergencePolicy
from gnosis.kernel.engine import TaskEngine
from gnosis.kernel.execution_scope import ExecutionScope
from gnosis.kernel.file_lock import FileLock
from gnosis.kernel.integration import IntegrationOutcome, PreparedIntegration, WorkIntegrator
from gnosis.kernel.policy import PolicyEngine
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.scheduler import HoldStore, TaskScheduler
from gnosis.kernel.subject import observe_subject
from gnosis.kernel.verification import CommandVerifier, Verifier
from gnosis.kernel.worktree import WorktreeError, WorktreeManager
from gnosis.provision.layout import DeploymentLayout
from gnosis.trust.bundle_verify import verify_bundle
from gnosis.trust.deployment import (
    FileTreeManifest,
    TrustPlaneDeploymentIdentity,
    observe_runtime,
    observe_runtime_tree,
)
from gnosis.trust.launch import AuthorityUnavailable
from gnosis.trust.launch_spec import LaunchSpec
from gnosis.trust.publisher_service import ServiceConfig
from gnosis.trust.worker_launcher import TrustedWindowsWorkerLauncher, WorkerAccount

# ADR-0032 §17: known anonymous/unattributed placeholders the canonical production
# composition MUST reject. A run under either is invalid (attribution-hygiene gate).
_PLACEHOLDER_REVIEWER_IDS = frozenset({"claude-cli"})
_PLACEHOLDER_POLICY_ACTORS = frozenset({"agent://unattributed"})

# Provider mode additionally requires a native executable bound into the measured
# runtime and cross-bound to the Publisher's expected deployment identity.
_SUPPORTED_MODES = frozenset({ExecutionMode.DETERMINISTIC, ExecutionMode.PROVIDER_BACKED})


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
    expected_deployment_digest: str | None = None


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
    provider_runtime_tree: FileTreeManifest | None = None
    integration_target: str | None = None


# --------------------------------------------------------------------------- #
# Canonical operator-configuration writer (F-33 Stage 2C-B1-R3E.1).
# The ONE production surface that constructs the operator configuration the deployed
# `gnosis.director.cli.build_operator_composition` consumes. Production-equivalent
# qualification (the B1 OS-real driver) and any future production entrypoint import
# THIS writer — no second, independently-maintained schema. A future production
# caller can build the config using only `gnosis.director.composition` (no scripts/).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OperatorConfigInputs:
    """TRUSTED structured inputs for the operator configuration. Every value is
    deployment-authority / trusted-config sourced — never operator work/brief input.
    `release_id` is carried ONLY from the authoritative `DeploymentLayout.release_id`
    (no fallback, hardcode, environment, cwd, or checkout lookup)."""

    layout: DeploymentLayout
    worker_username: str
    trust_root: str
    reviewer_binary: str
    reviewer_id: str
    policy_actor: str
    director_root: str
    repo_path: str
    trust_state_root: str
    evidence_root: str
    repository_id: str
    service_name: str
    pipe_name: str
    verifier_name: str
    verifier_command: tuple[str, ...]
    reviewer_provider: str = "claude"
    execution_mode: ExecutionMode = ExecutionMode.DETERMINISTIC
    integration_target: str | None = None


# The mandatory production config contract (sections consumed by the reader
# `gnosis.director.cli`). Kept here so the writer and any drift test share one source.
OPERATOR_CONFIG_SECTIONS = ("deployment", "attribution", "operator", "publication",
                            "verifier", "reviewer")


def build_operator_config(inputs: OperatorConfigInputs) -> dict[str, Any]:
    """THE canonical production writer of the operator configuration. It SERIALIZES
    trusted values (it establishes no trust itself); the deployment section carries
    the authoritative `release_id` verbatim from `inputs.layout.release_id`, so the
    deployed operator reconstructs the EXACT release layout it was staged under."""
    lay = inputs.layout
    if inputs.reviewer_provider not in {"claude", "codex"}:
        raise CompositionError("unsupported trusted reviewer provider")
    reviewer = {"binary": inputs.reviewer_binary}
    if inputs.reviewer_provider != "claude":
        reviewer["provider"] = inputs.reviewer_provider
    result: dict[str, Any] = {
        "deployment": {
            "code_base": lay.code_base, "state_base": lay.state_base,
            "work_base": lay.work_base, "release_id": lay.release_id,
            "worker_username": inputs.worker_username,
            "trust_root": inputs.trust_root},
        "attribution": {"reviewer_id": inputs.reviewer_id,
                        "policy_actor": inputs.policy_actor},
        "operator": {"director_root": inputs.director_root,
                     "repo_path": inputs.repo_path},
        "publication": {
            "trust_state_root": inputs.trust_state_root,
            "evidence_root": inputs.evidence_root,
            "repository_id": inputs.repository_id,
            "service_name": inputs.service_name, "pipe_name": inputs.pipe_name},
        "verifier": {"name": inputs.verifier_name,
                     "command": list(inputs.verifier_command)},
        "reviewer": reviewer,
    }
    if inputs.execution_mode not in _SUPPORTED_MODES:
        raise CompositionError("unsupported trusted execution mode")
    if inputs.execution_mode is ExecutionMode.PROVIDER_BACKED:
        result["execution"] = {"mode": "provider_backed", "provider": "codex"}
    if inputs.integration_target is not None:
        validate_integration_target(inputs.integration_target)
        result["integration"] = {"target_branch": inputs.integration_target, "authorized": True}
    return result


def validate_integration_target(target: str) -> None:
    if (not isinstance(target, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", target) is None
            or ".." in target or "//" in target
            or any(part.startswith(".") or part.endswith((".", ".lock")) for part in target.split("/"))
            or target.endswith("/")):
        raise CompositionError("invalid trusted integration target branch")


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
        launch_root=Path(layout.work_base),
        expected_deployment_digest=service_config.expected_deployment_digest)


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


def bind_codex_runtime(python_executable: Path,
                       expected_tree: FileTreeManifest | None) -> CodexWorkerConfiguration:
    """Select only the native Codex inside the existing measured runtime tree."""
    _require(expected_tree is not None, "provider runtime tree evidence is required")
    assert expected_tree is not None
    try:
        current = observe_runtime_tree(python_executable.parent)
    except Exception as exc:
        raise CompositionError("provider runtime tree could not be observed") from exc
    _require(current.digest() == expected_tree.digest(), "provider runtime tree drifted")
    from gnosis.provision.codex_package import CodexPackageError, codex_package_entrypoint

    relpath = "providers/codex/bin/codex.exe"
    matches = [entry for entry in expected_tree.files if entry.path == relpath]
    _require(len(matches) == 1, "measured runtime must contain exactly one native Codex")
    try:
        executable = codex_package_entrypoint(python_executable.parent / "providers" / "codex")
    except CodexPackageError as exc:
        raise CompositionError(f"deployed native Codex package is invalid: {exc}") from exc
    from gnosis.provision.git_package import GitPackageError, git_package_entrypoint

    runtime_root = python_executable.parent
    try:
        git = git_package_entrypoint(runtime_root / "toolchains" / "git")
    except GitPackageError as exc:
        raise CompositionError(f"deployed Git package is invalid: {exc}") from exc
    bootstrap_root = runtime_root / "worker-bootstrap"
    required_bootstrap = (
        "gnosis/__init__.py", "gnosis/kernel/__init__.py", "gnosis/kernel/canonical.py",
        "gnosis/kernel/atomic_io.py", "gnosis/trust/__init__.py", "gnosis/trust/launch.py",
        "gnosis/trust/launch_spec.py", "gnosis/trust/bootstrap.py",
    )
    _require(all((bootstrap_root / relative).is_file() for relative in required_bootstrap),
             "measured runtime lacks the Worker bootstrap closure")
    provider = CodexWorkerConfiguration(
        executable, matches[0].digest, trusted_path=(runtime_root, git.parent),
        bootstrap=bootstrap_root / "gnosis" / "trust" / "bootstrap.py")
    try:
        provider.verify()
    except Exception as exc:
        raise CompositionError("deployed native Codex does not match its runtime record") from exc
    return provider


def build_production_composition(config: ProductionCompositionConfig, *,
                                 checkpoint_store: PipelineCheckpointStore | None = None,
                                 checkpoint_context: str | None = None,
                                 scope: ExecutionScope | None = None) -> GovernedPipeline:
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
    if config.integration_target is not None:
        validate_integration_target(config.integration_target)

    op = config.operator
    _require(op.repo_path.exists() and op.repo_path.is_dir(),
             f"repository path {op.repo_path} is not an existing directory")
    op.director_root.mkdir(parents=True, exist_ok=True)

    # --- trusted execution seam (deployment-derived runtime) -------------------
    dep = config.deployment
    python_executable = _bind_deployment_runtime(dep)
    codex = None
    if config.execution_mode is ExecutionMode.PROVIDER_BACKED:
        codex = bind_codex_runtime(python_executable, config.provider_runtime_tree)
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
        runtime=python_executable,
        bootstrap=codex.bootstrap if codex is not None else None,
        director_env=dict(codex.environment) if codex is not None else None,
        environment_allowlist=frozenset({"PYTHONUTF8", "PYTHONIOENCODING", "PATH"}))
    port = TrustedExecutionPort(launcher=launcher, python_executable=python_executable,
                                codex=codex)
    trusted_runner = TrustedExecutionRunner(port, workspace=dep.launch_root,
                                             output_workspace=dep.launch_root / "outputs",
                                            mode=config.execution_mode)

    # Every candidate check crosses the same identity boundary as implementation.
    # Never reuse an operator-supplied local executor in the production graph.
    from gnosis.director.check_executor import WorkerCheckExecutor

    _require(isinstance(config.verifier, CommandVerifier),
             "production verification requires a reproducible command verifier")
    assert isinstance(config.verifier, CommandVerifier)
    verification_executor = WorkerCheckExecutor(
        launcher=launcher, runtime=python_executable,
        output_root=dep.launch_root / "verification-output",
        evidence_root=op.director_root / "verification-evidence",
        guard=scope.check if scope is not None else lambda: None,
        is_cancelled=scope.cancellation.is_cancelled if scope is not None else lambda: False)
    verification_executor.recover_outputs()
    verifier = CommandVerifier(config.verifier.name, config.verifier.command,
                               config.verifier.timeout_s, config.verifier.excerpt_chars,
                               executor=verification_executor)

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

    review_runner = config.review_runner
    if config.execution_mode is ExecutionMode.PROVIDER_BACKED:
        from gnosis.runner.claude_cli_runner import ClaudeCodeCLIRunner

        if isinstance(review_runner, ClaudeCodeCLIRunner):
            from gnosis.director.worker_review import WorkerClaudeReviewer

            relative = "providers/claude/claude.exe"
            binary = python_executable.parent / relative
            tree = config.provider_runtime_tree
            _require(tree is not None and sum(entry.path == relative for entry in tree.files) == 1,
                     "Claude reviewer must belong to the measured provider runtime")
            _require(Path(review_runner.binary).resolve() == binary.resolve() and binary.is_file(),
                     "Claude reviewer path differs from measured runtime")
            review_runner = WorkerClaudeReviewer(binary=binary, launcher=launcher,
                output_root=dep.launch_root / "review-output",
                guard=scope.check if scope is not None else lambda: None)

    def prepare_workspace(target: Path) -> None:
        # Creation under the Worker token gives its sandbox authority over only
        # this fresh task directory. No privileged ownership transfer or change
        # to the protected repository, provenance, runtime or state is needed.
        result = verification_executor.execute(
            (str(python_executable), "-I", "-B", "-c",
             "from pathlib import Path; import sys; Path(sys.argv[1]).mkdir()",
             str(target)), cwd=target.parent, timeout_s=30)
        if result.returncode != 0:
            raise WorktreeError("Worker workspace preparation failed: " + result.stderr)
        # Git metadata is Director-owned and Worker-readable. Trust only this
        # exact kernel-assigned worktree in the Worker's own Git configuration;
        # never trust '*' or grant write access to source repository metadata.
        git = python_executable.parent / "toolchains/git/cmd/git.exe"
        trusted = verification_executor.execute(
            (str(git), "config", "--global", "--add", "safe.directory", str(target)),
            cwd=target.parent, timeout_s=30)
        if trusted.returncode != 0:
            raise WorktreeError("Worker Git workspace registration failed: " + trusted.stderr)
        # The root belongs to Worker while its Git metadata belongs to Director.
        # Both identities need this exact assignment registered. Run this small
        # configuration operation from the protected source, never task code.
        director_trust = subprocess.run(
            [str(git), "config", "--global", "--add", "safe.directory", str(target)],
            cwd=op.repo_path, capture_output=True, text=True, timeout=30, check=False)
        if director_trust.returncode != 0:
            raise WorktreeError("Director Git workspace registration failed: "
                                + director_trust.stderr)

    def populate_workspace(target: Path) -> None:
        # checkout-index without --index reads the protected index and creates
        # files as Worker. It does not need write access to source Git metadata.
        git = python_executable.parent / "toolchains/git/cmd/git.exe"
        result = verification_executor.execute(
            (str(git), "checkout-index", "--all"), cwd=target, timeout_s=120)
        if result.returncode != 0:
            raise WorktreeError("Worker workspace checkout failed: " + result.stderr)

    pipeline = GovernedPipeline(
        director_root=op.director_root, scheduler=scheduler, repo_path=op.repo_path,
        verifier=verifier, policy=config.policy,
        review_runner=review_runner,
        fix_runner=trusted_runner,
        policy_actor=config.attribution.policy_actor,
        reviewer_id=config.attribution.reviewer_id,
        convergence_policy=config.convergence_policy,
        bind_review_subject=True,
        checkpoint_store=checkpoint_store, checkpoint_context=checkpoint_context,
        scope=scope,
        commit_before_review=config.integration_target is not None,
        worktrees=WorktreeManager(
            op.repo_path,
            dep.launch_root / "worktrees" / hash_canonical({
                "director_root": str(op.director_root.resolve()).casefold()}),
            provenance_root=op.director_root / "worktrees",
            prepare_directory=(prepare_workspace
                               if config.execution_mode is ExecutionMode.PROVIDER_BACKED else None),
            populate_worktree=(populate_workspace
                               if config.execution_mode is ExecutionMode.PROVIDER_BACKED else None)))
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


# R4A.1: worker-launch pipeline-error reasons whose preserved `problems_encountered`
# line is a SAFE launcher attribution — the failing WinAPI call/stage + native winerr
# from the F-17 `WorkerLaunchFailed` message — and NEVER reviewer/provider/evidence
# content. `WorkerIdentityMismatch` is a `WorkerLaunchFailed` subclass raised on the
# same launch path; the pipeline records the reason as `pipeline_error:<type name>`.
_WORKER_LAUNCH_REASONS = frozenset({
    "pipeline_error:WorkerLaunchFailed",
    "pipeline_error:WorkerIdentityMismatch",
})
# Bound the exposed diagnostic so it can never become an unbounded reflection channel.
# Every legitimate launcher message is short: the winerr forms (`"<Api> failed (winerr
# N)"`) are ~55 chars, and the longest legitimate case — a `WorkerIdentityMismatch`
# listing the full dangerous-privilege set — stays well under this ceiling. The cap is
# defense-in-depth against an anomalous/injected over-long line; an over-cap line is
# rejected (returns None) rather than truncated, so a native winerr is never silently
# dropped (§8).
_WORKER_LAUNCH_DIAG_MAX = 512


def _worker_launch_diagnostic(work: PipelineOutcome) -> str | None:
    """Return ONLY the authoritative worker-launch attribution line, else None.

    ACTIVATION is bound to the typed pipeline-error reason — not the status, not a
    `pipeline_error:` prefix, not a substring of any problem text: the field is
    populated exclusively when the governed failure reason is a worker-launch
    exception class (`_WORKER_LAUNCH_REASONS`). SELECTION then takes the single
    `problems_encountered` line the pipeline recorded for that exception
    (`f"{type(exc).__name__}: {exc}"`, which starts with the reason's type name) —
    never the whole list, never a convergence finding, evidence-failure message, or
    reviewer/provider string. The launcher messages carry only the failing WinAPI
    call and native winerr (audited SAFE); this forwards that one line unchanged
    (bounded), reconstructing nothing.
    """
    if work.reason_code not in _WORKER_LAUNCH_REASONS:
        return None
    prefix = work.reason_code.split(":", 1)[1] + ": "   # e.g. "WorkerLaunchFailed: "
    for line in work.report.problems_encountered:
        if line.startswith(prefix):
            # Bounded: a real launcher line is short (API + "failed (winerr N)"). An
            # over-long line is anomalous; prefer an UNAVAILABLE diagnostic over a
            # truncation that could silently drop the trailing native winerr (§8).
            return line if len(line) <= _WORKER_LAUNCH_DIAG_MAX else None
    return None


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
    # R4A.1: the SINGLE authoritative worker-launch attribution line (failing WinAPI
    # call/stage + native winerr from the F-17 `WorkerLaunchFailed`), and ONLY that —
    # populated exclusively for the worker-launch pipeline-error class, never the
    # general `problems_encountered` channel (which can carry reviewer, provider, or
    # evidence content). None for success and for every other (reviewer/governance/
    # evidence) failure. Evidence only: it never affects success/work_status/exit/
    # verifier/reviewer/publication/retry.
    worker_launch_diagnostic: str | None = None


class ProductionComposition:
    """The single operator-reachable production object. Governed work still runs
    through the canonical `GovernedPipeline`; this adds the publication step and
    the composite operator-success invariant. It builds no second orchestrator."""

    def __init__(self, pipeline: GovernedPipeline,
                 runner: TrustedExecutionRunner,
                 publication: PublicationCompositionInputs,
                 repo_path: Path,
                 publisher_client: PublisherClient,
                 scope: ExecutionScope | None = None,
                 integration_target: str | None = None,
                 verification_workspace: Path | None = None) -> None:
        self._pipeline = pipeline
        self._runner = runner
        self._publication = publication
        self._repo_path = repo_path
        self._publisher_client = publisher_client
        self.scope = scope
        self.integration_target = integration_target
        self.verification_workspace = verification_workspace

    def _guard(self) -> None:
        if self.scope is not None:
            self.scope.check()

    @cached_property
    def _checkpoints(self) -> PublicationCheckpointStore:
        # A failed-work report does not need publication infrastructure.
        # Construct recovery storage only when that phase is actually reached.
        return PublicationCheckpointStore(
            self._publication.trust_state_root, self._publication.evidence_root, self.scope)

    @property
    def pipeline(self) -> GovernedPipeline:
        return self._pipeline

    def run_brief(self, brief: DirectorBrief) -> OperatorOutcome:
        # Serialize one brief across its complete execution/publication path.
        # A restart releases the OS lock; a concurrent caller cannot duplicate it.
        self._guard()
        operation = self._checkpoints.path_for(brief.brief_id).with_suffix(".operation.lock")
        with FileLock(operation):
            self._guard()
            return self._run_brief(brief)

    def _run_brief(self, brief: DirectorBrief) -> OperatorOutcome:
        self._runner.clear_launch()
        try:
            publication_epoch = self._publication.epoch
            claimed_launch = False
            phases = getattr(self._pipeline, "checkpoints", None)
            if isinstance(phases, PipelineCheckpointStore):
                phase = phases.load(brief.brief_id)
                if phase is not None and (phase.brief != brief
                        or phase.context_digest != self._pipeline.checkpoint_context):
                    raise CheckpointError("brief or deployment configuration changed since checkpoint")
                if self.scope is not None and phase is not None and phase.trusted_attempt is not None:
                    if phase.trusted_attempt.epoch is None:
                        raise CheckpointError("unclaimed launch cannot be adopted by a claimed operation")
                    publication_epoch = phase.trusted_attempt.epoch
                    claimed_launch = True
            pending = self._checkpoints.load(
                brief, deployment=self._publication.deployment,
                repository_id=self._publication.repository_id, epoch=publication_epoch,
                source_for=self._pipeline._exec_root, verifier=self._pipeline.verifier)
            if pending is not None:
                if self.scope is not None and not claimed_launch:
                    raise CheckpointError("claimed recovery requires a protected launch epoch")
                self._guard()
                result = publish_governed_run(
                    trust_state_root=self._publication.trust_state_root,
                    bundle_dir=self._publication.evidence_root / pending.run_id,
                    inputs=pending, publisher_client=self._publisher_client,
                    scope=self.scope)
                self._guard()
                landing = self._finish_integration(brief, pending.task_id, pending.run_id)
                if landing is not None:
                    return landing
                return OperatorOutcome(True, pending.task_id, pending.run_id,
                                       ReportStatus.COMPLETED.value,
                                       result.publication_state.value, "anchored after recovery")
        except (PublicationError, CheckpointError, WorktreeError, OSError, ValueError) as exc:
            return OperatorOutcome(False, "", None, ReportStatus.BLOCKED.value, None,
                                   f"publication recovery refused: {exc}")
        work: PipelineOutcome = self._pipeline.run_brief(brief)
        return self._finish(work, brief)

    def _finish(self, work: PipelineOutcome, brief: DirectorBrief | None = None) -> OperatorOutcome:
        self._guard()
        # Governed work must succeed FIRST; a non-COMPLETED run is never published.
        if work.status is not ReportStatus.COMPLETED:
            return OperatorOutcome(
                success=False, task_id=work.task_id, run_id=None,
                work_status=work.status.value, publication_state=None,
                reason=f"governed work not COMPLETED ({work.reason_code}); "
                       "no publication attempted",
                worker_launch_diagnostic=_worker_launch_diagnostic(work))
        launched = self._runner.last_launched
        spec = self._runner.last_spec
        run_id = self._runner.last_run_id
        phases = getattr(self._pipeline, "checkpoints", None)
        if launched is None and isinstance(phases, PipelineCheckpointStore) and brief is not None:
            try:
                phase = phases.load(brief.brief_id)
                if (phase is None or phase.task_id != work.task_id or phase.brief != brief
                        or phase.context_digest != self._pipeline.checkpoint_context
                        or phase.trusted_attempt is None
                        or phase.trusted_attempt.spec.run_id != work.report.run_id):
                    raise CheckpointError("completed work has no matching protected launch")
                spec, launched = phase.trusted_attempt.spec, phase.trusted_attempt.launched
                run_id = spec.run_id
            except CheckpointError as exc:
                return OperatorOutcome(False, work.task_id, None, work.status.value, None,
                                       f"launch recovery refused: {exc}")
        if launched is None or spec is None or run_id is None:
            return OperatorOutcome(
                success=False, task_id=work.task_id, run_id=run_id,
                work_status=work.status.value, publication_state=None,
                reason="no trusted launch was recorded for the governed run")
        try:
            if brief is None:
                raise PublicationError("the completed work has no attributable brief")
            publication_epoch = self._publication.epoch
            if self.scope is not None:
                if not isinstance(phases, PipelineCheckpointStore):
                    raise CheckpointError("claimed publication requires protected phase evidence")
                phase = phases.load(brief.brief_id)
                if (phase is None or phase.trusted_attempt is None
                        or phase.trusted_attempt.spec.run_id != run_id
                        or phase.trusted_attempt.epoch is None):
                    raise CheckpointError("claimed publication has no recorded launch epoch")
                publication_epoch = phase.trusted_attempt.epoch
            bundle_dir = self._publication.evidence_root / run_id
            tree = self._capture_proof(work, brief, run_id, spec)
            inputs = PublicationInputs(
                task_id=work.task_id, run_id=run_id,
                repository_id=self._publication.repository_id,
                epoch=publication_epoch, exit_code=0,
                launched=launched, spec=spec,
                deployment=self._publication.deployment, tree=tree)
            self._guard()
            self._checkpoints.save(brief, inputs)
            self._guard()
            result = publish_governed_run(
                trust_state_root=self._publication.trust_state_root,
                bundle_dir=bundle_dir,
                inputs=inputs,
                publisher_client=self._publisher_client, scope=self.scope)
        except (PublicationError, CheckpointError, WorktreeError, OSError, ValueError) as exc:
            return OperatorOutcome(
                success=False, task_id=work.task_id, run_id=run_id,
                work_status=work.status.value, publication_state=None,
                reason=f"authoritative publication failed: {exc}")
        # operator success = work COMPLETED AND publication ANCHORED (§14).
        self._guard()
        assert brief is not None
        landing = self._finish_integration(brief, work.task_id, run_id)
        if landing is not None:
            return landing
        return OperatorOutcome(
            success=True, task_id=work.task_id, run_id=run_id,
            work_status=work.status.value,
            publication_state=result.publication_state.value, reason="anchored")

    def _finish_integration(self, brief: DirectorBrief, task_id: str,
                            run_id: str) -> OperatorOutcome | None:
        if self.integration_target is None:
            return None
        self._guard()
        phases = self._pipeline.checkpoints
        try:
            if phases is None or self._pipeline.worktrees is None:
                raise CheckpointError("integration requires durable isolated task state")
            record = phases.load(brief.brief_id)
            if (record is None or record.task_id != task_id or record.brief != brief
                    or record.proof is None or record.proof.run_id != run_id
                    or record.convergence is None or record.subject is None):
                raise CheckpointError("integration has no matching published task proof")
            session = CheckpointSession(phases, record)

            def prepared(receipt: PreparedIntegration) -> None:
                self._guard()
                session.save(prepared_integration=receipt)

            integrator = WorkIntegrator(self._repo_path, self._pipeline.worktrees,
                self._pipeline.verifier, target_branch=self.integration_target,
                integration_root=self._pipeline.inbox.layout.root / "integration",
                staging_root=(self.verification_workspace / "integration"
                              if self.verification_workspace is not None else None),
                policy=self._pipeline.policy, approvals=self._pipeline.approvals,
                policy_actor=self._pipeline.policy_actor, scope=self.scope,
                on_prepared=prepared, convergence_policy=self._pipeline.convergence_policy)
            if record.prepared_integration is not None:
                result = integrator.resume_prepared(record.prepared_integration)
            else:
                if record.integration_attempts >= 3:
                    raise CheckpointError("integration attempt budget exhausted")
                session.save(integration_attempts=record.integration_attempts + 1)
                ledger = BudgetLedger(self._pipeline.budget, prior_launches=record.launches,
                                      prior_elapsed_s=record.elapsed_s)

                def save_budget() -> None:
                    self._guard()
                    session.save(launches=ledger.launches, elapsed_s=ledger.elapsed_s)
                    self._pipeline.budget_store.record(brief.brief_id, ledger)

                try:
                    result = integrator.integrate(task_id, record.convergence,
                        re_reviewer=self._pipeline._rereviewer_for(task_id, ledger, save_budget,
                            integration_attempt=session.current.integration_attempts))
                finally:
                    save_budget()
            self._guard()
            session.save(integration=result)
            landed = result.integrated
            if result.outcome is IntegrationOutcome.NOTHING_TO_INTEGRATE:
                landed = observe_subject(self._repo_path) == record.subject
            if not landed:
                return OperatorOutcome(False, task_id, run_id, ReportStatus.COMPLETED.value,
                                       "ANCHORED", f"integration refused: {result.reason}")
            return OperatorOutcome(True, task_id, run_id, ReportStatus.COMPLETED.value,
                                   "ANCHORED", "anchored and integrated")
        except (CheckpointError, WorktreeError, OSError, ValueError) as exc:
            return OperatorOutcome(False, task_id, run_id, ReportStatus.COMPLETED.value,
                                   "ANCHORED", f"integration failed: {exc}")

    def _capture_proof(self, work: PipelineOutcome, brief: DirectorBrief,
                       run_id: str, spec: LaunchSpec) -> GitTreeEvidence:
        self._guard()
        final = self._publication.evidence_root / run_id

        def capture(target: Path) -> GitTreeEvidence:
            return capture_task_proof(
                bundle_dir=target, source=self._pipeline._exec_root(work.task_id),
                brief=brief, work=work, run_id=run_id, spec=spec,
                verifier=self._pipeline.verifier,
                snapshot_root=(self.verification_workspace / "proof"
                               if self.verification_workspace is not None else None),
                convergence_dir=self._pipeline.inbox.layout.outbox / f"{work.task_id}-convergence")

        phases = getattr(self._pipeline, "checkpoints", None)
        if not isinstance(phases, PipelineCheckpointStore):
            return capture(final)
        phase = phases.load(brief.brief_id)
        if (phase is None or phase.task_id != work.task_id or phase.brief != brief
                or phase.trusted_attempt is None or phase.trusted_attempt.spec != spec
                or phase.context_digest != self._pipeline.checkpoint_context
                or phase.convergence != work.convergence):
            raise CheckpointError("proof does not match protected phase evidence")
        if phase.proof is None:
            if final.exists():
                raise PublicationError("uncheckpointed final proof exists; refusing replacement")
            if phase.proof_attempts >= 3:
                raise PublicationError("proof capture attempt budget exhausted; evidence retained")
            phase = phases.update(phase, proof_attempts=phase.proof_attempts + 1)
            stage = final.parent / f".{run_id}-proof-{phase.proof_attempts}"
            tree = capture(stage)
            self._guard()
            verified = verify_bundle(stage)
            if not verified.verified or verified.bundle_digest is None:
                raise PublicationError("captured proof has no verified digest")
            # Persist the receipt BEFORE moving the sealed directory. A restart
            # can identify either side of that rename by its protected digest.
            phase = phases.update(phase, proof=CapturedProof(
                run_id, phase.proof_attempts, verified.bundle_digest, tree))
        receipt = phase.proof
        assert receipt is not None
        stage = final.parent / f".{run_id}-proof-{receipt.attempt}"
        candidate = final if final.exists() else stage
        root = self._publication.evidence_root.resolve()
        if candidate.resolve().parent != root or final.resolve().parent != root:
            raise PublicationError("proof recovery path escaped its evidence root")
        if not verify_bundle(candidate, receipt.bundle_digest).verified:
            raise PublicationError("captured proof digest changed before publication")
        if candidate == stage:
            self._guard()
            stage.rename(final)
        elif stage.exists():
            raise PublicationError("proof recovery has ambiguous staging and final copies")
        if not verify_bundle(final, receipt.bundle_digest).verified:
            raise PublicationError("final proof differs from protected capture receipt")
        return receipt.tree


def _checkpoint_context(config: ProductionCompositionConfig,
                        publication: PublicationCompositionInputs) -> str:
    """Bind durable work to the trusted deployment and its execution configuration.

    The deployment digest covers the installed policy/adapter code. Never load
    executable rules or provider credentials from recovery records.
    """
    verifier = config.verifier
    if not isinstance(verifier, CommandVerifier):
        raise CompositionError("durable publication requires a reproducible command verifier")
    reviewer_binary = getattr(config.review_runner, "binary", None)
    _require(isinstance(reviewer_binary, str) and bool(reviewer_binary),
             "durable publication requires an identified reviewer executable")
    convergence = config.convergence_policy or ConvergencePolicy(max_rounds=3)
    return hash_canonical({
        "schema": "gnosis.pipeline-context.v1",
        "deployment": publication.deployment.digest(),
        "repository_id": publication.repository_id,
        "repository_path": str(config.operator.repo_path.resolve()),
        "director_root": str(config.operator.director_root.resolve()),
        "evidence_root": str(publication.evidence_root.resolve()),
        "launch_root": str(config.deployment.launch_root.resolve()),
        "worker_sid": config.deployment.worker_account.expected_sid,
        "epoch": publication.epoch, "mode": config.execution_mode.value,
        "integration_target": config.integration_target,
        "credential": config.credential,
        "reviewer": {"id": config.attribution.reviewer_id,
                     "binary": reviewer_binary,
                     "adapter": type(config.review_runner).__module__ + "." + type(config.review_runner).__qualname__},
        "policy_actor": config.attribution.policy_actor,
        "verifier": {"name": verifier.name, "timeout_s": verifier.timeout_s,
                     "argv": shlex.split(verifier.command) if isinstance(verifier.command, str)
                             else list(verifier.command)},
        "convergence": {"max_rounds": convergence.max_rounds,
                        "max_unchanged_rounds": convergence.max_unchanged_rounds,
                        "blocking": sorted(v.value for v in convergence.blocking_severities),
                        "min_confidence": convergence.min_blocking_confidence},
    })


def build_production_deployment(config: ProductionCompositionConfig,
                                publication: PublicationCompositionInputs, *,
                                scope: ExecutionScope | None = None,
                                ) -> ProductionComposition:
    """Assemble the operator-reachable production composition (governed work +
    authoritative publication). Reuses the canonical `build_production_composition`
    for the governed graph, then binds the publication seam on top."""
    if config.execution_mode is ExecutionMode.PROVIDER_BACKED:
        expected = config.deployment.expected_deployment_digest
        _require(expected is not None and publication.deployment.digest() == expected,
                 "provider deployment differs from the Publisher's trusted expectation")
        tree = publication.deployment.runtime_tree
        _require(tree is not None and config.provider_runtime_tree is not None
                 and tree.digest() == config.provider_runtime_tree.digest(),
                 "provider and publication must bind the same runtime tree")
    if scope is not None:
        scope.check()
    pipeline = build_production_composition(config,
        checkpoint_store=PipelineCheckpointStore(publication.trust_state_root / "director-phases", scope),
        checkpoint_context=_checkpoint_context(config, publication), scope=scope)
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
                                 config.operator.repo_path, publisher_client, scope,
                                 config.integration_target,
                                 config.deployment.launch_root / "checks" /
                                 hash_canonical({"director_root":
                                     str(config.operator.director_root.resolve()).casefold()})[:32])
