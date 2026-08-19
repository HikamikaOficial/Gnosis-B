import shutil
import unittest
from pathlib import Path

from gnosis.kernel.code_intelligence import (
    CodeIntelligenceUnavailable,
    ImpactResult,
    NullCodeIntelligenceProvider,
    SymbolLocation,
)
from gnosis.kernel.code_intelligence_adapters import CodegraphMcpAdapter

# Real codegraph-mcp CLI output, captured verbatim (NO_COLOR=1) during the
# M2.1 lab benchmark against the Gnosis fixture repo. Used here so the
# parser is tested against real tool output, not a guessed format.
REAL_CALLERS_OUTPUT = '''
Callers of "compute_c" (2):

function    entrypoint
  pkg/core.py:4

file        core.py
  pkg/core.py:1
'''

REAL_IMPACT_OUTPUT = '''
Impact of changing "compute_c" -- 5 affected symbols:

pkg/helpers.py
  function    compute_c:8

pkg/core.py
  function    entrypoint:4
  file        core.py:1

tests/test_core.py
  function    test_entrypoint:4
  file        test_core.py:1
'''

REAL_CALLEES_OUTPUT = '''
Callees of "entrypoint" (2):

function    compute_b_renamed
  pkg/helpers.py:4

function    compute_c
  pkg/helpers.py:8
'''

REAL_NO_CALLERS_OUTPUT = '''
[i] No callers found for "unused_function"
'''


class TestNullCodeIntelligenceProvider(unittest.TestCase):
    def test_index_is_a_no_op(self):
        provider = NullCodeIntelligenceProvider()
        self.assertIsNone(provider.index(Path(".")))

    def test_queries_raise_unavailable(self):
        provider = NullCodeIntelligenceProvider()
        with self.assertRaises(CodeIntelligenceUnavailable):
            provider.callers("x")
        with self.assertRaises(CodeIntelligenceUnavailable):
            provider.callees("x")
        with self.assertRaises(CodeIntelligenceUnavailable):
            provider.impact("x")


class TestSymbolLocationAndImpactResult(unittest.TestCase):
    def test_symbol_location_to_dict(self):
        loc = SymbolLocation(qualified_name="pkg.core.entrypoint", file="pkg/core.py", line=4)
        self.assertEqual(loc.to_dict(), {"qualified_name": "pkg.core.entrypoint", "file": "pkg/core.py", "line": 4})

    def test_impact_result_to_dict(self):
        result = ImpactResult(
            changed_symbol="compute_c",
            impacted_symbols=(SymbolLocation("entrypoint", "pkg/core.py", 4),),
        )
        self.assertEqual(result.to_dict()["changed_symbol"], "compute_c")
        self.assertEqual(len(result.to_dict()["impacted_symbols"]), 1)


class TestCodegraphMcpAdapterParsing(unittest.TestCase):
    """Exercises the adapter's real CLI-output parser against text
    actually produced by codegraph-mcp during the M2.1 lab benchmark, not
    a hand-guessed format."""

    def _adapter_with_canned_output(self, output: str) -> CodegraphMcpAdapter:
        return CodegraphMcpAdapter(
            repo_path=Path("."), command_runner=lambda args: output,
        )

    def test_callers_parses_and_skips_file_nodes(self):
        adapter = self._adapter_with_canned_output(REAL_CALLERS_OUTPUT)
        callers = adapter.callers("compute_c")
        self.assertEqual(callers, (SymbolLocation("entrypoint", "pkg/core.py", 4),))

    def test_callees_parses_multiple_entries(self):
        adapter = self._adapter_with_canned_output(REAL_CALLEES_OUTPUT)
        callees = adapter.callees("entrypoint")
        self.assertEqual(callees, (
            SymbolLocation("compute_b_renamed", "pkg/helpers.py", 4),
            SymbolLocation("compute_c", "pkg/helpers.py", 8),
        ))

    def test_impact_parses_function_level_entries_only(self):
        adapter = self._adapter_with_canned_output(REAL_IMPACT_OUTPUT)
        result = adapter.impact("compute_c")
        self.assertEqual(result.changed_symbol, "compute_c")
        names = [s.qualified_name for s in result.impacted_symbols]
        self.assertEqual(names, ["compute_c", "entrypoint", "test_entrypoint"])

    def test_no_callers_output_parses_to_empty_tuple(self):
        adapter = self._adapter_with_canned_output(REAL_NO_CALLERS_OUTPUT)
        self.assertEqual(adapter.callers("unused_function"), ())

    def test_command_runner_is_injectable_not_hardcoded(self):
        calls = []

        def fake_runner(args):
            calls.append(list(args))
            return REAL_CALLERS_OUTPUT

        adapter = CodegraphMcpAdapter(repo_path=Path("/some/repo"), command_runner=fake_runner)
        adapter.callers("compute_c")
        self.assertEqual(calls, [["callers", "compute_c"]])

    def test_default_runner_unavailable_on_missing_binary(self):
        adapter = CodegraphMcpAdapter(repo_path=Path("."), node_binary="definitely-not-a-real-binary-xyz")
        with self.assertRaises(CodeIntelligenceUnavailable):
            adapter.callers("x")


_LAB_ROOT = Path(__file__).resolve().parent.parent / ".gnosis" / "lab" / "code-intelligence"
_LAB_NODE24 = _LAB_ROOT / "tools" / "node-v24.9.0-win-x64" / "node.exe"
_LAB_CODEGRAPH_JS = _LAB_ROOT / "candidates" / "codegraph-mcp" / "dist" / "bin" / "codegraph.js"
_LAB_FIXTURE_REPO = _LAB_ROOT / "datasets" / "fixture-repo"
_LAB_AVAILABLE = _LAB_NODE24.exists() and _LAB_CODEGRAPH_JS.exists() and _LAB_FIXTURE_REPO.exists()


@unittest.skipUnless(
    _LAB_AVAILABLE,
    "M2.1 lab install of codegraph-mcp not present on this machine (expected outside the lab session)",
)
class TestCodegraphMcpAdapterRealIntegration(unittest.TestCase):
    """Runs the real adapter against the real, already-indexed M2.1 lab
    fixture repo, not a fake runner. Skips cleanly on any machine that
    does not have the lab's npm-installed candidate (this is a one-time
    benchmark artifact, not a Gnosis dependency)."""

    def test_callers_of_compute_c_matches_ground_truth(self):
        adapter = CodegraphMcpAdapter(
            repo_path=_LAB_FIXTURE_REPO, node_binary=str(_LAB_NODE24), codegraph_js=str(_LAB_CODEGRAPH_JS),
        )
        callers = adapter.callers("compute_c")
        names = {c.qualified_name for c in callers}
        self.assertIn("entrypoint", names)

    def test_impact_of_compute_c_matches_ground_truth(self):
        adapter = CodegraphMcpAdapter(
            repo_path=_LAB_FIXTURE_REPO, node_binary=str(_LAB_NODE24), codegraph_js=str(_LAB_CODEGRAPH_JS),
        )
        result = adapter.impact("compute_c")
        names = {s.qualified_name for s in result.impacted_symbols}
        self.assertEqual(names, {"compute_c", "entrypoint", "test_entrypoint"})


if __name__ == "__main__":
    unittest.main()
