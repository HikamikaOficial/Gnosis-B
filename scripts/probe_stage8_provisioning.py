"""F-17 Stage 8 — OS-real provisioning qualification probe.

Everything the Stage 8 provisioner claims, asserted against REAL Windows state:
a real dedicated worker account, a real RESTRICTED-SID service, real NTFS ACLs
under real `C:\\Program Files` / `C:\\ProgramData` ancestors, a real DPAPI
credential blob, a real relocated runtime with a real `python._pth`, and the
real deployment identity the trust plane observes.

WHAT IS DISPOSABLE. All of it, and it is all rolled back. A probe-only worker
account (`GnosisWkrS8`), a probe-only service (`GnosisPubS8Probe`), probe-only
roots under `C:\\Program Files\\GnosisStage8Probe` and
`C:\\ProgramData\\GnosisStage8Probe`, a probe-only pipe name. The roots use the
SAME production ancestors and the SAME layout as a real install, so the ACL
inheritance, the traverse semantics and the deployment identity are the real
ones; only the leaf names are disposable. NO production account, path, service,
ACL, or provider call.

WHAT IT PROVES, in order:
  A  a clean install from clean state produces the intended OS state;
  B  the deployment identity is observed, stable, and version-bound;
  C  import provenance: the deployed runtime imports gnosis from the deployed
     publisher and nothing else, with site disabled;
  D  the adversarial ACL matrix: AS the provisioned worker, every mutating
     access (WRITE/DELETE/RENAME/WRITE_DAC/WRITE_OWNER) against every protected
     category is DENIED, the credential blob is unreadable, and the positive
     controls (read the runtime, write the work root) succeed;
  E  the composed path still works on the provisioned deployment (Director ->
     worker -> publisher -> Anchor v2) and still fails closed on a non-CLEAN
     boundary verdict;
  F  the installer is idempotent; update / failed-update / rollback are
     fail-closed; uninstall leaves no account, service, root or blob behind.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/probe_stage8_provisioning.py

Requires an elevated (Administrator) shell.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import probe_stage5_worker_launcher as s5
import probe_stage6_composition as s6

from gnosis.provision.layout import DeploymentLayout
from gnosis.provision.provisioner import (
    ProvisionConfig,
    Provisioner,
    RealOperations,
    ResolvedSids,
)
from gnosis.trust.anchor import AnchorStore
from gnosis.trust.bundle_verify import write_bundle_manifest
from gnosis.trust.deployment import (
    DesiredDeploymentConfig,
    observe_deployment,
    observe_service,
)
from gnosis.trust.launch_spec import LaunchSpec
from gnosis.trust.orchestration import (
    CompletionEvidence,
    RunNotPublishable,
    RunPlan,
    authorize_publishable,
    create_trusted_run,
)
from gnosis.trust.publication import read_watermark
from gnosis.trust.run_identity import (
    PublicationState,
    TrustedRunIdentityStore,
)
from gnosis.trust.worker_launcher import (
    LaunchedWorkerIdentity,
    TrustedWindowsWorkerLauncher,
    WorkerAccount,
)

say = s5.say

# ---------------------------------------------------------------------------
# Disposable, production-equivalent identifiers.
# ---------------------------------------------------------------------------
CODE_BASE = r"C:\Program Files\GnosisStage8Probe\Trust"
STATE_BASE = r"C:\ProgramData\GnosisStage8Probe\Trust"
WORK_BASE = r"C:\ProgramData\GnosisStage8Probe\Work"
LAUNCH_ROOT = Path(r"C:\ProgramData\GnosisStage8Probe\Launch")
PF_PARENT = Path(r"C:\Program Files\GnosisStage8Probe")
PD_PARENT = Path(r"C:\ProgramData\GnosisStage8Probe")
SERVICE_NAME = "GnosisPubS8Probe"
PIPE_NAME = r"\\.\pipe\gnosis-s8-probe-publish"
WORKER_NAME = "GnosisWkrS8"

DISPOSABLE_ROOTS = (PF_PARENT, PD_PARENT)

# The fixture run's fixed identity (same shape the Stage 6 probe uses so the
# bundle readers in anchor.py accept it).
RUN_OK = "RUN-S8-OK-0001"
RUN_BAD = "RUN-S8-BAD-0001"
HEAD_SHA = "b" * 40
TREE_ID = "c" * 64

# The bootstrap module closure and the publisher closure to deploy FROM.
BOOTSTRAP_CLOSURE = (
    ("gnosis/__init__.py", "gnosis/__init__.py"),
    ("gnosis/kernel/__init__.py", "gnosis/kernel/__init__.py"),
    ("gnosis/kernel/canonical.py", "gnosis/kernel/canonical.py"),
    ("gnosis/kernel/atomic_io.py", "gnosis/kernel/atomic_io.py"),
    ("gnosis/trust/__init__.py", "gnosis/trust/__init__.py"),
    ("gnosis/trust/launch.py", "gnosis/trust/launch.py"),
    ("gnosis/trust/launch_spec.py", "gnosis/trust/launch_spec.py"),
    ("gnosis/trust/bootstrap.py", "gnosis/trust/bootstrap.py"),
)

CHECKS = [0]
FAIL_LOCAL: list[str] = []


def ck(label: str, actual: object, required: object) -> bool:
    CHECKS[0] += 1
    ok = actual == required
    mark = "PASS" if ok else "FAIL"
    say(f"   [{mark}] {label}: {actual!r} (want {required!r})")
    if not ok:
        FAIL_LOCAL.append(label)
        s5.FAILURES.append(f"S8:{label}")
    return ok


def sc(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sc.exe", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def _account_exists(name: str) -> bool:
    from gnosis.provision import winapi
    return winapi.account_exists(name)


# Broad-principal names in the icacls output that must NOT appear on a protected
# root (English + this machine's Spanish locale). Absence == inheritance stripped
# and no broad grant; the adversarial matrix is the authoritative denial proof.
_BROAD_PRINCIPALS = ("Everyone", "Todos", "BUILTIN\\Users", "BUILTIN\\Usuarios",
                     "Authenticated Users", "autentificados")


def _assert_disposable(target: Path) -> None:
    """Refuse to aim a worker mutation at anything outside the probe's roots."""
    resolved = target.resolve()
    for root in DISPOSABLE_ROOTS:
        try:
            resolved.relative_to(root.resolve())
            return
        except ValueError:
            continue
    raise SystemExit(
        f"REFUSING to aim a worker attack at {resolved}: outside the probe's "
        f"disposable roots {[str(r) for r in DISPOSABLE_ROOTS]}.")


