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

A THIRD independent review then showed that one function is not enough
while the only way to REPORT a verdict is a two-state field.
`CompositeVerifier` ran a child whose `passed` was `1`, read it with
`all(r.passed for r in results)`, and returned a brand-new
`VerificationResult(passed=True)`. Every strict reader downstream was
then perfectly correct and perfectly wrong: the composite really is a
well-formed passing result, and the malformed evidence it was computed
from had been laundered out of existence. The same review found
`CompositeVerifier("empty", [])` passing on `all([]) is True` — a DONE
minted by running no check at all.

`passed: bool` has two states and the verdict has three, so a composite
that must say "a member returned invalid evidence" had nowhere to say
it. `MalformedEvidence` is that third state made representable:
evidence that records NO verdict, kept as its own type so that
`verification_verdict` classifies it MALFORMED by construction and no
arithmetic over `passed` can collapse it into a pass. `Verifier.run`
therefore returns `Evidence`, not `VerificationResult`, which is what
makes every production reader confront the case instead of inheriting a
guarantee nobody checked.
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

from .check_execution import CheckExecutionUnavailable, CheckExecutor
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


@dataclass(frozen=True)
class MalformedEvidence:
    """Evidence that records NO verdict, kept as a thing in its own right.

    A `VerificationResult` cannot express this. Its `passed` is a
    two-state field and MALFORMED is the third state, so a verifier that
    aggregates others — `CompositeVerifier` — had exactly two ways to
    report "a member returned something I could not read": call it a pass
    or call it a failure. It called it a pass (third F-34 review), and
    because the object it built was itself well-formed, every strict
    reader downstream believed it.

    This is not a `VerificationResult` subclass, deliberately.
    `verification_verdict` classifies anything that is not a
    `VerificationResult` as MALFORMED, so an instance of this type is
    unable to be read as a pass by the one function that decides — the
    property holds by construction rather than by anyone remembering to
    check. Inheriting would have made `isinstance` say yes and put the
    guarantee back in the hands of every call site.

    `children` keeps the raw member payloads. Rejecting evidence is not
    the same as destroying it: a serialized child may still carry its
    original `passed` of `1`, because that is what forensics is for. What
    no summary may do is read that field to decide anything, which is why
    each child arrives with the `verdict` already computed beside it.
    """

    name: str
    reason: str
    children: tuple[dict[str, Any], ...] = ()
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            # Named `verdict`, never `passed`. A reader scanning a payload
            # for `passed` must not find a key here at all, rather than
            # find one whose value they then have to interpret correctly.
            "verdict": VerificationVerdict.MALFORMED.value,
            "reason": self.reason,
            "children": [dict(child) for child in self.children],
            "ts": self.ts,
        }


#: What a `Verifier` may answer: a readable result, or a record that it
#: could not produce one. Widening the ABC's return type to this union is
#: what makes mypy name every reader that assumed the narrow case — the
#: composite's laundering was invisible precisely because the type said
#: it could not happen.
Evidence = VerificationResult | MalformedEvidence


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

    - not a `VerificationResult` (including `None`, and including a
      `MalformedEvidence`) -> MALFORMED. Absence of evidence is not
      success, and neither is a stand-in the kernel cannot read.
      `MalformedEvidence` needs no branch of its own here on purpose:
      it is classified by the same rule as every other non-result, so
      the property cannot be lost by editing a branch that names it.
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


def evidence_reason(result: object) -> str:
    """Why this evidence states no verdict, in words an operator can act on.

    `MALFORMED_EVIDENCE_EXPLANATION` describes ONE cause — a `passed`
    that is neither `True` nor `False`. A composite whose member returned
    invalid evidence, or a verifier that returned nothing at all, has a
    different cause, and printing the generic sentence for all of them
    sends the reader to inspect a field that is not the problem. The
    verdict is shared; the reason is not.
    """
    if isinstance(result, MalformedEvidence):
        return result.reason
    return MALFORMED_EVIDENCE_EXPLANATION


def evidence_name(result: object, fallback: str = "unknown") -> str:
    """The name to file this evidence under, without trusting its type."""
    name = getattr(result, "name", None)
    return name if isinstance(name, str) and name else fallback


def evidence_payload(result: object) -> dict[str, Any]:
    """A serializable record of evidence, with its verdict ALREADY read.

    Constitution rule 2 is about what may be claimed, and a payload is
    read by things that claim. The raw object is preserved verbatim —
    including a `passed` of `1`, which is the whole point of keeping it —
    but `verdict` travels beside it so that nothing downstream has to
    re-derive the classification from the raw field. Re-derivation is the
    defect this module keeps repairing.
    """
    verdict = verification_verdict(result)
    if isinstance(result, VerificationResult | MalformedEvidence):
        return {"verdict": verdict.value, "raw": result.to_dict()}
    # A duck-typed verifier can return literally anything; a repr is all
    # that can honestly be said about it, and it is bounded because an
    # object's repr is not a trusted length.
    return {
        "verdict": verdict.value,
        "raw": {"type": type(result).__name__, "repr": repr(result)[:500]},
    }


class Verifier(ABC):
    name: str

    @abstractmethod
    def run(self, cwd: Path) -> Evidence:
        raise NotImplementedError


