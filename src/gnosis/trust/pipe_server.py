"""The named pipe the Worker may talk to, and nothing more.

THE AUTHORIZATION ROOT IS THE DACL, NOT THE CLIENT.

The kernel decides who may open this pipe, because the kernel is the only party
in the exchange the Worker cannot argue with. The client's process id is read
and logged, but it is FORENSIC ONLY: a pid is a number the kernel will happily
reuse, and asking a client who it is and believing the answer is not
authentication. Authorization is the pipe DACL plus the trusted
`RunIdentity.owner_worker_sid` the publisher checks afterwards.

WHY THE WORKER IS NOT GRANTED GENERIC_WRITE.

For a named pipe, `FILE_APPEND_DATA` and `FILE_CREATE_PIPE_INSTANCE` are the
same bit. Granting the Worker a convenient `GW` in the SDDL would therefore
grant it the right to CREATE INSTANCES OF THIS PIPE - to become a second server
on the trusted name. The Worker gets the individual rights it needs to connect
and exchange one message, and not that bit.

WHY FIRST_PIPE_INSTANCE IS NOT AN OPTIMISATION.

If the Worker creates the pipe name first, `FILE_FLAG_FIRST_PIPE_INSTANCE`
makes the server's creation FAIL. That failure is the correct outcome and is
propagated: the server never attaches to a pipe it did not create, never retries
into an existing name, and never falls back to another name. A publisher that
recovered gracefully from squatting would be a publisher that could be lured
into someone else's pipe.
"""
from __future__ import annotations

import ctypes as C
from collections.abc import Callable
from ctypes import wintypes as W
from typing import Any

from gnosis.trust.launch import AuthorityUnavailable

_k32: Any = C.WinDLL("kernel32", use_last_error=True)
_adv: Any = C.WinDLL("advapi32", use_last_error=True)

INVALID_HANDLE = W.HANDLE(-1).value
PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
ERROR_PIPE_CONNECTED = 535
GENERIC_READ = 0x80000000
OPEN_EXISTING = 3

# One instance, one message, bounded. A request larger than this is refused
# before anything tries to parse it.
MAX_INSTANCES = 1
MAX_MESSAGE_BYTES = 512


class SECURITY_ATTRIBUTES(C.Structure):
    _fields_ = (("nLength", W.DWORD), ("lpSecurityDescriptor", C.c_void_p),
                ("bInheritHandle", W.BOOL))


_k32.CreateNamedPipeW.restype = W.HANDLE
_k32.CreateNamedPipeW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.DWORD, W.DWORD,
                                  W.DWORD, W.DWORD, C.c_void_p]
_k32.CreateFileW.restype = W.HANDLE
_k32.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD,
                             W.DWORD, W.HANDLE]
_k32.ConnectNamedPipe.argtypes = [W.HANDLE, C.c_void_p]
_k32.ConnectNamedPipe.restype = W.BOOL
_k32.DisconnectNamedPipe.argtypes = [W.HANDLE]
_k32.ReadFile.argtypes = [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
_k32.ReadFile.restype = W.BOOL
_k32.WriteFile.argtypes = [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
_k32.WriteFile.restype = W.BOOL
_k32.FlushFileBuffers.argtypes = [W.HANDLE]
_k32.CloseHandle.argtypes = [W.HANDLE]
_k32.GetNamedPipeClientProcessId.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
_k32.GetNamedPipeClientProcessId.restype = W.BOOL
_adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
    W.LPCWSTR, W.DWORD, C.POINTER(C.c_void_p), C.c_void_p]
_adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = W.BOOL

SDDL_REVISION_1 = 1


# The Worker's access mask, spelled out bit by bit because the SDDL shorthand is
# WRONG here in a way that is easy to miss:
#
#   `FW` (FILE_GENERIC_WRITE) and `GW` (GENERIC_WRITE) both include
#   FILE_APPEND_DATA (0x0004) - and for a named pipe that bit IS
#   FILE_CREATE_PIPE_INSTANCE. Granting the Worker either shorthand would grant
#   it the right to become a server on this name, which is precisely the attack
#   FILE_FLAG_FIRST_PIPE_INSTANCE exists to make fail.
#
# So the mask is explicit, and the append bit is simply not in it:
#
#   0x00000001  FILE_READ_DATA          read the reply
#   0x00000002  FILE_WRITE_DATA         write the request
#   0x00000080  FILE_READ_ATTRIBUTES    open the handle
#   0x00020000  READ_CONTROL            read the descriptor (diagnosable)
#   0x00100000  SYNCHRONIZE             wait on the handle
#
# NOT 0x00000004 FILE_APPEND_DATA / FILE_CREATE_PIPE_INSTANCE.
WORKER_PIPE_ACCESS = 0x00120083


def worker_pipe_sddl(worker_sid: str, service_sid: str) -> str:
    """The pipe's security descriptor, written out rather than defaulted.

    `D:P` makes the DACL protected, so nothing is inherited into it: the rights
    on this object are the rights written here and not whatever a parent
    container happens to say. The service owns the object; SYSTEM and
    Administrators keep full control so the machine stays administrable, which
    is a T4 concession already declared out of scope.
    """
    return (f"O:{service_sid}"
            f"D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;{service_sid})"
            f"(A;;0x{WORKER_PIPE_ACCESS:08X};;;{worker_sid})")


def _security_descriptor(sddl: str) -> C.c_void_p:
    psd = C.c_void_p()
    if not _adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, SDDL_REVISION_1, C.byref(psd), None):
        raise AuthorityUnavailable(
            f"the pipe security descriptor is not valid SDDL "
            f"(error {C.get_last_error()}): {sddl}")
    return psd


