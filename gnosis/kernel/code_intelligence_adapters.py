"""Adapters satisfying gnosis.kernel.code_intelligence.CodeIntelligenceProvider.

Each adapter shells out to one external tool's CLI via an injectable
command runner, so the parsing logic is unit-testable without the real
tool installed (Gnosis's own test suite stays dependency-free, per M0/M1
principle). The command runner defaults to a real subprocess call.

CodegraphMcpAdapter is the production adapter for codegraph-mcp (github.com/
StarQuant/codegraph-mcp), selected in the M2.1 benchmark: MIT, Windows-
verified, zero false positives/negatives on every ground-truth query
tested. Every parser below was built from real CLI output captured during
that benchmark and this milestone's lifecycle testing, not guessed.
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
    CompactContext,
    ImpactResult,
    IndexStatus,
    SymbolLocation,
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_SYMBOL_KINDS = ("function", "method", "class", "variable")

_ENTRY_HEADER_RE = re.compile(r"^(" + "|".join(_SYMBOL_KINDS) + r")\s+(\S+)\s*$")
_ENTRY_LOCATION_RE = re.compile(r"^\s*(\S+):(\d+)\s*$")
_IMPACT_LINE_RE = re.compile(r"^\s*(" + "|".join(_SYMBOL_KINDS) + r")\s+(\S+):(\d+)\s*$")

_STATUS_INT_RE = {
    "files": re.compile(r"^\s*Files:\s*(\d+)\s*$"),
    "nodes": re.compile(r"^\s*Nodes:\s*(\d+)\s*$"),
    "edges": re.compile(r"^\s*Edges:\s*(\d+)\s*$"),
}

_EXPLORE_TEXT_LIMIT = 8000


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _parse_symbol_entries(text: str) -> Tuple[SymbolLocation, ...]:
    """Shared parser for callers/callees/query output (all three use the
    same "<kind>  <name>" + indented "<file>:<line>" two-line shape, with
    an optional ignored third line). Non-symbol kinds ("file", "import")
    never match _ENTRY_HEADER_RE, so they are skipped automatically."""
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
    """Parses `impact` output: a file-path header line followed by one or
    more "<kind>    <name>:<line>" lines."""
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


def _parse_status(text: str) -> IndexStatus:
    """Parses `codegraph status` output, e.g.:

        Index Statistics:
          Files:     12
          Nodes:     29
          Edges:     37
        ...
        [OK] Index is up to date

    or, when the working tree has diverged from the last index:

        Pending Changes:
          Modified:  1 files
        [i] Run "codegraph sync" to update the index
    """
    clean = _strip_ansi(text)
    if "not initialized" in clean.lower():
        return IndexStatus(available=False, stale=True, detail="Index not initialized.")

    values = {"files": 0, "nodes": 0, "edges": 0}
    for line in clean.splitlines():
        for key, pattern in _STATUS_INT_RE.items():
            match = pattern.match(line)
            if match:
                values[key] = int(match.group(1))

    stale = "up to date" not in clean.lower() or "pending changes" in clean.lower()
    return IndexStatus(
        available=True, files_indexed=values["files"], nodes=values["nodes"], edges=values["edges"],
        stale=stale, detail="up to date" if not stale else "pending changes since last index",
    )


def _extract_related_symbols(explore_text: str) -> Tuple[str, ...]:
    """Best-effort extraction of symbol names mentioned in an `explore`
    response's "Blast radius" bullet list (backtick-quoted names). The
    text itself remains authoritative; this is a convenience index."""
    return tuple(dict.fromkeys(re.findall(r"^- `([^`]+)`", explore_text, flags=re.MULTILINE)))


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
                encoding="utf-8", errors="replace",
                timeout=self.timeout_s, env={**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CodeIntelligenceUnavailable(f"codegraph-mcp invocation failed: {exc}") from exc
        return proc.stdout

    def index(self, repo_path: Path, full: bool = False) -> None:
        command = "index" if full else "sync"
        output = self._run([command, str(repo_path)])
        if "not found" in output.lower() or "not initialized" in output.lower():
            self._run(["init", str(repo_path)])

    def status(self) -> IndexStatus:
        try:
            return _parse_status(self._run(["status", str(self.repo_path)]))
        except CodeIntelligenceUnavailable:
            return IndexStatus(available=False, stale=True, detail="Provider unavailable.")

    def find(self, query: str) -> Tuple[SymbolLocation, ...]:
        return _parse_symbol_entries(self._run(["query", query]))

    def callers(self, symbol: str) -> Tuple[SymbolLocation, ...]:
        return _parse_symbol_entries(self._run(["callers", symbol]))

    def callees(self, symbol: str) -> Tuple[SymbolLocation, ...]:
        return _parse_symbol_entries(self._run(["callees", symbol]))

    def impact(self, symbol: str) -> ImpactResult:
        entries = _parse_impact_entries(self._run(["impact", symbol]))
        return ImpactResult(changed_symbol=symbol, impacted_symbols=entries)

    def explore(self, query: str) -> CompactContext:
        raw = _strip_ansi(self._run(["explore", query]))
        bounded = raw[:_EXPLORE_TEXT_LIMIT]
        return CompactContext(query=query, text=bounded, related_symbols=_extract_related_symbols(bounded))
