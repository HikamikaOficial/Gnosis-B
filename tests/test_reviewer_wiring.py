"""F-33 Stage-2C-A — production reviewer wiring (R1-R8).

The canonical operator route wires a REAL provider-backed reviewer runner
(distinct object), never a replay runner and never an always-pass fake; the
reviewer executable is trusted/deployment configuration, never operator input.
No provider is invoked here (construction only).
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

from gnosis.director import cli
from gnosis.director import composition as comp_mod
from gnosis.director.cli import OperatorError, build_reviewer
from gnosis.runner.claude_cli_runner import ClaudeCodeCLIRunner


class TestReviewerWiring(unittest.TestCase):
    def test_r1_builds_real_claude_runner(self) -> None:
        # A valid absolute existing binary → a ClaudeCodeCLIRunner (distinct
        # object type from the trusted-execution implementer). sys.executable
        # stands in for an existing absolute deployment binary.
        runner = build_reviewer({"binary": sys.executable})
        self.assertIsInstance(runner, ClaudeCodeCLIRunner)
        self.assertEqual(runner.binary, sys.executable)

    def test_r2_no_replay_runner_in_production_source(self) -> None:
        for module in (cli, comp_mod):
            src = Path(module.__file__).read_text(encoding="utf-8")
            names = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
            self.assertNotIn("ReplayingCLIRunner", names,
                             f"{module.__name__} must not reference the replay runner")
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn("ReplayingCLIRunner",
                                     {a.name for a in node.names})

    def test_r3_reviewer_unavailable_fails_closed(self) -> None:
        with self.assertRaises(OperatorError) as ctx:
            build_reviewer({"binary": r"C:\definitely\not\here\claude.exe"})
        self.assertEqual(ctx.exception.code, cli.EXIT_EXECUTION)

    def test_r8_operator_cannot_select_relative_executable(self) -> None:
        with self.assertRaises(OperatorError) as ctx:
            build_reviewer({"binary": "claude"})  # relative / PATH lookup
        self.assertEqual(ctx.exception.code, cli.EXIT_USAGE)

    def test_missing_binary_is_usage_error(self) -> None:
        with self.assertRaises(OperatorError) as ctx:
            build_reviewer({})
        self.assertEqual(ctx.exception.code, cli.EXIT_USAGE)

    def test_r4_malformed_review_output_fails_closed(self) -> None:
        # The reviewer output contract fails closed on garbage (underpins R4).
        from gnosis.adapters.review_payload import (
            InvalidReviewOutput,
            parse_review_payload,
        )
        with self.assertRaises(InvalidReviewOutput):
            parse_review_payload("not a review verdict at all", reviewer="reviewer@team")


if __name__ == "__main__":
    unittest.main()