# ---------------------------------------------------------------------------
# The worker-side attack helper. Runs AS THE PROVISIONED WORKER; everything it
# manages to do, the worker may do. Pure stdlib so the deployed runtime runs it.
# ---------------------------------------------------------------------------
ATTACK_HELPER = r'''
import json, os, subprocess, sys

def try_write(path):
    try:
        with open(path, "ab") as fh:
            fh.write(b"WORKER-WAS-HERE\n")
        return "WROTE"
    except OSError as exc:
        return "DENIED:%s:%s" % (type(exc).__name__, getattr(exc, "winerror", ""))

def try_delete(path):
    try:
        if os.path.isdir(path):
            os.rmdir(path)
        else:
            os.remove(path)
        return "DELETED"
    except OSError as exc:
        return "DENIED:%s:%s" % (type(exc).__name__, getattr(exc, "winerror", ""))

def try_rename(path):
    try:
        os.rename(path, path + ".rn")
        return "RENAMED"
    except OSError as exc:
        return "DENIED:%s:%s" % (type(exc).__name__, getattr(exc, "winerror", ""))

def try_read(path):
    try:
        with open(path, "rb") as fh:
            data = fh.read(16)
        return "READ:%d" % len(data)
    except OSError as exc:
        return "DENIED:%s:%s" % (type(exc).__name__, getattr(exc, "winerror", ""))

def try_icacls(args):
    proc = subprocess.run(["icacls", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return ("CHANGED" if proc.returncode == 0 else "DENIED:%d" % proc.returncode)

def main():
    mode, out = sys.argv[1], sys.argv[2]
    rest = sys.argv[3:]
    result = {"mode": mode}
    if mode == "write":
        result["outcome"] = try_write(rest[0])
    elif mode == "delete":
        result["outcome"] = try_delete(rest[0])
    elif mode == "rename":
        result["outcome"] = try_rename(rest[0])
    elif mode == "read":
        result["outcome"] = try_read(rest[0])
    elif mode == "writedac":
        result["outcome"] = try_icacls([rest[0], "/grant", "*%s:(F)" % rest[1]])
    elif mode == "writeowner":
        result["outcome"] = try_icacls([rest[0], "/setowner", "*%s" % rest[1]])
    elif mode == "provenance":
        # Runs under the DEPLOYED runtime: report where gnosis resolves.
        import gnosis, gnosis.trust.publisher as pub
        result["executable"] = sys.executable
        result["gnosis_file"] = getattr(gnosis, "__file__", None)
        result["publisher_file"] = getattr(pub, "__file__", None)
        result["path"] = list(sys.path)
        result["site_in_modules"] = ("site" in sys.modules and
                                     getattr(sys.modules.get("site"), "ENABLE_USER_SITE", None) is not None)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    return 0

sys.exit(main())
'''


@dataclass
class Installed:
    prov: Provisioner
    layout: DeploymentLayout
    sids: ResolvedSids
    digest: str
    observed: object
    password: str
    runtime: Path
    tools: Path       # the deployed toolchain root (worker RX) where helpers live
    launcher: TrustedWindowsWorkerLauncher


