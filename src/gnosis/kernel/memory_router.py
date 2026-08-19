"""MemoryRouter: retrieves the smallest useful context for a task.

Composes multiple MemoryProvider instances (one per conceptual role --
factual/temporal, governance, procedural) and returns a bounded,
per-role result. Never blindly injects everything: each role gets its
own record-count budget, and total combined content is additionally
capped, mirroring the exact context-budgeting pattern already proven in
kernel.engine._gather_code_intelligence_context (M2.5). Context quality
over quantity: this is a retrieval budget, not a router that tries to
be clever about ranking -- ranking is each provider's job.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .memory import MemoryProvider, MemoryQuery, MemoryResult, MemoryUnavailable


@dataclass(frozen=True)
class MemoryRouterResult:
    query_text: str
    results_by_role: dict[str, MemoryResult]
    failures_by_role: dict[str, str]
    total_records_included: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_text": self.query_text,
            "results_by_role": {role: result.to_dict() for role, result in self.results_by_role.items()},
            "failures_by_role": self.failures_by_role,
            "total_records_included": self.total_records_included,
        }


class MemoryRouter:
    def __init__(self, providers: dict[str, MemoryProvider] | None = None):
        self.providers: dict[str, MemoryProvider] = dict(providers or {})

    def register(self, role: str, provider: MemoryProvider) -> None:
        self.providers[role] = provider

    def gather_context(
        self,
        query_text: str,
        roles: Sequence[str] | None = None,
        max_records_per_role: int = 3,
        max_total_records: int = 8,
        as_of: str | None = None,
    ) -> MemoryRouterResult:
        """Never raises: a provider failure is recorded per-role and does
        not prevent the other roles from contributing. Total records
        across all roles is capped at max_total_records regardless of
        how many roles are configured -- the budgeting knob a future
        task-integration layer can drive with a smarter number, exactly
        like max_context_chars in the code-intelligence path."""
        selected_roles = list(roles) if roles is not None else list(self.providers.keys())
        results: dict[str, MemoryResult] = {}
        failures: dict[str, str] = {}
        total_included = 0

        for role in selected_roles:
            provider = self.providers.get(role)
            if provider is None:
                failures[role] = "no provider registered for this role"
                continue
            remaining = max_total_records - total_included
            if remaining <= 0:
                failures[role] = "skipped: max_total_records budget exhausted"
                continue
            per_role_limit = min(max_records_per_role, remaining)
            try:
                result = provider.query(MemoryQuery(text=query_text, as_of=as_of, limit=per_role_limit))
            except MemoryUnavailable as exc:
                failures[role] = str(exc)
                continue
            results[role] = result
            total_included += len(result.records)

        return MemoryRouterResult(
            query_text=query_text, results_by_role=results, failures_by_role=failures,
            total_records_included=total_included,
        )
