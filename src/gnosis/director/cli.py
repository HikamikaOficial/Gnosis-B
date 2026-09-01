"""Canonical operator entry (F-33 Stage 2B.2, ADR-0032 §7).

`gnosis = "gnosis.director.cli:main"` is the ONE supported operator entry. It
delegates to the ONE canonical production composition
(`build_production_deployment`) and never builds a second dependency graph, a
second orchestration root, or a weaker route.

Deliberately narrow (ADR §7, §13): one governed+published run per invocation.
The operator supplies only WORK input (a trusted-config path and a brief); it may
NOT override trusted deployment/security configuration (runtime, Worker identity,
credential, launch root, attribution, publisher/deployment identity) and there is
NO governance-disable flag. Trusted configuration is read from a file and
validated under the existing composition/deployment contract; a flag never
asserts a security-critical value as true.

Operator success is reported ONLY when governed work COMPLETED **and** the
evidence reached ANCHORED (§14). Nothing here reimplements policy, worker
isolation, credential authority, publication authorization, or the anchor.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# Exit codes (ADR §20 / task §20): publication-not-ANCHORED is always non-zero.
EXIT_OK = 0
EXIT_USAGE = 2          # invalid operator input / trusted config
EXIT_WORK_FAILED = 3    # governed work did not COMPLETE
EXIT_EXECUTION = 4      # trusted execution / composition construction failure
EXIT_PUBLICATION = 5    # authoritative publication did not reach ANCHORED

# Forbidden operator flags (§13): trusted deployment/security must never be
# overridden per run, and there is no production governance bypass.
_FORBIDDEN_FLAGS = (
    "--python", "--runtime", "--python-executable", "--worker-sid",
    "--worker-account", "--credential-blob", "--launch-root", "--reviewer-id",
    "--policy-actor", "--publisher", "--service-sid", "--deployment-digest",
    "--skip-review", "--no-verify", "--unsafe-direct", "--direct-runner",
    "--worker-executable", "--worker-module",
)


class OperatorError(Exception):
    """A fail-closed operator-facing error carrying an exit code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def _reject_forbidden_flags(argv: Sequence[str]) -> None:
    for token in argv:
        flag = token.split("=", 1)[0]
        if flag in _FORBIDDEN_FLAGS:
            raise OperatorError(
                f"{flag} is not accepted: trusted deployment/security "
                "configuration cannot be overridden per run, and production "
                "governance cannot be disabled", EXIT_USAGE)


_REQUIRED_CONFIG = ("deployment", "attribution", "operator", "publication",
                    "verifier")


def build_operator_composition(config_path: Path) -> Any:
    """Build the canonical operator composition from a TRUSTED config file.

    Isolated so tests can substitute a controlled composition; production always
    reaches the one `build_production_deployment`. Imported lazily so arg parsing
    and flag rejection never require the trust plane.

    STAGE 2B.2 SCOPE (honest): the production operator run additionally requires a
    provider-backed INDEPENDENT reviewer to reach COMPLETED, and provider-backed
    execution is explicitly deferred (ADR-0032 §11; Stage 2C). Rather than run a
    fake always-PASS reviewer in the operator path — which would defeat governance
    — this fails closed until the provider-backed reviewer lands. The publication
    seam, the operator-success invariant and the composition are qualified
    separately against the real trust code (see tests/test_publication_seam.py,
    tests/test_operator_composition.py). The CLI's own logic (delegation, flag
    rejection, exit codes) is qualified with a substituted composition.
    """
    try:
        raw = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatorError(f"trusted config {config_path} unreadable: {exc}",
                            EXIT_USAGE) from exc
    if not isinstance(raw, dict):
        raise OperatorError("trusted config must be a JSON object", EXIT_USAGE)
    missing = [k for k in _REQUIRED_CONFIG if k not in raw]
    if missing:
        raise OperatorError(
            f"trusted config missing sections: {', '.join(missing)}", EXIT_USAGE)
    raise OperatorError(
        "the canonical operator run requires a provider-backed independent "
        "reviewer to reach COMPLETED; provider-backed execution is deferred to "
        "Stage 2C. gnosis run fails closed rather than running an unsafe "
        "always-pass reviewer.", EXIT_EXECUTION)


def _load_brief(brief_path: Path) -> Any:
    from gnosis.contracts.director_brief import DirectorBrief
    try:
        raw = json.loads(Path(brief_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatorError(f"brief {brief_path} unreadable: {exc}",
                            EXIT_USAGE) from exc
    try:
        return DirectorBrief.from_dict(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise OperatorError(f"brief {brief_path} is invalid: {exc}",
                            EXIT_USAGE) from exc


def _run(config_path: Path, brief_path: Path) -> tuple[int, dict[str, Any]]:
    from gnosis.director.composition import CompositionError

    try:
        composition = build_operator_composition(config_path)
    except OperatorError:
        raise
    except CompositionError as exc:
        raise OperatorError(f"composition refused: {exc}", EXIT_EXECUTION) from exc
    brief = _load_brief(brief_path)
    outcome = composition.run_brief(brief)
    record = {
        "run_id": outcome.run_id, "task_id": outcome.task_id,
        "work_status": outcome.work_status,
        "publication_state": outcome.publication_state,
        "success": outcome.success, "detail": outcome.reason,
    }
    if outcome.success:
        return EXIT_OK, record
    if outcome.work_status != "COMPLETED":
        return EXIT_WORK_FAILED, record
    return EXIT_PUBLICATION, record


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(argv if argv is not None else __import__("sys").argv[1:])
    try:
        _reject_forbidden_flags(argv)
    except OperatorError as exc:
        print(f"gnosis: {exc}")
        return exc.code

    parser = argparse.ArgumentParser(prog="gnosis", add_help=True)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "submit"):
        p = sub.add_parser(name, help="run one governed+published brief")
        p.add_argument("--config", required=True, help="trusted config JSON path")
        p.add_argument("--brief", required=True, help="operator brief JSON path")
    try:
        ns = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE

    try:
        code, record = _run(Path(ns.config), Path(ns.brief))
    except OperatorError as exc:
        print(f"gnosis: {exc}")
        return exc.code
    print(json.dumps(record, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
