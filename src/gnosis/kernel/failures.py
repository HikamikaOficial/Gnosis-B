"""Typed failure taxonomy, rate-limit park states, recovery-as-reconcile
(Directive 9).

From docs/research/REFERENCE_REPOSITORY_FINDINGS.md §9, and the direct
implementation of constitution rules 5–7 (`RATE_LIMITED != FAIL_CODE`;
`FAIL_INFRA` does not penalize the agent; every retry is classified
before it is repeated).

**Classification is graded.** Classifiers are consulted in descending
evidence grade and the first match wins. Every classification records the
`EvidenceGrade` that carried it, so a decision made by regex over a human
sentence is never mistaken for one made by a documented field.

The exact ordering, stated honestly because three docstrings once claimed
a stronger rule than the code holds (adversarial review): informative
structured evidence (runner flags, documented provider fields) always
wins; PROSE outranks exactly one thing — a BARE non-zero exit code
(`LAST_RESORT`), which says only "something failed" and never which
failure. That demotion is deliberate: a real CLI rate limit also exits
non-zero, so ranking the bare exit above prose would make rate-limit
detection dead code and violate rule 6. Prose cannot overturn structured
evidence that positively describes a different failure — a higher-grade
classifier returning None means "I looked, and it is not this".

When nothing classifies, the answer is `UNCLASSIFIED` — refusing to
guess is a supported outcome, because a wrong retry decision costs more
than an honest "I do not know".

**Reason codes flow unchanged.** The same `reason_code` travels from the
adapter's classification into the append-only event and into the
scheduler's decision, so an operator reading a ledger sees the string the
scheduler actually acted on rather than a re-derived paraphrase.

**RATE_LIMITED is a park state, not a failure.** It carries a durable
reset timestamp and never penalizes agent quality. Holds are
credential-scoped: an ACCOUNT hold means "the window is known shut —
block everything on this credential", while a PROBE hold means "one
resume is testing the water — block new work but let the probe through".
Conflating them either wastes the whole window or stampedes it.

**Recovery is reconcile, not restore.** Durable state lives on the
record; volatile timers are rebuilt idempotently on every scheduler pump
(`HoldRegistry.reconcile`), so a restart loses no correctness and a
double pump changes nothing. The boot sweep re-adopts every stranded run
through the normal path or fails it loudly — a ghost record that is
neither running nor finished is never left behind.
"""
from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FailureClass(str, Enum):
    """The constitution's taxonomy (CLAUDE.md §Failure taxonomy)."""

    PASS = "PASS"
    FAIL_CODE = "FAIL_CODE"
    FAIL_TEST = "FAIL_TEST"
    FAIL_REVIEW = "FAIL_REVIEW"
    FAIL_SECURITY = "FAIL_SECURITY"
    FAIL_ARCHITECTURE = "FAIL_ARCHITECTURE"
    FAIL_PERFORMANCE = "FAIL_PERFORMANCE"
    FAIL_POLICY = "FAIL_POLICY"
    FAIL_INFRA = "FAIL_INFRA"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    AGENT_CRASH = "AGENT_CRASH"
    INVALID_AGENT_OUTPUT = "INVALID_AGENT_OUTPUT"
    STALEMATE = "STALEMATE"
    STALE_LEASE = "STALE_LEASE"
    MERGE_CONFLICT = "MERGE_CONFLICT"
    CONTEXT_ERROR = "CONTEXT_ERROR"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    # Not in the constitution's list: the honest answer when no classifier
    # had structured OR prose evidence. Guessing here is what rule 5 bans.
    UNCLASSIFIED = "UNCLASSIFIED"


class EvidenceGrade(str, Enum):
    STRUCTURED = "STRUCTURED"            # exit code / documented frame field
    SEMI_STRUCTURED = "SEMI_STRUCTURED"  # documented JSON payload field
    PROSE = "PROSE"                      # regex over human text: last resort
    # Structured but uninformative (a bare non-zero exit): real
    # evidence, consulted only after everything more specific.
    LAST_RESORT = "LAST_RESORT"
    NONE = "NONE"                        # nothing to classify from


