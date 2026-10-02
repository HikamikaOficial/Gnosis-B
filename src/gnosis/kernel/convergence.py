"""Review-convergence loop (Directive 6): signal ∧ evidence, tri-state
rounds, stalemate fingerprints, nothing-lost gate ledger.

The kernel owns the loop; reviewers and fixers are injected callables
(later: Claude/Codex adapters; in tests: deterministic fakes). Rules,
from docs/research/REFERENCE_REPOSITORY_FINDINGS.md §6:

- **An agent's DONE claim never closes a Task.** Convergence requires
  computer-checked evidence: the deterministic verification returned
  `VerificationVerdict.PASSED` AND the independent review verdict is
  PASS AND no blocking finding stands. "The verification passed" is read
  through `verification_verdict`, never off `result.passed`: a third
  independent F-34 review found this loop reading that field for
  truthiness, so a `passed` of `1` — evidence the state authority
  refuses — converged the loop and produced a COMPLETED brief.
  A fixer's ``claims_done`` with an unchanged repo fingerprint is
  downgraded to continue-with-warning (ralphex: DONE means "zero issues
  this round", not "I finished fixing").
- **Rounds are tri-state**: clean round → CONVERGED; fixed-something →
  another independent verification round; can't-fix → typed CANNOT_FIX.
- **Stalemate is a kernel circuit breaker** over repo-state fingerprints
  (git HEAD + status + diff, hashed with kernel.canonical): N
  consecutive unchanged fingerprints → STALEMATE. The counter resets on
  change and NEVER counts a round whose evidence collection failed
  (fingerprint unavailable) — a broken probe must not masquerade as a
  stuck repo.
- **Nothing is lost.** Every finding held back by a gate (severity below
  the blocking set, confidence below the floor) is carried in the
  GateLedger and surfaced in the result at every loop exit; non-blocking
  findings present at convergence are preserved as dissent (orca's
  GateLedger, agent-arena's dissent preservation).
- **Every loop is bounded** (constitution rule 8): ``max_rounds`` is
  required and finite; exhaustion is its own typed outcome.

Exceptions from ``fix_fn`` propagate raw: a crashing fixer is an agent
failure for the caller's taxonomy to classify, never something this loop
absorbs into a fake verdict. ``verify_fn``/``review_fn``/``fingerprint_fn``
failures are treated as evidence-collection failures: the round cannot
converge, cannot count toward stalemate, and is recorded with a warning.
A verification that returns MALFORMED evidence is the same kind of
event and is handled the same way: a verifier that stated no verdict
collected nothing, so the round cannot converge and must not count
toward stalemate either — a broken verifier is not a stuck repo.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Any

from ..runner.capture import RecordedAttempt
from .canonical import hash_canonical
from .git_evidence import capture_git_evidence
from .subject import SubjectIdentity
from .verification import (
    Evidence,
    VerificationVerdict,
    evidence_name,
    evidence_payload,
    evidence_reason,
    verification_verdict,
)


class ReviewVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNCERTAIN = "UNCERTAIN"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    INFO = "INFO"


@dataclass(frozen=True)
class Finding:
    severity: Severity
    category: str
    description: str
    reviewer: str
    evidence: str = ""
    file: str | None = None
    symbol: str | None = None
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value, "category": self.category,
            "description": self.description, "reviewer": self.reviewer,
            "evidence": self.evidence, "file": self.file, "symbol": self.symbol,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ReviewReport:
    """One independent reviewer's structured verdict for one round."""

    verdict: ReviewVerdict
    findings: tuple[Finding, ...] = ()
    reviewer: str = "unknown"
    notes: str = ""


@dataclass(frozen=True)
class FixRequest:
    round_index: int
    blocking_findings: tuple[Finding, ...]
    # `Evidence`, so a fixer prompt can tell "your code is failing" from
    # "your verifier returned nothing readable". Those are different jobs
    # and a fixer told the wrong one edits the wrong file.
    verification: Evidence | None


