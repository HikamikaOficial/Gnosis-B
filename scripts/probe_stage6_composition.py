"""F-17 Stage 6 — OS-real composition probe.

Everything the unit tests assert about the composed path, asserted again against
a REAL Windows service with a REAL restricted service SID, a REAL dedicated
worker account, and a REAL named pipe between them.

WHAT IS DISPOSABLE. All of it. A probe-only worker account, a probe-only
service, probe-only roots under `C:\\ProgramData\\Gnosis\\TrustProbe6`, a
probe-only pipe name, and ACLs applied ONLY under those roots and to that
service. No production account, no production path, no production service, no
production ACL, and no provider call.

WHY IT REUSES THE STAGE 5 PROBE. The dedicated-worker infrastructure - the
account, the DPAPI credential, the copied runtime, the read-only tool root -
was already built and qualified there. Rebuilding it here would be a second
implementation of a thing whose correctness matters, so this imports it.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/probe_stage6_composition.py
"""
from __future__ import annotations

import json
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
    RunPlan,
    authorize_publishable,
    create_trusted_run,
)
from gnosis.trust.publication import read_watermark
from gnosis.trust.publisher_service import SERVICE_CONFIG_SCHEMA
from gnosis.trust.run_identity import (
    PublicationState,
    TrustedRunIdentityStore,
)

SERVICE_NAME = "GnosisPubS6Probe"
PIPE_NAME = r"\\.\pipe\gnosis-s6-probe-publish"
STATE_ROOT = Path(r"C:\ProgramData\Gnosis\TrustProbe6")
# The happy path and the adversarial matrix together assert well over this
# many properties; anything less means the probe stopped early.
MINIMUM_CHECKS = 40

say = s5.say
check = s5.check


# ---------------------------------------------------------------------------
# The worker-side helper. Runs AS THE WORKER, under the Stage 5 launcher.
# ---------------------------------------------------------------------------
WORKER_HELPER = r'''
"""Runs as the dedicated Worker. Everything it does, the Worker may do."""
import ctypes, json, sys
from ctypes import wintypes as W

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
INVALID = W.HANDLE(-1).value
# The exact rights the pipe DACL grants: read data, write data, read attrs,
# read control, synchronize. Deliberately NOT GENERIC_WRITE, whose append bit
# is FILE_CREATE_PIPE_INSTANCE and which the DACL therefore refuses.
WORKER_ACCESS = 0x00120083
OPEN_EXISTING = 3

k32.CreateFileW.restype = W.HANDLE
k32.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, ctypes.c_void_p,
                            W.DWORD, W.DWORD, W.HANDLE]
k32.CreateNamedPipeW.restype = W.HANDLE
k32.CreateNamedPipeW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.DWORD, W.DWORD,
                                 W.DWORD, W.DWORD, ctypes.c_void_p]
k32.ReadFile.argtypes = [W.HANDLE, ctypes.c_void_p, W.DWORD,
                         ctypes.POINTER(W.DWORD), ctypes.c_void_p]
k32.WriteFile.argtypes = [W.HANDLE, ctypes.c_void_p, W.DWORD,
                          ctypes.POINTER(W.DWORD), ctypes.c_void_p]
k32.CloseHandle.argtypes = [W.HANDLE]
k32.OpenProcess.restype = W.HANDLE
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]


def send(pipe, message):
    handle = k32.CreateFileW(pipe, WORKER_ACCESS, 0, None, OPEN_EXISTING, 0, None)
    if handle in (INVALID, None, 0):
        return {"opened": False, "error": ctypes.get_last_error(), "reply": None}
    try:
        raw = message.encode("utf-8")
        written = W.DWORD(0)
        if not k32.WriteFile(handle, raw, len(raw), ctypes.byref(written), None):
            return {"opened": True, "error": ctypes.get_last_error(), "reply": None}
        buf = ctypes.create_string_buffer(4096)
        read = W.DWORD(0)
        if not k32.ReadFile(handle, buf, 4096, ctypes.byref(read), None):
            return {"opened": True, "error": ctypes.get_last_error(), "reply": None}
        return {"opened": True, "error": 0,
                "reply": buf.raw[:read.value].decode("utf-8", "replace")}
    finally:
        k32.CloseHandle(handle)


def try_write(path, data):
    try:
        with open(path, "ab") as fh:
            fh.write(data)
        return "WROTE"
    except OSError as exc:
        return f"DENIED:{type(exc).__name__}:{getattr(exc, 'winerror', '')}"


def try_create_pipe(name):
    handle = k32.CreateNamedPipeW(name, 0x00000003, 0x00000004, 1, 512, 512, 0, None)
    if handle in (INVALID, None, 0):
        return f"DENIED:{ctypes.get_last_error()}"
    k32.CloseHandle(handle)
    return "CREATED"


def try_open_process(pid, access):
    handle = k32.OpenProcess(access, False, pid)
    if handle in (INVALID, None, 0):
        return f"DENIED:{ctypes.get_last_error()}"
    k32.CloseHandle(handle)
    return "OPENED"


def main():
    mode, out = sys.argv[1], sys.argv[2]
    rest = sys.argv[3:]
    result = {"mode": mode}
    if mode == "publish":
        result.update(send(rest[0], rest[1]))
    elif mode == "write":
        result["outcome"] = try_write(rest[0], b"WORKER-WAS-HERE\n")
    elif mode == "createpipe":
        result["outcome"] = try_create_pipe(rest[0])
    elif mode == "openprocess":
        result["outcome"] = try_open_process(int(rest[0]), int(rest[1], 16))
    elif mode == "service":
        import subprocess as sp
        proc = sp.run(rest, capture_output=True, text=True,
                      encoding="utf-8", errors="replace")
        result["rc"] = proc.returncode
        result["out"] = (proc.stdout + proc.stderr)[:400]
    elif mode == "work":
        # The fixture run itself: produce the bundle the Director will gate on.
        from pathlib import Path as P
        bundle = P(rest[0])
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "SUMMARY.json").write_text(json.dumps({
            "tree_identity": {"post": {"fingerprint": {"head_sha": rest[1]}}},
            "boundary": {"verdict": "CLEAN", "protection": {"content_digest": rest[2]}},
        }), encoding="utf-8")
        result["bundle"] = str(bundle)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    return 0


sys.exit(main())
'''


