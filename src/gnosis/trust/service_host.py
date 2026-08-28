"""A real Windows service, in pure ctypes.

WHY THIS EXISTS AT ALL. `python main.py` under a scheduled task is not a
service: it has no ServiceMain, answers no control codes, reports no status, and
the SCM cannot start, stop or supervise it. The publisher's identity - a
restricted service SID that owns the trust state - is granted BY the SCM to a
process it launched as a service. Without the real contract there is no service
SID, and without that there is no boundary.

WHY NOT pywin32. It would work and it would balloon the TCB of a process whose
whole job is to compare hashes and append one line. The contract is a dispatcher,
a ServiceMain, a control handler and status transitions; in ctypes that is about
120 lines, and 120 lines of TCB is cheaper to audit than a large extension
module.

THE WORKLOAD RUNS ON ITS OWN THREAD, and ServiceMain waits. A control handler
must return promptly - the SCM is entitled to conclude the service is hung - so
the handler sets the stop event, calls the caller's `on_stop` to unblock the
workload, and returns, while ServiceMain does the waiting.
"""
from __future__ import annotations

import ctypes as C
import threading
from collections.abc import Callable
from ctypes import wintypes as W
from typing import Any

_adv: Any = C.WinDLL("advapi32", use_last_error=True)

SERVICE_WIN32_OWN_PROCESS = 0x00000010
SERVICE_STOPPED = 0x00000001
SERVICE_START_PENDING = 0x00000002
SERVICE_STOP_PENDING = 0x00000003
SERVICE_RUNNING = 0x00000004
SERVICE_ACCEPT_STOP = 0x00000001
SERVICE_ACCEPT_SHUTDOWN = 0x00000004
SERVICE_CONTROL_STOP = 0x00000001
SERVICE_CONTROL_INTERROGATE = 0x00000004
SERVICE_CONTROL_SHUTDOWN = 0x00000005

# StartServiceCtrlDispatcherW returns this when the process was NOT launched by
# the SCM. It is the signal that "we are not actually a service", and it must
# never be papered over by falling back to a plain foreground loop.
ERROR_FAILED_SERVICE_CONTROLLER_CONNECT = 1063
# A SECOND dispatcher call in one process answers this instead. It means
# the same thing for our purposes - this process is not serving as a
# service - and it is named so callers can recognise it rather than
# reporting an unexplained number.
ERROR_SERVICE_ALREADY_RUNNING = 1056


class SERVICE_STATUS(C.Structure):
    _fields_ = (("dwServiceType", W.DWORD), ("dwCurrentState", W.DWORD),
                ("dwControlsAccepted", W.DWORD), ("dwWin32ExitCode", W.DWORD),
                ("dwServiceSpecificExitCode", W.DWORD), ("dwCheckPoint", W.DWORD),
                ("dwWaitHint", W.DWORD))


LPSERVICE_MAIN = C.WINFUNCTYPE(None, W.DWORD, C.POINTER(W.LPWSTR))
LPHANDLER_EX = C.WINFUNCTYPE(W.DWORD, W.DWORD, W.DWORD, C.c_void_p, C.c_void_p)


class SERVICE_TABLE_ENTRY(C.Structure):
    _fields_ = (("lpServiceName", W.LPWSTR), ("lpServiceProc", LPSERVICE_MAIN))


_adv.RegisterServiceCtrlHandlerExW.restype = C.c_void_p
_adv.RegisterServiceCtrlHandlerExW.argtypes = [W.LPCWSTR, LPHANDLER_EX, C.c_void_p]
_adv.SetServiceStatus.argtypes = [C.c_void_p, C.POINTER(SERVICE_STATUS)]
_adv.SetServiceStatus.restype = W.BOOL
_adv.StartServiceCtrlDispatcherW.argtypes = [C.POINTER(SERVICE_TABLE_ENTRY)]
_adv.StartServiceCtrlDispatcherW.restype = W.BOOL


class ServiceHost:
    """`on_start(stop_event)` runs the workload; `on_stop()` unblocks it."""

    def __init__(self, name: str,
                 on_start: Callable[[threading.Event], None],
                 on_stop: Callable[[], None],
                 log: Callable[[str], None]) -> None:
        self.name = name
        self.on_start = on_start
        self.on_stop = on_stop
        self.log = log
        self._status_handle: int | None = None
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._status = SERVICE_STATUS(SERVICE_WIN32_OWN_PROCESS, SERVICE_STOPPED,
                                      0, 0, 0, 0, 0)
        # The ctypes trampolines must outlive the calls that register them; if
        # they are collected the SCM calls freed memory.
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
            _adv.SetServiceStatus(self._status_handle, C.byref(self._status))

    def _control(self, control: int, event_type: int, event_data: Any,
                 context: Any) -> int:
        if control in (SERVICE_CONTROL_STOP, SERVICE_CONTROL_SHUTDOWN):
            self.log(f"control {control}: stopping")
            self._set(SERVICE_STOP_PENDING, checkpoint=1, wait_hint=5000)
            self._stop_event.set()
            try:
                self.on_stop()
            except Exception as exc:  # noqa: BLE001 - the handler must return
                self.log(f"on_stop error: {exc!r}")
        elif control == SERVICE_CONTROL_INTERROGATE:
            self._set(self._status.dwCurrentState)
        return 0

    def _run_workload(self) -> None:
        try:
            self.on_start(self._stop_event)
        except Exception as exc:  # noqa: BLE001 - a dead workload stops the service
            self.log(f"workload error: {exc!r}")
            self._stop_event.set()

    def _service_main(self, argc: int, argv: Any) -> None:
        handle = _adv.RegisterServiceCtrlHandlerExW(self.name, self._c_handler, None)
        if not handle:
            self.log(f"RegisterServiceCtrlHandlerExW failed {C.get_last_error()}")
            return
        self._status_handle = handle
        self._set(SERVICE_START_PENDING, checkpoint=1, wait_hint=10000)
        try:
            self._worker = threading.Thread(target=self._run_workload, daemon=True)
            self._worker.start()
            self._set(SERVICE_RUNNING)
            self.log("service RUNNING")
            self._stop_event.wait()
            self._worker.join(timeout=8)
        except Exception as exc:  # noqa: BLE001 - report STOPPED, never hang
            self.log(f"service_main error: {exc!r}")
            self._set(SERVICE_STOPPED, exit_code=1)
            return
        self._set(SERVICE_STOPPED)
        self.log("service STOPPED")

    def run(self) -> None:
        """Hand control to the SCM. Raises if this process is not a service."""
        table = (SERVICE_TABLE_ENTRY * 2)()
        table[0].lpServiceName = self.name
        table[0].lpServiceProc = self._c_main
        table[1].lpServiceName = None
        table[1].lpServiceProc = LPSERVICE_MAIN()
        if not _adv.StartServiceCtrlDispatcherW(table):
            error = C.get_last_error()
            hints = {
                ERROR_FAILED_SERVICE_CONTROLLER_CONNECT:
                    " (1063: this process was not launched by the SCM)",
                ERROR_SERVICE_ALREADY_RUNNING:
                    " (1056: a dispatcher was already started in this process)",
            }
            hint = hints.get(error, "")
            self.log(f"StartServiceCtrlDispatcher failed {error}{hint}")
            # FAIL CLOSED. A publisher that fell back to a foreground loop here
            # would run without the service SID that its whole boundary rests on.
            raise OSError(f"StartServiceCtrlDispatcher failed {error}{hint}")
