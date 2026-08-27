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
    assert_integrity,
    label_high_no_write_up,
    process_integrity,
    publish_anchor,
    run_at_integrity,
    verify_anchored_bundle,
)
from gnosis.kernel.canonical import GENESIS_HASH
from gnosis.kernel.evidence_capture import write_bundle_manifest
from gnosis.trust.anchor import ANCHOR_SCHEMA_V2, AnchorNotDeploymentBound

# Stage-3 fixtures. The production writer emits V2 only, so every record built
# here names a deployment and a run identity; a V1 record is exercised
# deliberately, and only where V1 compatibility is the thing under test.
SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"
DEPLOY = "d" * 64
RUNID_DIGEST = "e" * 64


def _record(run_id: str, seq: int, prev: str, *, bundle_digest: str = "d0",
            head: str = "h", tree: str = "tr", task: str = "t",
            repo: str = "repo", bundle: str = "b") -> AnchorRecord:
    """A V2 anchor record with the Stage-3 binding fields filled in."""
    return AnchorRecord(task, run_id, repo, head, tree, bundle, bundle_digest,
                        seq, prev, deployment_digest=DEPLOY,
                        run_identity_digest=RUNID_DIGEST,
                        schema=ANCHOR_SCHEMA_V2)


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


def _identity(head_sha: str, run_id: str = "run-1", *, tree: str = "cd0",
              sid: str = SID, deployment: str = DEPLOY,
              epoch: int = 0) -> RunIdentity:
    return RunIdentity(task_id="F-17", run_id=run_id, repository_id="repoX",
                       head_sha=head_sha, tree_identity=tree,
                       bundle_path=".gnosis/evidence/x", owner_worker_sid=sid,
                       deployment_digest=deployment, epoch=epoch)