class _Adapter:
    """Minimal `s5.Probe`-shaped object so `s6.run_as_worker` can drive the
    PROVISIONED worker + runtime for the composition smoke."""

    def __init__(self, tools: Path, work: Path, src: Path,
                 launcher: TrustedWindowsWorkerLauncher) -> None:
        self.tools = tools
        self.work = work
        self.src = src
        self._launcher = launcher

    def launcher(self, director_env: dict[str, str] | None = None
                 ) -> TrustedWindowsWorkerLauncher:
        return self._launcher


def _make_config(layout: DeploymentLayout, version: str, commit: str,
                 tree: str) -> ProvisionConfig:
    return ProvisionConfig(
        layout=layout, service_name=SERVICE_NAME, pipe_name=PIPE_NAME,
        worker_username=WORKER_NAME, package_version=version,
        source_commit=commit, source_tree=tree)


def _make_provisioner(layout: DeploymentLayout, version: str, commit: str,
                      tree: str, toolchain_files: list[tuple[str, str]]
                      ) -> Provisioner:
    publisher_files = [(str(REPO / "src" / rel), rel) for rel in s6.PUBLISHER_CLOSURE]
    bootstrap_files = [(str(REPO / "src" / src), dst) for src, dst in BOOTSTRAP_CLOSURE]
    return Provisioner(
        config=_make_config(layout, version, commit, tree),
        ops=RealOperations(),
        runtime_src=sys.base_prefix,
        publisher_files=publisher_files,
        bootstrap_files=bootstrap_files,
        toolchain_files=toolchain_files)


def _head_commit() -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                          capture_output=True, text=True, check=False)
    return (proc.stdout.strip() or "unknown")


def _clean_state() -> None:
    """Remove any leftover from a previous run before installing."""
    sc("stop", SERVICE_NAME)
    time.sleep(0.5)
    sc("delete", SERVICE_NAME)
    if _account_exists(WORKER_NAME):
        from gnosis.provision import winapi
        winapi.delete_local_account(WORKER_NAME)
    for root in (PF_PARENT, PD_PARENT):
        if root.exists():
            subprocess.run(["icacls", str(root), "/reset", "/T", "/C", "/Q"],
                           capture_output=True, text=True, check=False)
            shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------------------
# A: install
# ---------------------------------------------------------------------------
def install() -> Installed:
    say("=" * 78)
    say("F-17 STAGE 8 — OS-REAL PROVISIONING PROBE")
    say("=" * 78)
    say("")
    say("A. CLEAN INSTALL")
    say("-" * 78)
    _clean_state()

    claude_src = shutil.which("claude")
    toolchain_files: list[tuple[str, str]] = []
    if claude_src and claude_src.lower().endswith(".exe"):
        toolchain_files.append((claude_src, "claude.exe"))
        say(f"   toolchain artifact for provenance: {claude_src}")
    else:
        say("   no claude.exe on PATH; toolchain byte-identity check will note it")

    layout = DeploymentLayout(CODE_BASE, STATE_BASE, WORK_BASE, release_id="R1")
    password = s5.random_password()
    prov = _make_provisioner(layout, "0.0.0-s8-R1", _head_commit(), "R1",
                             toolchain_files)
    say("   installing (create account, deploy code, ACLs, service, observe) ...")
    result = prov.install(password)
    for step in prov.steps:
        say(f"     - {step}")

    runtime = Path(layout.runtime_executable)
    tools = Path(layout.code_release_base) / "toolchain"
    # Place both worker helpers in the toolchain root (worker RX) as maintenance.
    (tools).mkdir(parents=True, exist_ok=True)
    (tools / "attack_s8.py").write_text(ATTACK_HELPER, encoding="utf-8")
    (tools / "worker_s6.py").write_text(s6.WORKER_HELPER, encoding="utf-8")

    LAUNCH_ROOT.mkdir(parents=True, exist_ok=True)
    s5.icacls(str(LAUNCH_ROOT), "/inheritance:r")
    s5.icacls(str(LAUNCH_ROOT), "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
              "*S-1-5-18:(OI)(CI)F", f"*{result.sids.worker}:(OI)(CI)(RX)")

    launcher = TrustedWindowsWorkerLauncher(
        account=WorkerAccount(username=WORKER_NAME, domain=".",
                              expected_sid=result.sids.worker,
                              expected_integrity="Medium"),
        credential_blob_path=Path(layout.secrets_blob),
        launch_root=LAUNCH_ROOT, runtime=runtime,
        director_env=dict(os.environ))

    say("")
    return Installed(prov=prov, layout=layout, sids=result.sids,
                     digest=result.deployment_digest, observed=result.observed,
                     password=password, runtime=runtime, tools=tools,
                     launcher=launcher)


