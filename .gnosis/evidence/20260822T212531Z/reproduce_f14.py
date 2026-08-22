"""F-14 reproduced against the repaired tree, and the repair exercised.

Run:  PYTHONUTF8=1 .venv/Scripts/python.exe <this file> --out <transcript>

Self-contained and read-only with respect to the repository: every tree
it builds is a throwaway git repo in the system temp directory. The only
thing it reads from the real repo is its own content identity, at the
end, and only to print digests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
REPO = Path(r"C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi")
sys.path.insert(0, str(REPO / "src"))

from gnosis.kernel.evidence_capture import (  # noqa: E402
    CheckCommand,
    TreeIdentity,
    probe_tree_identity,
    run_capture,
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


def old_bundle_digest(repo: Path) -> str:
    """Exactly what the pre-ADR-0026 bundle recorded about the tree."""
    head = git(repo, "rev-parse", "HEAD")
    status = git(repo, "status", "--porcelain")
    return hashlib.sha256((head + status).encode("utf-8")).hexdigest()


def python_check(source: str) -> CheckCommand:
    return CheckCommand("check", (sys.executable, "-c", source))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    say("F-14 REPRODUCTION — a name is not a content")
    say("=" * 72)
    say(f"repaired tree: {git(REPO, 'rev-parse', 'HEAD').strip()}")
    say(f"python:        {sys.version.split()[0]}")
    say()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        say("[1] THE FINDING — two dirty trees, one status, different bytes")
        repo = make_repo(root, "one")
        (repo / "a.txt").write_text("AAAA\n", encoding="utf-8")
        status_a, stat_a = git(repo, "status", "--porcelain"), git(repo, "diff", "--stat")
        old_a, new_a = old_bundle_digest(repo), probe_tree_identity(repo)
        (repo / "a.txt").write_text("BBBB\n", encoding="utf-8")
        status_b, stat_b = git(repo, "status", "--porcelain"), git(repo, "diff", "--stat")
        old_b, new_b = old_bundle_digest(repo), probe_tree_identity(repo)

        say(f"  tree A: a.txt = 'AAAA'   status: {status_a.strip()!r}")
        say(f"  tree B: a.txt = 'BBBB'   status: {status_b.strip()!r}")
        say(f"  git status identical:     {status_a == status_b}")
        say(f"  git diff --stat identical:{stat_a == stat_b}   ({stat_a.strip()!r})")
        say(f"  OLD bundle digest A:      {old_a}")
        say(f"  OLD bundle digest B:      {old_b}")
        say(f"  OLD identical:            {old_a == old_b}   <- F-14: two trees, one bundle")
        say(f"  NEW identity A:           {new_a.digest}")
        say(f"  NEW identity B:           {new_b.digest}")
        say(f"  NEW identical:            {new_a.digest == new_b.digest}   <- the repair")
        say(f"  status_sha256 identical:  "
            f"{new_a.fingerprint['status_sha256'] == new_b.fingerprint['status_sha256']}"
            "   (the status really is the same; that was never the question)")
        say(f"  patch_sha256 identical:   "
            f"{new_a.fingerprint['patch_sha256'] == new_b.fingerprint['patch_sha256']}")
        say()

        say("[2] AN UNTRACKED FILE IS COVERED WITHOUT BEING DISCLOSED")
        repo2 = make_repo(root, "two")
        (repo2 / "u.txt").write_text("SECRET-CONTENT-9f3a\n", encoding="utf-8")
        status_c = git(repo2, "status", "--porcelain")
        identity_c = probe_tree_identity(repo2)
        (repo2 / "u.txt").write_text("SECRET-CONTENT-0000\n", encoding="utf-8")
        status_d = git(repo2, "status", "--porcelain")
        identity_d = probe_tree_identity(repo2)
        payload = json.dumps(identity_c.to_dict())
        say(f"  status identical:         {status_c == status_d}  ({status_c.strip()!r})")
        say(f"  identity identical:       {identity_c.digest == identity_d.digest}")
        say(f"  path present in payload:  {'u.txt' in payload}")
        say(f"  bytes present in payload: {'SECRET-CONTENT-9f3a' in payload}")
        say(f"  recorded as:              {identity_c.fingerprint['untracked']['u.txt']}")
        say()

        say("[3] A TRACKED FILE TOUCHED DURING A CHECK — capture refused")
        repo3 = make_repo(root, "three")
        (repo3 / "a.txt").write_text("dirty\n", encoding="utf-8")
        cap3 = run_capture(
            repo3, [python_check("open('a.txt','a',encoding='utf-8').write('more\\n')")],
            root / "s3")
        say(f"  binding:        {cap3.binding.verdict.value}")
        say(f"  drift:          {list(cap3.binding.drift)}")
        say(f"  checks:         {cap3.checks_verdict.value} "
            f"(the check itself exited {cap3.checks[0].exit_code})")
        say(f"  evidence_valid: {cap3.evidence_valid}")
        say(f"  all_passed:     {cap3.summary['all_passed']}   "
            f"checks_all_zero_exit: {cap3.summary['checks_all_zero_exit']}")
        say(f"  exit_code:      {cap3.exit_code}")
        say(f"  verdict:        {cap3.summary['verdict']}")
        say()

        say("[4] AN UNTRACKED FILE TOUCHED DURING A CHECK — capture refused")
        repo4 = make_repo(root, "four")
        (repo4 / "u.txt").write_text("before\n", encoding="utf-8")
        cap4 = run_capture(
            repo4, [python_check("open('u.txt','w',encoding='utf-8').write('after\\n')")],
            root / "s4")
        say(f"  binding:        {cap4.binding.verdict.value}")
        say(f"  drift:          {list(cap4.binding.drift)}")
        say(f"  exit_code:      {cap4.exit_code}")
        say()

        say("[5] A BROKEN IDENTITY PROBE — nothing runs, and it fails closed")
        repo5 = make_repo(root, "five")
        broken = TreeIdentity(False, None, {"is_repo": True, "probe_failed": "git timed out"},
                              "git probe failed: git timed out")
        cap5 = run_capture(
            repo5, [python_check("open('ran.txt','w',encoding='utf-8').write('x')")],
            root / "s5", identity=lambda _: broken)
        say(f"  binding:        {cap5.binding.verdict.value}")
        say(f"  checks run:     {len(cap5.checks)}")
        say(f"  side effect:    ran.txt exists = {(repo5 / 'ran.txt').exists()}")
        say(f"  checks_verdict: {cap5.checks_verdict.value}")
        say(f"  exit_code:      {cap5.exit_code}")
        say(f"  verdict:        {cap5.summary['verdict']}")
        say()

        say("[6] A BUNDLE WRITTEN INSIDE THE TREE IT MEASURES — refuses itself")
        repo6 = make_repo(root, "six")
        cap6 = run_capture(repo6, [python_check("pass")],
                           repo6 / ".gnosis" / "evidence" / "run")
        say(f"  staged outside: {cap6.summary['bundle_staged_outside_repo']}")
        say(f"  binding:        {cap6.binding.verdict.value}")
        say(f"  exit_code:      {cap6.exit_code}   <- why staging lives outside the repo")
        say()

    say("[7] THIS REPOSITORY, AS THE CAPTURE SEES IT")
    identity = probe_tree_identity(REPO)
    say(f"  available:      {identity.available}")
    say(f"  head_sha:       {identity.fingerprint['head_sha']}")
    say(f"  digest:         {identity.digest}")
    for path, digest in sorted(identity.fingerprint["untracked"].items()):
        say(f"  untracked:      {digest}  {path}")
    say("  (pre-existing untracked entries are identified by hash; their")
    say("   contents appear nowhere in the bundle)")
    say()

    say("-" * 72)
    say("source of this transcript, verbatim, so it can be re-run:")
    say("-" * 72)
    for line in Path(__file__).read_text(encoding="utf-8").splitlines():
        say(f"| {line}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
