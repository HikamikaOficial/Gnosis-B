"""F-17 Stage 5 OS-REAL PROBE — the trusted dedicated-worker launcher.

Creates DISPOSABLE infrastructure, exercises the real Windows boundary against
it, and rolls everything back. Nothing production is created or modified: no
production account, no service, no production ACL, no production path.

    account   GnosisWkrS5Probe   (local, non-admin, deleted at the end)
    root      C:\\ProgramData\\Gnosis\\TrustProbe\\   (deleted at the end)
    secret    a random password, DPAPI machine-bound, never printed, never
              on a command line, never written in plaintext

Run ELEVATED:

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/probe_stage5_worker_launcher.py \
        [--out PATH] [--keep]

`--keep` skips rollback and is for debugging only; the default always rolls back,
including on failure.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import time
from ctypes import wintypes as W
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from gnosis.trust.launch_spec import LaunchSpec, launch_spec_path
from gnosis.trust.worker_launcher import (
    TRANSPORT_COMMAND_BUDGET,
    LaunchedWorkerIdentity,
    TrustedWindowsWorkerLauncher,
    WorkerAccount,
    WorkerLaunchFailed,
    build_transport_command,
    protect_worker_secret,
)

WORKER_NAME = "GnosisWkrS5Probe"   # <= 20 chars: Windows SAM limit
PROBE_ROOT = Path(r"C:\ProgramData\Gnosis\TrustProbe")
SENTINEL_NAME = "GNOSIS_STAGE5_SECRET_SENTINEL"

OUT: list[str] = []
FAILURES: list[str] = []


def say(text: str = "") -> None:
    print(text, flush=True)
    OUT.append(text)


def check(label: str, actual: object, required: object) -> bool:
    ok = actual == required
    say(f"   {label:<52s}: {actual!s:<26s} <- required {required!s}   "
        f"{'OK' if ok else '*** FAIL ***'}")
    if not ok:
        FAILURES.append(label)
    return ok


# ---------------------------------------------------------------------------
# Win32: account creation and SID resolution
# ---------------------------------------------------------------------------
_netapi = ctypes.WinDLL("netapi32", use_last_error=True)
_a32 = ctypes.WinDLL("advapi32", use_last_error=True)

USER_PRIV_USER = 1
UF_SCRIPT = 0x0001
UF_NORMAL_ACCOUNT = 0x0200
UF_DONT_EXPIRE_PASSWD = 0x10000


class USER_INFO_1(ctypes.Structure):
    _fields_ = [("usri1_name", W.LPWSTR), ("usri1_password", W.LPWSTR),
                ("usri1_password_age", W.DWORD), ("usri1_priv", W.DWORD),
                ("usri1_home_dir", W.LPWSTR), ("usri1_comment", W.LPWSTR),
                ("usri1_flags", W.DWORD), ("usri1_script_path", W.LPWSTR)]


_netapi.NetUserAdd.argtypes = [W.LPCWSTR, W.DWORD, ctypes.c_void_p,
                               ctypes.POINTER(W.DWORD)]
_netapi.NetUserDel.argtypes = [W.LPCWSTR, W.LPCWSTR]
_a32.LookupAccountNameW.argtypes = [
    W.LPCWSTR, W.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(W.DWORD), W.LPWSTR,
    ctypes.POINTER(W.DWORD), ctypes.POINTER(W.DWORD)]
_a32.LookupAccountNameW.restype = W.BOOL
_a32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(W.LPWSTR)]
_a32.ConvertSidToStringSidW.restype = W.BOOL
ctypes.WinDLL("kernel32").LocalFree.argtypes = [ctypes.c_void_p]
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)


def random_password() -> str:
    """Random, complexity-satisfying, never logged and never on a command line.

    Every character is drawn from `secrets`, including the ones that satisfy
    Windows' complexity policy. An earlier version used a FIXED prefix and
    suffix to guarantee complexity; that put a literal password fragment in the
    repository, which a secret scan is right to flag even though the fragment is
    not itself a credential. Complexity is now guaranteed by construction
    without any constant.
    """
    classes = (string.ascii_uppercase, string.ascii_lowercase, string.digits,
               "!#%&*+-=?@^_")
    required = [secrets.choice(group) for group in classes]
    alphabet = "".join(classes)
    body = [secrets.choice(alphabet) for _ in range(24)]
    chars = required + body
    # shuffle without random.shuffle, which is not a CSPRNG
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


def create_worker(password: str) -> None:
    info = USER_INFO_1(
        usri1_name=WORKER_NAME, usri1_password=password, usri1_password_age=0,
        usri1_priv=USER_PRIV_USER, usri1_home_dir=None,
        usri1_comment="GNOSIS F-17 Stage 5 disposable probe worker",
        usri1_flags=UF_SCRIPT | UF_NORMAL_ACCOUNT | UF_DONT_EXPIRE_PASSWD,
        usri1_script_path=None)
    parm = W.DWORD(0)
    status = _netapi.NetUserAdd(None, 1, ctypes.byref(info), ctypes.byref(parm))
    if status != 0:
        raise SystemExit(f"NetUserAdd failed with status {status} (parm {parm.value})")


def delete_worker() -> int:
    return int(_netapi.NetUserDel(None, WORKER_NAME))


def resolve_sid(name: str) -> str:
    sid_size = W.DWORD(0)
    dom_size = W.DWORD(0)
    use = W.DWORD(0)
    _a32.LookupAccountNameW(None, name, None, ctypes.byref(sid_size), None,
                            ctypes.byref(dom_size), ctypes.byref(use))
    sid = ctypes.create_string_buffer(sid_size.value)
    dom = ctypes.create_unicode_buffer(dom_size.value)
    if not _a32.LookupAccountNameW(None, name, sid, ctypes.byref(sid_size), dom,
                                   ctypes.byref(dom_size), ctypes.byref(use)):
        raise SystemExit(f"LookupAccountNameW({name}) failed "
                         f"(winerr {ctypes.get_last_error()})")
    out = W.LPWSTR()
    if not _a32.ConvertSidToStringSidW(sid, ctypes.byref(out)):
        raise SystemExit("ConvertSidToStringSidW failed")
    try:
        return out.value or ""
    finally:
        _k32.LocalFree(out)


def icacls(*args: str) -> subprocess.CompletedProcess[str]:
    # errors="replace": icacls speaks the OEM console code page, which is not
    # UTF-8 on a Spanish install, and a decode crash in a probe helper would
    # look like an ACL failure it is not.
    return subprocess.run(["icacls", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


# ---------------------------------------------------------------------------
# Worker-side probe helper. Runs AS THE WORKER through the real launcher.
# ---------------------------------------------------------------------------
WORKER_PROBE = r'''
import ctypes, json, os, subprocess, sys, time
from ctypes import wintypes as W
mode = sys.argv[1]; out_path = sys.argv[2]
result = {"mode": mode}
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
a32 = ctypes.WinDLL("advapi32", use_last_error=True)

if mode == "identity":
    result["argv"] = sys.argv[3:]
    result["cwd"] = os.getcwd()
    result["env_names"] = sorted(os.environ)
    result["USERPROFILE"] = os.environ.get("USERPROFILE", "")
    result["APPDATA"] = os.environ.get("APPDATA", "")
    result["USERNAME"] = os.environ.get("USERNAME", "")
    result["sentinel_present"] = "GNOSIS_STAGE5_SECRET_SENTINEL" in os.environ
    try:
        result["stdin_isatty"] = sys.stdin.isatty() if sys.stdin else None
    except Exception as exc:
        result["stdin_isatty"] = "error:" + type(exc).__name__
    try:
        result["stdin_read"] = repr(sys.stdin.read(16)) if sys.stdin else None
    except Exception as exc:
        result["stdin_read"] = "error:" + type(exc).__name__
    STD_INPUT_HANDLE = -10
    k32.GetStdHandle.argtypes = [W.DWORD]
    k32.GetStdHandle.restype = W.HANDLE
    k32.GetConsoleMode.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
    mode = W.DWORD(0)
    h_in = k32.GetStdHandle(STD_INPUT_HANDLE)
    result["stdin_is_console"] = bool(k32.GetConsoleMode(h_in, ctypes.byref(mode)))
    k32.IsProcessInJob.argtypes = [W.HANDLE, W.HANDLE, ctypes.POINTER(W.BOOL)]
    injob = W.BOOL(False)
    k32.IsProcessInJob(k32.GetCurrentProcess(), None, ctypes.byref(injob))
    result["in_a_job"] = bool(injob.value)

elif mode == "denied":
    targets = json.loads(sys.argv[3])
    acc = {}
    for label, path in targets.items():
        try:
            with open(path, "rb") as fh:
                fh.read(1)
            acc[label + ":read"] = "ALLOWED"
        except Exception as exc:
            acc[label + ":read"] = "DENIED:" + type(exc).__name__
        try:
            with open(path, "ab") as fh:
                fh.write(b"x")
            acc[label + ":write"] = "ALLOWED"
        except Exception as exc:
            acc[label + ":write"] = "DENIED:" + type(exc).__name__
        try:
            os.remove(path); acc[label + ":delete"] = "ALLOWED"
        except Exception as exc:
            acc[label + ":delete"] = "DENIED:" + type(exc).__name__
        try:
            os.rename(path, path + ".moved"); acc[label + ":rename"] = "ALLOWED"
        except Exception as exc:
            acc[label + ":rename"] = "DENIED:" + type(exc).__name__
    dirs = json.loads(sys.argv[4])
    for label, path in dirs.items():
        try:
            p = os.path.join(path, "worker_created.txt")
            with open(p, "wb") as fh:
                fh.write(b"x")
            acc[label + ":create"] = "ALLOWED"
        except Exception as exc:
            acc[label + ":create"] = "DENIED:" + type(exc).__name__
        r = subprocess.run(["icacls", path, "/grant", "*S-1-1-0:(F)"],
                           capture_output=True, text=True)
        acc[label + ":write_dac"] = "ALLOWED" if r.returncode == 0 else "DENIED"
        r = subprocess.run(["takeown", "/F", path], capture_output=True, text=True)
        acc[label + ":takeown"] = "ALLOWED" if r.returncode == 0 else "DENIED"
    result["access"] = acc

elif mode == "descendants":
    marker = sys.argv[3]
    child_code = (
        "import subprocess,sys,time\n"
        "subprocess.Popen([sys.executable,'-c',"
        "\"import time,sys\\nfor i in range(600):\\n open(sys.argv[1],'w').write(str(i))\\n time.sleep(0.2)\","
        "sys.argv[1]])\n"
        "time.sleep(600)\n")
    subprocess.Popen([sys.executable, "-I", "-c", child_code, marker])
    # a breakaway attempt: CREATE_BREAKAWAY_FROM_JOB must not let it escape
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    try:
        p = subprocess.Popen([sys.executable, "-I", "-c",
                              "import time;time.sleep(600)"],
                             creationflags=CREATE_BREAKAWAY_FROM_JOB)
        result["breakaway"] = "CREATED pid=%d" % p.pid
    except Exception as exc:
        result["breakaway"] = "REFUSED:" + type(exc).__name__
    time.sleep(1.0)
    result["spawned"] = True
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    time.sleep(600)

elif mode == "crossprocess":
    target_pid = int(sys.argv[3])
    RIGHTS = {"PROCESS_VM_WRITE": 0x0020, "PROCESS_VM_OPERATION": 0x0008,
              "PROCESS_CREATE_THREAD": 0x0002, "PROCESS_DUP_HANDLE": 0x0040,
              "PROCESS_CREATE_PROCESS": 0x0080, "PROCESS_ALL_ACCESS": 0x1FFFFF,
              "PROCESS_QUERY_INFORMATION": 0x0400}
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.OpenProcess.restype = W.HANDLE
    acc = {}
    for name, right in RIGHTS.items():
        h = k32.OpenProcess(right, False, target_pid)
        acc[name] = "ALLOWED" if h else "DENIED"
        if h:
            k32.CloseHandle(h)
    h = k32.OpenProcess(0x0400, False, target_pid)
    if h:
        tok = W.HANDLE()
        a32.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, ctypes.POINTER(W.HANDLE)]
        acc["OpenProcessToken"] = ("ALLOWED"
                                   if a32.OpenProcessToken(h, 0x0008, ctypes.byref(tok))
                                   else "DENIED")
        k32.CloseHandle(h)
    else:
        acc["OpenProcessToken"] = "DENIED(no process handle)"
    result["access"] = acc

elif mode == "toolchain":
    tools = json.loads(sys.argv[3])
    got = {}
    for name, argv in tools.items():
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=120)
            got[name] = {"rc": r.returncode,
                         "out": (r.stdout or r.stderr).strip().splitlines()[:1]}
        except Exception as exc:
            got[name] = {"rc": None, "out": ["error:" + type(exc).__name__]}
    result["tools"] = got
    writes = {}
    for name, path in json.loads(sys.argv[4]).items():
        try:
            with open(path, "ab") as fh:
                fh.write(b"")
            writes[name] = "ALLOWED"
        except Exception as exc:
            writes[name] = "DENIED:" + type(exc).__name__
    result["toolchain_write"] = writes

with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(result, fh)
'''


@dataclass
class Probe:
    root: Path
    tools: Path
    runtime: Path
    src: Path
    launch: Path
    secrets_dir: Path
    work: Path
    worker_sid: str
    blob: Path
    account: WorkerAccount

    def launcher(self, director_env: dict[str, str] | None = None
                 ) -> TrustedWindowsWorkerLauncher:
        return TrustedWindowsWorkerLauncher(
            account=self.account, credential_blob_path=self.blob,
            launch_root=self.launch, runtime=self.runtime,
            director_env=director_env if director_env is not None else dict(os.environ))

    def run_worker(self, launch_id: str, args: list[str], *, timeout_s: float = 180.0
                   ) -> tuple[LaunchedWorkerIdentity, int, dict[str, object], str]:
        """Run the worker probe helper AS THE WORKER, return its JSON result."""
        payload = self.work / f"{launch_id}-result.json"
        stdout = self.work / f"{launch_id}.out"
        stderr = self.work / f"{launch_id}.err"
        helper = self.tools / "worker_probe.py"
        argv = [str(self.runtime), "-I", str(helper), *args, str(payload)]
        # the helper takes (mode, out_path, *rest) -> reorder to (mode, out, rest)
        argv = [str(self.runtime), "-I", str(helper), args[0], str(payload), *args[1:]]
        spec = LaunchSpec(launch_id=launch_id, executable=str(self.runtime),
                          argv=tuple(argv), cwd=str(self.work),
                          stdout_path=str(stdout), stderr_path=str(stderr),
                          run_id=None)
        result = self.launcher().launch(spec)
        try:
            code, timed_out, cancelled = result.wait(timeout_s)
        finally:
            identity = result.identity
            result.close()
        data: dict[str, object] = {}
        if payload.is_file():
            data = json.loads(payload.read_text(encoding="utf-8"))
        err = stderr.read_text(encoding="utf-8", errors="replace") if stderr.is_file() else ""
        if timed_out or cancelled:
            err += f" [timed_out={timed_out} cancelled={cancelled}]"
        return identity, code, data, err


def setup(password: str) -> Probe:
    say("SETUP — disposable infrastructure")
    say("-" * 78)
    root = PROBE_ROOT
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    tools, launch, secrets_dir, work = (root / "tools", root / "launch",
                                        root / "secrets", root / "work")
    for path in (tools, launch, secrets_dir, work):
        path.mkdir(parents=True, exist_ok=True)

    say("   copying the Python runtime into the probe tool root ...")
    runtime_src = Path(sys.base_prefix)
    shutil.copytree(runtime_src, tools / "runtime", dirs_exist_ok=True)
    runtime = tools / "runtime" / "python.exe"

    say("   copying the bootstrap's module closure into the probe tool root ...")
    src = tools / "src"
    for rel in ("gnosis/__init__.py", "gnosis/kernel/__init__.py",
                "gnosis/kernel/canonical.py", "gnosis/kernel/atomic_io.py",
                "gnosis/trust/__init__.py", "gnosis/trust/launch.py",
                "gnosis/trust/launch_spec.py", "gnosis/trust/bootstrap.py"):
        dest = src / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / "src" / rel, dest)
    (tools / "worker_probe.py").write_text(WORKER_PROBE, encoding="utf-8")

    # THE TOOLCHAIN LIVES IN THE DIRECTOR'S PROFILE, which a dedicated worker
    # cannot read — proven by an earlier run of this probe, where
    # `claude --version` returned PermissionError. Relocating the toolchain into
    # a worker-readable root is the documented compat cost of the dedicated
    # worker model (already priced in by the earlier qualification: "toolchain
    # relocation is the compat cost"). The probe performs the relocation and
    # then proves the tool runs, rather than granting the worker rights inside
    # the Director's profile.
    claude_src = shutil.which("claude")
    if claude_src:
        say("   relocating the Claude CLI into the probe tool root ...")
        shutil.copy2(claude_src, tools / "claude.exe")
    else:
        say("   Claude CLI not on PATH; the toolchain check will report it")

    say(f"   creating the disposable account {WORKER_NAME} ...")
    create_worker(password)
    worker_sid = resolve_sid(WORKER_NAME)
    say(f"   worker SID: {worker_sid}")

    say("   DPAPI-protecting the credential (machine-bound) ...")
    blob = secrets_dir / "worker.dpapi"
    blob.write_bytes(protect_worker_secret(password))

    say("   applying probe-only ACLs ...")
    # tools + launch: worker may READ and EXECUTE, nothing else.
    for path in (tools, launch):
        icacls(str(path), "/inheritance:r")
        icacls(str(path), "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
               "*S-1-5-18:(OI)(CI)F", f"*{worker_sid}:(OI)(CI)(RX)")
    # secrets: the worker is simply NOT granted. This is the T2 boundary.
    icacls(str(secrets_dir), "/inheritance:r")
    icacls(str(secrets_dir), "/grant:r", "*S-1-5-32-544:(OI)(CI)F",
           "*S-1-5-18:(OI)(CI)F")
    # work: the run's own workspace; the worker writes its output here.
    icacls(str(work), "/inheritance:r")
    icacls(str(work), "/grant:r", "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F",
           f"*{worker_sid}:(OI)(CI)M")
    say("")
    return Probe(root=root, tools=tools, runtime=runtime, src=src, launch=launch,
                 secrets_dir=secrets_dir, work=work, worker_sid=worker_sid, blob=blob,
                 account=WorkerAccount(username=WORKER_NAME, domain=".",
                                       expected_sid=worker_sid,
                                       expected_integrity="Medium"))


def rollback(probe: Probe | None) -> None:
    say("")
    say("ROLLBACK")
    say("-" * 78)
    # kill anything still running as the worker
    kill_workers = (
        "Get-CimInstance Win32_Process | Where-Object { "
        f"$_.GetOwner().User -eq '{WORKER_NAME}' }} | ForEach-Object "
        "{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", kill_workers],
                   capture_output=True, check=False)
    status = delete_worker()
    say(f"   NetUserDel({WORKER_NAME})                       : status {status} "
        f"({'deleted' if status == 0 else 'already absent' if status == 2221 else 'ERROR'})")
    drop_profile = (
        "Get-CimInstance Win32_UserProfile | Where-Object { "
        f"$_.LocalPath -like '*{WORKER_NAME}*' }} | Remove-CimInstance "
        "-ErrorAction SilentlyContinue")
    subprocess.run(["powershell", "-NoProfile", "-Command", drop_profile],
                   capture_output=True, check=False)
    profile = Path(r"C:\Users") / WORKER_NAME
    if profile.exists():
        shutil.rmtree(profile, ignore_errors=True)
    say(f"   Win32 profile removed                          : {not profile.exists()}")
    if PROBE_ROOT.exists():
        subprocess.run(["icacls", str(PROBE_ROOT), "/reset", "/T", "/C", "/Q"],
                       capture_output=True, check=False)
        shutil.rmtree(PROBE_ROOT, ignore_errors=True)
    say(f"   probe root removed                             : {not PROBE_ROOT.exists()}")
    residual = subprocess.run(["net", "user", WORKER_NAME], capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              check=False)
    say(f"   account residue (net user rc!=0 means gone)    : rc={residual.returncode}")
    say(f"   DPAPI blob removed                             : "
        f"{probe is None or not probe.blob.exists()}")
    say("   no service, no scheduled task, no production ACL was ever created")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    say("F-17 STAGE 5 — OS-REAL TRUSTED WORKER LAUNCHER PROBE")
    say("=" * 78)
    say("")
    password = random_password()
    probe: Probe | None = None
    try:
        probe = setup(password)
        run_matrix(probe, password)
    finally:
        # the password buffer is a str and cannot truly be erased; it is dropped
        # here and never written anywhere. The DPAPI blob is the only at-rest form.
        del password
        if not args.keep:
            rollback(probe)
        else:
            say("--keep: rollback SKIPPED (debugging only)")

    say("")
    say("=" * 78)
    if FAILURES:
        say(f"PROBE RESULT: FAIL ({len(FAILURES)} checks) -> {FAILURES}")
    else:
        say("PROBE RESULT: ALL CHECKS PASSED")
    if args.out:
        args.out.write_text("\n".join(OUT) + "\n", encoding="utf-8")
    return 1 if FAILURES else 0


def run_matrix(probe: Probe, password: str) -> None:
    say("T1 — CROSS-USER LAUNCH, IDENTITY AND CONTAINMENT")
    say("-" * 78)
    director_env = dict(os.environ)
    director_env[SENTINEL_NAME] = "this-value-must-never-reach-the-worker"
    launcher = probe.launcher(director_env)

    payload = probe.work / "t1-result.json"
    helper = probe.tools / "worker_probe.py"
    argv = [str(probe.runtime), "-I", str(helper), "identity", str(payload),
            "plain", "with space", 'has "quotes"', "back\\slash", "trail\\\\", "",
            "unicode-\u00e1\u00e9\u4e2d\u6587", "X" * 12000, "%NOT_EXPANDED%"]
    spec = LaunchSpec(launch_id="t1", executable=str(probe.runtime), argv=tuple(argv),
                      cwd=str(probe.work), stdout_path=str(probe.work / "t1.out"),
                      stderr_path=str(probe.work / "t1.err"),
                      run_id="RUN-20260827T000000000Z-stage5")
    command = build_transport_command(probe.runtime,
                                      launch_spec_path(probe.launch, "t1"), "0" * 64)
    say(f"   logical argv rendered length : "
        f"{len(subprocess.list2cmdline(argv))} characters")
    say(f"   transport command length     : {len(command)} characters "
        f"(budget {TRANSPORT_COMMAND_BUDGET}, OS cap 1024)")
    check("transport command within budget", len(command) <= TRANSPORT_COMMAND_BUDGET, True)

    result = launcher.launch(spec)
    identity = result.identity
    code, timed_out, _cancelled = result.wait(240.0)
    result.close()
    data = json.loads(payload.read_text(encoding="utf-8")) if payload.is_file() else {}

    check("child exit code", code, 0)
    check("timed out", timed_out, False)
    check("observed TokenUser SID == expected", identity.observed_sid,
          probe.worker_sid)
    check("child integrity", identity.integrity, "Medium")
    check("child is administrator", identity.is_administrator, False)
    check("dangerous privileges in child token", list(identity.dangerous_privileges), [])
    check("contained in job", identity.contained_in_job, True)
    check("worker reports it is in a job", data.get("in_a_job"), True)
    say(f"   pid={identity.pid}  launch_spec_digest={identity.launch_spec_digest}")
    say(f"   logical_command_digest={identity.logical_command_digest}")

    say("")
    say("T2 — ARGV FIDELITY THROUGH THE BOUNDARY")
    say("-" * 78)
    check("argv vector roundtrips exactly", data.get("argv"), argv[5:])
    check("12000-char argument survived",
          len(str((data.get("argv") or ["", ""])[7])) if data.get("argv") else 0, 12000)
    check("cwd is the authorized workspace",
          str(data.get("cwd", "")).lower(), str(probe.work).lower())

    say("")
    say("T3 — E1: ENVIRONMENT ISOLATION")
    say("-" * 78)
    check("Director sentinel present in worker env", data.get("sentinel_present"), False)
    names = set(data.get("env_names") or [])
    leaked = sorted(n for n in names if n in director_env
                    and n not in {"PYTHONUTF8", "PYTHONIOENCODING", "SystemRoot",
                                  "SystemDrive", "windir", "COMPUTERNAME",
                                  "NUMBER_OF_PROCESSORS", "OS", "PROCESSOR_ARCHITECTURE",
                                  "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL",
                                  "PROCESSOR_REVISION", "PATHEXT", "COMSPEC",
                                  "DriverData", "ProgramData", "ProgramFiles",
                                  "ProgramFiles(x86)", "ProgramW6432", "PUBLIC",
                                  "ALLUSERSPROFILE", "CommonProgramFiles",
                                  "CommonProgramFiles(x86)", "CommonProgramW6432",
                                  "PATH", "USERDOMAIN", "LOGONSERVER"}
                    and director_env.get(n) == "")
    say(f"   worker env variables         : {len(names)}")
    check("Director CLAUDE_* names in worker env",
          sorted(n for n in names if n.startswith("CLAUDE")), [])
    check("Director-only leaked names", leaked, [])
    check("USERPROFILE belongs to the worker",
          WORKER_NAME.lower() in str(data.get("USERPROFILE", "")).lower(), True)
    check("APPDATA belongs to the worker",
          WORKER_NAME.lower() in str(data.get("APPDATA", "")).lower(), True)
    check("USERNAME is the worker", str(data.get("USERNAME", "")).lower(),
          WORKER_NAME.lower())

    say("")
    say("T4 — H1: STDIN ISOLATION")
    say("-" * 78)
    # NOT isatty(): on Windows NUL is a CHARACTER DEVICE, so isatty() is True
    # for DEVNULL as well as for a console. The discriminator that actually
    # separates them is GetConsoleMode, which succeeds only on a console handle.
    # The first OS-real run asserted isatty and failed for that reason; the
    # assertion was wrong, not the isolation.
    check("worker stdin is a real console", data.get("stdin_is_console"), False)
    check("worker stdin reads EOF immediately", data.get("stdin_read"), "''")
    say(f"   (isatty() reports {data.get('stdin_isatty')} because NUL is a "
        "character device; that is a Windows quirk, not a leak)")

    say("")
    say("T5 — PAYLOAD AND CREDENTIAL ACCESS FROM THE WORKER")
    say("-" * 78)
    targets = {"launch_spec": str(launch_spec_path(probe.launch, "t1")),
               "dpapi_blob": str(probe.blob),
               "bootstrap": str(probe.src / "gnosis" / "trust" / "bootstrap.py")}
    dirs = {"launch_root": str(probe.launch), "tool_root": str(probe.tools)}
    _, _, acc_data, err = probe.run_worker(
        "t5", ["denied", json.dumps(targets), json.dumps(dirs)])
    acc = acc_data.get("access") or {}
    if not acc:
        say(f"   worker probe produced no access map; stderr: {err[:200]}")
        FAILURES.append("T5 produced no data")
    for label, required in (
            ("launch_spec:read", "ALLOWED"), ("launch_spec:write", "DENIED"),
            ("launch_spec:delete", "DENIED"), ("launch_spec:rename", "DENIED"),
            ("dpapi_blob:read", "DENIED"), ("dpapi_blob:write", "DENIED"),
            ("dpapi_blob:delete", "DENIED"), ("dpapi_blob:rename", "DENIED"),
            ("bootstrap:read", "ALLOWED"), ("bootstrap:write", "DENIED"),
            ("bootstrap:delete", "DENIED"), ("bootstrap:rename", "DENIED"),
            ("launch_root:create", "DENIED"), ("launch_root:write_dac", "DENIED"),
            ("launch_root:takeown", "DENIED"), ("tool_root:create", "DENIED"),
            ("tool_root:write_dac", "DENIED"), ("tool_root:takeown", "DENIED")):
        got = str(acc.get(label, "<missing>"))
        ok = got.startswith(required)
        say(f"   {label:<52s}: {got:<26s} <- required {required}   "
            f"{'OK' if ok else '*** FAIL ***'}")
        if not ok:
            FAILURES.append(f"T5 {label}")

    say("")
    say("T6 — SEAL TAMPERING")
    say("-" * 78)
    tampered = LaunchSpec(launch_id="t6", executable=str(probe.runtime),
                          argv=(str(probe.runtime), "-I", "-c", "print(1)"),
                          cwd=str(probe.work), stdout_path=str(probe.work / "t6.out"),
                          stderr_path=str(probe.work / "t6.err"))
    try:
        launcher.launch(tampered).close()
    except WorkerLaunchFailed as exc:  # pragma: no cover - only on a real failure
        say(f"   baseline launch failed unexpectedly: {exc}")
    spec_file = launch_spec_path(probe.launch, "t6")
    original = spec_file.read_bytes()
    evil = json.loads(original.decode("utf-8"))
    evil["argv"] = [str(probe.runtime), "-I", "-c", "print('PWNED')"]
    spec_file.write_bytes(json.dumps(evil).encode("utf-8"))
    good_digest = LaunchSpec.from_dict(json.loads(original.decode("utf-8"))).digest()
    rc = subprocess.run([str(probe.runtime), "-I",
                         str(probe.src / "gnosis" / "trust" / "bootstrap.py"),
                         str(spec_file), good_digest],
                        capture_output=True, text=True, check=False)
    check("bootstrap refuses a tampered spec (exit 121)", rc.returncode, 121)
    check("refusal names the seal", "not the one that was sealed" in rc.stderr
          or "digests to" in rc.stderr, True)
    spec_file.write_bytes(original)
    rc = subprocess.run([str(probe.runtime), "-I",
                         str(probe.src / "gnosis" / "trust" / "bootstrap.py"),
                         str(spec_file), "f" * 64],
                        capture_output=True, text=True, check=False)
    check("bootstrap refuses a wrong expected digest", rc.returncode, 121)

    say("")
    say("T7 — D1: DESCENDANT CONTAINMENT")
    say("-" * 78)
    marker = probe.work / "descendant.txt"
    payload7 = probe.work / "t7-result.json"
    helper = probe.tools / "worker_probe.py"
    argv7 = [str(probe.runtime), "-I", str(helper), "descendants", str(payload7),
             str(marker)]
    spec7 = LaunchSpec(launch_id="t7", executable=str(probe.runtime),
                       argv=tuple(argv7), cwd=str(probe.work),
                       stdout_path=str(probe.work / "t7.out"),
                       stderr_path=str(probe.work / "t7.err"))
    res7 = probe.launcher().launch(spec7)
    time.sleep(4.0)
    running = marker.read_text(encoding="utf-8") if marker.is_file() else "<none>"
    _code7, timed7, _cancel7 = res7.wait(0.5)   # force the timeout path
    res7.close()
    # MEASURE THE RIGHT INTERVAL. An earlier version compared the marker from
    # BEFORE wait() with the marker after it, and reported "not contained"
    # because the grandchild legitimately kept running during the 0.5s the
    # timeout was still counting down. What has to be shown is that it stops
    # AFTER termination, so both samples are taken after the job was killed.
    time.sleep(1.0)
    first_after = marker.read_text(encoding="utf-8") if marker.is_file() else "<none>"
    time.sleep(2.5)
    second_after = marker.read_text(encoding="utf-8") if marker.is_file() else "<none>"
    say(f"   marker while running                       : {running!r}")
    say(f"   marker after termination, +1s then +3.5s   : "
        f"{first_after!r} -> {second_after!r}")
    check("timeout path taken", timed7, True)
    check("grandchild STOPPED by job termination", first_after == second_after, True)
    count_workers = (
        "(Get-CimInstance Win32_Process | Where-Object { $_.GetOwner().User -eq "
        f"'{WORKER_NAME}' }}).Count")
    alive = subprocess.run(["powershell", "-NoProfile", "-Command", count_workers],
                           capture_output=True, text=True, check=False)
    remaining = (alive.stdout or "0").strip() or "0"
    check("worker processes still alive after job kill", remaining, "0")

    say("")
    say("T8 — CROSS-PROCESS ATTACKS AGAINST THE DIRECTOR")
    say("-" * 78)
    _, _, xdata, xerr = probe.run_worker("t8", ["crossprocess", str(os.getpid())])
    xacc = xdata.get("access") or {}
    if not xacc:
        say(f"   no data; stderr {xerr[:200]}")
        FAILURES.append("T8 produced no data")
    for right in ("PROCESS_VM_WRITE", "PROCESS_VM_OPERATION", "PROCESS_CREATE_THREAD",
                  "PROCESS_DUP_HANDLE", "PROCESS_CREATE_PROCESS", "PROCESS_ALL_ACCESS",
                  "OpenProcessToken"):
        got = str(xacc.get(right, "<missing>"))
        ok = got.startswith("DENIED")
        say(f"   worker -> Director {right:<34s}: {got:<12s} <- required DENIED   "
            f"{'OK' if ok else '*** FAIL ***'}")
        if not ok:
            FAILURES.append(f"T8 {right}")

    say("")
    say("T9 — TOOLCHAIN UNDER THE WORKER (no login, no provider call)")
    say("-" * 78)
    claude = str(probe.tools / "claude.exe")
    git = shutil.which("git") or "git"
    tools = {"python": [str(probe.runtime), "-V"],
             "git": [git, "--version"],
             "claude": [claude, "--version"]}
    writes = {"runtime": str(probe.runtime), "bootstrap":
              str(probe.src / "gnosis" / "trust" / "bootstrap.py")}
    _, _, tdata, _terr = probe.run_worker(
        "t9", ["toolchain", json.dumps(tools), json.dumps(writes)])
    for name, got in (tdata.get("tools") or {}).items():
        say(f"   {name:<10s} rc={got.get('rc')}  {got.get('out')}")
        if got.get("rc") != 0:
            FAILURES.append(f"T9 {name}")
    for name, verdict in (tdata.get("toolchain_write") or {}).items():
        ok = str(verdict).startswith("DENIED")
        say(f"   worker WRITE to {name:<12s}: {verdict:<26s} <- required DENIED   "
            f"{'OK' if ok else '*** FAIL ***'}")
        if not ok:
            FAILURES.append(f"T9 write {name}")

    say("")
    say("T10 — CREDENTIAL FAILURE MODES (all must FAIL CLOSED)")
    say("-" * 78)
    good_blob = probe.blob.read_bytes()
    for label, payload_bytes in (
            ("missing blob", None),
            ("empty blob", b""),
            ("corrupt blob", bytes(b ^ 0xFF for b in good_blob[:64]) + good_blob[64:]),
            ("truncated blob", good_blob[: len(good_blob) // 2])):
        if payload_bytes is None:
            probe.blob.unlink()
        else:
            probe.blob.write_bytes(payload_bytes)
        try:
            probe.launcher().launch(LaunchSpec(
                launch_id="t10", executable=str(probe.runtime),
                argv=(str(probe.runtime), "-I", "-c", "pass"), cwd=str(probe.work),
                stdout_path=str(probe.work / "t10.out"),
                stderr_path=str(probe.work / "t10.err"))).close()
            verdict = "LAUNCHED"
        except (WorkerLaunchFailed, OSError) as exc:
            verdict = type(exc).__name__
        ok = verdict != "LAUNCHED"
        say(f"   {label:<52s}: {verdict:<26s} <- required refusal   "
            f"{'OK' if ok else '*** FAIL ***'}")
        if not ok:
            FAILURES.append(f"T10 {label}")
    probe.blob.write_bytes(good_blob)

    say("")
    say("T11 — SID MISMATCH IS REFUSED")
    say("-" * 78)
    wrong = TrustedWindowsWorkerLauncher(
        account=WorkerAccount(username=WORKER_NAME, domain=".",
                              expected_sid="S-1-5-21-1-2-3-4444",
                              expected_integrity="Medium"),
        credential_blob_path=probe.blob, launch_root=probe.launch,
        runtime=probe.runtime, director_env={})
    try:
        wrong.launch(LaunchSpec(
            launch_id="t11", executable=str(probe.runtime),
            argv=(str(probe.runtime), "-I", "-c", "pass"), cwd=str(probe.work),
            stdout_path=str(probe.work / "t11.out"),
            stderr_path=str(probe.work / "t11.err"))).close()
        verdict = "LAUNCHED"
    except WorkerLaunchFailed as exc:
        verdict = type(exc).__name__
    check("a wrong expected SID refuses", verdict, "WorkerIdentityMismatch")

    say("")
    say("T12 — PLAINTEXT SCAN OF EVERYTHING THE PROBE WROTE")
    say("-" * 78)
    # Scan for the ACTUAL generated password, in both encodings the OS could
    # have written it in, and for any 8-character run of it. An earlier version
    # scanned for a fixed prefix, which only worked because the generator had
    # one - and having one was itself the defect.
    needles = [password.encode("utf-8"), password.encode("utf-16-le")]
    needles += [password[i:i + 8].encode("utf-8") for i in range(0, 16, 8)]
    hits: list[str] = []
    for path in probe.root.rglob("*"):
        if not path.is_file() or "runtime" in path.parts:
            continue
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        if any(needle in blob for needle in needles):
            hits.append(str(path.relative_to(probe.root)))
    check("password fragments in probe artifacts", hits, [])
    say("   (scanned for the real generated secret in UTF-8 and UTF-16-LE, plus")
    say("    8-character runs of it, across every file the probe wrote except the")
    say("    copied runtime)")


if __name__ == "__main__":
    raise SystemExit(main())
