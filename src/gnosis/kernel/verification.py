"""Deterministic verification interface.

Per the project constitution: no LLM may mark work verified merely by
claiming it is correct. A Verifier wraps something checkable, a test
suite, a build, a lint pass, and returns a VerificationResult with a
computer-checked pass/fail, never a self-report.
"""
from __future__ import annotations

import shlex
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence, Union

from .redaction import redact


@dataclass(frozen=True)
class VerificationResult:
    name: str
    passed: bool
    exit_code: "int | None"
    duration_s: float
    stdout_excerpt: str
    stderr_excerpt: str
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "name": self.name, "passed": self.passed, "exit_code": self.exit_code,
            "duration_s": self.duration_s, "stdout_excerpt": self.stdout_excerpt,
            "stderr_excerpt": self.stderr_excerpt, "ts": self.ts,
        }


class Verifier(ABC):
    name: str

    @abstractmethod
    def run(self, cwd: Path) -> VerificationResult:
        raise NotImplementedError


class CommandVerifier(Verifier):
    """Runs a shell command and treats a zero exit code as passing."""

    def __init__(self, name: str, command: Union[Sequence[str], str], timeout_s: float = 300.0,
                 excerpt_chars: int = 2000):
        self.name = name
        self.command = command
        self.timeout_s = timeout_s
        self.excerpt_chars = excerpt_chars

    def run(self, cwd: Path) -> VerificationResult:
        argv = shlex.split(self.command) if isinstance(self.command, str) else list(self.command)
        started = time.monotonic()
        try:
            proc = subprocess.run(
                argv, cwd=str(cwd), capture_output=True, text=True, timeout=self.timeout_s,
            )
            duration = time.monotonic() - started
            return VerificationResult(
                name=self.name, passed=proc.returncode == 0, exit_code=proc.returncode,
                duration_s=duration,
                stdout_excerpt=redact(proc.stdout)[-self.excerpt_chars:],
                stderr_excerpt=redact(proc.stderr)[-self.excerpt_chars:],
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            captured = exc.stdout if isinstance(exc.stdout, str) else ""
            return VerificationResult(
                name=self.name, passed=False, exit_code=None, duration_s=duration,
                stdout_excerpt=redact(captured)[-self.excerpt_chars:],
                stderr_excerpt=f"TIMEOUT after {self.timeout_s}s",
            )
        except FileNotFoundError as exc:
            duration = time.monotonic() - started
            return VerificationResult(
                name=self.name, passed=False, exit_code=None, duration_s=duration,
                stdout_excerpt="", stderr_excerpt=f"command not found: {exc}",
            )


class CompositeVerifier(Verifier):
    """Runs several verifiers and passes only if all of them pass."""

    def __init__(self, name: str, verifiers: Sequence[Verifier]):
        self.name = name
        self.verifiers = list(verifiers)

    def run(self, cwd: Path) -> VerificationResult:
        results = [v.run(cwd) for v in self.verifiers]
        all_passed = all(r.passed for r in results)
        return VerificationResult(
            name=self.name,
            passed=all_passed,
            exit_code=0 if all_passed else 1,
            duration_s=sum(r.duration_s for r in results),
            stdout_excerpt="\n".join(f"[{r.name}] {r.stdout_excerpt}" for r in results),
            stderr_excerpt="\n".join(f"[{r.name}] {r.stderr_excerpt}" for r in results if not r.passed),
        )