class TestTheAnchorRecordChains(unittest.TestCase):
    def test_a_record_serialises_and_digests_stably(self):
        r = _record("r", 0, GENESIS_HASH, bundle_digest="dig", head="head", tree="tree")
        self.assertEqual(r.schema, ANCHOR_SCHEMA_V2)
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
            r0 = _record("r0", 0, GENESIS_HASH, head="h0", bundle="b0")
            s.append(r0)
            seq, prev = s.next_seq_and_prev()
            r1 = _record("r1", seq, prev, bundle_digest="d1", head="h1", bundle="b1")
            s.append(r1)
            self.assertTrue(s.verify_chain())
            self.assertEqual(s.lookup("r1").bundle_digest, "d1")

    def test_a_record_that_does_not_extend_the_chain_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self._store(Path(tmp))
            bad = _record("r", 5, "deadbeef", bundle_digest="d")
            with self.assertRaises(AuthorityUnavailable):
                s.append(bad)

    def test_editing_a_non_last_record_breaks_the_chain(self):
        # A hash chain protects record N through record N+1's prev pointer.
        with tempfile.TemporaryDirectory() as tmp:
            s = self._store(Path(tmp))
            s.append(_record("r0", 0, GENESIS_HASH))
            seq, prev = s.next_seq_and_prev()
            s.append(_record("r1", seq, prev, bundle_digest="d1"))
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
            s.append(_record("r0", 0, GENESIS_HASH))
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

    def test_publish_binds_the_directors_identity_not_the_bundles(self):
        # BLOCKER C: the record's authoritative fields come from the Director's
        # RunIdentity, never from anything the worker put in the bundle. The
        # bundle is only cross-checked (head), never adopted as identity.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = _make_bundle(root, head_sha="deadbeef")
            store = AnchorStore(root / "anchors")
            ident = RunIdentity(task_id="F-17", run_id="DIRECTOR-RUN",
                                repository_id="canonical-repo", head_sha="deadbeef",
                                tree_identity="cd0",
                                bundle_path=".gnosis/evidence/x",
                                owner_worker_sid=SID, deployment_digest=DEPLOY,
                                epoch=0)
            rec = publish_anchor(store, ident, b)
            self.assertEqual(rec.run_id, "DIRECTOR-RUN")
            self.assertEqual(rec.repository_id, "canonical-repo")
            self.assertEqual(rec.head_sha, "deadbeef")
            self.assertEqual(rec.bundle_path, ".gnosis/evidence/x")

    def test_verify_fails_closed_on_a_broken_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = _make_bundle(root, head_sha="abc123")
            store = AnchorStore(root / "anchors")
            publish_anchor(store, _identity("abc123", "run-1"), b)
            # a second record so tampering the first breaks the chain
            seq, prev = store.next_seq_and_prev()
            store.append(_record("run-2", seq, prev, bundle_digest="d", task="F-17",
                                 repo="repoX"))
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

    def test_the_worker_does_not_inherit_a_privileged_handle(self):
        # BLOCKER A: a High parent opens the anchor WRITE with an INHERITABLE
        # handle; run_at_integrity (CreateProcessWithTokenW) must not pass it to
        # the Medium worker. WorkerInheritedPrivilegedHandles = empty.
        import ctypes
        import msvcrt
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            anchor = root / "anchor"; anchor.mkdir()
            worktree = root / "worktree"; worktree.mkdir()
            held = anchor / "held.txt"; held.write_text("", encoding="utf-8")
            label_high_no_write_up(anchor)
            fh = open(held, "w")  # noqa: SIM115 - handle kept open on purpose
            try:
                handle = msvcrt.get_osfhandle(fh.fileno())
                ctypes.WinDLL("kernel32").SetHandleInformation(
                    ctypes.c_void_p(handle), 1, 1)  # HANDLE_FLAG_INHERIT
                result = worktree / "r.txt"
                child = root / "c.py"
                child.write_text(
                    "import ctypes, sys\n"
                    "h = int(sys.argv[2]); w = ctypes.c_ulong(0)\n"
                    "ok = ctypes.WinDLL('kernel32', use_last_error=True).WriteFile("
                    "ctypes.c_void_p(h), b'X', 1, ctypes.byref(w), None)\n"
                    "open(sys.argv[1],'w').write('WROTE' if ok else 'NO_HANDLE')\n",
                    encoding="utf-8")
                cmd = f'"{sys.executable}" "{child}" "{result}" "{handle}"'
                run_at_integrity(cmd, str(worktree))
                self.assertEqual(result.read_text(encoding="utf-8"), "NO_HANDLE")
            finally:
                fh.close()
            self.assertEqual(held.read_text(encoding="utf-8"), "")  # never written

    def test_assert_integrity_fails_closed_on_the_wrong_level(self):
        # the publisher (this High process) passes High and is refused Medium
        assert_integrity("High")
        with self.assertRaises(AuthorityUnavailable):
            assert_integrity("Medium")

    def test_a_medium_worker_asserts_medium_and_refuses_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worktree = root / "worktree"; worktree.mkdir()
            result = worktree / "r.txt"
            child = root / "c.py"
            child.write_text(
                f"import sys\nsys.path.insert(0, r'{SCRATCH_SRC}')\n"
                "from gnosis.kernel.authority import assert_integrity, AuthorityUnavailable\n"
                "out = []\n"
                "try: assert_integrity('Medium'); out.append('medium=OK')\n"
                "except AuthorityUnavailable: out.append('medium=RAISED')\n"
                "try: assert_integrity('High'); out.append('high=OK')\n"
                "except AuthorityUnavailable: out.append('high=RAISED')\n"
                "open(sys.argv[1],'w').write(' '.join(out))\n",
                encoding="utf-8")
            run_at_integrity(f'"{sys.executable}" "{child}" "{result}"', str(worktree))
            self.assertEqual(result.read_text(encoding="utf-8"), "medium=OK high=RAISED")

    def test_high_labelled_trusted_code_is_readable_but_not_writable_by_the_worker(self):
        # BLOCKER B (mechanism): the publisher's trusted code, if labelled High
        # NO_WRITE_UP, is READ/executed by the Medium worker but cannot be
        # modified by it — so the worker cannot poison code the High Director
        # later runs. (The wiring must label the real trusted-code root; this
        # proves the mechanism.)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trusted = root / "trusted"; trusted.mkdir()
            worktree = root / "worktree"; worktree.mkdir()
            (trusted / "trusted_mod.py").write_text('MARKER = "ORIGINAL"\n', encoding="utf-8")
            label_high_no_write_up(trusted)
            result = worktree / "r.txt"
            child = root / "c.py"
            child.write_text(
                "import sys, os\n"
                "t = os.path.join(sys.argv[2], 'trusted_mod.py'); out = []\n"
                "try:\n"
                "    open(t).read(); out.append('read=OK')\n"
                "except Exception as e: out.append('read=DENIED')\n"
                "try:\n"
                "    open(t,'w').write('MARKER=\"POISONED\"'); out.append('write=OK')\n"
                "except Exception as e: out.append('write=DENIED')\n"
                "open(sys.argv[1],'w').write(' '.join(out))\n",
                encoding="utf-8")
            cmd = f'"{sys.executable}" "{child}" "{result}" "{trusted}"'
            run_at_integrity(cmd, str(worktree))
            self.assertEqual(result.read_text(encoding="utf-8"), "read=OK write=DENIED")
            self.assertIn("ORIGINAL", (trusted / "trusted_mod.py").read_text(encoding="utf-8"))


