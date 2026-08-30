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

import contextlib
import hashlib
import importlib.util
import json
import mmap
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from gnosis.kernel import input_lock as input_lock_module
from gnosis.kernel.canonical import hash_canonical
from gnosis.kernel.evidence_capture import (
    BUNDLE_MANIFEST,
    EXIT_BOUNDARY_UNAVAILABLE,
    EXIT_CHECKS_FAILED,
    EXIT_IDENTITY_UNAVAILABLE,
    EXIT_INPUTS_MUTATED,
    EXIT_INPUTS_UNPROTECTED,
    EXIT_MACHINERY_MUTATED,
    EXIT_MACHINERY_REDIRECTED,
    EXIT_MACHINERY_UNOBSERVABLE,
    EXIT_MACHINERY_UNQUALIFIED,
    EXIT_OK,
    EXIT_PREPARATION_DRIFT,
    EXIT_STREAMS_MUTATED,
    EXIT_TREE_MUTATED,
    BindingVerdict,
    Boundary,
    Capture,
    CheckCommand,
    CheckOutcome,
    ChecksVerdict,
    EmptyCaptureError,
    ObservationVerdict,
    PathClass,
    TreeIdentity,
    _is_git_machinery_tamper,
    _is_git_resolution_redirect,
    bind_tree,
    classify_observation,
    classify_path,
    count_lint_findings,
    covered_paths,
    describe_drift,
    probe_tree_identity,
    publish_bundle,
    run_capture,
    stream_directories,
    verify_bundle,
)
from gnosis.kernel.git_evidence import (
    content_fingerprint,
    git_resolution_faithful,
    git_topology_eligible,
)
from gnosis.kernel.input_lock import (
    _SUPPORTED_DRIVE_TYPES,
    _SUPPORTED_FILESYSTEMS,
    LockOutcome,
    UnavailableLock,
    VolumeCapabilities,
    WindowsInputLock,
    classify_volume,
    create_input_lock,
    named_streams,
    probe_volume,
    reparse_in_chain,
    stream_domain,
    stream_drift,
    stream_inventory,
)
from gnosis.kernel.write_observer import (
    MECHANISM,
    Observation,
    UnavailableObserver,
    WriteEvent,
    create_write_observer,
)

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
            capture = run_capture(repo, [mutate], root / "staging",
                                  input_lock=_no_prevention)

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
            capture = run_capture(repo, [mutate], root / "staging",
                                  input_lock=_no_prevention)

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
            # Three answers, not two: the identity is taken before the
            # lock, again once the inputs are unwritable, and again after
            # the checks. Only the last one is the unavailable case here.
            answers = [probe_tree_identity(repo),
                       probe_tree_identity(repo),
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
        # Changed by the first independent review, and only here: the
        # capture now needs a boundary as well as a binding, because
        # equal endpoints were exactly the defect. The assertion below is
        # the same one, with the second half it was missing.
        capture = Capture(
            bind_tree(TreeIdentity(True, "d", {}), TreeIdentity(True, "d", {})),
            (), ChecksVerdict.ALL_CLEAN, Path("."), {}, EXIT_OK, _clean_boundary())
        self.assertTrue(capture.evidence_valid)

        mutated = Capture(
            bind_tree(TreeIdentity(True, "d", {}), TreeIdentity(True, "e", {})),
            (), ChecksVerdict.ALL_CLEAN, Path("."), {}, EXIT_TREE_MUTATED,
            _clean_boundary())
        self.assertFalse(mutated.evidence_valid)

    def test_a_bound_capture_over_an_unobserved_interval_is_not_valid(self):
        unobserved = Boundary(
            ObservationVerdict.UNOBSERVED, "none", 0, 0, (), 0, (),
            reason="no write observer")
        capture = Capture(
            bind_tree(TreeIdentity(True, "d", {}), TreeIdentity(True, "d", {})),
            (), ChecksVerdict.ALL_CLEAN, Path("."), {}, EXIT_BOUNDARY_UNAVAILABLE,
            unobserved)
        self.assertFalse(capture.evidence_valid)


def _clean_boundary() -> Boundary:
    return Boundary(ObservationVerdict.CLEAN, "test", 0, 0, (), 0, ())


class _FixedObserver:
    """An observer that reports whatever the test needs it to report."""

    def __init__(self, observation: Observation) -> None:
        self._observation = observation
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> Observation:
        return self._observation


def _script(*lines: str) -> CheckCommand:
    return CheckCommand("check", (sys.executable, "-c", "\n".join(lines)))


class _NoPrevention:
    """Prevention switched off, so the OBSERVATION half can be tested alone.

    By default the boundary REFUSES these writes outright — that is what
    `TestTheInputsCannotBeWritten` proves. Detection still has to work
    and still has to be tested: it is the only half that covers a path
    which did not exist when the lock was taken, and the only half a
    platform without the share-mode mechanism could ever have.
    """

    def acquire(self, paths, directories=()):
        # locked=0, so the byte-bound invariant is satisfied vacuously:
        # this lock holds nothing and therefore hashes nothing.
        return LockOutcome(True, 0, (), "none (prevention disabled for this test)")

    def release(self) -> None:
        return None


def _no_prevention(_: Path) -> _NoPrevention:
    return _NoPrevention()


def _change_read_restore(target: str) -> CheckCommand:
    """The reproduction: mutate, read the mutation, put everything back.

    Bytes, size and timestamps are all restored, so every sampled
    comparison — the two fingerprints included — sees a tree that never
    moved.
    """
    return _script(
        "import os",
        f"p = r'{target}'",
        "st = os.stat(p)",
        "original = open(p, 'rb').read()",
        "open(p, 'wb').write(b'TAMPERED-DURING-THE-CHECK\\n')",
        "assert open(p, 'rb').read() == b'TAMPERED-DURING-THE-CHECK\\n'",
        "open(p, 'wb').write(original)",
        "os.utime(p, (st.st_atime, st.st_mtime))",
    )


class TestATransientChangeIsStillAChange(unittest.TestCase):
    """The first independent review of ADR-0026, reproduced and closed.

    Every test here checks the SAME two things: that the endpoints agree
    (so the previous implementation would have called it valid) and that
    the capture refuses anyway.
    """

    def _assert_caught(self, capture, expect_path: str):
        self.assertIs(capture.binding.verdict, BindingVerdict.BOUND,
                      "the endpoints must agree, or this proves nothing")
        self.assertIs(capture.boundary.verdict, ObservationVerdict.INPUTS_MUTATED)
        self.assertFalse(capture.evidence_valid)
        self.assertFalse(capture.summary["all_passed"])
        self.assertEqual(capture.exit_code, EXIT_INPUTS_MUTATED)
        self.assertIn("INVALID EVIDENCE", capture.summary["verdict"])
        self.assertTrue(
            any(expect_path in violation for violation in capture.boundary.violations),
            f"{expect_path} not named in {capture.boundary.violations}")

    def test_a_clean_tracked_file_changed_read_and_restored_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(repo, [_change_read_restore("a.txt")], root / "staging",
                                  input_lock=_no_prevention)
            self._assert_caught(capture, "a.txt")

    def test_an_already_dirty_tracked_file_changed_read_and_restored_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            (repo / "a.txt").write_text("dirty before the capture\n", encoding="utf-8")
            capture = run_capture(repo, [_change_read_restore("a.txt")], root / "staging",
                                  input_lock=_no_prevention)
            self._assert_caught(capture, "a.txt")

    def test_an_untracked_file_changed_read_and_restored_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            (repo / "u.txt").write_text("untracked\n", encoding="utf-8")
            capture = run_capture(repo, [_change_read_restore("u.txt")], root / "staging",
                                  input_lock=_no_prevention)
            self._assert_caught(capture, "u.txt")

    def test_an_untracked_file_created_read_and_deleted_is_caught(self):
        # In neither fingerprint: it did not exist at the start and does
        # not exist at the end. Only the stream ever saw it.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(repo, [_script(
                "import os",
                "open('ghost.txt', 'w', encoding='utf-8').write('here\\n')",
                "assert open('ghost.txt', encoding='utf-8').read() == 'here\\n'",
                "os.remove('ghost.txt')",
            )], root / "staging")
            self._assert_caught(capture, "ghost.txt")

    def test_an_external_change_that_restores_itself_before_the_end_is_caught(self):
        # Nothing the check did: another process on the machine. The
        # handshake keeps it deterministic instead of racing a sleep.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            ready, go = root / "ready", root / "go"
            check = _script(
                "import os, time",
                f"open(r'{ready}', 'w').close()",
                f"while not os.path.exists(r'{go}'):",
                "    time.sleep(0.01)",
            )

            def meddle():
                while not ready.exists():
                    time.sleep(0.01)
                target = repo / "a.txt"
                stat = target.stat()
                original = target.read_bytes()
                target.write_bytes(b"TAMPERED-FROM-OUTSIDE\n")
                target.write_bytes(original)
                os.utime(target, (stat.st_atime, stat.st_mtime))
                go.write_text("go", encoding="utf-8")

            meddler = threading.Thread(target=meddle)
            meddler.start()
            try:
                capture = run_capture(repo, [check], root / "staging",
                                      input_lock=_no_prevention)
            finally:
                go.write_text("go", encoding="utf-8")
                meddler.join(timeout=30)
            self._assert_caught(capture, "a.txt")

    def test_a_stable_run_still_produces_valid_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            (repo / "a.txt").write_text("dirty but still\n", encoding="utf-8")
            (repo / "u.txt").write_text("untracked but still\n", encoding="utf-8")

            capture = run_capture(repo, [_script("print('quiet')")], root / "staging")

            self.assertIs(capture.binding.verdict, BindingVerdict.BOUND)
            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertEqual(capture.boundary.violations, ())
            self.assertTrue(capture.evidence_valid)
            self.assertEqual(capture.exit_code, EXIT_OK)
            self.assertTrue(capture.summary["all_passed"])

    def test_an_authorised_output_created_and_removed_is_not_a_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            check = _script(
                "import os",
                "os.makedirs('build-output', exist_ok=True)",
                "open('build-output/report.txt', 'w', encoding='utf-8').write('x\\n')",
                "os.remove('build-output/report.txt')",
                "os.rmdir('build-output')",
            )
            capture = run_capture(repo, [check], root / "staging",
                                  allowed_writes=("build-output/",))

            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertTrue(capture.evidence_valid)
            self.assertGreater(capture.boundary.allowed_events, 0)

    def test_the_same_write_without_the_authorisation_is_a_violation(self):
        # The allow-list is what makes the difference, not the file name.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            check = _script(
                "import os",
                "os.makedirs('build-output', exist_ok=True)",
                "open('build-output/report.txt', 'w', encoding='utf-8').write('x\\n')",
                "os.remove('build-output/report.txt')",
                "os.rmdir('build-output')",
            )
            capture = run_capture(repo, [check], root / "staging")
            self._assert_caught(capture, "build-output/report.txt")

    def test_a_git_ignored_cache_is_allowed_only_when_it_is_declared(self):
        # This asserted that being git-ignored was enough, which is the
        # equivalence the seventh review refused. Declaring the root is
        # what allows it now; git's opinion is not consulted at all.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            (repo / ".gitignore").write_text(".mypy_cache/\n", encoding="utf-8")
            _git(repo, "add", ".gitignore")
            _git(repo, "commit", "-m", "ignore the cache")

            check = _script(
                "import os",
                "os.makedirs('.mypy_cache', exist_ok=True)",
                "open('.mypy_cache/data.json', 'w', encoding='utf-8').write('{}\\n')",
            )

            undeclared = run_capture(repo, [check], root / "undeclared")
            self.assertIs(undeclared.boundary.verdict, ObservationVerdict.INPUTS_MUTATED)
            self.assertFalse(undeclared.evidence_valid)

            shutil.rmtree(repo / ".mypy_cache")
            declared = run_capture(repo, [check], root / "declared",
                                   allowed_writes=(".mypy_cache/",))
            self.assertIs(declared.binding.verdict, BindingVerdict.BOUND)
            self.assertIs(declared.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertTrue(declared.evidence_valid)

    def test_writes_to_git_itself_are_counted_not_judged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(repo, [_script("pass")], root / "staging")

            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertGreater(capture.boundary.machinery_events, 0,
                               "git updates its index while reading the tree")


class TestTheBoundaryFailsClosed(unittest.TestCase):
    def test_an_unavailable_observer_invalidates_the_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(
                repo, [_script("pass")], root / "staging",
                observer=lambda _: _FixedObserver(
                    Observation(False, False, (), "none", "no observer on this platform")))

            self.assertIs(capture.binding.verdict, BindingVerdict.BOUND)
            self.assertIs(capture.boundary.verdict, ObservationVerdict.UNOBSERVED)
            self.assertFalse(capture.evidence_valid)
            self.assertEqual(capture.exit_code, EXIT_BOUNDARY_UNAVAILABLE)
            self.assertIn("no observer on this platform", capture.summary["verdict"])

    def test_an_incomplete_observation_invalidates_the_capture(self):
        # The kernel dropped events. Seeing none of them is not seeing none.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(
                repo, [_script("pass")], root / "staging",
                observer=lambda _: _FixedObserver(Observation(
                    True, False, (), "ReadDirectoryChangesW(recursive)",
                    "the change buffer overflowed; events were lost")))

            self.assertIs(capture.boundary.verdict, ObservationVerdict.UNOBSERVED)
            self.assertFalse(capture.evidence_valid)
            self.assertEqual(capture.exit_code, EXIT_BOUNDARY_UNAVAILABLE)
            self.assertFalse(capture.summary["gates_clean"])

    def test_an_empty_stream_from_a_trustworthy_observer_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(
                repo, [_script("pass")], root / "staging",
                observer=lambda _: _FixedObserver(
                    Observation(True, True, (), "test", None)))

            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertTrue(capture.evidence_valid)

    def test_the_six_situations_have_six_exit_codes(self):
        self.assertEqual(
            len({EXIT_OK, EXIT_CHECKS_FAILED, EXIT_TREE_MUTATED,
                 EXIT_IDENTITY_UNAVAILABLE, EXIT_INPUTS_MUTATED,
                 EXIT_BOUNDARY_UNAVAILABLE}), 6)

    def test_the_bundle_records_the_boundary_beside_the_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(repo, [_script("pass")], root / "staging")
            written = json.loads(
                (capture.bundle / "SUMMARY.json").read_text(encoding="utf-8"))

            boundary = written["boundary"]
            self.assertEqual(boundary["verdict"], "CLEAN")
            self.assertIn("ReadDirectoryChangesW", boundary["mechanism"])
            self.assertIn("undoes itself", boundary["authority"])
            self.assertGreater(boundary["covered_files"], 0)


class TestTheWriteObserverItself(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "ReadDirectoryChangesW is Windows-only")
    def test_a_change_that_undoes_itself_is_still_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("original\n", encoding="utf-8")
            stat = (root / "a.txt").stat()

            observer = create_write_observer(root)
            observer.start()
            (root / "a.txt").write_bytes(b"TAMPERED\n")
            (root / "a.txt").write_bytes(b"original\n")
            os.utime(root / "a.txt", (stat.st_atime, stat.st_mtime))
            observation = observer.stop()

            self.assertTrue(observation.available)
            self.assertTrue(observation.complete)
            self.assertTrue(observation.trustworthy)
            self.assertTrue(any(event.path == "a.txt" for event in observation.events))
            # And the tree really is byte-identical again.
            self.assertEqual((root / "a.txt").read_bytes(), b"original\n")

    @unittest.skipUnless(sys.platform == "win32", "ReadDirectoryChangesW is Windows-only")
    def test_a_quiet_directory_reports_a_trustworthy_empty_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("original\n", encoding="utf-8")
            observer = create_write_observer(root)
            observer.start()
            (root / "a.txt").read_bytes()
            observation = observer.stop()

            self.assertTrue(observation.trustworthy)
            self.assertFalse([event for event in observation.events
                              if not event.path.startswith(".gnosis-capture-barrier")])

    @unittest.skipUnless(sys.platform == "win32", "ReadDirectoryChangesW is Windows-only")
    def test_the_barrier_is_removed_after_the_stream_is_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            observer = create_write_observer(root)
            observer.start()
            observer.stop()
            self.assertFalse((root / ".gnosis-capture-barrier").exists())

    def test_an_observer_that_was_never_armed_never_says_nothing_happened(self):
        observation = UnavailableObserver("no mechanism here").stop()
        self.assertFalse(observation.available)
        self.assertFalse(observation.complete)
        self.assertFalse(observation.trustworthy)
        self.assertEqual(observation.events, ())


