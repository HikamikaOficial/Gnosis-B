import ctypes
import os
import subprocess
import threading
import uuid
from ctypes import wintypes as w
from unittest.mock import patch

import pytest

from gnosis.director.publisher_client import PipePublisherClient, PublisherClientError


@pytest.mark.skipif(os.name != "nt", reason="real Windows named pipe")
@pytest.mark.parametrize("reply", [b"ANCHORED:0123456789ab:seq=1", None, b"x" * 300])
def test_real_pipe_response_hang_and_oversize_are_bounded(reply) -> None:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateNamedPipeW.argtypes = (w.LPCWSTR, w.DWORD, w.DWORD, w.DWORD,
                                       w.DWORD, w.DWORD, w.DWORD, w.LPVOID)
    kernel.CreateNamedPipeW.restype = w.HANDLE
    kernel.ConnectNamedPipe.argtypes = (w.HANDLE, w.LPVOID)
    kernel.ConnectNamedPipe.restype = w.BOOL
    kernel.ReadFile.argtypes = (w.HANDLE, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID)
    kernel.WriteFile.argtypes = (w.HANDLE, w.LPCVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID)
    kernel.CloseHandle.argtypes = (w.HANDLE,)
    name = rf"\\.\pipe\gnosis-timeout-test-{uuid.uuid4().hex}"
    handle = kernel.CreateNamedPipeW(name, 3, 6, 1, 1024, 1024, 1000, None)
    assert handle not in (None, 0, ctypes.c_void_p(-1).value)
    received, release = threading.Event(), threading.Event()
    requests, errors, children = [], [], []

    def server():
        try:
            connected = kernel.ConnectNamedPipe(handle, None)
            assert connected or ctypes.get_last_error() == 535
            buffer = ctypes.create_string_buffer(512)
            count = w.DWORD()
            assert kernel.ReadFile(handle, buffer, 512, ctypes.byref(count), None)
            requests.append(buffer.raw[:count.value])
            received.set()
            if reply is None:
                assert release.wait(10)
            else:
                assert kernel.WriteFile(handle, reply, len(reply), ctypes.byref(count), None)
                assert release.wait(10)
        except BaseException as exc:  # noqa: BLE001 - report thread failures in the test thread
            errors.append(exc)
        finally:
            kernel.CloseHandle(handle)

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    original = subprocess.Popen

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    client = PipePublisherClient(name, connect_timeout_ms=1000, op_timeout_ms=500)
    try:
        with patch("gnosis.director.publisher_client.subprocess.Popen", side_effect=spawn):
            if reply is not None and reply.startswith(b"ANCHORED:"):
                assert client.publish("run-1").anchored
            else:
                with pytest.raises(PublisherClientError) as failure:
                    client.publish("run-1")
                if reply is None:
                    assert "timed out" in str(failure.value)
                    assert "unknown" in str(failure.value)
        assert received.wait(2)
        assert requests == [b"PUBLISH run-1"]
        assert len(children) == 1 and children[0].poll() is not None
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert not errors


@pytest.mark.parametrize("timeout", [0, -1, True, 1.5, float("inf"), 300001])
def test_transport_timeout_configuration_is_bounded(timeout) -> None:
    with pytest.raises(PublisherClientError):
        PipePublisherClient(r"\\.\pipe\test", op_timeout_ms=timeout)
