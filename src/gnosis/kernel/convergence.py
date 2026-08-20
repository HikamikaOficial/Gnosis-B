"""Review-convergence loop (Directive 6): signal ∧ evidence, tri-state
rounds, stalemate fingerprints, nothing-lost gate ledger.

The kernel owns the loop; reviewers and fixers are injected callables
(later: Claude/Codex adapters; in tests: deterministic fakes). Rules,
from docs/research/REFERENCE_REPOSITORY_FINDINGS.md §6:

- **An agent's DONE claim never closes a Task.** Convergence requires
  computer-checked evidence: the deterministic verification passed AND
  the independent review verdict is PASS AND no blocking finding stands.
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
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Any

from .canonical import hash_canonical
from .git_evidence import capture_git_evidence
from .verification import VerificationResult


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
    verification: VerificationResult | None


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
    verification: VerificationResult | None
    review: ReviewReport | None
    blocking: tuple[Finding, ...]
    gated: tuple[GatedFinding, ...]
    fix: FixReport | None
    warnings: tuple[str, ...]
    unchanged_streak: int


@dataclass(frozen=True)
class ConvergenceResult:
    outcome: ConvergenceOutcome
    rounds: tuple[RoundRecord, ...]
    gate_ledger: tuple[GatedFinding, ...]
    dissent: tuple[Finding, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "round_count": len(self.rounds),
            "gate_ledger": [g.to_dict() for g in self.gate_ledger],
            "dissent": [f.to_dict() for f in self.dissent],
            "warnings": list(self.warnings),
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
        verify_fn: Callable[[], VerificationResult],
        review_fn: Callable[[int], ReviewReport],
        fix_fn: Callable[[FixRequest], FixReport],
        fingerprint_fn: Callable[[], str | None],
    ):
        self.policy = policy
        self.verify_fn = verify_fn
        self.review_fn = review_fn
        self.fix_fn = fix_fn
        self.fingerprint_fn = fingerprint_fn

    def run(self) -> ConvergenceResult:
        rounds: list[RoundRecord] = []
        ledger: list[GatedFinding] = []
        loop_warnings: list[str] = []
        prev_fingerprint: str | None = None
        have_prev = False
        unchanged = 0
        last_fix: FixReport | None = None
        # Last verification outcome observed per fingerprint, for the
        # flip-detection guard below (Codex review finding 3).
        verified_by_fp: dict[str, bool] = {}

        for index in range(1, self.policy.max_rounds + 1):
            warnings: list[str] = []

            fingerprint = self._collect(self.fingerprint_fn, "fingerprint", warnings)
            verification = self._collect(self.verify_fn, "verification", warnings)
            review = self._collect(partial(self.review_fn, index), "review", warnings)
            if fingerprint is None and not any("fingerprint" in w for w in warnings):
                # The probe's documented soft-failure mode is returning
                # None (git_fingerprint); record it, same as a raise.
                warnings.append(
                    "fingerprint unavailable: round cannot converge or "
                    "count toward stalemate"
                )
            evidence_ok = (
                fingerprint is not None and verification is not None and review is not None
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

            blocking: list[Finding] = []
            gated_this_round: list[GatedFinding] = []
            if review is not None:
                for finding in review.findings:
                    if finding.severity not in self.policy.blocking_severities:
                        gated_this_round.append(GatedFinding(
                            finding, f"severity {finding.severity.value} below blocking set", index,
                        ))
                    elif finding.confidence < self.policy.min_blocking_confidence:
                        gated_this_round.append(GatedFinding(
                            finding,
                            f"confidence {finding.confidence} below floor "
                            f"{self.policy.min_blocking_confidence}",
                            index,
                        ))
                    else:
                        blocking.append(finding)
                ledger.extend(gated_this_round)

            clean = (
                evidence_ok
                and verification is not None and verification.passed
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
                and verified_by_fp.get(fingerprint) is False
            ):
                clean = False
                warnings.append(
                    "verification outcome flipped from fail to pass on an "
                    "unchanged repo fingerprint: requiring reproduction in "
                    "an independent round before convergence"
                )
            if fingerprint is not None and verification is not None:
                verified_by_fp[fingerprint] = verification.passed

            fix: FixReport | None = None
            if not clean and evidence_ok:
                needs_fix = bool(blocking) or (
                    verification is not None and not verification.passed
                )
                if needs_fix:
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
            ))

            if clean:
                dissent = tuple(
                    f for f in (review.findings if review else ())
                    if f not in blocking
                )
                return self._result(
                    ConvergenceOutcome.CONVERGED, rounds, ledger, dissent, loop_warnings,
                )
            if fix is not None and fix.cannot_fix:
                return self._result(
                    ConvergenceOutcome.CANNOT_FIX, rounds, ledger, (), loop_warnings,
                )
            if unchanged >= self.policy.max_unchanged_rounds:
                return self._result(
                    ConvergenceOutcome.STALEMATE, rounds, ledger, (), loop_warnings,
                )

        return self._result(
            ConvergenceOutcome.ROUNDS_EXHAUSTED, rounds, ledger, (), loop_warnings,
        )

    @staticmethod
    def _collect(fn: Callable[[], Any], label: str, warnings: list[str]) -> Any:
        """Evidence collection: a failing probe yields None + a warning,
        never a fake value and never an aborted loop."""
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - probe failure is data, not control flow
            warnings.append(f"{label} collection failed: {exc}")
            return None

    @staticmethod
    def _result(
        outcome: ConvergenceOutcome,
        rounds: list[RoundRecord],
        ledger: list[GatedFinding],
        dissent: tuple[Finding, ...],
        warnings: list[str],
    ) -> ConvergenceResult:
        # Nothing-lost rule: the gate ledger rides on EVERY exit path.
        return ConvergenceResult(
            outcome=outcome, rounds=tuple(rounds), gate_ledger=tuple(ledger),
            dissent=dissent, warnings=tuple(warnings),
        )
