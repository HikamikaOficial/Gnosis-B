"""F-33 Stage 2C-B — OS-real composed backend + single orchestration graph.

This module contains the COMPLETE privileged-path orchestration that Stage-2C-B1
will execute. It is written ONCE and driven by an injected operations backend, so
the DRY qualification and the future OS-REAL run traverse the SAME graph — only
the lowest-level side-effecting operations differ:

    DryOperations         — records calls, simulates just enough filesystem so the
                            real F-17 `Provisioner` and the composed provisioner
                            run their real code; NO Windows accounts/services/ACLs,
                            NO process spawn, NO provider calls.
    WindowsRealOperations — the real privileged backend (F-17 `RealOperations` +
                            sc.exe/pipe/spawn). GUARDED: only reachable under an
                            explicit OS-real authorization, never in this slice.

The backend CONSUMES the existing qualified F-17 `Provisioner` (install/uninstall)
through its own injected `Operations` protocol — F-17 owns F-17 semantics; this
module is orchestration/evidence only and reimplements no F-17 logic. No
`src/gnosis` production semantics are changed.

Live-call budget, transaction journal + rollback, residue manifest + recovery,
collision preflight and provider-environment isolation are all implemented here so
that B1 needs only configuration + authorization + execution.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from gnosis.provision.gnosis_deployment import (
    BaseDeployment,
    ComposedDeployment,
    GnosisDeploymentProvisioner,
    f17_publisher_files,
)
from gnosis.provision.layout import DeploymentLayout
from gnosis.provision.provisioner import (
    Operations,
    ProvisionConfig,
    Provisioner,
)

MAX_LIVE_CALLS = 5
RESIDUE_SCHEMA = "gnosis.stage2cb.residue.v1"


def _atomic_write_json(path: Path, obj: dict[str, Any]) -> None:
    """Transactional write: temp file in the same dir, flush + fsync, atomic
    replace. A partial/truncated record can never be observed; the prior valid
    generation survives a torn write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, indent=2, sort_keys=True).encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".residue_", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Live-call budget (hard cumulative ceiling of 5; L1 already consumed).
# ---------------------------------------------------------------------------
class BudgetError(RuntimeError):
    pass


@dataclass
class LiveCallBudget:
    used: int
    max_total: int = MAX_LIVE_CALLS

    def __post_init__(self) -> None:
        if self.used < 0 or self.used > self.max_total:
            raise BudgetError(f"invalid budget state: used={self.used} > max={self.max_total}")

    def remaining(self) -> int:
        return self.max_total - self.used

    def permit(self, n: int = 1) -> bool:
        return self.used + n <= self.max_total

    def consume(self, purpose: str) -> int:
        if not self.permit(1):
            raise BudgetError(
                f"live-call budget exhausted (used={self.used}/{self.max_total}); "
                f"refusing '{purpose}'")
        self.used += 1
        return self.used


# ---------------------------------------------------------------------------
# Residue manifest (hard-kill recovery record). Non-secret, deterministic.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ResidueManifest:
    run_id: str
    worker_username: str
    service_name: str
    pipe_name: str
    owned_roots: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"schema": RESIDUE_SCHEMA, "run_id": self.run_id,
                "worker_username": self.worker_username,
                "service_name": self.service_name, "pipe_name": self.pipe_name,
                "owned_roots": list(self.owned_roots)}

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def ownership_matches(manifest: ResidueManifest, config: Stage2CBConfig) -> bool:
    """True only if the residue manifest names EXACTLY this qualification's owned
    resources — so recovery cleans owned residue and never a prefix match."""
    return (manifest.worker_username == config.worker_username
            and manifest.service_name == config.service_name
            and manifest.pipe_name == config.pipe_name
            and set(manifest.owned_roots) == set(config.owned_roots()))


def plan_recovery(manifest: ResidueManifest,
                  config: Stage2CBConfig) -> tuple[bool, list[str]]:
    """(safe, targets). Refuses (safe=False) unless ownership matches exactly."""
    if not ownership_matches(manifest, config):
        return False, []
    targets = [f"delete_worker:{manifest.worker_username}",
               f"delete_service:{manifest.service_name}",
               *[f"rmtree:{r}" for r in manifest.owned_roots]]
    return True, targets


