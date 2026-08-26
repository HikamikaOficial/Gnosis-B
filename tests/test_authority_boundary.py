"""F-17 BLOCKER C — the OS-enforced authority boundary for the evidence anchor.

The property under test is `worker_write_authority ∩ anchor_write_authority = ∅`,
enforced by Windows Mandatory Integrity Control, not by a role flag or a path:
a MEDIUM-integrity worker (and every child it spawns) is DENIED write to a
HIGH-integrity NO_WRITE_UP AnchorStore, while the HIGH publisher is ALLOWED.

These tests require the test process itself to be HIGH integrity (an elevated
run, the Director's domain) on Windows; they skip otherwise, because the
boundary cannot be demonstrated from a Medium process.
"""
from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from gnosis.kernel.authority import (
    ANCHOR_SCHEMA,
    AnchorRecord,
    AnchorStore,
    AuthorityUnavailable,
    RunIdentity,
    label_high_no_write_up,
    process_integrity,
    publish_anchor,
    run_at_integrity,
    verify_anchored_bundle,
)
from gnosis.kernel.canonical import GENESIS_HASH
from gnosis.kernel.evidence_capture import write_bundle_manifest


def _is_high() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return process_integrity() == "High"
    except AuthorityUnavailable:
        return False


HIGH_ONLY = unittest.skipUnless(
    _is_high(), "needs an elevated (High integrity) Windows process")

SCRATCH_SRC = str(REPO / "src")


def _make_bundle(root: Path, head_sha: str, content_digest: str = "cd0") -> Path:
    """A minimal verify_bundle-able bundle bound to `head_sha`."""
    b = root / "bundle"
    b.mkdir()
    (b / "pytest.stdout.txt").write_text("ok\n", encoding="utf-8")
    summary = {
        "tree_identity": {"post": {"fingerprint": {"head_sha": head_sha}}},
        "boundary": {"protection": {"content_digest": content_digest}},
    }
    (b / "SUMMARY.json").write_text(json.dumps(summary), encoding="utf-8")
    write_bundle_manifest(b)
    return b


def _identity(head_sha: str, run_id: str = "run-1") -> RunIdentity:
    return RunIdentity(task_id="F-17", run_id=run_id, repository_id="repoX",
                       head_sha=head_sha, bundle_path=".gnosis/evidence/x")


class TestTheAnchorRecordChains(unittest.TestCase):
    def test_a_record_serialises_and_digests_stably(self):
        r = AnchorRecord("t", "r", "repo", "head", "tree", "b", "dig", 0, GENESIS_HASH)
        self.assertEqual(r.schema, ANCHOR_SCHEMA)
        self.assertEqual(len(r.digest()), 64)
        self.assertEqual(r.digest(), AnchorRecord(**r.to_dict()).digest())


