"""Execution boundary shared by task verification and proof recapture.

An executor must either return the observed process result or raise. Callers
must never retry a refused isolated launch under their own identity.
"""
from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol


class CheckExecutionUnavailable(RuntimeError):
    """Verification infrastructure failed, so no code verdict is available."""


class CheckExecutor(Protocol):
    def execute(self, argv: Sequence[str], *, cwd: Path,
                timeout_s: float | None,
                env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        """Run one check, preserving its deadline and separate output streams."""
        ...