_GRADE_RANK = {
    EvidenceGrade.STRUCTURED: 3,
    EvidenceGrade.SEMI_STRUCTURED: 2,
    EvidenceGrade.PROSE: 1,
    EvidenceGrade.LAST_RESORT: 0.5,
    EvidenceGrade.NONE: 0,
}

# Failures that are the environment's fault, not the agent's: they must
# never count against agent quality (constitution rule 7).
_NON_PENALIZING = frozenset({
    FailureClass.FAIL_INFRA,
    FailureClass.RATE_LIMITED,
    FailureClass.STALE_LEASE,
    FailureClass.DEPENDENCY_ERROR,
    FailureClass.UNCLASSIFIED,
    # A routing verdict ("the kernel cannot decide, a human must"), never a
    # quality judgement. A gap in the rule set is the operator's hole, not
    # the agent's mistake; work an agent did badly has its own class.
    FailureClass.NEEDS_HUMAN,
})


@dataclass(frozen=True)
class FailureSignal:
    """Everything an adapter observed about one attempt.

    Structured fields are separate from text on purpose: a classifier that
    wants an exit code must not be able to reach it by scraping a log.
    """

    exit_code: int | None = None
    timed_out: bool = False
    cancelled: bool = False
    structured: dict[str, Any] = field(default_factory=dict)
    stderr_text: str = ""
    stdout_text: str = ""
    exception: str | None = None

    def __post_init__(self) -> None:
        # Annotations are not enforcement, and `bool` IS an `int` in
        # Python: an adapter passing exit_code=False for a FAILED process
        # would have been classified PASS at structured grade, bypassing
        # retry, park and escalation entirely (Codex review).
        if isinstance(self.exit_code, bool) or not isinstance(
            self.exit_code, (int, type(None))
        ):
            raise TypeError(f"exit_code must be an int or None, got {self.exit_code!r}")
        for flag_name in ("timed_out", "cancelled"):
            if not isinstance(getattr(self, flag_name), bool):
                raise TypeError(f"{flag_name} must be a bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code, "timed_out": self.timed_out,
            "cancelled": self.cancelled, "structured": self.structured,
            "stderr_excerpt": self.stderr_text[-2000:],
            "stdout_excerpt": self.stdout_text[-2000:],
            "exception": self.exception,
        }


@dataclass(frozen=True)
class FailureClassification:
    failure: FailureClass
    reason_code: str
    evidence_grade: EvidenceGrade
    classifier_id: str
    evidence: str = ""
    reset_at: float | None = None       # RATE_LIMITED: when the window reopens
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def penalizes_agent(self) -> bool:
        """Constitution rule 7: infrastructure problems are not the
        agent's fault and must not degrade its quality score."""
        return self.failure not in _NON_PENALIZING and self.failure is not FailureClass.PASS

    @property
    def is_park(self) -> bool:
        """Rule 6: RATE_LIMITED is a park state, not a code failure."""
        return self.failure is FailureClass.RATE_LIMITED

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure": self.failure.value, "reason_code": self.reason_code,
            "evidence_grade": self.evidence_grade.value,
            "classifier_id": self.classifier_id, "evidence": self.evidence[:500],
            "reset_at": self.reset_at, "detail": self.detail,
            "penalizes_agent": self.penalizes_agent,
        }


Classifier = Callable[[FailureSignal], "FailureClassification | None"]


@dataclass(frozen=True)
class NamedClassifier:
    classifier_id: str
    grade: EvidenceGrade
    fn: Classifier


