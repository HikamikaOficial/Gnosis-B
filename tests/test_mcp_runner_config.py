import unittest

from gnosis.runner.claude_cli_runner import ClaudeCodeCLIRunner, McpRunnerConfig


class TestMcpRunnerConfig(unittest.TestCase):
    def test_rejects_empty_config_paths(self):
        with self.assertRaises(ValueError):
            McpRunnerConfig(config_paths=())

    def test_to_dict(self):
        cfg = McpRunnerConfig(config_paths=("a.json", "b.json"), strict=True)
        self.assertEqual(cfg.to_dict(), {"config_paths": ["a.json", "b.json"], "strict": True})


class TestBuildArgvMcp(unittest.TestCase):
    def setUp(self):
        self.runner = ClaudeCodeCLIRunner(binary="claude")

    def test_unused_by_default_argv_unchanged(self):
        with_mcp = self.runner.build_argv("do it")
        without_any_mcp_param = self.runner.build_argv("do it", mcp=None)
        self.assertEqual(with_mcp, without_any_mcp_param)
        self.assertNotIn("--mcp-config", with_mcp)
        self.assertNotIn("--strict-mcp-config", with_mcp)

    def test_mcp_config_appends_flag_and_paths(self):
        cfg = McpRunnerConfig(config_paths=("servers.json",))
        argv = self.runner.build_argv("do it", mcp=cfg)
        self.assertIn("--mcp-config", argv)
        idx = argv.index("--mcp-config")
        self.assertEqual(argv[idx + 1], "servers.json")
        self.assertNotIn("--strict-mcp-config", argv)

    def test_mcp_config_multiple_paths(self):
        cfg = McpRunnerConfig(config_paths=("a.json", "b.json"))
        argv = self.runner.build_argv("do it", mcp=cfg)
        idx = argv.index("--mcp-config")
        self.assertEqual(argv[idx + 1 : idx + 3], ["a.json", "b.json"])

    def test_strict_flag_appended_when_set(self):
        cfg = McpRunnerConfig(config_paths=("servers.json",), strict=True)
        argv = self.runner.build_argv("do it", mcp=cfg)
        self.assertIn("--strict-mcp-config", argv)

    def test_no_hard_dependency_on_specific_server_name(self):
        # McpRunnerConfig only carries file paths; nothing in the runner
        # references any particular MCP server implementation.
        cfg = McpRunnerConfig(config_paths=("whatever-tool-i-want.json",))
        argv = self.runner.build_argv("do it", mcp=cfg)
        self.assertIn("whatever-tool-i-want.json", argv)


if __name__ == "__main__":
    unittest.main()