@dataclass(frozen=True)
class FixReport:
    """The fixer's own account of its round. ``claims_done`` is a SIGNAL,
    never evidence — the next round's verification/review decide."""

    claims_done: bool = False
    cannot_fix: bool = False
    notes: str = ""


@dataclass(frozen=True)
class GatedFinding:
    finding: Finding
    gate_reason: str
    round_index: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding": self.finding.to_dict(),
            "gate_reason": self.gate_reason,
            "round_index": self.round_index,
        }


class ConvergenceOutcome(str, Enum):
    CONVERGED = "CONVERGED"
    STALEMATE = "STALEMATE"
    CANNOT_FIX = "CANNOT_FIX"
    ROUNDS_EXHAUSTED = "ROUNDS_EXHAUSTED"


@dataclass(frozen=True)
class RoundRecord:
    index: int
    fingerprint: str | None
    evidence_ok: bool
    verification: Evidence | None
    review: ReviewReport | None
    blocking: tuple[Finding, ...]
    gated: tuple[GatedFinding, ...]
    fix: FixReport | None
    warnings: tuple[str, ...]
    unchanged_streak: int
    subject: SubjectIdentity | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "fingerprint": self.fingerprint,
            "evidence_ok": self.evidence_ok,
            "verification": evidence_payload(self.verification),
            "review": ({"verdict": self.review.verdict.value,
                        "reviewer": self.review.reviewer, "notes": self.review.notes,
                        "findings": [f.to_dict() for f in self.review.findings]}
                       if self.review else None),
            "blocking": [f.to_dict() for f in self.blocking],
            "gated": [g.to_dict() for g in self.gated],
            "fix": ({"claims_done": self.fix.claims_done,
                     "cannot_fix": self.fix.cannot_fix, "notes": self.fix.notes}
                    if self.fix else None),
            "warnings": list(self.warnings), "unchanged_streak": self.unchanged_streak,
            "subject": self.subject.to_dict() if self.subject else None,
        }


@dataclass(frozen=True)
class EvidenceFailure:
    """A probe that raised, kept with its TYPE rather than only its text.

    "review collection failed: ..." reads the same whether the agent
    produced unreadable output, edited the code it was judging, or
    crashed — and those demand very different responses. The loop's
    handling is identical (no evidence was collected), but the record is
    not (Codex review)."""

    stage: str          # fingerprint | verification | review
    error_type: str     # the exception class name, e.g. InvalidReviewOutput
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "error_type": self.error_type,
                "message": self.message}


@dataclass(frozen=True)
class ConvergenceResult:
    outcome: ConvergenceOutcome
    rounds: tuple[RoundRecord, ...]
    gate_ledger: tuple[GatedFinding, ...]
    dissent: tuple[Finding, ...]
    warnings: tuple[str, ...]
    evidence_failures: tuple[EvidenceFailure, ...] = ()
    rework_attempts: tuple[RecordedAttempt, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "round_count": len(self.rounds),
            "rounds": [r.to_dict() for r in self.rounds],
            "gate_ledger": [g.to_dict() for g in self.gate_ledger],
            "dissent": [f.to_dict() for f in self.dissent],
            "warnings": list(self.warnings),
            "evidence_failures": [f.to_dict() for f in self.evidence_failures],
            "rework_attempts": [a.to_dict() for a in self.rework_attempts],
        }


@dataclass(frozen=True)
class ConvergencePolicy:
    max_rounds: int
    max_unchanged_rounds: int = 3
    blocking_severities: frozenset[Severity] = frozenset({Severity.CRITICAL, Severity.MAJOR})
    min_blocking_confidence: float = 0.5

    def __post_init__(self) -> None:
        if self.max_rounds < 1:
            raise ValueError("ConvergencePolicy.max_rounds must be >= 1")
        if self.max_unchanged_rounds < 1:
            raise ValueError("ConvergencePolicy.max_unchanged_rounds must be >= 1")
        if not 0.0 <= self.min_blocking_confidence <= 1.0:
            raise ValueError("min_blocking_confidence must be within [0, 1]")