_RESIDUE_KEYS = {"schema", "run_id", "worker_username", "service_name",
                 "pipe_name", "owned_roots"}


def parse_residue_manifest(text: str) -> ResidueManifest:
    """Fail-closed parse: schema, exact keys, string fields, list of roots."""
    try:
        data = json.loads(text)
    except Exception as exc:
        raise ValueError(f"malformed residue manifest: {exc}") from exc
    if not isinstance(data, dict) or set(data.keys()) != _RESIDUE_KEYS:
        raise ValueError("residue manifest has unexpected keys")
    if data["schema"] != RESIDUE_SCHEMA:
        raise ValueError(f"unexpected residue schema {data['schema']!r}")
    for k in ("run_id", "worker_username", "service_name", "pipe_name"):
        if not isinstance(data[k], str) or not data[k]:
            raise ValueError(f"residue manifest {k} invalid")
    roots = data["owned_roots"]
    if not isinstance(roots, list) or not all(isinstance(r, str) and r for r in roots):
        raise ValueError("residue manifest owned_roots invalid")
    return ResidueManifest(run_id=data["run_id"], worker_username=data["worker_username"],
                           service_name=data["service_name"], pipe_name=data["pipe_name"],
                           owned_roots=tuple(roots))


# ---------------------------------------------------------------------------
# Crash-persistent residue ownership (v2). The in-memory journal handles the
# normal path; this on-disk record survives an ABRUPT kill so orphaned OS state
# is recoverable. INTENDED is persisted BEFORE mutation; ACQUIRED is persisted
# only AFTER a confirmed acquisition; the record is retired only after every owned
# resource is positively absent.
# ---------------------------------------------------------------------------
RESIDUE_SCHEMA_V2 = "gnosis.stage2cb.residue.v2"
_MAX_RESIDUE_BYTES = 65_536


@dataclass(frozen=True)
class ResourceOwnership:
    kind: str        # "worker" | "service" | "root"
    identity: str    # exact username / service name / root path
    intended: bool
    acquired: bool

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "identity": self.identity,
                "intended": self.intended, "acquired": self.acquired}


@dataclass(frozen=True)
class ResidueRecord:
    schema: str
    run_id: str
    generation: int
    status: str      # "active" | "cleaned"
    resources: tuple[ResourceOwnership, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "run_id": self.run_id,
                "generation": self.generation, "status": self.status,
                "resources": [r.to_dict() for r in self.resources]}


_REC_KEYS = {"schema", "run_id", "generation", "status", "resources"}
_RES_KEYS = {"kind", "identity", "intended", "acquired"}


def parse_residue_record(text: str) -> ResidueRecord:
    """Fail-closed: schema, exact keys, no duplicate keys, bounded, canonical."""
    if len(text.encode("utf-8")) > _MAX_RESIDUE_BYTES:
        raise ValueError("residue record too large")

    def _no_dupes(pairs: list[tuple[str, object]]) -> dict[str, object]:
        seen: dict[str, object] = {}
        for k, v in pairs:
            if k in seen:
                raise ValueError(f"duplicate key in residue record: {k}")
            seen[k] = v
        return seen

    try:
        data = json.loads(text, object_pairs_hook=_no_dupes)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"malformed residue record: {exc}") from exc
    if not isinstance(data, dict) or set(data.keys()) != _REC_KEYS:
        raise ValueError("residue record unexpected keys")
    if data["schema"] != RESIDUE_SCHEMA_V2:
        raise ValueError(f"unexpected residue schema {data['schema']!r}")
    if not isinstance(data["run_id"], str) or not data["run_id"]:
        raise ValueError("residue record run_id invalid")
    if not isinstance(data["generation"], int) or data["generation"] < 0:
        raise ValueError("residue record generation invalid")
    if data["status"] not in ("active", "cleaned"):
        raise ValueError("residue record status invalid")
    raw = data["resources"]
    if not isinstance(raw, list) or not raw:
        raise ValueError("residue record resources invalid")
    resources = []
    for r in raw:
        if not isinstance(r, dict) or set(r.keys()) != _RES_KEYS:
            raise ValueError("residue resource unexpected keys")
        if r["kind"] not in ("worker", "service", "root"):
            raise ValueError("residue resource kind invalid")
        if not isinstance(r["identity"], str) or not r["identity"]:
            raise ValueError("residue resource identity invalid")
        if not isinstance(r["intended"], bool) or not isinstance(r["acquired"], bool):
            raise ValueError("residue resource flags invalid")  # noqa: TRY004
        resources.append(ResourceOwnership(kind=r["kind"], identity=r["identity"],
                                           intended=r["intended"], acquired=r["acquired"]))
    return ResidueRecord(schema=data["schema"], run_id=data["run_id"],
                         generation=data["generation"], status=data["status"],
                         resources=tuple(resources))


