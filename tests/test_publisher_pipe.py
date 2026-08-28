"""F-17 Stage 6 — the transport, exercised against a REAL named pipe.

WHY THIS FILE EXISTS. The first mutation run over the composed path left twelve
survivors, and five of them lived here: remove `FILE_FLAG_FIRST_PIPE_INSTANCE`,
remove `PIPE_REJECT_REMOTE_CLIENTS`, raise the instance limit, drop the message
bound, or let the service host fall back when the SCM never launched it, and
nothing in the suite noticed. The constants were asserted; the BEHAVIOUR was
not, and a constant nobody passes to the OS protects nothing.

So these tests create real pipes, connect real clients, and read back what was
actually handed to `CreateNamedPipeW`. No admin rights are needed: a named pipe
is not a privileged object, which is precisely why the DACL on it has to be
right.
"""
from __future__ import annotations

import ctypes
import sys
import threading
import time
import unittest
from ctypes import wintypes as W
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gnosis.trust import pipe_server as ps
from gnosis.trust.pipe_server import (
    MAX_MESSAGE_BYTES,
    PipeServer,
    PipeSquatted,
    worker_pipe_sddl,
)
from gnosis.trust.service_host import (
    ERROR_FAILED_SERVICE_CONTROLLER_CONNECT,
    ERROR_SERVICE_ALREADY_RUNNING,
    ServiceHost,
)

WINDOWS_ONLY = unittest.skipUnless(sys.platform == "win32", "Windows-only")

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = W.HANDLE
_k32.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, ctypes.c_void_p,
                             W.DWORD, W.DWORD, W.HANDLE]
_k32.CreateNamedPipeW.restype = W.HANDLE
_k32.CreateNamedPipeW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.DWORD, W.DWORD,
                                  W.DWORD, W.DWORD, ctypes.c_void_p]
_k32.WriteFile.argtypes = [W.HANDLE, ctypes.c_void_p, W.DWORD,
                           ctypes.POINTER(W.DWORD), ctypes.c_void_p]
_k32.ReadFile.argtypes = [W.HANDLE, ctypes.c_void_p, W.DWORD,
                          ctypes.POINTER(W.DWORD), ctypes.c_void_p]
_k32.CloseHandle.argtypes = [W.HANDLE]

INVALID = W.HANDLE(-1).value
OPEN_EXISTING = 3
CLIENT_ACCESS = 0x00120083   # exactly what the DACL grants; no append bit

# A permissive descriptor: these tests are about the pipe's FLAGS and framing,
# not about who may open it. The DACL itself is asserted in the publisher tests
# and proved OS-real, across accounts, by the Stage 6 composition probe.
_TEST_SDDL = "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;WD)"


def _unique_pipe(tag: str) -> str:
    return rf"\\.\pipe\gnosis-test-{tag}-{time.time_ns()}"


def _client_send(name: str, message: bytes, *, timeout_s: float = 5.0) -> bytes | None:
    deadline = time.monotonic() + timeout_s
    handle = INVALID
    while time.monotonic() < deadline:
        handle = _k32.CreateFileW(name, CLIENT_ACCESS, 0, None, OPEN_EXISTING, 0, None)
        if handle not in (INVALID, None, 0):
            break
        time.sleep(0.02)
    if handle in (INVALID, None, 0):
        return None
    try:
        written = W.DWORD(0)
        _k32.WriteFile(handle, message, len(message), ctypes.byref(written), None)
        buffer = ctypes.create_string_buffer(4096)
        read = W.DWORD(0)
        if not _k32.ReadFile(handle, buffer, 4096, ctypes.byref(read), None):
            return None
        return buffer.raw[:read.value]
    finally:
        _k32.CloseHandle(handle)


class _ServerCase(unittest.TestCase):
    def serve(self, name: str, handler):  # type: ignore[no-untyped-def]
        server = PipeServer(name, _TEST_SDDL, handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5.0)
        self.addCleanup(server.stop)
        time.sleep(0.1)          # let the first instance exist
        return server


@WINDOWS_ONLY
class TestTheServerActuallySpeaks(_ServerCase):
    def test_a_request_round_trips(self):
        name = _unique_pipe("roundtrip")
        self.serve(name, lambda request, pid: f"SEEN:{request}")
        self.assertEqual(_client_send(name, b"PUBLISH run-1"), b"SEEN:PUBLISH run-1")

    def test_a_message_larger_than_the_bound_is_refused_not_parsed(self):
        # The mutant that removed this bound survived because nothing ever sent
        # an oversized message. Now something does.
        name = _unique_pipe("oversized")
        seen: list[str] = []

        def handler(request: str, pid: int) -> str:
            seen.append(request)
            return "HANDLED"

        self.serve(name, handler)
        reply = _client_send(name, b"PUBLISH " + b"a" * (MAX_MESSAGE_BYTES * 2))
        self.assertEqual(reply, b"REJECTED:oversized")
        self.assertEqual(seen, [], "an oversized message reached the parser")

    def test_a_handler_that_raises_becomes_a_refusal_not_a_dead_server(self):
        name = _unique_pipe("raiser")

        def handler(request: str, pid: int) -> str:
            raise RuntimeError("boom")

        self.serve(name, handler)
        self.assertEqual(_client_send(name, b"PUBLISH run-1"),
                         b"REJECTED:handler-error")
        # still serving: a Worker cannot kill the endpoint with a bad request
        self.assertEqual(_client_send(name, b"PUBLISH run-2"),
                         b"REJECTED:handler-error")


