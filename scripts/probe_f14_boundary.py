"""Try to break the F-14 boundary the way three reviews said it could break.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/probe_f14_boundary.py --out <file>

Committed so the claim can be re-run rather than read. Read-only with
respect to this repository: every tree it builds is a throwaway git repo
in the system temp directory, and every ordering is a handshake on a
pipe — there is not one sleep in the synchronisation.

Ten cases, in four groups.

OBSERVATION ONLY — the design the second review broke, reconstructed here
with a lock that claims enforcement and locks nothing, so the write
stream is the only authority:

  A0  a check writes a covered input with an ordinary handle, reads the
      change, and puts the original bytes back
  B0  the same through a writable memory-mapped view

PREVENTION, the attacker already holding something:

  A1  an independent process holds a raw write handle when the capture starts
  B1  an independent process holds a writable mapping
  A3  a writable SECTION whose file handle has been closed
  A4  the same with the mapping handle closed too: only the view remains
  A5  the same with a duplicated file handle kept alive instead

PREVENTION, the check itself is the attacker:

  A2  the check opens a covered input for writing
  B2  the check maps a covered input writable

PREVENTION, with the PATH as the attacker:

  J   a junction ABOVE a covered input, retargeted to another directory
      on the same volume while a handle on the object is held

Each case prints what the review asked to see separately: whether the
mutation was observable BY THE CHECK, whether the endpoints agree,
whether a notification arrived, the boundary verdict, and evidence_valid.
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

from gnosis.kernel.evidence_capture import CheckCommand, run_capture  # noqa: E402
from gnosis.kernel.input_lock import (  # noqa: E402
    LockOutcome,
    VolumeCapabilities,
    WindowsInputLock,
)

MEDDLER = HERE / "probe_f14_meddler.py"
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

    The reviewed design, expressed as a lock: observation only.
    """

    def acquire(self, paths: list[str]) -> LockOutcome:
        return LockOutcome(True, 0, (), "none (observation only)",
                           volume=VolumeCapabilities(True, "fixed", "NTFS"))

    def release(self) -> None:
        return None


class Meddler:
    """The other process, driven over its stdin/stdout pipes."""

    def __init__(self, mode: str, target: Path) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(MEDDLER), mode, str(target)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.expect("READY")

    def read(self) -> str:
        assert self.process.stdout is not None
        return self.process.stdout.readline().strip()

    def send(self, command: str) -> str:
        assert self.process.stdin is not None
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()
        return self.read()

    def expect(self, prefix: str) -> str:
        line = self.read()
        if not line.startswith(prefix):
            raise RuntimeError(f"expected {prefix}, got {line!r}")
        return line

    def close(self) -> None:
        try:
            self.send("CLOSE")
        finally:
            assert self.process.stdin is not None
            self.process.stdin.close()
            self.process.wait(timeout=30)


def tampering_check(mode: str) -> CheckCommand:
    """A check that tries the ABA on its own inputs and reports the result."""
    if mode == "handle":
        source = (
            "import hashlib, os\n"
            "try:\n"
            "    fd = os.open('a.txt', os.O_RDWR | os.O_BINARY)\n"
            "except OSError as exc:\n"
            "    print('REFUSED', type(exc).__name__)\n"
            "else:\n"
            "    original = os.read(fd, 1 << 20)\n"
            "    os.lseek(fd, 0, os.SEEK_SET)\n"
            "    os.write(fd, b'TAMPERED')\n"
            "    print('TAMPERED', hashlib.sha256(open('a.txt','rb').read()).hexdigest())\n"
            "    os.lseek(fd, 0, os.SEEK_SET)\n"
            "    os.write(fd, original)\n"
            "    os.close(fd)\n")
    else:
        source = (
            "import hashlib, mmap\n"
            "try:\n"
            "    handle = open('a.txt', 'r+b')\n"
            "except OSError as exc:\n"
            "    print('REFUSED', type(exc).__name__)\n"
            "else:\n"
            "    view = mmap.mmap(handle.fileno(), 0)\n"
            "    original = bytes(view[:])\n"
            "    view[0:8] = b'TAMPERED'\n"
            "    print('TAMPERED', hashlib.sha256(open('a.txt','rb').read()).hexdigest())\n"
            "    view[:] = original\n")
    return CheckCommand("check", (sys.executable, "-c", source))


