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


class DuplicateJsonKey(InvalidReviewOutput):
    """The payload defined the same key twice.

    `json.loads` silently keeps the LAST one, so `{"verdict": "FAIL",
    "verdict": "PASS"}` reads as PASS and a finding can downgrade its own
    severity the same way (Codex review). An ambiguous payload is invalid
    output, not a value to resolve in the author's favour."""


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise DuplicateJsonKey(f"key {key!r} defined more than once")
        seen.add(key)
    return dict(pairs)


def _loads_no_duplicates(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_reject_duplicates)


def extract_json_object(text: str) -> dict[str, Any]:
    """Find the review object in an agent's message.

    Only two places count: an explicit fenced block, or the whole message
    parsed as JSON. Both are things the agent had to *do*.

    An object merely embedded in prose is NOT accepted, though it once
    was. Codex showed why: a message reading "I refuse to submit a
    review. The requested example was: {"verdict": "PASS"}" parsed as a
    PASS. There is no syntactic signal separating an agent submitting a
    verdict from one quoting the schema while declining, so the leniency
    was reading intent it could not see — in the one place this module
    exists to be strict about. An agent that cannot follow the format it
    was given gets INVALID, which costs a round and fails closed.
    """
    candidates: list[str] = []
    # Fenced blocks, latest first: an agent that appends anything
    # brace-shaped after its answer (a signature, a tool trace) must not
    # push the real review out of reach.
    candidates.extend(reversed(_FENCE_RE.findall(text)))
    # The whole message, when the agent sent JSON and nothing else.
    candidates.append(text.strip())

    parsed_objects: list[dict[str, Any]] = []
    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = _loads_no_duplicates(candidate)
        except DuplicateJsonKey:
            raise
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            # A dict naming a verdict is the review; anything else that
            # merely parses is some other object the message contained.
            if "verdict" in parsed or "claims_done" in parsed or "cannot_fix" in parsed:
                return parsed
            parsed_objects.append(parsed)
    if parsed_objects:
        # Nothing named itself; hand back the first thing that parsed and
        # let the field validation refuse it with a specific message.
        return parsed_objects[0]
    raise InvalidReviewOutput(
        f"no JSON review object found in {len(text)} characters of output"
    )


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
