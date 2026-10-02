"""Unit tests for the F-33 Stage-2A trusted execution runner (result mapping).

A fake port isolates the adapter's translation logic: a successful
`ExecutionOutcome` becomes a succeeded `ExecutionResult`; every fail-closed port
error becomes a FAILED result and never a success or a fallback.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from gnosis.director import deterministic_worker as dw
from gnosis.director.execution import (
    ExecutionMode,
    ExecutionOutcome,
    WorkerExecutionFailed,
    WorkerResultInvalid,
)
from gnosis.director.trusted_runner import (
    TrustedExecutionRunner,
    deterministic_cassette_source,
)


class _FakePort:
    def __init__(self, *, outcome: ExecutionOutcome | None = None,
                 raises: Exception | None = None) -> None:
        self._outcome = outcome
        self._raises = raises
        self.calls: list[tuple[ExecutionMode, Any]] = []

    def execute(self, mode: ExecutionMode, intent: Any, *,
                timeout_s: float) -> ExecutionOutcome:
        self.calls.append((mode, intent))
        if self._raises is not None:
            raise self._raises
        assert self._outcome is not None
        return self._outcome


def _ok_outcome() -> ExecutionOutcome:
    return ExecutionOutcome(
        exit_code=0,
        result={"schema": dw.RESULT_SCHEMA, "ok": True, "cassette_sha256": "a" * 64,
                "turn_count": 1, "final_message": "done", "provider_calls": 0},
        launch={"observed_sid": "S-1-5-21-x", "is_administrator": False})


class TestRunnerMapping(unittest.TestCase):
    def _run(self, port: _FakePort) -> Any:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            ws = tmp / "ws"
            runner = TrustedExecutionRunner(port, workspace=ws)  # type: ignore[arg-type]
            return runner.run(prompt="do it", cwd=tmp,
                              stdout_path=tmp / "o.txt", stderr_path=tmp / "e.txt",
                              timeout_s=5.0)

    def test_success_maps_to_succeeded_result(self) -> None:
        port = _FakePort(outcome=_ok_outcome())
        result = self._run(port)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.parsed_json["schema"], dw.RESULT_SCHEMA)
        self.assertEqual(result.launch["observed_sid"], "S-1-5-21-x")
        self.assertEqual(port.calls[0][0], ExecutionMode.DETERMINISTIC)

    def test_worker_execution_failed_maps_to_failed(self) -> None:
        port = _FakePort(raises=WorkerExecutionFailed("deterministic Worker exited 13"))
        result = self._run(port)
        self.assertFalse(result.succeeded)
        self.assertEqual(result.exit_code, 1)
        self.assertIsNone(result.parsed_json)

    def test_timeout_maps_to_timed_out(self) -> None:
        port = _FakePort(raises=WorkerExecutionFailed("deterministic Worker timed out after 5s"))
        result = self._run(port)
        self.assertFalse(result.succeeded)
        self.assertTrue(result.timed_out)

    def test_invalid_result_maps_to_failed(self) -> None:
        port = _FakePort(raises=WorkerResultInvalid("bad digest"))
        result = self._run(port)
        self.assertFalse(result.succeeded)
        self.assertIsNone(result.parsed_json)

    def test_cassette_source_is_closed_schema(self) -> None:
        blob = deterministic_cassette_source("anything")
        cassette = json.loads(blob)
        self.assertEqual(set(cassette), {"schema", "turns"})
        self.assertEqual(cassette["schema"], dw.CASSETTE_SCHEMA)
        # It validates against the worker's closed schema.
        dw.validate_cassette(cassette)

    def test_binary_name(self) -> None:
        port = _FakePort(outcome=_ok_outcome())
        runner = TrustedExecutionRunner(port)  # type: ignore[arg-type]
        self.assertEqual(runner.binary, "trusted-execution-port:deterministic")


if __name__ == "__main__":
    unittest.main()