# ---------------------------------------------------------------------------
# A/B: OS state + deployment identity
# ---------------------------------------------------------------------------
def verify_os_state(inst: Installed) -> None:
    say("A/B. OS STATE + DEPLOYMENT IDENTITY")
    say("-" * 78)
    lay = inst.layout

    ck("worker account exists", _account_exists(WORKER_NAME), True)
    q = sc("query", SERVICE_NAME)
    ck("service installed", q.returncode, 0)
    # Read the SID type from the SCM (the raw DWORD), not sc.exe's localized text.
    ck("service SID type is RESTRICTED", observe_service(SERVICE_NAME).sid_type,
       "RESTRICTED")
    ck("service SID resolves (S-1-5-80-*)",
       inst.sids.service.startswith("S-1-5-80-"), True)
    ck("DPAPI credential blob present", Path(lay.secrets_blob).is_file(), True)

    # Every protected root: exists, inheritance stripped, no BUILTIN\Users ACE.
    for spec in lay.roots():
        path = lay.path(spec)
        ck(f"root exists: {spec.key}", Path(path).exists(), True)
        out = subprocess.run(["icacls", path], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", check=False).stdout
        # Inheritance stripped + only specific SIDs granted => no broad principal
        # appears (checked in both this machine's locales).
        ck(f"no broad principal on {spec.key}",
           not any(p in out for p in _BROAD_PRINCIPALS), True)

    # Deployment identity: observe again, expect the SAME digest (stable), and
    # equal to what install committed.
    obs2 = observe_deployment(_desired(lay))
    if obs2.digest() != inst.digest:
        _explain_digest_drift(inst.observed, obs2)
    ck("deployment digest stable across observations", obs2.digest(), inst.digest)
    ck("deployment binds the runtime tree", obs2.binds_runtime_tree, True)
    assert obs2.runtime_tree is not None
    ck("runtime tree is non-trivial (>1000 files)",
       len(obs2.runtime_tree.files) > 1000, True)
    # config.json carries the expected digest the service will require.
    cfg = json.loads(Path(lay.config_path).read_text(encoding="utf-8"))
    ck("config expected_deployment_digest matches install",
       cfg["expected_deployment_digest"], inst.digest)
    ck("config authorized_worker_sid is the worker",
       cfg["authorized_worker_sid"], inst.sids.worker)
    say("")


def _explain_digest_drift(before: object, after: object) -> None:
    """Say WHICH deployment sub-field moved between two observations."""
    da = before.to_dict()  # type: ignore[attr-defined]
    db = after.to_dict()   # type: ignore[attr-defined]
    for key in sorted(set(da) | set(db)):
        if da.get(key) != db.get(key):
            say(f"   DRIFT in deployment field {key!r}:")
            say(f"     install: {json.dumps(da.get(key))[:280]}")
            say(f"     now    : {json.dumps(db.get(key))[:280]}")


def _desired(lay: DeploymentLayout) -> DesiredDeploymentConfig:
    return DesiredDeploymentConfig(
        trust_root=Path(lay.trust_root),
        runtime_executable=Path(lay.runtime_executable),
        runtime_root=Path(lay.runtime_root),
        runidentity_store=Path(lay.runidentity_root),
        anchorstore=Path(lay.anchors_root),
        service_name=SERVICE_NAME)


# ---------------------------------------------------------------------------
# C: import provenance + python._pth
# ---------------------------------------------------------------------------
def verify_import_provenance(inst: Installed) -> None:
    say("C. IMPORT PROVENANCE (deployed runtime + python._pth)")
    say("-" * 78)
    lay = inst.layout
    pth = Path(lay.pth_file)
    ck("python._pth present next to python.exe", pth.is_file(), True)
    text = pth.read_text(encoding="utf-8") if pth.is_file() else ""
    ck("python._pth disables site (no 'import site')",
       "import site" not in text, True)
    ck("python._pth pins the publisher (..\\publisher)",
       "..\\publisher" in text, True)

    # Run the DEPLOYED runtime, isolated, on a provenance probe.
    payload = Path(WORK_BASE) / "provenance.json"
    payload.parent.mkdir(parents=True, exist_ok=True)
    helper = inst.tools / "attack_s8.py"
    # -B so importing gnosis for the provenance check does not drop __pycache__
    # into the measured trust root (which would drift the deployment digest).
    proc = subprocess.run([str(inst.runtime), "-I", "-B", str(helper),
                           "provenance", str(payload)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          check=False)
    if not payload.is_file():
        say(f"   provenance run produced no payload; stderr: {proc.stderr[:300]}")
        ck("import provenance payload produced", False, True)
        say("")
        return
    data = json.loads(payload.read_text(encoding="utf-8"))
    exe = str(data.get("executable", ""))
    gfile = str(data.get("gnosis_file", ""))
    pubfile = str(data.get("publisher_file", ""))
    ck("sys.executable is the deployed runtime",
       _under(exe, lay.runtime_root), True)
    ck("import gnosis resolves under the deployed publisher",
       _under(gfile, lay.trust_root), True)
    ck("import gnosis.trust.publisher resolves under the deployed publisher",
       _under(pubfile, lay.trust_root), True)
    no_site_pkgs = all("site-packages" not in str(p) for p in data.get("path", []))
    ck("no site-packages on sys.path", no_site_pkgs, True)
    say("")


def _under(path: str, root: str) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError):
        return False


# ---------------------------------------------------------------------------
# D: adversarial ACL matrix (AS the provisioned worker)
# ---------------------------------------------------------------------------
def _launch_attack(inst: Installed, launch_id: str, mode: str, *args: str,
                   timeout_s: float = 90.0) -> dict[str, object]:
    if mode in ("write", "delete", "rename"):
        _assert_disposable(Path(args[0]))
    work = Path(WORK_BASE)
    payload = work / f"{launch_id}-result.json"
    if payload.exists():
        payload.unlink()
    helper = inst.tools / "attack_s8.py"
    argv = [str(inst.runtime), "-I", "-B", str(helper), mode, str(payload), *args]
    spec = LaunchSpec(launch_id=launch_id, executable=str(inst.runtime),
                      argv=tuple(argv), cwd=str(work),
                      stdout_path=str(work / f"{launch_id}.out"),
                      stderr_path=str(work / f"{launch_id}.err"),
                      run_id=None)
    res = inst.launcher.launch(spec)
    try:
        code, timed_out, cancelled = res.wait(timeout_s)
    finally:
        identity = res.identity
        res.close()
    data: dict[str, object] = {"exit_code": code, "timed_out": timed_out,
                               "cancelled": cancelled,
                               "observed_sid": identity.observed_sid}
    if payload.is_file():
        data.update(json.loads(payload.read_text(encoding="utf-8")))
    return data


def adversarial_matrix(inst: Installed) -> None:
    say("D. ADVERSARIAL ACL MATRIX (as the provisioned worker)")
    say("-" * 78)
    lay = inst.layout

    # Seed a maintenance-owned file inside each denied directory so the
    # delete/rename/write attempts target a real file the worker must be denied.
    seeds: dict[str, str] = {}
    for key, root in (("anchors", lay.anchors_root),
                      ("runidentity", lay.runidentity_root),
                      ("bundles", lay.bundles_root),
                      ("logs", f"{lay.state_base}\\logs")):
        seed = Path(root) / "_seed.txt"
        seed.parent.mkdir(parents=True, exist_ok=True)
        seed.write_text("maintenance-owned seed\n", encoding="utf-8")
        seeds[key] = str(seed)

    # (label, target file, worker_may_read)
    categories = [
        ("runtime", lay.runtime_executable, True),
        ("publisher", f"{lay.trust_root}\\gnosis\\trust\\publisher.py", False),
        ("bootstrap", f"{lay.code_release_base}\\bootstrap\\gnosis\\trust\\bootstrap.py", True),
        ("toolchain", str(inst.tools / "attack_s8.py"), True),
        ("anchors", seeds["anchors"], False),
        ("runidentity", seeds["runidentity"], False),
        ("bundles", seeds["bundles"], False),
        ("secrets", lay.secrets_blob, False),
        ("state_root", lay.config_path, False),
        ("logs", seeds["logs"], False),
    ]

    n = 0
    for label, target, may_read in categories:
        for verb in ("write", "delete", "rename", "writedac", "writeowner"):
            n += 1
            lid = f"s8-adv-{n}"
            if verb in ("writedac", "writeowner"):
                r = _launch_attack(inst, lid, verb, target, inst.sids.worker)
            else:
                r = _launch_attack(inst, lid, verb, target)
            outcome = str(r.get("outcome", ""))
            ck(f"  {verb} {label} DENIED", outcome.startswith("DENIED"), True)
        # read: denied on no-ACE roots, allowed on RX roots.
        n += 1
        r = _launch_attack(inst, f"s8-adv-{n}", "read", target)
        outcome = str(r.get("outcome", ""))
        if may_read:
            ck(f"  read {label} ALLOWED (RX)", outcome.startswith("READ"), True)
        else:
            ck(f"  read {label} DENIED", outcome.startswith("DENIED"), True)

    # The credential boundary, stated on its own: the worker cannot read the blob.
    r = _launch_attack(inst, "s8-blob", "read", lay.secrets_blob)
    ck("  DPAPI credential blob unreadable by worker",
       str(r.get("outcome", "")).startswith("DENIED"), True)

    # Positive controls: the matrix GRANTS what it must, or a mutant that drops
    # a grant would pass unnoticed.
    workfile = f"{lay.work_base}\\worker_wrote_here.txt"
    r = _launch_attack(inst, "s8-pos-work", "write", workfile)
    ck("  POSITIVE: worker writes its own work root", r.get("outcome"), "WROTE")
    r = _launch_attack(inst, "s8-pos-rt", "read", lay.runtime_executable)
    ck("  POSITIVE: worker reads the runtime it must run",
       str(r.get("outcome", "")).startswith("READ"), True)

    # The worker observed as the intended identity, medium integrity.
    ck("  worker ran as the provisioned SID",
       str(r.get("observed_sid")), inst.sids.worker)
    say("")


# ---------------------------------------------------------------------------
# E: composition smoke on the provisioned deployment
# ---------------------------------------------------------------------------
def _composition_adapter(inst: Installed) -> s6.Composition:
    adapter = _Adapter(tools=inst.tools, work=Path(WORK_BASE),
                       src=Path(inst.layout.trust_root), launcher=inst.launcher)
    return s6.Composition(
        s5probe=adapter, state_root=Path(inst.layout.state_base),
        evidence_root=Path(inst.layout.bundles_root),
        config_path=Path(inst.layout.config_path),
        log_path=Path(inst.layout.log_path), service_sid=inst.sids.service,
        worker_sid=inst.sids.worker, runtime=inst.runtime,
        deployment_digest=inst.digest, observed=inst.observed)


def _start_service(inst: Installed) -> bool:
    r = sc("start", SERVICE_NAME)
    say(f"   sc start rc={r.returncode} {(r.stdout + r.stderr).strip()[:160]}")
    for _ in range(60):
        if "RUNNING" in sc("query", SERVICE_NAME).stdout:
            return True
        time.sleep(0.25)
    log = Path(inst.layout.log_path)
    if log.is_file():
        say("   --- publisher log tail ---")
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]:
            say(f"     {line}")
    return False


