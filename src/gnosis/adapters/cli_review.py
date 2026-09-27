"""Real reviewer and fixer adapters for `ConvergenceLoop` (adapter milestone 3/4).

ADR-0008 built the convergence loop and injected `review_fn`/`fix_fn` as
callables, with a note that the real adapters were future work. Nothing
ever supplied them, so the loop only ever judged deterministic fakes.
This is the wiring.

Three things this module refuses to do, each because the constitution
says so and the loop's value collapses without it:

**A reviewer never modifies what it judges** (rule 9). The reviewer
adapter launches its agent in a read-only posture and, crucially, does
not *trust* that posture: it fingerprints the workspace before and after
and raises if the tree moved. The permission flag is the provider's
promise; the fingerprint is the kernel's evidence. The enforcement
matrix records which is which.

**An unreadable answer is not a verdict.** Parsing lives in
`review_payload` and fails closed; see the reasoning there.

**A fixer's DONE is a signal, not evidence** (ADR-0008 already encodes
this: `claims_done` with an unchanged fingerprint is downgraded). The
adapter reports what the agent said and never upgrades it.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from ..kernel.convergence import Finding, FixReport, FixRequest, ReviewReport
from ..kernel.git_evidence import tamper_fingerprint
from ..kernel.verification import (
    VerificationVerdict,
    evidence_name,
    evidence_reason,
    verification_verdict,
)
from ..runner.capture import ExecutionResult
from ..runner.claude_cli_runner import McpRunnerConfig
from .review_payload import (
    REVIEW_SCHEMA_INSTRUCTIONS,
    InvalidReviewOutput,
    extract_json_object,
    parse_review_payload,
)

# A reviewer must not be able to edit the thing it judges. `plan` is the
# Claude Code mode that withholds edit tools; it is a permission-layer
# promise, not a sandbox, which is why CliReviewer fingerprints the tree
# either side of the run and why the enforcement matrix records
# `reviewer_read_only` as SANDBOX_APPROX rather than HARD.
REVIEW_PERMISSION_MODE = "plan"
FIX_PERMISSION_MODE = "acceptEdits"

# An agent that dumps a build log to stdout must not turn a review round
# into an unbounded read.
MAX_AGENT_MESSAGE_CHARS = 2_000_000


class ReviewerModifiedSubject(RuntimeError):
    """The reviewer changed the workspace it was judging (rule 9).

    Treated as an evidence-collection failure by the loop: a round whose
    reviewer edited the code produced no independent verdict, whatever it
    printed."""


class AgentRunner(Protocol):
    """What both adapters need from a runner.

    Deliberately narrower than `ClaudeCodeCLIRunner`: a `ReplayingCLIRunner`
    (ADR-0014) satisfies it too, so a whole convergence loop can be
    recorded and replayed."""

    def run(
        self, prompt: str, cwd: Path, stdout_path: Path, stderr_path: Path,
        timeout_s: float = ..., **kwargs: Any,
    ) -> ExecutionResult: ...


def agent_message_text(result: ExecutionResult) -> str:
    """The agent's own final message, from a Claude Code `--output-format json` run.

    Falls back to the raw stdout when the envelope is missing or shaped
    unexpectedly: a review is still readable from plain text, and
    refusing to look would turn a provider's envelope change into a total
    outage. What is NOT tolerated is inventing a verdict — that decision
    belongs to the parser, which fails closed.
    """
    payload = result.parsed_json
    if isinstance(payload, dict):
        for key in ("result", "text", "content", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value[:MAX_AGENT_MESSAGE_CHARS]
    try:
        with Path(result.stdout_path).open("r", encoding="utf-8", errors="replace") as fh:
            # Bounded: an agent that dumps a log to stdout must not be able
            # to make the reviewer read a multi-gigabyte file into memory,
            # and a review that does not fit in this much text is not a
            # review this parser was going to find an answer in anyway.
            return fh.read(MAX_AGENT_MESSAGE_CHARS)
    except OSError:
        return ""


def build_review_prompt(
    objective: str, round_index: int, focus: Sequence[str] | None = None,
    verification_summary: str | None = None,
) -> str:
    parts = [
        ("You are an INDEPENDENT reviewer. Do not modify any file: you are "
         "judging this work, not doing it."),
        f"Objective under review: {objective}",
        f"Review round: {round_index}",
    ]
    if verification_summary:
        # The reviewer sees what the machine already proved, so it spends
        # its round on what deterministic verification cannot answer.
        parts.append(f"Deterministic verification this round: {verification_summary}")
    if focus:
        parts.append("Focus on: " + "; ".join(focus))
    parts.append(
        "Judge correctness first, then security, then whether the change is "
        "supported by evidence. Report only defects you can point at."
    )
    parts.append(REVIEW_SCHEMA_INSTRUCTIONS)
    return "\n\n".join(parts)


def verification_prompt_line(evidence: object) -> str | None:
    """What a fixer is told about the deterministic verification.

    Three answers, because there are three states and collapsing them
    misdirects the agent that reads it:

    - PASSED, or no verification this round: nothing to say here.
    - FAILED: the code is wrong and must end up passing.
    - MALFORMED: the VERIFIER is wrong. Telling a fixer "verification is
      failing" here sends it to edit code that may be perfectly fine,
      and the old line did exactly that — it tested
      `not request.verification.passed`, so a `passed` of `1` printed
      nothing at all and the round looked clean (third F-34 review).
    """
    if evidence is None:
        return None
    verdict = verification_verdict(evidence)
    if verdict is VerificationVerdict.FAILED:
        return ("Deterministic verification is currently FAILING; that must "
                "end up passing.")
    if verdict is VerificationVerdict.MALFORMED:
        return (
            "Deterministic verification returned INVALID EVIDENCE: "
            f"{evidence_name(evidence)} recorded no verdict, so nothing is "
            "known about whether the code is correct. This is NOT a report "
            "that the code failed — do not start by editing it. Repair the "
            f"verifier first. Details: {evidence_reason(evidence)}"
        )
    return None


def build_fix_prompt(request: FixRequest, objective: str) -> str:
    parts = [
        ("You are fixing defects an independent reviewer found. Change the "
         "code; do not argue with the findings in prose."),
        f"Objective: {objective}",
        f"Round: {request.round_index}",
    ]
    verification_line = verification_prompt_line(request.verification)
    if verification_line is not None:
        parts.append(verification_line)
    if request.blocking_findings:
        parts.append("Blocking findings:\n" + "\n".join(
            _render_finding(index, finding)
            for index, finding in enumerate(request.blocking_findings, start=1)
        ))
    parts.append(
        "When you are done, output a single JSON object in a ```json fenced "
        'block: {"claims_done": true|false, "cannot_fix": true|false, '
        '"notes": "<what you changed, or why you cannot>"}. '
        'Set "cannot_fix" only when the finding cannot be addressed here — '
        "it stops the loop, so it is not a way to end a hard round."
    )
    return "\n\n".join(parts)


def _slug(identity: str) -> str:
    """A filename-safe form of an agent identity.

    Identities carry `/` and `:` (`claude-cli`, `codex://reviewer-2`), and
    a path built from one unsanitised would escape the evidence directory
    or fail outright on Windows."""
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in identity)
    return safe.strip("-") or "agent"


def _render_finding(index: int, finding: Finding) -> str:
    location = f" [{finding.file}]" if finding.file else ""
    return (
        f"{index}. ({finding.severity.value}/{finding.category}){location} "
        f"{finding.description}"
        + (f"\n   evidence: {finding.evidence}" if finding.evidence else "")
    )


class CliReviewer:
    """`review_fn` for `ConvergenceLoop`, backed by a real agent CLI."""

    def __init__(
        self,
        runner: AgentRunner,
        repo_path: Path,
        evidence_dir: Path,
        objective: str,
        reviewer_id: str = "claude-cli",
        focus: Sequence[str] | None = None,
        timeout_s: float = 900.0,
        mcp: McpRunnerConfig | None = None,
        fingerprint_fn: Callable[[Path], dict[str, Any]] | None = None,
    ) -> None:
        self.runner = runner
        self.repo_path = repo_path
        self.evidence_dir = evidence_dir
        self.objective = objective
        self.reviewer_id = reviewer_id
        self.focus = tuple(focus or ())
        self.timeout_s = timeout_s
        self.mcp = mcp
        self.fingerprint_fn = fingerprint_fn or tamper_fingerprint

    def __call__(self, round_index: int) -> ReviewReport:
        before = self.fingerprint_fn(self.repo_path)
        stdout, stderr = self._evidence_paths(round_index)
        result = self.runner.run(
            prompt=build_review_prompt(self.objective, round_index, self.focus),
            cwd=self.repo_path, stdout_path=stdout, stderr_path=stderr,
            timeout_s=self.timeout_s, permission_mode=REVIEW_PERMISSION_MODE,
            mcp=self.mcp,
        )
        # Checked BEFORE the output is parsed: a reviewer that edited the
        # code has already violated rule 9, and reading its verdict first
        # would mean deciding whether to care based on what it said.
        after = self.fingerprint_fn(self.repo_path)
        if after != before:
            raise ReviewerModifiedSubject(
                f"reviewer {self.reviewer_id!r} changed the workspace it was "
                f"judging in round {round_index}: {before} -> {after}"
            )
        if result.timed_out or result.cancelled or result.exit_code != 0:
            raise InvalidReviewOutput(
                f"reviewer {self.reviewer_id!r} did not finish round {round_index} "
                f"(exit_code={result.exit_code}, timed_out={result.timed_out}, "
                f"cancelled={result.cancelled})"
            )
        return parse_review_payload(agent_message_text(result), reviewer=self.reviewer_id)

    def _evidence_paths(self, round_index: int) -> tuple[Path, Path]:
        # The reviewer identity is in the filename, not just the round.
        # Two loops sharing an evidence directory both wrote `review-1.*`
        # and destroyed each other's evidence, which also made replay
        # attribution unreliable (Codex review).
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        stem = f"review-{_slug(self.reviewer_id)}-{round_index}"
        return (self.evidence_dir / f"{stem}.stdout",
                self.evidence_dir / f"{stem}.stderr")


class CliFixer:
    """`fix_fn` for `ConvergenceLoop`, backed by a real agent CLI."""

    def __init__(
        self,
        runner: AgentRunner,
        repo_path: Path,
        evidence_dir: Path,
        objective: str,
        fixer_id: str = "claude-cli",
        timeout_s: float = 1800.0,
        mcp: McpRunnerConfig | None = None,
    ) -> None:
        self.runner = runner
        self.repo_path = repo_path
        self.evidence_dir = evidence_dir
        self.objective = objective
        self.fixer_id = fixer_id
        self.timeout_s = timeout_s
        self.mcp = mcp

    def __call__(self, request: FixRequest) -> FixReport:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        stem = f"fix-{_slug(self.fixer_id)}-{request.round_index}"
        stdout = self.evidence_dir / f"{stem}.stdout"
        stderr = self.evidence_dir / f"{stem}.stderr"
        result = self.runner.run(
            prompt=build_fix_prompt(request, self.objective),
            cwd=self.repo_path, stdout_path=stdout, stderr_path=stderr,
            timeout_s=self.timeout_s, permission_mode=FIX_PERMISSION_MODE,
            mcp=self.mcp,
        )
        return self._parse(result, request.round_index)

    def _parse(self, result: ExecutionResult, round_index: int) -> FixReport:
        """A fixer's report, read conservatively.

        Unlike a review, an unreadable fix report is NOT fatal: the fixer
        may well have changed the repository, and the next round's
        verification and review are what decide anyway. The conservative
        reading is "it ran, it claims nothing" — which costs one more
        round and cannot fake progress. Claiming `cannot_fix` on
        unreadable output would end the loop on no evidence at all.
        """
        if result.timed_out or result.cancelled:
            return FixReport(
                claims_done=False, cannot_fix=False,
                notes=f"fixer {self.fixer_id!r} round {round_index} did not finish "
                      f"(timed_out={result.timed_out}, cancelled={result.cancelled})",
            )
        text = agent_message_text(result)
        try:
            payload = extract_json_object(text)
        except InvalidReviewOutput:
            return FixReport(
                claims_done=False, cannot_fix=False,
                notes=f"fixer {self.fixer_id!r} round {round_index}: no structured "
                      f"report found; treating the round as inconclusive",
            )
        notes = payload.get("notes", "")
        return FixReport(
            # `is True` on purpose: a truthy string or a non-empty list is
            # not a claim of doneness, and coercing one into `True` would
            # invent the signal the loop weighs.
            claims_done=payload.get("claims_done") is True,
            cannot_fix=payload.get("cannot_fix") is True,
            notes=notes if isinstance(notes, str) else json.dumps(notes, sort_keys=True),
        )