class FailureClassifierChain:
    """Evidence-ordered classification.

    Classifiers are consulted in descending evidence grade and the FIRST
    match wins. Prose outranks ONLY the bare-exit-code classifier
    (`LAST_RESORT`); it can never overrule informative structured
    evidence. See the module docstring for why that one demotion is
    deliberate. A classifier cannot claim a grade it was not registered
    with — the grade is the chain's property, not the classifier's
    self-description.
    """

    def __init__(self, classifiers: Sequence[NamedClassifier]):
        self._classifiers = sorted(
            classifiers, key=lambda c: _GRADE_RANK[c.grade], reverse=True,
        )

    def classify(self, signal: FailureSignal) -> FailureClassification:
        for named in self._classifiers:
            try:
                result = named.fn(signal)
            except Exception as exc:  # noqa: BLE001 - a broken classifier must not decide
                return FailureClassification(
                    FailureClass.UNCLASSIFIED,
                    reason_code="classifier_raised",
                    evidence_grade=EvidenceGrade.NONE,
                    classifier_id=named.classifier_id,
                    evidence=repr(exc)[:500],
                )
            if result is None:
                continue
            # The chain stamps identity and grade: a classifier cannot
            # promote its own evidence to a higher grade than it holds.
            return FailureClassification(
                failure=result.failure, reason_code=result.reason_code,
                evidence_grade=named.grade, classifier_id=named.classifier_id,
                evidence=result.evidence, reset_at=result.reset_at,
                detail=result.detail,
            )
        return FailureClassification(
            FailureClass.UNCLASSIFIED, reason_code="no_classifier_matched",
            evidence_grade=EvidenceGrade.NONE, classifier_id="chain",
        )


# -- built-in classifiers --------------------------------------------------


def structured_outcome_classifier(signal: FailureSignal) -> FailureClassification | None:
    """Exit codes and runner flags: the highest-confidence evidence."""
    if signal.cancelled:
        return FailureClassification(
            FailureClass.FAIL_INFRA, "cancelled", EvidenceGrade.STRUCTURED,
            "structured", evidence="runner reported cancelled",
        )
    if signal.timed_out:
        return FailureClassification(
            FailureClass.TIMEOUT, "timed_out", EvidenceGrade.STRUCTURED,
            "structured", evidence="runner reported timeout",
        )
    if signal.exit_code == 0:
        return FailureClassification(
            FailureClass.PASS, "exit_zero", EvidenceGrade.STRUCTURED, "structured",
        )
    return None


def exit_code_failure_classifier(signal: FailureSignal) -> FailureClassification | None:
    """A non-zero exit with no richer evidence is a code failure.

    This runs at the LOWEST structured priority, after the rate-limit
    classifiers, so a rate-limited process that also exits non-zero is
    still parked rather than retried. Treating a bare non-zero exit as
    UNCLASSIFIED instead would escalate every ordinary failure and make
    the common case unworkable — which is how a taxonomy ends up bypassed
    (both reviews raised this).
    """
    if signal.exit_code is None or signal.exit_code == 0:
        return None
    return FailureClassification(
        FailureClass.FAIL_CODE, "nonzero_exit", EvidenceGrade.STRUCTURED,
        "exit_code_failure", evidence=f"exit_code={signal.exit_code}",
    )