def sc(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sc.exe", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


@dataclass
class Composition:
    s5probe: object
    state_root: Path
    evidence_root: Path
    config_path: Path
    log_path: Path
    service_sid: str
    worker_sid: str
    runtime: Path
    deployment_digest: str
    observed: object


def _worker_helper_path(s5probe: object) -> Path:
    tools = s5probe.tools  # type: ignore[attr-defined]
    path = tools / "worker_s6.py"
    path.write_text(WORKER_HELPER, encoding="utf-8")
    return path


DISPOSABLE_ROOTS = (STATE_ROOT, s5.PROBE_ROOT)


def _assert_disposable(target: Path) -> None:
    """Refuse to point a WRITE attempt at anything that is not disposable.

    THIS GUARD EXISTS BECAUSE THE PROBE ONCE DAMAGED THE REPOSITORY. An earlier
    revision aimed the "can the Worker write the service script?" check at
    `src/gnosis/trust/publisher_service.py` in the CHECKOUT rather than at the
    deployed copy. The Worker could write it - the checkout lives under a path
    whose inherited permissions include Users - so the attack succeeded, a line
    of marker text was appended to real source, and the next run failed to
    import.

    The lesson is not "fix that one path". A probe that runs real attacks with
    real credentials must be unable to aim them outside its own disposable
    roots, so the target is checked here rather than trusted at each call site.
    """
    resolved = target.resolve()
    for root in DISPOSABLE_ROOTS:
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        return
    raise SystemExit(
        f"REFUSING to aim a worker write at {resolved}: it is outside the "
        f"probe's disposable roots {[str(r) for r in DISPOSABLE_ROOTS]}. "
        "A probe that can damage the checkout is a defect, not a test.")


def run_as_worker(comp: Composition, launch_id: str, mode: str,
                  *args: str, timeout_s: float = 120.0,
                  run_id: str | None = None) -> dict[str, object]:
    """Run the Stage-6 helper AS THE WORKER, through the Stage 5 launcher."""
    if mode == "write":
        _assert_disposable(Path(args[0]))
    s5probe = comp.s5probe
    work = s5probe.work  # type: ignore[attr-defined]
    payload = work / f"{launch_id}-result.json"
    if payload.exists():
        payload.unlink()
    helper = s5probe.tools / "worker_s6.py"  # type: ignore[attr-defined]
    argv = [str(comp.runtime), "-I", str(helper), mode, str(payload), *args]
    spec = LaunchSpec(launch_id=launch_id, executable=str(comp.runtime),
                      argv=tuple(argv), cwd=str(work),
                      stdout_path=str(work / f"{launch_id}.out"),
                      stderr_path=str(work / f"{launch_id}.err"),
                      run_id=run_id)
    result = s5probe.launcher().launch(spec)  # type: ignore[attr-defined]
    try:
        code, timed_out, cancelled = result.wait(timeout_s)
    finally:
        identity = result.identity
        result.close()
    data: dict[str, object] = {"exit_code": code, "timed_out": timed_out,
                               "cancelled": cancelled,
                               "observed_sid": identity.observed_sid,
                               "launch_spec_digest": identity.launch_spec_digest}
    if payload.is_file():
        data.update(json.loads(payload.read_text(encoding="utf-8")))
    return data


PUBLISHER_CLOSURE = (
    "gnosis/__init__.py",
    "gnosis/kernel/__init__.py",
    "gnosis/kernel/canonical.py",
    "gnosis/kernel/atomic_io.py",
    "gnosis/kernel/file_lock.py",
    "gnosis/trust/__init__.py",
    "gnosis/trust/anchor.py",
    "gnosis/trust/bundle_verify.py",
    "gnosis/trust/launch.py",
    "gnosis/trust/pipe_server.py",
    "gnosis/trust/publication.py",
    "gnosis/trust/publisher.py",
    "gnosis/trust/publisher_service.py",
    "gnosis/trust/run_identity.py",
    "gnosis/trust/service_host.py",
)


def deploy_publisher(trust_root: Path) -> None:
    """Copy the publisher's OWN closure into the deployed trust root.

    The service must run the DEPLOYED bytes, not the repository: an image path
    pointing at a developer working tree would be a service whose code lives
    somewhere the deployment identity does not measure and the ACLs do not
    protect. Copying the closure is also what lets `observe_trust_package`
    measure the publisher itself into `deployment_digest`.
    """
    for rel in PUBLISHER_CLOSURE:
        dest = trust_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / "src" / rel, dest)
    # The entry point lives AT the trust root, so `python -I <root>/service_main.py`
    # puts the root itself on sys.path[0] and the deployed package imports
    # cleanly without PYTHONPATH - which the Worker's environment could set.
    (trust_root / "service_main.py").write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
        "from gnosis.trust.publisher_service import main\n"
        "raise SystemExit(main(sys.argv))\n",
        encoding="utf-8")
    # `observe_trust_package` reads its version/commit/tree claims FROM the
    # deployed package. They are CLAIMS - the digest binds the bytes.
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                          capture_output=True, text=True, check=False)
    (trust_root / "PACKAGE.json").write_text(json.dumps({
        "schema": "gnosis.trust.package.v1",
        "package_version": "0.0.0-s6-probe",
        "source_commit": (head.stdout.strip() or "unknown"),
        "source_tree": "probe-deployment",
    }, indent=2), encoding="utf-8")


