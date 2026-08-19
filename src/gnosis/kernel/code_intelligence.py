"""Gnosis's own Code Intelligence contract (M2 / M2.5).

Gnosis owns this interface; external tools satisfy it via adapters. No
kernel code should import a specific vendor's client directly -- every
call goes through CodeIntelligenceProvider, which is what keeps the
underlying tool replaceable (per the Director architectural rule: "do
not integrate a candidate merely because it wins one metric... the final
Code Intelligence Plane must be replaceable").

Code intelligence is an optional accelerant, never a hard dependency of
task execution: a provider that cannot answer raises
CodeIntelligenceUnavailable rather than the kernel silently proceeding
with wrong or stale data, but callers are expected to treat that as
"fall back to reading files," not as a fatal error. Gnosis must never
silently trust known-stale structural information: IndexStatus.stale
exists precisely so a caller can check before trusting a query result.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SymbolLocation:
    qualified_name: str
    file: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"qualified_name": self.qualified_name, "file": self.file, "line": self.line}


@dataclass(frozen=True)
class ImpactResult:
    changed_symbol: str
    impacted_symbols: tuple[SymbolLocation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_symbol": self.changed_symbol,
            "impacted_symbols": [s.to_dict() for s in self.impacted_symbols],
        }


@dataclass(frozen=True)
class IndexStatus:
    """Answers "can this index be trusted right now?" -- the load-bearing
    field is `stale`: a caller must check it before treating query
    results as authoritative, per the Director's "never silently trust
    known-stale structural information" instruction."""

    available: bool
    files_indexed: int = 0
    nodes: int = 0
    edges: int = 0
    stale: bool = True
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available, "files_indexed": self.files_indexed,
            "nodes": self.nodes, "edges": self.edges, "stale": self.stale, "detail": self.detail,
        }


@dataclass(frozen=True)
class CompactContext:
    """Bounded, LLM-ready context for one query -- the "compact context
    retrieval" capability. `text` is intentionally size-bounded by the
    adapter (never the full graph) so a caller can hand it straight to a
    prompt without its own budgeting logic."""

    query: str
    text: str
    related_symbols: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {"query": self.query, "text": self.text, "related_symbols": list(self.related_symbols)}


class CodeIntelligenceUnavailable(RuntimeError):
    """Raised when a provider cannot answer (index missing, tool not
    installed, query failed, or timed out). Callers must treat code
    intelligence as optional, never load-bearing for task correctness."""


class CodeIntelligenceProvider(ABC):
    """The contract. Implementation-specific adapters (one per external
    tool) live alongside this file; Gnosis kernel/task code depends only
    on this interface."""

    @abstractmethod
    def index(self, repo_path: Path, full: bool = False) -> None:
        """(Re)build the index for repo_path. full=False means
        incremental (sync changes since last index); full=True forces a
        clean rebuild. Implementations must handle "no index yet"
        transparently (i.e. an incremental call still produces a valid
        index on a fresh repo)."""
        raise NotImplementedError

    @abstractmethod
    def status(self) -> IndexStatus:
        """Current index health: available at all, and stale or not."""
        raise NotImplementedError

    @abstractmethod
    def find(self, query: str) -> tuple[SymbolLocation, ...]:
        """Symbol/definition lookup by name or fuzzy query."""
        raise NotImplementedError

    @abstractmethod
    def callers(self, symbol: str) -> tuple[SymbolLocation, ...]:
        """Functions/methods that call `symbol` (reference lookup)."""
        raise NotImplementedError

    @abstractmethod
    def callees(self, symbol: str) -> tuple[SymbolLocation, ...]:
        """Functions/methods that `symbol` calls (dependency relationships)."""
        raise NotImplementedError

    @abstractmethod
    def impact(self, symbol: str) -> ImpactResult:
        """Blast-radius analysis for a prospective change to `symbol`."""
        raise NotImplementedError

    @abstractmethod
    def explore(self, query: str) -> CompactContext:
        """Compact, LLM-ready context for a symbol/query: relevant source
        + relationships in one bounded response. This is the method
        TaskEngine uses for pre-task context gathering -- never dump the
        full graph, always retrieve only what is relevant to `query`."""
        raise NotImplementedError


class NullCodeIntelligenceProvider(CodeIntelligenceProvider):
    """Reference implementation: always unavailable. This is the default
    when no adapter is configured -- proves the contract does not require
    any specific external tool to exist, and gives every caller a real,
    testable "no provider wired up" behavior instead of None-checking."""

    def index(self, repo_path: Path, full: bool = False) -> None:
        return None

    def status(self) -> IndexStatus:
        return IndexStatus(available=False, stale=True, detail="No CodeIntelligenceProvider is configured.")

    def find(self, query: str) -> tuple[SymbolLocation, ...]:
        raise CodeIntelligenceUnavailable("No CodeIntelligenceProvider is configured.")

    def callers(self, symbol: str) -> tuple[SymbolLocation, ...]:
        raise CodeIntelligenceUnavailable("No CodeIntelligenceProvider is configured.")

    def callees(self, symbol: str) -> tuple[SymbolLocation, ...]:
        raise CodeIntelligenceUnavailable("No CodeIntelligenceProvider is configured.")

    def impact(self, symbol: str) -> ImpactResult:
        raise CodeIntelligenceUnavailable("No CodeIntelligenceProvider is configured.")

    def explore(self, query: str) -> CompactContext:
        raise CodeIntelligenceUnavailable("No CodeIntelligenceProvider is configured.")