def report(capture, before: str, after: str, extra: str = "") -> bool:
    reported = capture.checks[0].tail.strip() if capture.checks else "(no check ran)"
    tampered = reported.startswith("TAMPERED")
    if extra:
        say(f"  {extra}")
    say(f"  what the CHECK reported           : {reported}")
    say(f"  -> a check consumed mutated bytes : {tampered}")
    say(f"  bytes unchanged at the end        : {before == after}")
    say(f"  PRE == POST                       : "
        f"{capture.summary['tree_identity']['identical']}")
    say(f"  notification for a.txt received   : "
        f"{any('a.txt' in item for item in capture.boundary.violations)}")
    say(f"  boundary                          : {capture.boundary.verdict.value}")
    say(f"  violations                        : {list(capture.boundary.violations)}")
    say(f"  protection.enforced               : "
        f"{dict(capture.boundary.protection).get('enforced')}")
    say(f"  checks that ran                   : {len(capture.checks)}")
    say(f"  evidence_valid                    : {capture.summary['evidence_valid']}")
    say(f"  exit_code                         : {capture.exit_code}")
    broke = tampered and bool(capture.summary["evidence_valid"])
    say(f"  VERDICT                           : "
        f"{'BROKEN - mutated bytes consumed inside a valid bundle' if broke else 'HELD'}")
    say()
    return broke


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_case(title: str, mode: str, root: Path, name: str, *, hollow: bool) -> bool:
    """The check itself is the attacker."""
    say(f"### {title}")
    repo = make_repo(root, name)
    before = digest(repo / "a.txt")
    kwargs = {"input_lock": (lambda _: HollowLock())} if hollow else {}
    capture = run_capture(repo, [tampering_check(mode)], root / f"s-{name}", **kwargs)
    return report(capture, before, digest(repo / "a.txt"))


def holder_case(title: str, mode: str, root: Path, name: str) -> bool:
    """Somebody else is already holding something writable."""
    say(f"### {title}")
    repo = make_repo(root, name)
    before = digest(repo / "a.txt")
    meddler = Meddler(mode, repo / "a.txt")
    try:
        opened = meddler.send("OPEN")
        say(f"  the other process reports         : {opened}")
        capture = run_capture(
            repo,
            [CheckCommand("check", (sys.executable, "-c",
                                    "open('ran.txt','w',encoding='utf-8').write('x')"))],
            root / f"s-{name}")
    finally:
        meddler.close()
    ran = (repo / "ran.txt").exists()
    return report(capture, before, digest(repo / "a.txt"),
                  extra=f"the check's side effect happened   : {ran}")


