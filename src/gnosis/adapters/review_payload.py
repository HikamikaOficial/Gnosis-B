"""Parsing an agent's review into a kernel `ReviewReport`.

Separate from the adapters that produce the text, because the hard part
is not running a CLI — it is refusing to invent a verdict when the CLI
gives you something you cannot read.

The one rule everything here follows: **an unreadable review is not a
PASS, and it is not an UNCERTAIN either.** `UNCERTAIN` is a verdict an
agent can deliberately give and it means something; using it for "the
adapter could not parse the output" would erase the difference between a
reviewer that thought about the code and one that crashed. Unreadable
output raises `InvalidReviewOutput`, which `ConvergenceLoop` treats as an
evidence-collection failure: the round cannot converge and cannot count
toward stalemate. That is the honest shape — no evidence was collected.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..kernel.convergence import Finding, ReviewReport, ReviewVerdict, Severity

# The contract an agent is asked to satisfy. Kept here, next to the
# parser, so the prompt and the parser cannot drift apart.
REVIEW_SCHEMA_INSTRUCTIONS = """\
Return your review as a single JSON object inside a ```json fenced block,
and nothing after it. Shape:

{
  "verdict": "PASS" | "FAIL" | "UNCERTAIN",
  "notes": "<one or two sentences>",
  "findings": [
    {
      "severity": "CRITICAL" | "MAJOR" | "MINOR" | "INFO",
      "category": "<short kebab-case slug>",
      "description": "<one sentence stating the defect>",
      "evidence": "<what you observed that supports it>",
      "file": "<repo-relative path or null>",
      "symbol": "<function/class name or null>",
      "confidence": <number between 0 and 1>
    }
  ]
}

Use "PASS" only when nothing blocking stands. Report an empty findings
list rather than omitting the key. Do not wrap the object in any other
structure."""

_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


class InvalidReviewOutput(ValueError):
    """The agent produced something this adapter cannot read as a review.

    Maps to the constitution's INVALID_AGENT_OUTPUT: a distinct failure
    from the reviewer *disagreeing*, and never silently downgraded into a
    verdict nobody gave."""


def extract_json_object(text: str) -> dict[str, Any]:
    """Find the review object in an agent's message.

    Tried in descending order of how much the agent had to mean it: an
    explicit fenced block, then the whole message as JSON, then the last
    balanced `{...}` in the text. Guessing beyond that is how a paragraph
    that happens to contain braces becomes a verdict.
    """
    candidates: list[str] = []
    fences = _FENCE_RE.findall(text)
    candidates.extend(reversed(fences))          # the last fence is the answer
    candidates.append(text.strip())
    tail = _last_balanced_object(text)
    if tail is not None:
        candidates.append(tail)

    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    raise InvalidReviewOutput(
        f"no JSON review object found in {len(text)} characters of output"
    )


def _last_balanced_object(text: str) -> str | None:
    """The last brace-balanced span, ignoring braces inside strings.

    A naive `text[text.find('{'):text.rfind('}')+1]` swallows prose
    between two unrelated objects and produces JSON that parses but is
    not the review."""
    depth = 0
    start: int | None = None
    best: str | None = None
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                best = text[start:index + 1]
    return best


def parse_review_payload(text: str, reviewer: str) -> ReviewReport:
    """Turn an agent message into a ReviewReport, or refuse.

    Every field is validated. A review whose verdict is a typo, or whose
    findings are not a list, is INVALID rather than partially believed:
    the loop's whole premise is that this verdict is evidence.
    """
    payload = extract_json_object(text)

    raw_verdict = payload.get("verdict")
    if not isinstance(raw_verdict, str):
        raise InvalidReviewOutput(f"verdict missing or not a string: {raw_verdict!r}")
    try:
        verdict = ReviewVerdict(raw_verdict.strip().upper())
    except ValueError as exc:
        raise InvalidReviewOutput(f"unknown verdict {raw_verdict!r}") from exc

    raw_findings = payload.get("findings", [])
    if raw_findings is None:
        raw_findings = []
    if not isinstance(raw_findings, list):
        raise InvalidReviewOutput(f"findings must be a list, got {type(raw_findings).__name__}")

    findings = tuple(_parse_finding(item, reviewer, index)
                     for index, item in enumerate(raw_findings))

    # A FAIL that names nothing is not actionable, and a PASS that carries
    # a CRITICAL contradicts itself. Neither is this adapter's to correct:
    # the kernel decides what blocks (blocking_severities, the confidence
    # floor), and silently rewriting an agent's verdict here would hide
    # exactly the disagreement the loop exists to surface.
    notes = payload.get("notes", "")
    if not isinstance(notes, str):
        notes = str(notes)
    return ReviewReport(verdict=verdict, findings=findings, reviewer=reviewer, notes=notes)


def _parse_finding(item: Any, reviewer: str, index: int) -> Finding:
    if not isinstance(item, dict):
        raise InvalidReviewOutput(f"finding {index} is not an object: {type(item).__name__}")

    raw_severity = item.get("severity")
    if not isinstance(raw_severity, str):
        raise InvalidReviewOutput(f"finding {index}: severity missing or not a string")
    try:
        severity = Severity(raw_severity.strip().upper())
    except ValueError as exc:
        raise InvalidReviewOutput(f"finding {index}: unknown severity {raw_severity!r}") from exc

    description = item.get("description")
    if not isinstance(description, str) or not description.strip():
        raise InvalidReviewOutput(f"finding {index}: description missing or empty")

    confidence = item.get("confidence", 1.0)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        # bool is int in Python: `confidence: true` would silently become
        # 1.0, i.e. maximum confidence from a value that expressed none.
        raise InvalidReviewOutput(f"finding {index}: confidence must be a number")
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        raise InvalidReviewOutput(f"finding {index}: confidence {confidence} outside [0, 1]")

    return Finding(
        severity=severity,
        category=_optional_str(item.get("category")) or "unspecified",
        description=description.strip(),
        # The reviewer identity comes from the ADAPTER, never from the
        # payload: an agent that names itself something else would forge
        # the attribution the loop records.
        reviewer=reviewer,
        evidence=_optional_str(item.get("evidence")) or "",
        file=_optional_str(item.get("file")),
        symbol=_optional_str(item.get("symbol")),
        confidence=confidence,
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    return str(value)