def write_pipe_policy(trust_root: Path, worker_sid: str, service_sid: str) -> str:
    """Record the pipe policy the service will actually use.

    Written AFTER the service exists, because the SDDL names the service SID,
    and written with the SAME `worker_pipe_sddl` the server calls at runtime -
    a policy file that could drift from the code it describes would bind a
    deployment identity to a pipe nobody serves.
    """
    from gnosis.trust.pipe_server import worker_pipe_sddl
    sddl = worker_pipe_sddl(worker_sid, service_sid)
    (trust_root / "PIPE_POLICY.json").write_text(json.dumps({
        "schema_version": "gnosis.trust.pipe_policy.v1",
        "name": PIPE_NAME,
        "sddl": sddl,
        "flags": ["FILE_FLAG_FIRST_PIPE_INSTANCE", "PIPE_REJECT_REMOTE_CLIENTS",
                  "PIPE_TYPE_MESSAGE", "MAX_INSTANCES=1"],
    }, indent=2), encoding="utf-8")
    return sddl


def install_service(comp_runtime: Path, trust_root: Path,
                    config_path: Path) -> str:
    """Install the publisher as a real service with a RESTRICTED service SID."""
    service_script = trust_root / "service_main.py"
    # `-I` isolates the interpreter; PYTHONPATH is not used, so the deployed
    # trust root is put on sys.path by the script's own location instead.
    binary = (f'"{comp_runtime}" -I "{service_script}" "{config_path}"')
    say(f"   sc create {SERVICE_NAME} ...")
    created = sc("create", SERVICE_NAME, "binPath=", binary, "type=", "own",
                 "start=", "demand", "obj=", f"NT SERVICE\\{SERVICE_NAME}")
    say(f"   create rc={created.returncode} {created.stdout.strip()[:120]}")
    say(f"   sc sidtype {SERVICE_NAME} restricted ...")
    sidtype = sc("sidtype", SERVICE_NAME, "restricted")
    say(f"   sidtype rc={sidtype.returncode} {sidtype.stdout.strip()[:120]}")
    return s5.resolve_sid(f"NT SERVICE\\{SERVICE_NAME}")