def junction_case(root: Path) -> bool:
    """J — the sixth review's attack: retarget the ancestor, not the file."""
    say("### J — an ancestor junction, retargeted while the object stays locked")
    repo = make_repo(root, "j")
    first, second = root / "dirA", root / "dirB"
    first.mkdir()
    second.mkdir()
    (first / "under.py").write_text("ORIGINAL-A\n", encoding="utf-8")
    (second / "under.py").write_text("SWAPPED-B\n", encoding="utf-8")
    link = repo / "linked"
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(first)],
                          capture_output=True, text=True, errors="replace", check=False)
    if made.returncode != 0:
        say("  junctions are not available here; case skipped")
        say()
        return False

    try:
        lock = WindowsInputLock(repo)
        outcome = lock.acquire(["a.txt", "linked/under.py"])
        say(f"  lock over linked/under.py         : enforced={outcome.enforced}")
        for item in outcome.refused:
            say(f"    refused: {item}")

        # Is the attack real on this platform? Hold the object and try.
        keeper = WindowsInputLock(repo)
        keeper.acquire(["a.txt"])
        handle = open(first / "under.py", "rb")  # noqa: SIM115
        try:
            link.rmdir()
            retargeted = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(second)],
                capture_output=True, text=True, errors="replace", check=False)
            through = (link / "under.py").read_text(encoding="utf-8").strip()
            link.rmdir()
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(first)],
                           capture_output=True, text=True, errors="replace", check=False)
            restored = (link / "under.py").read_text(encoding="utf-8").strip()
        finally:
            handle.close()
            keeper.release()
            lock.release()

        say(f"  retarget while the file is held   : {retargeted.returncode == 0}")
        say(f"  lexical path then reads           : {through}")
        say(f"  after restoring, it reads         : {restored}")
        say(f"  -> the OS does NOT prevent it     : {through == 'SWAPPED-B'}")

        capture = run_capture(
            repo,
            [CheckCommand("check", (sys.executable, "-c",
                                    "open('ran.txt','w',encoding='utf-8').write('x')"))],
            root / "s-j", input_lock=lambda _: _LockOverPaths(repo,
                                                              ["a.txt",
                                                               "linked/under.py"]))
        say(f"  boundary                          : {capture.boundary.verdict.value}")
        say(f"  checks that ran                   : {len(capture.checks)}")
        say(f"  evidence_valid                    : {capture.summary['evidence_valid']}")
        say(f"  exit_code                         : {capture.exit_code}")
        broke = bool(capture.checks) and bool(capture.summary["evidence_valid"])
        say(f"  VERDICT                           : "
            f"{'BROKEN - a check ran over a redirectable path' if broke else 'HELD'}")
        say()
        return broke
    finally:
        if link.exists():
            link.rmdir()


class _LockOverPaths:
    """The real lock, over a caller-chosen set of covered paths."""

    def __init__(self, root: Path, paths: list[str]) -> None:
        self._inner = WindowsInputLock(root)
        self._paths = paths

    def acquire(self, paths: list[str]) -> LockOutcome:
        return self._inner.acquire(self._paths)

    def release(self) -> None:
        self._inner.release()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    say("F-14 — trying to break the boundary, across three reviews")
    say("=" * 78)
    say(f"tree:   {git(REPO, 'rev-parse', 'HEAD').strip()}")
    say(f"python: {sys.version.split()[0]}")
    say()

    broke: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        say("GROUP 1 — OBSERVATION ONLY (prevention disabled: the second")
        say("          review's world, where watching is the whole boundary)")
        say()
        if check_case("A0 — the check writes, reads and restores with an ordinary handle",
                      "handle", root, "a0", hollow=True):
            broke.append("A0")
        if check_case("B0 — the same through a writable memory-mapped view",
                      "mmap", root, "b0", hollow=True):
            broke.append("B0")

        say("GROUP 2 — PREVENTION, with the attacker already holding something")
        say()
        for name, mode, title in (
            ("a1", "handle", "A1 — a raw write handle, taken before the capture"),
            ("b1", "mmap", "B1 — a writable mapping, taken before the capture"),
            ("a3", "section", "A3 — a writable SECTION with the file handle closed"),
            ("a4", "section-orphan", "A4 — the same with the mapping handle closed too"),
            ("a5", "section-dup", "A5 — the same with a duplicated handle kept alive"),
        ):
            if holder_case(title, mode, root, name):
                broke.append(name.upper())

        say("GROUP 3 — PREVENTION, with the check itself as the attacker")
        say()
        if check_case("A2 — the check opens a covered input for writing",
                      "handle", root, "a2", hollow=False):
            broke.append("A2")
        if check_case("B2 — the check maps a covered input writable",
                      "mmap", root, "b2", hollow=False):
            broke.append("B2")

        say("GROUP 4 — PREVENTION, with the PATH as the attacker")
        say()
        if junction_case(root):
            broke.append("J")

    say("=" * 78)
    say(f"BROKEN: {', '.join(broke) if broke else 'none'}")
    say("Expected: A0 held (a raw write does notify), B0 BROKEN (a mapped write")
    say("need not — that is why prevention exists), everything in groups 2 and 3")
    say("held once the covered inputs are unwritable, and J held once a covered")
    say("input reached through a junction is refused before any check runs.")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
