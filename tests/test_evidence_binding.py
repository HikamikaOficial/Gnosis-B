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
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from gnosis.kernel.canonical import hash_canonical
from gnosis.kernel.evidence_capture import (
    EXIT_BOUNDARY_UNAVAILABLE,
    EXIT_CHECKS_FAILED,
    EXIT_IDENTITY_UNAVAILABLE,
    EXIT_INPUTS_MUTATED,
    EXIT_INPUTS_UNPROTECTED,
    EXIT_OK,
    EXIT_PREPARATION_DRIFT,
    EXIT_TREE_MUTATED,
    BindingVerdict,
    Boundary,
    Capture,
    CheckCommand,
    CheckOutcome,
    ChecksVerdict,
    EmptyCaptureError,
    ObservationVerdict,
    TreeIdentity,
    bind_tree,
    classify_observation,
    count_lint_findings,
    covered_paths,
    describe_drift,
    probe_tree_identity,
    publish_bundle,
    run_capture,
)
from gnosis.kernel.git_evidence import content_fingerprint
from gnosis.kernel.input_lock import (
    LockOutcome,
    UnavailableLock,
    VolumeCapabilities,
    WindowsInputLock,
    classify_volume,
    create_input_lock,
    probe_volume,
)
from gnosis.kernel.write_observer import (
    Observation,
    UnavailableObserver,
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

    def acquire(self, paths):
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

    def test_a_git_ignored_cache_written_during_a_check_is_not_a_violation(self):
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
            capture = run_capture(repo, [check], root / "staging")

            self.assertIs(capture.binding.verdict, BindingVerdict.BOUND)
            self.assertIs(capture.boundary.verdict, ObservationVerdict.CLEAN)
            self.assertTrue(capture.evidence_valid)

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

    def acquire(self, paths):
        ordered = sorted(paths)
        first = self._inner.acquire(ordered[:1])
        self._during()
        second = self._inner.acquire(ordered[1:])
        identities = dict(first.identities)
        identities.update(second.identities)
        return LockOutcome(
            first.enforced and second.enforced, second.locked,
            first.refused + second.refused, first.mechanism,
            first.reason or second.reason, identities, first.volume)

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
        self.assertIn(capabilities.filesystem, {"NTFS", "ReFS"})

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

    @WINDOWS_ONLY
    def test_the_bundle_records_the_volume_it_was_demonstrated_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _make_repo(root)
            capture = run_capture(repo, [_script("pass")], root / "staging")

            volume = capture.boundary.protection["volume"]
            self.assertTrue(volume["supported"])
            self.assertEqual(volume["drive_type"], "fixed")
            self.assertIn(volume["filesystem"], {"NTFS", "ReFS"})

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


if __name__ == "__main__":
    unittest.main()
