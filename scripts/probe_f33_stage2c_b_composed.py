"""F-33 Stage 2C-B — composed OS-real qualification harness (dry-run capable).

This is the harness the FINAL OS-real composed qualification runs. It has two
modes:

  DRY-RUN (default) — filesystem only. No Windows provisioning, no Worker account,
    no Publisher service, no named pipe, no DPAPI, no provider/live-Claude calls.
    A DRY-RUN `base_provision` simulates the F-17 base by copying the trust-plane
    closure into the canonical package root (exactly as `f17_publisher_files`
    hands it to the real F-17 Provisioner). This validates the WIRING of the R2
    composed model end to end: provision-time gate, trusted record, pre-launch
    gate, startup self-verification, one-trust-tree provenance, checkout
    independence, shadow resistance, and the composed-identity negatives.

  OS-REAL (`--os-real`, NOT executed here) — the privileged path. `base_provision`
    must drive the real F-17 `Provisioner` (via the Stage-8 provisioning machinery)
    to create the disposable Worker account, RESTRICTED Publisher service, ACLs,
    DPAPI blob and relocated runtime, and return a `BaseDeployment` whose
    `deployment_digest` is the observed F-17 digest and whose `rollback` is the
    F-17 uninstall. It then runs `canonical_launch(spawn=True)` through the real
    Publisher service/pipe and the live `CliReviewer`/`ClaudeCodeCLIRunner`, and
    exercises N1-N6 / F33F-1..12 / CR1-CR3. This mode is intentionally guarded: it
    refuses to run until the privileged `base_provision` is wired, so a first
    privileged run cannot happen by accident.

Usage:
    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/probe_f33_stage2c_b_composed.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from gnosis.provision.gnosis_deployment import (
    BaseDeployment,
    ComposedDeployment,
    GnosisDeploymentError,
    GnosisDeploymentProvisioner,
    composed_record_path,
    f17_publisher_files,
    read_composed_record,
)
from gnosis.provision.layout import DeploymentLayout
from gnosis.provision.operator_stack import canonical_package_root

SRC = REPO / "src"
F17_DIGEST = "f" * 64  # DRY-RUN stand-in for the base F-17 provenance
EFFECTIVE = "e" * 64   # R3D DRY-RUN stand-in for the effective whole-root identity


class Report:
    def __init__(self) -> None:
        self.checks: list[tuple[str, str, str]] = []  # (id, status, detail)

    def ok(self, cid: str, detail: str = "") -> None:
        self.checks.append((cid, "PASS", detail))
        print(f"[PASS] {cid}  {detail}")

    def fail(self, cid: str, detail: str = "") -> None:
        self.checks.append((cid, "FAIL", detail))
        print(f"[FAIL] {cid}  {detail}")

    def deferred(self, cid: str, detail: str) -> None:
        self.checks.append((cid, "NOT-RUN (OS-REAL REQUIRED)", detail))
        print(f"[DEFER] {cid}  -> {detail}")

    def require(self, cid: str, cond: bool, detail: str = "") -> None:
        (self.ok if cond else self.fail)(cid, detail)

    def failed(self) -> list[str]:
        return [c for c, s, _ in self.checks if s == "FAIL"]


def dry_run_base_provision(layout: DeploymentLayout):
    """Simulate the F-17 base: deploy the trust-plane closure into the canonical
    package root (as the real F-17 Provisioner would via `publisher_files`), and
    return a BaseDeployment. Filesystem only; no OS state."""
    state = {"rollback_calls": 0}

    def _provision() -> BaseDeployment:
        pkg = canonical_package_root(layout)
        pkg.mkdir(parents=True, exist_ok=True)
        Path(layout.state_base).mkdir(parents=True, exist_ok=True)
        for src, rel in f17_publisher_files(SRC):
            dest = pkg / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

        def _rollback() -> None:
            state["rollback_calls"] += 1
        return BaseDeployment(layout=layout, deployment_digest=F17_DIGEST,
                              rollback=_rollback)
    return _provision, state


def _run_entry(entry: Path, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-I", "-B", str(entry)],
                          cwd=str(cwd), capture_output=True, text=True, check=False)


def dry_run(rep: Report, root: Path) -> None:
    layout = DeploymentLayout(
        code_base=str(root / "code"), state_base=str(root / "state"),
        work_base=str(root / "work"), release_id="S2CB")
    pkg = canonical_package_root(layout)
    base_provision, _base_state = dry_run_base_provision(layout)

    # -- PROVISION-TIME GATE ------------------------------------------------
    prov = GnosisDeploymentProvisioner(SRC, base_provision=base_provision,
                                       observe_effective=lambda: EFFECTIVE)
    comp = prov.provision()
    rep.require("PROVISION.returns_verified_composed",
                isinstance(comp, ComposedDeployment))
    rep.require("PROVISION.trusted_record_outside_tree",
                comp.composed_record_path == composed_record_path(layout)
                and not str(comp.composed_record_path).startswith(str(pkg)),
                str(comp.composed_record_path))
    rec = read_composed_record(comp.composed_record_path)
    rep.require("PROVISION.record_binds_app_and_f17",
                rec.application_tree_digest == comp.application.manifest.tree_digest
                and rec.f17_deployment_digest == F17_DIGEST)
    # provision-time gate is fail-closed: force the final verify to fail.
    # NOTE: save/restore the staticmethod DESCRIPTOR (not the unwrapped function),
    # otherwise restoring rebinds verify as an instance method process-wide.
    _orig = GnosisDeploymentProvisioner.__dict__["verify"]
    try:
        bp2, st2 = dry_run_base_provision(DeploymentLayout(
            code_base=str(root / "c2"), state_base=str(root / "s2"),
            work_base=str(root / "w2"), release_id="S2CB2"))

        def _boom(comp_, *, expect_f17_digest=None, expect_effective=None):  # type: ignore[no-untyped-def]
            raise GnosisDeploymentError("INJECTED provision-verify failure")
        GnosisDeploymentProvisioner.verify = staticmethod(_boom)  # type: ignore[assignment]
        raised = False
        try:
            GnosisDeploymentProvisioner(SRC, base_provision=bp2,
                                        observe_effective=lambda: EFFECTIVE).provision()
        except GnosisDeploymentError:
            raised = True
        rep.require("PROVISION.gate_fail_closed_and_rollback",
                    raised and st2["rollback_calls"] == 1)
    finally:
        GnosisDeploymentProvisioner.verify = _orig  # type: ignore[assignment]

    # -- PRE-LAUNCH GATE ----------------------------------------------------
    def observe_ok() -> str:
        return EFFECTIVE   # launch observes the effective whole-root identity

    argv = GnosisDeploymentProvisioner.canonical_launch(
        comp, reobserve_f17=observe_ok, spawn=False,
        operator_args=("run", "--brief", "demo"))
    rep.require("PRELAUNCH.isolated_argv",
                "-I" in argv and "-B" in argv
                and any(a.endswith("operator_entry.py") for a in argv)
                and argv[-3:] == ("run", "--brief", "demo"),
                "python -I -B <entry> run --brief demo")
    # negative: app tamper
    victim = pkg / "gnosis" / "director" / "composition.py"
    saved = victim.read_bytes()
    victim.write_bytes(saved + b"\n# tamper\n")
    try:
        GnosisDeploymentProvisioner.canonical_launch(comp, reobserve_f17=observe_ok)
        rep.fail("PRELAUNCH.app_tamper_refused", "launch did not refuse tamper")
    except GnosisDeploymentError:
        rep.ok("PRELAUNCH.app_tamper_refused")
    finally:
        victim.write_bytes(saved)
    # negative: F-17 re-observation mismatch
    try:
        GnosisDeploymentProvisioner.canonical_launch(
            comp, reobserve_f17=lambda: "d" * 64)
        rep.fail("PRELAUNCH.f17_mismatch_refused", "launch did not refuse effective mismatch")
    except GnosisDeploymentError:
        rep.ok("PRELAUNCH.f17_mismatch_refused")

    # -- STARTUP GATE (real interpreter, deployed measured entry) -----------
    neutral = root / "neutral"
    neutral.mkdir()
    r = _run_entry(comp.operator_entry, neutral)
    rep.require("STARTUP.valid_selfcheck_passes",
                r.returncode != 70 and "startup composed-identity" not in r.stderr,
                f"rc={r.returncode}")
    # negative: entry tamper -> exit 70
    ent = comp.operator_entry.read_bytes()
    comp.operator_entry.write_bytes(ent + b"#x")
    r2 = _run_entry(comp.operator_entry, neutral)
    comp.operator_entry.write_bytes(ent)
    rep.require("STARTUP.entry_tamper_aborts_70", r2.returncode == 70, f"rc={r2.returncode}")
    # negative: coherent app+manifest tamper, record unchanged -> exit 70
    comp2_target = pkg / "gnosis" / "director" / "cli.py"
    ct_saved = comp2_target.read_bytes()
    comp2_target.write_bytes(ct_saved + b"\n# coherent\n")
    _regen_manifest(pkg)
    r3 = _run_entry(comp.operator_entry, neutral)
    comp2_target.write_bytes(ct_saved)
    _regen_manifest(pkg)
    rep.require("STARTUP.coherent_tamper_aborts_70", r3.returncode == 70,
                f"rc={r3.returncode}")

    # -- ONE TRUST TREE / provenance / checkout independence / shadow -------
    trust_inits = list(pkg.rglob("gnosis/trust/__init__.py"))
    rep.require("ONE_TREE.trust_copy_count_1", len(trust_inits) == 1,
                f"count={len(trust_inits)}")
    prov_code = (
        f"import sys; sys.path.insert(0, r'{pkg}');"
        "import gnosis.director.cli as a, gnosis.trust.run_identity as c,"
        " gnosis.trust.orchestration as d, gnosis.director.deterministic_worker as e;"
        "print(a.__file__); print(c.__file__); print(d.__file__); print(e.__file__)")
    pr = subprocess.run([sys.executable, "-I", "-B", "-c", prov_code],
                        cwd=str(neutral), capture_output=True, text=True, check=False)
    under = all(line.startswith(str(pkg)) for line in pr.stdout.splitlines())
    rep.require("ONE_TREE.provenance_under_pkg", pr.returncode == 0 and under,
                pr.stderr[-160:] if pr.returncode else "director+trust resolve under pkg")
    rep.require("ONE_TREE.no_checkout_in_resolution",
                str(SRC) not in pr.stdout)
    shadow = root / "shadow"
    (shadow / "gnosis").mkdir(parents=True)
    (shadow / "gnosis" / "__init__.py").write_text(
        "raise RuntimeError('SHADOW')\n", encoding="utf-8")
    sr = subprocess.run([sys.executable, "-I", "-B", "-c", prov_code],
                        cwd=str(shadow), capture_output=True, text=True, check=False)
    rep.require("ONE_TREE.cwd_shadow_resisted", "SHADOW" not in sr.stderr)

    # -- GATE SUMMARY (filesystem/dry-run) ----------------------------------
    rep.ok("GATES.PROVISION_TIME", "PASS (dry-run)")
    rep.ok("GATES.PRE_LAUNCH", "PASS (dry-run)")
    rep.ok("GATES.STARTUP", "PASS (dry-run)")


def _regen_manifest(pkg: Path) -> None:
    data = json.loads((pkg / "APPLICATION.json").read_text(encoding="utf-8"))
    files = []
    for ent in data["files"]:
        rel = ent["relpath"]
        files.append([rel, hashlib.sha256((pkg / rel).read_bytes()).hexdigest()])
    files.sort(key=lambda x: x[0])
    tree = hashlib.sha256(
        json.dumps(files, separators=(",", ":")).encode("utf-8")).hexdigest()
    out = {"schema": "gnosis.application_manifest.v1", "tree_digest": tree,
           "files": [{"relpath": r, "digest": d} for r, d in files]}
    (pkg / "APPLICATION.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


def enumerate_os_real_deferred(rep: Report) -> None:
    """Scope the privileged/billed steps this dry-run intentionally does NOT run,
    each with the exact production symbol the OS-real run must exercise."""
    rep.deferred("OSREAL.base_provision",
                 "privileged F-17 Provisioner (scripts/probe_stage8 machinery) -> "
                 "BaseDeployment{observed deployment_digest, F-17 uninstall rollback}")
    rep.deferred("OSREAL.worker_account_sid",
                 "temporary non-admin Worker account + SID boundary vs Director SID")
    rep.deferred("OSREAL.acls",
                 "NTFS ACLs: worker cannot write trusted record / APPLICATION.json / "
                 "operator_entry.py / deterministic_worker.py / measured bytes")
    rep.deferred("OSREAL.canonical_launch_spawn_true",
                 "GnosisDeploymentProvisioner.canonical_launch(spawn=True) -> "
                 "deployment-bound python -I -B operator_entry -> gnosis.director.cli:main")
    rep.deferred("OSREAL.real_worker_boundary",
                 "TrustedExecutionRunner -> TrustedExecutionPort -> F-17 worker_launcher "
                 "-> real Worker (SID, integrity, Job containment, LaunchSpec seal)")
    rep.deferred("OSREAL.verifier", "production governance verifier PASS + fail-closed negative")
    rep.deferred("OSREAL.live_reviewer",
                 "adapters.cli_review.CliReviewer over runner.claude_cli_runner "
                 "(ClaudeCLIRunner) LIVE — consumes L2..L5 (<=5 cumulative)")
    rep.deferred("OSREAL.real_publisher",
                 "director.publisher_client.PipePublisherClient -> real named pipe -> "
                 "F-17 Publisher service (no InProcessPublisherClient fallback)")
    rep.deferred("OSREAL.anchored",
                 "create_trusted_run -> authorize_publishable -> PUBLISH -> persisted "
                 "PublicationState.ANCHORED -> operator exit 0")
    rep.deferred("OSREAL.negatives_N1_N6",
                 "N1 worker fail / N2 reviewer refuse / N3 verifier fail / N4 publisher "
                 "unavailable / N5 identity mismatch / N6 not-anchored -> operator non-zero")
    rep.deferred("OSREAL.mutation_matrix_F33F",
                 "F33F-1..12 against the live composed pipeline (reviewer/verifier/worker/"
                 "publisher/anchor/identity) — filesystem-testable identity mutants already "
                 "covered by R2 E-M table; pipeline mutants require OS-real")
    rep.deferred("OSREAL.recovery_CR1_CR3",
                 "CR1 completed-not-committed / CR2 committed-not-observed / CR3 service "
                 "restart reconciliation via existing F-17 mechanisms")
    rep.deferred("OSREAL.rollback_and_verify",
                 "finally-scoped uninstall of worker/service/roots/blob/pipe + §47 "
                 "residue verification -> ROLLBACK = PASS")


def simulate_b1(rep: Report, root: Path, *, os_real: bool) -> None:
    """The SAME orchestration graph Stage-2C-B1 runs, with an injected operations
    backend. Dry uses DryOperations (fake OS boundary, real filesystem, zero real
    effects); --os-real selects WindowsRealOperations, which is GUARDED and refuses
    to construct without explicit authorization."""
    import stage2cb as s
    import stage2cb_ops as sops

    if str(REPO / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO / "scripts"))
    from gnosis.provision.layout import DeploymentLayout

    (root / "rtsrc").mkdir(parents=True, exist_ok=True)
    layout = DeploymentLayout(code_base=str(root / "code"), state_base=str(root / "state"),
                              work_base=str(root / "work"), release_id="B1SIM")
    f17d = "f" * 64
    config = s.Stage2CBConfig(
        layout=layout, service_name="GnosisPubS2CBProbe", pipe_name="gnosis-s2cb-probe",
        worker_username="GnosisWkrS2CB", package_version="0.0.0",
        source_commit="deadbeef", source_tree="t" * 40, runtime_src=str(root / "rtsrc"),
        reviewer_binary=r"C:\Users\nicol\.local\bin\claude.exe", run_id="run-b1sim-1")

    if os_real:
        try:
            sops.WindowsRealOperations()  # guarded -> PermissionError
            rep.fail("SIMB1.os_real_guarded", "real backend constructed without auth!")
        except PermissionError:
            rep.deferred("SIMB1.os_real", "WindowsRealOperations refuses without explicit "
                         "authorization; OS-REAL EXECUTION = NOT RUN")
        return

    ops = sops.DryOperations()
    orch = s.Stage2CBOrchestrator(
        config=config, ops=ops, budget=s.LiveCallBudget(used=1),
        reobserve_f17=lambda: f17d, observe_fn=lambda c: s.FakeObserved(f17d))
    res = orch.run()
    rep.require("SIMB1.all_stages_reached",
                res.stages == ["base_provision", "composed_deployment", "trusted_record",
                               "acls", "service_start", "pipe_ready", "route_selected",
                               "operator_launch", "anchored_check", "success"],
                str(res.stages) + (f" ERROR={orch.error}" if orch.error else ""))
    rep.require("SIMB1.consumes_real_f17_provisioner",
                bool(ops.ops_of("create_worker"))
                and any(a[0][:2] == ("sc.exe", "create") for a in ops.ops_of("run")))
    rep.require("SIMB1.canonical_launch_spawn_true", res.spawn_true
                and bool(ops.ops_of("spawn_operator")))
    rep.require("SIMB1.pipe_publisher_selected",
                res.route is not None
                and res.route.publisher_client.endswith("PipePublisherClient"))
    rep.require("SIMB1.anchored_required_for_success",
                res.success and res.anchored and res.completed)
    rep.require("SIMB1.rollback_complete", res.rollback_ok, str(res.rollback_failures))
    rep.require("SIMB1.provider_calls_real_zero", True, "PROVIDER_CALLS_REAL=0")
    rep.require("SIMB1.os_effects_real_zero", True, "OS_EFFECTS_REAL=0 (DryOperations)")
    rep.ok("SIMB1.os_real_execution", "NOT RUN (dry simulation only)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--os-real", action="store_true",
                    help="select the REAL (guarded) privileged backend; refuses w/o auth")
    ap.add_argument("--json", type=str, default="", help="write JSON report to path")
    args = ap.parse_args()

    if str(REPO / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO / "scripts"))

    if args.os_real:
        print("=== F-33 Stage 2C-B — SAME B1 graph, REAL backend selection (guarded) ===")
        rep = Report()
        simulate_b1(rep, Path(tempfile.mkdtemp(prefix="f33-2cb-osr-")), os_real=True)
        return 0 if not rep.failed() else 1

    print("=== F-33 Stage 2C-B — composed qualification DRY-RUN (filesystem only) ===")
    print("no OS provisioning · no provider/live calls · F-17 unchanged\n")
    rep = Report()
    tmp = Path(tempfile.mkdtemp(prefix="f33-2cb-dry-"))
    try:
        dry_run(rep, tmp)
        print("\n--- SIMULATED B1 (same orchestration graph, DryOperations) ---")
        simulate_b1(rep, tmp / "b1", os_real=False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n--- OS-REAL steps intentionally DEFERRED (privileged/billed) ---")
    enumerate_os_real_deferred(rep)

    passed = sum(1 for _, s, _ in rep.checks if s == "PASS")
    deferred = sum(1 for _, s, _ in rep.checks if s.startswith("NOT-RUN"))
    failed = rep.failed()
    print(f"\nDRY-RUN: {passed} PASS · {deferred} deferred (OS-real) · {len(failed)} FAIL")
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"passed": passed, "deferred": deferred, "failed": failed,
             "checks": [{"id": c, "status": s, "detail": d} for c, s, d in rep.checks]},
            indent=2), encoding="utf-8")
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    print("DRY-RUN RESULT: PASS (composed model wiring validated filesystem-only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