@HIGH_ONLY
class TestTheAnchorIsBoundToItsDeploymentAndIdentity(unittest.TestCase):
    """F-17 Stage 3: an anchor cannot be verified against a different trust-plane
    deployment or a different run identity, and a V1 record — which carries no
    binding at all — cannot be read as though it did."""

    OTHER_DEPLOY = "f" * 64

    def test_publish_writes_a_v2_record_naming_the_deployment_and_the_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = _make_bundle(root, head_sha="abc123")
            store = AnchorStore(root / "anchors")
            ident = _identity("abc123")
            rec = publish_anchor(store, ident, b)
            self.assertEqual(rec.schema, ANCHOR_SCHEMA_V2)
            self.assertTrue(rec.is_deployment_bound)
            self.assertEqual(rec.deployment_digest, DEPLOY)
            self.assertEqual(rec.run_identity_digest, ident.digest())

    def test_a_bound_verification_passes_for_the_right_deployment_and_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = _make_bundle(root, head_sha="abc123")
            store = AnchorStore(root / "anchors")
            ident = _identity("abc123")
            publish_anchor(store, ident, b)
            self.assertTrue(verify_anchored_bundle(
                store, "run-1", b, expected_deployment_digest=DEPLOY,
                expected_run_identity_digest=ident.digest()))

    def test_a_record_made_under_one_deployment_is_refused_under_another(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = _make_bundle(root, head_sha="abc123")
            store = AnchorStore(root / "anchors")
            publish_anchor(store, _identity("abc123"), b)
            # bound to a DIFFERENT deployment: a cross-deployment attempt, and
            # NOT the same finding as "carries no binding at all".
            with self.assertRaises(AuthorityUnavailable) as caught:
                verify_anchored_bundle(store, "run-1", b,
                                       expected_deployment_digest=self.OTHER_DEPLOY)
            self.assertNotIsInstance(caught.exception, AnchorNotDeploymentBound)
            # "but the bundle itself verifies" is not an argument: the unbound
            # verification still passes, and that is exactly why the bound one
            # has to exist.
            self.assertTrue(verify_anchored_bundle(store, "run-1", b))

    def test_a_record_made_for_one_run_identity_is_refused_under_another(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = _make_bundle(root, head_sha="abc123")
            store = AnchorStore(root / "anchors")
            publish_anchor(store, _identity("abc123"), b)
            with self.assertRaises(AuthorityUnavailable):
                verify_anchored_bundle(store, "run-1", b,
                                       expected_run_identity_digest="0" * 64)

    def test_a_v1_record_cannot_satisfy_a_bound_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = _make_bundle(root, head_sha="abc123")
            store = AnchorStore(root / "anchors")
            from gnosis.kernel.evidence_capture import verify_bundle
            digest = verify_bundle(b).bundle_digest
            store.append(AnchorRecord(
                "F-17", "run-1", "repoX", "abc123", "cd0", ".gnosis/evidence/x",
                digest, 0, GENESIS_HASH, schema=ANCHOR_SCHEMA))
            # historical contract: still readable and verifiable
            self.assertTrue(verify_anchored_bundle(store, "run-1", b))
            # final F-17 contract: it carries no deployment binding, so it fails
            # closed instead of being treated as matching — and says so as its
            # own type, because "unbound legacy evidence" and "bound to another
            # trust plane" call for different operator responses.
            with self.assertRaises(AnchorNotDeploymentBound):
                verify_anchored_bundle(store, "run-1", b,
                                       expected_deployment_digest=DEPLOY)
            with self.assertRaises(AnchorNotDeploymentBound):
                verify_anchored_bundle(store, "run-1", b,
                                       expected_run_identity_digest="0" * 64)

    def test_publish_refuses_a_bundle_whose_tree_is_not_the_dispatched_one(self):
        # Before Stage 3 the record ADOPTED the bundle's content digest, so a
        # worker chose the tree identity that went into the authoritative record.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = _make_bundle(root, head_sha="abc123", content_digest="SOMETHING-ELSE")
            store = AnchorStore(root / "anchors")
            with self.assertRaises(AuthorityUnavailable):
                publish_anchor(store, _identity("abc123", tree="cd0"), b)

    def test_a_ledger_line_that_is_not_a_readable_record_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = AnchorStore(root / "anchors")
            store.append(_record("run-1", 0, GENESIS_HASH))
            for corrupt in ('{"schema": "gnosis.anchor.v9"}',
                            '{"task_id": "t", "surprise": 1}',
                            "{not json"):
                store.ledger.write_text(corrupt + "\n", encoding="utf-8")
                with self.assertRaises(AuthorityUnavailable, msg=corrupt):
                    store.records()


if __name__ == "__main__":
    unittest.main()
