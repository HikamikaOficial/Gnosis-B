"""F-33 Stage 2C-B — operations backends for the single orchestration graph.

`DryOperations` fakes ONLY the lowest-level side effects (Windows accounts,
services, ACL/sc/icacls commands, process creation, anchor observation) while
performing REAL filesystem writes, so the real F-17 `Provisioner` and the composed
`GnosisDeploymentProvisioner` run their real code against a temp tree. It records
every operation so tests can assert call order/arguments, and it accepts injected
failures/collisions for the failure-injection, cleanup-failure and collision
matrices.

`WindowsRealOperations` is the real privileged backend used by Stage-2C-B1. It
exists and is complete (no TODO / pass / NotImplementedError on the live path);
it delegates F-17 provisioning primitives to the qualified
`gnosis.provision.provisioner.RealOperations` and adds the sc.exe/pipe/spawn
operations. It is GUARDED: constructing it requires `authorized=True`, so it can
never run by accident in a dry slice.
"""
from __future__ import annotations

import contextlib
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import stage2cb

import gnosis.provision.gnosis_deployment as _gd
from gnosis.provision.provisioner import RealOperations
from gnosis.provision.provisioner import service_imagepath as _service_imagepath

# -- R2C: Windows named-pipe readiness observation ---------------------------
# The production client (gnosis.director.publisher_client.PipePublisherClient)
# gates on WaitNamedPipeW(pipe_name, connect_timeout_ms) BEFORE CreateFileW, so
# WaitNamedPipeW is the faithful, least-invasive readiness primitive: it never
# opens a handle and therefore cannot consume the single-instance server. The old
# harness observed the pipe with pathlib filesystem existence, which RAISES on a
# \\.\pipe\ path (OS-real terminal_reason=observation-error) so the endpoint was
# never actually observed.
_ERROR_FILE_NOT_FOUND = 2      # pipe not created yet -> transient not-ready
_ERROR_ACCESS_DENIED = 5       # abnormal for a provisioned deployment -> fail closed
_ERROR_SEM_TIMEOUT = 121       # pipe exists but no free instance in the wait -> busy
_ERROR_INVALID_NAME = 123      # malformed name -> observation-error
_ERROR_BAD_PATHNAME = 161      # malformed path -> observation-error
_ERROR_PIPE_BUSY = 231         # all instances busy -> busy (transient)
_WIN32_NAME = {
    0: "SUCCESS", _ERROR_FILE_NOT_FOUND: "ERROR_FILE_NOT_FOUND",
    _ERROR_ACCESS_DENIED: "ERROR_ACCESS_DENIED", _ERROR_SEM_TIMEOUT: "ERROR_SEM_TIMEOUT",
    _ERROR_INVALID_NAME: "ERROR_INVALID_NAME", _ERROR_BAD_PATHNAME: "ERROR_BAD_PATHNAME",
    _ERROR_PIPE_BUSY: "ERROR_PIPE_BUSY"}
# transient = the observation SUCCEEDED semantically; the endpoint is just not
# connectable yet (absent or busy). Bounded polling continues. Everything else is
# an unexpected/abnormal API outcome -> observation-error (fail closed).
_TRANSIENT_NOT_READY = {_ERROR_FILE_NOT_FOUND, _ERROR_SEM_TIMEOUT, _ERROR_PIPE_BUSY}


class PipeObservationError(RuntimeError):
    """An unexpected/abnormal named-pipe observation outcome (access denied,
    invalid name, or any unmapped Win32 error). Raised so the bounded readiness
    loop fails closed with terminal_reason=observation-error — NEVER swallowed as
    an ordinary not-ready."""