def _resources_for(config: Stage2CBConfig) -> tuple[ResourceOwnership, ...]:
    res = [ResourceOwnership("worker", config.worker_username, True, False),
           ResourceOwnership("service", config.service_name, True, False)]
    res += [ResourceOwnership("root", r, True, False) for r in config.owned_roots()]
    return tuple(res)


class ResidueStore:
    """Atomic, generation-counted persistence of residue ownership."""

    def __init__(self, path: Path, run_id: str) -> None:
        self._path = Path(path)
        self._run_id = run_id

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> ResidueRecord | None:
        if not self._path.is_file():
            return None
        return parse_residue_record(self._path.read_text(encoding="utf-8"))

    def _write(self, record: ResidueRecord) -> None:
        _atomic_write_json(self._path, record.to_dict())

    def write_initial(self, config: Stage2CBConfig) -> ResidueRecord:
        rec = ResidueRecord(RESIDUE_SCHEMA_V2, config.run_id, 0, "active",
                            _resources_for(config))
        self._write(rec)
        return rec

    def _update(self, identities: set[str], acquired: bool) -> ResidueRecord:
        rec = self.load()
        if rec is None:
            raise RuntimeError("residue record missing during update")
        new = tuple(
            ResourceOwnership(r.kind, r.identity, r.intended,
                              acquired if r.identity in identities else r.acquired)
            for r in rec.resources)
        status = "cleaned" if all(not r.acquired for r in new) else "active"
        updated = ResidueRecord(rec.schema, rec.run_id, rec.generation + 1, status, new)
        self._write(updated)
        return updated

    def mark_acquired(self, identities: set[str]) -> ResidueRecord:
        return self._update(identities, True)

    def mark_cleaned(self, identities: set[str]) -> ResidueRecord:
        return self._update(identities, False)

    def retire(self) -> None:
        """Remove the record — call ONLY after every owned resource is absent."""
        try:
            self._path.unlink()
        except OSError:
            pass


def _resource_present(ops: Any, r: ResourceOwnership) -> bool:
    if r.kind == "worker":
        return not ops.account_absent(r.identity)
    if r.kind == "service":
        return not ops.service_absent(r.identity)
    return not ops.root_absent(r.identity)


def recover(store: ResidueStore, config: Stage2CBConfig,
            ops: Any) -> tuple[str, list[str]]:
    """Ownership-safe recovery from the persisted record.

    Returns (status, targets). Never assumes acquired=false => unrelated: it
    observes actual OS state by EXACT identity from the record's INTENT and cleans
    only resources present AND whose identity exactly matches this qualification.
    Unprovable ownership -> AMBIGUOUS_RESIDUE (no destructive cleanup)."""
    try:
        rec = store.load()
    except ValueError:
        return "MALFORMED_RECORD", []
    if rec is None:
        return "NO_RECORD", []
    if rec.run_id != config.run_id:
        return "REFUSE_RUN_MISMATCH", []
    owned_identities = {config.worker_username, config.service_name, *config.owned_roots()}
    targets: list[str] = []
    ambiguous: list[str] = []
    for r in rec.resources:
        if not r.intended:
            continue
        if not _resource_present(ops, r):
            continue  # already absent
        if r.identity in owned_identities:
            targets.append(f"{r.kind}:{r.identity}")
        else:
            ambiguous.append(f"{r.kind}:{r.identity}")
    if ambiguous:
        return "AMBIGUOUS_RESIDUE", []
    if not targets:
        return "STALE_VERIFIED_ABSENT", []
    return "PLAN", targets