@WINDOWS_ONLY
class TestTheServerRefusesASquattedName(unittest.TestCase):
    def test_a_pre_existing_pipe_name_fails_the_server_closed(self):
        # The Worker creates the name first. The server must NOT attach to it.
        name = _unique_pipe("squat")
        squatter = _k32.CreateNamedPipeW(name, 0x00000003, 0x00000004, 1,
                                         512, 512, 0, None)
        self.assertNotIn(squatter, (INVALID, None, 0), "could not create the squat")
        try:
            server = PipeServer(name, _TEST_SDDL, lambda request, pid: "NEVER")
            with self.assertRaises(PipeSquatted):
                server._create_instance()
        finally:
            _k32.CloseHandle(squatter)


@WINDOWS_ONLY
class TestWhatIsActuallyHandedToTheOS(unittest.TestCase):
    """Constants prove nothing until they reach `CreateNamedPipeW`."""

    def test_the_creation_flags_are_the_ones_the_design_requires(self):
        recorded: list[tuple[int, int, int]] = []
        original = ps._k32.CreateNamedPipeW

        def spy(name, open_mode, pipe_mode, max_instances, out_buf, in_buf,
                timeout, security):  # type: ignore[no-untyped-def]
            recorded.append((open_mode, pipe_mode, max_instances))
            return original(name, open_mode, pipe_mode, max_instances, out_buf,
                            in_buf, timeout, security)

        ps._k32.CreateNamedPipeW = spy
        try:
            name = _unique_pipe("flags")
            server = PipeServer(name, _TEST_SDDL, lambda request, pid: "X")
            handle = server._create_instance()
            _k32.CloseHandle(handle)
        finally:
            ps._k32.CreateNamedPipeW = original

        self.assertEqual(len(recorded), 1)
        open_mode, pipe_mode, max_instances = recorded[0]
        self.assertTrue(open_mode & ps.FILE_FLAG_FIRST_PIPE_INSTANCE,
                        "the server would attach to a name it did not create")
        self.assertTrue(pipe_mode & ps.PIPE_REJECT_REMOTE_CLIENTS,
                        "a remote client could reach the trusted endpoint")
        self.assertTrue(pipe_mode & ps.PIPE_TYPE_MESSAGE)
        self.assertEqual(max_instances, 1,
                         "more than one instance of the trusted name may exist")


class TestTheSddlWithholdsTheAppendBit(unittest.TestCase):
    def test_no_shorthand_that_includes_create_pipe_instance_appears(self):
        sddl = worker_pipe_sddl("S-1-5-21-1-2-3-1001", "S-1-5-80-1-2-3-4-5")
        worker_ace = [part for part in sddl.split("(") if "S-1-5-21-1-2-3-1001" in part]
        self.assertEqual(len(worker_ace), 1)
        self.assertNotIn("GA", worker_ace[0])
        self.assertNotIn("GW", worker_ace[0])
        self.assertNotIn("FW", worker_ace[0])
        self.assertNotIn("FA", worker_ace[0])


@WINDOWS_ONLY
class TestTheServiceHostRefusesToPretend(unittest.TestCase):
    def test_a_process_the_scm_never_launched_fails_closed(self):
        # This test process is not a service, so the dispatcher must refuse.
        # The mutant that returned quietly instead of raising survived because
        # nothing ever called `run()` outside a service.
        #
        # THE PROPERTY IS THAT IT RAISES, not which code it raises with. An
        # earlier version of this test pinned 1063 and went red only when run
        # after another test in the same process, because a SECOND
        # StartServiceCtrlDispatcher call answers 1056 (ALREADY_RUNNING)
        # instead of 1063 (never connected). Both mean the same thing here -
        # this process is not serving as a service - so both are accepted and
        # the over-specified assertion is gone.
        messages: list[str] = []
        host = ServiceHost("GnosisNotAService",
                           on_start=lambda stop: None, on_stop=lambda: None,
                           log=messages.append)
        with self.assertRaises(OSError) as caught:
            host.run()
        message = str(caught.exception)
        self.assertIn("StartServiceCtrlDispatcher failed", message)
        self.assertTrue(
            any(str(code) in message
                for code in (ERROR_FAILED_SERVICE_CONTROLLER_CONNECT,
                             ERROR_SERVICE_ALREADY_RUNNING)),
            f"unexpected dispatcher failure: {message}")


if __name__ == "__main__":
    unittest.main()
