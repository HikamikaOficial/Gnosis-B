"""Placeholder contract for a future ChatGPT MCP Director transport.

Not implemented in M0 (per DIRECTOR BRIEF non-negotiables: no premature
integration). Exists so the transport interface is proven pluggable and so
M1 can implement this class without touching kernel code."""
from __future__ import annotations

from ..contracts.director_brief import DirectorBrief
from ..contracts.engineer_report import EngineerReport
from .base import DirectorTransport

_NOT_IMPLEMENTED_MSG = (
    "ChatGPT MCP transport is a placeholder in M0. Implement this method "
    "when the MCP integration is architected (Director escalation item)."
)


class McpDirectorTransport(DirectorTransport):
    def __init__(self, endpoint: str, **config):
        self.endpoint = endpoint
        self.config = config

    def receive_brief(self) -> DirectorBrief:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def send_report(self, report: EngineerReport) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
