"""Gnosis's own Code Intelligence contract (M2).

Gnosis owns this interface; external tools satisfy it via adapters. No
kernel code should import a specific vendor's client directly -- every
call goes through CodeIntelligenceProvider, which is what keeps the
underlying tool replaceable (per the M2 Director architectural rule: "do
not integrate a candidate merely because it wins one metric... the final
Code Intelligence Plane must be replaceable").

Code intelligence is an optional accelerant, never a hard dependency of
task execution: a provider that cannot answer raises
CodeIntelligenceUnavailable rather than the kernel silently proceeding
with wrong data, but callers are expected to treat that as "fall back to
reading files," not as a fatal error.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


@dataclass(frozen=True)
class SymbolLocation:
    qualified_name: str
    file: str
    line: Optional[int] = None

    def to_dict(self) -> dict:
        return {"qualified_name": self.qualified_name, "file": self.file, "line": self.line}


@dataclass(frozen=True)
class ImpactResult:
    changed_symbol: str
    impacted_symbols: Tuple[SymbolLocation, ...]

    def to_dict(self) -> dict:
        return {
            "changed_symbol": self.changed_symbol,
            "impacted_symbols": [s.to_dict() for s in self.impacted_symbols],
        }


class CodeIntelligenceUnavailable(RuntimeError):
    """Raised when a provider cannot answer (index missing, tool not
    installed, query failed). Callers must treat code intelligence as
    optional, never load-bearing for task correctness."""


class CodeIntelligenceProvider(ABC):
    """The contract. Implementation-specific adapters (one per external
    tool) live alongside this file; Gnosis kernel/task code depends only
    on this interface."""

    @abstractmethod
    def index(self, repo_path: Path) -> None:
        """(Re)build the index for repo_path. Full vs incremental is an
        implementation decision."""
        raise NotImplementedError

    @abstractmethod
    def callers(self, symbol: str) -> Tuple[SymbolLocation, ...]:
        """Functions/methods that call `symbol`."""
        raise NotImplementedError

    @abstractmethod
    def callees(self, symbol: str) -> Tuple[SymbolLocation, ...]:
        """Functions/methods that `symbol` calls."""
        raise NotImplementedError

    @abstractmethod
    def impact(self, symbol: str) -> ImpactResult:
        """Blast-radius analysis for a prospective change to `symbol`."""
        raise NotImplementedError


class NullCodeIntelligenceProvider(CodeIntelligenceProvider):
    """Reference implementation: always unavailable. This is the default
    when no adapter is configured -- proves the contract does not require
    any specific external tool to exist, and gives every caller a real,
    testable "no provider wired up" behavior instead of None-checking."""

    def index(self, repo_path: Path) -> None:
        return None

    def callers(self, symbol: str) -> Tuple[SymbolLocation, ...]:
        raise CodeIntelligenceUnavailable("No CodeIntelligenceProvider is configured.")

    def callees(self, symbol: str) -> Tuple[SymbolLocation, ...]:
        raise CodeIntelligenceUnavailable("No CodeIntelligenceProvider is configured.")

    def impact(self, symbol: str) -> ImpactResult:
        raise CodeIntelligenceUnavailable("No CodeIntelligenceProvider is configured.")