def setup() -> Composition:
    say("=" * 78)
    say("F-17 STAGE 6 — OS-REAL COMPOSITION PROBE")
    say("=" * 78)
    say("")

    password = s5.random_password()
    s5probe = s5.setup(password)

    say("SETUP — Stage 6 additions")
    say("-" * 78)
    if STATE_ROOT.exists():
        shutil.rmtree(STATE_ROOT, ignore_errors=True)
    evidence_root = STATE_ROOT / "evidence"
    for path in (STATE_ROOT, evidence_root, STATE_ROOT / "anchors",
                 STATE_ROOT / "runidentity"):
        path.mkdir(parents=True, exist_ok=True)

    _worker_helper_path(s5probe)
    config_path = STATE_ROOT / "publisher.json"
    log_path = STATE_ROOT / "publisher.log"

    runtime = s5probe.runtime  # type: ignore[attr-defined]
    deploy_publisher(s5probe.src)  # type: ignore[attr-defined]
    service_sid = install_service(runtime, s5probe.src, config_path)  # type: ignore[attr-defined]
    say(f"   service SID: {service_sid}")

    worker_sid = s5probe.worker_sid  # type: ignore[attr-defined]
    sddl = write_pipe_policy(s5probe.src, worker_sid, service_sid)  # type: ignore[attr-defined]
    say(f"   pipe SDDL: {sddl}")

    # ACLS BEFORE OBSERVATION, DELIBERATELY. `deployment_digest` binds the
    # observed security of these paths, so measuring them before provisioning
    # finishes would bind a state the service never runs under.
    say("   applying probe-only ACLs ...")
    # THE SERVICE MUST BE ABLE TO READ ITS OWN CODE. The Stage 5 tool root
    # grants Administrators, SYSTEM and the WORKER - and nothing else - so the
    # first run of this probe failed with `sc start rc=5` (ACCESS_DENIED): the
    # service identity could not read the interpreter it was told to run. That
    # is a real provisioning requirement, found OS-real, and Stage 8 owes it
    # for the production layout too.
    tools = s5probe.tools  # type: ignore[attr-defined]
    s5.icacls(str(tools), "/grant:r", f"*{service_sid}:(OI)(CI)(RX)")
    # The trust state: the service writes, the worker gets NOTHING.
    s5.icacls(str(STATE_ROOT), "/inheritance:r")
    s5.icacls(str(STATE_ROOT), "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
              "*S-1-5-18:(OI)(CI)F", f"*{service_sid}:(OI)(CI)F")
    # The evidence root: the worker WRITES its bundle there, the service reads.
    s5.icacls(str(evidence_root), "/inheritance:r")
    s5.icacls(str(evidence_root), "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
              "*S-1-5-18:(OI)(CI)F", f"*{service_sid}:(OI)(CI)F",
              f"*{worker_sid}:(OI)(CI)M")

    say("   observing the deployment (V2: the runtime as a TREE) ...")
    deployment = observe_deployment(DesiredDeploymentConfig(
        trust_root=s5probe.src,  # type: ignore[attr-defined]
        runtime_executable=runtime,
        runtime_root=runtime.parent,
        runidentity_store=STATE_ROOT / "runidentity",
        anchorstore=STATE_ROOT / "anchors",
        service_name=SERVICE_NAME))
    digest = deployment.digest()
    say(f"   deployment_digest: {digest}")
    assert deployment.runtime_tree is not None
    say(f"   runtime tree files: {len(deployment.runtime_tree.files)}")

    config_path.write_text(json.dumps({
        "schema": SERVICE_CONFIG_SCHEMA,
        "service_name": SERVICE_NAME,
        "pipe_name": PIPE_NAME,
        "service_sid": service_sid,
        "trust_state_root": str(STATE_ROOT),
        "evidence_root": str(evidence_root),
        "authorized_worker_sid": worker_sid,
        "expected_deployment_digest": digest,
        "log_path": str(log_path),
    }, indent=2), encoding="utf-8")

    say("")
    return Composition(s5probe=s5probe, state_root=STATE_ROOT,
                       evidence_root=evidence_root, config_path=config_path,
                       log_path=log_path, service_sid=service_sid,
                       worker_sid=worker_sid, runtime=runtime,
                       deployment_digest=digest, observed=deployment)


