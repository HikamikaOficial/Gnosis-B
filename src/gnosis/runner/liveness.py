"""Process liveness fingerprinting.

A bare PID is not a trustworthy ownership token: operating systems reuse
PIDs, so "the PID in this heartbeat is alive" can mean "an unrelated
process now happens to have that PID." A ProcessFingerprint pairs the PID
with the process's start time; is_alive() only returns True if a process
with that PID exists *and* its start time still matches (within a small
tolerance), which is what actually distinguishes "the same process" from
"a different process that reused the PID."

Windows-first (this is the deployment target), with a POSIX /proc fallback
so the module still degrades gracefully rather than crashing elsewhere.
"""
from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from typing import Any, Optional

_STALE_TOLERANCE_S = 2.0


@dataclass(frozen=True)
class ProcessFingerprint:
    pid: int
    start_time: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return {"pid": self.pid, "start_time": self.start_time}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProcessFingerprint":
        return cls(pid=data["pid"], start_time=data.get("start_time"))


def current_fingerprint() -> ProcessFingerprint:
    pid = os.getpid()
    return ProcessFingerprint(pid=pid, start_time=_process_start_time(pid))


def is_alive(fingerprint: ProcessFingerprint) -> bool:
    """True only if a process with this PID exists and, when a start time
    was recorded, that start time still matches, guarding against PID
    reuse by an unrelated later process."""
    if not _pid_exists(fingerprint.pid):
        return False
    if fingerprint.start_time is None:
        return True
    current_start = _process_start_time(fingerprint.pid)
    if current_start is None:
        return True
    return abs(current_start - fingerprint.start_time) < _STALE_TOLERANCE_S


def _process_start_time(pid: int) -> Optional[float]:
    if platform.system() == "Windows":
        return _windows_process_start_time(pid)
    return _posix_process_start_time(pid)


def _pid_exists(pid: int) -> bool:
    if platform.system() == "Windows":
        return _windows_pid_exists(pid)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _windows_pid_exists(pid: int) -> bool:
    try:
        import ctypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    except Exception:
        return False


def _windows_process_start_time(pid: int) -> Optional[float]:
    try:
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            ok = kernel32.GetProcessTimes(
                handle, ctypes.byref(creation), ctypes.byref(exit_time),
                ctypes.byref(kernel_time), ctypes.byref(user_time),
            )
            if not ok:
                return None
            ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            if ticks == 0:
                return None
            epoch_diff_100ns = 116444736000000000
            return (ticks - epoch_diff_100ns) / 1e7
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def _posix_process_start_time(pid: int) -> Optional[float]:
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as fh:
            fields = fh.read().split()
        clk_tck = os.sysconf("SC_CLK_TCK")
        boot_time = _posix_boot_time()
        if boot_time is None:
            return None
        starttime_ticks = float(fields[21])
        return boot_time + starttime_ticks / clk_tck
    except Exception:
        return None


def _posix_boot_time() -> Optional[float]:
    try:
        with open("/proc/stat", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("btime"):
                    return float(line.split()[1])
    except Exception:
        return None
    return None
