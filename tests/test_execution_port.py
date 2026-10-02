"""Component qualification for the F-33 Stage-2A trusted execution port.

These use a Protocol-injected fake `WorkerLauncher` to qualify the port's LOGIC,
bypass-resistance and fail-closed behaviour. Per ADR-0032 §18 a fake CANNOT
satisfy the OS-real trusted-launch gate — that is a separate test launching the
deterministic Worker entry through the real `TrustedWindowsWorkerLauncher`.
"""

from __future__ import annotations

import ast
import hashlib
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gnosis.director import deterministic_worker as dw
from gnosis.director import execution
from gnosis.director.execution import (
    MAX_RESULT_BYTES,
    DeterministicIntent,
    ExecutionMode,
    ExecutionModeError,
    TrustedExecutionError,
    TrustedExecutionPort,
    WorkerExecutionFailed,
    WorkerResultInvalid,
)
from gnosis.trust.launch_spec import LaunchSpec

# An absolute Windows path the LaunchSpec validator accepts, for the fake python.
FAKE_PYTHON = Path(r"C:\qualified\runtime\python.exe")


@dataclass
class _FakeIdentity:
    pid: int = 4321
    observed_sid: str = "S-1-5-21-fake-worker"
    integrity: str = "Medium"
    is_administrator: bool = False
    contained_in_job: bool = True
    launch_spec_digest: str = "0" * 64


class _FakeLaunched:
    def __init__(self, exit_code: int, timed_out: bool) -> None:
        self._exit_code = exit_code
        self._timed_out = timed_out
        self.identity = _FakeIdentity()
        self.closed = False

    def wait(self, timeout_s: float, *, poll_interval_s: float = 0.2,
             is_cancelled: Any = None) -> tuple[int, bool, bool]:
        return self._exit_code, self._timed_out, False

    def close(self) -> None:
        self.closed = True


class _FakeLauncher:
    """Records the spec, simulates the Worker by writing `stdout_content` to the
    spec's stdout_path, and returns a configurable result. It NEVER runs a real
    process — it stands in for the trusted boundary in component tests only."""

    def __init__(self, stdout_content: str, *, exit_code: int = 0,
                 timed_out: bool = False) -> None:
        self.stdout_content = stdout_content
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.spec: LaunchSpec | None = None
        self.launched: _FakeLaunched | None = None

    def launch(self, spec: LaunchSpec) -> _FakeLaunched:
        self.spec = spec
        Path(spec.stdout_path).write_text(self.stdout_content, encoding="utf-8")
        self.launched = _FakeLaunched(self.exit_code, self.timed_out)
        return self.launched


def _write_cassette(tmp: Path, *, blob: bytes | None = None) -> tuple[Path, str]:
    """Write a valid cassette and return (path, sha256-of-bytes)."""
    if blob is None:
        blob = json.dumps(
            {"schema": dw.CASSETTE_SCHEMA, "turns": [{"message": "hi"}]}
        ).encode("utf-8")
    path = tmp / "cassette.json"
    path.write_bytes(blob)
    return path, hashlib.sha256(blob).hexdigest()


def _result_json(digest: str, **override: Any) -> str:
    payload: dict[str, Any] = {
        "schema": dw.RESULT_SCHEMA, "ok": True, "cassette_sha256": digest,
        "turn_count": 1, "final_message": "done", "provider_calls": 0,
    }
    payload.update(override)
    return json.dumps(payload)


def _intent(tmp: Path, cassette_path: Path) -> DeterministicIntent:
    return DeterministicIntent(
        cassette_path=cassette_path, cwd=tmp,
        stdout_path=tmp / "out.txt", stderr_path=tmp / "err.txt")


