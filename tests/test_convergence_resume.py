"""Crash resume preserves evidence, round bounds, stalemate and flaky-check history."""
from dataclasses import replace

import pytest

from gnosis.kernel.convergence import (
    ConvergenceLoop,
    ConvergenceOutcome,
    ConvergencePolicy,
    ConvergenceResult,
    Finding,
    FixReport,
    ReviewReport,
    ReviewVerdict,
    Severity,
)
from gnosis.kernel.verification import VerificationResult


def _verification(passed=True):
    return VerificationResult("check", passed, 0 if passed else 1, 0.1, "", "")


def _loop(*, verify=None, review=None, fix=None, fingerprint=None, rounds=3, unchanged=2):
    return ConvergenceLoop(ConvergencePolicy(rounds, max_unchanged_rounds=unchanged),
        verify or _verification,
        review or (lambda index: ReviewReport(ReviewVerdict.UNCERTAIN)),
        fix or (lambda request: FixReport()), fingerprint or (lambda: "unchanged"))


def test_crash_in_fixer_preserves_the_review_that_requested_it():
    saved, started = [], []
    finding = Finding(Severity.MAJOR, "bug", "fix x", "independent", evidence="x was one")
    fail = ReviewReport(ReviewVerdict.FAIL, (finding,), "independent")

    def crashed(request):
        raise RuntimeError("worker died")

    with pytest.raises(RuntimeError, match="worker died"):
        _loop(review=lambda index: fail, fix=crashed).run(
            on_round_started=started.append, on_progress=saved.append)
    assert started == [1]
    assert saved[-1].rounds[-1].review == fail
    assert saved[-1].rounds[-1].fix is None
    reviewed = []
    fixed = []

    def passing(index):
        reviewed.append(index)
        return ReviewReport(ReviewVerdict.PASS, reviewer="independent")

    def finish_fix(request):
        fixed.append(request)
        return FixReport(claims_done=True)

    resumed = _loop(review=passing, fix=finish_fix, fingerprint=lambda: "fixed").run(
        initial=saved[-1], start_index=2)
    assert resumed.outcome is ConvergenceOutcome.CONVERGED
    assert reviewed == [2]
    assert [r.index for r in resumed.rounds] == [1, 2]
    assert resumed.rounds[0].blocking == (finding,)
    assert resumed.rounds[0].fix.claims_done
    assert len(fixed) == 1 and fixed[0].round_index == 2
    assert fixed[0].blocking_findings == (finding,)


def test_restart_does_not_reset_stalemate_counter():
    saved = []

    def interrupted(index):
        if index == 3:
            raise RuntimeError("director died before third round")

    with pytest.raises(RuntimeError):
        _loop(rounds=5).run(on_progress=saved.append, on_round_started=interrupted)
    assert saved[-1].rounds[-1].unchanged_streak == 1
    resumed = _loop(rounds=5).run(initial=saved[-1], start_index=3)
    assert resumed.outcome is ConvergenceOutcome.STALEMATE
    assert len(resumed.rounds) == 3


def test_resume_remembers_failed_verification_before_accepting_a_flipped_pass():
    saved = []

    def interrupted(index):
        if index == 2:
            raise RuntimeError("director died")

    passing = lambda index: ReviewReport(ReviewVerdict.PASS)
    with pytest.raises(RuntimeError):
        _loop(verify=lambda: _verification(False), review=passing).run(
            on_round_started=interrupted, on_progress=saved.append)
    resumed = _loop(review=passing).run(initial=saved[-1], start_index=2)
    assert resumed.outcome is ConvergenceOutcome.CONVERGED
    assert len(resumed.rounds) == 3  # pass must be reproduced on unchanged bytes
    assert any("flipped" in warning for warning in resumed.rounds[1].warnings)


def test_rounds_spent_in_an_interrupted_probe_cannot_be_reused():
    calls = []
    result = _loop(review=lambda index: calls.append(index)).run(start_index=4)
    assert result.outcome is ConvergenceOutcome.ROUNDS_EXHAUSTED
    assert calls == []


def test_a_failed_durable_round_reservation_prevents_all_probes():
    calls = []

    def no_storage(index):
        raise OSError("state could not be saved")

    with pytest.raises(OSError):
        _loop(verify=lambda: calls.append("verify"), review=lambda i: calls.append("review")).run(
            on_round_started=no_storage)
    assert calls == []


def test_checkpoint_callback_receives_the_actual_final_outcome():
    saved = []
    result = _loop(review=lambda index: ReviewReport(ReviewVerdict.PASS)).run(on_progress=saved.append)
    assert saved[-1] == result
    assert result.outcome is ConvergenceOutcome.CONVERGED
    with pytest.raises(ValueError, match="overwrite"):
        _loop().run(initial=result, start_index=1)
    assert _loop().run(initial=result, start_index=2) == result


def test_unevidenced_terminal_checkpoint_is_refused():
    forged = ConvergenceResult(ConvergenceOutcome.CONVERGED, (), (), (), ())
    with pytest.raises(ValueError, match="no valid passing round"):
        _loop().run(initial=forged)
    valid = _loop(review=lambda i: ReviewReport(ReviewVerdict.PASS)).run()
    invalid = replace(valid, rounds=(replace(valid.rounds[0], verification=_verification(False)),))
    with pytest.raises(ValueError, match="no valid passing round"):
        _loop().run(initial=invalid, start_index=2)