@HIGH_ONLY
class TestTheStoreIsAppendOnlyAndChained(unittest.TestCase):
    def _store(self, root: Path) -> AnchorStore:
        return AnchorStore(root / "anchors")

    def test_appends_chain_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self._store(Path(tmp))
            seq, prev = s.next_seq_and_prev()
            self.assertEqual((seq, prev), (0, GENESIS_HASH))
            r0 = AnchorRecord("t", "r0", "repo", "h0", "tr", "b0", "d0", 0, GENESIS_HASH)
            s.append(r0)
            seq, prev = s.next_seq_and_prev()
            r1 = AnchorRecord("t", "r1", "repo", "h1", "tr", "b1", "d1", seq, prev)
            s.append(r1)
            self.assertTrue(s.verify_chain())
            self.assertEqual(s.lookup("r1").bundle_digest, "d1")

    def test_a_record_that_does_not_extend_the_chain_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self._store(Path(tmp))
            bad = AnchorRecord("t", "r", "repo", "h", "tr", "b", "d", 5, "deadbeef")
            with self.assertRaises(AuthorityUnavailable):
                s.append(bad)

    def test_editing_a_non_last_record_breaks_the_chain(self):
        # A hash chain protects record N through record N+1's prev pointer.
        with tempfile.TemporaryDirectory() as tmp:
            s = self._store(Path(tmp))
            s.append(AnchorRecord("t", "r0", "repo", "h", "tr", "b", "d0", 0, GENESIS_HASH))
            seq, prev = s.next_seq_and_prev()
            s.append(AnchorRecord("t", "r1", "repo", "h", "tr", "b", "d1", seq, prev))
            self.assertTrue(s.verify_chain())
            lines = s.ledger.read_text(encoding="utf-8").splitlines()
            rec0 = json.loads(lines[0]); rec0["bundle_digest"] = "TAMPERED"
            lines[0] = json.dumps(rec0, sort_keys=True)
            s.ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertFalse(s.verify_chain())

    def test_the_last_records_authenticity_comes_from_the_os_boundary_not_the_chain(self):
        # Declared honestly: editing the LAST record's content is NOT caught by
        # the chain alone (no successor pins it). What stops a worker doing it
        # is the OS boundary — a Medium worker cannot write the ledger at all
        # (TestTheOsAuthorityBoundary). The chain guards logical integrity of
        # earlier records; the OS integrity label guards the head of the log.
        with tempfile.TemporaryDirectory() as tmp:
            s = self._store(Path(tmp))
            s.append(AnchorRecord("t", "r0", "repo", "h", "tr", "b", "d0", 0, GENESIS_HASH))
            lines = s.ledger.read_text(encoding="utf-8").splitlines()
            rec0 = json.loads(lines[0]); rec0["bundle_digest"] = "TAMPERED"
            s.ledger.write_text(json.dumps(rec0, sort_keys=True) + "\n", encoding="utf-8")
            self.assertTrue(s.verify_chain())  # chain alone does not catch it


@HIGH_ONLY
class TestThePublicationProtocol(unittest.TestCase):
    def test_publish_recomputes_the_digest_and_verify_uses_the_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = _make_bundle(root, head_sha="abc123")
            store = AnchorStore(root / "anchors")
            rec = publish_anchor(store, _identity("abc123"), b)
            self.assertEqual(len(rec.bundle_digest), 64)
            # verify_anchored_bundle uses the store's digest, not a caller one
            self.assertTrue(verify_anchored_bundle(store, "run-1", b))

    def test_a_worker_supplied_digest_is_ignored(self):
        # publish_anchor recomputes; a caller cannot inject a false digest.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = _make_bundle(root, head_sha="abc123")
            store = AnchorStore(root / "anchors")
            rec = publish_anchor(store, _identity("abc123"), b)
            # the recorded digest equals a fresh recompute, never a supplied value
            from gnosis.kernel.evidence_capture import verify_bundle
            self.assertEqual(rec.bundle_digest, verify_bundle(b).bundle_digest)

    def test_a_bundle_bound_to_another_head_is_refused(self):
        # replay / cross-run: the bundle's own head must equal the run's head.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = _make_bundle(root, head_sha="OTHERHEAD")
            store = AnchorStore(root / "anchors")
            with self.assertRaises(AuthorityUnavailable):
                publish_anchor(store, _identity("abc123"), b)

    def test_verify_fails_closed_with_no_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = _make_bundle(root, head_sha="abc123")
            store = AnchorStore(root / "anchors")
            with self.assertRaises(AuthorityUnavailable):
                verify_anchored_bundle(store, "no-such-run", b)

    def test_publish_refuses_a_bundle_that_is_not_self_consistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = _make_bundle(root, head_sha="abc123")
            # tamper a covered file so verify_bundle no longer verifies
            (b / "pytest.stdout.txt").write_text("TAMPERED\n", encoding="utf-8")
            store = AnchorStore(root / "anchors")
            with self.assertRaises(AuthorityUnavailable):
                publish_anchor(store, _identity("abc123"), b)

    def test_verify_fails_closed_on_a_broken_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = _make_bundle(root, head_sha="abc123")
            store = AnchorStore(root / "anchors")
            publish_anchor(store, _identity("abc123", "run-1"), b)
            # a second record so tampering the first breaks the chain
            store.append(AnchorRecord("F-17", "run-2", "repoX", "h", "tr", "b",
                                      "d", *store.next_seq_and_prev()))
            lines = store.ledger.read_text(encoding="utf-8").splitlines()
            rec0 = json.loads(lines[0]); rec0["bundle_digest"] = "TAMPERED"
            lines[0] = json.dumps(rec0, sort_keys=True)
            store.ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(AuthorityUnavailable):
                verify_anchored_bundle(store, "run-1", b)