def _tamper_attempt(mode: str) -> CheckCommand:
    """A check that tries the ABA on its own inputs and says what happened."""
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


WINDOWS_ONLY = unittest.skipUnless(sys.platform == "win32",
                                   "the share-mode lock is a Windows mechanism")


class TestTheInputsCannotBeWritten(unittest.TestCase):
    """The second independent review, closed by prevention rather than sight.

    Its reproduction B is why this class exists: a write made through a
    memory-mapped view need not generate any notification at all, so no
    watcher can be the whole boundary. What closes it is that a writable
    mapping needs a handle with write access, and while the capture holds
    every covered input open with a share mode of FILE_SHARE_READ there
    is no way to get one.
    """

    @WINDOWS_ONLY
    def test_a_check_cannot_open_a_covered_input_for_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            before = (repo / "a.txt").read_bytes()

            capture = run_capture(repo, [_tamper_attempt("handle")], root / "staging")

            self.assertIn("REFUSED", capture.checks[0].tail)
            self.assertEqual((repo / "a.txt").read_bytes(), before)
            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertTrue(capture.boundary.protection["enforced"])

    @WINDOWS_ONLY
    def test_a_check_cannot_map_a_covered_input_writable(self):
        # Reproduction B. Under observation alone this succeeded in
        # silence: no notification, both fingerprints equal, valid bundle.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            before = (repo / "a.txt").read_bytes()

            capture = run_capture(repo, [_tamper_attempt("mmap")], root / "staging")

            self.assertIn("REFUSED", capture.checks[0].tail)
            self.assertNotIn("TAMPERED", capture.checks[0].tail)
            self.assertEqual((repo / "a.txt").read_bytes(), before)
            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)

    @WINDOWS_ONLY
    def test_a_mapped_write_is_invisible_to_the_observer_which_is_why_this_exists(self):
        # A characterisation of the platform, kept deliberately. With
        # prevention disabled the same tamper succeeds and the write
        # stream reports NOTHING, so the capture calls it clean. If
        # Windows ever starts notifying mapped writes this goes red, and
        # that is worth learning rather than worth hiding.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)

            capture = run_capture(repo, [_tamper_attempt("mmap")], root / "staging",
                                  input_lock=_no_prevention)

            self.assertIn("TAMPERED", capture.checks[0].tail)
            self.assertIs(capture.binding.verdict, BindingVerdict.BOUND)
            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertTrue(capture.summary["evidence_valid"],
                            "this is precisely the hole the input lock closes")

    @WINDOWS_ONLY
    def test_a_check_may_still_read_every_covered_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(
                repo,
                [_script("print(open('a.txt', encoding='utf-8').read().strip())")],
                root / "staging")

            self.assertEqual(capture.checks[0].tail, "original")
            self.assertEqual(capture.exit_code, EXIT_OK)
            self.assertTrue(capture.evidence_valid)

    @WINDOWS_ONLY
    def test_an_input_held_open_for_writing_elsewhere_refuses_the_whole_capture(self):
        # Reproductions A1 and B1: the other process already has the
        # handle when the capture starts, so the boundary cannot be built
        # and nothing runs. The handshake is a pipe, not a sleep.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            hold = ("import sys\n"
                    "handle = open(sys.argv[1], 'r+b')\n"
                    "print('HELD', flush=True)\n"
                    "sys.stdin.readline()\n")
            holder = subprocess.Popen(
                [sys.executable, "-c", hold, str(repo / "a.txt")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(holder.stdout.readline().strip(), "HELD")
                capture = run_capture(
                    repo,
                    [_script("open('ran.txt', 'w', encoding='utf-8').write('x')")],
                    root / "staging")
            finally:
                holder.stdin.write("\n")
                holder.stdin.flush()
                holder.wait(timeout=30)

            self.assertIs(capture.boundary.verdict, ObservationVerdict.UNPROTECTED)
            self.assertEqual(capture.exit_code, EXIT_INPUTS_UNPROTECTED)
            self.assertFalse(capture.evidence_valid)
            self.assertEqual(capture.checks, ())
            self.assertFalse((repo / "ran.txt").exists())
            self.assertTrue(any("a.txt" in item for item in capture.boundary.violations))
            self.assertFalse(capture.boundary.protection["enforced"])

    def test_a_lock_that_is_not_there_is_not_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(
                repo, [_script("pass")], root / "staging",
                input_lock=lambda _: UnavailableLock("no lock on this platform"))

            self.assertIs(capture.boundary.verdict, ObservationVerdict.UNPROTECTED)
            self.assertEqual(capture.exit_code, EXIT_INPUTS_UNPROTECTED)
            self.assertFalse(capture.evidence_valid)
            self.assertEqual(capture.checks, ())

    @WINDOWS_ONLY
    def test_the_lock_releases_every_handle_it_took(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            run_capture(repo, [_script("pass")], root / "staging")
            # If one handle had survived the capture, this would raise.
            (repo / "a.txt").write_text("writable again\n", encoding="utf-8")
            self.assertEqual((repo / "a.txt").read_text(encoding="utf-8"),
                             "writable again\n")

    @WINDOWS_ONLY
    def test_the_lock_covers_every_covered_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            (repo / "u.txt").write_text("untracked\n", encoding="utf-8")
            lock = create_input_lock(repo)
            try:
                outcome = lock.acquire(sorted(covered_paths(repo)))
                self.assertTrue(outcome.enforced)
                self.assertEqual(outcome.locked, 2)
                with self.assertRaises(PermissionError):
                    (repo / "u.txt").write_text("changed\n", encoding="utf-8")
            finally:
                lock.release()

    def test_a_refused_lock_is_a_boundary_failure_not_a_check_failure(self):
        boundary = classify_observation(
            Path("."), Observation(True, True, (), "test"), frozenset({"a.txt"}), (),
            LockOutcome(False, 0, ("a.txt (error 32)",), "test", "held open elsewhere"))

        self.assertIs(boundary.verdict, ObservationVerdict.UNPROTECTED)
        self.assertIn("a.txt (error 32)", boundary.violations)
        self.assertFalse(boundary.protection["enforced"])


MEDDLER = REPO / "scripts" / "probe_f14_meddler.py"


class _Meddler:
    """The other process, driven over pipes. No sleeps anywhere."""

    def __init__(self, mode: str, target: Path) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(MEDDLER), mode, str(target)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self._expect("READY")

    def _read(self) -> str:
        return self.process.stdout.readline().strip()

    def _expect(self, prefix: str) -> str:
        line = self._read()
        if not line.startswith(prefix):
            raise RuntimeError(f"expected {prefix}, got {line!r}")
        return line

    def send(self, command: str) -> str:
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()
        return self._read()

    def close(self) -> None:
        try:
            self.send("CLOSE")
        finally:
            self.process.stdin.close()
            self.process.wait(timeout=30)


class _PausingLock:
    """Takes the locks in two halves so a test can act inside the window.

    Acquiring several hundred handles is not instantaneous, and the third
    review asked what happens to a covered input that is modified while
    its turn has not come yet.
    """

    def __init__(self, root: Path, during) -> None:
        self._inner = create_input_lock(root)
        self._during = during

    def acquire(self, paths, directories=()):
        ordered = sorted(paths)
        first = self._inner.acquire(ordered[:1], directories)
        self._during()
        second = self._inner.acquire(ordered[1:], directories)
        identities = dict(first.identities)
        identities.update(second.identities)
        digests = dict(first.content_digests)
        digests.update(second.content_digests)
        return LockOutcome(
            first.enforced and second.enforced, second.locked,
            first.refused + second.refused, first.mechanism,
            first.reason or second.reason, identities, first.volume,
            content_digests=digests)

    def release(self) -> None:
        self._inner.release()


def _repo_with_two_files(root: Path) -> Path:
    repo = _make_repo(root)
    (repo / "b.txt").write_text("second-covered-file\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-m", "second")
    return repo


class TestALiveWritableSectionRefusesTheBoundary(unittest.TestCase):
    """Third review, reproduction A.

    A writable section keeps the underlying file object alive with the
    access it was created through, so the share-mode check still sees a
    writer even when every ordinary handle is gone. If that were not so,
    a view could sit on a covered input with nothing left to conflict
    with, and the lock would report ENFORCED over a file somebody can
    still change.
    """

    def _assert_refused(self, mode: str):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            meddler = _Meddler(mode, repo / "a.txt")
            try:
                opened = meddler.send("OPEN")
                self.assertTrue(opened.startswith("OPENED"), opened)
                capture = run_capture(
                    repo,
                    [_script("open('ran.txt', 'w', encoding='utf-8').write('x')")],
                    root / "staging")
            finally:
                meddler.close()

            self.assertIs(capture.boundary.verdict, ObservationVerdict.UNPROTECTED)
            self.assertEqual(capture.exit_code, EXIT_INPUTS_UNPROTECTED)
            self.assertEqual(capture.checks, ())
            self.assertFalse((repo / "ran.txt").exists())
            self.assertFalse(capture.evidence_valid)
            self.assertTrue(any("a.txt" in item for item in capture.boundary.violations))

    @WINDOWS_ONLY
    def test_a_writable_view_with_the_file_handle_closed_refuses_the_lock(self):
        self._assert_refused("section")

    @WINDOWS_ONLY
    def test_a_writable_view_with_the_mapping_handle_closed_too_refuses_the_lock(self):
        # Only the view is left. Nothing a directory listing or a handle
        # enumeration would show, and still a writer.
        self._assert_refused("section-orphan")

    @WINDOWS_ONLY
    def test_a_duplicated_file_handle_kept_alive_refuses_the_lock(self):
        self._assert_refused("section-dup")


class TestTheProtectedObjectIsTheIdentifiedObject(unittest.TestCase):
    """Third review, B: the handle and the fingerprint must be one object."""

    @WINDOWS_ONLY
    def test_every_protected_handle_is_recorded_by_file_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_two_files(root)
            lock = create_input_lock(repo)
            try:
                outcome = lock.acquire(sorted(covered_paths(repo)))
                self.assertTrue(outcome.enforced)
                self.assertEqual(set(outcome.identities), {"a.txt", "b.txt"})
                for path, identity in outcome.identities.items():
                    with self.subTest(path=path):
                        self.assertRegex(identity, r"\A[0-9a-f]{16}:[0-9a-f]{32}\Z")
                self.assertNotEqual(outcome.identities["a.txt"],
                                    outcome.identities["b.txt"])
                self.assertRegex(outcome.identity_digest, r"\A[0-9a-f]{64}\Z")
            finally:
                lock.release()

    @WINDOWS_ONLY
    def test_the_identities_are_written_into_the_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(repo, [_script("pass")], root / "staging")

            written = json.loads(
                (capture.bundle / "input-identities.json").read_text(encoding="utf-8"))
            self.assertIn("a.txt", written)
            self.assertEqual(capture.boundary.protection["identified_objects"], 1)
            self.assertEqual(capture.boundary.protection["identity_digest"],
                             hash_canonical(sorted(written.items())))

    @WINDOWS_ONLY
    def test_a_hardlink_to_a_covered_input_cannot_be_written_either(self):
        # The share mode belongs to the FILE, not to the name it was
        # opened by, so a second name for the same object is refused too.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            link = root / "outside-link.txt"
            try:
                os.link(repo / "a.txt", link)
            except OSError as exc:  # pragma: no cover - filesystem dependent
                self.skipTest(f"hard links are not available here: {exc}")

            lock = create_input_lock(repo)
            try:
                self.assertTrue(lock.acquire(sorted(covered_paths(repo))).enforced)
                with self.assertRaises(PermissionError):
                    link.write_text("through the other name\n", encoding="utf-8")
            finally:
                lock.release()

    @WINDOWS_ONLY
    def test_a_reparse_point_among_the_covered_inputs_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            link = repo / "link.txt"
            try:
                link.symlink_to(repo / "a.txt")
            except OSError as exc:  # pragma: no cover - needs privilege
                self.skipTest(f"symlinks are not available here: {exc}")

            lock = create_input_lock(repo)
            try:
                outcome = lock.acquire(["a.txt", "link.txt"])
            finally:
                lock.release()

            self.assertFalse(outcome.enforced)
            self.assertTrue(any("reparse" in item for item in outcome.refused))

    @WINDOWS_ONLY
    def test_a_covered_input_deleted_before_its_turn_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_two_files(root)

            def during() -> None:
                (repo / "b.txt").unlink()

            capture = run_capture(
                repo, [_script("pass")], root / "staging",
                input_lock=lambda _: _PausingLock(repo, during))

            self.assertFalse(capture.evidence_valid)
            self.assertEqual(capture.checks, ())


class TestARaceWhileTheBoundaryIsBuilt(unittest.TestCase):
    """Third review, C: the acquisition window is not instantaneous."""

    @WINDOWS_ONLY
    def test_an_input_modified_before_its_turn_and_left_that_way_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_two_files(root)

            def during() -> None:
                (repo / "b.txt").write_text("changed inside the window\n",
                                            encoding="utf-8")

            capture = run_capture(
                repo, [_script("open('ran.txt', 'w', encoding='utf-8').write('x')")],
                root / "staging", input_lock=lambda _: _PausingLock(repo, during))

            self.assertIs(capture.boundary.verdict, ObservationVerdict.PREPARATION_DRIFT)
            self.assertEqual(capture.checks, (), "nothing may run on a tree that moved")
            self.assertFalse((repo / "ran.txt").exists())
            self.assertFalse(capture.evidence_valid)
            self.assertIn("patch_sha256", capture.boundary.violations)
            # The change is still there at the end, so the endpoints
            # disagree as well and the more severe of the two is what the
            # exit code reports. Both facts are in the bundle.
            self.assertEqual(capture.exit_code, EXIT_TREE_MUTATED)
            self.assertIs(capture.binding.verdict, BindingVerdict.TREE_MUTATED)

    def test_preparation_drift_alone_has_its_own_exit_code(self):
        # The same defect with the endpoints agreeing: the tree moved
        # between the fingerprint and the lock and moved back before the
        # end. Only the post-lock identity ever saw it.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            settled = probe_tree_identity(repo)
            drifted = TreeIdentity(True, "a-different-digest", dict(settled.fingerprint))
            answers = [settled, drifted, settled]

            capture = run_capture(
                repo, [_script("open('ran.txt', 'w', encoding='utf-8').write('x')")],
                root / "staging", identity=lambda _: answers.pop(0))

            self.assertIs(capture.binding.verdict, BindingVerdict.BOUND)
            self.assertIs(capture.boundary.verdict, ObservationVerdict.PREPARATION_DRIFT)
            self.assertEqual(capture.exit_code, EXIT_PREPARATION_DRIFT)
            self.assertEqual(capture.checks, ())
            self.assertFalse((repo / "ran.txt").exists())
            self.assertFalse(capture.evidence_valid)

    @WINDOWS_ONLY
    def test_an_input_modified_and_restored_before_its_turn_is_still_not_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_two_files(root)
            original = (repo / "b.txt").read_bytes()

            def during() -> None:
                (repo / "b.txt").write_bytes(b"transient\n")
                (repo / "b.txt").write_bytes(original)

            capture = run_capture(
                repo, [_script("pass")], root / "staging",
                input_lock=lambda _: _PausingLock(repo, during))

            # The post-lock identity matches, so the bytes that would be
            # checked are the bytes named — but the interval was not quiet
            # and the observer says so.
            self.assertFalse(capture.evidence_valid)
            self.assertIs(capture.boundary.verdict, ObservationVerdict.INPUTS_MUTATED)
            self.assertTrue(any("b.txt" in item for item in capture.boundary.violations))

    @WINDOWS_ONLY
    def test_a_quiet_preparation_records_the_identity_of_what_will_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_two_files(root)

            capture = run_capture(repo, [_script("pass")], root / "staging",
                                  input_lock=lambda _: _PausingLock(repo, lambda: None))

            locked = capture.boundary.locked_identity
            self.assertTrue(locked["available"])
            self.assertEqual(locked["digest"], capture.binding.pre.digest)
            self.assertTrue(capture.evidence_valid)


class TestTheVolumeMustDemonstrateWhatIsClaimed(unittest.TestCase):
    """Third review, D: do not extrapolate from one local NTFS volume."""

    @WINDOWS_ONLY
    def test_this_repository_sits_on_a_volume_the_boundary_is_demonstrated_on(self):
        capabilities = probe_volume(REPO)
        self.assertTrue(capabilities.supported, capabilities.reason)
        self.assertEqual(capabilities.drive_type, "fixed")
        # Exactly the demonstrated contract. This used to admit ReFS as an
        # alternative, which let a filesystem nobody had run the boundary
        # on ride along in an assertion that always resolved by NTFS.
        self.assertEqual(capabilities.filesystem, "NTFS")

    @WINDOWS_ONLY
    def test_a_network_volume_is_refused_rather_than_assumed(self):
        capabilities = classify_volume("remote", "NTFS")
        self.assertFalse(capabilities.supported)
        self.assertIn("remote", capabilities.reason or "")

    @WINDOWS_ONLY
    def test_a_filesystem_that_cannot_answer_file_id_is_refused(self):
        for filesystem in ("FAT32", "exFAT", "unknown"):
            with self.subTest(filesystem=filesystem):
                capabilities = classify_volume("fixed", filesystem)
                self.assertFalse(capabilities.supported)
                self.assertIn("FILE_ID_INFO", capabilities.reason or "")

    @WINDOWS_ONLY
    def test_a_local_ntfs_volume_is_accepted(self):
        self.assertTrue(classify_volume("fixed", "NTFS").supported)

    def test_refs_is_a_candidate_and_not_a_guarantee(self):
        # The fourth independent review: the accepted domain was wider
        # than the demonstrated one. ReFS supports FILE_ID_INFO and shares
        # the share-mode model, which is an argument; nobody has ever run
        # the boundary on a ReFS volume, which is the fact that decides.
        capabilities = classify_volume("fixed", "ReFS")

        self.assertFalse(capabilities.supported)
        self.assertEqual(capabilities.filesystem, "ReFS")
        self.assertIn("candidate", capabilities.reason or "")
        self.assertIn("NOT been demonstrated", capabilities.reason or "")

    def test_the_demonstrated_domain_is_exactly_one_filesystem(self):
        self.assertEqual(_SUPPORTED_FILESYSTEMS, frozenset({"NTFS"}))
        self.assertEqual(_SUPPORTED_DRIVE_TYPES, frozenset({"fixed"}))
        self.assertNotIn("ReFS", _SUPPORTED_FILESYSTEMS)

    @WINDOWS_ONLY
    def test_a_refs_volume_locks_nothing_and_runs_nothing(self):
        # Injected, because no ReFS volume exists here — which is the
        # whole point. The refusal comes from the production classifier,
        # not from a hand-made VolumeCapabilities.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            refs = classify_volume("fixed", "ReFS")
            self.assertFalse(refs.supported)

            lock = WindowsInputLock(repo, volume_probe=lambda _: refs)
            try:
                outcome = lock.acquire(sorted(covered_paths(repo)))
            finally:
                lock.release()

            self.assertFalse(outcome.enforced)
            self.assertEqual(outcome.locked, 0, "no input may be opened after the "
                                                "volume is found unsupported")
            self.assertEqual(outcome.identities, {})

            capture = run_capture(
                repo,
                [_script("open('ran.txt', 'w', encoding='utf-8').write('x')")],
                root / "staging",
                input_lock=lambda _: WindowsInputLock(repo, volume_probe=lambda _: refs))

            self.assertIs(capture.boundary.verdict, ObservationVerdict.UNPROTECTED)
            self.assertEqual(capture.exit_code, EXIT_INPUTS_UNPROTECTED)
            self.assertEqual(capture.checks, ())
            self.assertFalse((repo / "ran.txt").exists())
            self.assertFalse(capture.evidence_valid)
            self.assertEqual(capture.boundary.protection["volume"]["filesystem"], "ReFS")
            self.assertFalse(capture.boundary.protection["volume"]["supported"])

    @WINDOWS_ONLY
    def test_the_bundle_records_the_volume_it_was_demonstrated_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(repo, [_script("pass")], root / "staging")

            volume = capture.boundary.protection["volume"]
            self.assertTrue(volume["supported"])
            self.assertEqual(volume["drive_type"], "fixed")
            self.assertEqual(volume["filesystem"], "NTFS")

    @WINDOWS_ONLY
    def test_a_volume_the_boundary_is_not_demonstrated_on_locks_nothing(self):
        # Injected, because this machine has no share to mount. The point
        # is that the refusal happens BEFORE a single handle is taken.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            unsupported = VolumeCapabilities(
                False, "remote", "NTFS", "a network redirector cannot demonstrate it")
            lock = WindowsInputLock(repo, volume_probe=lambda _: unsupported)
            try:
                outcome = lock.acquire(sorted(covered_paths(repo)))
            finally:
                lock.release()

            self.assertFalse(outcome.enforced)
            self.assertEqual(outcome.locked, 0)
            self.assertEqual(outcome.identities, {})
            self.assertIn("network redirector", outcome.reason or "")
            # And the file is still writable, because nothing was locked.
            (repo / "a.txt").write_text("still writable" + chr(10), encoding="utf-8")

    def test_an_unavailable_lock_records_an_unsupported_volume(self):
        outcome = UnavailableLock("no lock on this platform").acquire(["a.txt"])
        self.assertFalse(outcome.enforced)
        self.assertIsNotNone(outcome.volume)
        self.assertFalse(outcome.volume.supported)


class TestNoProtectedHandleEscapesIdentification(unittest.TestCase):
    """Fifth review: a directory handle counted as locked and was never named.

    `CreateFileW` on a covered entry that is a directory failed with
    ERROR_ACCESS_DENIED, the code reopened it with
    FILE_FLAG_BACKUP_SEMANTICS, appended the handle and skipped
    `_identify` altogether. That handle counted towards `locked_inputs`,
    never reached `identities`, and the outcome could still say
    `enforced: true` — against this module's own published guarantee. A
    submodule gitlink is the realistic way to get one, and a handle on a
    submodule's directory says nothing about the bytes inside it.
    """

    @WINDOWS_ONLY
    def test_a_directory_covered_input_is_refused_before_it_is_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            (repo / "subdir").mkdir()

            lock = create_input_lock(repo)
            try:
                outcome = lock.acquire(["a.txt", "subdir"])
            finally:
                lock.release()

            self.assertFalse(outcome.enforced)
            self.assertTrue(any("subdir" in item and "directory-like" in item
                                for item in outcome.refused), outcome.refused)
            self.assertNotIn("subdir", outcome.identities)
            # And the invariant holds even in the refusal: no handle is
            # held that the outcome cannot name.
            self.assertTrue(outcome.fully_identified)
            self.assertEqual(outcome.locked, len(outcome.identities))

    @WINDOWS_ONLY
    def test_a_directory_handle_cannot_pass_as_a_protected_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            (repo / "subdir").mkdir()
            (repo / "subdir" / "inner.txt").write_text("inner\n", encoding="utf-8")

            capture = run_capture(
                repo,
                [_script("open('ran.txt', 'w', encoding='utf-8').write('x')")],
                root / "staging",
                input_lock=lambda _: _LockOver(repo, ["a.txt", "subdir"]))

            self.assertIs(capture.boundary.verdict, ObservationVerdict.UNPROTECTED)
            self.assertEqual(capture.exit_code, EXIT_INPUTS_UNPROTECTED)
            self.assertEqual(capture.checks, ())
            self.assertFalse((repo / "ran.txt").exists())
            self.assertFalse(capture.evidence_valid)
            self.assertFalse(capture.boundary.protection["enforced"])

    @WINDOWS_ONLY
    def test_a_real_submodule_gitlink_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inner = _make_repo(root)
            outer = root / "outer"
            outer.mkdir()
            _git(outer, "init")
            _git(outer, "config", "user.email", "test@example.com")
            _git(outer, "config", "user.name", "Test")
            _git(outer, "config", "commit.gpgsign", "false")
            (outer / "a.txt").write_text("original\n", encoding="utf-8")
            _git(outer, "add", "a.txt")
            _git(outer, "commit", "-m", "init")
            try:
                _git(outer, "-c", "protocol.file.allow=always", "submodule", "add",
                     inner.as_uri(), "sub")
                _git(outer, "commit", "-m", "add submodule")
            except subprocess.CalledProcessError as exc:  # pragma: no cover
                self.skipTest(f"git refused to create a submodule here: {exc}")

            covered = covered_paths(outer)
            self.assertIn("sub", covered, "the gitlink must be a covered path")
            self.assertTrue((outer / "sub").is_dir())

            lock = create_input_lock(outer)
            try:
                outcome = lock.acquire(sorted(covered))
            finally:
                lock.release()

            self.assertFalse(outcome.enforced)
            self.assertTrue(any(item.startswith("sub ") for item in outcome.refused),
                            outcome.refused)
            self.assertNotIn("sub", outcome.identities)
            self.assertTrue(outcome.fully_identified)

            capture = run_capture(
                outer,
                [_script("open('ran.txt', 'w', encoding='utf-8').write('x')")],
                root / "staging")

            self.assertIs(capture.boundary.verdict, ObservationVerdict.UNPROTECTED)
            self.assertEqual(capture.exit_code, EXIT_INPUTS_UNPROTECTED)
            self.assertEqual(capture.checks, ())
            self.assertFalse((outer / "ran.txt").exists())

    @WINDOWS_ONLY
    def test_an_enforced_outcome_identifies_every_handle_it_holds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            (repo / "u.txt").write_text("untracked\n", encoding="utf-8")

            lock = create_input_lock(repo)
            try:
                outcome = lock.acquire(sorted(covered_paths(repo)))
            finally:
                lock.release()

            self.assertTrue(outcome.enforced)
            self.assertEqual(outcome.locked, len(outcome.identities))
            self.assertTrue(outcome.fully_identified)

    def test_an_outcome_holding_an_unnamed_handle_is_not_protection(self):
        # Constructed by hand, because the producer can no longer make
        # one. The consumer refuses it anyway: two readers, same rule.
        # The digests are supplied so that the FILE ID invariant is the
        # one under test here and not the byte invariant beside it.
        inconsistent = LockOutcome(
            True, 3, (), "test", identities={"a.txt": "x"},
            content_digests={"a.txt": "s", "b.txt": "s", "c.txt": "s"})
        self.assertFalse(inconsistent.fully_identified)
        self.assertTrue(inconsistent.fully_bound)

        boundary = classify_observation(
            Path("."), Observation(True, True, (), "test"),
            frozenset({"a.txt"}), (), inconsistent)

        self.assertIs(boundary.verdict, ObservationVerdict.UNPROTECTED)
        self.assertIn("identified", boundary.reason or "")
        self.assertFalse(boundary.protection["fully_identified"])

    def test_an_outcome_holding_an_unhashed_input_is_not_protection(self):
        # The eighth review's invariant, and a DIFFERENT failure from the
        # one above: every handle is named, and the bytes behind them
        # were never hashed.
        unhashed = LockOutcome(
            True, 2, (), "test",
            identities={"a.txt": "x", "b.txt": "y"},
            content_digests={"a.txt": "s"})
        self.assertTrue(unhashed.fully_identified)
        self.assertFalse(unhashed.fully_bound)

        boundary = classify_observation(
            Path("."), Observation(True, True, (), "test"),
            frozenset({"a.txt"}), (), unhashed)

        self.assertIs(boundary.verdict, ObservationVerdict.UNPROTECTED)
        self.assertIn("hashed", boundary.reason or "")
        self.assertFalse(boundary.protection["fully_bound"])

    @WINDOWS_ONLY
    def test_an_input_on_another_volume_is_refused(self):
        # Injected serial, because this machine has one volume. A junction
        # or mount point ABOVE a covered path is what would really do
        # this, and the per-path reparse check cannot see it.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            lock = WindowsInputLock(repo, expected_serial=0xDEADBEEFDEADBEEF)
            try:
                outcome = lock.acquire(sorted(covered_paths(repo)))
            finally:
                lock.release()

            self.assertFalse(outcome.enforced)
            self.assertTrue(any("not the probed volume" in item
                                for item in outcome.refused), outcome.refused)
            self.assertEqual(outcome.identities, {})

    @WINDOWS_ONLY
    def test_a_covered_file_under_an_ancestor_junction_is_refused(self):
        # This test asserted the opposite until the sixth review, and the
        # thing it asserted was the defect: the object was identified and
        # locked, its serial matched, and the PATH used to reach it could
        # still be pointed at a different directory. Holding the object
        # does not hold the name.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            real = root / "elsewhere"
            real.mkdir()
            (real / "under.txt").write_text("via a junction\n", encoding="utf-8")
            link = repo / "linked"
            if not _junction(link, real):  # pragma: no cover - needs the privilege
                self.skipTest("junctions are not available here")

            lock = WindowsInputLock(repo)
            try:
                outcome = lock.acquire(["a.txt", "linked/under.txt"])
            finally:
                lock.release()
                link.rmdir()

            self.assertFalse(outcome.enforced)
            self.assertNotIn("linked/under.txt", outcome.identities)
            self.assertTrue(any("ancestor linked is a reparse point" in item
                                for item in outcome.refused), outcome.refused)
            # The plain sibling is not collateral damage: it is refused
            # only because the whole acquisition is, and it was never
            # identified as protected on its own.
            self.assertTrue(outcome.fully_identified)


def _write_stream(target: Path, name: str, text: str) -> None:
    """A named data stream is a path with a colon in it, nothing more."""
    with open(f"{target}:{name}", "w", encoding="utf-8") as handle:
        handle.write(text)


def _read_stream(target: Path, name: str) -> str:
    with open(f"{target}:{name}", encoding="utf-8") as handle:
        return handle.read()


def _reads_stream(relative: str, name: str) -> CheckCommand:
    """A check whose RESULT depends on bytes outside the main stream."""
    return _script(
        "import sys",
        f"print(open({relative!r} + ':' + {name!r}, encoding='utf-8').read().strip())",
    )


@contextlib.contextmanager
def _no_stream_enumeration():
    """Make `named_streams` fail, so the refusal path is reachable here.

    Every path on this volume answers, and a guarantee whose refusal
    branch cannot be run on the machine that has only the working case is
    untested where it matters. Same reasoning as the injected volume
    probe in the fourth review.
    """
    original = input_lock_module.named_streams
    input_lock_module.named_streams = lambda _target: None
    try:
        yield
    finally:
        input_lock_module.named_streams = original


def _manifest(capture) -> dict:
    return json.loads(
        (capture.bundle / "input-manifest.json").read_text(encoding="utf-8"))


class _ForgetfulLock:
    """The real lock with the hashes thrown away after the fact.

    The producer cannot build this any more — the byte invariant refuses
    before `acquire` returns — so the only way to ask the CONSUMER the
    review's eleventh question is to hand it an outcome that is enforced,
    fully identified, and missing the digests.
    """

    def __init__(self, root: Path) -> None:
        self._inner = create_input_lock(root)

    def acquire(self, paths, directories=()):
        outcome = self._inner.acquire(paths, directories)
        return LockOutcome(
            outcome.enforced, outcome.locked, outcome.refused, outcome.mechanism,
            outcome.reason, identities=dict(outcome.identities),
            volume=outcome.volume, content_digests={})

    def release(self) -> None:
        self._inner.release()


class _LockOver:
    """The real lock, over a caller-chosen set of covered paths."""

    def __init__(self, root: Path, paths: list[str]) -> None:
        self._inner = create_input_lock(root)
        self._paths = paths

    def acquire(self, paths, directories=()):
        return self._inner.acquire(self._paths, directories)

    def release(self) -> None:
        self._inner.release()


def _junction(link: Path, target: Path) -> bool:
    """A directory junction, which needs no elevation on Windows.

    `errors="replace"`: mklink answers in the console codepage, which is
    not UTF-8 on this machine.
    """
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                          capture_output=True, text=True, errors="replace", check=False)
    return made.returncode == 0


class TestAnAncestorCannotRedirectTheInput(unittest.TestCase):
    """Sixth review: the lock held the object and not the name.

    A junction is a directory entry. A handle on a file underneath it
    stops the FILE being written, renamed or deleted, and does nothing at
    all about the junction, which can be removed and recreated against
    another directory while a check reads the lexical path. Both
    directories can sit on the same NTFS volume, so the file id's volume
    serial cannot see it either.
    """

    @WINDOWS_ONLY
    def test_the_retarget_attack_is_refused_before_any_check_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            first, second = root / "dirA", root / "dirB"
            first.mkdir()
            second.mkdir()
            (first / "under.py").write_text("ORIGINAL-A\n", encoding="utf-8")
            (second / "under.py").write_text("SWAPPED-B\n", encoding="utf-8")
            link = repo / "linked"
            if not _junction(link, first):  # pragma: no cover
                self.skipTest("junctions are not available here")

            try:
                capture = run_capture(
                    repo,
                    [_script("open('ran.txt', 'w', encoding='utf-8').write('x')")],
                    root / "staging",
                    input_lock=lambda _: _LockOver(repo, ["a.txt", "linked/under.py"]))

                self.assertIs(capture.boundary.verdict, ObservationVerdict.UNPROTECTED)
                self.assertEqual(capture.exit_code, EXIT_INPUTS_UNPROTECTED)
                self.assertEqual(capture.checks, ())
                self.assertFalse((repo / "ran.txt").exists())
                self.assertFalse(capture.evidence_valid)
                self.assertFalse(capture.boundary.protection["enforced"])

                # And the attack the refusal exists for is real on this
                # platform, not hypothetical: the junction retargets while
                # a handle on dirA/under.py is held, and the lexical path
                # then reads the other directory.
                held = WindowsInputLock(repo)
                self.assertTrue(held.acquire(["a.txt"]).enforced)
                try:
                    keep = open(first / "under.py", "rb")  # noqa: SIM115
                    try:
                        link.rmdir()
                        self.assertTrue(_junction(link, second))
                        self.assertEqual(
                            (link / "under.py").read_text(encoding="utf-8").strip(),
                            "SWAPPED-B", "the retarget is possible on this platform")
                        link.rmdir()
                        self.assertTrue(_junction(link, first))
                        self.assertEqual(
                            (link / "under.py").read_text(encoding="utf-8").strip(),
                            "ORIGINAL-A", "and it restores invisibly")
                    finally:
                        keep.close()
                finally:
                    held.release()
            finally:
                if link.exists():
                    link.rmdir()

    @WINDOWS_ONLY
    def test_a_root_reached_through_a_junction_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            door = root / "door"
            if not _junction(door, repo):  # pragma: no cover
                self.skipTest("junctions are not available here")

            lock = WindowsInputLock(door)
            try:
                outcome = lock.acquire(["a.txt"])
            finally:
                lock.release()
                door.rmdir()

            self.assertFalse(outcome.enforced)
            self.assertEqual(outcome.locked, 0)
            self.assertEqual(outcome.identities, {})
            self.assertIn("reached through a redirection", outcome.reason or "")

    @WINDOWS_ONLY
    def test_a_plain_chain_is_still_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            (repo / "pkg").mkdir()
            (repo / "pkg" / "deep.txt").write_text("deep\n", encoding="utf-8")

            lock = WindowsInputLock(repo)
            try:
                outcome = lock.acquire(["a.txt", "pkg/deep.txt"])
            finally:
                lock.release()

            self.assertTrue(outcome.enforced, outcome.refused)
            self.assertEqual(set(outcome.identities), {"a.txt", "pkg/deep.txt"})

    def test_the_chain_walker_names_the_component_that_redirects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real"
            real.mkdir()
            link = root / "link"
            if not _junction(link, real):  # pragma: no cover
                self.skipTest("junctions are not available here")
            try:
                self.assertIsNone(reparse_in_chain(real))
                found = reparse_in_chain(link / "deeper")
                self.assertIsNotNone(found)
                self.assertIn("reparse point", found or "")
            finally:
                link.rmdir()


class TestStructuralDirectoryEventsAreJudged(unittest.TestCase):
    """Sixth review, second half: `is_dir()` at the END forgave too much.

    A directory's timestamp moves whenever its entries move, so a
    `modified` event on one is noise. Creating, removing or renaming a
    directory is not noise, and the classifier used to allow all four
    actions purely because the path happened to be a directory again by
    the time it looked — which is precisely what a junction removed and
    recreated against another target leaves behind.
    """

    def _classify(self, repo: Path, events: tuple[WriteEvent, ...]) -> Boundary:
        return classify_observation(
            repo, Observation(True, True, events, "test"), frozenset({"a.txt"}), (),
            LockOutcome(True, 1, (), "test", identities={"a.txt": "id"},
                        content_digests={"a.txt": "sha"}))

    def test_a_directory_removed_and_recreated_is_a_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            (repo / "linked").mkdir()

            boundary = self._classify(repo, (
                WriteEvent("removed", "linked"),
                WriteEvent("added", "linked"),
            ))

            self.assertIs(boundary.verdict, ObservationVerdict.INPUTS_MUTATED)
            self.assertTrue(any("linked" in item for item in boundary.violations))

    def test_a_directory_renamed_and_restored_is_a_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            (repo / "linked").mkdir()

            boundary = self._classify(repo, (
                WriteEvent("renamed_from", "linked"),
                WriteEvent("renamed_to", "linked"),
            ))

            self.assertIs(boundary.verdict, ObservationVerdict.INPUTS_MUTATED)

    def test_a_directory_whose_timestamp_moved_is_still_forgiven(self):
        # The false positive this branch exists to avoid: every child
        # write bumps the container's timestamp, and the child has its
        # own event.
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            (repo / "linked").mkdir()

            boundary = self._classify(repo, (WriteEvent("modified", "linked"),))

            self.assertIs(boundary.verdict, ObservationVerdict.CLEAN)
            self.assertEqual(boundary.allowed_events, 1)

    def test_a_declared_output_directory_created_during_a_run_is_allowed(self):
        # Was "an ignored directory ... is still allowed". Being ignored
        # is not the authority any more; the declaration is.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            (repo / ".gitignore").write_text(".mypy_cache/\n", encoding="utf-8")
            _git(repo, "add", ".gitignore")
            _git(repo, "commit", "-m", "ignore the cache")

            capture = run_capture(repo, [_script(
                "import os",
                "os.makedirs('.mypy_cache', exist_ok=True)",
                "open('.mypy_cache/data.json', 'w', encoding='utf-8').write('{}\\n')",
            )], root / "staging", allowed_writes=(".mypy_cache/",))

            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertTrue(capture.evidence_valid)

    def test_a_directory_created_and_removed_during_a_check_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)

            capture = run_capture(repo, [_script(
                "import os",
                "os.mkdir('ghostdir')",
                "os.rmdir('ghostdir')",
            )], root / "staging")

            self.assertIs(capture.boundary.verdict, ObservationVerdict.INPUTS_MUTATED)
            self.assertEqual(capture.exit_code, EXIT_INPUTS_MUTATED)
            self.assertFalse(capture.evidence_valid)
            self.assertTrue(any("ghostdir" in item
                                for item in capture.boundary.violations))