class TestBoundedModeSelection(unittest.TestCase):
    def test_deterministic_mode_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            cassette, digest = _write_cassette(tmp)
            launcher = _FakeLauncher(_result_json(digest))
            port = TrustedExecutionPort(launcher, FAKE_PYTHON)
            outcome = port.execute(ExecutionMode.DETERMINISTIC,
                                   _intent(tmp, cassette), timeout_s=5.0)
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(outcome.result["schema"], dw.RESULT_SCHEMA)
        self.assertEqual(outcome.result["cassette_sha256"], digest)
        self.assertEqual(outcome.launch["observed_sid"], "S-1-5-21-fake-worker")

    def test_provider_backed_fails_closed_in_stage_2a(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            cassette, digest = _write_cassette(tmp)
            launcher = _FakeLauncher(_result_json(digest))
            port = TrustedExecutionPort(launcher, FAKE_PYTHON)
            with self.assertRaises(ExecutionModeError):
                port.execute(ExecutionMode.PROVIDER_BACKED,
                             _intent(tmp, cassette), timeout_s=5.0)
            self.assertIsNone(launcher.spec)


class TestImageIsTrustedNotOperatorChosen(unittest.TestCase):
    def test_absolute_executable_required(self) -> None:
        with self.assertRaises(execution.TrustedExecutionError):
            TrustedExecutionPort(_FakeLauncher("{}"), Path("python.exe"))

    def test_launchspec_image_is_the_deterministic_worker(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            cassette, digest = _write_cassette(tmp)
            launcher = _FakeLauncher(_result_json(digest))
            port = TrustedExecutionPort(launcher, FAKE_PYTHON)
            port.execute(ExecutionMode.DETERMINISTIC, _intent(tmp, cassette),
                         timeout_s=5.0)
        spec = launcher.spec
        assert spec is not None
        self.assertEqual(spec.executable, str(FAKE_PYTHON))
        self.assertEqual(spec.argv[0], str(FAKE_PYTHON))
        self.assertIn("-I", spec.argv)
        module_file = str(Path(dw.__file__).resolve())
        self.assertIn(module_file, spec.argv)
        for p in (spec.executable, spec.cwd, spec.stdout_path, spec.stderr_path):
            self.assertTrue(Path(p).is_absolute())

    def test_intent_has_no_executable_or_module_field(self) -> None:
        fields = set(DeterministicIntent.__dataclass_fields__)
        for forbidden in ("executable", "argv", "command", "module", "backend"):
            self.assertNotIn(forbidden, fields)


class TestFailClosed(unittest.TestCase):
    def test_worker_nonzero_exit_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            cassette, digest = _write_cassette(tmp)
            launcher = _FakeLauncher(_result_json(digest), exit_code=13)
            port = TrustedExecutionPort(launcher, FAKE_PYTHON)
            with self.assertRaises(WorkerExecutionFailed):
                port.execute(ExecutionMode.DETERMINISTIC, _intent(tmp, cassette),
                             timeout_s=5.0)

    def test_worker_timeout_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            cassette, digest = _write_cassette(tmp)
            launcher = _FakeLauncher(_result_json(digest), timed_out=True)
            port = TrustedExecutionPort(launcher, FAKE_PYTHON)
            with self.assertRaises(WorkerExecutionFailed):
                port.execute(ExecutionMode.DETERMINISTIC, _intent(tmp, cassette),
                             timeout_s=5.0)

    def test_malformed_result_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            cassette, _ = _write_cassette(tmp)
            launcher = _FakeLauncher("not json at all")
            port = TrustedExecutionPort(launcher, FAKE_PYTHON)
            with self.assertRaises(WorkerResultInvalid):
                port.execute(ExecutionMode.DETERMINISTIC, _intent(tmp, cassette),
                             timeout_s=5.0)

    def test_wrong_schema_result_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            cassette, _ = _write_cassette(tmp)
            launcher = _FakeLauncher(json.dumps({"schema": "evil", "ok": True}))
            port = TrustedExecutionPort(launcher, FAKE_PYTHON)
            with self.assertRaises(WorkerResultInvalid):
                port.execute(ExecutionMode.DETERMINISTIC, _intent(tmp, cassette),
                             timeout_s=5.0)

    def test_launched_worker_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            cassette, digest = _write_cassette(tmp)
            launcher = _FakeLauncher(_result_json(digest))
            port = TrustedExecutionPort(launcher, FAKE_PYTHON)
            port.execute(ExecutionMode.DETERMINISTIC, _intent(tmp, cassette),
                         timeout_s=5.0)
            assert launcher.launched is not None
            self.assertTrue(launcher.launched.closed)


class TestStage2AHardening(unittest.TestCase):
    """H1 bounded output, H3 duplicate result keys, closed result schema,
    H4 expected-cassette-digest binding, and the cassette-missing guard."""

    def test_h4_digest_mismatch_fails_closed(self) -> None:
        # The Worker reports a well-formed but WRONG cassette digest (the sealed
        # bytes are not the bytes it claims to have run).
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            cassette, _digest = _write_cassette(tmp)
            launcher = _FakeLauncher(_result_json("b" * 64))
            port = TrustedExecutionPort(launcher, FAKE_PYTHON)
            with self.assertRaises(WorkerResultInvalid):
                port.execute(ExecutionMode.DETERMINISTIC, _intent(tmp, cassette),
                             timeout_s=5.0)

    def test_h1_oversize_stdout_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            cassette, digest = _write_cassette(tmp)
            # A valid JSON object padded past the ceiling with whitespace.
            huge = _result_json(digest) + (" " * (MAX_RESULT_BYTES + 8))
            launcher = _FakeLauncher(huge)
            port = TrustedExecutionPort(launcher, FAKE_PYTHON)
            with self.assertRaises(WorkerResultInvalid):
                port.execute(ExecutionMode.DETERMINISTIC, _intent(tmp, cassette),
                             timeout_s=5.0)

    def test_closed_result_schema_rejects_unknown_key(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            cassette, digest = _write_cassette(tmp)
            launcher = _FakeLauncher(_result_json(digest, sneaky="authority"))
            port = TrustedExecutionPort(launcher, FAKE_PYTHON)
            with self.assertRaises(WorkerResultInvalid):
                port.execute(ExecutionMode.DETERMINISTIC, _intent(tmp, cassette),
                             timeout_s=5.0)

    def test_h3_duplicate_result_key_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            cassette, digest = _write_cassette(tmp)
            dup = ('{"schema":"' + dw.RESULT_SCHEMA + '","schema":"x","ok":true,'
                   '"cassette_sha256":"' + digest + '","turn_count":1,'
                   '"final_message":"done","provider_calls":0}')
            launcher = _FakeLauncher(dup)
            port = TrustedExecutionPort(launcher, FAKE_PYTHON)
            with self.assertRaises(WorkerResultInvalid):
                port.execute(ExecutionMode.DETERMINISTIC, _intent(tmp, cassette),
                             timeout_s=5.0)

    def test_missing_cassette_fails_closed_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            launcher = _FakeLauncher(_result_json("a" * 64))
            port = TrustedExecutionPort(launcher, FAKE_PYTHON)
            with self.assertRaises(TrustedExecutionError):
                port.execute(ExecutionMode.DETERMINISTIC,
                             _intent(tmp, tmp / "nope.json"), timeout_s=5.0)
            self.assertIsNone(launcher.spec)  # never launched


class TestNoBypassStructural(unittest.TestCase):
    """AST/structural guards: the port must not contain a route around the
    trusted launcher. These kill the Stage-2A mutation set at the source."""

    def _source(self) -> str:
        return Path(execution.__file__).read_text(encoding="utf-8")

    def test_no_subprocess_or_os_exec_in_execution_port(self) -> None:
        tree = ast.parse(self._source())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("subprocess", imported,
                         "execution port must not import subprocess")
        banned_attrs = {"system", "popen", "exec", "execv", "execvp",
                        "execve", "spawn", "spawnv"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and (
                    isinstance(node.value, ast.Name) and node.value.id in {
                        "subprocess", "os"} and (
                        node.attr in banned_attrs or node.value.id == "subprocess")):
                self.fail(f"execution port uses {node.value.id}.{node.attr}")
            if isinstance(node, ast.Name) and node.id == "Popen":
                self.fail("execution port references Popen")

    def test_port_does_not_run_worker_in_director_process(self) -> None:
        src = self._source()
        self.assertNotIn("deterministic_worker.run(", src)
        self.assertNotIn("deterministic_worker.main(", src)

    def test_port_does_not_reference_directororchestrator(self) -> None:
        self.assertNotIn("DirectorOrchestrator", self._source())

    def test_launch_is_the_only_execution_call(self) -> None:
        tree = ast.parse(self._source())
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self" and node.func.attr.startswith("_launch")
        }
        self.assertEqual(calls, set())


if __name__ == "__main__":
    unittest.main()
