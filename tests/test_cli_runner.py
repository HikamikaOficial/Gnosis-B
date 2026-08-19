import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

from gnosis.runner.claude_cli_runner import CancellationToken, CLIRunner, ClaudeCodeCLIRunner


class TestCLIRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.runner = CLIRunner(poll_interval_s=0.05)

    def tearDown(self):
        # Windows: a child killed via TerminateProcess can keep its inherited
        # out/err.log handles alive for a moment after wait() returns, so a
        # same-instant cleanup loses the race (WinError 32). Bounded retry:
        # a handle still held after ~2s would be a real leak and must fail.
        for attempt in range(10):
            try:
                self.tmp.cleanup()
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.2)

    def _run(self, code, timeout_s=10.0, cancellation_token=None, heartbeat_fn=None, heartbeat_interval_s=5.0):
        return self.runner.run(
            [sys.executable, "-c", code], cwd=self.dir,
            stdout_path=self.dir / "out.log", stderr_path=self.dir / "err.log",
            timeout_s=timeout_s, cancellation_token=cancellation_token,
            heartbeat_fn=heartbeat_fn, heartbeat_interval_s=heartbeat_interval_s,
        )

    def test_success_captures_stdout(self):
        result = self._run("print('hello gnosis')")
        self.assertEqual(result.exit_code, 0)
        self.assertTrue(result.succeeded)
        self.assertIn("hello gnosis", Path(result.stdout_path).read_text())

    def test_nonzero_exit(self):
        result = self._run("import sys; sys.exit(3)")
        self.assertEqual(result.exit_code, 3)
        self.assertFalse(result.succeeded)

    def test_stderr_captured(self):
        result = self._run("import sys; sys.stderr.write('boom')")
        self.assertIn("boom", Path(result.stderr_path).read_text())

    def test_timeout_kills_process(self):
        result = self._run("import time; time.sleep(30)", timeout_s=0.5)
        self.assertTrue(result.timed_out)
        self.assertFalse(result.succeeded)

    def test_cancellation(self):
        token = CancellationToken()
        token.cancel()
        result = self._run("import time; time.sleep(30)", timeout_s=30, cancellation_token=token)
        self.assertTrue(result.cancelled)
        self.assertFalse(result.succeeded)

    def test_heartbeat_invoked_during_long_run(self):
        calls = []
        result = self._run(
            "import time; time.sleep(0.6)", timeout_s=5,
            heartbeat_fn=lambda pid: calls.append(pid), heartbeat_interval_s=0.1,
        )
        self.assertTrue(result.succeeded)
        self.assertGreater(len(calls), 0)


class TestClaudeCodeCLIRunnerArgv(unittest.TestCase):
    def test_build_argv_defaults(self):
        runner = ClaudeCodeCLIRunner(binary="claude")
        argv = runner.build_argv("do the thing")
        self.assertEqual(argv[0], "claude")
        self.assertIn("-p", argv)
        self.assertIn("do the thing", argv)
        self.assertIn("--output-format", argv)
        self.assertIn("json", argv)
        self.assertIn("--permission-mode", argv)
        self.assertIn("plan", argv)

    def test_build_argv_with_session_and_model(self):
        runner = ClaudeCodeCLIRunner(binary="claude")
        argv = runner.build_argv("x", session_id="abc-123", model="sonnet")
        self.assertIn("--session-id", argv)
        self.assertIn("abc-123", argv)
        self.assertIn("--model", argv)
        self.assertIn("sonnet", argv)


@unittest.skipUnless(shutil.which("claude"), "claude CLI not installed on this machine")
class TestRealClaudeCliSmoke(unittest.TestCase):
    def test_version_invocation_via_cli_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            runner = CLIRunner()
            result = runner.run(
                ["claude", "--version"], cwd=d, stdout_path=d / "out.log", stderr_path=d / "err.log",
                timeout_s=15,
            )
            self.assertEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
