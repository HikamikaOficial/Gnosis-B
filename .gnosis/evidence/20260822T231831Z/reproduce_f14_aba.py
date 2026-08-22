"""The first independent review of ADR-0026, reproduced and closed.

The finding: two fingerprints prove two instants, not the interval
between them. A check that changes a covered file, reads the change and
restores the bytes, the size and the timestamps leaves both endpoints
identical, and the previous implementation called that valid evidence.

Every case below prints BOTH answers: what an endpoint comparison says
(`binding`, which is what the reviewed version decided on) and what the
observed interval says (`boundary`). The first column is BOUND in every
transient case — that is the finding — and the capture refuses anyway.

Run:  PYTHONUTF8=1 .venv/Scripts/python.exe <this file> --out <transcript>

Read-only with respect to the repository: every tree it builds is a
throwaway git repo in the system temp directory.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(r"C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi")
sys.path.insert(0, str(REPO / "src"))

from gnosis.kernel.evidence_capture import (  # noqa: E402
    CheckCommand,
    run_capture,
)
from gnosis.kernel.write_observer import (  # noqa: E402
    Observation,
    create_write_observer,
)

LINES: list[str] = []


def say(text: str = "") -> None:
    print(text, flush=True)
    LINES.append(text)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, check=True).stdout


def make_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "a.txt").write_text("original\n", encoding="utf-8")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-m", "init")
    return repo


def script(*lines: str) -> CheckCommand:
    return CheckCommand("check", (sys.executable, "-c", "\n".join(lines)))


def change_read_restore(target: str) -> CheckCommand:
    return script(
        "import os",
        f"p = r'{target}'",
        "st = os.stat(p)",
        "original = open(p, 'rb').read()",
        "open(p, 'wb').write(b'TAMPERED-DURING-THE-CHECK\\n')",
        "assert open(p, 'rb').read() == b'TAMPERED-DURING-THE-CHECK\\n'",
        "open(p, 'wb').write(original)",
        "os.utime(p, (st.st_atime, st.st_mtime))",
    )


class Fixed:
    def __init__(self, observation: Observation) -> None:
        self._observation = observation

    def start(self) -> None:
        return None

    def stop(self) -> Observation:
        return self._observation


def report(title: str, capture) -> None:
    say(f"  {title}")
    say(f"    endpoints (the reviewed authority): {capture.summary['tree_identity']['binding']}"
        f"  identical={capture.summary['tree_identity']['identical']}")
    say(f"    interval  (the new authority):      {capture.boundary.verdict.value}")
    for violation in capture.boundary.violations:
        say(f"      violation: {violation}")
    say(f"    evidence_valid={capture.summary['evidence_valid']}  "
        f"all_passed={capture.summary['all_passed']}  exit={capture.exit_code}")
    say(f"    verdict: {capture.summary['verdict']}")
    say()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    say("F-14, FIRST INDEPENDENT REVIEW — a change that undoes itself is still a change")
    say("=" * 78)
    say(f"repaired tree: {git(REPO, 'rev-parse', 'HEAD').strip()}")
    say(f"python:        {sys.version.split()[0]}")
    say()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        say("[1] THE FINDING — a clean tracked file, changed, read, restored")
        repo = make_repo(root, "one")
        report("bytes, size and mtime all put back before the check exits",
               run_capture(repo, [change_read_restore("a.txt")], root / "s1"))

        say("[2] AN ALREADY DIRTY TRACKED FILE — same treatment")
        repo2 = make_repo(root, "two")
        (repo2 / "a.txt").write_text("dirty before the capture\n", encoding="utf-8")
        report("the tree was dirty at both ends, and identically so",
               run_capture(repo2, [change_read_restore("a.txt")], root / "s2"))

        say("[3] AN UNTRACKED FILE — same treatment")
        repo3 = make_repo(root, "three")
        (repo3 / "u.txt").write_text("untracked\n", encoding="utf-8")
        report("covered by the identity through its per-path digest",
               run_capture(repo3, [change_read_restore("u.txt")], root / "s3"))

        say("[4] A FILE CREATED, READ AND DELETED INSIDE THE RUN")
        repo4 = make_repo(root, "four")
        report("in NEITHER fingerprint; only the stream ever saw it",
               run_capture(repo4, [script(
                   "import os",
                   "open('ghost.txt', 'w', encoding='utf-8').write('here\\n')",
                   "assert open('ghost.txt', encoding='utf-8').read() == 'here\\n'",
                   "os.remove('ghost.txt')")], root / "s4"))

        say("[5] AN EXTERNAL PROCESS — not the check, and it restores itself")
        repo5 = make_repo(root, "five")
        ready, go = root / "ready", root / "go"

        def meddle() -> None:
            while not ready.exists():
                time.sleep(0.01)
            target = repo5 / "a.txt"
            stat = target.stat()
            original = target.read_bytes()
            target.write_bytes(b"TAMPERED-FROM-OUTSIDE\n")
            target.write_bytes(original)
            os.utime(target, (stat.st_atime, stat.st_mtime))
            go.write_text("go", encoding="utf-8")

        meddler = threading.Thread(target=meddle)
        meddler.start()
        try:
            capture5 = run_capture(repo5, [script(
                "import os, time",
                f"open(r'{ready}', 'w').close()",
                f"while not os.path.exists(r'{go}'):",
                "    time.sleep(0.01)")], root / "s5")
        finally:
            go.write_text("go", encoding="utf-8")
            meddler.join(timeout=30)
        report("the check itself wrote nothing to the tree", capture5)

        say("[6] FAIL CLOSED — an observer that is not there")
        repo6 = make_repo(root, "six")
        report("no mechanism is not 'nothing happened'",
               run_capture(repo6, [script("pass")], root / "s6",
                           observer=lambda _: Fixed(Observation(
                               False, False, (), "none", "no observer on this platform"))))

        say("[7] FAIL CLOSED — a stream that overflowed")
        repo7 = make_repo(root, "seven")
        report("events were dropped, so an empty list proves nothing",
               run_capture(repo7, [script("pass")], root / "s7",
                           observer=lambda _: Fixed(Observation(
                               True, False, (), "ReadDirectoryChangesW(recursive)",
                               "the change buffer overflowed; events were lost"))))

        say("[8] NO FALSE POSITIVES — a git-ignored cache written during a check")
        repo8 = make_repo(root, "eight")
        (repo8 / ".gitignore").write_text(".mypy_cache/\n", encoding="utf-8")
        git(repo8, "add", ".gitignore")
        git(repo8, "commit", "-m", "ignore the cache")
        report("ignored paths were never part of the covered set",
               run_capture(repo8, [script(
                   "import os",
                   "os.makedirs('.mypy_cache', exist_ok=True)",
                   "open('.mypy_cache/data.json', 'w', encoding='utf-8').write('{}\\n')")],
                   root / "s8"))

        say("[9] NO FALSE POSITIVES — an explicitly authorised output area")
        repo9 = make_repo(root, "nine")
        build = script(
            "import os",
            "os.makedirs('build-output', exist_ok=True)",
            "open('build-output/report.txt', 'w', encoding='utf-8').write('x\\n')",
            "os.remove('build-output/report.txt')",
            "os.rmdir('build-output')")
        report("declared allowed: created and removed, and not a violation",
               run_capture(repo9, [build], root / "s9",
                           allowed_writes=("build-output/",)))
        report("the SAME writes without the authorisation",
               run_capture(repo9, [build], root / "s9b"))

        say("[10] A STABLE RUN STILL PRODUCES EVIDENCE")
        repo10 = make_repo(root, "ten")
        (repo10 / "a.txt").write_text("dirty but still\n", encoding="utf-8")
        (repo10 / "u.txt").write_text("untracked but still\n", encoding="utf-8")
        report("dirty at both ends, quiet in between",
               run_capture(repo10, [script("print('quiet')")], root / "s10"))

        say("[11] THE OBSERVER ITSELF — the undo is in the stream")
        watched = root / "watched"
        watched.mkdir()
        (watched / "a.txt").write_text("original\n", encoding="utf-8")
        stat = (watched / "a.txt").stat()
        observer = create_write_observer(watched)
        observer.start()
        (watched / "a.txt").write_bytes(b"TAMPERED\n")
        (watched / "a.txt").write_bytes(b"original\n")
        os.utime(watched / "a.txt", (stat.st_atime, stat.st_mtime))
        observation = observer.stop()
        say(f"    mechanism:  {observation.mechanism}")
        say(f"    available={observation.available} complete={observation.complete}")
        restored = (watched / "a.txt").read_bytes() == b"original" + bytes([10])
        say(f"    file is byte-identical again: {restored}")
        for event in observation.events:
            say(f"      {event.action}: {event.path}")
        say(f"    barrier removed: {not (watched / '.gnosis-capture-barrier').exists()}")
        say()

    say("-" * 78)
    say("source of this transcript, verbatim, so it can be re-run:")
    say("-" * 78)
    for line in Path(__file__).read_text(encoding="utf-8").splitlines():
        say(f"| {line}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