@HIGH_ONLY
class TestTheOsAuthorityBoundary(unittest.TestCase):
    """The OS-real matrix: a Medium worker cannot touch a High anchor."""

    CHILD = textwrap.dedent(f"""
        import os, sys, subprocess
        sys.path.insert(0, r"{SCRATCH_SRC}")
        from gnosis.kernel.authority import process_integrity, lowered_primary_token, SID_HIGH
        result, anchor, worktree = sys.argv[1], sys.argv[2], sys.argv[3]
        out = ["integrity=" + process_integrity()]
        def rec(name, fn):
            try:
                fn(); out.append(name + "=ALLOWED")
            except Exception as e:
                out.append(name + "=DENIED:" + type(e).__name__)
        rec("write_worktree", lambda: open(os.path.join(worktree,"w.txt"),"w").write("x"))
        rec("write_anchor", lambda: open(os.path.join(anchor,"a.txt"),"w").write("x"))
        rec("delete_anchor", lambda: os.remove(os.path.join(anchor,"seed.txt")))
        def relabel():
            r = subprocess.run(["icacls",anchor,"/setintegritylevel","(OI)(CI)Medium"],
                               capture_output=True,text=True)
            if r.returncode != 0: raise PermissionError("icacls denied")
        rec("relabel_anchor", relabel)
        def child_write():
            tgt = os.path.join(anchor,"gc.txt")
            subprocess.run([sys.executable,"-c",
                "open(r'%s','w').write('x')" % tgt], capture_output=True)
            if os.path.exists(tgt): raise RuntimeError("PRIVILEGE_RECOVERY")
            raise PermissionError("child denied")
        rec("child_write_anchor", child_write)
        rec("raise_integrity", lambda: lowered_primary_token(SID_HIGH))
        open(result,"w",encoding="utf-8").write("\\n".join(out))
    """)

    def test_the_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            anchor = root / "anchor"; anchor.mkdir()
            worktree = root / "worktree"; worktree.mkdir()
            (anchor / "seed.txt").write_text("seed", encoding="utf-8")
            label_high_no_write_up(anchor)
            child = root / "child.py"
            child.write_text(self.CHILD, encoding="utf-8")
            result = worktree / "result.txt"
            cmd = (f'"{sys.executable}" "{child}" "{result}" "{anchor}" "{worktree}"')
            code = run_at_integrity(cmd, str(worktree))
            self.assertEqual(code, 0, "worker did not complete")
            lines = dict(l.split("=", 1) for l in
                         result.read_text(encoding="utf-8").splitlines())
            self.assertEqual(lines["integrity"], "Medium")
            self.assertEqual(lines["write_worktree"], "ALLOWED")
            for k in ("write_anchor", "delete_anchor", "relabel_anchor",
                      "child_write_anchor", "raise_integrity"):
                self.assertTrue(lines[k].startswith("DENIED"),
                                f"{k} was not DENIED: {lines[k]}")
            # the anchor is intact: no worker file leaked in, seed survives
            names = sorted(p.name for p in anchor.iterdir())
            self.assertIn("seed.txt", names)
            self.assertNotIn("a.txt", names)
            self.assertNotIn("gc.txt", names)

    def test_the_publisher_can_write_what_the_worker_cannot(self):
        with tempfile.TemporaryDirectory() as tmp:
            anchor = Path(tmp) / "anchor"; anchor.mkdir()
            label_high_no_write_up(anchor)
            # this test process is High (the publisher) -> ALLOWED
            (anchor / "published.txt").write_text("by director", encoding="utf-8")
            self.assertTrue((anchor / "published.txt").exists())


if __name__ == "__main__":
    unittest.main()
