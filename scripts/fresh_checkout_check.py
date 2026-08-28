"""Run a test set against a FRESH CHECKOUT, and prove it was the fresh one.

WHY THIS EXISTS.

A fresh-checkout run is supposed to answer "does the committed tree stand on its
own?". It answers nothing if the interpreter imports the WORKING tree instead -
and on this machine it did. The project venv carries an editable install whose
`.pth` puts the repository's `src` on `sys.path` at startup, so a bare `import
gnosis` inside an extracted checkout resolved to the repository, not to the
extraction. Measured, not assumed:

    gnosis : C:\\...\\GnosisAgentAi\\src\\gnosis\\__init__.py      <- the repo

Worse, it resolved INCONSISTENTLY. Test files that insert their own `src` at
`sys.path[0]` got the fresh copy while files relying on the editable install got
the repository copy, so one process held TWO `gnosis` packages and two copies of
every class in them. That surfaced as `assertRaises(WorkerLaunchFailed)` failing
while the traceback showed `WorkerLaunchFailed` being raised: two classes, same
name, different objects.

So this runner does two things a plain `pytest` invocation cannot:

  1. it puts the extracted `src` FIRST on `PYTHONPATH`;
  2. it PROVES the import resolved there before running anything, and refuses
     to run if it did not.

A fresh-checkout check that cannot tell which tree it measured is not a check.

    PYTHONUTF8=1 python scripts/fresh_checkout_check.py <commit> <out> [tests...]
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PREFLIGHT = (
    "import gnosis, json, sys;"
    "print(json.dumps({'gnosis': gnosis.__file__, 'path0': sys.path[0]}))"
)


def extract(commit: str, destination: Path) -> int:
    """`git archive` reads the OBJECT DATABASE, not the working tree, so this is
    safe even while something else is editing the checkout."""
    destination.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(["git", "archive", commit], cwd=REPO,
                             capture_output=True, check=True)
    extract_proc = subprocess.run(["tar", "-x", "-C", str(destination)],
                                  input=archive.stdout, capture_output=True,
                                  check=False)
    if extract_proc.returncode != 0:
        raise SystemExit(f"extraction failed: {extract_proc.stderr[:400]!r}")
    return sum(1 for _ in destination.rglob("*") if _.is_file())


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        sys.stderr.write("usage: fresh_checkout_check.py <commit> <out> [tests...]\n")
        return 2
    commit, out_path = argv[1], Path(argv[2])
    targets = argv[3:] or ["tests"]

    lines: list[str] = []

    def say(message: str) -> None:
        print(message, flush=True)
        lines.append(message)

    with tempfile.TemporaryDirectory(prefix="gnosis-fresh-") as tmp:
        fresh = Path(tmp) / "tree"
        say(f"FRESH CHECKOUT OF {commit}")
        say("=" * 70)
        count = extract(commit, fresh)
        say(f"extracted files: {count}")
        say(f"extracted to   : {fresh}")
        say("")

        env = dict(os.environ)
        env["PYTHONPATH"] = str(fresh / "src")
        env["PYTHONUTF8"] = "1"

        say("PREFLIGHT — which tree does `import gnosis` actually resolve to?")
        pre = subprocess.run([sys.executable, "-c", PREFLIGHT], cwd=fresh,
                             env=env, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", check=False)
        say(pre.stdout.strip() or pre.stderr.strip()[:400])
        # PARSED, not substring-matched against the raw line: the probe prints
        # JSON, so its backslashes are escaped and a naive `in` test compares
        # `C:\\Users` against `C:\Users` and always fails. It failed CLOSED,
        # which is the right direction for a bug to fail in, but it was still a
        # bug in the check rather than a finding about the tree.
        try:
            resolved = json.loads(pre.stdout.strip())["gnosis"]
        except (ValueError, KeyError):
            resolved = ""
        if not resolved or not Path(resolved).is_relative_to(fresh):
            # FAIL CLOSED. Running the tests now would measure the working tree
            # while calling the result a fresh checkout.
            say("")
            say("PREFLIGHT FAILED: the import resolved OUTSIDE the extraction, so "
                "this run would measure the working tree. Refusing to continue.")
            out_path.write_text("\n".join(lines) + "\nFRESH_EXIT=3\n", encoding="utf-8")
            return 3
        say("preflight OK: the extraction won the import")
        say("")

        say(f"RUNNING: {' '.join(targets)}")
        say("-" * 70)
        proc = subprocess.run([sys.executable, "-m", "pytest", *targets, "-q",
                               "-p", "no:cacheprovider"],
                              cwd=fresh, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=False)
        for line in (proc.stdout + proc.stderr).splitlines():
            say(line)
        say(f"FRESH_EXIT={proc.returncode}")
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # The temporary tree is removed by the context manager; nothing of the
        # extraction survives the run.
        shutil.rmtree(fresh, ignore_errors=True)
        return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
