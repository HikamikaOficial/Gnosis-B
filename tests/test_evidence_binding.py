"""EVIDENCE BINDS BYTES — the suite named after F-14's invariant.

The finding: `git status --porcelain` records a state and a name, so two
different dirty trees that touch the same files produce a byte-identical
bundle. The tests here are written to go red if the identity ever goes
back to being status-and-names, if the before/after comparison is
removed, or if a broken identity probe reads as "nothing changed".

Most of them drive real git repositories through real subprocesses. A
capture that only ever ran against a stub would prove the stub.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gnosis.kernel.evidence_capture import (
    EXIT_CHECKS_FAILED,
    EXIT_IDENTITY_UNAVAILABLE,
    EXIT_OK,
    EXIT_TREE_MUTATED,
    BindingVerdict,
    Capture,
    CheckCommand,
    CheckOutcome,
    ChecksVerdict,
    EmptyCaptureError,
    TreeIdentity,
    bind_tree,
    count_lint_findings,
    describe_drift,
    probe_tree_identity,
    publish_bundle,
    run_capture,
)
from gnosis.kernel.git_evidence import content_fingerprint

REPO = Path(__file__).resolve().parent.parent


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, check=True)
    return proc.stdout


def _make_repo(root: Path) -> Path:
    """A real repository with one commit, so HEAD and diffs exist."""
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "a.txt").write_text("original\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "init")
    return repo


def _python(*source: str) -> CheckCommand:
    """A check that really runs, so a mutation during it really happens."""
    return CheckCommand("check", (sys.executable, "-c", "; ".join(source)))


NOOP = _python("pass")

# A stand-in for ruff: two findings in its concise format, exit 1.
TWO_FINDINGS = (
    "print('a.py:1:1: E501 line too long'); "
    "print('b.py:2:1: F401 unused import'); "
    "raise SystemExit(1)"
)


class TestStatusAndNamesAreNotIdentity(unittest.TestCase):
    """F-14, reproduced: the same status over different bytes."""

    def test_same_status_same_names_different_bytes_differ(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))

            (repo / "a.txt").write_text("AAAA\n", encoding="utf-8")
            status_a = _git(repo, "status", "--porcelain")
            stat_a = _git(repo, "diff", "--stat")
            first = probe_tree_identity(repo)

            (repo / "a.txt").write_text("BBBB\n", encoding="utf-8")
            status_b = _git(repo, "status", "--porcelain")
            stat_b = _git(repo, "diff", "--stat")
            second = probe_tree_identity(repo)

            # What the old bundle recorded is identical across the two
            # trees. This is the finding, not a setup detail.
            self.assertEqual(status_a, status_b)
            self.assertEqual(stat_a, stat_b)

            self.assertTrue(first.available)
            self.assertTrue(second.available)
            self.assertEqual(first.fingerprint["status_sha256"],
                             second.fingerprint["status_sha256"])
            self.assertNotEqual(first.fingerprint["patch_sha256"],
                                second.fingerprint["patch_sha256"])
            self.assertNotEqual(first.digest, second.digest)

    def test_untracked_files_with_one_name_and_two_contents_differ(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))

            (repo / "u.txt").write_text("one\n", encoding="utf-8")
            status_a = _git(repo, "status", "--porcelain")
            first = probe_tree_identity(repo)

            (repo / "u.txt").write_text("two\n", encoding="utf-8")
            status_b = _git(repo, "status", "--porcelain")
            second = probe_tree_identity(repo)

            self.assertEqual(status_a, status_b)
            self.assertEqual(first.fingerprint["status_sha256"],
                             second.fingerprint["status_sha256"])
            self.assertNotEqual(first.fingerprint["untracked"]["u.txt"],
                                second.fingerprint["untracked"]["u.txt"])
            self.assertNotEqual(first.digest, second.digest)

    def test_an_untracked_file_is_identified_by_hash_not_by_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            (repo / "u.txt").write_text("SECRET-CONTENT-9f3a\n", encoding="utf-8")

            identity = probe_tree_identity(repo)
            payload = json.dumps(identity.to_dict())

            self.assertIn("u.txt", payload)
            self.assertNotIn("SECRET-CONTENT-9f3a", payload)
            self.assertRegex(identity.fingerprint["untracked"]["u.txt"], r"\A[0-9a-f]{64}\Z")


class TestTheIdentityProbeFailsClosed(unittest.TestCase):
    def test_a_git_probe_failure_is_not_an_identity(self):
        identity = probe_tree_identity(
            REPO, fingerprint=lambda _: {"is_repo": True, "probe_failed": "git timed out"})
        self.assertFalse(identity.available)
        self.assertIsNone(identity.digest)
        self.assertIn("git timed out", identity.reason or "")

    def test_a_directory_that_is_not_a_repository_is_not_an_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity = probe_tree_identity(Path(tmp))
            self.assertFalse(identity.available)
            self.assertIsNone(identity.digest)

    def test_an_unreadable_untracked_file_is_not_an_identity(self):
        # content_fingerprint records `unreadable: ...` for a file whose
        # bytes it could not hash. Treating that as an identity would mean
        # calling a tree identified when part of it was never read.
        identity = probe_tree_identity(REPO, fingerprint=lambda _: {
            "is_repo": True, "head_sha": "a" * 40, "branch": "main",
            "status_sha256": "b" * 64, "patch_sha256": "c" * 64,
            "untracked": {"locked.bin": "unreadable: [Errno 13] Permission denied"},
        })
        self.assertFalse(identity.available)
        self.assertIn("locked.bin", identity.reason or "")

    def test_a_probe_that_raises_is_not_an_identity(self):
        def explode(_: Path) -> dict[str, object]:
            raise OSError("git is gone")

        identity = probe_tree_identity(REPO, fingerprint=explode)
        self.assertFalse(identity.available)
        self.assertIsNone(identity.digest)
        self.assertIn("git is gone", identity.reason or "")

    def test_an_unhashable_fingerprint_is_not_an_identity(self):
        identity = probe_tree_identity(REPO, fingerprint=lambda _: {
            "is_repo": True, "untracked": {}, "patch_sha256": float("nan")})
        self.assertFalse(identity.available)
        self.assertIsNone(identity.digest)


class TestBinding(unittest.TestCase):
    def test_two_identical_identities_bind(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            binding = bind_tree(probe_tree_identity(repo), probe_tree_identity(repo))
            self.assertIs(binding.verdict, BindingVerdict.BOUND)
            self.assertTrue(binding.identical)
            self.assertEqual(binding.drift, ())

    def test_a_changed_tree_does_not_bind_and_the_drift_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            pre = probe_tree_identity(repo)
            (repo / "a.txt").write_text("moved\n", encoding="utf-8")
            binding = bind_tree(pre, probe_tree_identity(repo))

            self.assertIs(binding.verdict, BindingVerdict.TREE_MUTATED)
            self.assertFalse(binding.identical)
            self.assertIn("patch_sha256", binding.drift)

    def test_an_available_identity_without_a_digest_cannot_bind(self):
        # Two `None`s comparing equal is the shape of `all([]) is True`.
        hollow = TreeIdentity(True, None, {"is_repo": True})
        binding = bind_tree(hollow, hollow)
        self.assertIs(binding.verdict, BindingVerdict.IDENTITY_UNAVAILABLE)
        self.assertFalse(binding.identical)

    def test_drift_names_untracked_paths_and_never_their_bytes(self):
        pre = {"untracked": {"kept.txt": "aa", "gone.txt": "bb"}}
        post = {"untracked": {"kept.txt": "zz", "new.txt": "cc"}}
        drift = describe_drift(pre, post)
        self.assertIn("untracked changed: kept.txt", drift)
        self.assertIn("untracked removed: gone.txt", drift)
        self.assertIn("untracked added: new.txt", drift)
        self.assertNotIn("aa", " ".join(drift))


class TestACaptureBindsTheTreeItChecked(unittest.TestCase):
    def test_a_dirty_but_stable_tree_is_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            (repo / "a.txt").write_text("dirty\n", encoding="utf-8")
            (repo / "u.txt").write_text("SECRET-CONTENT-9f3a\n", encoding="utf-8")

            capture = run_capture(repo, [NOOP], root / "staging")

            self.assertIs(capture.binding.verdict, BindingVerdict.BOUND)
            self.assertTrue(capture.evidence_valid)
            self.assertEqual(capture.exit_code, EXIT_OK)
            self.assertTrue(capture.summary["tree_identity"]["identical"])
            self.assertTrue(capture.summary["all_passed"])

            # Both COMPLETE fingerprints are in the summary, and the
            # digest is re-derivable from what is written down.
            identity = capture.summary["tree_identity"]
            self.assertEqual(identity["pre"]["fingerprint"],
                             identity["post"]["fingerprint"])
            self.assertIn("patch_sha256", identity["pre"]["fingerprint"])
            self.assertIn("u.txt", identity["pre"]["fingerprint"]["untracked"])

            written = (capture.bundle / "SUMMARY.json").read_text(encoding="utf-8")
            self.assertNotIn("SECRET-CONTENT-9f3a", written)

    def test_touching_an_already_dirty_tracked_file_invalidates_the_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            (repo / "a.txt").write_text("dirty\n", encoding="utf-8")

            mutate = _python("open('a.txt', 'a', encoding='utf-8').write('more\\n')")
            capture = run_capture(repo, [mutate], root / "staging")

            self.assertIs(capture.binding.verdict, BindingVerdict.TREE_MUTATED)
            self.assertFalse(capture.evidence_valid)
            self.assertEqual(capture.exit_code, EXIT_TREE_MUTATED)
            self.assertIn("patch_sha256", capture.binding.drift)

    def test_touching_an_untracked_file_invalidates_the_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            (repo / "u.txt").write_text("before\n", encoding="utf-8")

            mutate = _python("open('u.txt', 'w', encoding='utf-8').write('after\\n')")
            capture = run_capture(repo, [mutate], root / "staging")

            self.assertIs(capture.binding.verdict, BindingVerdict.TREE_MUTATED)
            self.assertEqual(capture.exit_code, EXIT_TREE_MUTATED)
            self.assertIn("untracked changed: u.txt", capture.binding.drift)

    def test_creating_an_untracked_file_invalidates_the_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)

            mutate = _python("open('new.txt', 'w', encoding='utf-8').write('x\\n')")
            capture = run_capture(repo, [mutate], root / "staging")

            self.assertIs(capture.binding.verdict, BindingVerdict.TREE_MUTATED)
            self.assertIn("untracked added: new.txt", capture.binding.drift)

    def test_a_mutated_tree_reports_its_checks_and_refuses_to_call_them_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)

            mutate = _python("open('new.txt', 'w', encoding='utf-8').write('x\\n')")
            capture = run_capture(repo, [mutate], root / "staging")
            summary = capture.summary

            # The checks really did all exit 0, and that fact is kept.
            self.assertIs(capture.checks_verdict, ChecksVerdict.ALL_CLEAN)
            self.assertTrue(summary["checks_all_zero_exit"])
            self.assertEqual(summary["non_zero_exits"], [])
            # And the bundle still refuses to call itself a pass.
            self.assertFalse(summary["all_passed"])
            self.assertFalse(summary["gates_clean"])
            self.assertFalse(summary["evidence_valid"])
            self.assertIn("INVALID EVIDENCE", summary["verdict"])

    def test_an_unavailable_pre_identity_runs_nothing_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            unavailable = TreeIdentity(False, None, {"is_repo": True,
                                                     "probe_failed": "git timed out"},
                                       "git probe failed: git timed out")

            capture = run_capture(
                repo, [_python("open('ran.txt', 'w', encoding='utf-8').write('x')")],
                root / "staging", identity=lambda _: unavailable)

            self.assertIs(capture.binding.verdict, BindingVerdict.IDENTITY_UNAVAILABLE)
            self.assertEqual(capture.exit_code, EXIT_IDENTITY_UNAVAILABLE)
            self.assertFalse(capture.evidence_valid)
            self.assertIs(capture.checks_verdict, ChecksVerdict.NOT_RUN)
            self.assertEqual(capture.checks, ())
            self.assertFalse((repo / "ran.txt").exists())

    def test_an_unavailable_post_identity_fails_closed_although_every_check_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            answers = [probe_tree_identity(repo),
                       TreeIdentity(False, None, {"is_repo": True,
                                                  "probe_failed": "git timed out"},
                                    "git probe failed: git timed out")]

            capture = run_capture(repo, [NOOP], root / "staging",
                                  identity=lambda _: answers.pop(0))

            self.assertEqual([c.outcome for c in capture.checks], [CheckOutcome.PASSED])
            self.assertIs(capture.checks_verdict, ChecksVerdict.ALL_CLEAN)
            self.assertIs(capture.binding.verdict, BindingVerdict.IDENTITY_UNAVAILABLE)
            self.assertEqual(capture.exit_code, EXIT_IDENTITY_UNAVAILABLE)
            self.assertFalse(capture.summary["all_passed"])

    def test_a_capture_with_no_checks_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            with self.assertRaises(EmptyCaptureError):
                run_capture(repo, [], root / "staging")

    def test_the_four_situations_have_four_exit_codes(self):
        self.assertEqual(
            len({EXIT_OK, EXIT_CHECKS_FAILED, EXIT_TREE_MUTATED,
                 EXIT_IDENTITY_UNAVAILABLE}), 4)


class TestTheBundleDoesNotInvalidateItself(unittest.TestCase):
    def test_a_bundle_staged_inside_the_repository_breaks_its_own_capture(self):
        # Why the staging directory lives outside the tree: written in
        # place, the evidence shows up in its own post fingerprint.
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            capture = run_capture(repo, [NOOP], repo / ".gnosis" / "evidence" / "run")

            self.assertIs(capture.binding.verdict, BindingVerdict.TREE_MUTATED)
            self.assertFalse(capture.summary["bundle_staged_outside_repo"])

    def test_a_bundle_staged_outside_the_repository_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(repo, [NOOP], root / "staging")

            self.assertIs(capture.binding.verdict, BindingVerdict.BOUND)
            self.assertTrue(capture.summary["bundle_staged_outside_repo"])

    def test_the_bundle_carries_a_transcript_per_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(repo, [NOOP], root / "staging")

            self.assertTrue((capture.bundle / "SUMMARY.json").is_file())
            self.assertTrue((capture.bundle / "check.stdout.txt").is_file())
            self.assertTrue((capture.bundle / "check.stderr.txt").is_file())

    def test_publishing_happens_after_the_fact_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(repo, [NOOP], root / "staging")

            published = publish_bundle(capture.bundle, repo / ".gnosis" / "evidence" / "x")
            self.assertTrue((published / "SUMMARY.json").is_file())
            with self.assertRaises(FileExistsError):
                publish_bundle(capture.bundle, published)


class TestTheCheckOutcomesStayDistinct(unittest.TestCase):
    def test_a_failing_check_is_a_failure_and_still_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(repo, [_python("raise SystemExit(1)")], root / "staging")

            self.assertIs(capture.checks_verdict, ChecksVerdict.FAILED)
            self.assertEqual(capture.exit_code, EXIT_CHECKS_FAILED)
            # The tree is identified; it is the code that is red.
            self.assertIs(capture.binding.verdict, BindingVerdict.BOUND)
            self.assertTrue(capture.evidence_valid)
            self.assertEqual(capture.summary["non_zero_exits"], ["check"])

    def test_lint_debt_within_the_baseline_is_not_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            lint = CheckCommand(
                "ruff", (sys.executable, "-c", TWO_FINDINGS), lint_baseline=True)

            capture = run_capture(repo, [lint], root / "staging", lint_baseline=19)
            result = capture.checks[0]

            self.assertIs(result.outcome, CheckOutcome.WITHIN_LINT_BASELINE)
            self.assertEqual(result.lint_findings, 2)
            self.assertEqual(result.detail, "known backlog, not above baseline")
            self.assertIs(capture.checks_verdict, ChecksVerdict.WITHIN_BASELINE)
            self.assertEqual(capture.exit_code, EXIT_OK)
            self.assertFalse(capture.summary["all_passed"])
            self.assertTrue(capture.summary["gates_clean"])
            self.assertEqual(capture.summary["non_zero_exits"], ["ruff"])
            self.assertEqual(capture.summary["verdict"],
                             "within baseline; see non_zero_exits")

    def test_lint_debt_above_the_baseline_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            lint = CheckCommand(
                "ruff", (sys.executable, "-c", TWO_FINDINGS), lint_baseline=True)

            capture = run_capture(repo, [lint], root / "staging", lint_baseline=1)

            self.assertIs(capture.checks[0].outcome, CheckOutcome.NEW_LINT_DEBT)
            self.assertIn("NEW LINT DEBT", capture.checks[0].detail or "")
            self.assertIs(capture.checks_verdict, ChecksVerdict.FAILED)
            self.assertEqual(capture.exit_code, EXIT_CHECKS_FAILED)

    def test_a_clean_run_says_all_gates_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(repo, [NOOP], root / "staging")
            self.assertEqual(capture.summary["verdict"], "all gates clean")
            self.assertTrue(capture.summary["checks_all_zero_exit"])

    def test_the_lint_count_matches_the_heuristic_the_baseline_was_recorded_with(self):
        stdout = (
            "src\\gnosis\\runner\\liveness.py:87:12: BLE001 Do not catch blind exception\n"
            "tests\\test_ledger.py:179:24: BLE001 Do not catch blind exception\n"
            "Found 2 errors.\n"
            "No fixes available (6 hidden fixes can be enabled).\n"
        )
        self.assertEqual(count_lint_findings(stdout), 2)


class TestTheRealCaptureScript(unittest.TestCase):
    """The script is the thing that runs; the module is what it uses."""

    @staticmethod
    def _load():
        path = REPO / "scripts" / "capture_evidence.py"
        spec = importlib.util.spec_from_file_location("capture_evidence_under_test", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"{path} could not be loaded as a module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_script_still_runs_pytest_mypy_and_ruff(self):
        script = self._load()
        names = [command.name for command in script.COMMANDS]
        self.assertEqual(names, ["pytest", "mypy", "ruff", "git-head", "git-status"])

        by_name = {command.name: command for command in script.COMMANDS}
        self.assertEqual(by_name["pytest"].argv[1:], ("-m", "pytest", "tests/", "-q"))
        self.assertEqual(by_name["mypy"].argv[1:], ("-m", "mypy", "src/gnosis"))
        self.assertIn("--output-format=concise", by_name["ruff"].argv)
        self.assertTrue(by_name["ruff"].lint_baseline)
        self.assertFalse(by_name["pytest"].lint_baseline)

    def test_the_script_reads_the_recorded_lint_baseline(self):
        script = self._load()
        recorded = json.loads(
            (REPO / ".gnosis" / "state" / "lint_baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(script.lint_baseline(), recorded["max_findings"])

    def test_the_script_stages_the_bundle_outside_the_repository(self):
        script = self._load()
        staging = script.staging_root()
        try:
            self.assertFalse(str(staging.resolve()).startswith(str(REPO.resolve())))
        finally:
            staging.rmdir()

    def test_the_script_captures_through_the_bound_driver(self):
        script = self._load()
        self.assertIs(script.run_capture, run_capture)
        self.assertIs(script.publish_bundle, publish_bundle)


class TestTheRepositorysOwnUntrackedFilesAreCovered(unittest.TestCase):
    """Requirement of this repo, not of the abstraction.

    `.stfolder/` and `PROJECT_REPORT.md` are pre-existing untracked
    entries nobody may delete or ignore. They must be part of the tree's
    identity, and their contents must not appear in the bundle.
    """

    def test_every_untracked_entry_is_represented_by_a_digest(self):
        fingerprint = content_fingerprint(REPO)
        if fingerprint.get("probe_failed") or not fingerprint.get("is_repo"):
            self.skipTest("git could not probe the repository")
        untracked = fingerprint["untracked"]
        if not untracked:
            self.skipTest("the working tree has no untracked files right now")
        for path, digest in untracked.items():
            with self.subTest(path=path):
                self.assertRegex(digest, r"\A[0-9a-f]{64}\Z")


class TestCaptureIsADataclassNotAFlag(unittest.TestCase):
    def test_evidence_valid_is_derived_from_the_binding(self):
        capture = Capture(
            bind_tree(TreeIdentity(True, "d", {}), TreeIdentity(True, "d", {})),
            (), ChecksVerdict.ALL_CLEAN, Path("."), {}, EXIT_OK)
        self.assertTrue(capture.evidence_valid)

        mutated = Capture(
            bind_tree(TreeIdentity(True, "d", {}), TreeIdentity(True, "e", {})),
            (), ChecksVerdict.ALL_CLEAN, Path("."), {}, EXIT_TREE_MUTATED)
        self.assertFalse(mutated.evidence_valid)


if __name__ == "__main__":
    unittest.main()