def start_service(log_path: Path | None = None) -> bool:
    result = sc("start", SERVICE_NAME)
    say(f"   sc start rc={result.returncode}")
    if result.returncode != 0:
        say(f"   sc start said: {(result.stdout + result.stderr).strip()[:300]}")
    for _ in range(40):
        query = sc("query", SERVICE_NAME)
        if "RUNNING" in query.stdout:
            return True
        time.sleep(0.25)
    say(f"   service did not reach RUNNING: {sc('query', SERVICE_NAME).stdout[:300]}")
    # The service's own log is the only place its refusal is explained; without
    # it a start failure is an error code and a guess.
    if log_path is not None and log_path.is_file():
        say("   --- publisher log ---")
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]:
            say(f"   {line}")
    else:
        say("   (the service wrote no log at all: it failed before its first line)")
    return False


def rollback(comp: Composition | None) -> None:
    say("")
    say("ROLLBACK")
    say("-" * 78)
    stopped = sc("stop", SERVICE_NAME)
    say(f"   sc stop rc={stopped.returncode}")
    time.sleep(1.0)
    deleted = sc("delete", SERVICE_NAME)
    say(f"   sc delete rc={deleted.returncode}")
    gone = sc("query", SERVICE_NAME)
    check("service absent (query rc 1060 means gone)", gone.returncode, 1060)
    if STATE_ROOT.exists():
        shutil.rmtree(STATE_ROOT, ignore_errors=True)
    check("stage 6 state root removed", STATE_ROOT.exists(), False)
    if comp is not None:
        s5.rollback(comp.s5probe)  # type: ignore[arg-type]
    else:
        s5.rollback(None)


RUN_ID = "RUN-S6-PROBE-0001"
HEAD_SHA = "b" * 40
TREE_ID = "c" * 64


def _explain_deployment_drift(comp: Composition, now: object) -> None:
    """Say WHICH component moved, instead of leaving a digest mismatch.

    A deployment digest that changes between two observations of a machine
    nobody reconfigured is either a real drift or a measurement that binds
    something incidental. Both matter, and neither is diagnosable from the hash.
    """
    say("   *** the deployment digest moved; comparing component by component")
    before = comp.observed
    for name in ("package", "runtime", "service", "trust_root",
                 "runidentity_store", "anchorstore", "pipe_policy",
                 "runtime_tree"):
        old = getattr(before, name, None)
        new = getattr(now, name, None)
        if old is None and new is None:
            continue
        same = (old.to_dict() == new.to_dict()) if (old and new) else (old is new)
        say(f"      {name:<20s} {'unchanged' if same else 'CHANGED'}")
        if same:
            continue
        old_files = {f.path: f.digest for f in getattr(old, "files", ())}
        new_files = {f.path: f.digest for f in getattr(new, "files", ())}
        if not old_files and not new_files:
            continue
        added = sorted(set(new_files) - set(old_files))
        removed = sorted(set(old_files) - set(new_files))
        changed = sorted(p for p in set(old_files) & set(new_files)
                         if old_files[p] != new_files[p])
        say(f"         added   ({len(added)}): {added[:8]}")
        say(f"         removed ({len(removed)}): {removed[:8]}")
        say(f"         changed ({len(changed)}): {changed[:8]}")


