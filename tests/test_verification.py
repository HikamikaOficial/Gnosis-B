import sys
import tempfile
import unittest
from pathlib import Path

from gnosis.kernel.verification import CommandVerifier, CompositeVerifier


class TestCommandVerifier(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_passing_command(self):
        v = CommandVerifier("ok", [sys.executable, "-c", "print('hi')"])
        result = v.run(self.cwd)
        self.assertTrue(result.passed)
        self.assertEqual(result.exit_code, 0)

    def test_failing_command(self):
        v = CommandVerifier("fail", [sys.executable, "-c", "import sys; sys.exit(1)"])
        result = v.run(self.cwd)
        self.assertFalse(result.passed)
        self.assertEqual(result.exit_code, 1)

    def test_missing_binary(self):
        v = CommandVerifier("missing", ["definitely-not-a-real-binary-xyz"])
        result = v.run(self.cwd)
        self.assertFalse(result.passed)

    def test_timeout(self):
        v = CommandVerifier("slow", [sys.executable, "-c", "import time; time.sleep(5)"], timeout_s=0.2)
        result = v.run(self.cwd)
        self.assertFalse(result.passed)
        self.assertIn("TIMEOUT", result.stderr_excerpt)

    def test_redacts_secrets_in_output(self):
        v = CommandVerifier(
            "secretive", [sys.executable, "-c", "print('sk-ant-api03-abcdefghijklmno')"],
        )
        result = v.run(self.cwd)
        self.assertNotIn("sk-ant-", result.stdout_excerpt)


class TestCompositeVerifier(unittest.TestCase):
    def test_all_pass(self):
        v = CompositeVerifier("suite", [
            CommandVerifier("a", [sys.executable, "-c", "pass"]),
            CommandVerifier("b", [sys.executable, "-c", "pass"]),
        ])
        result = v.run(Path("."))
        self.assertTrue(result.passed)

    def test_one_fails(self):
        v = CompositeVerifier("suite", [
            CommandVerifier("a", [sys.executable, "-c", "pass"]),
            CommandVerifier("b", [sys.executable, "-c", "import sys; sys.exit(1)"]),
        ])
        result = v.run(Path("."))
        self.assertFalse(result.passed)


if __name__ == "__main__":
    unittest.main()
