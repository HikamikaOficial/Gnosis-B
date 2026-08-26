"""OS-real inspection of the CURRENT process token (ctypes only).

Proves, from inside the running service, what the operator's correction #3/#5
requires: service SID present, real restricted-SID list, integrity level,
groups, privileges (present/enabled/disabled), effective account, and whether
the token is write-restricted (IsTokenRestricted). Pure stdlib ctypes; no
pywin32 (keeps the TCB minimal).
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W

adv = C.WinDLL("advapi32", use_last_error=True)
k32 = C.WinDLL("kernel32", use_last_error=True)

# Prototypes — required on 64-bit so handles/pointers are not truncated to int.
k32.GetCurrentProcess.restype = W.HANDLE
k32.GetCurrentProcess.argtypes = []
k32.CloseHandle.argtypes = [W.HANDLE]
k32.LocalFree.argtypes = [W.HPVOID] if hasattr(W, "HPVOID") else [C.c_void_p]
adv.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
adv.OpenProcessToken.restype = W.BOOL
adv.GetTokenInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
adv.GetTokenInformation.restype = W.BOOL
adv.IsTokenRestricted.argtypes = [W.HANDLE]
adv.IsTokenRestricted.restype = W.BOOL
adv.ConvertSidToStringSidW.argtypes = [C.c_void_p, C.POINTER(W.LPWSTR)]
adv.ConvertSidToStringSidW.restype = W.BOOL
adv.LookupAccountSidW.argtypes = [W.LPCWSTR, C.c_void_p, W.LPWSTR, C.POINTER(W.DWORD),
                                  W.LPWSTR, C.POINTER(W.DWORD), C.POINTER(W.DWORD)]
adv.LookupAccountSidW.restype = W.BOOL
adv.LookupPrivilegeNameW.argtypes = [W.LPCWSTR, C.c_void_p, W.LPWSTR, C.POINTER(W.DWORD)]
adv.LookupPrivilegeNameW.restype = W.BOOL

TOKEN_QUERY = 0x0008
TokenUser, TokenGroups, TokenPrivileges = 1, 2, 3
TokenRestrictedSids, TokenIntegrityLevel = 11, 25
SE_PRIVILEGE_ENABLED = 0x2
SE_PRIVILEGE_ENABLED_BY_DEFAULT = 0x1
SE_PRIVILEGE_REMOVED = 0x4

INTEGRITY = {0x0000: "Untrusted", 0x1000: "Low", 0x2000: "Medium",
             0x2100: "MediumPlus", 0x3000: "High", 0x4000: "System"}


class SID_AND_ATTRIBUTES(C.Structure):
    _fields_ = [("Sid", C.c_void_p), ("Attributes", W.DWORD)]


class LUID(C.Structure):
    _fields_ = [("LowPart", W.DWORD), ("HighPart", W.LONG)]


class LUID_AND_ATTRIBUTES(C.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", W.DWORD)]


def _sid_str(psid: int) -> str:
    out = W.LPWSTR()
    if not adv.ConvertSidToStringSidW(C.c_void_p(psid), C.byref(out)):
        return "<sid?>"
    s = out.value or "<sid?>"
    k32.LocalFree(out)
    return s


def _account(psid: int) -> str:
    name = C.create_unicode_buffer(256)
    dom = C.create_unicode_buffer(256)
    cch1 = W.DWORD(256); cch2 = W.DWORD(256); use = W.DWORD()
    if adv.LookupAccountSidW(None, C.c_void_p(psid), name, C.byref(cch1),
                             dom, C.byref(cch2), C.byref(use)):
        return f"{dom.value}\\{name.value}"
    return "<unresolved>"


def _priv_name(luid: LUID) -> str:
    buf = C.create_unicode_buffer(256); cch = W.DWORD(256)
    if adv.LookupPrivilegeNameW(None, C.byref(luid), buf, C.byref(cch)):
        return buf.value or "<priv?>"
    return "<priv?>"


def _open() -> W.HANDLE:
    h = W.HANDLE()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), TOKEN_QUERY, C.byref(h)):
        raise OSError(f"OpenProcessToken failed {C.get_last_error()}")
    return h


def _query(h: W.HANDLE, cls: int) -> bytes:
    size = W.DWORD(0)
    adv.GetTokenInformation(h, cls, None, 0, C.byref(size))
    buf = (C.c_byte * size.value)()
    if not adv.GetTokenInformation(h, cls, buf, size, C.byref(size)):
        raise OSError(f"GetTokenInformation cls={cls} failed {C.get_last_error()}")
    return bytes(buf), buf  # keep buf alive


def _counted_array(buf, elem_type):
    """A leading DWORD count followed by elem_type[count], with the array
    aligned to elem_type's alignment (pointer-aligned structs get padding
    after the count on 64-bit)."""
    count = C.cast(buf, C.POINTER(W.DWORD))[0]
    align = C.alignment(elem_type)
    off = ((C.sizeof(W.DWORD) + align - 1) // align) * align
    arr = C.cast(C.addressof(buf) + off, C.POINTER(elem_type * count))[0]
    return count, arr


def dump() -> dict:
    h = _open()
    out: dict = {}

    _, ubuf = _query(h, TokenUser)
    sa = C.cast(ubuf, C.POINTER(SID_AND_ATTRIBUTES))[0]
    out["user_sid"] = _sid_str(sa.Sid)
    out["account"] = _account(sa.Sid)

    # groups
    _, gbuf = _query(h, TokenGroups)
    _, arr = _counted_array(gbuf, SID_AND_ATTRIBUTES)
    out["groups"] = sorted({_sid_str(g.Sid) for g in arr})

    # privileges present / enabled
    _, pbuf = _query(h, TokenPrivileges)
    _, parr = _counted_array(pbuf, LUID_AND_ATTRIBUTES)
    present, enabled, disabled = [], [], []
    for p in parr:
        nm = _priv_name(p.Luid)
        present.append(nm)
        if p.Attributes & SE_PRIVILEGE_REMOVED:
            continue
        if p.Attributes & (SE_PRIVILEGE_ENABLED | SE_PRIVILEGE_ENABLED_BY_DEFAULT):
            enabled.append(nm)
        else:
            disabled.append(nm)
    out["privileges_present"] = sorted(present)
    out["privileges_enabled"] = sorted(enabled)
    out["privileges_disabled"] = sorted(disabled)

    # integrity level
    _, ibuf = _query(h, TokenIntegrityLevel)
    il = C.cast(ibuf, C.POINTER(SID_AND_ATTRIBUTES))[0]
    # integrity RID = last sub-authority
    n_sub = C.cast(il.Sid + 1, C.POINTER(C.c_ubyte))[0]
    rid = C.cast(il.Sid + 8 + 4 * (n_sub - 1), C.POINTER(W.DWORD))[0]
    out["integrity_sid"] = _sid_str(il.Sid)
    out["integrity_level"] = INTEGRITY.get(rid, hex(rid))

    # restricted SIDs + is-restricted
    out["is_token_restricted"] = bool(adv.IsTokenRestricted(h))
    try:
        _, rbuf = _query(h, TokenRestrictedSids)
        rcount, rarr = _counted_array(rbuf, SID_AND_ATTRIBUTES)
        out["restricted_sids"] = sorted({_sid_str(r.Sid) for r in rarr}) if rcount else []
    except OSError as exc:
        out["restricted_sids"] = f"<query failed: {exc}>"

    k32.CloseHandle(h)
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(dump(), indent=2))
