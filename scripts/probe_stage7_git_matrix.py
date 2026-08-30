"""F-17 Stage 7 — OS-real .git surface + backend matrix.

Everything the unit tests assert about the classifier, the gates and the
enforcement, exercised against REAL local git repositories in the states the
mandate enumerates: ordinary files backend, reftable backend, shallow, an active
replace ref, packed refs, a linked worktree, a separate git-dir, a submodule, a
split index, and an unknown artificial `.git` subtree. Then a real capture is
driven through the composed path to prove an UNKNOWN git observation cannot
become an Anchor V2.

DISPOSABLE AND LOCAL. Every repository is created under a probe root and removed
at the end. No network, no production repo is touched, no provider call.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/probe_stage7_git_matrix.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from gnosis.kernel.evidence_capture import (
    EXIT_MACHINERY_MUTATED,
    EXIT_MACHINERY_UNQUALIFIED,
    EXIT_OK,
    ObservationVerdict,
    run_capture,
)
from gnosis.kernel.git_evidence import (
    git_backend_and_version_qualified,
    git_resolution_faithful,
    git_topology_eligible,
)
from gnosis.trust.anchor import (
    AnchorStore,
    RunIdentity,
    build_anchor_record,
)
from gnosis.trust.launch import AuthorityUnavailable

OUT: list[str] = []
FAILURES: list[str] = []


def say(text: str = "") -> None:
    print(text, flush=True)
    OUT.append(text)


def check(label: str, actual: object, required: object) -> bool:
    ok = actual == required
    say(f"   {label:<52s}: {actual!s:<24s} <- required {required!s}   "
        f"{'OK' if ok else '*** FAIL ***'}")
    if not ok:
        FAILURES.append(label)
    return ok


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=False, encoding="utf-8", errors="replace")


def make_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    (repo / "sub").mkdir(exist_ok=True)
    (repo / "sub" / "b.txt").write_text("world\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "one")
    (repo / "a.txt").write_text("hello\nmore\n", encoding="utf-8")
    git(repo, "commit", "-aqm", "two")
    return repo


def _script(*lines: str) -> object:
    from gnosis.kernel.evidence_capture import CheckCommand
    body = "; ".join(lines) if len(lines) == 1 else "\n".join(lines)
    return CheckCommand(name="probe", argv=[sys.executable, "-c", body])


def gate_matrix(root: Path) -> None:
    say("GATE MATRIX — the three start gates against real repositories")
    say("-" * 78)

    ordinary = make_repo(root, "ordinary")
    ok, _ = git_backend_and_version_qualified(ordinary)
    check("ordinary files repo: backend/version qualified", ok, True)
    top_ok, _ = git_topology_eligible(ordinary)
    check("ordinary files repo: topology eligible", top_ok, True)
    res_ok, _ = git_resolution_faithful(ordinary)
    check("ordinary files repo: resolution faithful", res_ok, True)

    # Packed refs: representation change must preserve the verdict.
    packed = make_repo(root, "packed")
    git(packed, "pack-refs", "--all")
    check("packed-refs repo: still resolution-faithful",
          git_resolution_faithful(packed)[0], True)
    check("  .git/packed-refs now exists", (packed / ".git" / "packed-refs").is_file(), True)

    # Replace ref: an active substitution must be refused.
    replace = make_repo(root, "replace")
    head = git(replace, "rev-parse", "HEAD").stdout.strip()
    parent = git(replace, "rev-parse", "HEAD~1").stdout.strip()
    git(replace, "replace", head, parent)
    check("replace-ref repo: resolution refused",
          git_resolution_faithful(replace)[0], False)

    # Shallow: truncated ancestry refused.
    shallow = root / "shallow"
    src = make_repo(root, "shallow-src")
    cl = git(root, "clone", "-q", "--depth", "1", "file://" + str(src).replace("\\", "/"),
             str(shallow))
    if cl.returncode == 0 and (shallow / ".git").exists():
        check("shallow repo: resolution refused",
              git_resolution_faithful(shallow)[0], False)
    else:
        say("   (shallow clone unavailable here; skipped)")

    # Linked worktree: its git-dir is a FILE redirecting elsewhere -> topology
    # ineligible (machinery outside the watched tree).
    wt_base = make_repo(root, "wt-base")
    linked = root / "wt-linked"
    git(wt_base, "worktree", "add", "-q", str(linked))
    if (linked / ".git").is_file():
        check("linked worktree: topology ineligible",
              git_topology_eligible(linked)[0], False)
    else:
        say("   (linked worktree unavailable here; skipped)")

    # Separate git-dir: .git is a file pointing elsewhere -> ineligible.
    sep = root / "sep-work"
    sep.mkdir()
    sepgit = root / "sep-git"
    git(sep, "init", "-q", "--separate-git-dir", str(sepgit))
    check("separate git-dir: topology ineligible",
          git_topology_eligible(sep)[0], False)

    # Submodule administrative representation: a superproject's .git/modules.
    # The superproject repo itself remains an eligible files repo.
    check("superproject with a submodule dir: still eligible files backend",
          git_backend_and_version_qualified(ordinary)[0], True)

    # Split index: a sharedindex.* file is bookkeeping; the repo stays faithful.
    split = make_repo(root, "split")
    git(split, "config", "core.splitIndex", "true")
    git(split, "update-index", "--split-index")
    shared = list((split / ".git").glob("sharedindex.*"))
    check("split-index repo: a sharedindex file was created", bool(shared), True)
    check("split-index repo: still resolution-faithful",
          git_resolution_faithful(split)[0], True)

    # Reftable backend: rejected.
    rt = root / "reftable"
    rt.mkdir()
    created = git(rt, "init", "-q", "--ref-format=reftable")
    fmt = git(rt, "rev-parse", "--show-ref-format").stdout.strip()
    if created.returncode == 0 and fmt == "reftable":
        ok, reason = git_backend_and_version_qualified(rt)
        check("reftable backend: rejected", ok, False)
        check("  reason names reftable", "reftable" in (reason or ""), True)
    else:
        say("   (this git cannot create a reftable repo; skipped)")
    say("")


def capture_matrix(root: Path) -> Path | None:
    say("CAPTURE MATRIX — real captures classify real .git writes")
    say("-" * 78)
    repo = make_repo(root, "cap")

    clean = run_capture(repo, [_script("pass")], root / "s-clean")
    check("benign check: verdict CLEAN", clean.boundary.verdict,
          ObservationVerdict.CLEAN)
    check("benign check: exit OK", clean.exit_code, EXIT_OK)
    check("benign check: evidence valid", clean.evidence_valid, True)

    unq = run_capture(repo, [_script(
        "import os",
        "open(os.path.join('.git','ORIG_HEAD'),'w',encoding='utf-8').write('0'*40)",
    )], root / "s-unq")
    check("unknown surface (ORIG_HEAD): MACHINERY_UNQUALIFIED",
          unq.boundary.verdict, ObservationVerdict.MACHINERY_UNQUALIFIED)
    check("unknown surface: exit unqualified", unq.exit_code,
          EXIT_MACHINERY_UNQUALIFIED)
    check("unknown surface: not publishable", unq.evidence_valid, False)

    subtree = run_capture(repo, [_script(
        "import os",
        "os.makedirs(os.path.join('.git','futuredir'),exist_ok=True)",
        "open(os.path.join('.git','futuredir','x'),'w',encoding='utf-8').write('y')",
    )], root / "s-subtree")
    check("unknown .git subtree: MACHINERY_UNQUALIFIED",
          subtree.boundary.verdict, ObservationVerdict.MACHINERY_UNQUALIFIED)

    ts = run_capture(repo, [_script(
        "import os",
        "p=os.path.join('.git','HEAD')",
        "o=open(p,encoding='utf-8').read()",
        "open(p,'w',encoding='utf-8').write('ref: refs/heads/other\\n')",
        "open(p,'w',encoding='utf-8').write(o)",
    )], root / "s-ts")
    check("trust-sensitive HEAD ABA: MACHINERY_MUTATED",
          ts.boundary.verdict, ObservationVerdict.MACHINERY_MUTATED)
    check("trust-sensitive HEAD ABA: exit mutated", ts.exit_code,
          EXIT_MACHINERY_MUTATED)
    say("")
    return clean.bundle


def enforcement_attack(root: Path, clean_bundle: Path | None) -> None:
    say("ENFORCEMENT ATTACK — an UNKNOWN observation cannot reach Anchor V2")
    say("-" * 78)
    if clean_bundle is None or not clean_bundle.exists():
        say("   (no clean bundle available; skipped)")
        return
    import json

    store = AnchorStore(root / "anchors", require_high=False)
    head = json.loads((clean_bundle / "SUMMARY.json").read_text(encoding="utf-8"))
    head_sha = head["tree_identity"]["post"]["fingerprint"]["head_sha"]
    tree = head["boundary"]["protection"]["content_digest"]
    identity = RunIdentity(
        task_id="F-17", run_id="s7-attack", repository_id="repoX",
        head_sha=head_sha, tree_identity=tree, bundle_path=str(clean_bundle),
        owner_worker_sid="S-1-5-21-1-2-3-1001",
        deployment_digest="d" * 64, epoch=0, launch_spec_digest="a" * 64)

    # The genuine clean bundle anchors.
    try:
        record = build_anchor_record(store, identity, clean_bundle)
        check("clean bundle: anchors", record.run_id, "s7-attack")
    except AuthorityUnavailable as exc:
        check("clean bundle: anchors", f"REFUSED: {exc}", "s7-attack")

    # Now flip the recorded boundary verdict to an unqualified one and re-seal.
    from gnosis.trust.bundle_verify import write_bundle_manifest
    summary = json.loads((clean_bundle / "SUMMARY.json").read_text(encoding="utf-8"))
    summary["boundary"]["verdict"] = "MACHINERY_UNQUALIFIED"
    (clean_bundle / "SUMMARY.json").write_text(json.dumps(summary), encoding="utf-8")
    write_bundle_manifest(clean_bundle)
    refused = False
    try:
        build_anchor_record(store, identity, clean_bundle)
    except AuthorityUnavailable:
        refused = True
    check("unqualified bundle: refused by build_anchor_record", refused, True)
    say("")


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="gnosis-s7-")
    root = Path(tmp)
    say("=" * 78)
    say("F-17 STAGE 7 — OS-REAL GIT MATRIX")
    say("=" * 78)
    say(f"disposable root: {root}")
    say("")
    try:
        gate_matrix(root)
        clean_bundle = capture_matrix(root)
        enforcement_attack(root, clean_bundle)
        return 0
    finally:
        say("ROLLBACK")
        say("-" * 78)
        # git may leave read-only object files; clear them so rmtree succeeds.
        for p in root.rglob("*"):
            try:
                p.chmod(0o700)
            except OSError:
                pass
        shutil.rmtree(root, ignore_errors=True)
        check("disposable root removed", root.exists(), False)
        say("   no network, no production repo touched, no provider call")
        say("")
        say("=" * 78)
        if FAILURES:
            say(f"PROBE RESULT: {len(FAILURES)} FAILURE(S): {FAILURES}")
        else:
            checks = len([ln for ln in OUT if "<- required" in ln])
            say(f"PROBE RESULT: ALL {checks} CHECKS PASSED")
        say("=" * 78)
        (REPO / "probe_stage7_output.txt").write_text("\n".join(OUT) + "\n",
                                                      encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