def happy_path(comp: Composition) -> str | None:
    """The full path, in the order the design requires. Returns the run id."""
    say("HAPPY PATH — trusted Director -> Worker -> Publisher -> Anchor v2")
    say("-" * 78)
    run_store = TrustedRunIdentityStore(comp.state_root / "runidentity")
    bundle = comp.evidence_root / RUN_ID

    # 3-6. The Worker runs, launched through the Stage 5 launcher, under a
    # LaunchSpec sealed for THIS run.
    produced = run_as_worker(comp, "s6-work", "work", str(bundle), HEAD_SHA,
                             TREE_ID, run_id=RUN_ID)
    check("fixture worker exit code", produced.get("exit_code"), 0)
    check("worker SID observed", produced.get("observed_sid"), comp.worker_sid)
    launch_digest = str(produced.get("launch_spec_digest"))
    say(f"   launch_spec_digest : {launch_digest}")
    check("bundle produced by the worker", bundle.is_dir(), True)

    # The trusted side seals the bundle. A worker-written manifest would be a
    # worker-controlled statement about worker-controlled bytes.
    write_bundle_manifest(bundle)

    # 7. The immutable identity, from OBSERVED values only.
    deployment = observe_deployment(DesiredDeploymentConfig(
        trust_root=comp.s5probe.src,  # type: ignore[attr-defined]
        runtime_executable=comp.runtime, runtime_root=comp.runtime.parent,
        runidentity_store=comp.state_root / "runidentity",
        anchorstore=comp.state_root / "anchors", service_name=SERVICE_NAME))
    if deployment.digest() != comp.deployment_digest:
        _explain_deployment_drift(comp, deployment)
    check("deployment digest stable across observations",
          deployment.digest(), comp.deployment_digest)

    launched = _launched_identity(produced, launch_digest)
    plan = RunPlan(task_id="F-17", run_id=RUN_ID, repository_id="gnosis",
                   head_sha=HEAD_SHA, tree_identity=TREE_ID,
                   bundle_path=str(bundle), epoch=0)
    spec = LaunchSpec(launch_id="s6-work", executable=str(comp.runtime),
                      argv=(str(comp.runtime),), cwd=str(comp.state_root),
                      stdout_path=str(comp.state_root / "o.txt"),
                      stderr_path=str(comp.state_root / "e.txt"), run_id=RUN_ID)
    record = create_trusted_run(run_store, plan, spec=spec,
                                deployment=deployment, launched=launched)
    check("run identity owner is the OBSERVED sid",
          record.identity.owner_worker_sid, comp.worker_sid)
    check("run identity binds the sealed launch",
          record.identity.launch_spec_digest, launch_digest)
    check("run identity starts NOT_PUBLISHABLE",
          record.publication_state, PublicationState.NOT_PUBLISHABLE)

    # 10 (out of order, deliberately): the Worker asks BEFORE the gate runs.
    early = run_as_worker(comp, "s6-early", "publish", PIPE_NAME,
                          f"PUBLISH {RUN_ID}")
    check("worker could open the pipe", early.get("opened"), True)
    check("publish BEFORE publishable is refused",
          str(early.get("reply")).startswith("REJECTED:"), True)
    say(f"   reply: {early.get('reply')}")

    # 9. Only a trusted party may make it publishable.
    gated = authorize_publishable(
        run_store, record.identity,
        CompletionEvidence(exit_code=0, timed_out=False, cancelled=False,
                           bundle_dir=bundle))
    check("trusted gate marked it PUBLISHABLE", gated.publication_state,
          PublicationState.PUBLISHABLE)

    # 10-13. The Worker asks again; now the publisher may act.
    published = run_as_worker(comp, "s6-publish", "publish", PIPE_NAME,
                              f"PUBLISH {RUN_ID}")
    reply = str(published.get("reply"))
    say(f"   reply: {reply}")
    check("publication ANCHORED", reply.startswith("ANCHORED:"), True)

    # 14-16. The durable consequences.
    store = AnchorStore(comp.state_root / "anchors", require_high=False)
    anchor = store.lookup(RUN_ID)
    check("anchor record exists", anchor is not None, True)
    if anchor is not None:
        check("anchor schema is V2", anchor.schema, "gnosis.anchor.v2")
        check("anchor binds the deployment", anchor.deployment_digest,
              comp.deployment_digest)
        check("anchor binds the run identity", anchor.run_identity_digest,
              record.identity.digest())
    watermark = read_watermark(comp.state_root / "anchors")
    check("watermark confirms the commit",
          watermark is not None and watermark.committed_seq >= 0, True)
    check("run identity reconciled to ANCHORED",
          run_store.read(RUN_ID).publication_state, PublicationState.ANCHORED)

    # 18. Idempotent retry.
    again = run_as_worker(comp, "s6-again", "publish", PIPE_NAME,
                          f"PUBLISH {RUN_ID}")
    check("a retry is ALREADY_ANCHORED",
          str(again.get("reply")).startswith("ALREADY_ANCHORED"), True)
    check("exactly one anchor record", len(store.records()), 1)
    say("")
    return RUN_ID


