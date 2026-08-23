"""Try to break the ADR-0026 boundary the way the second review says it can.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/probe_f14_boundary.py --out <file>

Committed so the claim can be re-run rather than read. Read-only with respect
to this repository: every tree it builds is a throwaway git repo in the system
temp directory.

Six cases, in three groups.

OBSERVATION ONLY (the reviewed design, reconstructed with a lock that
claims to be enforced and locks nothing):

  A0  an independent process keeps a raw write handle open across the
      whole capture, never flushes, and closes only after stop()
  B0  the same through a writable memory-mapped view, never flushed

PREVENTION IN PLACE (the repaired design):

  A1  the same open handle, taken BEFORE the capture: the boundary
      cannot be established and nothing runs
  B1  the same for the mapping
  A2  the CHECK ITSELF tries to open a covered input for writing
  B2  the CHECK ITSELF tries to map a covered input writable

Every ordering is a handshake on a pipe. There is not one sleep in it:
the mutation is sent after the PRE fingerprint has been acknowledged and
before any check starts, and the restore is sent after the checks and
acknowledged before the POST fingerprint.

Each case separates, as the review asked: whether the mutation was
observable BY THE CHECK, whether PRE == POST, whether a notification
arrived at all, the boundary verdict, and evidence_valid.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from gnosis.kernel.evidence_capture import (  # noqa: E402
    CheckCommand,
    probe_tree_identity,
    run_capture,
)
from gnosis.kernel.input_lock import LockOutcome  # noqa: E402

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
    (repo / "a.txt").write_text("original-content-of-the-covered-file\n", encoding="utf-8")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-m", "init")
    return repo


class HollowLock:
    """Claims the inputs are protected and protects nothing.

    This is the reviewed design expressed as a lock: observation only.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def acquire(self, paths):  # noqa: ANN001, ANN201
        return LockOutcome(True, 0, (), "none (observation only)")

    def release(self) -> None:
        return None


class Meddler:
    """The other process, driven over its stdin/stdout pipes."""

    def __init__(self, mode: str, target: Path) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(HERE / "probe_f14_meddler.py"), mode, str(target)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.expect("READY")

    def send(self, command: str) -> str:
        assert self.process.stdin is not None
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()
        return self.read()

    def read(self) -> str:
        assert self.process.stdout is not None
        return self.process.stdout.readline().strip()

    def expect(self, prefix: str) -> str:
        line = self.read()
        if not line.startswith(prefix):
            raise RuntimeError(f"expected {prefix}, got {line!r}")
        return line

    def close(self) -> str:
        line = self.send("CLOSE")
        self.process.wait(timeout=30)
        return line


READER = CheckCommand("check", (
    sys.executable, "-c",
    "import hashlib;print(hashlib.sha256(open('a.txt','rb').read()).hexdigest())"))


def tampering_check(mode: str) -> CheckCommand:
    """A check that tries the ABA on its own inputs and reports the result."""
    if mode == "handle":
        source = (
            "import hashlib, os\n"
            "try:\n"
            "    fd = os.open('a.txt', os.O_RDWR | os.O_BINARY)\n"
            "except OSError as exc:\n"
            "    print('REFUSED', type(exc).__name__, exc.errno)\n"
            "else:\n"
            "    original = os.read(fd, 1 << 20)\n"
            "    os.lseek(fd, 0, os.SEEK_SET); os.write(fd, b'TAMPERED')\n"
            "    print('TAMPERED', hashlib.sha256(open('a.txt','rb').read()).hexdigest())\n"
            "    os.lseek(fd, 0, os.SEEK_SET); os.write(fd, original); os.close(fd)\n")
    else:
        source = (
            "import hashlib, mmap\n"
            "try:\n"
            "    handle = open('a.txt', 'r+b')\n"
            "except OSError as exc:\n"
            "    print('REFUSED', type(exc).__name__, exc.errno)\n"
            "else:\n"
            "    view = mmap.mmap(handle.fileno(), 0)\n"
            "    original = bytes(view[:])\n"
            "    view[0:8] = b'TAMPERED'\n"
            "    print('TAMPERED', hashlib.sha256(open('a.txt','rb').read()).hexdigest())\n"
            "    view[:] = original\n")
    return CheckCommand("check", (sys.executable, "-c", source))


def show(capture, original_digest, modified_digest, check_saw, closed) -> bool:
    say(f"  digest before                     : {original_digest}")
    say(f"  digest after MODIFY (fresh read)  : {modified_digest}")
    say(f"  what the CHECK reported           : {check_saw or '(no check ran)'}")
    consumed = bool(modified_digest) and check_saw == modified_digest
    say(f"  -> a check consumed mutated bytes : {consumed}")
    if closed:
        say(f"  digest after CLOSE                : {closed}")
    say(f"  PRE == POST                       : "
        f"{capture.summary['tree_identity']['identical']}")
    say(f"  binding                           : "
        f"{capture.summary['tree_identity']['binding']}")
    say(f"  notification for a.txt received   : "
        f"{any('a.txt' in v for v in capture.boundary.violations)}")
    say(f"  boundary                          : {capture.boundary.verdict.value}")
    say(f"  violations                        : {list(capture.boundary.violations)}")
    say(f"  protection                        : {dict(capture.boundary.protection)}")
    say(f"  checks that ran                   : {len(capture.checks)}")
    say(f"  evidence_valid                    : {capture.summary['evidence_valid']}")
    say(f"  exit_code                         : {capture.exit_code}")
    broke = consumed and bool(capture.summary["evidence_valid"])
    say(f"  VERDICT                           : "
        f"{'BROKEN - mutated bytes consumed inside a valid bundle' if broke else 'HELD'}")
    say()
    return broke


