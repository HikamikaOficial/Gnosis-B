import subprocess
import tempfile
import unittest
from pathlib import Path

from gnosis.kernel.convergence import (
    ConvergenceLoop,
    ConvergenceOutcome,
    ConvergencePolicy,
    Finding,
    FixReport,
    FixRequest,
    ReviewReport,
    ReviewVerdict,
    Severity,
    git_fingerprint,
)
from gnosis.kernel.verification import VerificationResult


def _verification(passed: bool) -> VerificationResult:
    return VerificationResult(
        name="fake", passed=passed, exit_code=0 if passed else 1,
        duration_s=0.01, stdout_excerpt="", stderr_excerpt="",
    )


def _finding(severity: Severity = Severity.MAJOR, confidence: float = 1.0,
             description: str = "bug") -> Finding:
    return Finding(severity=severity, category="correctness",
                   description=description, reviewer="fake-reviewer",
                   confidence=confidence)


class _Script:
    """Deterministic per-round script for verify/review/fingerprint/fix.
    Each stream keeps its own call counter (they are each called exactly
    once per round, in loop order fingerprint -> verify -> review)."""

    def __init__(self, verifications, reviews, fingerprints):
        self._verifications = list(verifications)
        self._reviews = list(reviews)
        self._fingerprints = list(fingerprints)
        self.fix_requests: list[FixRequest] = []
        self.fix_reports: list[FixReport] = []
        self._calls = {"verify": 0, "review": 0, "fingerprint": 0}

    def _take(self, stream: str, seq):
        self._calls[stream] += 1
        item = seq[min(self._calls[stream], len(seq)) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    def verify(self):
        return self._take("verify", self._verifications)

    def review(self, round_index: int):
        return self._take("review", self._reviews)

    def fingerprint(self):
        return self._take("fingerprint", self._fingerprints)

    def fix(self, request: FixRequest) -> FixReport:
        self.fix_requests.append(request)
        report = (self.fix_reports[len(self.fix_requests) - 1]
                  if len(self.fix_reports) >= len(self.fix_requests)
                  else FixReport(claims_done=True))
        return report


def _run(script: _Script, policy: ConvergencePolicy | None = None):
    loop = ConvergenceLoop(
        policy or ConvergencePolicy(max_rounds=10, max_unchanged_rounds=3),
        verify_fn=script.verify, review_fn=script.review,
        fix_fn=script.fix, fingerprint_fn=script.fingerprint,
    )
    return loop.run()


class TestConvergenceLoop(unittest.TestCase):
    def test_clean_first_round_converges(self):
        script = _Script(
            verifications=[_verification(True)],
            reviews=[ReviewReport(verdict=ReviewVerdict.PASS)],
            fingerprints=["fp1"],
        )
        result = _run(script)
        self.assertEqual(result.outcome, ConvergenceOutcome.CONVERGED)
        self.assertEqual(len(result.rounds), 1)
        self.assertEqual(script.fix_requests, [])

    def test_findings_then_fix_then_converges(self):
        bad = _finding()
        script = _Script(
            verifications=[_verification(True), _verification(True)],
            reviews=[ReviewReport(verdict=ReviewVerdict.FAIL, findings=(bad,)),
                     ReviewReport(verdict=ReviewVerdict.PASS)],
            fingerprints=["fp1", "fp2"],  # the fix changed the repo
        )
        result = _run(script)
        self.assertEqual(result.outcome, ConvergenceOutcome.CONVERGED)
        self.assertEqual(len(result.rounds), 2)
        self.assertEqual(script.fix_requests[0].blocking_findings, (bad,))

    def test_verification_failure_blocks_convergence_despite_pass_verdict(self):
        # Evidence beats signal: a PASS review cannot converge a failing
        # verification.
        script = _Script(
            verifications=[_verification(False), _verification(True)],
            reviews=[ReviewReport(verdict=ReviewVerdict.PASS),
                     ReviewReport(verdict=ReviewVerdict.PASS)],
            fingerprints=["fp1", "fp2"],
        )
        result = _run(script)
        self.assertEqual(result.outcome, ConvergenceOutcome.CONVERGED)
        self.assertEqual(len(result.rounds), 2)
        # The fixer was pointed at the verification failure.
        self.assertEqual(len(script.fix_requests), 1)
        self.assertFalse(script.fix_requests[0].verification.passed)

    def test_cannot_fix_is_a_typed_exit_with_ledger(self):
        gated = _finding(Severity.MINOR, description="style nit")
        blocking = _finding(Severity.CRITICAL)
        script = _Script(
            verifications=[_verification(True)],
            reviews=[ReviewReport(verdict=ReviewVerdict.FAIL, findings=(blocking, gated))],
            fingerprints=["fp1"],
        )
        script.fix_reports = [FixReport(cannot_fix=True, notes="beyond me")]
        result = _run(script)
        self.assertEqual(result.outcome, ConvergenceOutcome.CANNOT_FIX)
        # Nothing lost: the gated finding rides out on the failure exit.
        self.assertEqual(len(result.gate_ledger), 1)
        self.assertIs(result.gate_ledger[0].finding, gated)

    def test_stalemate_after_n_unchanged_fingerprints(self):
        bad = _finding()
        script = _Script(
            verifications=[_verification(True)] * 10,
            reviews=[ReviewReport(verdict=ReviewVerdict.FAIL, findings=(bad,))] * 10,
            fingerprints=["same"] * 10,  # fixes never change the repo
        )
        result = _run(script)
        self.assertEqual(result.outcome, ConvergenceOutcome.STALEMATE)
        # Round 1 sets the baseline; three consecutive unchanged rounds
        # (2, 3, 4) trip the breaker.
        self.assertEqual(len(result.rounds), 4)
        self.assertEqual(result.rounds[-1].unchanged_streak, 3)

    def test_fingerprint_change_resets_the_stalemate_counter(self):
        bad = _finding()
        script = _Script(
            verifications=[_verification(True)] * 6,
            reviews=[ReviewReport(verdict=ReviewVerdict.FAIL, findings=(bad,))] * 6,
            fingerprints=["a", "a", "a", "b", "b", "b"],
        )
        result = _run(script, ConvergencePolicy(max_rounds=6, max_unchanged_rounds=3))
        # Streak reached 2 at round 3, reset by "b" at round 4, reached 2
        # again at round 6: the loop exhausts instead of stalemating.
        self.assertEqual(result.outcome, ConvergenceOutcome.ROUNDS_EXHAUSTED)
        streaks = [r.unchanged_streak for r in result.rounds]
        self.assertEqual(streaks, [0, 1, 2, 0, 1, 2])

    def test_failed_fingerprint_collection_never_counts_toward_stalemate(self):
        bad = _finding()
        script = _Script(
            verifications=[_verification(True)] * 6,
            reviews=[ReviewReport(verdict=ReviewVerdict.FAIL, findings=(bad,))] * 6,
            fingerprints=["same", None, None, None, None, "same"],
        )
        result = _run(script, ConvergencePolicy(max_rounds=6, max_unchanged_rounds=3))
        # Rounds 2-5 had no usable fingerprint: they break consecutiveness
        # entirely, so round 6 starts a fresh baseline (streak 0) rather
        # than resuming round 1's — no STALEMATE.
        self.assertEqual(result.outcome, ConvergenceOutcome.ROUNDS_EXHAUSTED)
        self.assertEqual(result.rounds[-1].unchanged_streak, 0)
        # The soft-failure mode (returning None) is recorded, not silent.
        self.assertTrue(any("fingerprint unavailable" in w for w in result.warnings))
        # The fixer is only dispatched on rounds with complete evidence
        # (rounds 1 and 6), never during the evidence gap.
        self.assertEqual(len(script.fix_requests), 2)

    def test_probe_failures_never_reach_stalemate(self):
        # A broken verify probe over a perfectly stable fingerprint is an
        # infra problem, not a stuck repo: it must exhaust rounds, never
        # STALEMATE (Codex review finding 1).
        script = _Script(
            verifications=[RuntimeError("verify probe down")] * 6,
            reviews=[ReviewReport(verdict=ReviewVerdict.PASS)] * 6,
            fingerprints=["same"] * 6,
        )
        result = _run(script, ConvergencePolicy(max_rounds=6, max_unchanged_rounds=2))
        self.assertEqual(result.outcome, ConvergenceOutcome.ROUNDS_EXHAUSTED)
        self.assertEqual(max(r.unchanged_streak for r in result.rounds), 0)

    def test_gap_breaks_consecutiveness_of_recurring_fingerprints(self):
        # A, gap, A, A must not stalemate at max_unchanged_rounds=2: the
        # kernel did not observe the gap round, so the post-gap A starts a
        # new consecutive run (Codex review finding 2).
        bad = _finding()
        script = _Script(
            verifications=[_verification(True)] * 4,
            reviews=[ReviewReport(verdict=ReviewVerdict.FAIL, findings=(bad,))] * 4,
            fingerprints=["A", None, "A", "A"],
        )
        result = _run(script, ConvergencePolicy(max_rounds=4, max_unchanged_rounds=2))
        self.assertEqual(result.outcome, ConvergenceOutcome.ROUNDS_EXHAUSTED)
        self.assertEqual([r.unchanged_streak for r in result.rounds], [0, 0, 0, 1])

    def test_verification_flip_on_unchanged_fingerprint_requires_reproduction(self):
        # Codex review finding 3: fail -> (no repo change) -> pass must not
        # close the task on the first lucky pass; the pass has to reproduce
        # on the same fingerprint in an independent round.
        script = _Script(
            verifications=[_verification(False), _verification(True), _verification(True)],
            reviews=[ReviewReport(verdict=ReviewVerdict.PASS)] * 3,
            fingerprints=["A", "A", "A"],
        )
        script.fix_reports = [FixReport(claims_done=True)]
        result = _run(script)
        self.assertEqual(result.outcome, ConvergenceOutcome.CONVERGED)
        self.assertEqual(len(result.rounds), 3)  # round 2 was refused
        self.assertTrue(any("flipped from fail to pass" in w for w in result.warnings))

    def test_convergence_requires_a_fingerprint(self):
        # The fingerprint leg of evidence_ok is load-bearing: passing
        # verification + PASS verdict cannot converge without the repo
        # fingerprint that anchors WHAT converged.
        script = _Script(
            verifications=[_verification(True)] * 2,
            reviews=[ReviewReport(verdict=ReviewVerdict.PASS)] * 2,
            fingerprints=[None, "fp2"],
        )
        result = _run(script)
        self.assertEqual(result.outcome, ConvergenceOutcome.CONVERGED)
        self.assertEqual(len(result.rounds), 2)  # round 1 could not close

    def test_gate_ledger_rides_on_stalemate_and_exhausted_exits(self):
        nit = _finding(Severity.MINOR, description="carried nit")
        blocking = _finding()
        stale = _Script(
            verifications=[_verification(True)] * 10,
            reviews=[ReviewReport(verdict=ReviewVerdict.FAIL, findings=(blocking, nit))] * 10,
            fingerprints=["same"] * 10,
        )
        stale_result = _run(stale)
        self.assertEqual(stale_result.outcome, ConvergenceOutcome.STALEMATE)
        self.assertTrue(any(g.finding == nit for g in stale_result.gate_ledger))

        exhausted = _Script(
            verifications=[_verification(True)] * 2,
            reviews=[ReviewReport(verdict=ReviewVerdict.FAIL, findings=(blocking, nit))] * 2,
            fingerprints=["a", "b"],
        )
        exhausted_result = _run(exhausted, ConvergencePolicy(max_rounds=2))
        self.assertEqual(exhausted_result.outcome, ConvergenceOutcome.ROUNDS_EXHAUSTED)
        self.assertTrue(any(g.finding == nit for g in exhausted_result.gate_ledger))

    def test_no_done_warning_when_fixer_does_not_claim_done(self):
        bad = _finding()
        script = _Script(
            verifications=[_verification(True)] * 3,
            reviews=[ReviewReport(verdict=ReviewVerdict.FAIL, findings=(bad,))] * 3,
            fingerprints=["same"] * 3,
        )
        script.fix_reports = [FixReport(claims_done=False)] * 3
        result = _run(script, ConvergencePolicy(max_rounds=3, max_unchanged_rounds=99))
        self.assertEqual(result.outcome, ConvergenceOutcome.ROUNDS_EXHAUSTED)
        self.assertFalse(any("signal without evidence" in w for w in result.warnings))

    def test_rounds_exhausted_is_bounded_and_typed(self):
        bad = _finding()
        script = _Script(
            verifications=[_verification(True)] * 3,
            reviews=[ReviewReport(verdict=ReviewVerdict.FAIL, findings=(bad,))] * 3,
            fingerprints=["a", "b", "c"] * 1,
        )
        result = _run(script, ConvergencePolicy(max_rounds=3, max_unchanged_rounds=99))
        self.assertEqual(result.outcome, ConvergenceOutcome.ROUNDS_EXHAUSTED)
        self.assertEqual(len(result.rounds), 3)

    def test_low_confidence_blocking_finding_is_gated_not_dropped(self):
        shaky = _finding(Severity.CRITICAL, confidence=0.2, description="maybe?")
        script = _Script(
            verifications=[_verification(True)],
            reviews=[ReviewReport(verdict=ReviewVerdict.PASS, findings=(shaky,))],
            fingerprints=["fp1"],
        )
        result = _run(script)
        self.assertEqual(result.outcome, ConvergenceOutcome.CONVERGED)  # gated out
        self.assertEqual(len(result.gate_ledger), 1)
        self.assertIn("confidence", result.gate_ledger[0].gate_reason)

    def test_minor_findings_do_not_block_but_survive_as_dissent(self):
        nit = _finding(Severity.MINOR, description="naming nit")
        script = _Script(
            verifications=[_verification(True)],
            reviews=[ReviewReport(verdict=ReviewVerdict.PASS, findings=(nit,))],
            fingerprints=["fp1"],
        )
        result = _run(script)
        self.assertEqual(result.outcome, ConvergenceOutcome.CONVERGED)
        self.assertIn(nit, result.dissent)
        self.assertEqual(len(result.gate_ledger), 1)  # and in the ledger

    def test_done_claim_without_repo_change_is_downgraded_to_warning(self):
        bad = _finding()
        script = _Script(
            verifications=[_verification(True)] * 3,
            reviews=[ReviewReport(verdict=ReviewVerdict.FAIL, findings=(bad,))] * 3,
            fingerprints=["same"] * 3,
        )
        script.fix_reports = [FixReport(claims_done=True)] * 3
        result = _run(script, ConvergencePolicy(max_rounds=3, max_unchanged_rounds=99))
        self.assertEqual(result.outcome, ConvergenceOutcome.ROUNDS_EXHAUSTED)
        self.assertTrue(any("signal without evidence" in w for w in result.warnings))

    def test_uncertain_verdict_never_converges_and_stalemates_out(self):
        script = _Script(
            verifications=[_verification(True)] * 10,
            reviews=[ReviewReport(verdict=ReviewVerdict.UNCERTAIN)] * 10,
            fingerprints=["same"] * 10,
        )
        result = _run(script)
        self.assertEqual(result.outcome, ConvergenceOutcome.STALEMATE)
        self.assertEqual(script.fix_requests, [])  # nothing concrete to fix

    def test_probe_exception_is_a_warning_not_a_crash_or_a_stalemate_count(self):
        bad = _finding()
        boom = RuntimeError("probe exploded")
        script = _Script(
            verifications=[boom, _verification(True)],
            reviews=[ReviewReport(verdict=ReviewVerdict.PASS),
                     ReviewReport(verdict=ReviewVerdict.PASS)],
            fingerprints=[boom, "fp2"],
        )
        result = _run(script)
        self.assertEqual(result.outcome, ConvergenceOutcome.CONVERGED)
        self.assertFalse(result.rounds[0].evidence_ok)
        self.assertTrue(any("verification collection failed" in w for w in result.warnings))
        self.assertEqual(result.rounds[1].unchanged_streak, 0)
        del bad

    def test_fixer_exception_propagates_raw(self):
        bad = _finding()
        script = _Script(
            verifications=[_verification(True)],
            reviews=[ReviewReport(verdict=ReviewVerdict.FAIL, findings=(bad,))],
            fingerprints=["fp1"],
        )

        def crashing_fix(request: FixRequest) -> FixReport:
            raise RuntimeError("fixer crashed")

        loop = ConvergenceLoop(
            ConvergencePolicy(max_rounds=3),
            verify_fn=script.verify, review_fn=script.review,
            fix_fn=crashing_fix, fingerprint_fn=script.fingerprint,
        )
        with self.assertRaises(RuntimeError):
            loop.run()

    def test_policy_validation(self):
        with self.assertRaises(ValueError):
            ConvergencePolicy(max_rounds=0)
        with self.assertRaises(ValueError):
            ConvergencePolicy(max_rounds=1, max_unchanged_rounds=0)
        with self.assertRaises(ValueError):
            ConvergencePolicy(max_rounds=1, min_blocking_confidence=1.5)


class TestGitFingerprintFailureModes(unittest.TestCase):
    def test_git_timeout_yields_none_not_an_exception(self):
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "gnosis.kernel.git_evidence.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=30),
        ):
            self.assertIsNone(git_fingerprint(Path(tmp)))

    def test_os_error_yields_none_not_an_exception(self):
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "gnosis.kernel.git_evidence.subprocess.run",
            side_effect=PermissionError("locked"),
        ):
            self.assertIsNone(git_fingerprint(Path(tmp)))


class TestGitFingerprint(unittest.TestCase):
    def test_fingerprint_tracks_repo_changes_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            self.assertIsNone(git_fingerprint(repo))  # not a repo yet
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            self.assertIsNone(git_fingerprint(repo))  # repo but no HEAD yet
            subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
            (repo / "a.txt").write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo,
                           check=True, capture_output=True)
            first = git_fingerprint(repo)
            self.assertIsNotNone(first)
            self.assertEqual(git_fingerprint(repo), first)  # stable when unchanged
            (repo / "a.txt").write_text("two\n", encoding="utf-8")
            self.assertNotEqual(git_fingerprint(repo), first)  # dirty tree differs


if __name__ == "__main__":
    unittest.main()