class NamedPipeReadinessObserver:
    """Observes a Windows named pipe with WaitNamedPipeW (the production client's
    own availability gate). `observe()` returns True when an instance is available
    (READY), False for a transient absent/busy endpoint (keep polling), and RAISES
    PipeObservationError on an abnormal outcome (fail closed). Win32 detail is
    stored on `.last` for the diagnostic bundle. A `wait_fn` seam lets tests script
    Win32 outcomes without touching the OS; the default binds the real API."""

    def __init__(self, pipe_name: str, *, probe_timeout_ms: int = 200,
                 wait_fn: Any = None) -> None:
        self._pipe_name = pipe_name          # passed to WaitNamedPipeW VERBATIM
        self._probe_timeout_ms = probe_timeout_ms   # per-probe availability wait
        self._wait_fn = wait_fn or self._real_wait  # (name, timeout_ms)->(ok, err)
        self.last: dict[str, Any] = {
            "observation_api": "WaitNamedPipeW", "expected_pipe": pipe_name,
            "win32_error_code": None, "win32_error_name": None,
            "endpoint_present": None, "connectable": None}

    def _real_wait(self, name: str, timeout_ms: int) -> tuple[bool, int]:
        import ctypes
        from ctypes import wintypes as w
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.WaitNamedPipeW.argtypes = [w.LPCWSTR, w.DWORD]
        k32.WaitNamedPipeW.restype = w.BOOL
        ok = bool(k32.WaitNamedPipeW(name, timeout_ms))
        return ok, (0 if ok else ctypes.get_last_error())

    def observe(self) -> bool:
        ok, err = self._wait_fn(self._pipe_name, self._probe_timeout_ms)
        name = _WIN32_NAME.get(err, f"WIN32_{err}")
        if ok:
            self.last.update(win32_error_code=0, win32_error_name="SUCCESS",
                             endpoint_present=True, connectable=True)
            return True
        if err in _TRANSIENT_NOT_READY:
            present = err != _ERROR_FILE_NOT_FOUND  # busy => present; not-found => absent
            self.last.update(win32_error_code=err, win32_error_name=name,
                             endpoint_present=present, connectable=False)
            return False
        # access-denied / invalid-name / unexpected -> fail closed (observation-error)
        self.last.update(win32_error_code=err, win32_error_name=name,
                         endpoint_present=None, connectable=False)
        raise PipeObservationError(f"WaitNamedPipeW failed: {name} ({err})")


class _Fail(RuntimeError):
    pass