def _repo_with_ignored_input(root: Path, name: str = "repo") -> Path:
    """A repo whose real input git has been told to ignore."""
    repo = root / name
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / ".gitignore").write_text("ignored-input.txt\nbuild-cache/\n",
                                     encoding="utf-8")
    (repo / "a.txt").write_text("tracked\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "a.txt")
    _git(repo, "commit", "-m", "init")
    (repo / "ignored-input.txt").write_text("ORIGINAL\n", encoding="utf-8")
    return repo


IGNORED_ABA = (
    "import os\n"
    "try:\n"
    "    handle = open('ignored-input.txt', 'r+b')\n"
    "except OSError as exc:\n"
    "    print('REFUSED', type(exc).__name__)\n"
    "else:\n"
    "    original = handle.read()\n"
    "    handle.seek(0)\n"
    "    handle.write(b'MALICIOUS')\n"
    "    handle.flush()\n"
    "    print('READ', open('ignored-input.txt', encoding='utf-8').read().strip())\n"
    "    handle.seek(0)\n"
    "    handle.write(original)\n"
    "    handle.close()\n"
)


class TestIgnoredFilesAreNotOutsideTheBoundary(unittest.TestCase):
    """Seventh review: `git ignores it` was being used as authority.

    An ignored file can be a real input — a `.env`, a local config, a
    fixture, a database, or the interpreter and tools in `.venv`. The
    reproduction that opened this round had a check read MALICIOUS out of
    an ignored file while the bundle reported CLEAN, evidence_valid true
    and all_passed true.
    """

    def test_the_input_domain_includes_ignored_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _repo_with_ignored_input(Path(tmp))

            covered = covered_paths(repo)

            self.assertIn("ignored-input.txt", covered)
            self.assertIn("a.txt", covered)

    def test_a_declared_output_root_is_not_an_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _repo_with_ignored_input(Path(tmp))
            (repo / "build-cache").mkdir()
            (repo / "build-cache" / "x.bin").write_text("cache\n", encoding="utf-8")

            covered = covered_paths(repo, ("build-cache/",))

            self.assertNotIn("build-cache/x.bin", covered)
            self.assertIn("ignored-input.txt", covered)

    def test_an_ignored_nested_clone_is_expanded_rather_than_dropped(self):
        # git reports a nested repository as one directory entry and will
        # not descend into it. The eighth review's point: git declining to
        # look is not a reason for the evidence to decline too.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)
            nested = repo / "vendor" / "clone"
            nested.mkdir(parents=True)
            _git(nested, "init")
            (nested / "code.py").write_text("vendored\n", encoding="utf-8")
            (repo / ".gitignore").write_text(
                "ignored-input.txt\nbuild-cache/\nvendor/\n", encoding="utf-8")

            covered = covered_paths(repo)

            self.assertIn("vendor/clone/code.py", covered)
            self.assertFalse(any(path.endswith("/") for path in covered))

    def test_the_two_classes_are_decided_by_declaration_not_by_git(self):
        outputs = (".mypy_cache/", "__pycache__")
        self.assertIs(classify_path("src/a.py", outputs), PathClass.INPUT)
        self.assertIs(classify_path(".env", outputs), PathClass.INPUT)
        self.assertIs(classify_path("external/repo/a", outputs), PathClass.INPUT)
        self.assertIs(classify_path(".mypy_cache/x", outputs), PathClass.OUTPUT)
        self.assertIs(classify_path("src/__pycache__/a.pyc", outputs), PathClass.OUTPUT)

    def test_there_is_no_class_for_bytes_the_evidence_cannot_state(self):
        # The eighth review removed the third one. Whatever a caller
        # declares, a path is either an INPUT or an OUTPUT.
        self.assertEqual({member.name for member in PathClass}, {"INPUT", "OUTPUT"})

    # -- A ------------------------------------------------------------------
    @WINDOWS_ONLY
    def test_an_ignored_input_a_check_reads_is_locked_against_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)
            before = (repo / "ignored-input.txt").read_bytes()

            capture = run_capture(
                repo, [CheckCommand("check", (sys.executable, "-c", IGNORED_ABA))],
                root / "staging")

            self.assertIn("REFUSED", capture.checks[0].tail)
            self.assertEqual((repo / "ignored-input.txt").read_bytes(), before)
            self.assertEqual(capture.boundary.protection["locked_inputs"], 3)
            self.assertEqual(capture.boundary.protection["identified_objects"], 3)

    # -- B ------------------------------------------------------------------
    @WINDOWS_ONLY
    def test_an_ignored_input_aba_cannot_produce_valid_evidence(self):
        # With prevention off, so the OBSERVATION half is the one under
        # test: the write succeeds and must still invalidate.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)

            capture = run_capture(
                repo, [CheckCommand("check", (sys.executable, "-c", IGNORED_ABA))],
                root / "staging", input_lock=_no_prevention)

            self.assertIn("READ MALICIOUS", capture.checks[0].tail)
            self.assertIs(capture.binding.verdict, BindingVerdict.BOUND)
            self.assertIs(capture.boundary.verdict, ObservationVerdict.INPUTS_MUTATED)
            self.assertFalse(capture.evidence_valid)
            self.assertFalse(capture.summary["all_passed"])
            self.assertTrue(any("ignored-input.txt" in item
                                for item in capture.boundary.violations))

    # -- C ------------------------------------------------------------------
    @WINDOWS_ONLY
    def test_an_ignored_file_created_during_a_run_is_not_silently_an_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)
            (repo / ".gitignore").write_text(
                "ignored-input.txt\nbuild-cache/\nlate.txt\n", encoding="utf-8")
            _git(repo, "commit", "-am", "ignore late.txt")

            capture = run_capture(repo, [_script(
                "open('late.txt', 'w', encoding='utf-8').write('APPEARED\\n')",
                "print(open('late.txt', encoding='utf-8').read().strip())",
            )], root / "staging")

            self.assertIs(capture.boundary.verdict, ObservationVerdict.INPUTS_MUTATED)
            self.assertFalse(capture.evidence_valid)
            self.assertTrue(any("late.txt" in item
                                for item in capture.boundary.violations))

    # -- D ------------------------------------------------------------------
    @WINDOWS_ONLY
    def test_an_ignored_input_deleted_and_recreated_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)

            capture = run_capture(repo, [_script(
                "import os",
                "os.remove('ignored-input.txt')",
                "open('ignored-input.txt', 'w', encoding='utf-8').write('ORIGINAL\\n')",
            )], root / "staging", input_lock=_no_prevention)

            self.assertIs(capture.boundary.verdict, ObservationVerdict.INPUTS_MUTATED)
            self.assertFalse(capture.evidence_valid)

    @WINDOWS_ONLY
    def test_an_ignored_input_cannot_be_deleted_while_it_is_locked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)

            capture = run_capture(repo, [_script(
                "import os",
                "try:",
                "    os.remove('ignored-input.txt')",
                "    print('DELETED')",
                "except OSError as exc:",
                "    print('REFUSED', type(exc).__name__)",
            )], root / "staging")

            self.assertIn("REFUSED", capture.checks[0].tail)
            self.assertTrue((repo / "ignored-input.txt").exists())

    # -- E ------------------------------------------------------------------
    @WINDOWS_ONLY
    def test_a_declared_cache_may_change_without_invalidating_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)
            (repo / "build-cache").mkdir()
            (repo / "build-cache" / "x.bin").write_text("before\n", encoding="utf-8")

            capture = run_capture(repo, [_script(
                "open('build-cache/x.bin', 'w', encoding='utf-8').write('after\\n')",
                "open('build-cache/y.bin', 'w', encoding='utf-8').write('new\\n')",
            )], root / "staging", allowed_writes=("build-cache/",))

            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertTrue(capture.evidence_valid)
            self.assertEqual(capture.exit_code, EXIT_OK)

    # -- F ------------------------------------------------------------------
    @WINDOWS_ONLY
    def test_an_undeclared_ignored_path_is_not_authorised_by_gitignore(self):
        # The same writes as the test above, with the declaration removed.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)
            (repo / "build-cache").mkdir()
            (repo / "build-cache" / "x.bin").write_text("before\n", encoding="utf-8")

            capture = run_capture(repo, [_script(
                "try:",
                "    open('build-cache/x.bin', 'w', encoding='utf-8').write('after\\n')",
                "    print('WROTE')",
                "except OSError as exc:",
                "    print('REFUSED', type(exc).__name__)",
            )], root / "staging")

            # It is a covered input now, so the write is refused outright.
            self.assertIn("REFUSED", capture.checks[0].tail)
            self.assertIn("build-cache/x.bin", covered_paths(repo))

    @WINDOWS_ONLY
    def test_a_root_nobody_declared_is_an_input_and_therefore_locked(self):
        # What used to be declarable as out of scope is simply an INPUT.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)
            (repo / "build-cache").mkdir()
            (repo / "build-cache" / "x.bin").write_text("before\n", encoding="utf-8")

            capture = run_capture(repo, [_script(
                "try:",
                "    open('build-cache/x.bin', 'w', encoding='utf-8').write('after\\n')",
                "    print('WROTE')",
                "except OSError as exc:",
                "    print('REFUSED', type(exc).__name__)",
            )], root / "staging")

            self.assertIn("REFUSED", capture.checks[0].tail)
            manifest = json.loads(
                (capture.bundle / "input-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("build-cache/x.bin", manifest["inputs"])

    def test_the_bundle_records_the_declared_classes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)

            capture = run_capture(repo, [_script("pass")], root / "staging",
                                  allowed_writes=("build-cache/",))

            written = json.loads(
                (capture.bundle / "SUMMARY.json").read_text(encoding="utf-8"))
            boundary = written["boundary"]
            self.assertIn("build-cache/", boundary["allowed_writes"])
            self.assertIn("git check-ignore is not consulted",
                          boundary["input_policy"])
            self.assertIn("no unbound class", boundary["input_policy"])

    def test_the_capture_script_declares_only_outputs(self):
        path = REPO / "scripts" / "capture_evidence.py"
        spec = importlib.util.spec_from_file_location("capture_policy_under_test", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"{path} could not be loaded")
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)

        self.assertIn(".git/", script.ALLOWED_WRITES)
        self.assertIn("__pycache__", script.ALLOWED_WRITES)
        # There is no second list any more, and .venv is in neither: the
        # toolchain is an INPUT, locked and hashed like everything else.
        self.assertFalse(hasattr(script, "OUT_OF_SCOPE"))
        self.assertNotIn(".venv/", script.ALLOWED_WRITES)
        self.assertNotIn("external/repositories/", script.ALLOWED_WRITES)