def _seed_run(inst: Installed, comp: s6.Composition, run_id: str,
              verdict: str) -> LaunchedWorkerIdentity:
    """Create a trusted run whose AUTHORITATIVE bundle (worker-denied `bundles`)
    is written by maintenance with the given boundary verdict."""
    run_store = TrustedRunIdentityStore(Path(inst.layout.runidentity_root))
    bundle = Path(inst.layout.bundles_root) / run_id
    # The worker produces a CANDIDATE in its Work root (proves a real sealed
    # launch + observed SID); the authoritative bundle is trusted-written.
    candidate = f"{inst.layout.work_base}\\candidate-{run_id}"
    produced = s6.run_as_worker(comp, f"s8-work-{run_id[-4:]}", "work",
                                candidate, HEAD_SHA, TREE_ID, run_id=run_id)
    ck(f"  candidate worker exit ({run_id})", produced.get("exit_code"), 0)
    launch_digest = str(produced.get("launch_spec_digest"))

    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "SUMMARY.json").write_text(json.dumps({
        "tree_identity": {"post": {"fingerprint": {"head_sha": HEAD_SHA}}},
        "boundary": {"verdict": verdict,
                     "protection": {"content_digest": TREE_ID}},
    }), encoding="utf-8")
    write_bundle_manifest(bundle)

    deployment = observe_deployment(_desired(inst.layout))
    launched = LaunchedWorkerIdentity(
        pid=0, observed_sid=str(produced.get("observed_sid")),
        integrity="Medium", is_administrator=False, dangerous_privileges=(),
        launch_spec_digest=launch_digest, logical_command_digest="0" * 64,
        transport_command_length=0, contained_in_job=True)
    plan = RunPlan(task_id="F-17", run_id=run_id, repository_id="gnosis",
                   head_sha=HEAD_SHA, tree_identity=TREE_ID,
                   bundle_path=str(bundle), epoch=0)
    spec = LaunchSpec(launch_id=f"s8-{run_id[-4:]}", executable=str(inst.runtime),
                      argv=(str(inst.runtime),), cwd=str(inst.layout.state_base),
                      stdout_path=f"{inst.layout.state_base}\\o.txt",
                      stderr_path=f"{inst.layout.state_base}\\e.txt", run_id=run_id)
    create_trusted_run(run_store, plan, spec=spec, deployment=deployment,
                       launched=launched)
    return launched