# ---------------------------------------------------------------------------
# Transaction journal: every acquisition registers its cleanup BEFORE the next
# major operation, so no acquired resource is ever unowned by rollback.
# ---------------------------------------------------------------------------
@dataclass
class TransactionJournal:
    entries: list[tuple[str, Callable[[], None]]] = field(default_factory=list)

    def register(self, label: str, cleanup: Callable[[], None]) -> None:
        self.entries.append((label, cleanup))

    def rollback(self) -> tuple[bool, list[str]]:
        """Run cleanups in reverse; keep going on failure; report residue."""
        failures: list[str] = []
        for label, cleanup in reversed(self.entries):
            try:
                cleanup()
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{label}: {exc}")
        return (not failures), failures


# ---------------------------------------------------------------------------
# Config.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Stage2CBConfig:
    layout: DeploymentLayout
    service_name: str
    pipe_name: str
    worker_username: str
    package_version: str
    source_commit: str
    source_tree: str
    runtime_src: str
    reviewer_binary: str          # absolute path to the trusted claude executable
    run_id: str
    residue_root: str = ""        # recovery-record dir; MUST be outside owned_roots

    def owned_roots(self) -> tuple[str, ...]:
        return (self.layout.code_base, self.layout.state_base, self.layout.work_base)

    def residue_record_dir(self) -> str:
        """Deterministic, qualification-owned recovery location OUTSIDE the
        disposable roots (which are torn down during rollback). Defaults to a
        sibling of the code base — never CWD, never env, never a deleted root."""
        if self.residue_root:
            root = self.residue_root
        else:
            root = str(Path(self.layout.code_base).parent / "GnosisStage2CBRecovery")
        for owned in self.owned_roots():
            if root == owned or Path(owned) in Path(root).parents:
                raise ValueError("residue record dir must be outside owned roots")
        return root

    def residue_record_path(self) -> Path:
        return Path(self.residue_record_dir()) / f"{self.run_id}.residue.json"

    def provision_config(self) -> ProvisionConfig:
        return ProvisionConfig(
            layout=self.layout, service_name=self.service_name,
            pipe_name=self.pipe_name, worker_username=self.worker_username,
            package_version=self.package_version, source_commit=self.source_commit,
            source_tree=self.source_tree)


# ---------------------------------------------------------------------------
# The operations backend: F-17 `Operations` + the B1-only side effects.
# ---------------------------------------------------------------------------
class OperationsBackend(Operations, Protocol):
    # environment / preflight
    def is_elevated(self) -> bool: ...
    def utilities_present(self) -> bool: ...
    # service lifecycle (beyond F-17 create; F-17 creates, we start/stop/delete)
    def service_start(self, name: str) -> None: ...
    def pipe_ready(self, pipe_name: str) -> bool: ...
    def service_stop(self, name: str) -> None: ...
    # operator process: canonical_launch(spawn=True) intercept seam. Returns a
    # context manager; while active, process creation is faked (dry) or real
    # (WindowsRealOperations). `last_spawn` yields (argv, exit_code).
    def spawn_intercept(self, exit_code: int) -> Any: ...
    def last_spawn(self) -> tuple[tuple[str, ...], int] | None: ...
    # authoritative outcome observation
    def observe_anchored(self, run_id: str) -> bool: ...
    # rollback verification
    def account_absent(self, username: str) -> bool: ...
    def service_absent(self, name: str) -> bool: ...
    def root_absent(self, path: str) -> bool: ...


@dataclass
class FakeObserved:
    _digest: str

    def digest(self) -> str:
        return self._digest