class TestEveryInputIsByteBound(unittest.TestCase):
    """Eighth review: a file id is not a content identity, and neither is a lock.

    An object identity says WHICH file. A lock says it did not change
    while the checks ran. Only a hash says WHAT was in it, and only a
    hash lets a third party re-derive the claim from the files instead of
    believing the bundle.
    """

    @staticmethod
    def _capture(root: Path, name: str, contents: str, **kwargs):
        repo = _repo_with_ignored_input(root, name)
        (repo / "ignored-input.txt").write_text(contents, encoding="utf-8")
        return run_capture(repo, [_script("pass")], root / f"s-{name}", **kwargs), repo

    # -- 9 ------------------------------------------------------------------
    @WINDOWS_ONLY
    def test_same_path_and_metadata_different_bytes_differ_in_identity(self):
        # Two fixtures a metadata-based identity cannot tell apart: same
        # relative path, same size, same timestamps, and each file id is
        # valid for its own volume. Only the bytes differ.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, first_repo = self._capture(root, "one", "AAAAAAAA\n")
            stat = (first_repo / "ignored-input.txt").stat()
            second, second_repo = self._capture(root, "two", "BBBBBBBB\n")
            os.utime(second_repo / "ignored-input.txt", (stat.st_atime, stat.st_mtime))

            first_manifest = json.loads(
                (first.bundle / "input-manifest.json").read_text(encoding="utf-8"))
            second_manifest = json.loads(
                (second.bundle / "input-manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(
                (first_repo / "ignored-input.txt").stat().st_size,
                (second_repo / "ignored-input.txt").stat().st_size)
            self.assertNotEqual(
                first_manifest["inputs"]["ignored-input.txt"],
                second_manifest["inputs"]["ignored-input.txt"])
            self.assertNotEqual(
                first.boundary.protection["content_digest"],
                second.boundary.protection["content_digest"])

    # -- 10 -----------------------------------------------------------------
    @WINDOWS_ONLY
    def test_changing_the_bytes_between_captures_changes_the_durable_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)

            before = run_capture(repo, [_script("pass")], root / "before")
            (repo / "ignored-input.txt").write_text("CHANGED\n", encoding="utf-8")
            after = run_capture(repo, [_script("pass")], root / "after")

            self.assertTrue(before.evidence_valid)
            self.assertTrue(after.evidence_valid)
            self.assertNotEqual(before.boundary.protection["content_digest"],
                                after.boundary.protection["content_digest"])
            # And the file id did NOT have to change for that to be true.
            self.assertEqual(before.boundary.protection["identified_objects"],
                             after.boundary.protection["identified_objects"])

    # -- 11 -----------------------------------------------------------------
    @WINDOWS_ONLY
    def test_a_locked_but_unhashed_input_cannot_produce_valid_evidence(self):
        # End to end, not at the classifier: the capture that holds an
        # ignored input by a named handle and never hashed it is not
        # allowed to call itself evidence, and it says which of the two
        # invariants it failed.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)

            capture = run_capture(repo, [_script("pass")], root / "staging",
                                  input_lock=lambda _: _ForgetfulLock(repo))

            self.assertFalse(capture.evidence_valid)
            self.assertIs(capture.boundary.verdict, ObservationVerdict.UNPROTECTED)
            self.assertIn("hashed", capture.boundary.reason or "")
            self.assertTrue(capture.boundary.protection["fully_identified"])
            self.assertFalse(capture.boundary.protection["fully_bound"])
            self.assertEqual(capture.exit_code, 6)

    # -- 12 -----------------------------------------------------------------
    @WINDOWS_ONLY
    def test_a_toolchain_artefact_is_an_input_and_its_bytes_are_bound(self):
        # .venv stays INPUT rather than becoming a fourth class, so this
        # is the same rule as everything else: change one byte of a tool
        # and the identity changes.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)
            (repo / ".gitignore").write_text(
                "ignored-input.txt\nbuild-cache/\n.venv/\n", encoding="utf-8")
            venv = repo / ".venv" / "Lib"
            venv.mkdir(parents=True)
            (venv / "tool.py").write_text("VERSION = '1.0'\n", encoding="utf-8")

            before = run_capture(repo, [_script("pass")], root / "before")
            manifest = json.loads(
                (before.bundle / "input-manifest.json").read_text(encoding="utf-8"))
            self.assertIn(".venv/Lib/tool.py", manifest["inputs"])

            # Same declared version, one different byte.
            (venv / "tool.py").write_text("VERSION = '1.O'\n", encoding="utf-8")
            after = run_capture(repo, [_script("pass")], root / "after")

            self.assertNotEqual(before.boundary.protection["content_digest"],
                                after.boundary.protection["content_digest"])

    # -- 14 -----------------------------------------------------------------
    @WINDOWS_ONLY
    def test_a_check_depending_on_a_formerly_unclaimed_file_reads_named_bytes(self):
        # There is no out-of-scope class to hide in any more. A nested
        # clone git will not descend into is expanded, locked and hashed,
        # so a check that reads it reads bytes the evidence states.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)
            (repo / ".gitignore").write_text(
                "ignored-input.txt\nbuild-cache/\nvendor/\n", encoding="utf-8")
            nested = repo / "vendor" / "clone"
            nested.mkdir(parents=True)
            _git(nested, "init")
            (nested / "data.txt").write_text("VENDORED\n", encoding="utf-8")

            capture = run_capture(repo, [_script(
                "print(open('vendor/clone/data.txt', encoding='utf-8').read().strip())",
            )], root / "staging")

            self.assertEqual(capture.checks[0].tail, "VENDORED")
            manifest = json.loads(
                (capture.bundle / "input-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("vendor/clone/data.txt", manifest["inputs"])
            self.assertRegex(manifest["inputs"]["vendor/clone/data.txt"],
                             r"\A[0-9a-f]{64}\Z")

    # -- 15 -----------------------------------------------------------------
    @WINDOWS_ONLY
    def test_content_planted_under_an_output_root_is_still_named(self):
        # The OUTPUT escape must not become a way to introduce an
        # unidentified prior input: whatever already exists under an
        # output root when the capture begins is hashed.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)
            (repo / "build-cache").mkdir()
            (repo / "build-cache" / "planted.txt").write_text(
                "PLANTED\n", encoding="utf-8")

            capture = run_capture(repo, [_script(
                "print(open('build-cache/planted.txt', encoding='utf-8').read().strip())",
            )], root / "staging", allowed_writes=("build-cache/",))

            self.assertEqual(capture.checks[0].tail, "PLANTED")
            manifest = json.loads(
                (capture.bundle / "input-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("build-cache/planted.txt", manifest["outputs_at_start"])
            self.assertRegex(manifest["outputs_at_start"]["build-cache/planted.txt"],
                             r"\A[0-9a-f]{64}\Z")

    # -- the manifest itself -------------------------------------------------
    @WINDOWS_ONLY
    def test_the_manifest_is_re_derivable_from_the_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)

            capture = run_capture(repo, [_script("pass")], root / "staging")

            manifest = json.loads(
                (capture.bundle / "input-manifest.json").read_text(encoding="utf-8"))
            for relative, recorded in manifest["inputs"].items():
                with self.subTest(path=relative):
                    self.assertEqual(
                        hashlib.sha256((repo / relative).read_bytes()).hexdigest(),
                        recorded)
            self.assertEqual(capture.boundary.protection["content_digest"],
                             hash_canonical(sorted(manifest["inputs"].items())))

    @WINDOWS_ONLY
    def test_every_locked_input_is_hashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _repo_with_ignored_input(root)

            capture = run_capture(repo, [_script("pass")], root / "staging")
            protection = capture.boundary.protection

            self.assertEqual(protection["locked_inputs"],
                             protection["byte_bound_inputs"])
            self.assertTrue(protection["fully_bound"])
            self.assertNotEqual(protection["content_digest"],
                                protection["identity_digest"])


class TestNamedDataStreamsAreNotASecondChannel(unittest.TestCase):
    """Ninth review: a path is not one stream, and `git` cannot see the rest.

    On NTFS a file is `::$DATA` plus any number of named streams, each
    openable as `path:name`, each readable by a check. Reproduced before
    anything changed: the same main stream with `probe.txt:gnosis-f14`
    flipped from ALLOW to DENY produced a check that read different bytes
    and two bundles whose `identity_digest` and `content_digest` were
    byte-identical, both `evidence_valid` true.

    Directories carry them too, and a handle on the main stream protects
    only the main stream. Both measured, both repaired here.
    """

    def _repo(self, root: Path, name: str = "repo") -> Path:
        return _repo_with_ignored_input(root, name)

    # -- 1 -------------------------------------------------------------------
    @WINDOWS_ONLY
    def test_same_main_stream_different_ads_cannot_share_an_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._repo(root, "one")
            _write_stream(first / "a.txt", "side", "ALLOW")
            second = self._repo(root, "two")
            _write_stream(second / "a.txt", "side", "DENY!")

            left = run_capture(first, [_script("pass")], root / "s1")
            right = run_capture(second, [_script("pass")], root / "s2")

            # The main streams really are identical, byte for byte.
            self.assertEqual((first / "a.txt").read_bytes(),
                             (second / "a.txt").read_bytes())
            self.assertEqual(_manifest(left)["inputs"]["a.txt"],
                             _manifest(right)["inputs"]["a.txt"])
            # And the evidence still tells them apart.
            self.assertNotEqual(left.boundary.protection["content_digest"],
                                right.boundary.protection["content_digest"])
            self.assertNotEqual(_manifest(left)["inputs"]["a.txt:side"],
                                _manifest(right)["inputs"]["a.txt:side"])

    # -- 2 -------------------------------------------------------------------
    @WINDOWS_ONLY
    def test_changing_only_an_ads_changes_the_durable_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            _write_stream(repo / "a.txt", "side", "ALLOW")

            before = run_capture(repo, [_script("pass")], root / "before")
            main_before = (repo / "a.txt").read_bytes()
            _write_stream(repo / "a.txt", "side", "DENY!")
            after = run_capture(repo, [_script("pass")], root / "after")

            self.assertEqual(main_before, (repo / "a.txt").read_bytes())
            self.assertTrue(before.evidence_valid)
            self.assertTrue(after.evidence_valid)
            self.assertNotEqual(before.boundary.protection["content_digest"],
                                after.boundary.protection["content_digest"])
            # And the review's own point 6, demonstrated rather than
            # asserted: "ALLOW" and "DENY!" are both five bytes of the
            # same stream of the same object, so owner id, stream name
            # and LENGTH are all unchanged. The identity digest cannot
            # tell them apart and is not asked to. Only the bytes can.
            self.assertEqual(before.boundary.protection["identity_digest"],
                             after.boundary.protection["identity_digest"])

            # A length change does move it, which is what makes the
            # inventory a usable second detector.
            _write_stream(repo / "a.txt", "side", "LONGER THAN BEFORE")
            longer = run_capture(repo, [_script("pass")], root / "longer")
            self.assertNotEqual(before.boundary.protection["identity_digest"],
                                longer.boundary.protection["identity_digest"])

    # -- 3 -------------------------------------------------------------------
    @WINDOWS_ONLY
    def test_a_check_reading_an_ads_reads_bytes_the_manifest_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            _write_stream(repo / "ignored-input.txt", "gnosis-f14", "ALLOW")

            capture = run_capture(
                repo, [_reads_stream("ignored-input.txt", "gnosis-f14")],
                root / "staging")

            self.assertEqual(capture.checks[0].tail, "ALLOW")
            recorded = _manifest(capture)["inputs"]["ignored-input.txt:gnosis-f14"]
            self.assertEqual(
                hashlib.sha256(b"ALLOW").hexdigest(), recorded,
                "the bytes the check read are not the bytes the evidence names")

    # -- 4 -------------------------------------------------------------------
    @WINDOWS_ONLY
    def test_an_ads_created_before_the_capture_is_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            _write_stream(repo / "a.txt", "planted", "PLANTED BEFORE")

            capture = run_capture(repo, [_script("pass")], root / "staging")
            protection = capture.boundary.protection
            inputs = _manifest(capture)["inputs"]

            self.assertIn("a.txt:planted", inputs)
            self.assertEqual(hashlib.sha256(b"PLANTED BEFORE").hexdigest(),
                             inputs["a.txt:planted"])
            self.assertTrue(protection["fully_bound"])
            self.assertEqual(protection["locked_inputs"],
                             protection["byte_bound_inputs"])
            # The identity names owner, stream and length, because a file
            # id alone is the same for every stream of one file.
            identities = json.loads(
                (capture.bundle / "input-identities.json").read_text(encoding="utf-8"))
            self.assertRegex(identities["a.txt:planted"],
                             r"\A[0-9a-f]{16}:[0-9a-f]+:planted:14\Z")

    # -- 5 -------------------------------------------------------------------
    @WINDOWS_ONLY
    def test_modifying_an_ads_during_the_interval_is_prevented(self):
        # Prevention, not detection: the stream has its own handle now.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            _write_stream(repo / "a.txt", "side", "ORIGINAL")

            lock = create_input_lock(repo)
            try:
                outcome = lock.acquire(sorted(covered_paths(repo)))
                self.assertTrue(outcome.enforced)
                with self.assertRaises(PermissionError):
                    _write_stream(repo / "a.txt", "side", "TAMPERED")
                with self.assertRaises(PermissionError):
                    os.remove(f"{repo / 'a.txt'}:side")
            finally:
                lock.release()

            self.assertEqual(_read_stream(repo / "a.txt", "side"), "ORIGINAL")

    @WINDOWS_ONLY
    def test_an_ads_created_during_the_interval_is_detected(self):
        # Creation cannot be prevented by ANY share mode on Windows, so
        # this half is caught by comparing the inventory instead.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)

            capture = run_capture(repo, [_script(
                "open('a.txt:sneaked', 'w', encoding='utf-8').write('NEW')",
            )], root / "staging")

            self.assertIs(capture.boundary.verdict,
                          ObservationVerdict.STREAMS_MUTATED)
            self.assertFalse(capture.evidence_valid)
            self.assertEqual(capture.exit_code, EXIT_STREAMS_MUTATED)
            self.assertTrue(any("appeared: a.txt:sneaked" in item
                                for item in capture.boundary.violations),
                            capture.boundary.violations)

    # -- 6 -------------------------------------------------------------------
    @WINDOWS_ONLY
    def test_an_ads_on_a_directory_is_covered(self):
        # git never enumerates a directory, so the covered set alone would
        # leave every directory stream unbound. They are in the domain.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            (repo / "subdir").mkdir()
            (repo / "subdir" / "kept.txt").write_text("x\n", encoding="utf-8")
            _git(repo, "add", "subdir/kept.txt")
            _git(repo, "commit", "-m", "subdir")
            _write_stream(repo / "subdir", "dir-stream", "DIRECTORY BYTES")

            capture = run_capture(
                repo, [_reads_stream("subdir", "dir-stream")], root / "staging")

            self.assertEqual(capture.checks[0].tail, "DIRECTORY BYTES")
            inputs = _manifest(capture)["inputs"]
            self.assertIn("subdir:dir-stream", inputs)
            self.assertEqual(hashlib.sha256(b"DIRECTORY BYTES").hexdigest(),
                             inputs["subdir:dir-stream"])

    @WINDOWS_ONLY
    def test_an_ads_on_the_repository_root_is_covered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            _write_stream(repo, "root-stream", "AT THE TOP")

            capture = run_capture(repo, [_script("pass")], root / "staging")

            self.assertIn(".:root-stream", _manifest(capture)["inputs"])

    @WINDOWS_ONLY
    def test_a_directory_ads_created_during_the_interval_is_detected(self):
        # The classifier forgives `modified` on a directory, because a
        # directory's timestamp moves when its entries move. That is
        # exactly why the inventory is a SECOND detector and not a
        # refinement of the first.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            (repo / "subdir").mkdir()
            (repo / "subdir" / "kept.txt").write_text("x\n", encoding="utf-8")
            _git(repo, "add", "subdir/kept.txt")
            _git(repo, "commit", "-m", "subdir")

            capture = run_capture(repo, [_script(
                "open('subdir:late', 'w', encoding='utf-8').write('LATE')",
            )], root / "staging")

            self.assertIs(capture.boundary.verdict,
                          ObservationVerdict.STREAMS_MUTATED)
            self.assertEqual(capture.exit_code, EXIT_STREAMS_MUTATED)
            self.assertTrue(any("appeared: subdir:late" in item
                                for item in capture.boundary.violations),
                            capture.boundary.violations)

    # -- 7 -------------------------------------------------------------------
    @WINDOWS_ONLY
    def test_an_ads_under_an_output_root_cannot_be_an_unnamed_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            (repo / "build-cache").mkdir()
            (repo / "build-cache" / "planted.txt").write_text(
                "MAIN\n", encoding="utf-8")
            _write_stream(repo / "build-cache" / "planted.txt", "hidden", "SIDE")

            capture = run_capture(repo, [_reads_stream(
                "build-cache/planted.txt", "hidden")], root / "staging",
                allowed_writes=("build-cache/",))

            self.assertEqual(capture.checks[0].tail, "SIDE")
            outputs = _manifest(capture)["outputs_at_start"]
            self.assertIn("build-cache/planted.txt:hidden", outputs)
            self.assertEqual(hashlib.sha256(b"SIDE").hexdigest(),
                             outputs["build-cache/planted.txt:hidden"])

    # -- 8 -------------------------------------------------------------------
    @WINDOWS_ONLY
    def test_a_tree_with_no_streams_behaves_exactly_as_before(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)

            capture = run_capture(repo, [_script("pass")], root / "staging")

            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertTrue(capture.evidence_valid)
            self.assertEqual(capture.exit_code, EXIT_OK)
            self.assertEqual(capture.boundary.violations, ())
            self.assertEqual([k for k in _manifest(capture)["inputs"] if ":" in k],
                             [], "a tree with no streams grew stream entries")
            self.assertEqual(capture.boundary.protection["locked_inputs"],
                             capture.boundary.protection["byte_bound_inputs"])

    # -- the primitives ------------------------------------------------------
    @WINDOWS_ONLY
    def test_enumeration_separates_absent_from_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plain = root / "plain.txt"
            plain.write_text("no streams\n", encoding="utf-8")
            self.assertEqual(named_streams(plain), ())

            carrying = root / "carrying.txt"
            carrying.write_text("main\n", encoding="utf-8")
            _write_stream(carrying, "side", "12345")
            self.assertEqual(named_streams(carrying), (("side", 5),))

            # An empty directory answers ERROR_HANDLE_EOF, which is "none"
            # and not "the enumeration failed".
            empty = root / "empty"
            empty.mkdir()
            self.assertEqual(named_streams(empty), ())
            self.assertEqual(named_streams(root / "missing.txt"), ())

    def test_the_domain_includes_every_directory_that_holds_an_input(self):
        self.assertEqual(
            stream_domain(["a.txt", "src/deep/b.py"]),
            ("", "a.txt", "src", "src/deep", "src/deep/b.py"))

    @WINDOWS_ONLY
    def test_a_directory_holding_no_input_is_still_in_the_domain(self):
        # Deriving directories from the covered files misses the ones
        # with no file in them — 83 of them on the real tree — and an
        # empty directory carries streams like any other.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            hollow = repo / "hollow"
            hollow.mkdir()
            _write_stream(hollow, "quiet", "NOBODY DECLARED ME")

            self.assertEqual(sorted(covered_paths(repo)),
                             [".gitignore", "a.txt", "ignored-input.txt"])
            self.assertNotIn("hollow", stream_domain(sorted(covered_paths(repo))))
            self.assertIn("hollow", stream_directories(repo))

            capture = run_capture(
                repo, [_reads_stream("hollow", "quiet")], root / "staging")

            self.assertEqual(capture.checks[0].tail, "NOBODY DECLARED ME")
            self.assertEqual(
                hashlib.sha256(b"NOBODY DECLARED ME").hexdigest(),
                _manifest(capture)["inputs"]["hollow:quiet"])

    @WINDOWS_ONLY
    def test_the_walk_leaves_out_git_and_declared_output_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            (repo / "build-cache" / "inner").mkdir(parents=True)
            (repo / "kept").mkdir()

            walked = stream_directories(repo, ("build-cache/",))

            self.assertIn("kept", walked)
            self.assertIn("", walked)
            self.assertNotIn("build-cache", walked)
            self.assertNotIn("build-cache/inner", walked)
            self.assertFalse([item for item in walked if item.startswith(".git")],
                             walked)

    def test_drift_names_what_appeared_vanished_and_resized(self):
        before = {"a.txt": (("keep", 3), ("gone", 9), ("grow", 1))}
        after = {"a.txt": (("keep", 3), ("grow", 7)), "b.txt": (("new", 2),)}

        self.assertEqual(
            stream_drift(before, after),
            ("vanished: a.txt:gone", "resized: a.txt:grow (1 -> 7 bytes)",
             "appeared: b.txt:new (2 bytes)"))

    @WINDOWS_ONLY
    def test_a_path_with_no_streams_produces_no_entry_and_no_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("x\n", encoding="utf-8")
            inventory, failures = stream_inventory(root, ["a.txt"])
            self.assertEqual(inventory, {})
            self.assertEqual(failures, ())

    @WINDOWS_ONLY
    def test_an_enumeration_failure_is_a_refusal_and_not_a_shrug(self):
        # An enumeration that cannot say WHICH streams exist cannot say
        # what the bytes are, and a path in that state is refused rather
        # than passed over.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("x\n", encoding="utf-8")

            with _no_stream_enumeration():
                inventory, failures = stream_inventory(root, ["a.txt"])

            self.assertEqual(inventory, {})
            self.assertEqual(len(failures), 2)  # the file and the root
            self.assertTrue(all("could not be enumerated" in item
                                for item in failures), failures)

    @WINDOWS_ONLY
    def test_a_lock_refuses_when_streams_cannot_be_enumerated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)

            with _no_stream_enumeration():
                lock = create_input_lock(repo)
                try:
                    outcome = lock.acquire(sorted(covered_paths(repo)))
                finally:
                    lock.release()

            self.assertFalse(outcome.enforced)
            self.assertTrue(any("could not be enumerated" in item
                                for item in outcome.refused), outcome.refused)


class TestDirectoryStreamAbaIsObserved(unittest.TestCase):
    """Tenth review: a named stream that appears and vanishes on a DIRECTORY.

        inventory has no dir:stream            (A)
        a check creates dir:stream, reads it   (B)
        the check deletes dir:stream           (A)
        inventory still has no dir:stream

    The endpoints are identical, so the inventory is blind, and the lock
    cannot pre-open a stream that does not exist. Measured: a recursive
    `ReadDirectoryChangesW` with the stream filters delivers `added_stream`
    for the create -- an event a benign entry move never produces -- so the
    observer catches the transient exactly as it catches a file's ABA.
    A directory's OWN streams are invisible to its own recursive watch, so
    the repository root is watched through its parent.
    """

    @staticmethod
    def _repo(root: Path) -> Path:
        repo = _make_repo(root)
        (repo / "pkg").mkdir()
        (repo / "pkg" / "mod.txt").write_text("y\n", encoding="utf-8")
        _git(repo, "add", "pkg/mod.txt")
        _git(repo, "commit", "-m", "pkg")
        return repo

    # -- the reviewer's minimal case, on a child directory -------------------
    @WINDOWS_ONLY
    def test_a_child_directory_stream_aba_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            capture = run_capture(repo, [_script(
                "import os",
                "open('pkg:secret', 'w', encoding='utf-8').write('ALLOW')",
                "verdict = open('pkg:secret', encoding='utf-8').read().strip()",
                "os.remove('pkg:secret')",
                "print(verdict)",
            )], root / "staging")

            self.assertEqual(capture.checks[0].tail, "ALLOW")
            self.assertIs(capture.boundary.verdict, ObservationVerdict.STREAMS_MUTATED)
            self.assertFalse(capture.evidence_valid)
            self.assertEqual(capture.exit_code, EXIT_STREAMS_MUTATED)
            self.assertTrue(any("added_stream: pkg:secret" in v
                                for v in capture.boundary.violations),
                            capture.boundary.violations)

    # -- the same, on the repository ROOT itself ----------------------------
    @WINDOWS_ONLY
    def test_the_repository_roots_own_stream_aba_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            capture = run_capture(repo, [_script(
                "import os",
                "root = os.getcwd()",
                "open(root + ':secret', 'w', encoding='utf-8').write('ALLOW')",
                "verdict = open(root + ':secret', encoding='utf-8').read().strip()",
                "os.remove(root + ':secret')",
                "print(verdict)",
            )], root / "staging")

            self.assertEqual(capture.checks[0].tail, "ALLOW")
            self.assertIs(capture.boundary.verdict, ObservationVerdict.STREAMS_MUTATED)
            self.assertFalse(capture.evidence_valid)
            self.assertEqual(capture.exit_code, EXIT_STREAMS_MUTATED)
            # Normalised to a root-relative stream path.
            self.assertTrue(any(v.endswith(":secret") for v in capture.boundary.violations),
                            capture.boundary.violations)

    # -- no false positive: a stream that is present the whole time ----------
    @WINDOWS_ONLY
    def test_a_pre_existing_directory_stream_and_a_noop_check_stays_clean(self):
        # The stream exists at lock time, so it is locked and hashed. The
        # capture reads it to hash it, which emits `modified_stream`; that
        # is not a change and must not be a violation.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            with open(f"{repo / 'pkg'}:kept", "w", encoding="utf-8") as fh:
                fh.write("PRESENT ALL ALONG")

            capture = run_capture(repo, [_script("pass")], root / "staging")

            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertTrue(capture.evidence_valid)
            manifest = json.loads(
                (capture.bundle / "input-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("pkg:kept", manifest["inputs"])

    @WINDOWS_ONLY
    def test_reading_a_locked_file_stream_is_not_a_violation(self):
        # The round-9 regression: a file with a pre-existing stream and a
        # no-op check must stay valid even though hashing the stream emits
        # modified_stream.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            with open(f"{repo / 'a.txt'}:side", "w", encoding="utf-8") as fh:
                fh.write("ALLOW")

            capture = run_capture(repo, [_script("pass")], root / "staging")

            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertTrue(capture.evidence_valid)

    # -- the classifier, where the stream/entry-move distinction lives -------
    def _observe(self, repo: Path, events, allowed=()):
        return classify_observation(
            repo, Observation(True, True, tuple(events), MECHANISM),
            frozenset({"a.txt"}), allowed,
            LockOutcome(True, 1, (), "test", identities={"a.txt": "id"},
                        content_digests={"a.txt": "sha"}))

    def test_added_stream_on_a_directory_is_a_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            (repo / "pkg").mkdir()
            boundary = self._observe(repo, [WriteEvent("added_stream", "pkg:x")])
            self.assertIs(boundary.verdict, ObservationVerdict.STREAMS_MUTATED)

    def test_modified_stream_alone_is_not_a_violation(self):
        # The read signal. Our own hashing produces it; a write to a
        # locked stream cannot.
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            (repo / "pkg").mkdir()
            boundary = self._observe(repo, [WriteEvent("modified_stream", "pkg:x")])
            self.assertIs(boundary.verdict, ObservationVerdict.CLEAN)

    def test_a_bare_directory_modified_is_still_forgiven(self):
        # The distinction the whole fix rests on: a directory's own
        # timestamp bump is forgiven, a stream action on it is not.
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            (repo / "pkg").mkdir()
            boundary = self._observe(repo, [WriteEvent("modified", "pkg")])
            self.assertIs(boundary.verdict, ObservationVerdict.CLEAN)

    def test_a_stream_under_an_output_root_may_churn(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = _make_repo(Path(tmp))
            (repo / "build-cache").mkdir()
            boundary = self._observe(
                repo, [WriteEvent("added_stream", "build-cache/art:x")],
                allowed=("build-cache/",))
            self.assertIs(boundary.verdict, ObservationVerdict.CLEAN)

    # -- fail closed when the root's own streams cannot be watched -----------
    @WINDOWS_ONLY
    def test_a_repo_at_a_volume_root_cannot_promise_root_stream_coverage(self):
        from gnosis.kernel.write_observer import _ParentStreamWatch
        watch = _ParentStreamWatch(Path("C:\\"))
        watch.start()
        observation = watch.stop()
        self.assertFalse(observation.complete)
        self.assertIn("no parent", (observation.reason or ""))

    @WINDOWS_ONLY
    def test_an_incomplete_root_watch_makes_the_observation_incomplete(self):
        # The merge: if the parent watch cannot promise the root grew no
        # transient stream, the whole observation is INCOMPLETE, not CLEAN.
        class _Blind:
            def start(self):
                return None

            def stop(self):
                return Observation(False, False, (), MECHANISM,
                                   "root-stream coverage was not established")

        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            observer = create_write_observer(repo)
            observer._root_stream = _Blind()
            capture = run_capture(repo, [_script("pass")], Path(tmp) / "staging",
                                  observer=lambda _: observer)
            self.assertIs(capture.boundary.verdict, ObservationVerdict.UNOBSERVED)
            self.assertFalse(capture.evidence_valid)


class TestNoUnobservedWindow(unittest.TestCase):
    """Eleventh review: CLEAN is licensed only by a COMPLETE observation over
    the whole interval, and the interval has no gap the guarantee ignores.

    The hard case is a memory-mapped write: a writable mapping can change a
    file's bytes without the observer ever seeing it (measured: silent even
    on flush). It is stopped not by observation but by the lock, which fails
    closed for any live writable mapping — a writable mapping needs write
    access and the lock's FILE_SHARE_READ open refuses to coexist with it.
    """

    @staticmethod
    def _repo(root: Path) -> Path:
        repo = _make_repo(root)
        (repo / "data.bin").write_bytes(b"A" * 64)
        _git(repo, "add", "data.bin")
        _git(repo, "commit", "-m", "data")
        return repo

    # -- memory mapping: the crux -------------------------------------------
    @WINDOWS_ONLY
    def test_a_live_writable_mapping_forces_fail_closed(self):
        # A writable mapping alive on a covered file when the lock tries to
        # acquire: the capture must fail closed (UNPROTECTED), never run a
        # check, never reach CLEAN.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            fh = open(repo / "data.bin", "r+b")  # noqa: SIM115 - handle held or open asserted to fail
            mm = mmap.mmap(fh.fileno(), 0)
            try:
                capture = run_capture(repo, [_script("pass")], root / "staging")
            finally:
                mm.close()
                fh.close()

            self.assertIs(capture.boundary.verdict, ObservationVerdict.UNPROTECTED)
            self.assertFalse(capture.evidence_valid)
            self.assertEqual(capture.exit_code, EXIT_INPUTS_UNPROTECTED)
            self.assertEqual(capture.checks, ())  # nothing ran

    @WINDOWS_ONLY
    def test_the_same_tree_is_clean_once_the_mapping_is_gone(self):
        # Control: the fail-closed above is the mapping, not the tree.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            fh = open(repo / "data.bin", "r+b")  # noqa: SIM115 - handle held or open asserted to fail
            mm = mmap.mmap(fh.fileno(), 0)
            mm.close()
            fh.close()

            capture = run_capture(repo, [_script("pass")], root / "staging")
            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertTrue(capture.evidence_valid)

    @WINDOWS_ONLY
    def test_a_locked_input_admits_no_writable_mapping(self):
        # A NEW writable mapping cannot be created while the lock holds the
        # file, so a check cannot map its way around the boundary either.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            lock = create_input_lock(repo)
            try:
                outcome = lock.acquire(sorted(covered_paths(repo)))
                self.assertTrue(outcome.enforced)
                with self.assertRaises(PermissionError):
                    open(repo / "data.bin", "r+b")  # write access refused  # noqa: SIM115 - handle held or open asserted to fail
            finally:
                lock.release()

    # -- locked stream immutability: the modified_stream invariant ----------
    @WINDOWS_ONLY
    def test_a_locked_stream_admits_no_modification_route(self):
        # modified_stream is tolerated because a stream present at lock time
        # cannot actually be changed. Prove every route is refused.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            with open(f"{repo / 'data.bin'}:s", "w", encoding="utf-8") as fh:
                fh.write("ORIGINAL")

            lock = create_input_lock(repo)
            try:
                outcome = lock.acquire(sorted(covered_paths(repo)))
                self.assertTrue(outcome.enforced)
                stream = f"{repo / 'data.bin'}:s"
                with self.assertRaises(OSError):        # overwrite
                    open(stream, "w", encoding="utf-8")  # noqa: SIM115 - handle held or open asserted to fail
                with self.assertRaises(OSError):        # truncate/extend
                    open(stream, "r+b")  # noqa: SIM115 - handle held or open asserted to fail
                with self.assertRaises(OSError):        # delete
                    os.remove(stream)
                with self.assertRaises(OSError):        # writable mapping
                    fh2 = open(stream, "r+b")  # noqa: SIM115 - handle held or open asserted to fail
                    try:
                        mmap.mmap(fh2.fileno(), 0)
                    finally:
                        fh2.close()
            finally:
                lock.release()
            self.assertEqual(
                open(stream, encoding="utf-8").read(), "ORIGINAL")  # noqa: SIM115 - handle held or open asserted to fail

    # -- start race: the observer is armed before the boundary --------------
    def test_the_observer_is_armed_before_the_lock(self):
        order: list[str] = []

        class _RecordingObserver:
            def __init__(self, inner):
                self._inner = inner

            def start(self):
                order.append("observer.start")
                return self._inner.start()

            def stop(self):
                return self._inner.stop()

        class _RecordingLock:
            def __init__(self, inner):
                self._inner = inner

            def acquire(self, paths, directories=()):
                order.append("lock.acquire")
                return self._inner.acquire(paths, directories)

            def release(self):
                return self._inner.release()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            run_capture(
                repo, [_script("pass")], root / "staging",
                observer=lambda r: _RecordingObserver(create_write_observer(r)),
                input_lock=lambda r: _RecordingLock(create_input_lock(r)))

        self.assertEqual(order[:2], ["observer.start", "lock.acquire"],
                         f"the boundary was raised before the watch: {order}")

    # -- end race / transient file: create -> modify -> delete --------------
    @WINDOWS_ONLY
    def test_a_file_created_and_deleted_in_the_interval_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            capture = run_capture(repo, [_script(
                "import os",
                "open('sneaked.txt', 'w', encoding='utf-8').write('X')",
                "os.remove('sneaked.txt')",
            )], root / "staging")

            self.assertIs(capture.boundary.verdict, ObservationVerdict.INPUTS_MUTATED)
            self.assertFalse(capture.evidence_valid)

    # -- overflow / failure: never CLEAN ------------------------------------
    def _capture_with_observation(self, observation):
        class _Injected:
            def start(self_inner):
                return None

            def stop(self_inner):
                return observation

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            return run_capture(repo, [_script("pass")], root / "staging",
                               observer=lambda _: _Injected())

    def test_an_overflowed_observation_is_never_clean(self):
        capture = self._capture_with_observation(
            Observation(True, False, (), MECHANISM, "the change buffer overflowed"))
        self.assertIs(capture.boundary.verdict, ObservationVerdict.UNOBSERVED)
        self.assertFalse(capture.evidence_valid)
        self.assertEqual(capture.exit_code, EXIT_BOUNDARY_UNAVAILABLE)

    def test_an_unavailable_observer_is_never_clean(self):
        capture = self._capture_with_observation(
            Observation(False, False, (), MECHANISM, "the observer was never armed"))
        self.assertIs(capture.boundary.verdict, ObservationVerdict.UNOBSERVED)
        self.assertFalse(capture.evidence_valid)

    # -- parent watcher: sibling noise is not a violation -------------------
    @WINDOWS_ONLY
    def test_a_stream_on_a_sibling_of_the_repo_is_not_a_violation(self):
        # The parent watch is non-recursive and filtered to the root's own
        # entry, so a stream created on a SIBLING directory in the same
        # parent must not be mistaken for a change to the repository.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            sibling = root / "sibling"
            sibling.mkdir()

            capture = run_capture(repo, [_script(
                "import os",
                "sib = os.path.join(os.path.dirname(os.getcwd()), 'sibling')",
                "open(sib + ':noise', 'w', encoding='utf-8').write('N')",
                "os.remove(sib + ':noise')",
            )], root / "staging")

            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertTrue(capture.evidence_valid)

    def test_the_summary_defines_complete_without_overclaiming(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = self._repo(root)
            capture = run_capture(repo, [_script("pass")], root / "staging")
            note = capture.summary["boundary"]["complete_note"]
            self.assertIn("does NOT mean every possible filesystem", note)
            self.assertIn("UNOBSERVED, never CLEAN", note)


class TestBundleIsTamperEvident(unittest.TestCase):
    """F-17: the evidence bundle was the least-protected part of the project
    — no hash chain, no signature. A capture now writes a manifest that
    SHA-256s every file plus one bundle_digest over them all, and
    verify_bundle re-derives it, so any file added, removed or changed after
    capture is detected. A cryptographic signature (which would also stop an
    editor recomputing the manifest) is a declared out-of-scope limitation,
    not a hidden claim.
    """

    @staticmethod
    def _repo(root: Path) -> Path:
        return _make_repo(root)

    @WINDOWS_ONLY
    def test_a_fresh_bundle_carries_a_manifest_that_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = run_capture(self._repo(root), [_script("pass")], root / "s")
            manifest = capture.bundle / BUNDLE_MANIFEST
            self.assertTrue(manifest.exists())
            recorded = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertIn("SUMMARY.json", recorded["files"])
            self.assertNotIn(BUNDLE_MANIFEST, recorded["files"])  # cannot hash itself
            self.assertRegex(recorded["bundle_digest"], r"\A[0-9a-f]{64}\Z")

            result = verify_bundle(capture.bundle)
            self.assertTrue(result.verified, result.problems)
            self.assertEqual(result.bundle_digest, recorded["bundle_digest"])

    @WINDOWS_ONLY
    def test_editing_any_bundle_file_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = run_capture(self._repo(root), [_script("pass")], root / "s")
            summary = capture.bundle / "SUMMARY.json"
            summary.write_text(summary.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            result = verify_bundle(capture.bundle)
            self.assertFalse(result.verified)
            self.assertTrue(any("changed: SUMMARY.json" in p for p in result.problems),
                            result.problems)

    @WINDOWS_ONLY
    def test_adding_or_removing_a_bundle_file_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = run_capture(self._repo(root), [_script("pass")], root / "s")

            planted = capture.bundle / "planted.txt"
            planted.write_text("smuggled", encoding="utf-8")
            self.assertFalse(verify_bundle(capture.bundle).verified)
            planted.unlink()

            (capture.bundle / "input-manifest.json").unlink()
            result = verify_bundle(capture.bundle)
            self.assertFalse(result.verified)
            self.assertTrue(any("absent: input-manifest.json" in p
                                for p in result.problems), result.problems)

    @WINDOWS_ONLY
    def test_a_recomputed_manifest_that_lies_about_its_digest_is_caught(self):
        # An editor who changes a file AND its recorded hash but forgets the
        # bundle_digest is caught; this pins the digest-vs-map cross-check.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = run_capture(self._repo(root), [_script("pass")], root / "s")
            manifest = capture.bundle / BUNDLE_MANIFEST
            data = json.loads(manifest.read_text(encoding="utf-8"))
            # Flip one recorded hash without touching bundle_digest.
            key = next(iter(data["files"]))
            data["files"][key] = "0" * 64
            manifest.write_text(json.dumps(data), encoding="utf-8")
            result = verify_bundle(capture.bundle)
            self.assertFalse(result.verified)

    def test_a_missing_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "not-a-bundle"
            empty.mkdir()
            self.assertFalse(verify_bundle(empty).verified)


class TestGitMachineryIsJudged(unittest.TestCase):
    """F-17 / the F-14 residual: most `.git` writes are git's own bookkeeping
    during a read and stay counted, but a hook (code that runs on the next
    git op) or config (what a filter runs, where a push goes) written during
    the capture is a tamper of the machinery that produced the evidence, and
    is judged. Caught in the interval, so a create+delete is caught too —
    a before/after machinery fingerprint is blind to that (measured).
    """

    @staticmethod
    def _repo(root: Path) -> Path:
        return _make_repo(root)

    # -- the predicate ------------------------------------------------------
    def test_the_predicate_names_the_execute_or_redirect_surface(self):
        self.assertTrue(_is_git_machinery_tamper(".git/hooks/pre-commit"))
        self.assertTrue(_is_git_machinery_tamper(".git/config"))
        self.assertTrue(_is_git_machinery_tamper(".git/config:stream"))
        self.assertTrue(_is_git_machinery_tamper(".git/hooks/pre-push:x"))
        # not the execute/redirect surface:
        self.assertFalse(_is_git_machinery_tamper(".git/hooks/pre-commit.sample"))
        self.assertFalse(_is_git_machinery_tamper(".git/index"))
        self.assertFalse(_is_git_machinery_tamper(".git/refs/heads/main"))
        self.assertFalse(_is_git_machinery_tamper(".git/objects/ab/cdef"))
        self.assertFalse(_is_git_machinery_tamper("src/config"))  # not under .git

    # -- end to end ---------------------------------------------------------
    @WINDOWS_ONLY
    def test_installing_a_hook_during_the_capture_is_judged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = run_capture(self._repo(root), [_script(
                "import os",
                "open(os.path.join('.git', 'hooks', 'pre-commit'), "
                "'w', encoding='utf-8').write('evil')",
            )], root / "s")
            self.assertIs(capture.boundary.verdict, ObservationVerdict.MACHINERY_MUTATED)
            self.assertFalse(capture.evidence_valid)
            self.assertEqual(capture.exit_code, EXIT_MACHINERY_MUTATED)
            self.assertTrue(any(".git/hooks/pre-commit" in v
                                for v in capture.boundary.violations),
                            capture.boundary.violations)

    @WINDOWS_ONLY
    def test_a_hook_installed_and_deleted_in_the_interval_is_judged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = run_capture(self._repo(root), [_script(
                "import os",
                "h = os.path.join('.git', 'hooks', 'pre-commit')",
                "open(h, 'w', encoding='utf-8').write('evil')",
                "os.remove(h)",
            )], root / "s")
            self.assertIs(capture.boundary.verdict, ObservationVerdict.MACHINERY_MUTATED)
            self.assertEqual(capture.exit_code, EXIT_MACHINERY_MUTATED)

    @WINDOWS_ONLY
    def test_rewriting_git_config_during_the_capture_is_judged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = run_capture(self._repo(root), [_script(
                "import subprocess",
                "subprocess.run(['git', 'config', 'core.pager', 'evil'], check=True)",
            )], root / "s")
            self.assertIs(capture.boundary.verdict, ObservationVerdict.MACHINERY_MUTATED)
            self.assertEqual(capture.exit_code, EXIT_MACHINERY_MUTATED)

    @WINDOWS_ONLY
    def test_an_unqualified_git_surface_write_fails_closed(self):
        # F-17 Stage 7: a .git administrative surface the closed-world
        # classifier does not qualify (here ORIG_HEAD) is written during the
        # capture. It must not be forgiven by default: MACHINERY_UNQUALIFIED.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = run_capture(self._repo(root), [_script(
                "import os",
                "open(os.path.join('.git', 'ORIG_HEAD'), 'w', "
                "encoding='utf-8').write('0'*40)",
            )], root / "s")
            self.assertIs(capture.boundary.verdict,
                          ObservationVerdict.MACHINERY_UNQUALIFIED)
            self.assertFalse(capture.evidence_valid)
            self.assertEqual(capture.exit_code, EXIT_MACHINERY_UNQUALIFIED)
            self.assertTrue(any("ORIG_HEAD" in v
                                for v in capture.boundary.violations),
                            capture.boundary.violations)

    @WINDOWS_ONLY
    def test_an_unknown_refs_namespace_write_fails_closed(self):
        # refs/codex/ exists on this machine and is NOT a qualified namespace.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = run_capture(self._repo(root), [_script(
                "import os",
                "os.makedirs(os.path.join('.git', 'refs', 'codex'), "
                "exist_ok=True)",
                "open(os.path.join('.git', 'refs', 'codex', 'x'), 'w', "
                "encoding='utf-8').write('0'*40)",
            )], root / "s")
            self.assertIs(capture.boundary.verdict,
                          ObservationVerdict.MACHINERY_UNQUALIFIED)
            self.assertEqual(capture.exit_code, EXIT_MACHINERY_UNQUALIFIED)

    @WINDOWS_ONLY
    def test_writing_head_during_the_capture_is_judged(self):
        # HEAD is trust-sensitive in the Stage 7 classifier (it defines the
        # checkout). Written and RESTORED inside the interval (ABA), so the
        # endpoints match and the binding stays BOUND — the observer still
        # caught the write, and it is MACHINERY_MUTATED with exit 9. This is
        # exactly the case a before/after fingerprint is blind to.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = run_capture(self._repo(root), [_script(
                "import os",
                "p = os.path.join('.git', 'HEAD')",
                "original = open(p, encoding='utf-8').read()",
                "open(p, 'w', encoding='utf-8').write('ref: refs/heads/other\\n')",
                "open(p, 'w', encoding='utf-8').write(original)",
            )], root / "s")
            self.assertIs(capture.boundary.verdict,
                          ObservationVerdict.MACHINERY_MUTATED)
            self.assertEqual(capture.exit_code, EXIT_MACHINERY_MUTATED)

    @WINDOWS_ONLY
    def test_writing_info_exclude_during_the_capture_is_judged(self):
        # info/exclude steers what git enumerates as ignored/untracked, so it
        # is trust-sensitive in Stage 7.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = run_capture(self._repo(root), [_script(
                "import os",
                "open(os.path.join('.git', 'info', 'exclude'), 'a', "
                "encoding='utf-8').write('*.log\\n')",
            )], root / "s")
            self.assertIs(capture.boundary.verdict,
                          ObservationVerdict.MACHINERY_MUTATED)

    @WINDOWS_ONLY
    def test_a_sample_hook_write_is_not_a_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = run_capture(self._repo(root), [_script(
                "import os",
                "open(os.path.join('.git', 'hooks', 'pre-commit.sample'), "
                "'w', encoding='utf-8').write('inert')",
            )], root / "s")
            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertTrue(capture.evidence_valid)

    @WINDOWS_ONLY
    def test_ordinary_git_bookkeeping_stays_counted_not_judged(self):
        # A normal capture: git updates its index/refs while reading, which
        # must stay counted (machinery), not become a violation.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = run_capture(self._repo(root), [_script("pass")], root / "s")
            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertTrue(capture.evidence_valid)
            self.assertGreater(capture.boundary.machinery_events, 0)