class CommandVerifier(Verifier):
    """Runs a shell command and treats a zero exit code as passing."""

    def __init__(self, name: str, command: Sequence[str] | str, timeout_s: float = 300.0,
                 excerpt_chars: int = 2000, *, executor: CheckExecutor | None = None):
        self.name = name
        self.command = command
        self.timeout_s = timeout_s
        self.excerpt_chars = excerpt_chars
        self.executor = executor

    def run(self, cwd: Path) -> Evidence:
        argv = shlex.split(self.command) if isinstance(self.command, str) else list(self.command)
        started = time.monotonic()
        try:
            if self.executor is None:
                proc = subprocess.run(
                    argv, cwd=str(cwd), capture_output=True, text=True, timeout=self.timeout_s,
                    check=False,
                )
            else:
                proc = self.executor.execute(argv, cwd=cwd, timeout_s=self.timeout_s)
            duration = time.monotonic() - started
            return VerificationResult(
                name=self.name, passed=proc.returncode == 0, exit_code=proc.returncode,
                duration_s=duration,
                stdout_excerpt=redact(proc.stdout)[-self.excerpt_chars:],
                stderr_excerpt=redact(proc.stderr)[-self.excerpt_chars:],
            )
        except CheckExecutionUnavailable as exc:
            return MalformedEvidence(self.name, f"verification infrastructure unavailable: {exc}")
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            captured = (exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes)
                        else exc.stdout if isinstance(exc.stdout, str) else "")
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


class EmptyCompositeError(ValueError):
    """A `CompositeVerifier` was constructed with nothing to run.

    Its own exception type because "you passed an empty collection" and
    "your verifier is misconfigured in some other way" are different
    repairs, and because a caller assembling an optional set of checks
    should have to catch this deliberately rather than discover it as a
    green run that proved nothing.
    """


class CompositeVerifier(Verifier):
    """Runs several verifiers; passes only when EVERY member said PASSED.

    Three things this refuses to do, each of which minted an unevidenced
    DONE in the third independent F-34 review:

    **It refuses to exist with nothing to run.** `all([])` is `True`, so
    an empty composite reported a pass having executed no check at all —
    the purest possible violation of rule 2. The collection is validated
    in `__init__`, before anything can run, because a composite that can
    never produce a meaningful answer is a construction error and not a
    verification outcome. The members are then held as a tuple: a list an
    owner could empty after construction would put the same hole back.

    **It refuses to read `passed` for truthiness.** Every member is
    classified by `verification_verdict` and by nothing else, so a
    `passed` of `1` is MALFORMED here exactly as it is everywhere else.

    **It refuses to convert a malformed member into a verdict.** Not into
    a pass, which is what `all(...)` did, and not into an ordinary
    failure either: a failing member is evidence that the WORK is wrong,
    while a malformed one is evidence that the VERIFIER is wrong, and an
    operator sent to debug the first when it is the second will not find
    anything. The composite answers `MalformedEvidence`, which
    `verification_verdict` reads as MALFORMED by construction.
    """

    def __init__(self, name: str, verifiers: Sequence[Verifier]):
        members = tuple(verifiers)
        if not members:
            raise EmptyCompositeError(
                f"CompositeVerifier {name!r} was given no verifiers to run. "
                "An empty composite reports on nothing: `all([])` is True, "
                "so it would answer PASSED having executed no check at all "
                "(constitution rule 2: no DONE without evidence)."
            )
        self.name = name
        # A tuple, not a list. `composite.verifiers.clear()` on a live
        # object would restore the empty case the constructor exists to
        # refuse, and the refusal would then hold only until somebody held
        # the object.
        self.verifiers: tuple[Verifier, ...] = members

    def run(self, cwd: Path) -> Evidence:
        # Typed `object` for the reason the engine does the same: a member
        # may be duck-typed past the ABC and return anything at all, and a
        # narrower annotation would let mypy delete the checks below as
        # unreachable (L-0039).
        graded: list[tuple[object, VerificationVerdict]] = [
            (produced, verification_verdict(produced))
            for produced in (member.run(cwd) for member in self.verifiers)
        ]

        invalid = [child for child, verdict in graded
                   if verdict is VerificationVerdict.MALFORMED]
        if invalid or not graded:
            # `not graded` is unreachable through `__init__` and is kept
            # anyway: it states the invariant where it is relied upon, so
            # deleting the constructor's guard cannot silently restore
            # `all([]) is True` here.
            return self._no_verdict(graded, invalid)

        # Every member is PASSED or FAILED, so every member IS a
        # `VerificationResult` — but that is derived, and the narrowing is
        # therefore done explicitly rather than assumed.
        results = [child for child, _ in graded if isinstance(child, VerificationResult)]
        failed = [child for child, verdict in graded
                  if verdict is VerificationVerdict.FAILED
                  and isinstance(child, VerificationResult)]
        all_passed = not failed
        return VerificationResult(
            name=self.name,
            # A `bool` literal, never the value of an `all(...)` over a
            # field whose annotation nothing enforces.
            passed=all_passed,
            exit_code=0 if all_passed else 1,
            duration_s=sum(r.duration_s for r in results),
            stdout_excerpt="\n".join(f"[{r.name}] {r.stdout_excerpt}" for r in results),
            stderr_excerpt="\n".join(f"[{r.name}] {r.stderr_excerpt}" for r in failed),
        )

    def _no_verdict(self, graded: Sequence[tuple[object, VerificationVerdict]],
                    invalid: Sequence[object]) -> MalformedEvidence:
        """The composite records no verdict, and says which member broke it."""
        names = ", ".join(evidence_name(child) for child in invalid) or "none"
        reason = (
            f"composite verifier {self.name!r} records no verdict: "
            f"{len(invalid)} of {len(graded)} member verifier(s) returned "
            f"invalid evidence ({names}). A member that states no verdict "
            "cannot be aggregated into one: reading it as a pass is how "
            "F-34 recurred, and reading it as a failure would blame the "
            "work for a broken verifier. The evidence is invalid, so the "
            "task is not COMPLETED (constitution rule 2)."
        )
        return MalformedEvidence(
            name=self.name, reason=reason,
            children=tuple(evidence_payload(child) for child, _ in graded),
        )