class PipeSquatted(AuthorityUnavailable):
    """The pipe name already existed, so the server refused to attach to it."""


class PipeServer:
    """A single-instance message pipe that serves one request per connection."""

    def __init__(self, name: str, sddl: str,
                 handler: Callable[[str, int], str],
                 log: Callable[[str], None] | None = None) -> None:
        self.name = name
        self.sddl = sddl
        self.handler = handler
        self._log = log
        self._stop = False
        self._handle: int | None = None
        self._keepalive: object = None

    def _stopping(self) -> bool:
        """Read through a call, not the attribute directly.

        `stop()` runs on the SCM control thread, so this value can change
        between two statements of `serve_forever`. Reading the attribute
        inline lets a checker narrow it to False for the rest of the loop
        body and call the shutdown branch dead code - which it is not.
        """
        return self._stop

    def _note(self, message: str) -> None:
        if self._log is not None:
            self._log(message)

    def _create_instance(self) -> int:
        psd = _security_descriptor(self.sddl)
        attributes = SECURITY_ATTRIBUTES(C.sizeof(SECURITY_ATTRIBUTES), psd, False)
        handle = _k32.CreateNamedPipeW(
            self.name,
            PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
            (PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT
             | PIPE_REJECT_REMOTE_CLIENTS),
            MAX_INSTANCES, MAX_MESSAGE_BYTES, MAX_MESSAGE_BYTES, 0,
            C.byref(attributes))
        # The descriptor must outlive the call: the pipe references it.
        self._keepalive = (psd, attributes)
        if handle in (INVALID_HANDLE, None, 0):
            error = C.get_last_error()
            # ACCESS_DENIED(5), PIPE_BUSY(231) and ALREADY_EXISTS(183) all mean
            # the same thing here: somebody else holds this name. FAIL CLOSED.
            raise PipeSquatted(
                f"could not create the FIRST instance of {self.name} "
                f"(error {error}); the name is already taken and this server "
                "will not attach to a pipe it did not create")
        return int(handle)

    def serve_forever(self) -> None:
        while True:
            if self._stopping():
                break
            self._handle = self._create_instance()
            connected = _k32.ConnectNamedPipe(self._handle, None)
            if self._stopping():
                _k32.CloseHandle(self._handle)
                break
            if not connected and C.get_last_error() not in (0, ERROR_PIPE_CONNECTED):
                _k32.CloseHandle(self._handle)
                continue
            client_pid = W.DWORD(0)
            _k32.GetNamedPipeClientProcessId(self._handle, C.byref(client_pid))
            reply = self._serve_one(client_pid.value)
            raw = reply.encode("utf-8")[:MAX_MESSAGE_BYTES]
            written = W.DWORD(0)
            _k32.WriteFile(self._handle, raw, len(raw), C.byref(written), None)
            _k32.FlushFileBuffers(self._handle)
            _k32.DisconnectNamedPipe(self._handle)
            _k32.CloseHandle(self._handle)
            self._handle = None

    def _serve_one(self, client_pid: int) -> str:
        buffer = (C.c_char * MAX_MESSAGE_BYTES)()
        read = W.DWORD(0)
        if not _k32.ReadFile(self._handle, buffer, MAX_MESSAGE_BYTES,
                             C.byref(read), None):
            return "REJECTED:read-failed"
        raw = buffer.raw[:read.value]
        if len(raw) >= MAX_MESSAGE_BYTES:
            return "REJECTED:oversized"
        try:
            request = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            return "REJECTED:bad-request"
        self._note(f"request from pid={client_pid} bytes={len(raw)}")
        try:
            return self.handler(request, client_pid)
        except Exception as exc:  # noqa: BLE001 - a bad request never kills the server
            self._note(f"handler error: {exc!r}")
            return "REJECTED:handler-error"

    def stop(self) -> None:
        """Unblock a synchronous ConnectNamedPipe by connecting to it once.

        Closing the handle does NOT reliably wake a blocked ConnectNamedPipe, so
        the stop flag is set first and then a throwaway client connection lets
        the serve loop notice it.
        """
        self._stop = True
        handle = _k32.CreateFileW(self.name, GENERIC_READ, 0, None,
                                  OPEN_EXISTING, 0, None)
        if handle not in (INVALID_HANDLE, None, 0):
            _k32.CloseHandle(handle)
