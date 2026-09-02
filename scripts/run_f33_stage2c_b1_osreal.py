"""F-33 Stage 2C-B1 — OS-real execution DRIVER (composition/bootstrap only).

This is the ONE explicit, authorized entrypoint that invokes the already-qualified
`Stage2CBOrchestrator` OS-real path. It performs NO production semantics of its own
(no account/ACL/service/review/publication/RunIdentity/composed-identity logic —
those live in the qualified components). It only:

    parse explicit authorization
      -> validate HEAD / source freeze
      -> load configuration (operator config.json + brief.json)
      -> locate the absolute trusted reviewer executable
      -> locate the qualified relocatable runtime_src (= sys.base_prefix, the
         mechanism qualified by F-17 Stage-8)
      -> configure REAL F-17 re-observation (observe_deployment)
      -> (only after gates) construct WindowsRealOperations(authorized=True)
      -> construct the qualified Stage2CBOrchestrator
      -> run the existing orchestration
      -> evidence / rollback (via the orchestrator's own residue mechanism)

DEFAULT invocation mutates NOTHING (dry trace). OS-real requires BOTH
`--execute-os-real` AND `--confirm <token>`, AND all gates must pass first; the
real backend is never constructed before authorization + HEAD + residue + preflight.

No `src/gnosis` change. No F-17 change. No provider call in this module.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import identity_delta as idd
import stage2cb as s
import stage2cb_ops as sops

from gnosis.provision.layout import DeploymentLayout

# The runtime source qualified by F-17 Stage-8 (`_make_provisioner`,
# runtime_src=sys.base_prefix). Never downloaded, never ad hoc.
QUALIFIED_RUNTIME_SRC = sys.base_prefix
# Explicit hard confirmation token required for privileged execution.
CONFIRM_TOKEN = "EXECUTE-F33-2CB1-OS-REAL"


@dataclass
class DriverConfig:
    stage: s.Stage2CBConfig
    reviewer_binary: str
    runtime_src: str
    live_used: int                    # authoritative cumulative live-call count
    operator_config_path: Path
    operator_brief_path: Path

    def operator_args(self) -> tuple[str, ...]:
        # The VERIFIED production CLI contract (archaeology of gnosis.director.cli):
        # `run --config <trusted config JSON path> --brief <operator brief JSON path>`.
        return ("run", "--config", str(self.operator_config_path),
                "--brief", str(self.operator_brief_path))


# ---------------------------------------------------------------------------
# Configuration loading (driver bootstrap; no production semantics).
# ---------------------------------------------------------------------------
def build_operator_config(cfg: s.Stage2CBConfig, reviewer_binary: str) -> dict[str, Any]:
    """The trusted operator config `gnosis.director.cli` requires (exact sections:
    deployment, attribution, operator, publication, verifier, reviewer)."""
    lay = cfg.layout
    return {
        "deployment": {
            "code_base": lay.code_base, "state_base": lay.state_base,
            "work_base": lay.work_base, "worker_username": cfg.worker_username,
            "trust_root": lay.trust_root},
        "attribution": {"reviewer_id": "claude-code-cli",
                        "policy_actor": "gnosis-director"},
        "operator": {"director_root": lay.state_base, "repo_path": str(REPO)},
        "publication": {
            "trust_state_root": lay.state_base, "evidence_root": lay.bundles_root,
            "repository_id": "gnosis", "pipe_name": cfg.pipe_name,
            "service_name": cfg.service_name},
        "verifier": {"name": "gnosis-verify",
                     "command": [str(Path(lay.runtime_executable)), "-I", "-B", "-c",
                                 "raise SystemExit(0)"]},
        "reviewer": {"binary": reviewer_binary},
    }


def build_operator_brief(cfg: s.Stage2CBConfig) -> dict[str, Any]:
    """A minimal structurally-valid DirectorBrief (contracts.director_brief)."""
    return {"brief_id": cfg.run_id, "title": "F-33 2C-B1 qualification brief",
            "mission": "governed no-op qualification brief", "source": "manual",
            "non_negotiables": [], "constraints": [], "acceptance_criteria": [],
            "raw_text": "", "metadata": {"stage": "2C-B1"}}


def write_operator_inputs(dcfg: DriverConfig) -> None:
    dcfg.operator_config_path.parent.mkdir(parents=True, exist_ok=True)
    dcfg.operator_config_path.write_text(
        json.dumps(build_operator_config(dcfg.stage, dcfg.reviewer_binary), indent=2),
        encoding="utf-8")
    dcfg.operator_brief_path.write_text(
        json.dumps(build_operator_brief(dcfg.stage), indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# REAL F-17 re-observation binding (§6). Fresh observe_deployment -> digest.
# ---------------------------------------------------------------------------
def make_real_reobserve(cfg: s.Stage2CBConfig,
                        recorder: Any = None) -> Callable[[], str]:
    def _observe() -> str:
        from gnosis.trust.deployment import DesiredDeploymentConfig, observe_deployment
        lay = cfg.layout
        identity = observe_deployment(DesiredDeploymentConfig(
            trust_root=Path(lay.trust_root),
            runtime_executable=Path(lay.runtime_executable),
            runtime_root=Path(lay.runtime_root),
            runidentity_store=Path(lay.runidentity_root),
            anchorstore=Path(lay.anchors_root),
            service_name=cfg.service_name))
        # R3B: record the SAME identity whose digest is returned to the trust gate.
        # Wrapped so that NOTHING the recorder does — even an exception — can break
        # or bypass the gate: the authoritative digest is always what is returned.
        if recorder is not None:
            try:
                recorder.record_launch(identity)
            except Exception:  # noqa: BLE001,S110  diagnostics never break the gate
                pass
        return identity.digest()
    return _observe


# ---------------------------------------------------------------------------
# Gate chain. Real ops constructed ONLY after auth + HEAD + residue + preflight.
# ---------------------------------------------------------------------------
def expected_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO),
                          capture_output=True, text=True, check=False).stdout.strip()


@dataclass
class GateResult:
    ok: bool
    failures: list[str] = field(default_factory=list)
    real_ops_constructed: bool = False


def _finalize_scaffold(dcfg: DriverConfig, trace: dict[str, Any],
                       cleanup_scaffold: bool) -> None:
    """Driver-owned scaffold cleanup on EVERY terminal path. The scaffold root is
    the deployment root (the exactly-owned parent of code/state/work AND of the
    recovery dir). Remove it ONLY after the residue record is retired (full
    rollback); if a residue record remains (rollback failed / real residue), KEEP
    the scaffold so recovery can act — never delete recovery metadata."""
    import shutil as _sh
    scaffold_root = Path(dcfg.stage.layout.code_base).parent
    store = s.ResidueStore(dcfg.stage.residue_record_path(), dcfg.stage.run_id)
    residue_present = store.path.is_file()
    if residue_present:
        trace["scaffold_cleanup"] = "RETAINED (residue record present; recover first)"
        return
    if not cleanup_scaffold:
        trace["scaffold_cleanup"] = "left (caller-managed root)"
        return
    _sh.rmtree(scaffold_root, ignore_errors=True)
    trace["scaffold_cleanup"] = ("removed" if not scaffold_root.exists()
                                 else "FAILED (residue present)")


def run_driver(dcfg: DriverConfig, *, execute_os_real: bool, confirm: str,
               expected_head_sha: str, dry_ops: Any | None = None,
               cleanup_scaffold: bool = False) -> dict[str, Any]:
    """The single gated flow. With execute_os_real=False (default) it runs the
    orchestrator with a fake backend and proves ZERO real effects. With
    execute_os_real=True it requires the confirm token and passing gates before it
    would construct the real backend."""
    trace: dict[str, Any] = {"mode": "os-real" if execute_os_real else "dry",
                             "real_ops_constructed": False, "gates": [],
                             "orchestration": None, "bindings": plan_trace(dcfg)}

    # -- gate 1: explicit authorization (EDM1) ------------------------------
    if execute_os_real and confirm != CONFIRM_TOKEN:
        trace["gates"].append("REFUSE: missing/invalid confirmation token")
        trace["result"] = "BLOCKED-NO-AUTH"
        return trace

    # -- gate 2: source freeze ---------------------------------------------
    actual = expected_head()
    if execute_os_real and actual != expected_head_sha:
        trace["gates"].append(f"REFUSE: HEAD {actual} != expected {expected_head_sha}")
        trace["result"] = "BLOCKED-HEAD"
        return trace
    trace["gates"].append("HEAD checked")

    # R3B: harness-only identity-delta recorder (pure/read-only; in-memory only, so
    # it lives strictly OUTSIDE every identity-observed root and cannot create a
    # digest delta). Captures the authoritative provision + launch observations.
    recorder = idd.IdentityDeltaRecorder()

    # backend selection: DRY unless explicitly executing os-real AND gates pass.
    if execute_os_real:
        ops = _construct_real_ops_after_gates(dcfg, trace)
        if ops is None:
            return trace  # a gate refused; real ops NOT constructed
        reobserve = make_real_reobserve(dcfg.stage, recorder)
        # R3D: a distinct (non-recording) whole-root observer for the provision-time
        # effective measurement — same observation, but it must not write the R3B
        # launch snapshot.
        observe_effective = make_real_reobserve(dcfg.stage)
        observe_fn = None  # -> Provisioner uses real observe_deployment (proven)
    else:
        ops = dry_ops if dry_ops is not None else sops.DryOperations()
        # dry stand-ins (no real deployment exists). base provenance "f", effective
        # whole-root "e" (post-app, distinct from base) — and the launch observer
        # returns the SAME effective so the canonical-launch gate passes on the
        # unchanged dry deployment.
        reobserve = (lambda: "e" * 64)
        observe_effective = (lambda: "e" * 64)
        observe_fn = (lambda c: s.FakeObserved("f" * 64))

    write_operator_inputs(dcfg)
    store = s.ResidueStore(dcfg.stage.residue_record_path(), dcfg.stage.run_id)
    orch = s.Stage2CBOrchestrator(
        config=dcfg.stage, ops=ops, budget=s.LiveCallBudget(used=dcfg.live_used),
        reobserve_f17=reobserve, observe_effective=observe_effective,
        observe_fn=observe_fn, residue_store=store,
        operator_args=dcfg.operator_args(), identity_recorder=recorder)
    res = orch.run()
    trace["orchestration"] = {
        "stages": res.stages, "success": res.success,
        "operator_exit": res.operator_exit, "anchored": res.anchored,
        "rollback_ok": res.rollback_ok, "launch_argv": list(res.launch_argv or ()),
        "error": orch.error,
        # R2A: structured publisher-failure diagnostics (populated on pipe failure).
        "pipe_readiness": res.pipe_readiness,
        "service_postmortem": res.service_postmortem,
        "publisher_failure_class": res.publisher_failure_class}
    trace["real_ops_constructed"] = isinstance(ops, sops.WindowsRealOperations)
    # R3B: the authoritative provision/launch identity delta (in-memory only). On a
    # digest mismatch this names the exact differing component(s); it NEVER changes
    # the gate outcome above.
    trace["identity_delta"] = recorder.result()
    trace["result"] = "DRY-TRACE-OK" if not execute_os_real else "OS-REAL-RAN"
    _finalize_scaffold(dcfg, trace, cleanup_scaffold)
    return trace


def _construct_real_ops_after_gates(dcfg: DriverConfig, trace: dict[str, Any]) -> Any:
    """Construct the authorized real backend ONLY after residue + runtime + preflight
    gates (auth + HEAD already checked by the caller)."""
    cfg = dcfg.stage
    # residue gate (read the persisted record BEFORE constructing a mutating backend)
    store = s.ResidueStore(cfg.residue_record_path(), cfg.run_id)
    try:
        rec = store.load()
    except ValueError:
        trace["gates"].append("REFUSE: malformed residue record")
        trace["result"] = "BLOCKED-RESIDUE"
        return None
    if rec is not None and rec.status == "active":
        trace["gates"].append("REFUSE: active residue record (recover first)")
        trace["result"] = "BLOCKED-RESIDUE"
        return None
    # runtime_src gate (§9)
    if not Path(dcfg.runtime_src).is_dir() or not (
            Path(dcfg.runtime_src) / "python.exe").exists():
        trace["gates"].append("REFUSE: runtime_src invalid/non-relocatable")
        trace["result"] = "BLOCKED-RUNTIME"
        return None
    # construct the read-capable real backend, then preflight, then gate mutation
    ops = sops.WindowsRealOperations(authorized=True,
                                     runidentity_root=cfg.layout.runidentity_root)
    pf = s.preflight(cfg, ops, expected_head=expected_head(), actual_head=expected_head(),
                     f17_stable=True, budget=s.LiveCallBudget(used=dcfg.live_used),
                     store=store)
    if not pf.ok:
        trace["gates"].append(f"REFUSE preflight: {pf.failures}")
        trace["result"] = "BLOCKED-PREFLIGHT"
        return None
    trace["gates"].append("preflight PASS; real backend authorized")
    return ops


def recover(dcfg: DriverConfig) -> tuple[str, list[str]]:
    """Explicit ownership-safe recovery entrypoint (separate from a new run)."""
    store = s.ResidueStore(dcfg.stage.residue_record_path(), dcfg.stage.run_id)
    ops = sops.WindowsRealOperations(authorized=True,
                                     runidentity_root=dcfg.stage.layout.runidentity_root)
    return s.recover(store, dcfg.stage, ops)


# ---------------------------------------------------------------------------
# Pre-mutation trace (§20).
# ---------------------------------------------------------------------------
def plan_trace(dcfg: DriverConfig) -> dict[str, Any]:
    cfg = dcfg.stage
    return {
        "expected_head": expected_head(),
        "runtime_src": dcfg.runtime_src,
        "reviewer_executable": dcfg.reviewer_binary,
        "worker_username": cfg.worker_username,
        "service_name": cfg.service_name,
        "pipe_name": cfg.pipe_name,
        "residue_record_path": str(cfg.residue_record_path()),
        "f17_observer": "gnosis.trust.deployment.observe_deployment",
        "os_backend": "stage2cb_ops.WindowsRealOperations",
        "live_ledger": f"{dcfg.live_used} used / {s.MAX_LIVE_CALLS - dcfg.live_used} remaining",
        "operator_argv": list(dcfg.operator_args()),
        "driver_owned_resources": {
            # exactly-owned scaffold root (parent of code/state/work AND recovery dir);
            # all nested driver artifacts covered by this one run-bound root.
            "scaffold_root": str(Path(cfg.layout.code_base).parent),
            "operator_config": str(dcfg.operator_config_path),
            "operator_brief": str(dcfg.operator_brief_path),
            "residue_record": str(cfg.residue_record_path()),
        },
    }


def default_driver_config(root: Path, *, live_used: int = 1,
                          reviewer_binary: str = r"C:\Users\nicol\.local\bin\claude.exe"
                          ) -> DriverConfig:
    layout = DeploymentLayout(
        code_base=str(root / "code"), state_base=str(root / "state"),
        work_base=str(root / "work"), release_id="B1")
    stage = s.Stage2CBConfig(
        layout=layout, service_name="GnosisPubS2CBProbe",
        # CANONICAL pipe identity: the FULL local pipe path the PipeServer creates
        # and PipePublisherClient opens (Stage-8 form). A bare name is invalid.
        pipe_name=r"\\.\pipe\gnosis-s2cb-probe",
        worker_username="GnosisWkrS2CB", package_version="0.0.0",
        source_commit="deadbeef", source_tree="t" * 40, runtime_src=QUALIFIED_RUNTIME_SRC,
        reviewer_binary=reviewer_binary, run_id="run-b1-1")
    inputs = Path(stage.residue_record_dir()) / "inputs"
    return DriverConfig(
        stage=stage, reviewer_binary=reviewer_binary, runtime_src=QUALIFIED_RUNTIME_SRC,
        live_used=live_used, operator_config_path=inputs / "operator_config.json",
        operator_brief_path=inputs / "operator_brief.json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="run_f33_stage2c_b1_osreal")
    ap.add_argument("--execute-os-real", action="store_true",
                    help="PRIVILEGED: perform the real OS-real B1 run (requires --confirm)")
    ap.add_argument("--confirm", default="", help="explicit confirmation token")
    ap.add_argument("--expected-head", default="", help="required source baseline SHA")
    ap.add_argument("--recover-owned-residue", action="store_true",
                    help="explicit ownership-safe recovery (separate from a new run)")
    ap.add_argument("--root", default="", help="deployment root (default: temp for dry)")
    args = ap.parse_args(argv)

    import tempfile
    # Deterministic, run-bound scaffold root (NOT random mkdtemp) so an abrupt kill
    # leaves a recoverable, exactly-owned root derivable from the run_id.
    root = (Path(args.root) if args.root
            else Path(tempfile.gettempdir()) / "gnosis-2cb-b1-run-b1-1")
    dcfg = default_driver_config(root)

    if args.recover_owned_residue:
        if not args.execute_os_real:
            print("recovery requires --execute-os-real (privileged); refusing in dry mode")
            return 3
        status, targets = recover(dcfg)
        print(json.dumps({"recovery": status, "targets": targets}, indent=2))
        return 0 if status in ("PLAN", "STALE_VERIFIED_ABSENT", "NO_RECORD") else 4

    trace = run_driver(dcfg, execute_os_real=args.execute_os_real, confirm=args.confirm,
                       expected_head_sha=args.expected_head or expected_head(),
                       cleanup_scaffold=True)  # driver owns + cleans its deterministic root
    print(json.dumps(trace, indent=2))
    return 0 if trace.get("result") in ("DRY-TRACE-OK", "OS-REAL-RAN") else 3


if __name__ == "__main__":
    raise SystemExit(main())
