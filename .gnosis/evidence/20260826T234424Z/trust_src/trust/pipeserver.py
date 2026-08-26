"""Named-pipe server for the P2 trusted publisher (ctypes only).

Security properties enforced here (operator corrections #9, #10):
- local pipe, PIPE_REJECT_REMOTE_CLIENTS;
- FILE_FLAG_FIRST_PIPE_INSTANCE: if the name already exists (a squatter
  pre-created it) creation FAILS CLOSED — the server never attaches to a pipe
  it did not create;
- an explicit SDDL security descriptor; the worker is NOT granted GENERIC_WRITE
  (whose FILE_APPEND_DATA bit == FILE_CREATE_PIPE_INSTANCE for pipes) — only the
  minimal individual rights to connect and exchange one message.
The client PID is read for FORENSIC logging only; it is NOT the trust root —
authorization is the pipe DACL (kernel) plus RunIdentity.owner (publisher).
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from typing import Callable

k32 = C.WinDLL("kernel32", use_last_error=True)
adv = C.WinDLL("advapi32", use_last_error=True)

INVALID = W.HANDLE(-1).value
PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
ERROR_PIPE_CONNECTED = 535
ERROR_BROKEN_PIPE = 109
ERROR_NO_DATA = 232

MAX_MSG = 512  # oversized requests are rejected before parse


class SECURITY_ATTRIBUTES(C.Structure):
    _fields_ = [("nLength", W.DWORD), ("lpSecurityDescriptor", C.c_void_p),
                ("bInheritHandle", W.BOOL)]


k32.CreateNamedPipeW.restype = W.HANDLE
k32.CreateNamedPipeW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.DWORD, W.DWORD,
                                 W.DWORD, W.DWORD, C.c_void_p]
k32.CreateFileW.restype = W.HANDLE
k32.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
k32.ConnectNamedPipe.argtypes = [W.HANDLE, C.c_void_p]
k32.ConnectNamedPipe.restype = W.BOOL
k32.DisconnectNamedPipe.argtypes = [W.HANDLE]
k32.ReadFile.argtypes = [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
k32.ReadFile.restype = W.BOOL
k32.WriteFile.argtypes = [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
k32.WriteFile.restype = W.BOOL
k32.FlushFileBuffers.argtypes = [W.HANDLE]
k32.CloseHandle.argtypes = [W.HANDLE]
k32.GetNamedPipeClientProcessId = getattr(k32, "GetNamedPipeClientProcessId", None)
if k32.GetNamedPipeClientProcessId:
    k32.GetNamedPipeClientProcessId.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
    k32.GetNamedPipeClientProcessId.restype = W.BOOL
adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
    W.LPCWSTR, W.DWORD, C.POINTER(C.c_void_p), C.c_void_p]
adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = W.BOOL


def _sd_from_sddl(sddl: str) -> C.c_void_p:
    psd = C.c_void_p()
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, C.byref(psd), None):
        raise OSError(f"bad SDDL ({C.get_last_error()}): {sddl}")
    return psd


class PipeServer:
    def __init__(self, name: str, sddl: str, handler: Callable[[str, int], str], log):
        self.name = name
        self.sddl = sddl
        self.handler = handler
        self.log = log
        self._stop = False
        self._h = None

    def _create_instance(self) -> W.HANDLE:
        psd = _sd_from_sddl(self.sddl)
        sa = SECURITY_ATTRIBUTES(C.sizeof(SECURITY_ATTRIBUTES), psd, False)
        h = k32.CreateNamedPipeW(
            self.name,
            PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
            1,            # nMaxInstances = 1: strictly single instance
            MAX_MSG, MAX_MSG, 0, C.byref(sa))
        self._keepalive = (psd, sa)  # keep the SD alive for the pipe's lifetime
        if h == INVALID or h is None:
            err = C.get_last_error()
            # ERROR_ACCESS_DENIED(5)/ERROR_PIPE_BUSY(231)/ALREADY_EXISTS(183) here
            # means the name is already taken (squatting) -> FAIL CLOSED, never attach.
            raise OSError(f"CreateNamedPipe FIRST_INSTANCE failed err={err} "
                          f"(name taken? refuse to attach)")
        return h

    def serve_forever(self) -> None:
        while not self._stop:
            self._h = self._create_instance()
            ok = k32.ConnectNamedPipe(self._h, None)
            if self._stop:
                k32.CloseHandle(self._h); break
            if not ok and C.get_last_error() not in (0, ERROR_PIPE_CONNECTED):
                k32.CloseHandle(self._h); continue
            pid = W.DWORD(0)
            if k32.GetNamedPipeClientProcessId:
                k32.GetNamedPipeClientProcessId(self._h, C.byref(pid))
            reply = self._handle_one(pid.value)
            b = reply.encode("utf-8")[:MAX_MSG]
            wr = W.DWORD(0)
            k32.WriteFile(self._h, b, len(b), C.byref(wr), None)
            k32.FlushFileBuffers(self._h)
            k32.DisconnectNamedPipe(self._h)
            k32.CloseHandle(self._h); self._h = None

    def _handle_one(self, client_pid: int) -> str:
        buf = (C.c_char * MAX_MSG)()
        rd = W.DWORD(0)
        ok = k32.ReadFile(self._h, buf, MAX_MSG, C.byref(rd), None)
        if not ok:
            return "REJECTED:read-failed"
        raw = bytes(buf[:rd.value])
        if len(raw) >= MAX_MSG:
            return "REJECTED:oversized"
        try:
            req = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            return "REJECTED:malformed-encoding"
        self.log(f"request from pid={client_pid} bytes={len(raw)}")
        try:
            return self.handler(req, client_pid)
        except Exception as exc:  # never crash the server on a bad request
            self.log(f"handler error: {exc!r}")
            return "REJECTED:handler-error"

    def stop(self) -> None:
        # Closing the handle does NOT reliably unblock a synchronous
        # ConnectNamedPipe; a self-connect does. Set stop first so the serve
        # loop breaks the moment ConnectNamedPipe returns.
        self._stop = True
        try:
            h = k32.CreateFileW(self.name, 0x80000000, 0, None, 3, 0, None)  # GENERIC_READ, OPEN_EXISTING
            if h not in (INVALID, None):
                k32.CloseHandle(h)
        except OSError:
            pass
