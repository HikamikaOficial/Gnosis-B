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
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

import gnosis.provision.gnosis_deployment as _gd
from gnosis.provision.provisioner import RealOperations


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
                 anchored: bool = True) -> None:
        self.log: list[tuple[str, tuple[Any, ...]]] = []
        self._accounts = set(existing_accounts)
        self._services = set(existing_services)
        self._roots = set(existing_roots)
        self._fail_op = fail_op
        self._fail_cleanup = set(fail_cleanup)
        self._utilities = utilities
        self._elevated = elevated
        self._anchored = anchored
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

    def pipe_ready(self, pipe_name: str) -> bool:
        self._rec("pipe_ready", pipe_name)
        return True

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

    def pipe_ready(self, pipe_name: str) -> bool:
        return Path(rf"\\.\pipe\{pipe_name}").exists()

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
