"""Capture a verification transcript with exit codes.

An ADR line reading "suite 535/535; mypy strict clean" is a claim about
a command nobody can see. An independent review called that out
precisely: self-reported prose is not evidence, and this project's own
definition of done requires proof.

Writes `.gnosis/evidence/<utc-stamp>/` containing each command's argv,
exit code, duration and captured output, plus a `SUMMARY.json` an ADR
can cite by path. Exits non-zero if any command failed, so it cannot
produce a green transcript for a red tree.

    uv run --no-project --with pytest --with mypy --with ruff \
        python scripts/capture_evidence.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EVIDENCE_ROOT = REPO / ".gnosis" / "evidence"

COMMANDS: list[tuple[str, list[str]]] = [
    ("pytest", [sys.executable, "-m", "pytest", "tests/", "-q"]),
    ("mypy", [sys.executable, "-m", "mypy", "src/gnosis"]),
    ("ruff", [sys.executable, "-m", "ruff", "check", "src/gnosis", "tests",
              "--no-cache", "--output-format=concise"]),
    ("git-head", ["git", "rev-parse", "HEAD"]),
    ("git-status", ["git", "status", "--porcelain"]),
]

# Commands whose non-zero exit is a KNOWN backlog rather than a broken
# tree. Ruff's default rule set here is broader than the one earlier
# milestones were written against, so the repo carries documented
# residuals in files nobody has touched since. Counting them, rather than
# ignoring the check or pretending it is clean, is what keeps "no NEW
# lint debt" enforceable while the backlog is paid down.
LINT_BASELINE = Path(__file__).resolve().parent.parent / ".gnosis" / "state" / "lint_baseline.json"


def _lint_baseline() -> int:
    try:
        payload = json.loads(LINT_BASELINE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # No baseline recorded: any finding is new debt. Failing closed
        # here is the point — a missing baseline must not read as
        # unlimited allowance.
        return 0
    value = payload.get("max_findings")
    return int(value) if isinstance(value, int) else 0


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = EVIDENCE_ROOT / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    failed = False
    for name, argv in COMMANDS:
        started = time.monotonic()
        proc = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, check=False)
        duration = time.monotonic() - started
        (out_dir / f"{name}.stdout.txt").write_text(proc.stdout, encoding="utf-8")
        (out_dir / f"{name}.stderr.txt").write_text(proc.stderr, encoding="utf-8")
        results.append({
            "name": name,
            "argv": argv,
            "exit_code": proc.returncode,
            "duration_s": round(duration, 2),
            # The last line is the one an ADR quotes ("535 passed in ...").
            "tail": (proc.stdout.strip().splitlines() or [""])[-1][:300],
        })
        if name == "ruff" and proc.returncode != 0:
            count = sum(1 for line in proc.stdout.splitlines()
                        if line.strip() and ":" in line and not line.startswith("["))
            baseline = _lint_baseline()
            results[-1]["lint_findings"] = count
            results[-1]["lint_baseline"] = baseline
            if count > baseline:
                results[-1]["verdict"] = f"NEW LINT DEBT: {count} > baseline {baseline}"
                failed = True
            else:
                results[-1]["verdict"] = "known backlog, not above baseline"
            continue
        if proc.returncode != 0:
            failed = True

    # `all_passed` used to be `not failed`, where `failed` forgave ruff for
    # exiting non-zero as long as it stayed at baseline. A one-line summary
    # that reads `true` while a gate exited 1 is where a reader stops, and
    # the reconciliation two levels down is not where they look
    # (independent review). The verdict is now split: what actually
    # succeeded, and what is a known, bounded backlog.
    non_zero = [r["name"] for r in results if r["exit_code"] != 0]
    summary = {
        "captured_at": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "results": results,
        "all_passed": not failed and not non_zero,
        "gates_clean": not failed,
        "non_zero_exits": non_zero,
        "verdict": (
            "all gates clean" if not failed and not non_zero
            else "within baseline; see non_zero_exits" if not failed
            else "FAILED"
        ),
    }
    (out_dir / "SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"\nevidence: {out_dir.relative_to(REPO)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