def _finite_number(value: Any) -> float | None:
    """A usable numeric field, or None.

    Rejects bools (True would become 1.0 — an epoch in 1970, reopening a
    shut window instantly) and non-finite values (NaN never satisfies
    `now >= reset_at`, wedging a credential forever). Both were reachable
    from provider JSON (Codex review).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def make_structured_rate_limit_classifier(
    now_fn: Callable[[], float],
) -> Classifier:
    """Build the structured rate-limit classifier.

    ``now_fn`` exists because the common provider field is HTTP's
    `Retry-After`: a RELATIVE number of seconds, not an epoch. Discarding
    it left the hold with no window at all, and a hold with no window
    never expires — one rate limit wedging a credential permanently
    (Codex review). Converting it needs a clock, so the clock is injected
    rather than read ambiently, keeping classification testable.
    """

    def classify(signal: FailureSignal) -> FailureClassification | None:
        payload = signal.structured
        if not payload:
            return None
        if not (payload.get("error_type") == "rate_limit"
                or payload.get("rate_limited") is True):
            return None
        now = now_fn()
        reset_at = _finite_number(payload.get("reset_at"))
        if reset_at is None:
            reset_at = _finite_number(payload.get("retry_after_epoch"))
        if reset_at is not None and reset_at <= now:
            # An absolute reset already in the past is not a window: it is
            # either a stale value or a different clock base. Parking until
            # a moment that has passed parks nothing (adversarial review).
            reset_at = None
        source = "absolute"
        if reset_at is None:
            # Relative seconds (the HTTP standard spelling).
            delay = _finite_number(payload.get("retry_after"))
            if delay is None:
                delay = _finite_number(payload.get("retry_after_seconds"))
            if delay is not None and delay >= 0:
                reset_at = now + delay
                source = "relative"
        return FailureClassification(
            FailureClass.RATE_LIMITED, "rate_limit_structured",
            EvidenceGrade.SEMI_STRUCTURED, "structured_rate_limit",
            evidence=str(payload)[:500], reset_at=reset_at,
            detail={"credential": payload.get("credential"),
                    "reset_source": source if reset_at is not None else "unknown"},
        )

    return classify


def structured_rate_limit_classifier(signal: FailureSignal) -> FailureClassification | None:
    """Default binding, using the wall clock for relative Retry-After."""
    return make_structured_rate_limit_classifier(time.time)(signal)


# Anchored to an ERROR context. The bare tokens matched ordinary output —
# including a tool describing its own limiter, and (verified) GNOSIS's own
# failing test suite, whose fixtures print the literal phrase. A log line
# mentioning rate limiting is not a rate limit (adversarial review).
_PROSE_RATE_LIMIT = re.compile(
    r"\b(?:(?:rate|usage)[ _-]?limit(?:ed|s)?\s+(?:reached|exceeded|hit)"
    r"|quota\s+exceeded"
    r"|too\s+many\s+requests)\b",
    re.IGNORECASE,
)


def prose_rate_limit_classifier(signal: FailureSignal) -> FailureClassification | None:
    """Last resort. Deliberately does NOT invent a reset timestamp: a
    parked run with a made-up reset time is worse than one that waits for
    an operator, so the absence of a reliable window is recorded as such.

    Refuses to fire when structured evidence is present and does NOT say
    rate limit: a higher-grade classifier returning None means "I looked
    and this is not one", which prose may not overturn (adversarial
    review — the chain previously read that silence as "no evidence").
    """
    if signal.structured and not (
        signal.structured.get("error_type") == "rate_limit"
        or signal.structured.get("rate_limited") is True
    ):
        return None
    text = f"{signal.stderr_text}\n{signal.stdout_text}"
    match = _PROSE_RATE_LIMIT.search(text)
    if not match:
        return None
    return FailureClassification(
        FailureClass.RATE_LIMITED, "rate_limit_prose", EvidenceGrade.PROSE,
        "prose_rate_limit", evidence=match.group(0).strip(),
        detail={"reset_unknown": True},
    )


DEFAULT_CHAIN = FailureClassifierChain([
    NamedClassifier("structured_outcome", EvidenceGrade.STRUCTURED,
                    structured_outcome_classifier),
    NamedClassifier("structured_rate_limit", EvidenceGrade.SEMI_STRUCTURED,
                    structured_rate_limit_classifier),
    NamedClassifier("prose_rate_limit", EvidenceGrade.PROSE,
                    prose_rate_limit_classifier),
    # Deliberately the LOWEST-priority classifier: a bare non-zero exit is
    # real structured evidence of a code failure, but any richer evidence
    # (a rate-limit field, even a prose rate-limit line) describes the
    # failure better and must win.
    NamedClassifier("exit_code_failure", EvidenceGrade.LAST_RESORT,
                    exit_code_failure_classifier),
])


# -- scheduler policy ------------------------------------------------------


class SchedulerAction(str, Enum):
    CONTINUE = "CONTINUE"    # success
    RETRY = "RETRY"          # bounded retry, counts against the attempt cap
    PARK = "PARK"            # durable wait (rate limit): NOT a retry
    FAIL = "FAIL"            # terminal for this attempt chain
    ESCALATE = "ESCALATE"    # needs a human


_ACTION_BY_CLASS = {
    FailureClass.PASS: SchedulerAction.CONTINUE,
    FailureClass.RATE_LIMITED: SchedulerAction.PARK,
    # Bounded by RetryPolicy.max_attempts (rule 8): a code failure is
    # exactly what a bounded rework loop exists to retry.
    FailureClass.FAIL_CODE: SchedulerAction.RETRY,
    FailureClass.FAIL_TEST: SchedulerAction.RETRY,
    FailureClass.FAIL_INFRA: SchedulerAction.RETRY,
    FailureClass.TIMEOUT: SchedulerAction.RETRY,
    FailureClass.AGENT_CRASH: SchedulerAction.RETRY,
    FailureClass.STALE_LEASE: SchedulerAction.RETRY,
    FailureClass.DEPENDENCY_ERROR: SchedulerAction.ESCALATE,
    FailureClass.NEEDS_HUMAN: SchedulerAction.ESCALATE,
    FailureClass.FAIL_SECURITY: SchedulerAction.ESCALATE,
    FailureClass.FAIL_POLICY: SchedulerAction.ESCALATE,
    FailureClass.STALEMATE: SchedulerAction.ESCALATE,
    FailureClass.MERGE_CONFLICT: SchedulerAction.ESCALATE,
}


def scheduler_action(classification: FailureClassification) -> SchedulerAction:
    """Map a classification to what the scheduler does next.

    An UNCLASSIFIED failure escalates rather than retrying: repeating an
    action nobody understood is how a loop becomes infinite (rule 8) and
    how a destructive call gets made twice.
    """
    if classification.failure is FailureClass.UNCLASSIFIED:
        return SchedulerAction.ESCALATE
    return _ACTION_BY_CLASS.get(classification.failure, SchedulerAction.FAIL)


# -- rate-limit holds (durable park state) ---------------------------------


class HoldScope(str, Enum):
    ACCOUNT = "ACCOUNT"  # window known shut: block everything on the credential
    PROBE = "PROBE"      # one resume is probing: block only NEW work


@dataclass(frozen=True)
class RateLimitHold:
    credential: str
    scope: HoldScope
    reason_code: str
    reset_at: float | None = None   # None = window unknown (prose evidence)
    placed_at: float = 0.0
    # PROBE holds name the ONE run allowed through. Without an identity,
    # `is_resume=True` was an unconstrained claim any caller could make,
    # so every queued resume was admitted at once — precisely the
    # stampede a probe exists to prevent (Codex review).
    probe_holder: str | None = None
    # True when reset_at is the kernel's bounded fallback rather than a
    # window the provider actually supplied: an operator reading a hold
    # must be able to tell a measured window from an estimated one.
    window_estimated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "credential": self.credential, "scope": self.scope.value,
            "reason_code": self.reason_code, "reset_at": self.reset_at,
            "placed_at": self.placed_at, "probe_holder": self.probe_holder,
            "window_estimated": self.window_estimated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RateLimitHold:
        """Rebuild a hold from a durable row, validating as it goes.

        This is the RECOVERY BOUNDARY, and it used to accept whatever the
        file held. `hold_from_classification` rejects non-finite and
        boolean windows on the way in, but nothing re-checked them on the
        way out — so a damaged or hostile row carrying `Infinity` produced
        a hold that never expires, and one carrying `NaN` both never
        expired and made `reconcile` order-dependent, since every
        comparison against NaN is false (Codex review). A validating
        constructor turns both into a rejected row, which the store
        reports as damage and the scheduler denies on.
        """
        reset_at = data.get("reset_at")
        if reset_at is not None:
            if isinstance(reset_at, bool) or not isinstance(reset_at, (int, float)):
                raise ValueError(f"reset_at must be a number or null, got {reset_at!r}")
            reset_at = float(reset_at)
            if not math.isfinite(reset_at):
                raise ValueError(f"reset_at must be finite, got {reset_at!r}")
        placed_at = data.get("placed_at", 0.0)
        if isinstance(placed_at, bool) or not isinstance(placed_at, (int, float)):
            raise ValueError(f"placed_at must be a number, got {placed_at!r}")  # noqa: TRY004
        placed_at = float(placed_at)
        if not math.isfinite(placed_at):
            raise ValueError("placed_at must be finite")
        credential = data["credential"]
        if not isinstance(credential, str) or not credential:
            # ValueError, not TypeError, throughout this constructor: it
            # validates a DURABLE ROW, where a wrong type is corrupt data
            # rather than a caller mistake — and the store's damage
            # handling catches ValueError to deny.
            raise ValueError("a hold must name a credential")
        return cls(
            credential=credential, scope=HoldScope(data["scope"]),
            reason_code=data["reason_code"], reset_at=reset_at,
            placed_at=placed_at,
            probe_holder=data.get("probe_holder"),
            window_estimated=bool(data.get("window_estimated", False)),
        )

    def restrictiveness(self) -> tuple[int, float]:
        """Sort key: how much this hold forbids.

        ACCOUNT outranks PROBE, and an unknown window (None) outranks any
        known one — "we do not know when it reopens" forbids more than a
        deadline. Among known windows the LATER reset wins: keeping an
        earlier one reopened a window a later durable record says is
        still shut (Codex review)."""
        scope_rank = 1 if self.scope is HoldScope.ACCOUNT else 0
        return (scope_rank, float("inf") if self.reset_at is None else self.reset_at)

    def expired(self, now: float) -> bool:
        # A hold with an unknown window never expires on its own: guessing
        # a reset time is what turns one rate limit into a stampede.
        return self.reset_at is not None and now >= self.reset_at


class HoldRegistry:
    """Credential-scoped holds, rebuilt idempotently from durable records.

    This is the volatile half of recovery-as-reconcile: it holds no truth
    of its own. `reconcile(records, now)` rebuilds the whole state from
    the durable rows, so calling it on every scheduler pump — or twice in
    a row, or after a restart — always lands in the same place.
    """

    def __init__(self) -> None:
        self._holds: dict[str, RateLimitHold] = {}

    def reconcile(self, records: Iterable[RateLimitHold], now: float) -> list[RateLimitHold]:
        """Rebuild from durable state; return the holds that are now live."""
        rebuilt: dict[str, RateLimitHold] = {}
        for hold in records:
            if hold.expired(now):
                continue
            current = rebuilt.get(hold.credential)
            # The MOST RESTRICTIVE competing hold wins, by comparison
            # rather than by iteration order: reconcile is a rebuild, and
            # a rebuild whose answer depends on record order is not one.
            if current is None or hold.restrictiveness() > current.restrictiveness():
                rebuilt[hold.credential] = hold
        self._holds = rebuilt
        return sorted(rebuilt.values(), key=lambda h: h.credential)

    def admits(self, credential: str, now: float, is_resume: bool = False,
               runner_id: str | None = None) -> bool:
        """May work start on this credential right now?

        A PROBE hold admits ONLY the named probing run (`runner_id` must
        match `probe_holder`); an ACCOUNT hold admits nothing. A PROBE
        hold with no named holder admits nobody: an unattributable probe
        is not a probe.

        `is_resume` is accepted and deliberately NOT required here. Once
        the holder is matched by identity the flag adds no restriction —
        the run named in the durable row is the one the kernel chose to
        admit — while requiring it means a caller that forgets the flag
        denies the probe its own passage. A claim any caller could make
        was the original defect; an exact identity is not that.
        """
        hold = self._holds.get(credential)
        if hold is None or hold.expired(now):
            return True
        if hold.scope is HoldScope.PROBE:
            return bool(
                runner_id is not None and hold.probe_holder is not None
                and runner_id == hold.probe_holder
            )
        return False

    def hold_for(self, credential: str) -> RateLimitHold | None:
        return self._holds.get(credential)

    def live_holds(self) -> list[RateLimitHold]:
        return sorted(self._holds.values(), key=lambda h: h.credential)


# How long a hold lasts when the provider gave no usable window. Chosen
# to be long enough to actually relieve a real limit, short enough that a
# false positive costs minutes rather than forever.
UNKNOWN_WINDOW_FALLBACK_S = 900.0


def hold_from_classification(classification: FailureClassification, credential: str,
                             now: float, scope: HoldScope = HoldScope.ACCOUNT,
                             probe_holder: str | None = None,
                             unknown_window_s: float = UNKNOWN_WINDOW_FALLBACK_S,
                             ) -> RateLimitHold | None:
    """Build the durable park record for a RATE_LIMITED classification.

    **Confidence bounds consequence.** The weakest evidence used to
    produce the harshest hold: prose is the only classifier that yields
    no window, an unknown window outranks every known one, and such a
    hold never expires — so one ambiguous log line could shut a
    credential permanently ("a loaded gun", adversarial review). A hold
    built without a provider-supplied window now gets a BOUNDED fallback
    and is marked `window_estimated`, so it relieves a real limit without
    being able to cause an unbounded outage on a guess.
    """
    if not classification.is_park:
        return None
    if scope is HoldScope.PROBE and not probe_holder:
        raise ValueError("a PROBE hold must name the run allowed to probe")
    reset_at = classification.reset_at
    estimated = reset_at is None
    if estimated:
        reset_at = now + unknown_window_s
    return RateLimitHold(
        credential=credential, scope=scope,
        reason_code=classification.reason_code,
        reset_at=reset_at, placed_at=now,
        probe_holder=probe_holder,
        window_estimated=estimated,
    )


# -- boot sweep (recovery as reconcile, never a ghost) ---------------------


class Disposition(str, Enum):
    READOPTED = "READOPTED"   # returned to the queue through the normal path
    FAILED = "FAILED"         # terminated loudly with a typed reason
    UNTOUCHED = "UNTOUCHED"   # legitimately still running


@dataclass(frozen=True)
class StrandedRun:
    run_id: str
    task_id: str
    state: str
    process_alive: bool | None
    heartbeat_stale_s: float | None
    classification: FailureClassification | None = None


@dataclass(frozen=True)
class SweepOutcome:
    run: StrandedRun
    disposition: Disposition
    reason_code: str
    action: SchedulerAction

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run.run_id, "task_id": self.run.task_id,
            "disposition": self.disposition.value, "reason_code": self.reason_code,
            "action": self.action.value,
        }


# Run states that are already finished: re-adopting one would re-execute
# completed work (Codex review — the sweep never read `state`).
TERMINAL_RUN_STATES = frozenset({
    "SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED", "CRASHED",
})


def boot_sweep(runs: Sequence[StrandedRun], stale_after_s: float = 120.0
               ) -> list[SweepOutcome]:
    """Re-adopt or fail every stranded run — never leave a ghost.

    A record that is neither progressing nor terminal is the worst
    outcome: nothing retries it and nothing reports it. Every run here
    leaves with a disposition and a typed reason code; a run that is
    demonstrably alive, and a run that already reached a terminal state,
    are both left strictly alone.
    """
    outcomes: list[SweepOutcome] = []
    for run in runs:
        if run.state in TERMINAL_RUN_STATES:
            # Already finished. Re-adopting it would run completed work a
            # second time, which is worse than the ghost this sweep exists
            # to prevent.
            outcomes.append(SweepOutcome(
                run, Disposition.UNTOUCHED, "already_terminal",
                SchedulerAction.CONTINUE,
            ))
            continue
        if run.process_alive is True and (run.heartbeat_stale_s is None
                                          or run.heartbeat_stale_s < stale_after_s):
            outcomes.append(SweepOutcome(
                run, Disposition.UNTOUCHED, "still_live", SchedulerAction.CONTINUE,
            ))
            continue

        classification = run.classification or FailureClassification(
            FailureClass.AGENT_CRASH, "no_live_process", EvidenceGrade.STRUCTURED,
            "boot_sweep",
        )
        action = scheduler_action(classification)
        if action in (SchedulerAction.RETRY, SchedulerAction.PARK):
            # Re-adoption goes through the NORMAL path: the sweep decides
            # nothing special, it just puts the run back where the
            # scheduler would have found it.
            disposition = Disposition.READOPTED
        else:
            disposition = Disposition.FAILED
        outcomes.append(SweepOutcome(
            run, disposition, classification.reason_code, action,
        ))
    return outcomes