def _launched_identity(produced: dict[str, object], launch_digest: str):  # type: ignore[no-untyped-def]
    from gnosis.trust.worker_launcher import LaunchedWorkerIdentity
    return LaunchedWorkerIdentity(
        pid=0, observed_sid=str(produced.get("observed_sid")),
        integrity="Medium", is_administrator=False, dangerous_privileges=(),
        launch_spec_digest=launch_digest, logical_command_digest="0" * 64,
        transport_command_length=0, contained_in_job=True)


def adversarial(comp: Composition) -> None:
    say("ADVERSARIAL COMPOSITION — every case has an expected verdict")
    say("-" * 78)

    say("  IPC grammar")
    for label, message, expected in (
            ("unknown run", "PUBLISH RUN-DOES-NOT-EXIST", "REJECTED:unknown-run"),
            ("path traversal", "PUBLISH ../../windows", "REJECTED:bad-request"),
            ("absolute path", "PUBLISH C:/Windows", "REJECTED:bad-request"),
            ("another verb", "DELETE " + RUN_ID, "REJECTED:bad-request"),
            ("no verb", RUN_ID, "REJECTED:bad-request"),
            ("extra argument", f"PUBLISH {RUN_ID} {comp.deployment_digest}",
             "REJECTED:bad-request"),
            # "F5" is a syntactically valid run id, so the honest refusal is
            # unknown-run. That no fault hook is installed by ANY request is
            # asserted directly in the unit tests.
            ("fault-point selection", "PUBLISH F5", "REJECTED:unknown-run"),
            ("oversized", "PUBLISH " + "a" * 2000, "REJECTED:oversized"),
    ):
        result = run_as_worker(comp, f"s6-adv-{abs(hash(label)) % 10000}",
                               "publish", PIPE_NAME, message)
        check(f"  {label}", str(result.get("reply")), expected)

    say("")
    say("  the Worker against trusted state (ACL prevention)")
    for label, target in (
            ("anchor ledger", comp.state_root / "anchors" / "anchors.jsonl"),
            ("watermark", comp.state_root / "anchors" / "anchors.watermark.json"),
            ("run identity", comp.state_root / "runidentity" / f"{RUN_ID}.json"),
            ("publisher config", comp.config_path),
            ("deployed service entry point",
             comp.s5probe.src / "service_main.py"),  # type: ignore[attr-defined]
            ("deployed publisher module",
             comp.s5probe.src / "gnosis" / "trust" / "publisher.py"),  # type: ignore[attr-defined]
            ("trusted runtime", comp.runtime),
    ):
        result = run_as_worker(comp, f"s6-w-{abs(hash(label)) % 10000}", "write",
                               str(target))
        outcome = str(result.get("outcome", ""))
        check(f"  write {label}", outcome.startswith("DENIED"), True)

    say("")
    say("  the Worker against the endpoint and the service")
    squat = run_as_worker(comp, "s6-squat", "createpipe", PIPE_NAME)
    check("  worker creates an instance of the trusted pipe",
          str(squat.get("outcome", "")).startswith("DENIED"), True)

    for label, args in (
            ("stop the service", ("stop", SERVICE_NAME)),
            ("reconfigure the image path",
             ("config", SERVICE_NAME, "binPath=", "C:\\evil.exe")),
            ("change the SID type", ("sidtype", SERVICE_NAME, "unrestricted")),
            ("delete the service", ("delete", SERVICE_NAME)),
    ):
        result = run_as_worker(comp, f"s6-sc-{abs(hash(label)) % 10000}",
                               "service", "sc.exe", *args)
        check(f"  worker can {label}", result.get("rc") == 0, False)

    still = sc("query", SERVICE_NAME)
    check("  service still installed and RUNNING",
          "RUNNING" in still.stdout, True)
    say("")


