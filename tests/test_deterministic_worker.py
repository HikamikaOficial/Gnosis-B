"""Unit tests for the F-33 Stage-2A deterministic Worker entry.

These qualify the entry's I/O CONTRACT in isolation (component level). They do
not, and cannot, satisfy the OS-real trusted-launch qualification gate, which is
covered separately by launching this image through the real `WorkerLauncher`.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from gnosis.director import deterministic_worker as dw


def _write(path: Path, obj: object) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def _valid_cassette() -> dict[str, object]:
    return {
        "schema": dw.CASSETTE_SCHEMA,
        "turns": [{"message": "hello"}, {"message": "done"}],
    }


class TestRunContract(unittest.TestCase):
    def test_valid_cassette_produces_bounded_result(self) -> None:
        result = dw.run  # bind for clarity
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = _write(Path(d) / "c.json", _valid_cassette())
            out = result(str(path))
        self.assertEqual(out["schema"], dw.RESULT_SCHEMA)
        self.assertTrue(out["ok"])
        self.assertEqual(out["turn_count"], 2)
        self.assertEqual(out["final_message"], "done")
        self.assertEqual(out["provider_calls"], 0)
        self.assertRegex(str(out["cassette_sha256"]), r"\A[0-9a-f]{64}\Z")

    def test_wrong_schema_rejected(self) -> None:
        with self.assertRaises(dw.CassetteInvalid):
            dw.validate_cassette({"schema": "other", "turns": [{"message": "x"}]})

    def test_authority_shaped_keys_rejected(self) -> None:
        for key in ("executable", "module", "mode", "policy", "run_id",
                    "deployment_digest", "authorize", "environment"):
            with self.subTest(key=key):
                bad = _valid_cassette()
                bad[key] = "anything"
                with self.assertRaises(dw.CassetteInvalid):
                    dw.validate_cassette(bad)

    def test_empty_turns_rejected(self) -> None:
        with self.assertRaises(dw.CassetteInvalid):
            dw.validate_cassette({"schema": dw.CASSETTE_SCHEMA, "turns": []})

    def test_non_string_message_rejected(self) -> None:
        with self.assertRaises(dw.CassetteInvalid):
            dw.validate_cassette(
                {"schema": dw.CASSETTE_SCHEMA, "turns": [{"message": 3}]})

    def test_oversize_cassette_rejected(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            big = Path(d) / "big.json"
            big.write_bytes(b"{" + b" " * (dw.MAX_CASSETTE_BYTES + 8))
            with self.assertRaises(dw.CassetteInvalid):
                dw._read_cassette_bytes(str(big))


class TestMainCli(unittest.TestCase):
    """Invoke the module as a script in isolated mode — the same shape the
    sealed LaunchSpec uses (absolute python -I -B <module file> <cassette>),
    but here run directly (NOT through the trusted boundary, which the OS-real
    test covers)."""

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        module_file = Path(dw.__file__).resolve()
        return subprocess.run(
            [sys.executable, "-I", "-B", str(module_file), *args],
            capture_output=True, text=True, check=False)

    def test_cli_success_emits_one_json_line_exit_0(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = _write(Path(d) / "c.json", _valid_cassette())
            proc = self._run([str(path)])
        self.assertEqual(proc.returncode, dw.EXIT_OK, proc.stderr)
        payload = json.loads(proc.stdout.strip())
        self.assertEqual(payload["schema"], dw.RESULT_SCHEMA)
        self.assertEqual(payload["final_message"], "done")

    def test_cli_usage_error_exit(self) -> None:
        proc = self._run([])
        self.assertEqual(proc.returncode, dw.EXIT_USAGE)

    def test_cli_invalid_cassette_exit(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = _write(Path(d) / "c.json", {"schema": "nope", "turns": []})
            proc = self._run([str(path)])
        self.assertEqual(proc.returncode, dw.EXIT_CASSETTE_INVALID, proc.stdout)

    def test_cli_missing_file_exit(self) -> None:
        proc = self._run([str(Path("does-not-exist-xyz.json"))])
        self.assertEqual(proc.returncode, dw.EXIT_CASSETTE_UNREADABLE)


if __name__ == "__main__":
    unittest.main()