# ---------------------------------------------------------------------------
# base_provision adapter — CONSUMES the real F-17 Provisioner through `ops`.
# ---------------------------------------------------------------------------
def make_base_provision(config: Stage2CBConfig, ops: Operations, *,
                        observe_fn: Any = None,
                        worker_password: str = "x") -> tuple[Callable[[], BaseDeployment],
                                                             dict[str, Any]]:
    """Return (base_provision, handle). base_provision runs the REAL F-17
    Provisioner.install() through `ops` and returns a BaseDeployment whose
    deployment_digest is the OBSERVED F-17 digest and whose rollback is the F-17
    uninstall() — no fabricated digest, no reimplemented provisioning."""
    handle: dict[str, Any] = {"provisioner": None, "install": None}

    def _base() -> BaseDeployment:
        prov = Provisioner(
            config=config.provision_config(), ops=ops,
            runtime_src=config.runtime_src,
            publisher_files=f17_publisher_files(_SRC()),
            bootstrap_files=(), toolchain_files=(), observe_fn=observe_fn)
        handle["provisioner"] = prov
        result = prov.install(worker_password)
        handle["install"] = result

        def _rollback() -> None:
            prov.uninstall(remove_worker=True)
        return BaseDeployment(layout=config.layout,
                              deployment_digest=result.deployment_digest,
                              rollback=_rollback)
    return _base, handle


def _SRC() -> Path:
    return Path(__file__).resolve().parent.parent / "src"


# ---------------------------------------------------------------------------
# Operator config builder — selects the REAL reviewer/publisher/worker path.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OperatorRouteSelection:
    reviewer_runner: str          # production runner class name
    reviewer_binary: str          # absolute trusted claude path (never a PATH lookup)
    publisher_client: str         # must be PipePublisherClient (never InProcess)
    worker_path: str              # F-17 trusted worker launch path
    replay_forbidden: bool


def select_production_route(config: Stage2CBConfig) -> OperatorRouteSelection:
    """The route the deployed operator (gnosis.director.cli:main) is configured to
    use. Asserts the real, non-replay, non-in-process selections."""
    if not config.reviewer_binary or not Path(config.reviewer_binary).is_absolute():
        raise ValueError("reviewer binary must be an absolute trusted deployment path")
    return OperatorRouteSelection(
        reviewer_runner="gnosis.runner.claude_cli_runner.ClaudeCLIRunner",
        reviewer_binary=config.reviewer_binary,
        publisher_client="gnosis.director.publisher_client.PipePublisherClient",
        worker_path="gnosis.director.trusted_runner.TrustedExecutionRunner"
                    " -> gnosis.trust.worker_launcher",
        replay_forbidden=True)


# ---------------------------------------------------------------------------
# Provider environment isolation (closed allowlist for the Director review call).
# ---------------------------------------------------------------------------
_REVIEWER_ENV_ALLOW = ("SystemRoot", "TEMP", "TMP", "USERPROFILE", "APPDATA",
                       "LOCALAPPDATA", "PATH", "HOMEDRIVE", "HOMEPATH")


def reviewer_environment(full_env: dict[str, str]) -> dict[str, str]:
    """The minimal environment for the Director's live reviewer call. A closed
    allowlist — the Worker and the Publisher service never receive this, and no
    secret categories are inherited blindly."""
    return {k: full_env[k] for k in _REVIEWER_ENV_ALLOW if k in full_env}


def worker_environment(full_env: dict[str, str]) -> dict[str, str]:
    """The Worker must NOT receive Claude auth/session state."""
    denied = ("ANTHROPIC", "CLAUDE", "AWS", "OPENAI")
    return {k: v for k, v in full_env.items()
            if not any(k.upper().startswith(d) for d in denied)}


# ---------------------------------------------------------------------------
# Preflight — must refuse mutation unless all hold.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    failures: tuple[str, ...]


