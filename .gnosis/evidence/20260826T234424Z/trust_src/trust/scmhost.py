"""Minimal Windows SCM service host in pure ctypes (no pywin32).

Implements the real SCM contract the operator's correction #4 requires: a
service-control dispatcher, ServiceMain, a control handler, status reporting,
and a clean stop. pywin32 is deliberately NOT used (it would balloon the TCB);
this adds only ctypes calls + ~120 lines, keeping the publisher TCB minimal.
"""
from __future__ import annotations

import ctypes as C
import threading
from ctypes import wintypes as W
from typing import Callable

adv = C.WinDLL("advapi32", use_last_error=True)

SERVICE_WIN32_OWN_PROCESS = 0x00000010
SERVICE_STOPPED, SERVICE_START_PENDING = 0x1, 0x2
SERVICE_STOP_PENDING, SERVICE_RUNNING = 0x3, 0x4
SERVICE_ACCEPT_STOP, SERVICE_ACCEPT_SHUTDOWN = 0x1, 0x4
SERVICE_CONTROL_STOP, SERVICE_CONTROL_INTERROGATE, SERVICE_CONTROL_SHUTDOWN = 0x1, 0x4, 0x5


class SERVICE_STATUS(C.Structure):
    _fields_ = [("dwServiceType", W.DWORD), ("dwCurrentState", W.DWORD),
                ("dwControlsAccepted", W.DWORD), ("dwWin32ExitCode", W.DWORD),
                ("dwServiceSpecificExitCode", W.DWORD), ("dwCheckPoint", W.DWORD),
                ("dwWaitHint", W.DWORD)]


LPSERVICE_MAIN = C.WINFUNCTYPE(None, W.DWORD, C.POINTER(W.LPWSTR))
LPHANDLER_EX = C.WINFUNCTYPE(W.DWORD, W.DWORD, W.DWORD, C.c_void_p, C.c_void_p)


class SERVICE_TABLE_ENTRY(C.Structure):
    _fields_ = [("lpServiceName", W.LPWSTR), ("lpServiceProc", LPSERVICE_MAIN)]


adv.RegisterServiceCtrlHandlerExW.restype = C.c_void_p
adv.RegisterServiceCtrlHandlerExW.argtypes = [W.LPCWSTR, LPHANDLER_EX, C.c_void_p]
adv.SetServiceStatus.argtypes = [C.c_void_p, C.POINTER(SERVICE_STATUS)]
adv.SetServiceStatus.restype = W.BOOL
adv.StartServiceCtrlDispatcherW.argtypes = [C.POINTER(SERVICE_TABLE_ENTRY)]
adv.StartServiceCtrlDispatcherW.restype = W.BOOL


class ServiceHost:
    """on_start(stop_event) runs the workload until stop_event is set;
    on_stop() unblocks it (e.g. closes the pipe)."""

    def __init__(self, name: str, on_start: Callable, on_stop: Callable, log):
        self.name = name
        self.on_start = on_start
        self.on_stop = on_stop
        self.log = log
        self._status_handle = None
        self._stop_event = threading.Event()
        self._status = SERVICE_STATUS(SERVICE_WIN32_OWN_PROCESS, SERVICE_STOPPED,
                                      0, 0, 0, 0, 0)
        # keep callbacks alive
        self._c_main = LPSERVICE_MAIN(self._service_main)
        self._c_handler = LPHANDLER_EX(self._control)

    def _set(self, state: int, *, checkpoint: int = 0, wait_hint: int = 0,
             exit_code: int = 0) -> None:
        self._status.dwCurrentState = state
        self._status.dwWin32ExitCode = exit_code
        self._status.dwCheckPoint = checkpoint
        self._status.dwWaitHint = wait_hint
        self._status.dwControlsAccepted = (
            SERVICE_ACCEPT_STOP | SERVICE_ACCEPT_SHUTDOWN
            if state == SERVICE_RUNNING else 0)
        if self._status_handle:
            adv.SetServiceStatus(self._status_handle, C.byref(self._status))

    def _control(self, ctrl, event_type, event_data, context):
        if ctrl in (SERVICE_CONTROL_STOP, SERVICE_CONTROL_SHUTDOWN):
            self.log(f"control {ctrl}: stopping")
            self._set(SERVICE_STOP_PENDING, checkpoint=1, wait_hint=5000)
            self._stop_event.set()
            try:
                self.on_stop()
            except Exception as exc:  # never fail the handler
                self.log(f"on_stop error: {exc!r}")
        elif ctrl == SERVICE_CONTROL_INTERROGATE:
            self._set(self._status.dwCurrentState)
        return 0

    def _service_main(self, argc, argv):
        self._status_handle = adv.RegisterServiceCtrlHandlerExW(
            self.name, self._c_handler, None)
        if not self._status_handle:
            self.log(f"RegisterServiceCtrlHandlerExW failed {C.get_last_error()}")
            return
        self._set(SERVICE_START_PENDING, checkpoint=1, wait_hint=10000)
        try:
            self.on_start_ready = self.on_start  # run workload in a worker thread
            self._worker = threading.Thread(
                target=self._run_workload, daemon=True)
            self._worker.start()
            self._set(SERVICE_RUNNING)
            self.log("service RUNNING")
            self._stop_event.wait()
            self._worker.join(timeout=8)
        except Exception as exc:
            self.log(f"service_main error: {exc!r}")
            self._set(SERVICE_STOPPED, exit_code=1); return
        self._set(SERVICE_STOPPED)
        self.log("service STOPPED")

    def _run_workload(self):
        try:
            self.on_start(self._stop_event)
        except Exception as exc:
            self.log(f"workload error: {exc!r}")
            self._stop_event.set()

    def run(self) -> None:
        table = (SERVICE_TABLE_ENTRY * 2)()
        table[0].lpServiceName = self.name
        table[0].lpServiceProc = self._c_main
        table[1].lpServiceName = None
        table[1].lpServiceProc = LPSERVICE_MAIN()
        if not adv.StartServiceCtrlDispatcherW(table):
            err = C.get_last_error()
            self.log(f"StartServiceCtrlDispatcher failed {err} "
                     f"(1063 = not launched by SCM)")
            raise OSError(f"StartServiceCtrlDispatcher failed {err}")
