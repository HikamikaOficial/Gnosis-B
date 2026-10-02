"""Deterministic Worker execution entry (F-33 Stage 2A).

This module is the executable IMAGE a sealed ``LaunchSpec`` names when the
canonical composition selects the ``DETERMINISTIC`` execution mode. It runs
INSIDE the dedicated Worker process (launched by the trusted F-17
``WorkerLauncher`` → ``bootstrap`` → this image, under the Worker SID) and
replays a bounded, sealed cassette with **zero external provider calls**,
zero network, and no subprocess of its own. It exists so the trusted
execution seam can be qualified provider-free while still traversing the real
Worker boundary.

Trust properties (Stage 2A):

- It is reached ONLY as the sealed ``LaunchSpec.executable``/``argv`` chosen by
  trusted composition code; it never chooses its own backend, executable or
  module, and it takes no execution-mode input.
- The cassette is DATA, not authority: it may describe deterministic model/tool
  output, but it cannot select an executable, weaken policy, forge identity, or
  manufacture a publication. Unknown/authority-shaped keys are rejected.
- Output is a single bounded machine-readable JSON object on stdout (captured by
  the bootstrap to the sealed ``stdout_path``). It is UNTRUSTED input to the
  Director-side seam until validated there.
- Exit code is the only control signal: ``0`` success, non-zero typed failures.

Run as (built by trusted code, never by an operator):
    <abs qualified python> -I -B <abs path to this module> <abs cassette path>

``-I`` (isolated) drops ``PYTHONPATH``, user site and the CWD from ``sys.path``,
so no current-directory module shadowing or uncontrolled ``PYTHONPATH`` can
redirect the run; the bootstrap additionally hands a closed-allowlist
environment. This module imports only the standard library so it resolves
without the ``gnosis`` package needing to be importable inside the Worker.
"""

from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

# Bounded so a malformed or hostile cassette cannot exhaust memory in the Worker.
MAX_CASSETTE_BYTES = 1 << 20  # 1 MiB
# H2 bounds for the CLOSED schema: an intentionally narrow deterministic format.
MAX_TURNS = 4096
MAX_MESSAGE_BYTES = 1 << 16  # 64 KiB per turn message
CASSETTE_SCHEMA = "gnosis.director.deterministic_cassette.v1"
RESULT_SCHEMA = "gnosis.director.deterministic_result.v1"

# Exit codes. Distinct, non-overlapping with the F-17 bootstrap's own codes,
# and each names one refusal so a Director-side reader never guesses.
EXIT_OK = 0
EXIT_USAGE = 10
EXIT_CASSETTE_UNREADABLE = 11
EXIT_CASSETTE_TOO_LARGE = 12
EXIT_CASSETTE_INVALID = 13

# H2 — CLOSED schema. The cassette is DATA, not execution authority. Rather than
# blocklisting a fixed set of authority-shaped keys (which a nested dict or a
# newly-invented key could slip past), the parser accepts ONLY these exact keys
# at each level and rejects everything else. Nothing outside this closed shape —
# at the top level or nested inside a turn — can be smuggled through.
_ALLOWED_TOP_KEYS = frozenset({"schema", "turns"})
_ALLOWED_TURN_KEYS = frozenset({"message"})


class CassetteInvalid(Exception):
    """The cassette is structurally or semantically unacceptable."""


def _read_cassette_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        # Read one byte past the ceiling so an over-size file is detected rather
        # than silently truncated to the limit.
        blob = handle.read(MAX_CASSETTE_BYTES + 1)
    if len(blob) > MAX_CASSETTE_BYTES:
        raise CassetteInvalid(
            f"cassette exceeds {MAX_CASSETTE_BYTES} bytes; refusing to load")
    return blob


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """H3 — reject duplicate keys in ANY JSON object rather than silently
    keeping the last (json's default), so a cassette cannot carry a shadow
    value under a repeated key that a lenient reader would miss."""
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise CassetteInvalid(f"duplicate JSON object key: {key!r}")
        seen.add(key)
    return dict(pairs)