def composition_smoke(inst: Installed) -> None:
    say("E. COMPOSITION SMOKE (Director -> worker -> publisher -> Anchor v2)")
    say("-" * 78)
    if not _start_service(inst):
        ck("  service reached RUNNING", False, True)
        return
    ck("  service reached RUNNING", True, True)
    comp = _composition_adapter(inst)
    run_store = TrustedRunIdentityStore(Path(inst.layout.runidentity_root))

    # --- happy path (CLEAN) ---
    self_launched = _seed_run(inst, comp, RUN_OK, "CLEAN")
    _ = self_launched
    identity = run_store.read(RUN_OK).identity
    early = s6.run_as_worker(comp, "s8-early", "publish", PIPE_NAME,
                             f"PUBLISH {RUN_OK}")
    ck("  publish before publishable is refused",
       str(early.get("reply", "")).startswith("REJECTED:"), True)
    gated = authorize_publishable(
        run_store, identity,
        CompletionEvidence(exit_code=0, timed_out=False, cancelled=False,
                           bundle_dir=Path(inst.layout.bundles_root) / RUN_OK))
    ck("  trusted gate marked it PUBLISHABLE", gated.publication_state,
       PublicationState.PUBLISHABLE)
    published = s6.run_as_worker(comp, "s8-pub", "publish", PIPE_NAME,
                                 f"PUBLISH {RUN_OK}")
    reply = str(published.get("reply", ""))
    say(f"   publish reply: {reply}")
    ck("  publication ANCHORED", reply.startswith("ANCHORED:"), True)

    store = AnchorStore(Path(inst.layout.anchors_root), require_high=False)
    anchor = store.lookup(RUN_OK)
    ck("  anchor record exists", anchor is not None, True)
    if anchor is not None:
        ck("  anchor schema is V2", anchor.schema, "gnosis.anchor.v2")
        ck("  anchor binds the deployment", anchor.deployment_digest, inst.digest)
    wm = read_watermark(Path(inst.layout.anchors_root))
    ck("  watermark committed", wm is not None and wm.committed_seq >= 0, True)

    # --- fail closed (non-CLEAN boundary verdict) ---
    _seed_run(inst, comp, RUN_BAD, "MACHINERY_UNQUALIFIED")
    bad_identity = run_store.read(RUN_BAD).identity
    refused_at_gate = False
    try:
        authorize_publishable(
            run_store, bad_identity,
            CompletionEvidence(exit_code=0, timed_out=False, cancelled=False,
                               bundle_dir=Path(inst.layout.bundles_root) / RUN_BAD))
    except RunNotPublishable:
        refused_at_gate = True
    ck("  non-CLEAN verdict refused at the trusted gate", refused_at_gate, True)
    bad_pub = s6.run_as_worker(comp, "s8-badpub", "publish", PIPE_NAME,
                               f"PUBLISH {RUN_BAD}")
    ck("  service refuses to anchor the non-CLEAN run",
       str(bad_pub.get("reply", "")).startswith("REJECTED:"), True)
    ck("  no anchor for the non-CLEAN run", store.lookup(RUN_BAD) is None, True)

    # Worker cannot squat the trusted pipe.
    squat = s6.run_as_worker(comp, "s8-squat", "createpipe", PIPE_NAME)
    ck("  worker cannot create the trusted pipe",
       str(squat.get("outcome", "")).startswith("DENIED"), True)
    say("")