class DryOperations:
    """Fake OS boundary; real filesystem. Records all operations."""

    def __init__(self, *, existing_accounts: tuple[str, ...] = (),
                 existing_services: tuple[str, ...] = (),
                 existing_roots: tuple[str, ...] = (),
                 fail_op: str | None = None,
                 fail_cleanup: tuple[str, ...] = (),
                 utilities: bool = True, elevated: bool = True,
                 anchored: bool = True, pipe_not_ready: bool = False,
                 readiness_reason: str = "timeout",
                 postmortem: dict[str, Any] | None = None) -> None:
        self.log: list[tuple[str, tuple[Any, ...]]] = []
        self._accounts = set(existing_accounts)
        self._services = set(existing_services)
        self._roots = set(existing_roots)
        self._fail_op = fail_op
        self._fail_cleanup = set(fail_cleanup)
        self._utilities = utilities
        self._elevated = elevated
        self._anchored = anchored
        self._pipe_not_ready = pipe_not_ready
        self._readiness_reason = readiness_reason
        self._postmortem = postmortem
        self._last_readiness: dict[str, Any] = {}
        self._last_spawn: tuple[tuple[str, ...], int] | None = None

    def _rec(self, op: str, *args: Any) -> None:
        self.log.append((op, args))
        if self._fail_op == op:
            raise _Fail(f"INJECTED failure in op {op}")

    def ops_of(self, op: str) -> list[tuple[Any, ...]]:
        return [a for o, a in self.log if o == op]

    # -- F-17 Operations protocol ------------------------------------------
    def run(self, argv: list[str]) -> tuple[int, str]:
        self._rec("run", tuple(argv))
        if argv[:2] == ["sc.exe", "query"]:
            return (0 if argv[2] in self._services else 1060), ""
        if argv[:2] == ["sc.exe", "create"]:
            self._services.add(argv[2])   # service now exists (created by F-17)
        if argv[:2] == ["sc.exe", "delete"]:
            self._services.discard(argv[2])  # service removed (F-17 uninstall)
        return 0, ""

    def mkdir(self, path: str) -> None:
        self._rec("mkdir", path)
        Path(path).mkdir(parents=True, exist_ok=True)

    def rmtree(self, path: str) -> None:
        self._rec("rmtree", path)
        shutil.rmtree(path, ignore_errors=True)

    def exists(self, path: str) -> bool:
        return Path(path).exists()

    def copytree(self, src: str, dst: str) -> None:
        self._rec("copytree", src, dst)
        Path(dst).mkdir(parents=True, exist_ok=True)  # runtime tree stub (dry)
        (Path(dst) / "python.exe").write_bytes(b"MZ dry runtime\n")

    def copyfile(self, src: str, dst: str) -> None:
        self._rec("copyfile", src, dst)
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

    def write_text(self, path: str, text: str) -> None:
        self._rec("write_text", path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding="utf-8")

    def write_bytes(self, path: str, data: bytes) -> None:
        self._rec("write_bytes", path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(data)

    def resolve_sid(self, name: str) -> str:
        self._rec("resolve_sid", name)
        return "S-1-5-21-DRY-" + str(abs(hash(name)) % 100000)

    def account_exists(self, username: str) -> bool:
        return username in self._accounts

    def create_worker(self, username: str, password: str, comment: str) -> None:
        self._rec("create_worker", username)
        self._accounts.add(username)

    def delete_worker(self, username: str) -> int:
        self._rec("delete_worker", username)
        if "delete_worker" in self._fail_cleanup:
            raise _Fail("INJECTED cleanup failure: delete_worker")
        self._accounts.discard(username)
        return 0

    def protect_secret(self, secret: str) -> bytes:
        self._rec("protect_secret")
        return b"DRY-DPAPI-BLOB"

    # -- B1 additions ------------------------------------------------------
    def is_elevated(self) -> bool:
        return self._elevated

    def utilities_present(self) -> bool:
        return self._utilities

    def service_start(self, name: str) -> None:
        self._rec("service_start", name)
        self._services.add(name)

    def pipe_ready(self, pipe_name: str, service_name: str) -> bool:
        self._rec("pipe_ready", pipe_name, service_name)
        ready = not self._pipe_not_ready
        reason = "ready" if ready else self._readiness_reason
        self._last_readiness = {
            "terminal_reason": reason, "expected_pipe": pipe_name,
            "timeout_s": 15.0, "poll_interval_s": 0.25,
            "poll_count": 1 if ready else 60, "elapsed_s": 0.0 if ready else 15.0,
            "service_running_observed": service_name in self._services,
            "pipe_seen": ready,
            "observation_error": (reason == "observation-error") or None}
        return ready

    def last_readiness(self) -> dict[str, Any]:
        return self._last_readiness

    def service_postmortem(self, service_name: str, config: Any) -> dict[str, Any]:
        self._rec("service_postmortem", service_name)
        if self._postmortem is not None:
            return self._postmortem
        return {"scm_state": "RUNNING" if service_name in self._services else "ABSENT",
                "service_running_observed": service_name in self._services,
                "service_exit_code": None, "runtime_exe_exists": True,
                "service_entry_exists": True, "config_path_exists": True,
                "access_contract": "UNKNOWN"}

    def service_stop(self, name: str) -> None:
        self._rec("service_stop", name)
        if "service_stop" in self._fail_cleanup:
            raise _Fail("INJECTED cleanup failure: service_stop")

    def spawn_intercept(self, exit_code: int) -> Any:
        @contextlib.contextmanager
        def _cm() -> Iterator[None]:
            real_run = _gd.subprocess.run

            def _fake_run(cmd: Any, *a: Any, **k: Any) -> Any:
                argv = tuple(str(x) for x in cmd)
                self._last_spawn = (argv, exit_code)
                self._rec("spawn_operator", argv)
                import types
                return types.SimpleNamespace(returncode=exit_code)
            _gd.subprocess.run = _fake_run  # type: ignore[assignment]
            try:
                yield
            finally:
                _gd.subprocess.run = real_run  # type: ignore[assignment]
        return _cm()

    def last_spawn(self) -> tuple[tuple[str, ...], int] | None:
        return self._last_spawn

    def observe_anchored(self, run_id: str) -> bool:
        self._rec("observe_anchored", run_id)
        return self._anchored

    def account_absent(self, username: str) -> bool:
        return username not in self._accounts

    def service_absent(self, name: str) -> bool:
        return name not in self._services

    def root_absent(self, path: str) -> bool:
        return path not in self._roots


class WindowsRealOperations:
    """The REAL privileged backend for Stage-2C-B1. GUARDED: `authorized=True` is
    required to construct it, so a dry slice cannot instantiate it by accident.
    Complete — no unimplemented live path."""

    def __init__(self, *, authorized: bool = False,
                 runidentity_root: str = "") -> None:
        if not authorized:
            raise PermissionError(
                "WindowsRealOperations requires explicit OS-real authorization; "
                "refusing to construct a privileged backend in a non-authorized run")
        self._f17 = RealOperations()
        self._runidentity_root = runidentity_root
        self._last_spawn: tuple[tuple[str, ...], int] | None = None
        # R2C: WaitNamedPipeW seam. None -> the real Win32 API; tests inject a fake.
        self._pipe_wait_fn: Any = None

    # F-17 Operations delegated to the qualified RealOperations
    def run(self, argv: list[str]) -> tuple[int, str]:
        return self._f17.run(argv)

    def mkdir(self, path: str) -> None:
        self._f17.mkdir(path)

    def rmtree(self, path: str) -> None:
        self._f17.rmtree(path)

    def exists(self, path: str) -> bool:
        return self._f17.exists(path)

    def copytree(self, src: str, dst: str) -> None:
        self._f17.copytree(src, dst)

    def copyfile(self, src: str, dst: str) -> None:
        self._f17.copyfile(src, dst)

    def write_text(self, path: str, text: str) -> None:
        self._f17.write_text(path, text)

    def write_bytes(self, path: str, data: bytes) -> None:
        self._f17.write_bytes(path, data)

    def resolve_sid(self, name: str) -> str:
        return self._f17.resolve_sid(name)

    def account_exists(self, username: str) -> bool:
        return self._f17.account_exists(username)

    def create_worker(self, username: str, password: str, comment: str) -> None:
        self._f17.create_worker(username, password, comment)

    def delete_worker(self, username: str) -> int:
        return self._f17.delete_worker(username)

    def protect_secret(self, secret: str) -> bytes:
        return self._f17.protect_secret(secret)

    # B1 additions (real)
    def is_elevated(self) -> bool:
        rc, _ = self._f17.run(["net", "session"])
        return rc == 0

    def utilities_present(self) -> bool:
        return all(shutil.which(u) for u in ("sc.exe", "icacls", "net"))

    def service_start(self, name: str) -> None:
        rc, out = self._f17.run(["sc.exe", "start", name])
        if rc not in (0, 1056):  # already running
            raise RuntimeError(f"service start failed rc={rc}: {out[:160]}")

    def _service_running(self, name: str) -> bool:
        rc, out = self._f17.run(["sc.exe", "query", name])
        return rc == 0 and "RUNNING" in out.upper()

    def pipe_ready(self, pipe_name: str, service_name: str) -> bool:
        # pipe_name is the EXACT full local path (\\.\pipe\<name>) passed VERBATIM
        # to WaitNamedPipeW — never re-prefixed, never routed through pathlib. R2C:
        # a Win32 named-pipe observer replaces the old pathlib existence probe
        # (which raised on a \\.\pipe path). Bounds (15s / 0.25s) and R1 liveness
        # are UNCHANGED — only HOW the pipe is observed changed.
        import time
        observer = NamedPipeReadinessObserver(pipe_name, wait_fn=self._pipe_wait_fn)
        result = stage2cb.wait_pipe_ready(
            pipe_name,
            pipe_exists=observer.observe,
            service_alive=lambda: self._service_running(service_name),
            now=time.monotonic, timeout_s=15.0, poll_s=0.25, sleep=time.sleep)
        self._last_readiness = {
            "terminal_reason": result.reason, "expected_pipe": pipe_name,
            "timeout_s": 15.0, "poll_interval_s": 0.25, "poll_count": result.polls,
            "elapsed_s": result.elapsed_s,
            "service_running_observed": self._service_running(service_name),
            "pipe_seen": result.ready,
            "observation_error": (result.reason == "observation-error") or None,
            # R2C structured Win32 detail (last observation):
            "observation_api": observer.last["observation_api"],
            "win32_error_code": observer.last["win32_error_code"],
            "win32_error_name": observer.last["win32_error_name"],
            "endpoint_present": observer.last["endpoint_present"],
            "connectable": observer.last["connectable"]}
        return result.ready

    def last_readiness(self) -> dict[str, Any]:
        return getattr(self, "_last_readiness", {})

    def _sc_state(self, name: str) -> tuple[str, int | None]:
        rc, out = self._f17.run(["sc.exe", "query", name])
        if rc != 0:
            return "ABSENT", None
        up = out.upper()
        state = ("RUNNING" if "RUNNING" in up else "START_PENDING"
                 if "START_PENDING" in up else "STOPPED" if "STOPPED" in up else "UNKNOWN")
        exit_code: int | None = None
        for line in out.splitlines():
            if "WIN32_EXIT_CODE" in line.upper():
                try:
                    exit_code = int(line.split(":")[1].strip().split()[0])
                except (IndexError, ValueError):
                    exit_code = None
        return state, exit_code

    def _access_contract(self, config: Any) -> tuple[str, dict[str, Any]]:
        """Read-only, CONSERVATIVE access diagnostic (R2B). Emits an authoritative
        aggregate label only when the evidence genuinely supports it:

          FAIL    -> an explicit DENY ACE for the *intended* service principal
                     (NT SERVICE\\<service> or its resolved SID) on a required
                     object: a proven denial.
          UNKNOWN -> everything else. Leaf `icacls` presence CANNOT prove grant
                     semantics or ancestor traversal, so a positive access
                     contract is NEVER asserted (no 'PASS').

        This is ACL-BASED INFERENCE over leaf objects only; a generic
        'NT SERVICE' substring (e.g. NT SERVICE\\TrustedInstaller) never satisfies
        the intended principal, and a missing friendly name never forces FAIL.
        All raw sub-signals are returned for the evidence bundle."""
        lay = config.layout
        name = config.service_name
        principal = rf"NT SERVICE\{name}".upper()
        resolved_sid: str | None = None
        try:
            resolved_sid = self._f17.resolve_sid(name)
        except Exception:                    # noqa: BLE001  best-effort, read-only
            resolved_sid = None
        sid_up = resolved_sid.upper() if resolved_sid else None
        required = {"runtime": Path(lay.runtime_executable),
                    "service_entry": Path(lay.service_entry),
                    "config": Path(lay.config_path)}
        leaf_signals: dict[str, str] = {}
        principal_rendered = False
        directly_denied = False
        for key, p in required.items():
            if not p.exists():
                leaf_signals[key] = "absent"
                continue
            rc, out = self._f17.run(["icacls", str(p)])
            if rc != 0:
                leaf_signals[key] = "icacls-error"
                continue

            def _hit(text: str) -> bool:
                up = text.upper()
                return principal in up or (sid_up is not None and sid_up in up)
            found = _hit(out)
            denied = any(_hit(ln) and "(DENY)" in ln.upper()
                         for ln in out.splitlines())
            principal_rendered = principal_rendered or found
            directly_denied = directly_denied or denied
            leaf_signals[key] = ("intended-principal-denied" if denied
                                 else "intended-principal-present" if found
                                 else "intended-principal-not-rendered")
        detail: dict[str, Any] = {
            "method": "ACL-BASED INFERENCE (leaf objects only)",
            "intended_principal": rf"NT SERVICE\{name}",
            "resolved_sid": resolved_sid,
            "intended_principal_rendered": principal_rendered,
            "leaf_acls_inspected": leaf_signals,
            "ancestors_tested": False,          # R2B: leaf-only; never claim ancestors
            "grant_semantics_proven": False,    # icacls presence != grant proof
            "deny_semantics_proven": directly_denied,
        }
        if directly_denied:
            detail["verdict"] = "DIRECTLY-DENIED"
            return "FAIL", detail
        detail["verdict"] = "UNKNOWN"
        return "UNKNOWN", detail

    def service_postmortem(self, service_name: str, config: Any) -> dict[str, Any]:
        lay = config.layout
        state, exit_code = self._sc_state(service_name)
        access, access_detail = self._access_contract(config)
        return {
            "scm_state": state, "service_running_observed": state == "RUNNING",
            "service_exit_code": exit_code,
            "effective_command": _service_imagepath(
                lay.runtime_executable, lay.service_entry, lay.config_path),
            "runtime_exe_exists": Path(lay.runtime_executable).exists(),
            "service_entry_exists": Path(lay.service_entry).exists(),
            "config_path_exists": Path(lay.config_path).exists(),
            "deployment_root": lay.code_base,
            "access_contract": access, "access_detail": access_detail}

    def service_stop(self, name: str) -> None:
        self._f17.run(["sc.exe", "stop", name])

    def spawn_intercept(self, exit_code: int) -> Any:
        # real spawn: no interception; canonical_launch performs the real
        # subprocess.run and raises SystemExit(rc), captured by the orchestrator.
        @contextlib.contextmanager
        def _cm() -> Iterator[None]:
            yield
        return _cm()

    def last_spawn(self) -> tuple[tuple[str, ...], int] | None:
        return self._last_spawn

    def observe_anchored(self, run_id: str) -> bool:
        # Read the persisted authoritative state from the deployed trusted
        # run-identity store; ANCHORED is the only success state.
        from gnosis.trust.run_identity import (
            PublicationState,
            TrustedRunIdentityStore,
        )
        store = TrustedRunIdentityStore(Path(self._runidentity_root))
        try:
            record = store.read(run_id)
        except Exception:  # noqa: BLE001  (absent/unreadable == not anchored)
            return False
        return record.publication_state is PublicationState.ANCHORED

    def account_absent(self, username: str) -> bool:
        return not self._f17.account_exists(username)

    def service_absent(self, name: str) -> bool:
        rc, _ = self._f17.run(["sc.exe", "query", name])
        return rc != 0

    def root_absent(self, path: str) -> bool:
        return not Path(path).exists()