def _parse_cassette(blob: bytes) -> dict[str, Any]:
    try:
        loaded = json.loads(blob.decode("utf-8"),
                            object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CassetteInvalid(f"cassette is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise CassetteInvalid("cassette top level must be a JSON object")
    return loaded


def validate_cassette(cassette: dict[str, Any]) -> dict[str, Any]:
    """Validate the CLOSED cassette contract and return the cassette.

    Raises ``CassetteInvalid`` for any deviation. This is the whole trust
    boundary of the cassette: it may only describe deterministic output, in an
    intentionally narrow shape. Only ``{schema, turns}`` at the top level and
    ``{message}`` per turn are accepted; every other key — top-level or nested —
    is rejected, so authority-shaped data cannot ride in through an unexpected
    or nested field.
    """
    schema = cassette.get("schema")
    if schema != CASSETTE_SCHEMA:
        raise CassetteInvalid(
            f"cassette schema must be {CASSETTE_SCHEMA!r}, got {schema!r}")
    extra = set(cassette) - _ALLOWED_TOP_KEYS
    if extra:
        raise CassetteInvalid(
            f"cassette carries unexpected top-level keys (closed schema): "
            f"{sorted(extra)}")
    turns = cassette.get("turns")
    if not isinstance(turns, list) or not turns:
        raise CassetteInvalid("cassette must carry a non-empty 'turns' list")
    if len(turns) > MAX_TURNS:
        raise CassetteInvalid(
            f"cassette carries {len(turns)} turns; the ceiling is {MAX_TURNS}")
    for index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            raise CassetteInvalid(f"turns[{index}] must be an object")
        turn_extra = set(turn) - _ALLOWED_TURN_KEYS
        if turn_extra:
            raise CassetteInvalid(
                f"turns[{index}] carries unexpected keys (closed schema): "
                f"{sorted(turn_extra)}")
        message = turn.get("message")
        if not isinstance(message, str):
            raise CassetteInvalid(f"turns[{index}].message must be a string")
        if len(message.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise CassetteInvalid(
                f"turns[{index}].message exceeds {MAX_MESSAGE_BYTES} bytes")
    return cassette


def run(cassette_path: str) -> dict[str, Any]:
    """Load, validate and 'execute' the cassette; return the bounded result.

    Execution here is deterministic replay: the result echoes the cassette's
    turns and binds the cassette's own content digest, so the Director-side seam
    can prove which sealed input produced this output. No provider is contacted.
    """
    blob = _read_cassette_bytes(cassette_path)
    cassette = validate_cassette(_parse_cassette(blob))
    turns = cassette["turns"]
    digest = hashlib.sha256(blob).hexdigest()
    return {
        "schema": RESULT_SCHEMA,
        "ok": True,
        "cassette_sha256": digest,
        "turn_count": len(turns),
        "final_message": turns[-1]["message"],
        "provider_calls": 0,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write(
            "usage: deterministic_worker.py <cassette-path>\n")
        return EXIT_USAGE
    cassette_path = argv[1]
    try:
        blob = _read_cassette_bytes(cassette_path)
    except CassetteInvalid as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_CASSETTE_TOO_LARGE
    except OSError as exc:
        sys.stderr.write(f"cannot read cassette: {exc}\n")
        return EXIT_CASSETTE_UNREADABLE
    try:
        cassette = validate_cassette(_parse_cassette(blob))
        turns = cassette["turns"]
        result = {
            "schema": RESULT_SCHEMA,
            "ok": True,
            "cassette_sha256": hashlib.sha256(blob).hexdigest(),
            "turn_count": len(turns),
            "final_message": turns[-1]["message"],
            "provider_calls": 0,
        }
    except CassetteInvalid as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_CASSETTE_INVALID
    # The one line of authoritative-shaped output: a bounded JSON object the
    # trusted side will re-validate. stdout only; diagnostics go to stderr.
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
