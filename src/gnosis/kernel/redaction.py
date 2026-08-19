"""Secrets redaction boundary.

Raw stdout/stderr capture files are stored verbatim under runs/<id>/raw/,
that is deliberate immutable evidence and must never be edited in place.
redact() is the boundary function: anything derived from raw evidence
that crosses into the ledger, an EngineerReport, or a Director-facing
transport MUST be passed through this function first.
"""
from __future__ import annotations

import re
from typing import Any

_LABELS_AND_PATTERNS = [
    ("ANTHROPIC_API_KEY", re.compile(r"sk-ant-[A-Za-z0-9\-_]{10,}")),
    ("OPENAI_API_KEY", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("GITHUB_TOKEN", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("AWS_ACCESS_KEY_ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("SLACK_TOKEN", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("PRIVATE_KEY_BLOCK", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("BEARER_TOKEN", re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_.]{10,}")),
    ("GENERIC_SECRET_ASSIGNMENT", re.compile(
        r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*.{8,40}"
    )),
]


def redact(text: str) -> str:
    if not text:
        return text
    redacted = text
    for label, pattern in _LABELS_AND_PATTERNS:
        redacted = pattern.sub("REDACTED:" + label, redacted)
    return redacted


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = redact(value)
        elif isinstance(value, dict):
            result[key] = redact_mapping(value)
        elif isinstance(value, list):
            result[key] = [redact(v) if isinstance(v, str) else v for v in value]
        else:
            result[key] = value
    return result
