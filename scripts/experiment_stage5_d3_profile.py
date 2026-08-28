"""F-17 Stage 5 — D3: can `LoadUserProfileW` be removed from the launcher?

The blocking finding: the launcher called `LogonUserW` + `LoadUserProfileW` to
build the Worker's environment, which makes `SeBackupPrivilege` and
`SeRestorePrivilege` a permanent architectural dependency. Those privileges being
present on this machine does not authorize depending on them —
REACHABLE != AUTHORIZED DEPENDENCY, the same rule that rejected
`SeImpersonatePrivilege`.

This experiment MEASURES, OS-real, what `CreateProcessWithLogonW` actually
produces for each way of supplying `lpEnvironment`, so the choice is made on
evidence rather than on what MSDN can be read to imply:

    A  lpEnvironment = NULL, LOGON_WITH_PROFILE
       Does seclogon build the environment from the WORKER's profile, or does
       the child inherit the DIRECTOR's environment (and its secrets)?

    B  lpEnvironment = a MINIMAL explicit block built by the launcher with no
       profile call and no Director copy. Does the bootstrap then start, and can
       it recover the correct profile environment FROM ITS OWN TOKEN — which
       needs no privilege, because it is the caller's own token and
       LOGON_WITH_PROFILE has already loaded the profile?

    C  the CURRENT path (LogonUser + LoadUserProfile + CreateEnvironmentBlock),
       as the baseline to beat.

Disposable infrastructure only, reusing the Stage-5 probe's setup and rollback.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/experiment_stage5_d3_profile.py [--out PATH]
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
from ctypes import wintypes as W
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import probe_stage5_worker_launcher as P

from gnosis.trust.launch_spec import LaunchSpec, launch_spec_path, seal_launch_spec
from gnosis.trust.worker_launcher import (
    _PROCESS_INFORMATION,
    _STARTUPINFOW,
    CREATE_NO_WINDOW,
    CREATE_SUSPENDED,
    LOGON_WITH_PROFILE,
    _a32,
    _k32,
    build_transport_command,
)

# SELF-CONTAINED ON PURPOSE. Options B and C exercise APIs the production
# launcher NO LONGER CALLS — that removal is this experiment's whole result — so
# the declarations live here rather than in the launcher. Keeping them here is
# what lets a reviewer re-run the comparison without the production module
# carrying a privilege-requiring API it has no use for.
_userenv = ctypes.WinDLL("userenv", use_last_error=True)
CREATE_UNICODE_ENVIRONMENT = 0x00000400
LOGON32_LOGON_INTERACTIVE = 2
LOGON32_PROVIDER_DEFAULT = 0
PI_NOUI = 0x00000001


class _PROFILEINFOW(ctypes.Structure):
    _fields_ = [("dwSize", W.DWORD), ("dwFlags", W.DWORD),
                ("lpUserName", W.LPWSTR), ("lpProfilePath", W.LPWSTR),
                ("lpDefaultPath", W.LPWSTR), ("lpServerName", W.LPWSTR),
                ("lpPolicyPath", W.LPWSTR), ("hProfile", W.HANDLE)]


_a32.LogonUserW.argtypes = [W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, W.DWORD, W.DWORD,
                            ctypes.POINTER(W.HANDLE)]
_a32.LogonUserW.restype = W.BOOL
_userenv.CreateEnvironmentBlock.argtypes = [ctypes.POINTER(ctypes.c_void_p),
                                            W.HANDLE, W.BOOL]
_userenv.CreateEnvironmentBlock.restype = W.BOOL
_userenv.DestroyEnvironmentBlock.argtypes = [ctypes.c_void_p]
_userenv.LoadUserProfileW.argtypes = [W.HANDLE, ctypes.POINTER(_PROFILEINFOW)]
_userenv.LoadUserProfileW.restype = W.BOOL
_userenv.UnloadUserProfile.argtypes = [W.HANDLE, W.HANDLE]


def _environment_block_for_token(token: W.HANDLE) -> dict[str, str]:
    block = ctypes.c_void_p()
    if not _userenv.CreateEnvironmentBlock(ctypes.byref(block), token, False):
        raise SystemExit("CreateEnvironmentBlock failed")
    try:
        out: dict[str, str] = {}
        address = block.value or 0
        while True:
            entry = ctypes.wstring_at(address)
            if not entry:
                break
            address += (len(entry) + 1) * ctypes.sizeof(ctypes.c_wchar)
            if "=" in entry[1:]:
                name, _, value = entry[1:].partition("=")
                out[entry[0] + name] = value
        return out
    finally:
        _userenv.DestroyEnvironmentBlock(block)


def _encode_environment_block(env: dict[str, str]) -> ctypes.Array[ctypes.c_wchar]:
    parts = [f"{name}={value}" for name, value in
             sorted(env.items(), key=lambda item: item[0].upper())]
    raw = "\0".join(parts) + "\0\0"
    return ctypes.create_unicode_buffer(raw, len(raw))

SENTINEL = "GNOSIS_STAGE5_SECRET_SENTINEL"
SENTINEL_VALUE = "this-value-must-never-reach-the-worker"

# What the bootstrap genuinely needs from Windows to start at all. Nothing here
# comes from the Director's own environment: these are machine facts, and each
# is taken from a fixed OS location rather than copied from os.environ.
def minimal_machine_environment() -> dict[str, str]:
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    drive = windir[:2]
    return {
        "SystemRoot": windir,
        "SystemDrive": drive,
        "windir": windir,
        "COMSPEC": str(Path(windir) / "system32" / "cmd.exe"),
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "PATH": ";".join([str(Path(windir) / "system32"), windir,
                          str(Path(windir) / "system32" / "Wbem")]),
    }


WORKER_ENV_PROBE = r'''
import ctypes, json, os, sys
from ctypes import wintypes as W
out_path = sys.argv[1]
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
a32 = ctypes.WinDLL("advapi32", use_last_error=True)
ue = ctypes.WinDLL("userenv", use_last_error=True)

result = {
    "USERPROFILE": os.environ.get("USERPROFILE", ""),
    "APPDATA": os.environ.get("APPDATA", ""),
    "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
    "USERNAME": os.environ.get("USERNAME", ""),
    "TEMP": os.environ.get("TEMP", ""),
    "env_names": sorted(os.environ),
    "sentinel_present": "GNOSIS_STAGE5_SECRET_SENTINEL" in os.environ,
    "sys_executable": sys.executable,
    "sys_path0": sys.path[0] if sys.path else "",
    "cwd": os.getcwd(),
    "flags_isolated": bool(sys.flags.isolated),
    "flags_no_user_site": bool(sys.flags.no_user_site),
}

# CAN THE BOOTSTRAP RECOVER THE PROFILE ENVIRONMENT FROM ITS OWN TOKEN?
# This needs no privilege: it is the caller's own token, and under
# LOGON_WITH_PROFILE the profile is already loaded by seclogon.
try:
    a32.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, ctypes.POINTER(W.HANDLE)]
    tok = W.HANDLE()
    a32.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(tok))
    ue.CreateEnvironmentBlock.argtypes = [ctypes.POINTER(ctypes.c_void_p), W.HANDLE, W.BOOL]
    ue.DestroyEnvironmentBlock.argtypes = [ctypes.c_void_p]
    block = ctypes.c_void_p()
    own = {}
    if ue.CreateEnvironmentBlock(ctypes.byref(block), tok, False):
        addr = block.value or 0
        while True:
            entry = ctypes.wstring_at(addr)
            if not entry:
                break
            addr += (len(entry) + 1) * ctypes.sizeof(ctypes.c_wchar)
            if "=" in entry[1:]:
                name, _, value = entry[1:].partition("=")
                own[entry[0] + name] = value
        ue.DestroyEnvironmentBlock(block)
    result["own_block_ok"] = bool(own)
    result["own_USERPROFILE"] = own.get("USERPROFILE", "")
    result["own_APPDATA"] = own.get("APPDATA", "")
    result["own_count"] = len(own)
    result["own_sentinel"] = "GNOSIS_STAGE5_SECRET_SENTINEL" in own
    k32.CloseHandle(tok)
except Exception as exc:
    result["own_block_ok"] = "error:" + type(exc).__name__

# GetUserProfileDirectoryW on our own token, the cheapest possible answer
try:
    ue.GetUserProfileDirectoryW.argtypes = [W.HANDLE, W.LPWSTR, ctypes.POINTER(W.DWORD)]
    tok = W.HANDLE()
    a32.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(tok))
    size = W.DWORD(0)
    ue.GetUserProfileDirectoryW(tok, None, ctypes.byref(size))
    buf = ctypes.create_unicode_buffer(size.value)
    ok = ue.GetUserProfileDirectoryW(tok, buf, ctypes.byref(size))
    result["own_profile_dir"] = buf.value if ok else ""
    k32.CloseHandle(tok)
except Exception as exc:
    result["own_profile_dir"] = "error:" + type(exc).__name__

with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(result, fh)
'''


def _launch(probe: P.Probe, password: str, launch_id: str,
            env: dict[str, str] | None, *, use_profile: bool = True,
            explicit_profile_call: bool = False) -> tuple[int, dict[str, object]]:
    """One raw CreateProcessWithLogonW launch with a chosen lpEnvironment."""
    helper = probe.tools / "worker_env_probe.py"
    payload = probe.work / f"{launch_id}.json"
    argv = [str(probe.runtime), "-I", str(helper), str(payload)]
    spec = LaunchSpec(launch_id=launch_id, executable=str(probe.runtime),
                      argv=tuple(argv), cwd=str(probe.work),
                      stdout_path=str(probe.work / f"{launch_id}.out"),
                      stderr_path=str(probe.work / f"{launch_id}.err"))
    digest = seal_launch_spec(probe.launch, spec)
    command = build_transport_command(probe.runtime,
                                      launch_spec_path(probe.launch, launch_id), digest)

    block = None
    if explicit_profile_call:
        # Option C baseline: LogonUser + LoadUserProfile + CreateEnvironmentBlock
        token = W.HANDLE()
        if not _a32.LogonUserW(probe.account.username, probe.account.domain or None,
                               password, LOGON32_LOGON_INTERACTIVE,
                               LOGON32_PROVIDER_DEFAULT, ctypes.byref(token)):
            raise SystemExit("LogonUserW failed in the baseline option")
        info = _PROFILEINFOW()
        info.dwSize = ctypes.sizeof(info)
        info.dwFlags = PI_NOUI
        info.lpUserName = probe.account.username
        loaded = bool(_userenv.LoadUserProfileW(token, ctypes.byref(info)))
        env = _environment_block_for_token(token) if loaded else {}
        if loaded:
            _userenv.UnloadUserProfile(token, info.hProfile)
        _k32.CloseHandle(token)
    if env is not None:
        block = _encode_environment_block(env)

    startup = _STARTUPINFOW()
    startup.cb = ctypes.sizeof(startup)
    proc_info = _PROCESS_INFORMATION()
    buffer = ctypes.create_unicode_buffer(command, len(command) + 1)
    flags = CREATE_SUSPENDED | CREATE_NO_WINDOW
    if env is not None:
        flags |= CREATE_UNICODE_ENVIRONMENT
    ok = _a32.CreateProcessWithLogonW(
        probe.account.username, probe.account.domain or None, password,
        LOGON_WITH_PROFILE if use_profile else 0, str(probe.runtime), buffer,
        flags, ctypes.byref(block) if block is not None else None,
        str(probe.work), ctypes.byref(startup), ctypes.byref(proc_info))
    if not ok:
        raise SystemExit(f"CreateProcessWithLogonW failed "
                         f"(winerr {ctypes.get_last_error()})")
    _k32.ResumeThread(proc_info.hThread)
    _k32.WaitForSingleObject(proc_info.hProcess, 180000)
    code = W.DWORD(0)
    _k32.GetExitCodeProcess(proc_info.hProcess, ctypes.byref(code))
    _k32.CloseHandle(proc_info.hThread)
    _k32.CloseHandle(proc_info.hProcess)
    data: dict[str, object] = {}
    if payload.is_file():
        data = json.loads(payload.read_text(encoding="utf-8"))
    else:
        err = probe.work / f"{launch_id}.err"
        data = {"stderr": err.read_text(encoding="utf-8", errors="replace")[:400]
                if err.is_file() else "<no output>"}
    return int(code.value), data


def report(label: str, code: int, data: dict[str, object]) -> dict[str, bool]:
    worker = P.WORKER_NAME.lower()
    profile_ok = worker in str(data.get("USERPROFILE", "")).lower()
    appdata_ok = worker in str(data.get("APPDATA", "")).lower()
    sentinel = bool(data.get("sentinel_present"))
    P.say(f"   {label}")
    P.say(f"     exit code                : {code}")
    P.say(f"     env variables            : {len(data.get('env_names') or [])}")
    P.say(f"     USERPROFILE              : {data.get('USERPROFILE', '')!r}")
    P.say(f"     APPDATA                  : {data.get('APPDATA', '')!r}")
    P.say(f"     USERNAME                 : {data.get('USERNAME', '')!r}")
    P.say(f"     DIRECTOR SENTINEL present: {sentinel}")
    P.say(f"     own-token profile dir    : {data.get('own_profile_dir', '')!r}")
    P.say(f"     own-token env block ok   : {data.get('own_block_ok')} "
          f"({data.get('own_count', 0)} vars)")
    P.say(f"     own-token USERPROFILE    : {data.get('own_USERPROFILE', '')!r}")
    P.say(f"     own-token sentinel       : {data.get('own_sentinel')}")
    P.say(f"     isolated / no-user-site  : {data.get('flags_isolated')} / "
          f"{data.get('flags_no_user_site')}")
    if "stderr" in data:
        P.say(f"     stderr                   : {data['stderr']!r}")
    P.say("")
    return {"started": code == 0, "profile_ok": profile_ok, "appdata_ok": appdata_ok,
            "no_sentinel": not sentinel,
            "own_profile_ok": worker in str(data.get("own_USERPROFILE", "")).lower()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    P.say("F-17 STAGE 5 — D3 EXPERIMENT: CAN LoadUserProfileW BE REMOVED?")
    P.say("=" * 78)
    P.say("REACHABLE != AUTHORIZED DEPENDENCY. The launcher currently calls")
    P.say("LogonUserW + LoadUserProfileW, which makes SeBackupPrivilege and")
    P.say("SeRestorePrivilege a permanent requirement. Measured here, not assumed.")
    P.say("")
    os.environ[SENTINEL] = SENTINEL_VALUE

    password = P.random_password()
    probe: P.Probe | None = None
    verdicts: dict[str, dict[str, bool]] = {}
    try:
        probe = P.setup(password)
        (probe.tools / "worker_env_probe.py").write_text(WORKER_ENV_PROBE,
                                                         encoding="utf-8")
        # re-apply the tool-root ACL so the new helper inherits it
        P.icacls(str(probe.tools), "/grant:r", f"*{probe.worker_sid}:(OI)(CI)(RX)")

        P.say("OPTION A — lpEnvironment = NULL, LOGON_WITH_PROFILE")
        P.say("-" * 78)
        code, data = _launch(probe, password, "d3a", None)
        verdicts["A"] = report("result:", code, data)

        P.say("OPTION B — MINIMAL explicit block, no profile call, no Director copy")
        P.say("-" * 78)
        code, data = _launch(probe, password, "d3b", minimal_machine_environment())
        verdicts["B"] = report("result:", code, data)

        P.say("OPTION C — BASELINE: LogonUser + LoadUserProfile + CreateEnvironmentBlock")
        P.say("-" * 78)
        code, data = _launch(probe, password, "d3c", None, explicit_profile_call=True)
        verdicts["C"] = report("result:", code, data)
    finally:
        del password
        os.environ.pop(SENTINEL, None)
        P.rollback(probe)

    P.say("")
    P.say("=" * 78)
    P.say("VERDICT")
    P.say("=" * 78)
    P.say(f"   {'option':<8s}{'starts':<9s}{'USERPROFILE':<14s}{'APPDATA':<10s}"
          f"{'no sentinel':<13s}{'own-token profile'}")
    for name in ("A", "B", "C"):
        v = verdicts.get(name, {})
        P.say(f"   {name:<8s}{v.get('started')!s:<9s}"
              f"{v.get('profile_ok')!s:<14s}{v.get('appdata_ok')!s:<10s}"
              f"{v.get('no_sentinel')!s:<13s}{v.get('own_profile_ok')}")
    if args.out:
        args.out.write_text("\n".join(P.OUT) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
