"""Adapters satisfying gnosis.kernel.code_intelligence.CodeIntelligenceProvider.

Each adapter shells out to one external tool's CLI via an injectable
command runner, so the parsing logic is unit-testable without the real
tool installed (Gnosis's own test suite stays dependency-free, per M0/M1
principle). The command runner defaults to a real subprocess call.

CodegraphMcpAdapter targets codegraph-mcp (github.com/StarQuant/
codegraph-mcp), the M2.1 benchmark's recommended default provider: MIT,
Windows-verified. The two output shapes parsed below (caller/callee
listings vs impact listings) were reverse-engineered from real CLI
output captured during the M2.1 lab benchmark, not guessed; the CLI
emits ANSI color codes even with NO_COLOR/FORCE_COLOR set in some code
paths, so both parsers strip ANSI escapes defensively before matching.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

from .code_intelligence import (
    CodeIntelligenceProvider,
    CodeIntelligenceUnavailable,
    ImpactResult,
    SymbolLocation,
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_SYMBOL_KINDS = ("function", "method", "class", "variable")

# callers/callees shape:
#   function    entrypoint
#     pkg/core.py:4
_ENTRY_HEADER_RE = re.compile(r"^(" + "|".join(_SYMBOL_KINDS) + r")\s+(\S+)\s*$")
_ENTRY_LOCATION_RE = re.compile(r"^\s*(\S+):(\d+)\s*$")

# impact shape:
#   pkg/helpers.py
#     function    compute_c:8
_IMPACT_LINE_RE = re.compile(r"^\s*(" + "|".join(_SYMBOL_KINDS) + r")\s+(\S+):(\d+)\s*$")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _parse_caller_callee_entries(text: str) -> Tuple[SymbolLocation, ...]:
    """Parses codegraph-mcp's `callers`/`callees` output. Skips "file"-kind
    rows (file nodes in codegraph-mcp's graph, not callable symbols)."""
    lines = _strip_ansi(text).splitlines()
    results: list = []
    i = 0
    while i < len(lines):
        header = _ENTRY_HEADER_RE.match(lines[i])
        if header and i + 1 < len(lines):
            loc = _ENTRY_LOCATION_RE.match(lines[i + 1])
            if loc:
                results.append(SymbolLocation(
                    qualified_name=header.group(2), file=loc.group(1), line=int(loc.group(2)),
                ))
                i += 2
                continue
        i += 1
    return tuple(results)


def _parse_impact_entries(text: str) -> Tuple[SymbolLocation, ...]:
    """Parses codegraph-mcp's `impact` output: a file-path header line
    followed by one or more "<kind>    <name>:<line>" lines. Skips
    "file"-kind rows for the same reason as above."""
    results: list = []
    current_file: Optional[str] = None
    for raw_line in _strip_ansi(text).splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        matched = _IMPACT_LINE_RE.match(line)
        if matched:
            results.append(SymbolLocation(
                qualified_name=matched.group(2), file=current_file or matched.group(2), line=int(matched.group(3)),
            ))
        elif not line.startswith(" "):
            current_file = line.strip()
    return tuple(results)


CommandRunner = Callable[[Sequence[str]], str]


class CodegraphMcpAdapter(CodeIntelligenceProvider):
    def __init__(
        self,
        repo_path: Path,
        node_binary: str = "node",
        codegraph_js: str = "codegraph",
        command_runner: Optional[CommandRunner] = None,
        timeout_s: float = 120.0,
    ):
        self.repo_path = repo_path
        self.node_binary = node_binary
        self.codegraph_js = codegraph_js
        self.timeout_s = timeout_s
        self._run = command_runner or self._default_runner

    def _default_runner(self, args: Sequence[str]) -> str:
        try:
            proc = subprocess.run(
                [self.node_binary, self.codegraph_js, *args],
                cwd=str(self.repo_path), capture_output=True, text=True,
                timeout=self.timeout_s, env={**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CodeIntelligenceUnavailable(f"codegraph-mcp invocation failed: {exc}") from exc
        return proc.stdout

    def index(self, repo_path: Path) -> None:
        self._run(["init", str(repo_path)])

    def callers(self, symbol: str) -> Tuple[SymbolLocation, ...]:
        return _parse_caller_callee_entries(self._run(["callers", symbol]))

    def callees(self, symbol: str) -> Tuple[SymbolLocation, ...]:
        return _parse_caller_callee_entries(self._run(["callees", symbol]))

    def impact(self, symbol: str) -> ImpactResult:
        entries = _parse_impact_entries(self._run(["impact", symbol]))
        return ImpactResult(changed_symbol=symbol, impacted_symbols=entries)
