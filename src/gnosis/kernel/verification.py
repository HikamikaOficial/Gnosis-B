"""Deterministic verification interface.

Per the project constitution: no LLM may mark work verified merely by
claiming it is correct. A Verifier wraps something checkable, a test
suite, a build, a lint pass, and returns a VerificationResult with a
computer-checked pass/fail, never a self-report.

Reading `passed` is not `if result.passed`. `bool` IS an `int` in
Python, so a `passed` of `1` — or of any other truthy value — sails
through a truthiness test and is rendered as a pass by everything
downstream. A second independent review of F-34 reproduced exactly
that: a `VerificationResult(passed=1)` was correctly REFUSED a DONE by
the state authority and then described as a pass in the report of the
very task it had failed to complete. Refusing evidence in one place and
believing it in another is worse than either alone, because the report
is what a human reads.

`verification_verdict()` is therefore the single place that interprets
`passed`, and it admits three answers, not two: PASSED, FAILED, and
MALFORMED for anything that is neither `True` nor `False`. Every
consumer — the completion predicate, the ledger, the report — derives
its answer from that one function, so they cannot disagree.
"""
from __future__ import annotations

import shlex
import subprocess
import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .redaction import redact


@dataclass(frozen=True)
class VerificationResult:
    name: str
    passed: bool
    exit_code: int | None
    duration_s: float
    stdout_excerpt: str
    stderr_excerpt: str
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "passed": self.passed, "exit_code": self.exit_code,
            "duration_s": self.duration_s, "stdout_excerpt": self.stdout_excerpt,
            "stderr_excerpt": self.stderr_excerpt, "ts": self.ts,
        }


class VerificationVerdict(str, Enum):
    """What a verification attempt actually says, read strictly.

    Three values, because there are three cases and the third is the one
    that bit us. `MALFORMED` is not a synonym for `FAILED`: a failing
    verifier produced real evidence that the work is wrong, while a
    malformed one produced an object that states nothing at all. An
    operator must be able to tell "your code is broken" from "your
    verifier is broken", and a report that collapses them sends them
    to debug the wrong thing.
    """

    PASSED = "PASSED"
    FAILED = "FAILED"
    MALFORMED = "MALFORMED"


#: What an operator is told when a verifier answered with a
#: `VerificationResult` whose `passed` states no verdict. Deliberately
#: free of the word this module refuses to print for such a result, so a
#: test can assert that token never appears anywhere in the report.
MALFORMED_EVIDENCE_EXPLANATION = (
    "The verifier returned a VerificationResult whose `passed` is neither "
    "True nor False, so it records no verdict at all. The evidence is "
    "invalid and was rejected rather than read as a pass: `bool` is an "
    "`int` in Python, so a truthy value such as 1 satisfies any check that "
    "merely tests it for truth. The task is not COMPLETED (constitution "
    "rule 2: no DONE without evidence)."
)


def verification_verdict(result: object) -> VerificationVerdict:
    """Read `result` as exactly one of three verdicts, by identity.

    Typed `object`, not `VerificationResult | None`, for the reason
    L-0039 records: a duck-typed verifier satisfies no ABC, mypy cannot
    see it, and narrowing the annotation here would let the type checker
    delete the very branch that catches it.

    - not a `VerificationResult` (including `None`) -> MALFORMED. Absence
      of evidence is not success, and neither is a stand-in the kernel
      cannot read.
    - `passed is True` -> PASSED. The exact object, never a truthy one.
    - `passed is False` -> FAILED. Also the exact object: a falsy value
      that is not `False` says no more than a truthy one that is not
      `True`, so `0`, `""` and `None` are malformed too, not failures.
    - anything else -> MALFORMED.
    """
    if not isinstance(result, VerificationResult):
        return VerificationVerdict.MALFORMED
    # Widened to `object` deliberately. `passed` is ANNOTATED `bool`, so
    # read through the attribute mypy proves `is True`/`is False`
    # exhaustive and deletes the branch below as unreachable — the exact
    # assumption L-0039 records and the second F-34 review disproved with
    # a live `passed=1`. Annotations are not enforcement; a dataclass
    # takes whatever it is handed.
    passed: object = result.passed
    if passed is True:
        return VerificationVerdict.PASSED
    if passed is False:
        return VerificationVerdict.FAILED
    return VerificationVerdict.MALFORMED


class Verifier(ABC):
    name: str

    @abstractmethod
    def run(self, cwd: Path) -> VerificationResult:
        raise NotImplementedError


class CommandVerifier(Verifier):
    """Runs a shell command and treats a zero exit code as passing."""

    def __init__(self, name: str, command: Sequence[str] | str, timeout_s: float = 300.0,
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