def restart_survives(comp: Composition) -> None:
    say("RESTART — committed state survives and reconciles")
    say("-" * 78)
    store = AnchorStore(comp.state_root / "anchors", require_high=False)
    before = len(store.records())
    sc("stop", SERVICE_NAME)
    time.sleep(1.5)
    check("service stopped", "STOPPED" in sc("query", SERVICE_NAME).stdout, True)
    if not start_service(comp.log_path):
        s5.FAILURES.append("service did not restart")
        return
    after = AnchorStore(comp.state_root / "anchors", require_high=False)
    check("anchor count unchanged across a restart", len(after.records()), before)
    check("chain still verifies", after.verify_chain(), True)
    retry = run_as_worker(comp, "s6-after-restart", "publish", PIPE_NAME,
                          f"PUBLISH {RUN_ID}")
    check("a retry after restart is still ALREADY_ANCHORED",
          str(retry.get("reply")).startswith("ALREADY_ANCHORED"), True)
    say("")


def main() -> int:
    comp: Composition | None = None
    try:
        comp = setup()
        say("SERVICE IDENTITY")
        say("-" * 78)
        observed = observe_service(SERVICE_NAME)
        check("service SID type", observed.sid_type, "RESTRICTED")
        check("service SID is a service SID",
              observed.service_sid.startswith("S-1-5-80-"), True)
        check("start type", observed.start_type, "DEMAND")
        say(f"   account            : {observed.account}")
        say(f"   required privileges: {observed.required_privileges}")
        say("")

        if not start_service(comp.log_path):
            s5.FAILURES.append("service did not start")
            return 1
        say("   service RUNNING")
        say("")

        if happy_path(comp) is None:
            return 1
        adversarial(comp)
        restart_survives(comp)
        return 0
    finally:
        rollback(comp)
        say("")
        say("=" * 78)
        # AN EMPTY FAILURE LIST IS NOT A PASS. A previous run crashed inside
        # setup() before a single check executed, and this summary announced
        # "ALL CHECKS PASSED" over zero checks - absence of failure read as
        # presence of verification, which is the defect this whole stage exists
        # to prevent. The count is now part of the verdict.
        checked = len([line for line in s5.OUT if "<- required" in line])
        if s5.FAILURES:
            say(f"PROBE RESULT: {len(s5.FAILURES)} FAILURE(S) of {checked} "
                f"checks: {s5.FAILURES}")
        elif checked < MINIMUM_CHECKS:
            say(f"PROBE RESULT: INCONCLUSIVE — only {checked} checks ran "
                f"(at least {MINIMUM_CHECKS} expected); the probe did not "
                "finish, so nothing is claimed")
        else:
            say(f"PROBE RESULT: ALL {checked} CHECKS PASSED")
        say("=" * 78)
        out = REPO / "probe_stage6_output.txt"
        out.write_text("\n".join(s5.OUT) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