# ---------------------------------------------------------------------------
# F: idempotence + update / failed-update / rollback + uninstall
# ---------------------------------------------------------------------------
def idempotence(inst: Installed) -> None:
    say("F1. IDEMPOTENCE (re-run the installer)")
    say("-" * 78)
    sc("stop", SERVICE_NAME)
    time.sleep(0.5)
    before = _acl_snapshot(inst.layout)
    prov2 = _make_provisioner(inst.layout, "0.0.0-s8-R1", _head_commit(), "R1",
                              _toolchain_files())
    result = prov2.install(inst.password)
    ck("  re-install reused the worker account (SID stable)",
       result.sids.worker, inst.sids.worker)
    ck("  re-install digest stable", result.deployment_digest, inst.digest)
    after = _acl_snapshot(inst.layout)
    ck("  ACLs did not broaden on re-run", after, before)
    # exactly one account, one service
    accounts = subprocess.run(["net", "user"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", check=False).stdout
    ck("  exactly one worker account", accounts.count(WORKER_NAME), 1)
    say("")


def _acl_snapshot(lay: DeploymentLayout) -> dict[str, str]:
    snap: dict[str, str] = {}
    for spec in lay.roots():
        out = subprocess.run(["icacls", lay.path(spec)], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             check=False).stdout
        # Normalise away the trailing "Successfully processed" summary line.
        snap[spec.key] = "\n".join(
            ln for ln in out.splitlines() if "Successfully processed" not in ln)
    return snap


def _toolchain_files() -> list[tuple[str, str]]:
    claude_src = shutil.which("claude")
    if claude_src and claude_src.lower().endswith(".exe"):
        return [(claude_src, "claude.exe")]
    return []


def update_rollback(inst: Installed) -> None:
    say("F2. UPDATE / FAILED-UPDATE / ROLLBACK (versioned releases)")
    say("-" * 78)

    # --- UPDATE to R2 (version bump => digest must change) ---
    lay2 = DeploymentLayout(CODE_BASE, STATE_BASE, WORK_BASE, release_id="R2")
    prov2 = _make_provisioner(lay2, "0.0.0-s8-R2", _head_commit(), "R2",
                              _toolchain_files())
    prov2.stage_release(lay2, inst.sids)
    ok2, _reason2 = prov2.verify_release(lay2)
    ck("  staged R2 verifies", ok2, True)
    sc("stop", SERVICE_NAME)
    time.sleep(0.5)
    digest2, _obs2 = prov2.activate_release(lay2, inst.sids)
    ck("  R2 digest differs from R1 (new code is really active)",
       digest2 != inst.digest, True)
    binpath = sc("qc", SERVICE_NAME).stdout
    ck("  service ImagePath points at R2",
       "releases\\R2\\" in binpath or "releases\\\\R2\\\\" in binpath, True)
    ck("  R1 release still present (for rollback)",
       Path(inst.layout.runtime_executable).exists(), True)
    started2 = _start_service(inst) if True else False
    ck("  service runs on R2", started2, True)

    # --- FAILED UPDATE: a broken R3 must not activate ---
    lay3 = DeploymentLayout(CODE_BASE, STATE_BASE, WORK_BASE, release_id="R3broken")
    prov3 = _make_provisioner(lay3, "0.0.0-s8-R3", _head_commit(), "R3",
                              _toolchain_files())
    prov3.stage_release(lay3, inst.sids)
    # Corrupt the staged release: remove the service entry point.
    Path(lay3.service_entry).unlink(missing_ok=True)
    ok3, reason3 = prov3.verify_release(lay3)
    say(f"   R3 verify: ok={ok3} reason={reason3}")
    ck("  broken R3 fails verification (not activated)", ok3, False)
    binpath_after = sc("qc", SERVICE_NAME).stdout
    ck("  service STILL points at R2 after the failed update",
       "R3broken" not in binpath_after, True)
    ck("  service still RUNNING after the failed update",
       "RUNNING" in sc("query", SERVICE_NAME).stdout, True)

    # --- ROLLBACK to R1 ---
    sc("stop", SERVICE_NAME)
    time.sleep(0.5)
    digest1b, _obs1b = prov2.activate_release(inst.layout, inst.sids)
    ck("  rollback recomputes the original R1 digest", digest1b, inst.digest)
    binpath_rb = sc("qc", SERVICE_NAME).stdout
    ck("  service ImagePath points at R1 after rollback",
       "releases\\R1\\" in binpath_rb or "releases\\\\R1\\\\" in binpath_rb, True)
    ck("  service runs on R1 after rollback", _start_service(inst), True)
    say("")


def uninstall_and_postcheck(inst: Installed) -> None:
    say("F3. UNINSTALL + OS POST-CHECK")
    say("-" * 78)
    inst.prov.uninstall(remove_worker=True)
    for step in inst.prov.steps[-1:]:
        say(f"     - {step}")
    ck("  service absent (query rc 1060)", sc("query", SERVICE_NAME).returncode, 1060)
    ck("  worker account absent", not _account_exists(WORKER_NAME), True)
    ck("  code base removed", Path(CODE_BASE).exists(), False)
    ck("  state base removed", Path(STATE_BASE).exists(), False)
    ck("  work base removed", Path(WORK_BASE).exists(), False)
    ck("  credential blob removed", Path(inst.layout.secrets_blob).exists(), False)
    say("")


def final_rollback() -> None:
    say("ROLLBACK — remove every disposable artifact")
    say("-" * 78)
    sc("stop", SERVICE_NAME)
    time.sleep(0.5)
    sc("delete", SERVICE_NAME)
    if _account_exists(WORKER_NAME):
        from gnosis.provision import winapi
        rc = winapi.delete_local_account(WORKER_NAME)
        say(f"   worker account deleted (rc={rc})")
    for root in (PF_PARENT, PD_PARENT):
        if root.exists():
            subprocess.run(["icacls", str(root), "/reset", "/T", "/C", "/Q"],
                           capture_output=True, text=True, check=False)
            shutil.rmtree(root, ignore_errors=True)
        say(f"   {root} removed: {not root.exists()}")
    say("")


MINIMUM_CHECKS = 70


def main() -> int:
    inst: Installed | None = None
    try:
        inst = install()
        verify_os_state(inst)
        verify_import_provenance(inst)
        adversarial_matrix(inst)
        composition_smoke(inst)
        idempotence(inst)
        update_rollback(inst)
        uninstall_and_postcheck(inst)
    except BaseException as exc:  # noqa: BLE001 - a probe reports, never crashes silently
        import traceback
        say("")
        say(f"PROBE ABORTED: {type(exc).__name__}: {exc}")
        say(traceback.format_exc())
        s5.FAILURES.append(f"S8:aborted:{type(exc).__name__}")
    finally:
        try:
            final_rollback()
        except BaseException as exc:  # noqa: BLE001
            say(f"   rollback error: {exc}")

    say("=" * 78)
    checked = CHECKS[0]
    if s5.FAILURES:
        say(f"PROBE RESULT: {len(s5.FAILURES)} FAILURE(S) over {checked} checks")
        for f in s5.FAILURES:
            say(f"   - {f}")
        return 1
    if checked < MINIMUM_CHECKS:
        say(f"PROBE RESULT: INCONCLUSIVE — only {checked} checks ran "
            f"(at least {MINIMUM_CHECKS} expected)")
        return 2
    say(f"PROBE RESULT: ALL {checked} CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
