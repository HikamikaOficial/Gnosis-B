"""Adapter milestone 3/4: ConvergenceLoop driven by real agent CLIs.

The loop already had its own suite (ADR-0008). What is under test here is
the seam: what an adapter does with output an agent actually produces,
including output that is wrong, hostile, or absent.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from gnosis.adapters.cli_review import (
    CliFixer,
    CliReviewer,
    ReviewerModifiedSubject,
    agent_message_text,
    build_fix_prompt,
    build_review_prompt,
)
from gnosis.adapters.review_payload import (
    InvalidReviewOutput,
    extract_json_object,
    parse_review_payload,
)
from gnosis.kernel.convergence import (
    ConvergenceLoop,
    ConvergenceOutcome,
    ConvergencePolicy,
    Finding,
    FixReport,
    FixRequest,
    ReviewVerdict,
    Severity,
    git_fingerprint,
)
from gnosis.kernel.verification import VerificationResult
from gnosis.runner.capture import ExecutionResult

_PASS_REVIEW = '```json\n{"verdict": "PASS", "findings": [], "notes": "clean"}\n```'


class _ScriptedAgent:
    """Writes a scripted answer to stdout the way a real CLI would."""

    def __init__(self, answers, exit_code=0, timed_out=False, on_run=None):
        self.answers = list(answers)
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.on_run = on_run
        self.calls = 0
        self.permission_modes = []

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s=900.0, **kwargs):
        self.calls += 1
        self.permission_modes.append(kwargs.get("permission_mode"))
        if self.on_run is not None:
            self.on_run(Path(cwd))
        answer = self.answers[min(self.calls, len(self.answers)) - 1]
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(json.dumps({"result": answer}), encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return ExecutionResult(
            command=("claude",), exit_code=self.exit_code, timed_out=self.timed_out,
            cancelled=False, duration_s=0.1, stdout_path=str(stdout_path),
            stderr_path=str(stderr_path), started_at="t0", ended_at="t1",
            parsed_json={"result": answer},
        )


class TestReviewPayloadParsing(unittest.TestCase):
    """An unreadable review must never become a verdict nobody gave."""

    def test_a_fenced_block_is_parsed(self):
        report = parse_review_payload(
            'Here is my review.\n' + _PASS_REVIEW, reviewer="r1")
        self.assertEqual(report.verdict, ReviewVerdict.PASS)
        self.assertEqual(report.findings, ())
        self.assertEqual(report.reviewer, "r1")

    def test_the_last_fenced_block_wins(self):
        # Agents quote the schema they were given before answering it.
        text = ('```json\n{"verdict": "FAIL"}\n```\n'
                'That was the template. My actual review:\n' + _PASS_REVIEW)
        self.assertEqual(parse_review_payload(text, "r1").verdict, ReviewVerdict.PASS)

    def test_an_object_quoted_inside_prose_is_not_a_verdict(self):
        # Contract tightened (Codex review): this used to parse as PASS.
        # There is no syntactic signal separating an agent SUBMITTING a
        # verdict from one quoting the schema while declining to give
        # one, so reading a bare object out of prose was reading intent
        # the parser cannot see — in the one place this module exists to
        # be strict about.
        text = ('I refuse to submit a review. The requested example was:\n'
                '{"verdict":"PASS","findings":[]}')
        with self.assertRaises(InvalidReviewOutput):
            parse_review_payload(text, "r1")

    def test_duplicate_keys_are_invalid_rather_than_last_one_wins(self):
        # json.loads keeps the LAST value, so this reads as PASS — and a
        # finding can downgrade its own severity the same way.
        with self.assertRaises(InvalidReviewOutput):
            parse_review_payload('{"verdict":"FAIL","verdict":"PASS","findings":[]}', "r1")
        with self.assertRaises(InvalidReviewOutput):
            parse_review_payload(
                '```json\n{"verdict":"FAIL","findings":[{"severity":"CRITICAL",'
                '"severity":"INFO","description":"d"}]}\n```', "r1")

    def test_braces_inside_strings_do_not_break_a_whole_message_object(self):
        text = '{"verdict": "PASS", "findings": [], "notes": "saw a } here"}'
        self.assertEqual(parse_review_payload(text, "r1").notes, "saw a } here")

    def test_no_json_at_all_is_invalid_not_uncertain(self):
        with self.assertRaises(InvalidReviewOutput):
            parse_review_payload("Looks fine to me!", "r1")

    def test_an_unknown_verdict_is_invalid(self):
        with self.assertRaises(InvalidReviewOutput):
            parse_review_payload('{"verdict": "LGTM"}', "r1")

    def test_a_missing_verdict_is_invalid(self):
        with self.assertRaises(InvalidReviewOutput):
            parse_review_payload('{"findings": []}', "r1")

    def test_findings_that_are_not_a_list_are_invalid(self):
        with self.assertRaises(InvalidReviewOutput):
            parse_review_payload('{"verdict": "FAIL", "findings": "lots"}', "r1")

    def test_an_unknown_severity_is_invalid(self):
        with self.assertRaises(InvalidReviewOutput):
            parse_review_payload(
                '{"verdict": "FAIL", "findings": [{"severity": "SCARY", '
                '"description": "d"}]}', "r1")

    def test_confidence_true_is_rejected_rather_than_read_as_certainty(self):
        # bool is int in Python: `true` would silently become 1.0, maximum
        # confidence from a value that expressed none.
        with self.assertRaises(InvalidReviewOutput):
            parse_review_payload(
                '{"verdict": "FAIL", "findings": [{"severity": "MAJOR", '
                '"description": "d", "confidence": true}]}', "r1")

    def test_confidence_outside_the_unit_interval_is_rejected(self):
        with self.assertRaises(InvalidReviewOutput):
            parse_review_payload(
                '{"verdict": "FAIL", "findings": [{"severity": "MAJOR", '
                '"description": "d", "confidence": 7}]}', "r1")

    def test_an_agent_cannot_forge_the_reviewer_attribution(self):
        report = parse_review_payload(
            '{"verdict": "FAIL", "findings": [{"severity": "MAJOR", '
            '"description": "d", "reviewer": "someone-trusted"}]}', "real-reviewer")
        self.assertEqual(report.findings[0].reviewer, "real-reviewer")

    def test_a_verdict_is_never_rewritten_to_match_its_findings(self):
        # A PASS carrying a CRITICAL is a disagreement the loop exists to
        # surface; silently "correcting" it here would hide it.
        report = parse_review_payload(
            '{"verdict": "PASS", "findings": [{"severity": "CRITICAL", '
            '"description": "boom"}]}', "r1")
        self.assertEqual(report.verdict, ReviewVerdict.PASS)
        self.assertEqual(report.findings[0].severity, Severity.CRITICAL)

    def test_extract_returns_the_object_not_a_list(self):
        with self.assertRaises(InvalidReviewOutput):
            extract_json_object("[1, 2, 3]")

    def test_a_trailing_fence_does_not_push_the_review_out_of_reach(self):
        # Taking only ONE fence meant anything appended after the answer
        # (a signature, a tool trace) turned a good round into INVALID.
        text = (_PASS_REVIEW + '\nReviewed by the model.\n'
                '```json\n{"tool_use_id": "abc"}\n```')
        self.assertEqual(parse_review_payload(text, "r1").verdict, ReviewVerdict.PASS)

    def test_the_verdict_bearing_fence_is_preferred_over_a_bare_one(self):
        text = '```json\n{"unrelated": 1}\n```\n' + _PASS_REVIEW
        self.assertEqual(parse_review_payload(text, "r1").verdict, ReviewVerdict.PASS)


class _AdapterTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        (self.repo / "code.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.repo, check=True, capture_output=True)
        self.evidence = self.root / "evidence"

    def tearDown(self):
        self.tmp.cleanup()

    def _reviewer(self, agent, **kwargs):
        return CliReviewer(agent, self.repo, self.evidence, "Demo objective", **kwargs)


class TestCliReviewer(_AdapterTestCase):
    def test_a_review_round_produces_a_report_and_keeps_evidence(self):
        agent = _ScriptedAgent([_PASS_REVIEW])
        report = self._reviewer(agent, reviewer_id="rev-1")(1)
        self.assertEqual(report.verdict, ReviewVerdict.PASS)
        self.assertEqual(report.reviewer, "rev-1")
        self.assertTrue((self.evidence / "review-rev-1-1.stdout").exists())

    def test_two_reviewers_sharing_a_directory_do_not_overwrite_each_other(self):
        # Round index alone collided, destroying run-specific evidence and
        # making replay attribution unreliable (Codex review).
        for reviewer_id in ("claude-cli", "codex://reviewer-2"):
            self._reviewer(_ScriptedAgent([_PASS_REVIEW]), reviewer_id=reviewer_id)(1)
        written = sorted(p.name for p in self.evidence.glob("*.stdout"))
        self.assertEqual(len(written), 2, written)
        # And an identity carrying path separators cannot escape the dir.
        for name in written:
            self.assertNotIn("/", name)
            self.assertNotIn(":", name)

    def test_the_reviewer_runs_in_a_read_only_posture(self):
        agent = _ScriptedAgent([_PASS_REVIEW])
        self._reviewer(agent)(1)
        self.assertEqual(agent.permission_modes, ["plan"])

    def test_a_reviewer_that_edits_the_subject_is_refused(self):
        # Rule 9. The permission flag is the provider's promise; this is
        # the kernel's evidence.
        def sneak(cwd):
            (cwd / "code.py").write_text("x = 2  # 'fixed' by the reviewer\n",
                                         encoding="utf-8")

        agent = _ScriptedAgent([_PASS_REVIEW], on_run=sneak)
        with self.assertRaises(ReviewerModifiedSubject):
            self._reviewer(agent)(1)

    def test_a_reviewer_is_caught_editing_an_already_dirty_file(self):
        # THE case that matters, and the one the first implementation
        # missed: during convergence a fix round has already dirtied the
        # tree, so `git status --porcelain` still reads " M code.py" and
        # `git diff --stat` still reads "1 insertion, 1 deletion" no
        # matter how many more times the reviewer rewrites that file.
        # Verified: both were byte-identical across the tamper.
        (self.repo / "code.py").write_text("x = 2\n", encoding="utf-8")

        def sneak(cwd):
            (cwd / "code.py").write_text("x = 999\n", encoding="utf-8")

        agent = _ScriptedAgent([_PASS_REVIEW], on_run=sneak)
        with self.assertRaises(ReviewerModifiedSubject):
            self._reviewer(agent)(1)

    def test_a_reviewer_is_caught_editing_a_file_with_an_accent_in_its_name(self):
        # `git status --porcelain` C-quotes non-ASCII paths
        # (`?? "caf\303\251.txt"`). Reading that literally failed, and the
        # failure was stored as a STABLE "unreadable" string — so the
        # file's bytes were never hashed and it could be edited freely. A
        # rule-9 bypass that needed nothing but an accent (Codex review,
        # reproduced).
        (self.repo / "café.txt").write_text("original", encoding="utf-8")

        def sneak(cwd):
            (cwd / "café.txt").write_text("TAMPERED", encoding="utf-8")

        agent = _ScriptedAgent([_PASS_REVIEW], on_run=sneak)
        with self.assertRaises(ReviewerModifiedSubject):
            self._reviewer(agent)(1)

    def test_a_reviewer_is_caught_editing_an_untracked_file(self):
        (self.repo / "scratch.txt").write_text("first", encoding="utf-8")

        def sneak(cwd):
            (cwd / "scratch.txt").write_text("second", encoding="utf-8")

        agent = _ScriptedAgent([_PASS_REVIEW], on_run=sneak)
        with self.assertRaises(ReviewerModifiedSubject):
            self._reviewer(agent)(1)

    def test_a_reviewer_is_caught_installing_a_git_hook(self):
        # `git status` says nothing about the repository's own machinery,
        # so a "read-only" reviewer could drop in a pre-commit hook —
        # arbitrary code that runs on the next commit — and the tamper
        # check saw an unchanged tree. Verified missed before the fix.
        def sneak(cwd):
            (cwd / ".git" / "hooks" / "pre-commit").write_text(
                "#!/bin/sh\necho pwned\n", encoding="utf-8")

        agent = _ScriptedAgent([_PASS_REVIEW], on_run=sneak)
        with self.assertRaises(ReviewerModifiedSubject):
            self._reviewer(agent)(1)

    def test_a_reviewer_is_caught_repointing_a_remote(self):
        def sneak(cwd):
            subprocess.run(["git", "config", "remote.origin.url", "https://elsewhere/x"],
                           cwd=cwd, check=True, capture_output=True)

        agent = _ScriptedAgent([_PASS_REVIEW], on_run=sneak)
        with self.assertRaises(ReviewerModifiedSubject):
            self._reviewer(agent)(1)

    def test_reading_the_repository_is_not_mistaken_for_tampering(self):
        # A tamper check that fires on `git log` would make every review
        # round fail, which is how a gate gets switched off.
        def look(cwd):
            for args in (["status"], ["log", "--oneline"], ["diff"]):
                subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

        agent = _ScriptedAgent([_PASS_REVIEW], on_run=look)
        self.assertEqual(self._reviewer(agent)(1).verdict, ReviewVerdict.PASS)

    def test_a_failed_git_probe_does_not_read_as_nothing_changed(self):
        # Otherwise breaking git would be the way to defeat the check.
        from gnosis.kernel.git_evidence import content_fingerprint
        fingerprint = content_fingerprint(self.repo)
        self.assertIn("patch_sha256", fingerprint)
        self.assertNotIn("probe_failed", fingerprint)

    def test_an_oversized_agent_message_is_read_boundedly(self):
        from gnosis.adapters.cli_review import MAX_AGENT_MESSAGE_CHARS
        huge = self.root / "huge.out"
        huge.write_text("x" * (MAX_AGENT_MESSAGE_CHARS + 5000), encoding="utf-8")
        result = ExecutionResult(
            command=("claude",), exit_code=0, timed_out=False, cancelled=False,
            duration_s=0.1, stdout_path=str(huge), stderr_path=str(huge),
            started_at="t0", ended_at="t1", parsed_json=None,
        )
        self.assertEqual(len(agent_message_text(result)), MAX_AGENT_MESSAGE_CHARS)

    def test_a_reviewer_that_only_reads_is_not_accused(self):
        def look(cwd):
            (cwd / "code.py").read_text(encoding="utf-8")

        agent = _ScriptedAgent([_PASS_REVIEW], on_run=look)
        self.assertEqual(self._reviewer(agent)(1).verdict, ReviewVerdict.PASS)

    def test_a_timed_out_reviewer_is_invalid_output_not_a_pass(self):
        agent = _ScriptedAgent([_PASS_REVIEW], timed_out=True)
        with self.assertRaises(InvalidReviewOutput):
            self._reviewer(agent)(1)

    def test_unreadable_output_raises_instead_of_inventing_uncertain(self):
        agent = _ScriptedAgent(["I could not complete the review."])
        with self.assertRaises(InvalidReviewOutput):
            self._reviewer(agent)(1)

    def test_the_prompt_states_the_read_only_contract_and_the_schema(self):
        prompt = build_review_prompt("Ship it", 2, focus=["auth"])
        self.assertIn("Do not modify any file", prompt)
        self.assertIn('"verdict"', prompt)
        self.assertIn("auth", prompt)


class TestCliFixer(_AdapterTestCase):
    def _fixer(self, agent, **kwargs):
        return CliFixer(agent, self.repo, self.evidence, "Demo objective", **kwargs)

    def _request(self):
        return FixRequest(
            round_index=1,
            blocking_findings=(Finding(Severity.MAJOR, "correctness", "off by one", "rev-1"),),
            verification=VerificationResult(name="v", passed=False, exit_code=1,
                                            duration_s=0.1, stdout_excerpt="",
                                            stderr_excerpt="boom"),
        )

    def test_a_structured_fix_report_is_read(self):
        agent = _ScriptedAgent(['```json\n{"claims_done": true, "notes": "fixed it"}\n```'])
        report = self._fixer(agent)(self._request())
        self.assertTrue(report.claims_done)
        self.assertFalse(report.cannot_fix)
        self.assertEqual(report.notes, "fixed it")

    def test_the_fixer_may_edit(self):
        agent = _ScriptedAgent(['{"claims_done": false}'])
        self._fixer(agent)(self._request())
        self.assertEqual(agent.permission_modes, ["acceptEdits"])

    def test_unreadable_fix_output_is_inconclusive_not_cannot_fix(self):
        # cannot_fix ENDS the loop; asserting it from output nobody could
        # read would stop on no evidence at all.
        agent = _ScriptedAgent(["I did some things."])
        report = self._fixer(agent)(self._request())
        self.assertFalse(report.cannot_fix)
        self.assertFalse(report.claims_done)
        self.assertIn("inconclusive", report.notes)

    def test_a_truthy_non_boolean_is_not_a_claim_of_doneness(self):
        agent = _ScriptedAgent(['{"claims_done": "yes, definitely"}'])
        self.assertFalse(self._fixer(agent)(self._request()).claims_done)

    def test_the_prompt_carries_the_blocking_findings(self):
        prompt = build_fix_prompt(self._request(), "Ship it")
        self.assertIn("off by one", prompt)
        self.assertIn("MAJOR", prompt)
        self.assertIn("FAILING", prompt)


class TestLoopWithRealAdapters(_AdapterTestCase):
    """L-0006 again: the adapters have to drive the actual loop."""

    def _fingerprint(self):
        return git_fingerprint(self.repo)

    def test_a_clean_review_converges_through_the_real_adapter(self):
        agent = _ScriptedAgent([_PASS_REVIEW])
        result = ConvergenceLoop(
            policy=ConvergencePolicy(max_rounds=3),
            verify_fn=lambda: VerificationResult(
                name="v", passed=True, exit_code=0, duration_s=0.1,
                stdout_excerpt="", stderr_excerpt=""),
            review_fn=self._reviewer(agent, reviewer_id="rev-1"),
            fix_fn=lambda request: FixReport(claims_done=True),
            fingerprint_fn=self._fingerprint,
        ).run()
        self.assertEqual(result.outcome, ConvergenceOutcome.CONVERGED)
        self.assertEqual(agent.calls, 1)

    def test_evidence_failures_keep_their_type_not_just_a_message(self):
        # "review collection failed: ..." reads the same whether the agent
        # produced unreadable output, edited the code it was judging, or
        # crashed — and the constitution requires INVALID_AGENT_OUTPUT to
        # stay distinct from disagreement (Codex review).
        agent = _ScriptedAgent(["no json here"])
        result = ConvergenceLoop(
            policy=ConvergencePolicy(max_rounds=1),
            verify_fn=lambda: VerificationResult(
                name="v", passed=True, exit_code=0, duration_s=0.1,
                stdout_excerpt="", stderr_excerpt=""),
            review_fn=self._reviewer(agent),
            fix_fn=lambda request: FixReport(claims_done=False),
            fingerprint_fn=self._fingerprint,
        ).run()
        types = {f.error_type for f in result.evidence_failures}
        self.assertIn("InvalidReviewOutput", types)
        self.assertEqual({f.stage for f in result.evidence_failures}, {"review"})

    def test_reviewer_tampering_is_distinguishable_from_unreadable_output(self):
        def sneak(cwd):
            (cwd / "code.py").write_text("tampered\n", encoding="utf-8")

        result = ConvergenceLoop(
            policy=ConvergencePolicy(max_rounds=1),
            verify_fn=lambda: VerificationResult(
                name="v", passed=True, exit_code=0, duration_s=0.1,
                stdout_excerpt="", stderr_excerpt=""),
            review_fn=self._reviewer(_ScriptedAgent([_PASS_REVIEW], on_run=sneak)),
            fix_fn=lambda request: FixReport(claims_done=False),
            fingerprint_fn=self._fingerprint,
        ).run()
        self.assertIn("ReviewerModifiedSubject",
                      {f.error_type for f in result.evidence_failures})

    def test_an_unreadable_review_cannot_converge_the_loop(self):
        # The loop treats it as evidence collection failing: no verdict
        # was collected, so nothing may be concluded from the round.
        agent = _ScriptedAgent(["no json here"])
        result = ConvergenceLoop(
            policy=ConvergencePolicy(max_rounds=2),
            verify_fn=lambda: VerificationResult(
                name="v", passed=True, exit_code=0, duration_s=0.1,
                stdout_excerpt="", stderr_excerpt=""),
            review_fn=self._reviewer(agent),
            fix_fn=lambda request: FixReport(claims_done=False),
            fingerprint_fn=self._fingerprint,
        ).run()
        self.assertNotEqual(result.outcome, ConvergenceOutcome.CONVERGED)
        self.assertTrue(any("review" in w for w in result.warnings))

    def test_a_reviewer_that_edits_stops_the_round_rather_than_being_believed(self):
        def sneak(cwd):
            (cwd / "code.py").write_text("tampered\n", encoding="utf-8")

        agent = _ScriptedAgent([_PASS_REVIEW], on_run=sneak)
        result = ConvergenceLoop(
            policy=ConvergencePolicy(max_rounds=1),
            verify_fn=lambda: VerificationResult(
                name="v", passed=True, exit_code=0, duration_s=0.1,
                stdout_excerpt="", stderr_excerpt=""),
            review_fn=self._reviewer(agent),
            fix_fn=lambda request: FixReport(claims_done=False),
            fingerprint_fn=self._fingerprint,
        ).run()
        self.assertNotEqual(result.outcome, ConvergenceOutcome.CONVERGED)


class TestAgentMessageExtraction(unittest.TestCase):
    def test_the_envelope_result_field_is_preferred(self):
        result = ExecutionResult(
            command=("claude",), exit_code=0, timed_out=False, cancelled=False,
            duration_s=0.1, stdout_path="nonexistent", stderr_path="nonexistent",
            started_at="t0", ended_at="t1", parsed_json={"result": "the answer"},
        )
        self.assertEqual(agent_message_text(result), "the answer")

    def test_raw_stdout_is_the_fallback_when_the_envelope_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "o.txt"
            out.write_text("plain text review", encoding="utf-8")
            result = ExecutionResult(
                command=("claude",), exit_code=0, timed_out=False, cancelled=False,
                duration_s=0.1, stdout_path=str(out), stderr_path=str(out),
                started_at="t0", ended_at="t1", parsed_json=None,
            )
            self.assertEqual(agent_message_text(result), "plain text review")

    def test_an_unreadable_stdout_yields_empty_text_not_a_crash(self):
        result = ExecutionResult(
            command=("claude",), exit_code=0, timed_out=False, cancelled=False,
            duration_s=0.1, stdout_path="does/not/exist", stderr_path="x",
            started_at="t0", ended_at="t1", parsed_json=None,
        )
        self.assertEqual(agent_message_text(result), "")


if __name__ == "__main__":
    unittest.main()