def classify_findings(review: ReviewReport | None, policy: ConvergencePolicy,
                      round_index: int) -> tuple[list[Finding], list[GatedFinding]]:
    """Split a review's findings into blocking and gated, by ONE rule.

    Extracted from the loop so that a re-review performed at integration
    time (ADR-0021) applies exactly the same severity set and confidence
    floor. Two copies of "what blocks" would drift on the first change to
    either, and a finding that blocks convergence but not landing — or
    the reverse — is a contradiction an operator would have to discover
    by experiment.

    Nothing is discarded: everything held back is returned as a
    `GatedFinding` with the reason it was held, which is the nothing-lost
    rule (ADR-0008).
    """
    blocking: list[Finding] = []
    gated: list[GatedFinding] = []
    if review is None:
        return blocking, gated
    for finding in review.findings:
        if finding.severity not in policy.blocking_severities:
            gated.append(GatedFinding(
                finding, f"severity {finding.severity.value} below blocking set",
                round_index,
            ))
        elif finding.confidence < policy.min_blocking_confidence:
            gated.append(GatedFinding(
                finding,
                f"confidence {finding.confidence} below floor "
                f"{policy.min_blocking_confidence}",
                round_index,
            ))
        else:
            blocking.append(finding)
    return blocking, gated


def git_fingerprint(repo_path: Path) -> str | None:
    """Repo-state fingerprint for stalemate detection: HEAD + working-tree
    status + diff stat, hashed with the kernel's canonical contract.
    Returns None when evidence collection fails (not a repo, no HEAD), so
    the caller knows not to count the round."""
    evidence = capture_git_evidence(repo_path)
    if not evidence.is_repo or evidence.head_sha is None:
        return None
    return hash_canonical({
        "head": evidence.head_sha,
        "status": evidence.status_porcelain,
        "diff": evidence.diff_stat,
    })