def external_case(title: str, mode: str, root: Path, name: str, *, hollow: bool) -> bool:
    """An independent process holds the write handle across the capture."""
    say(f"### {title}")
    repo = make_repo(root, name)
    target = repo / "a.txt"
    original_digest = hashlib.sha256(target.read_bytes()).hexdigest()

    meddler = Meddler(mode, target)
    opened = meddler.send("OPEN")
    say(f"  external open                     : {opened}")
    state: dict[str, str | None] = {"modified": None}
    calls = {"n": 0}

    def identity(path: Path):
        index = calls["n"]
        calls["n"] += 1
        if index == 0:
            pre = probe_tree_identity(path)
            if opened.startswith("OPENED"):
                state["modified"] = meddler.send("MODIFY").split()[1]
            return pre
        if opened.startswith("OPENED"):
            meddler.send("RESTORE")
        return probe_tree_identity(path)

    kwargs = {"input_lock": (lambda _: HollowLock(_))} if hollow else {}
    try:
        capture = run_capture(repo, [READER], root / f"s-{name}",
                              identity=identity, **kwargs)
    finally:
        closed = meddler.close()

    check_saw = capture.checks[0].tail.strip() if capture.checks else ""
    return show(capture, original_digest, state["modified"], check_saw,
                closed.split()[1] if len(closed.split()) > 1 else "")


def check_case(title: str, mode: str, root: Path, name: str) -> bool:
    """The check itself is the attacker, and the lock is already in place."""
    say(f"### {title}")
    repo = make_repo(root, name)
    original_digest = hashlib.sha256((repo / "a.txt").read_bytes()).hexdigest()
    capture = run_capture(repo, [tampering_check(mode)], root / f"s-{name}")
    reported = capture.checks[0].tail.strip() if capture.checks else ""
    after = hashlib.sha256((repo / "a.txt").read_bytes()).hexdigest()
    say(f"  the check reported                : {reported}")
    say(f"  file digest afterwards            : {after}")
    say(f"  -> bytes never changed            : {after == original_digest}")
    say(f"  PRE == POST                       : "
        f"{capture.summary['tree_identity']['identical']}")
    say(f"  boundary                          : {capture.boundary.verdict.value}")
    say(f"  protection                        : {dict(capture.boundary.protection)}")
    say(f"  check exit code                   : {capture.checks[0].exit_code}")
    say(f"  evidence_valid                    : {capture.summary['evidence_valid']}")
    say(f"  exit_code                         : {capture.exit_code}")
    broke = reported.startswith("TAMPERED")
    say(f"  VERDICT                           : "
        f"{'BROKEN - the check mutated its own inputs' if broke else 'HELD - the write was refused'}")
    say()
    return broke


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    say("F-14 — SECOND INDEPENDENT REVIEW: breaking, then closing, the boundary")
    say("=" * 78)
    say(f"tree:   {git(REPO, 'rev-parse', 'HEAD').strip()}")
    say(f"python: {sys.version.split()[0]}")
    say()
    say("GROUP 1 — OBSERVATION ONLY (the reviewed design: a lock that claims")
    say("          enforcement and locks nothing, so the write stream is the")
    say("          only authority)")
    say()

    broke: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        if external_case("A0 — open write handle, no flush, closed after stop()",
                         "handle", root, "a0", hollow=True):
            broke.append("A0")
        if external_case("B0 — writable memory-mapped view, never flushed",
                         "mmap", root, "b0", hollow=True):
            broke.append("B0")

        say("GROUP 2 — PREVENTION IN PLACE, attacker already holding the handle")
        say()
        if external_case("A1 — the same open handle, taken before the capture",
                         "handle", root, "a1", hollow=False):
            broke.append("A1")
        if external_case("B1 — the same mapping, taken before the capture",
                         "mmap", root, "b1", hollow=False):
            broke.append("B1")

        say("GROUP 3 — PREVENTION IN PLACE, the check itself is the attacker")
        say()
        if check_case("A2 — the check opens a covered input for writing",
                      "handle", root, "a2"):
            broke.append("A2")
        if check_case("B2 — the check maps a covered input writable",
                      "mmap", root, "b2"):
            broke.append("B2")

    say("=" * 78)
    say(f"BROKEN: {', '.join(broke) if broke else 'none'}")
    say("Expected: A0 held (a raw write does notify), B0 BROKEN (a mapped write")
    say("need not), A1/B1/A2/B2 held once the inputs are unwritable.")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