def preflight(config: Stage2CBConfig, ops: OperationsBackend, *,
              expected_head: str, actual_head: str,
              f17_stable: bool, budget: LiveCallBudget,
              store: ResidueStore | None = None,
              owned_residue: ResidueManifest | None = None) -> PreflightResult:
    f: list[str] = []
    if not ops.is_elevated():
        f.append("not elevated")
    if actual_head != expected_head:
        f.append("HEAD mismatch")
    if not f17_stable:
        f.append("F-17 not byte-stable")
    if not Path(config.reviewer_binary).is_absolute():
        f.append("reviewer binary not an absolute path")
    if not budget.permit(1):
        f.append("no live-call budget")
    if ops.account_exists(config.worker_username):
        f.append("worker account collision")
    if not ops.service_absent(config.service_name):
        f.append("service collision")
    for root in config.owned_roots():
        if not ops.root_absent(root):
            f.append(f"root collision: {root}")
    if owned_residue is not None:
        f.append("owned residue requires recovery first")
    # crash-persistent residue record: read from disk BEFORE any mutation.
    if store is not None:
        try:
            rec = store.load()
        except ValueError:
            f.append("malformed residue record")
        else:
            if rec is not None and rec.status == "active":
                f.append("active residue record requires recovery/adjudication")
            elif (rec is not None and rec.status == "cleaned"
                  and any(_resource_present(ops, r) for r in rec.resources)):
                f.append("cleaned residue record but a resource is still present")
    if not ops.utilities_present():
        f.append("required utilities missing")
    return PreflightResult(ok=not f, failures=tuple(f))


# ---------------------------------------------------------------------------
# The ONE orchestration graph.
# ---------------------------------------------------------------------------
class OrchestrationError(RuntimeError):
    pass


@dataclass
class OrchestrationResult:
    success: bool
    stages: list[str]
    operator_exit: int | None
    anchored: bool
    completed: bool
    rollback_ok: bool
    rollback_failures: list[str]
    route: OperatorRouteSelection | None
    launch_argv: tuple[str, ...] | None
    spawn_true: bool


