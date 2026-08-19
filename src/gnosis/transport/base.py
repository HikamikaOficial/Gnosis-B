"""Abstract Director transport.

The kernel must never hard-code how a DirectorBrief arrives or an
EngineerReport is delivered. M0 ships a ManualDirectorTransport (files on
disk) and a placeholder McpDirectorTransport whose methods raise
NotImplementedError but satisfy the same interface, swapping the manual
transport for a future ChatGPT MCP transport is a config change, not a
kernel redesign.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..contracts.director_brief import DirectorBrief
from ..contracts.engineer_report import EngineerReport


class DirectorTransport(ABC):
    @abstractmethod
    def receive_brief(self) -> DirectorBrief:
        raise NotImplementedError

    @abstractmethod
    def send_report(self, report: EngineerReport) -> None:
        raise NotImplementedError
