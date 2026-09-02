r"""F-33 Stage 2C-B1-R2C — Windows named-pipe readiness observation.

The OS-real diagnostic run established the blocker was a READINESS OBSERVATION
FAILURE: the harness observed the pipe with `Path(r"\\.\pipe\...").exists()`, which
RAISES on a Win32 pipe path, so the actual pipe state was never determined while the
Publisher service was RUNNING. R2C replaces that probe with a Win32 named-pipe
observer built on `WaitNamedPipeW` — the exact primitive the production client
(`PipePublisherClient`) already gates on before `CreateFileW`.

Filesystem/mock only; a `wait_fn` seam scripts Win32 outcomes with no OS call.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "scripts", REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import stage2cb as s
import stage2cb_ops as sops

PIPE = r"\\.\pipe\gnosis-s2cb-probe"

OK = (True, 0)
NOT_FOUND = (False, sops._ERROR_FILE_NOT_FOUND)
BUSY = (False, sops._ERROR_SEM_TIMEOUT)
PIPE_BUSY = (False, sops._ERROR_PIPE_BUSY)
DENIED = (False, sops._ERROR_ACCESS_DENIED)
INVALID = (False, sops._ERROR_INVALID_NAME)
UNEXPECTED = (False, 0x1F00)


def _scripted(outcomes):
    it = iter(outcomes)
    last = outcomes[-1]

    def _fn(name, timeout_ms):
        nonlocal last
        try:
            last = next(it)
        except StopIteration:
            pass
        return last
    return _fn


class _Clock:
    def __init__(self, step: float = 1.0) -> None:
        self.t, self.step = 0.0, step

    def __call__(self) -> float:
        v = self.t
        self.t += self.step
        return v


def _observer(outcomes):
    return sops.NamedPipeReadinessObserver(PIPE, wait_fn=_scripted(outcomes))


def _wait(outcomes, alive_seq, *, timeout_s=5.0):
    """Compose the R2C observer with the R1 bounded loop under a fake clock."""
    obs = _observer(outcomes)
    al = iter(alive_seq)
    return obs, s.wait_pipe_ready(
        PIPE, pipe_exists=obs.observe, service_alive=lambda: next(al),
        now=_Clock(1.0), timeout_s=timeout_s, poll_s=0.0, sleep=None)


def _wait_inf(outcomes, *, timeout_s=3.0):
    """Same, but the service stays alive indefinitely — for timeout-boundedness."""
    obs = _observer(outcomes)
    return obs, s.wait_pipe_ready(
        PIPE, pipe_exists=obs.observe, service_alive=lambda: True,
        now=_Clock(1.0), timeout_s=timeout_s, poll_s=0.0, sleep=None)


class TestObserverSemantics(unittest.TestCase):
    def test_np1_available_is_ready(self) -> None:
        obs = _observer([OK])
        self.assertTrue(obs.observe())
        self.assertEqual(obs.last["win32_error_name"], "SUCCESS")
        self.assertTrue(obs.last["endpoint_present"])
        self.assertTrue(obs.last["connectable"])

    def test_np2_not_created_is_transient(self) -> None:
        obs = _observer([NOT_FOUND])
        self.assertFalse(obs.observe())          # transient, not an error
        self.assertEqual(obs.last["win32_error_name"], "ERROR_FILE_NOT_FOUND")
        self.assertFalse(obs.last["endpoint_present"])
        self.assertFalse(obs.last["connectable"])

    def test_np3_busy_present_not_connectable(self) -> None:
        for outcome, name in ((BUSY, "ERROR_SEM_TIMEOUT"),
                              (PIPE_BUSY, "ERROR_PIPE_BUSY")):
            obs = _observer([outcome])
            self.assertFalse(obs.observe())      # production client waits on busy
            self.assertEqual(obs.last["win32_error_name"], name)
            self.assertTrue(obs.last["endpoint_present"])   # endpoint IS present
            self.assertFalse(obs.last["connectable"])

    def test_np5_access_denied_not_ready_explicit(self) -> None:
        obs = _observer([DENIED])
        with self.assertRaises(sops.PipeObservationError):
            obs.observe()                        # never READY; fail closed
        self.assertEqual(obs.last["win32_error_name"], "ERROR_ACCESS_DENIED")

    def test_np6_invalid_name_is_observation_error(self) -> None:
        obs = _observer([INVALID])
        with self.assertRaises(sops.PipeObservationError):
            obs.observe()
        self.assertEqual(obs.last["win32_error_name"], "ERROR_INVALID_NAME")

    def test_np7_unexpected_error_is_observation_error(self) -> None:
        obs = _observer([UNEXPECTED])
        with self.assertRaises(sops.PipeObservationError):
            obs.observe()

    def test_np8_canonical_pipe_passed_verbatim(self) -> None:
        seen = {}

        def _fn(name, timeout_ms):
            seen["name"] = name
            return OK
        obs = sops.NamedPipeReadinessObserver(PIPE, wait_fn=_fn)
        obs.observe()
        self.assertEqual(seen["name"], PIPE)     # exact, no reprefix / pathlib


class TestObserverBoundedLoop(unittest.TestCase):
    def test_np2_not_created_times_out(self) -> None:
        obs, r = _wait_inf([NOT_FOUND], timeout_s=3.0)
        self.assertFalse(r.ready)
        self.assertEqual(r.reason, "timeout")    # NOT observation-error
        self.assertLess(r.polls, 100)            # bounded by the deadline
        self.assertFalse(obs.last["endpoint_present"])

    def test_np3_busy_times_out(self) -> None:
        obs, r = _wait_inf([BUSY], timeout_s=3.0)
        self.assertFalse(r.ready)
        self.assertEqual(r.reason, "timeout")
        self.assertLess(r.polls, 100)
        self.assertTrue(obs.last["endpoint_present"])

    def test_np5_access_denied_is_observation_error(self) -> None:
        _, r = _wait([DENIED], [True])
        self.assertFalse(r.ready)
        self.assertEqual(r.reason, "observation-error")

    def test_np9_service_dies_while_waiting(self) -> None:
        _, r = _wait([NOT_FOUND, NOT_FOUND], [True, False])
        self.assertFalse(r.ready)
        self.assertEqual(r.reason, "service-died")

    def test_np10_delayed_ready(self) -> None:
        _, r = _wait([NOT_FOUND, NOT_FOUND, OK], [True, True, True])
        self.assertTrue(r.ready)
        self.assertEqual(r.reason, "ready")
        self.assertEqual(r.polls, 3)


class TestRealBackendWiring(unittest.TestCase):
    def _ops(self, outcomes, running=True):
        ops = sops.WindowsRealOperations(authorized=True)
        ops._pipe_wait_fn = _scripted(outcomes)
        ops._service_running = lambda name: running   # instance shadow (unbound)
        return ops

    def test_pipe_ready_ready_and_carries_win32(self) -> None:
        ops = self._ops([OK])
        self.assertTrue(ops.pipe_ready(PIPE, "GnosisPubS2CBProbe"))
        d = ops.last_readiness()
        self.assertEqual(d["terminal_reason"], "ready")
        self.assertEqual(d["observation_api"], "WaitNamedPipeW")
        self.assertEqual(d["win32_error_name"], "SUCCESS")
        self.assertTrue(d["connectable"])
        self.assertEqual(d["timeout_s"], 15.0)          # bounds unchanged
        self.assertEqual(d["poll_interval_s"], 0.25)

    def test_pipe_ready_access_denied_observation_error(self) -> None:
        ops = self._ops([DENIED])
        self.assertFalse(ops.pipe_ready(PIPE, "GnosisPubS2CBProbe"))
        d = ops.last_readiness()
        self.assertEqual(d["terminal_reason"], "observation-error")
        self.assertEqual(d["win32_error_name"], "ERROR_ACCESS_DENIED")


class TestProductionClientConsistency(unittest.TestCase):
    def test_observer_uses_same_primitive_as_client(self) -> None:
        # §15: the observer's readiness primitive is exactly the production client's
        # availability gate (WaitNamedPipeW), so READY == "client can proceed".
        client_src = (REPO / "src" / "gnosis" / "director"
                      / "publisher_client.py").read_text(encoding="utf-8")
        ops_src = (REPO / "scripts" / "stage2cb_ops.py").read_text(encoding="utf-8")
        self.assertIn("WaitNamedPipeW", client_src)
        self.assertIn("WaitNamedPipeW", ops_src)

    def test_ready_only_on_wait_success(self) -> None:
        # for every non-success Win32 outcome the observer returns False or raises,
        # NEVER True -> it can never claim READY for a state the client cannot use.
        for outcome in (NOT_FOUND, BUSY, PIPE_BUSY, DENIED, INVALID, UNEXPECTED):
            obs = _observer([outcome])
            try:
                self.assertFalse(obs.observe())
            except sops.PipeObservationError:
                pass                              # abnormal -> fail closed, not READY


class TestHistoricalObservationRegression(unittest.TestCase):
    def test_pathlib_probe_removed(self) -> None:
        # §13: the real backend must NOT observe a Win32 pipe via pathlib existence.
        src = (REPO / "scripts" / "stage2cb_ops.py").read_text(encoding="utf-8")
        self.assertNotIn("Path(pipe_name).exists()", src)
        self.assertIn("NamedPipeReadinessObserver(pipe_name", src)

    def test_raising_wait_fn_fails_closed(self) -> None:
        # a wait_fn that raises (the historical pathlib-exception shape) must map to
        # observation-error via the bounded loop, never a false ready/not-ready.
        def _boom(name, timeout_ms):
            raise OSError("winapi blew up")
        obs = sops.NamedPipeReadinessObserver(PIPE, wait_fn=_boom)
        r = s.wait_pipe_ready(PIPE, pipe_exists=obs.observe,
                              service_alive=lambda: True, now=_Clock(), timeout_s=5.0)
        self.assertFalse(r.ready)
        self.assertEqual(r.reason, "observation-error")


if __name__ == "__main__":
    unittest.main()