@dataclass
class Stage2CBOrchestrator:
    config: Stage2CBConfig
    ops: OperationsBackend
    budget: LiveCallBudget
    reobserve_f17: Callable[[], str]
    observe_fn: Any = None            # injected deployment observer (dry stand-in)
    inject_fail_after: str | None = None   # failure-injection point label
    consume_live_review: bool = True  # the positive path uses one live reviewer call
    operator_exit_code: int = 0       # the (faked, in dry) operator process exit
    residue_store: ResidueStore | None = None
    inject_crash_at: str | None = None     # hard-kill simulation boundary label
    error: str | None = None
    _hardkill: bool = field(default=False, init=False)

    def _stage(self, res: OrchestrationResult, label: str) -> None:
        res.stages.append(label)
        self._crash(label)
        if self.inject_fail_after == label:
            raise OrchestrationError(f"INJECTED failure after {label}")

    def _crash(self, label: str) -> None:
        """Simulate an ABRUPT hard kill at this boundary: the process 'dies', so
        rollback/finally does NOT run — only what was already persisted to disk
        remains. The test then inspects the residue record."""
        if self.inject_crash_at == label:
            self._hardkill = True
            raise OrchestrationError(f"HARD-KILL simulated at {label}")

    def _persistent_identities(self) -> set[str]:
        return {self.config.worker_username, self.config.service_name,
                *self.config.owned_roots()}

    def run(self) -> OrchestrationResult:
        res = OrchestrationResult(
            success=False, stages=[], operator_exit=None, anchored=False,
            completed=False, rollback_ok=False, rollback_failures=[], route=None,
            launch_argv=None, spawn_true=False)
        journal = TransactionJournal()
        try:
            # (1) persist INTENDED ownership BEFORE the first mutation, so an abrupt
            #     kill during provisioning still leaves a recovery record on disk.
            if self.residue_store is not None:
                self.residue_store.write_initial(self.config)
            self._crash("HK0_before_base")

            # -- base F-17 provisioning (real Provisioner via ops) --------------
            base_provision, _handle = make_base_provision(
                self.config, self.ops, observe_fn=self.observe_fn)
            base = base_provision()
            # (2) AMBIGUOUS WINDOW: the OS resources now exist but ACQUIRED is not
            #     yet persisted. A kill here leaves acquired=false while the worker/
            #     service exist — recovery must observe reality, not trust the flag.
            self._crash("HK_after_base_os_before_persist")
            # (3) only AFTER confirmed acquisition, persist acquired=true, atomically.
            if self.residue_store is not None:
                self.residue_store.mark_acquired(self._persistent_identities())
            # register the F-17 uninstall BEFORE anything else touches state
            journal.register("f17-uninstall", base.rollback)
            self._crash("HK_after_base_acquired")
            self._stage(res, "base_provision")

            # -- composed deployment (provision-time gate inside) ---------------
            comp: ComposedDeployment = GnosisDeploymentProvisioner(
                _SRC(), base_provision=lambda: base).provision()
            journal.register("composed-cleanup",
                             lambda: GnosisDeploymentProvisioner.cleanup(comp))
            self._stage(res, "composed_deployment")

            # -- trusted record finalized (provision already wrote+verified it) -
            self._stage(res, "trusted_record")

            # -- ACLs (F-17 Provisioner applied them via ops during install) ----
            self._stage(res, "acls")

            # -- Publisher service lifecycle ------------------------------------
            self.ops.service_start(self.config.service_name)
            journal.register("service-stop",
                             lambda: self.ops.service_stop(self.config.service_name))
            self._stage(res, "service_start")
            if not self.ops.pipe_ready(self.config.pipe_name):
                raise OrchestrationError("publisher pipe not ready")
            self._stage(res, "pipe_ready")

            # -- route selection: real reviewer/publisher/worker, no replay -----
            res.route = select_production_route(self.config)
            self._stage(res, "route_selected")

            # -- canonical launch: spawn=True ENCODED (dry fakes only the process
            #    creation seam via ops.spawn_intercept) --------------------------
            if self.consume_live_review:
                self.budget.consume("governed live reviewer (operator subprocess)")
            res.spawn_true = True
            with self.ops.spawn_intercept(self.operator_exit_code):
                try:
                    GnosisDeploymentProvisioner.canonical_launch(
                        comp, reobserve_f17=self.reobserve_f17, spawn=True,
                        operator_args=("run", "--brief", self.config.run_id))
                    res.operator_exit = 0  # spawn=True normally raises SystemExit
                except SystemExit as se:
                    res.operator_exit = int(se.code or 0)
            last = self.ops.last_spawn()
            if last is not None:
                res.launch_argv, res.operator_exit = last[0], last[1]
            self._stage(res, "operator_launch")

            # -- authoritative outcome: COMPLETED and persisted ANCHORED --------
            res.completed = res.operator_exit == 0
            res.anchored = self.ops.observe_anchored(self.config.run_id)
            self._stage(res, "anchored_check")
            res.success = bool(res.completed and res.anchored
                               and res.operator_exit == 0)
            if not res.success:
                raise OrchestrationError(
                    f"operator success requires COMPLETED and ANCHORED "
                    f"(exit={res.operator_exit}, anchored={res.anchored})")
            self._stage(res, "success")
        except Exception as exc:  # noqa: BLE001
            res.success = False
            self.error = str(exc)
        finally:
            if self._hardkill:
                # simulated abrupt kill: rollback/reconciliation does NOT run; only
                # what was already persisted to disk remains (the test inspects it).
                res.rollback_ok = False
            else:
                res.rollback_ok, res.rollback_failures = journal.rollback()
                self._reconcile_residue()
        return res

    def _reconcile_residue(self) -> None:
        """After rollback: persist cleaned state for resources now positively
        absent; retire the record ONLY when every owned resource is absent. If a
        cleanup failed, the record is KEPT describing the remaining residue."""
        store = self.residue_store
        if store is None:
            return
        rec = store.load()
        if rec is None:
            return
        absent = {r.identity for r in rec.resources
                  if not _resource_present(self.ops, r)}
        if absent:
            store.mark_cleaned(absent)
        rec2 = store.load()
        if rec2 is not None and all(not r.acquired for r in rec2.resources):
            store.retire()
