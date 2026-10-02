"""Windows account / SID / command primitives for provisioning (F-17 Stage 8).

The Win32 calls the Stage 5/6 probes proved OS-real, lifted into the source tree
so the production provisioner and the qualification probe share ONE
implementation instead of the probe owning it. Windows-only, ctypes-only, no
third-party dependency. Every call fails closed as data (a status/return code),
never by leaking a handle or an exception a caller cannot classify.
"""
from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes as W

_netapi = ctypes.WinDLL("netapi32", use_last_error=True)
_adv = ctypes.WinDLL("advapi32", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

USER_PRIV_USER = 1
UF_SCRIPT = 0x0001
UF_NORMAL_ACCOUNT = 0x0200
UF_DONT_EXPIRE_PASSWD = 0x10000


class USER_INFO_1(ctypes.Structure):
    _fields_ = (("usri1_name", W.LPWSTR), ("usri1_password", W.LPWSTR),
                ("usri1_password_age", W.DWORD), ("usri1_priv", W.DWORD),
                ("usri1_home_dir", W.LPWSTR), ("usri1_comment", W.LPWSTR),
                ("usri1_flags", W.DWORD), ("usri1_script_path", W.LPWSTR))


_netapi.NetUserAdd.argtypes = [W.LPCWSTR, W.DWORD, ctypes.c_void_p,
                               ctypes.POINTER(W.DWORD)]
_netapi.NetUserDel.argtypes = [W.LPCWSTR, W.LPCWSTR]
_adv.LookupAccountNameW.argtypes = [
    W.LPCWSTR, W.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(W.DWORD), W.LPWSTR,
    ctypes.POINTER(W.DWORD), ctypes.POINTER(W.DWORD)]
_adv.LookupAccountNameW.restype = W.BOOL
_adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(W.LPWSTR)]
_adv.ConvertSidToStringSidW.restype = W.BOOL
_k32.LocalFree.argtypes = [ctypes.c_void_p]


class AccountError(RuntimeError):
    """A worker-account operation failed; provisioning fails closed."""


def create_local_account(username: str, password: str, comment: str) -> None:
    """Create a dedicated non-admin local account (USER_PRIV_USER)."""
    info = USER_INFO_1(
        usri1_name=username, usri1_password=password, usri1_password_age=0,
        usri1_priv=USER_PRIV_USER, usri1_home_dir=None, usri1_comment=comment,
        usri1_flags=UF_SCRIPT | UF_NORMAL_ACCOUNT | UF_DONT_EXPIRE_PASSWD,
        usri1_script_path=None)
    parm = W.DWORD(0)
    status = _netapi.NetUserAdd(None, 1, ctypes.byref(info), ctypes.byref(parm))
    if status != 0:
        raise AccountError(
            f"NetUserAdd({username}) failed with status {status} "
            f"(parm {parm.value})")


def delete_local_account(username: str) -> int:
    """Delete a local account. Returns the NetUserDel status (0 = deleted,
    2221 = did not exist — both fine for an idempotent teardown)."""
    return int(_netapi.NetUserDel(None, username))


def account_exists(username: str) -> bool:
    try:
        resolve_sid(username)
        return True
    except AccountError:
        return False


def resolve_sid(name: str) -> str:
    """The canonical SID string for an account/group name, or raise."""
    sid_size = W.DWORD(0)
    dom_size = W.DWORD(0)
    use = W.DWORD(0)
    _adv.LookupAccountNameW(None, name, None, ctypes.byref(sid_size), None,
                            ctypes.byref(dom_size), ctypes.byref(use))
    if sid_size.value == 0:
        raise AccountError(
            f"LookupAccountName({name}) found nothing "
            f"(winerr {ctypes.get_last_error()})")
    sid = ctypes.create_string_buffer(sid_size.value)
    dom = ctypes.create_unicode_buffer(dom_size.value)
    if not _adv.LookupAccountNameW(None, name, sid, ctypes.byref(sid_size), dom,
                                   ctypes.byref(dom_size), ctypes.byref(use)):
        raise AccountError(
            f"LookupAccountName({name}) failed (winerr {ctypes.get_last_error()})")
    out = W.LPWSTR()
    if not _adv.ConvertSidToStringSidW(sid, ctypes.byref(out)):
        raise AccountError("ConvertSidToStringSid failed")
    try:
        return out.value or ""
    finally:
        _k32.LocalFree(out)


def run(argv: list[str]) -> tuple[int, str]:
    """Run a provisioning command (icacls, sc). rc-as-data; OEM-safe decode."""
    proc = subprocess.run(argv, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)
    return proc.returncode, (proc.stdout + proc.stderr).strip()