class TestGitTopologyMustBeInTree(unittest.TestCase):
    """F-17 BLOCKER 1: the machinery judgement can only see what the observer
    watches. In a linked worktree, a submodule, or a separate-git-dir clone,
    `.git` is a redirect FILE and the hooks/config/HEAD/index live in an
    external git-dir OUTSIDE the tree. Measured as a real bypass — a capture
    inside a worktree with a hook installed into the common dir returned
    CLEAN. So an ineligible topology fails closed, never a clean verdict.
    """

    @staticmethod
    def _git(cwd, *a):
        r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True,
                           check=False)  # returncode handled explicitly below
        if r.returncode != 0:
            raise RuntimeError(f"git {a}: {r.stderr}")
        return r.stdout.strip()

    def _repo(self, root: Path, name: str = "main") -> Path:
        repo = root / name
        repo.mkdir()
        for a in (["init"], ["config", "user.email", "t@e.com"],
                  ["config", "user.name", "T"], ["config", "commit.gpgsign", "false"]):
            self._git(repo, *a)
        (repo / "a.txt").write_text("A\n", encoding="utf-8")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-m", "init")
        return repo

    # -- the predicate ------------------------------------------------------
    def test_a_standard_repo_is_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            ok, reason = git_topology_eligible(repo)
            self.assertTrue(ok, reason)
            self.assertIsNone(reason)

    def test_a_non_repo_directory_is_eligible_no_machinery(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "plain"
            plain.mkdir()
            ok, reason = git_topology_eligible(plain)
            self.assertTrue(ok, reason)  # nothing git to tamper

    def test_a_linked_worktree_is_ineligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            self._git(repo, "branch", "feature")
            wt = Path(tmp) / "wt"
            self._git(repo, "worktree", "add", str(wt), "feature")
            self.assertTrue((wt / ".git").is_file())  # redirect file
            ok, reason = git_topology_eligible(wt)
            self.assertFalse(ok)
            self.assertIn("redirect file", reason or "")

    def test_a_git_file_pointing_outside_the_tree_is_refused_not_followed(self):
        # A .git redirect to an external, real git-dir: eligible must be
        # False, and the redirect is refused rather than followed into.
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            elsewhere = Path(tmp) / "elsewhere"
            elsewhere.mkdir()
            decoy = Path(tmp) / "decoy"
            decoy.mkdir()
            (decoy / "a.txt").write_text("A\n", encoding="utf-8")
            # point decoy/.git at the real repo's git-dir (path confusion)
            (decoy / ".git").write_text(
                f"gitdir: {(repo / '.git').as_posix()}\n", encoding="utf-8")
            ok, reason = git_topology_eligible(decoy)
            self.assertFalse(ok, reason)

    @WINDOWS_ONLY
    def test_a_real_submodule_working_dir_is_ineligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            inner = self._repo(Path(tmp), "inner")
            outer = self._repo(Path(tmp), "outer")
            self._git(outer, "-c", "protocol.file.allow=always",
                      "submodule", "add", inner.as_uri(), "sub")
            sub = outer / "sub"
            self.assertTrue((sub / ".git").is_file())
            ok, reason = git_topology_eligible(sub)
            self.assertFalse(ok)
            self.assertIn("redirect file", reason or "")

    # -- end to end ---------------------------------------------------------
    @WINDOWS_ONLY
    def test_a_capture_inside_a_worktree_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            self._git(repo, "branch", "feature")
            wt = Path(tmp) / "wt"
            self._git(repo, "worktree", "add", str(wt), "feature")

            # A check that installs a hook in the COMMON dir would be the
            # bypass; it must never run, because the topology is refused.
            capture = run_capture(wt, [_script(
                "import subprocess, os",
                "cd = subprocess.run(['git','rev-parse','--git-common-dir'],"
                "capture_output=True,text=True).stdout.strip()",
                "open(os.path.join(cd,'hooks','pre-commit'),'w',"
                "encoding='utf-8').write('evil')",
            )], Path(tmp) / "staging")

            self.assertIs(capture.boundary.verdict,
                          ObservationVerdict.MACHINERY_UNOBSERVABLE)
            self.assertFalse(capture.evidence_valid)
            self.assertEqual(capture.exit_code, EXIT_MACHINERY_UNOBSERVABLE)
            self.assertEqual(capture.checks, ())  # nothing ran

    @WINDOWS_ONLY
    def test_a_standard_repo_capture_is_not_refused_for_topology(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            capture = run_capture(repo, [_script("pass")], Path(tmp) / "staging")
            self.assertIsNot(capture.boundary.verdict,
                             ObservationVerdict.MACHINERY_UNOBSERVABLE)
            self.assertTrue(capture.evidence_valid)

    @WINDOWS_ONLY
    def test_changing_which_commit_we_verify_is_caught_by_the_binding(self):
        # Backs the "`.git` bookkeeping counted is safe" claim: HEAD is
        # counted, not judged, because a change to it moves the fingerprint
        # and the binding fails closed (TREE_MUTATED).
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            self._git(repo, "branch", "other")
            capture = run_capture(repo, [_script(
                "import subprocess",
                "subprocess.run(['git','checkout','other'],check=True)",
            )], Path(tmp) / "staging")
            self.assertIs(capture.binding.verdict, BindingVerdict.TREE_MUTATED)
            self.assertFalse(capture.evidence_valid)


class TestGitResolutionMustBeUnredirected(unittest.TestCase):
    """F-17 third review, BLOCKER A. The tree-identity binding reads
    `git diff HEAD` / `git status`, which honour git's resolution machinery.
    A `refs/replace/*` ref substitutes one object for another during
    resolution WITHOUT changing the original object's bytes — measured OS-real
    on git 2.55: a working tree that matches HEAD reads as dirty (and the
    reverse). A replace ref active at capture start is present at both
    endpoints, so the binding would certify a false identity with
    `identical: true`; the replace surface is `.git`, counted-not-judged, so
    nothing else catches it. `objects/info/alternates` redirects object
    lookup; `info/grafts` and `shallow` redirect ancestry. A redirection
    ALREADY ACTIVE at start fails closed (MACHINERY_REDIRECTED, exit 11); a
    write to a redirect surface DURING the interval is judged like a hook
    (MACHINERY_MUTATED, exit 9), so an ABA the endpoints are blind to is
    caught too. F-14 is untouched: it hashes each input's bytes THROUGH its
    handle, never through git, so a replace ref cannot move a content_digest.
    """

    @staticmethod
    def _git(cwd, *a):
        r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True,
                           check=False)  # returncode handled explicitly below
        if r.returncode != 0:
            raise RuntimeError(f"git {a}: {r.stderr}")
        return r.stdout.strip()

    def _repo(self, root: Path, name: str = "repo") -> Path:
        repo = root / name
        repo.mkdir()
        for a in (["init"], ["config", "user.email", "t@e.com"],
                  ["config", "user.name", "T"], ["config", "commit.gpgsign", "false"],
                  ["config", "core.autocrlf", "false"]):
            self._git(repo, *a)
        (repo / "a.txt").write_text("REAL\n", encoding="utf-8")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-m", "c1")
        (repo / "a.txt").write_text("FAKE\n", encoding="utf-8")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-m", "c2")
        return repo

    # -- the predicate ------------------------------------------------------
    def test_the_predicate_names_the_resolution_redirect_surface(self):
        self.assertTrue(_is_git_resolution_redirect(".git/refs/replace/abc"))
        self.assertTrue(_is_git_resolution_redirect(".git/packed-refs"))
        self.assertTrue(_is_git_resolution_redirect(".git/packed-refs:s"))
        self.assertTrue(_is_git_resolution_redirect(".git/objects/info/alternates"))
        self.assertTrue(_is_git_resolution_redirect(".git/objects/info/http-alternates"))
        self.assertTrue(_is_git_resolution_redirect(".git/info/grafts"))
        self.assertTrue(_is_git_resolution_redirect(".git/shallow"))
        self.assertTrue(_is_git_resolution_redirect(".git/config.worktree"))
        self.assertTrue(_is_git_resolution_redirect(".git/commondir"))
        # NOT a resolution-redirect surface — ordinary bookkeeping stays counted:
        self.assertFalse(_is_git_resolution_redirect(".git/index"))
        self.assertFalse(_is_git_resolution_redirect(".git/HEAD"))
        self.assertFalse(_is_git_resolution_redirect(".git/refs/heads/main"))
        self.assertFalse(_is_git_resolution_redirect(".git/logs/HEAD"))
        self.assertFalse(_is_git_resolution_redirect(".git/objects/ab/cdef"))
        self.assertFalse(_is_git_resolution_redirect("refs/replace/x"))  # not under .git

    def test_the_redirected_exit_code_is_distinct(self):
        self.assertEqual(
            len({EXIT_OK, EXIT_MACHINERY_MUTATED, EXIT_MACHINERY_UNOBSERVABLE,
                 EXIT_MACHINERY_REDIRECTED}), 4)

    # -- the gate -----------------------------------------------------------
    def test_a_clean_repo_is_faithful(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, reason = git_resolution_faithful(self._repo(Path(tmp)))
            self.assertTrue(ok, reason)
            self.assertIsNone(reason)

    def test_a_non_repo_directory_is_faithful_nothing_to_redirect(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "plain"
            plain.mkdir()
            ok, reason = git_resolution_faithful(plain)
            self.assertTrue(ok, reason)

    def test_a_loose_replace_ref_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            c1 = self._git(repo, "rev-parse", "HEAD~1")
            c2 = self._git(repo, "rev-parse", "HEAD")
            self._git(repo, "replace", c1, c2)
            ok, reason = git_resolution_faithful(repo)
            self.assertFalse(ok)
            self.assertIn("replace ref", reason or "")

    def test_a_packed_replace_ref_is_still_refused(self):
        # A replace ref carried by packed-refs (not a loose ref) must be
        # refused just the same — `for-each-ref` sees both backends.
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            c1 = self._git(repo, "rev-parse", "HEAD~1")
            c2 = self._git(repo, "rev-parse", "HEAD")
            self._git(repo, "replace", c1, c2)
            self._git(repo, "pack-refs", "--all")
            ok, reason = git_resolution_faithful(repo)
            self.assertFalse(ok)
            self.assertIn("replace ref", reason or "")

    def test_an_alternates_object_store_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            info = repo / ".git" / "objects" / "info"
            info.mkdir(parents=True, exist_ok=True)
            (info / "alternates").write_text("/some/other/objects\n", encoding="utf-8")
            ok, reason = git_resolution_faithful(repo)
            self.assertFalse(ok)
            self.assertIn("alternates", reason or "")

    def test_a_grafts_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            c2 = self._git(repo, "rev-parse", "HEAD")
            info = repo / ".git" / "info"
            info.mkdir(parents=True, exist_ok=True)
            (info / "grafts").write_text(c2 + "\n", encoding="utf-8")
            ok, reason = git_resolution_faithful(repo)
            self.assertFalse(ok)
            self.assertIn("grafts", reason or "")

    def test_a_shallow_repository_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            c2 = self._git(repo, "rev-parse", "HEAD")
            (repo / ".git" / "shallow").write_text(c2 + "\n", encoding="utf-8")
            ok, reason = git_resolution_faithful(repo)
            self.assertFalse(ok)
            self.assertIn("shallow", reason or "")

    def test_an_empty_redirection_file_is_not_a_redirection(self):
        # A zero-byte alternates/grafts file does not redirect anything; the
        # gate keys on non-empty, so it must not false-positive.
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            info = repo / ".git" / "objects" / "info"
            info.mkdir(parents=True, exist_ok=True)
            (info / "alternates").write_text("", encoding="utf-8")
            ok, reason = git_resolution_faithful(repo)
            self.assertTrue(ok, reason)

    def test_the_binding_is_actually_fooled_by_a_replace_ref(self):
        # WHY the gate exists, reproduced against the product primitive: with a
        # replace ref active, content_fingerprint records a different patch and
        # status while head_sha is unchanged. Present at both endpoints it
        # would bind with identical:true to a tree that is not the real one.
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            c1 = self._git(repo, "rev-parse", "HEAD~1")
            c2 = self._git(repo, "rev-parse", "HEAD")
            self._git(repo, "checkout", c1)  # tree matches c1, git diff HEAD empty
            before = content_fingerprint(repo)
            self._git(repo, "replace", c1, c2)
            after = content_fingerprint(repo)
            self.assertEqual(before["head_sha"], after["head_sha"])
            self.assertNotEqual(before["patch_sha256"], after["patch_sha256"])
            self.assertNotEqual(before["status_sha256"], after["status_sha256"])
            ok, _ = git_resolution_faithful(repo)
            self.assertFalse(ok, "the gate must refuse the state that fools the binding")

    # -- end to end ---------------------------------------------------------
    @WINDOWS_ONLY
    def test_a_pre_existing_replace_ref_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            c1 = self._git(repo, "rev-parse", "HEAD~1")
            c2 = self._git(repo, "rev-parse", "HEAD")
            self._git(repo, "checkout", c1)
            self._git(repo, "replace", c1, c2)
            capture = run_capture(repo, [_script("pass")], Path(tmp) / "staging")
            self.assertIs(capture.boundary.verdict,
                          ObservationVerdict.MACHINERY_REDIRECTED)
            self.assertFalse(capture.evidence_valid)
            self.assertEqual(capture.exit_code, EXIT_MACHINERY_REDIRECTED)
            self.assertEqual(capture.checks, ())  # nothing ran

    @WINDOWS_ONLY
    def test_a_replace_ref_installed_and_removed_in_the_interval_is_judged(self):
        # ABA: absent at both endpoints, so the start gate and the endpoints
        # are blind; only the interval observer catches the write to
        # refs/replace, exactly as it does for a hook create+delete.
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            c1 = self._git(repo, "rev-parse", "HEAD~1")
            c2 = self._git(repo, "rev-parse", "HEAD")
            capture = run_capture(repo, [_script(
                "import subprocess",
                f"subprocess.run(['git','replace','{c1}','{c2}'],check=True)",
                f"subprocess.run(['git','replace','-d','{c1}'],check=True)",
            )], Path(tmp) / "staging")
            self.assertIs(capture.boundary.verdict,
                          ObservationVerdict.MACHINERY_MUTATED)
            self.assertEqual(capture.exit_code, EXIT_MACHINERY_MUTATED)
            self.assertTrue(any("refs/replace" in v
                                for v in capture.boundary.violations),
                            capture.boundary.violations)

    @WINDOWS_ONLY
    def test_a_raw_packed_refs_replace_injection_in_the_interval_is_judged(self):
        # A raw packed-refs edit installs a replace ref with no `git replace`
        # command (reproduced OS-real). The write to packed-refs is judged,
        # so even this ABA is caught.
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            c1 = self._git(repo, "rev-parse", "HEAD~1")
            c2 = self._git(repo, "rev-parse", "HEAD")
            capture = run_capture(repo, [_script(
                "import os",
                "pr = os.path.join('.git', 'packed-refs')",
                f"open(pr, 'a', encoding='utf-8').write('{c2} refs/replace/{c1}\\n')",
                "os.remove(pr)",
            )], Path(tmp) / "staging")
            self.assertIs(capture.boundary.verdict,
                          ObservationVerdict.MACHINERY_MUTATED)
            self.assertTrue(any("packed-refs" in v
                                for v in capture.boundary.violations),
                            capture.boundary.violations)

    @WINDOWS_ONLY
    def test_a_standard_repo_capture_is_not_refused_for_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(Path(tmp))
            capture = run_capture(repo, [_script("pass")], Path(tmp) / "staging")
            self.assertIsNot(capture.boundary.verdict,
                             ObservationVerdict.MACHINERY_REDIRECTED)
            self.assertTrue(capture.evidence_valid)


class TestBundleRootOfTrust(unittest.TestCase):
    """F-17 BLOCKER 2: the manifest inside the bundle proves self-consistency,
    not tamper-evidence — an editor can recompute it. `verify_bundle` with an
    `expected_digest` recorded OUTSIDE the bundle (ADR-0027, or the git
    commit that carries it) is the tamper-evidence check; authenticity still
    needs a signature and is out of scope.
    """

    @staticmethod
    def _repo(root: Path) -> Path:
        return _make_repo(root)

    @WINDOWS_ONLY
    def test_the_external_anchor_turns_self_consistency_into_tamper_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = run_capture(self._repo(root), [_script("pass")], root / "s")
            digest = verify_bundle(capture.bundle).bundle_digest

            self.assertTrue(verify_bundle(capture.bundle).verified)
            self.assertTrue(
                verify_bundle(capture.bundle, expected_digest=digest).verified)
            self.assertFalse(
                verify_bundle(capture.bundle, expected_digest="0" * 64).verified)

    @WINDOWS_ONLY
    def test_a_recomputed_manifest_is_caught_by_the_external_anchor(self):
        # The exact attack BLOCKER 2 names: edit a file AND regenerate the
        # manifest so the bundle is self-consistent again. verify_bundle
        # alone then passes; the external anchor catches it.
        from gnosis.kernel.evidence_capture import write_bundle_manifest
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = run_capture(self._repo(root), [_script("pass")], root / "s")
            trusted = verify_bundle(capture.bundle).bundle_digest

            summary = capture.bundle / "SUMMARY.json"
            summary.write_text(summary.read_text(encoding="utf-8") + "\n",
                               encoding="utf-8")
            write_bundle_manifest(capture.bundle)  # attacker recomputes it

            self.assertTrue(verify_bundle(capture.bundle).verified,
                            "self-consistent after recompute")
            self.assertFalse(
                verify_bundle(capture.bundle, expected_digest=trusted).verified,
                "the external anchor catches the recomputed bundle")


if __name__ == "__main__":
    unittest.main()