class ConvergenceLoop:
    """Bounded implement→verify→review→fix convergence engine."""

    def __init__(
        self,
        policy: ConvergencePolicy,
        verify_fn: Callable[[], Evidence],
        review_fn: Callable[[int], ReviewReport],
        fix_fn: Callable[[FixRequest], FixReport],
        fingerprint_fn: Callable[[], str | None],
        subject_fn: Callable[[], SubjectIdentity] | None = None,
        prepare_fn: Callable[[], None] | None = None,
    ):
        self.policy = policy
        self.verify_fn = verify_fn
        self.review_fn = review_fn
        self.fix_fn = fix_fn
        self.fingerprint_fn = fingerprint_fn
        self.subject_fn = subject_fn
        self.prepare_fn = prepare_fn

    def run(self, *, initial: ConvergenceResult | None = None, start_index: int = 1,
            on_round_started: Callable[[int], None] | None = None,
            on_progress: Callable[[ConvergenceResult], None] | None = None) -> ConvergenceResult:
        if type(start_index) is not int or start_index < 1:
            raise ValueError("convergence start index must be a positive integer")
        rounds: list[RoundRecord] = list(initial.rounds) if initial else []
        indexes = [r.index for r in rounds]
        if (any(type(i) is not int or i < 1 or i > self.policy.max_rounds for i in indexes)
                or indexes != sorted(set(indexes)) or any(i >= start_index for i in indexes)):
            raise ValueError("resume cannot overwrite a recorded convergence round")
        if initial is not None and initial.outcome is ConvergenceOutcome.CONVERGED:
            last_round = rounds[-1] if rounds else None
            if (last_round is None or last_round.evidence_ok is not True
                    or last_round.fingerprint is None
                    or verification_verdict(last_round.verification) is not VerificationVerdict.PASSED
                    or last_round.review is None or last_round.review.verdict is not ReviewVerdict.PASS
                    or last_round.blocking):
                raise ValueError("resumed convergence has no valid passing round")
        if initial is not None and initial.outcome in {
            ConvergenceOutcome.CONVERGED, ConvergenceOutcome.CANNOT_FIX, ConvergenceOutcome.STALEMATE,
        }:
            return initial
        ledger: list[GatedFinding] = list(initial.gate_ledger) if initial else []
        loop_warnings: list[str] = list(initial.warnings) if initial else []
        evidence_failures: list[EvidenceFailure] = list(initial.evidence_failures) if initial else []
        prev_fingerprint: str | None = None
        have_prev = False
        unchanged = 0
        last_fix: FixReport | None = None
        # Last verification VERDICT observed per fingerprint, for the
        # flip-detection guard below (Codex review finding 3). A verdict,
        # not a bool: `passed` is the field this loop is not allowed to
        # read, and a `dict[str, bool]` would have re-admitted it.
        verified_by_fp: dict[str, VerificationVerdict] = {}
        for previous in rounds:
            prior_verdict = verification_verdict(previous.verification)
            if previous.fingerprint is not None and prior_verdict in {
                VerificationVerdict.PASSED, VerificationVerdict.FAILED,
            }:
                verified_by_fp[previous.fingerprint] = prior_verdict
        if rounds and rounds[-1].index + 1 == start_index:
            last = rounds[-1]
            last_fix = last.fix
            if last.evidence_ok:
                prev_fingerprint, have_prev = last.fingerprint, True
                unchanged = last.unchanged_streak

        # A review was committed before its fixer, but no fix result was ever
        # committed. Resume that work under the NEXT round's reservation rather
        # than accepting an author's partial output as a completed attempt.
        pending_fix = (rounds[-1] if rounds and rounds[-1].fix is None
                       and rounds[-1].evidence_ok
                       and (rounds[-1].blocking or verification_verdict(rounds[-1].verification)
                            is VerificationVerdict.FAILED) else None)

        for index in range(start_index, self.policy.max_rounds + 1):
            if on_round_started is not None:
                on_round_started(index)
            if pending_fix is not None:
                resumed_fix = self.fix_fn(FixRequest(index, pending_fix.blocking,
                                                    pending_fix.verification))
                rounds[-1] = replace(pending_fix, fix=resumed_fix)
                last_fix = resumed_fix
                pending_fix = None
                resumed_outcome = (ConvergenceOutcome.CANNOT_FIX if resumed_fix.cannot_fix
                                   else ConvergenceOutcome.ROUNDS_EXHAUSTED)
                progress = self._result(resumed_outcome, rounds, ledger, (),
                                        loop_warnings, evidence_failures)
                if on_progress is not None:
                    on_progress(progress)
                if resumed_fix.cannot_fix:
                    return progress
            if self.prepare_fn is not None:
                self.prepare_fn()
            warnings: list[str] = []

            fingerprint = (self._collect(
                self.fingerprint_fn, "fingerprint", warnings, evidence_failures)
                if self.subject_fn is None else None)
            subject = (self._collect(self.subject_fn, "subject", warnings, evidence_failures)
                       if self.subject_fn else None)
            if self.subject_fn:
                # Real bytes key the canonical loop; diff-stat alone can remain
                # identical while a binary or ignored input changes.
                fingerprint = subject.digest() if subject is not None else None
            verification = self._collect(
                self.verify_fn, "verification", warnings, evidence_failures)
            verified_subject = (
                self._collect(self.subject_fn, "subject", warnings, evidence_failures)
                if self.subject_fn else None)
            review = self._collect(
                partial(self.review_fn, index), "review", warnings, evidence_failures)
            reviewed_subject = (
                self._collect(self.subject_fn, "subject", warnings, evidence_failures)
                if self.subject_fn else None)
            subject_ok = (self.subject_fn is None or (
                subject is not None and subject == verified_subject == reviewed_subject))
            if not subject_ok:
                warnings.append("subject unavailable or changed during verification/review")
                evidence_failures.append(EvidenceFailure(
                    stage="subject", error_type="SubjectChanged",
                    message="verification and review did not observe the same subject bytes"))

            # The verdict, read ONCE, by the one function that reads it.
            # Every use below is derived from this value; the loop used to
            # test `verification.passed` for truthiness in three separate
            # places, which is three chances to disagree with the state
            # authority about the same object (third F-34 review).
            verdict = (verification_verdict(verification)
                       if verification is not None else None)
            if fingerprint is None and not any("fingerprint" in w for w in warnings):
                # The probe's documented soft-failure mode is returning
                # None (git_fingerprint); record it, same as a raise.
                warnings.append(
                    "fingerprint unavailable: round cannot converge or "
                    "count toward stalemate"
                )
            if verdict is VerificationVerdict.MALFORMED:
                # Evidence that states no verdict is evidence that was not
                # collected, whatever object carried it. Same handling as a
                # verifier that raised — and now recorded with a type, so a
                # reader can tell an invalid answer from a crash.
                warnings.append(
                    f"verification produced invalid evidence: "
                    f"{evidence_reason(verification)}"
                )
                evidence_failures.append(EvidenceFailure(
                    stage="verification",
                    error_type="MalformedEvidence",
                    message=(f"{evidence_name(verification)}: "
                             f"{evidence_reason(verification)}")[:500],
                ))
            evidence_ok = (
                fingerprint is not None
                and verification is not None
                and verdict is not VerificationVerdict.MALFORMED
                and review is not None
                and subject_ok
            )

            # Signal ∧ evidence: a prior DONE claim with an unchanged repo
            # is downgraded to a warning, never trusted.
            if (
                last_fix is not None and last_fix.claims_done
                and fingerprint is not None and have_prev
                and fingerprint == prev_fingerprint
            ):
                warnings.append(
                    "fixer claimed done but the repo fingerprint did not "
                    "change: signal without evidence, continuing"
                )

            # Stalemate accounting — "N CONSECUTIVE unchanged rounds", and
            # only rounds with COMPLETE evidence count (Codex review
            # findings 1-2): a failed probe of any kind breaks the
            # consecutive run entirely (streak and baseline), so a broken
            # probe can neither masquerade as a stuck repo nor bridge a
            # gap the kernel did not observe.
            if evidence_ok:
                if have_prev and fingerprint == prev_fingerprint:
                    unchanged += 1
                else:
                    unchanged = 0
                prev_fingerprint = fingerprint
                have_prev = True
            else:
                unchanged = 0
                have_prev = False

            blocking, gated_this_round = classify_findings(review, self.policy, index)
            if review is not None:
                ledger.extend(gated_this_round)

            clean = (
                evidence_ok
                and verdict is VerificationVerdict.PASSED
                and review is not None and review.verdict is ReviewVerdict.PASS
                and not blocking
            )

            # Flip-detection guard (Codex review finding 3): a verification
            # that FAILED earlier on this exact repo fingerprint and now
            # PASSES with the repo unchanged is contradictory evidence — a
            # flaky or gameable verifier must not close the task on one
            # lucky pass. Convergence then requires the pass to be
            # REPRODUCED in an independent round on the same fingerprint.
            if (
                clean and fingerprint is not None
                and verified_by_fp.get(fingerprint) is VerificationVerdict.FAILED
            ):
                clean = False
                warnings.append(
                    "verification outcome flipped from fail to pass on an "
                    "unchanged repo fingerprint: requiring reproduction in "
                    "an independent round before convergence"
                )
            if fingerprint is not None and verdict in (
                VerificationVerdict.PASSED, VerificationVerdict.FAILED
            ):
                # Only a real verdict is remembered. Recording MALFORMED
                # here would let "the verifier was broken last round" count
                # as "it failed last round", and the flip guard would then
                # demand a reproduction of a failure nobody observed.
                verified_by_fp[fingerprint] = verdict

            fix: FixReport | None = None
            if not clean and evidence_ok:
                needs_fix = bool(blocking) or verdict is VerificationVerdict.FAILED
                if needs_fix:
                    # Persist the evidence that requested rework before calling
                    # the mutating agent. A crash there cannot erase the review.
                    if on_progress is not None:
                        pending = RoundRecord(
                            index, fingerprint, evidence_ok, verification, review,
                            tuple(blocking), tuple(gated_this_round), None,
                            tuple(warnings), unchanged, subject if subject_ok else None)
                        on_progress(self._result(ConvergenceOutcome.ROUNDS_EXHAUSTED,
                            [*rounds, pending], ledger, (), [*loop_warnings, *warnings],
                            evidence_failures))
                    fix = self.fix_fn(FixRequest(
                        round_index=index,
                        blocking_findings=tuple(blocking),
                        verification=verification,
                    ))
                    last_fix = fix
                else:
                    # e.g. an UNCERTAIN verdict with nothing concrete to
                    # fix: another independent round decides; a reviewer
                    # who stays uncertain over an unchanging repo runs
                    # into the stalemate breaker, not an infinite loop.
                    warnings.append(
                        "round not clean but no fixable target (verdict "
                        f"{review.verdict.value if review else 'n/a'}): "
                        "scheduling another independent round"
                    )

            loop_warnings.extend(warnings)
            rounds.append(RoundRecord(
                index=index, fingerprint=fingerprint, evidence_ok=evidence_ok,
                verification=verification, review=review,
                blocking=tuple(blocking), gated=tuple(gated_this_round),
                fix=fix, warnings=tuple(warnings), unchanged_streak=unchanged,
                subject=subject if subject_ok else None,
            ))

            finished: ConvergenceResult | None = None
            if clean:
                dissent = tuple(
                    f for f in (review.findings if review else ())
                    if f not in blocking
                )
                finished = self._result(
                    ConvergenceOutcome.CONVERGED, rounds, ledger, dissent, loop_warnings, evidence_failures,
                )
            elif fix is not None and fix.cannot_fix:
                finished = self._result(
                    ConvergenceOutcome.CANNOT_FIX, rounds, ledger, (), loop_warnings, evidence_failures,
                )
            elif unchanged >= self.policy.max_unchanged_rounds:
                finished = self._result(
                    ConvergenceOutcome.STALEMATE, rounds, ledger, (), loop_warnings, evidence_failures,
                )
            if on_progress is not None:
                on_progress(finished or self._result(ConvergenceOutcome.ROUNDS_EXHAUSTED,
                    rounds, ledger, (), loop_warnings, evidence_failures))
            if finished is not None:
                return finished

        return self._result(
            ConvergenceOutcome.ROUNDS_EXHAUSTED, rounds, ledger, (), loop_warnings, evidence_failures,
        )

    @staticmethod
    def _collect(fn: Callable[[], Any], label: str, warnings: list[str],
                 failures: list[EvidenceFailure] | None = None) -> Any:
        """Evidence collection: a failing probe yields None + a warning,
        never a fake value and never an aborted loop.

        The *type* is kept alongside the message. A prose warning collapsed
        an unreadable agent answer, a reviewer that edited the code, a
        broken git probe and a crashed verifier into one indistinguishable
        outcome — and the constitution requires INVALID_AGENT_OUTPUT to
        stay distinct from disagreement (Codex review). The loop still
        treats them identically, which is correct: no evidence was
        collected either way. The caller can now tell them apart.
        """
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - probe failure is data, not control flow
            warnings.append(f"{label} collection failed: {exc}")
            if failures is not None:
                failures.append(EvidenceFailure(
                    stage=label, error_type=type(exc).__name__, message=str(exc)[:500],
                ))
            return None

    @staticmethod
    def _result(
        outcome: ConvergenceOutcome,
        rounds: list[RoundRecord],
        ledger: list[GatedFinding],
        dissent: tuple[Finding, ...],
        warnings: list[str],
        evidence_failures: list[EvidenceFailure] | None = None,
    ) -> ConvergenceResult:
        # Nothing-lost rule: the gate ledger rides on EVERY exit path, and
        # so does the typed record of what could not be collected.
        return ConvergenceResult(
            outcome=outcome, rounds=tuple(rounds), gate_ledger=tuple(ledger),
            dissent=dissent, warnings=tuple(warnings),
            evidence_failures=tuple(evidence_failures or ()),
        )
