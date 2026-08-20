import unittest

from gnosis.kernel.failures import (
    DEFAULT_CHAIN,
    Disposition,
    EvidenceGrade,
    FailureClass,
    FailureClassification,
    FailureClassifierChain,
    FailureSignal,
    HoldRegistry,
    HoldScope,
    NamedClassifier,
    RateLimitHold,
    SchedulerAction,
    StrandedRun,
    boot_sweep,
    hold_from_classification,
    make_structured_rate_limit_classifier,
    scheduler_action,
)


class TestGradedClassification(unittest.TestCase):
    def test_exit_zero_is_a_structured_pass(self):
        result = DEFAULT_CHAIN.classify(FailureSignal(exit_code=0))
        self.assertEqual(result.failure, FailureClass.PASS)
        self.assertEqual(result.evidence_grade, EvidenceGrade.STRUCTURED)
        self.assertFalse(result.penalizes_agent)

    def test_structured_rate_limit_carries_a_reset_timestamp(self):
        result = DEFAULT_CHAIN.classify(FailureSignal(
            exit_code=1,
            structured={"error_type": "rate_limit", "reset_at": 1770000000,
                        "credential": "claude:nicol"},
        ))
        self.assertEqual(result.failure, FailureClass.RATE_LIMITED)
        self.assertEqual(result.evidence_grade, EvidenceGrade.SEMI_STRUCTURED)
        self.assertEqual(result.reset_at, 1770000000.0)

    def test_prose_rate_limit_refuses_to_invent_a_reset_time(self):
        # A parked run with a fabricated window is worse than one that
        # waits for an operator.
        result = DEFAULT_CHAIN.classify(FailureSignal(
            exit_code=1, stderr_text="Error: usage limit reached, try again later",
        ))
        self.assertEqual(result.failure, FailureClass.RATE_LIMITED)
        self.assertEqual(result.evidence_grade, EvidenceGrade.PROSE)
        self.assertIsNone(result.reset_at)
        self.assertTrue(result.detail["reset_unknown"])

    def test_prose_can_never_overrule_structured_evidence(self):
        # An exit code of 0 with a log line mentioning "rate limit" is a
        # SUCCESS whose logs mention rate limiting, not a rate limit.
        result = DEFAULT_CHAIN.classify(FailureSignal(
            exit_code=0, stderr_text="warning: approaching rate limit",
        ))
        self.assertEqual(result.failure, FailureClass.PASS)
        self.assertEqual(result.evidence_grade, EvidenceGrade.STRUCTURED)

    def test_structured_beats_prose_regardless_of_registration_order(self):
        chain = FailureClassifierChain([
            NamedClassifier("prose", EvidenceGrade.PROSE,
                            lambda s: FailureClassification(
                                FailureClass.FAIL_CODE, "guessed",
                                EvidenceGrade.PROSE, "prose")),
            NamedClassifier("structured", EvidenceGrade.STRUCTURED,
                            lambda s: FailureClassification(
                                FailureClass.TIMEOUT, "measured",
                                EvidenceGrade.STRUCTURED, "structured")),
        ])
        result = chain.classify(FailureSignal(exit_code=1))
        self.assertEqual(result.reason_code, "measured")

    def test_a_classifier_cannot_promote_its_own_evidence_grade(self):
        # The grade is the chain's property; a classifier claiming
        # STRUCTURED while registered as PROSE gets its real grade.
        chain = FailureClassifierChain([
            NamedClassifier("liar", EvidenceGrade.PROSE,
                            lambda s: FailureClassification(
                                FailureClass.FAIL_CODE, "claims_structured",
                                EvidenceGrade.STRUCTURED, "liar")),
        ])
        result = chain.classify(FailureSignal(exit_code=1))
        self.assertEqual(result.evidence_grade, EvidenceGrade.PROSE)

    def test_a_bare_nonzero_exit_is_a_code_failure_not_a_mystery(self):
        # An exit code IS structured evidence. Calling it UNCLASSIFIED
        # would escalate every ordinary failure and make the taxonomy the
        # first thing a caller bypasses (both reviews raised this).
        result = DEFAULT_CHAIN.classify(FailureSignal(exit_code=42))
        self.assertEqual(result.failure, FailureClass.FAIL_CODE)
        self.assertEqual(result.evidence_grade, EvidenceGrade.LAST_RESORT)
        self.assertEqual(scheduler_action(result), SchedulerAction.RETRY)
        self.assertTrue(result.penalizes_agent)

    def test_richer_evidence_outranks_the_bare_exit_code(self):
        # A rate-limited process also exits non-zero: it must PARK, not
        # burn retries against a shut window.
        result = DEFAULT_CHAIN.classify(FailureSignal(
            exit_code=1, stderr_text="Error: usage limit reached",
        ))
        self.assertEqual(result.failure, FailureClass.RATE_LIMITED)

    def test_a_signal_with_no_evidence_at_all_is_unclassified(self):
        result = DEFAULT_CHAIN.classify(FailureSignal())
        self.assertEqual(result.failure, FailureClass.UNCLASSIFIED)
        self.assertEqual(result.evidence_grade, EvidenceGrade.NONE)
        self.assertEqual(result.reason_code, "no_classifier_matched")

    def test_a_bool_exit_code_is_refused_rather_than_read_as_success(self):
        # bool IS int in Python: exit_code=False would have classified a
        # FAILED process as PASS at structured grade (Codex review).
        with self.assertRaises(TypeError):
            FailureSignal(exit_code=False)
        with self.assertRaises(TypeError):
            FailureSignal(timed_out="yes")

    def test_relative_retry_after_becomes_an_absolute_window(self):
        # HTTP's Retry-After is RELATIVE seconds; discarding it left the
        # hold with no window, and a hold with no window never expires —
        # one rate limit wedging a credential forever (Codex review).
        chain = FailureClassifierChain([
            NamedClassifier("structured_rate_limit", EvidenceGrade.SEMI_STRUCTURED,
                            make_structured_rate_limit_classifier(lambda: 1000.0)),
        ])
        result = chain.classify(FailureSignal(
            exit_code=1, structured={"rate_limited": True, "retry_after": 60},
        ))
        self.assertEqual(result.reset_at, 1060.0)
        self.assertEqual(result.detail["reset_source"], "relative")

    def test_nonsense_reset_values_are_rejected_not_coerced(self):
        # True -> 1.0 reopens a shut window instantly; NaN never satisfies
        # `now >= reset_at` and wedges the credential forever.
        for bad in (True, float("nan"), float("inf"), "600"):
            result = DEFAULT_CHAIN.classify(FailureSignal(
                exit_code=1, structured={"rate_limited": True, "reset_at": bad},
            ))
            self.assertIsNone(result.reset_at, msg=repr(bad))
            self.assertEqual(result.detail["reset_source"], "unknown", msg=repr(bad))

    def test_a_raising_classifier_does_not_decide(self):
        def boom(_: FailureSignal) -> FailureClassification:
            raise ValueError("classifier exploded")

        chain = FailureClassifierChain([
            NamedClassifier("boom", EvidenceGrade.STRUCTURED, boom),
        ])
        result = chain.classify(FailureSignal(exit_code=1))
        self.assertEqual(result.failure, FailureClass.UNCLASSIFIED)
        self.assertEqual(result.reason_code, "classifier_raised")


class TestConstitutionRules(unittest.TestCase):
    """Rules 5-7 are the point of this taxonomy, so they get their own
    assertions rather than being implied by other tests."""

    def test_rate_limited_is_not_a_code_failure(self):
        rate = FailureClassification(FailureClass.RATE_LIMITED, "rl",
                                     EvidenceGrade.SEMI_STRUCTURED, "c")
        self.assertNotEqual(rate.failure, FailureClass.FAIL_CODE)
        self.assertTrue(rate.is_park)
        self.assertEqual(scheduler_action(rate), SchedulerAction.PARK)
        self.assertNotEqual(scheduler_action(rate), SchedulerAction.RETRY)

    def test_infra_failures_do_not_penalize_the_agent(self):
        for failure in (FailureClass.FAIL_INFRA, FailureClass.RATE_LIMITED,
                        FailureClass.STALE_LEASE, FailureClass.DEPENDENCY_ERROR):
            classification = FailureClassification(failure, "r", EvidenceGrade.STRUCTURED, "c")
            self.assertFalse(classification.penalizes_agent, msg=failure.value)

    def test_agent_failures_do_penalize(self):
        for failure in (FailureClass.FAIL_CODE, FailureClass.FAIL_TEST,
                        FailureClass.FAIL_REVIEW, FailureClass.INVALID_AGENT_OUTPUT):
            classification = FailureClassification(failure, "r", EvidenceGrade.STRUCTURED, "c")
            self.assertTrue(classification.penalizes_agent, msg=failure.value)

    def test_unclassified_escalates_instead_of_retrying(self):
        # Repeating an action nobody understood is how a loop becomes
        # infinite and how a destructive call gets made twice.
        unknown = FailureClassification(FailureClass.UNCLASSIFIED, "?",
                                        EvidenceGrade.NONE, "chain")
        self.assertEqual(scheduler_action(unknown), SchedulerAction.ESCALATE)

    def test_reason_code_flows_unchanged_into_the_scheduler_view(self):
        signal = FailureSignal(exit_code=1, structured={"error_type": "rate_limit"})
        classification = DEFAULT_CHAIN.classify(signal)
        event_payload = classification.to_dict()
        self.assertEqual(event_payload["reason_code"], classification.reason_code)
        self.assertEqual(event_payload["evidence_grade"],
                         classification.evidence_grade.value)


class TestRateLimitHolds(unittest.TestCase):
    def setUp(self):
        self.registry = HoldRegistry()

    def test_account_hold_blocks_everything_on_that_credential(self):
        hold = RateLimitHold("claude:nicol", HoldScope.ACCOUNT, "rl", reset_at=200.0)
        self.registry.reconcile([hold], now=100.0)
        self.assertFalse(self.registry.admits("claude:nicol", now=100.0))
        self.assertFalse(self.registry.admits("claude:nicol", now=100.0, is_resume=True))
        # A different credential is unaffected.
        self.assertTrue(self.registry.admits("codex:nicol", now=100.0))

    def test_probe_hold_admits_only_the_named_probing_run(self):
        # `is_resume=True` alone was an unconstrained claim any caller
        # could make, so every queued resume was admitted at once — the
        # stampede a probe exists to prevent (Codex review).
        hold = RateLimitHold("claude:nicol", HoldScope.PROBE, "rl", reset_at=200.0,
                             probe_holder="RUN-PROBE")
        self.registry.reconcile([hold], now=100.0)
        self.assertTrue(self.registry.admits(
            "claude:nicol", now=100.0, is_resume=True, runner_id="RUN-PROBE"))
        self.assertFalse(self.registry.admits(
            "claude:nicol", now=100.0, is_resume=True, runner_id="RUN-OTHER"))
        self.assertFalse(self.registry.admits(
            "claude:nicol", now=100.0, is_resume=True))  # unattributable
        self.assertFalse(self.registry.admits("claude:nicol", now=100.0))

    def test_an_unattributable_probe_hold_admits_nobody(self):
        self.registry.reconcile(
            [RateLimitHold("claude:nicol", HoldScope.PROBE, "rl", reset_at=200.0)],
            now=100.0,
        )
        self.assertFalse(self.registry.admits(
            "claude:nicol", now=100.0, is_resume=True, runner_id="RUN-ANY"))

    def test_a_probe_hold_must_name_its_holder(self):
        rate = FailureClassification(FailureClass.RATE_LIMITED, "rl",
                                     EvidenceGrade.SEMI_STRUCTURED, "c")
        with self.assertRaises(ValueError):
            hold_from_classification(rate, "claude:nicol", now=1.0,
                                     scope=HoldScope.PROBE)

    def test_reconcile_keeps_the_most_restrictive_competing_hold(self):
        # Keeping the first record seen reopened a window a later durable
        # record says is still shut (Codex review).
        for order in ([100.0, 1000.0], [1000.0, 100.0]):
            registry = HoldRegistry()
            registry.reconcile(
                [RateLimitHold("claude:nicol", HoldScope.ACCOUNT, "rl", reset_at=t)
                 for t in order],
                now=50.0,
            )
            self.assertEqual(registry.hold_for("claude:nicol").reset_at, 1000.0,
                             msg=str(order))
            self.assertFalse(registry.admits("claude:nicol", now=150.0))

    def test_an_unknown_window_outranks_a_known_one(self):
        # "We do not know when it reopens" forbids more than a deadline.
        registry = HoldRegistry()
        registry.reconcile([
            RateLimitHold("claude:nicol", HoldScope.ACCOUNT, "known", reset_at=200.0),
            RateLimitHold("claude:nicol", HoldScope.ACCOUNT, "unknown"),
        ], now=100.0)
        self.assertIsNone(registry.hold_for("claude:nicol").reset_at)

    def test_account_hold_outranks_a_probe_hold_for_the_same_credential(self):
        self.registry.reconcile([
            RateLimitHold("claude:nicol", HoldScope.PROBE, "probe", reset_at=200.0),
            RateLimitHold("claude:nicol", HoldScope.ACCOUNT, "shut", reset_at=200.0),
        ], now=100.0)
        self.assertEqual(self.registry.hold_for("claude:nicol").scope, HoldScope.ACCOUNT)
        self.assertFalse(self.registry.admits("claude:nicol", now=100.0, is_resume=True))

    def test_expired_holds_are_dropped_on_reconcile(self):
        self.registry.reconcile(
            [RateLimitHold("claude:nicol", HoldScope.ACCOUNT, "rl", reset_at=150.0)],
            now=200.0,
        )
        self.assertEqual(self.registry.live_holds(), [])
        self.assertTrue(self.registry.admits("claude:nicol", now=200.0))

    def test_a_hold_with_an_unknown_window_never_expires_on_its_own(self):
        # Guessing a reset time is what turns one rate limit into a
        # stampede; an unknown window waits for evidence or an operator.
        hold = RateLimitHold("claude:nicol", HoldScope.ACCOUNT, "rate_limit_prose")
        self.registry.reconcile([hold], now=10_000_000.0)
        self.assertFalse(self.registry.admits("claude:nicol", now=10_000_000.0))

    def test_reconcile_is_idempotent_and_rebuilds_from_durable_state(self):
        records = [RateLimitHold("claude:nicol", HoldScope.ACCOUNT, "rl", reset_at=500.0)]
        first = self.registry.reconcile(records, now=100.0)
        second = self.registry.reconcile(records, now=100.0)
        self.assertEqual([h.to_dict() for h in first], [h.to_dict() for h in second])
        # A fresh registry (i.e. after a restart) lands in the same state.
        restarted = HoldRegistry()
        restarted.reconcile(records, now=100.0)
        self.assertEqual([h.to_dict() for h in restarted.live_holds()],
                         [h.to_dict() for h in self.registry.live_holds()])

    def test_reconcile_forgets_holds_absent_from_durable_state(self):
        # The registry holds no truth of its own.
        self.registry.reconcile(
            [RateLimitHold("claude:nicol", HoldScope.ACCOUNT, "rl", reset_at=500.0)],
            now=100.0,
        )
        self.registry.reconcile([], now=100.0)
        self.assertTrue(self.registry.admits("claude:nicol", now=100.0))

    def test_hold_is_built_only_from_a_park_classification(self):
        rate = DEFAULT_CHAIN.classify(FailureSignal(
            exit_code=1, structured={"error_type": "rate_limit", "reset_at": 900},
        ))
        hold = hold_from_classification(rate, "claude:nicol", now=100.0)
        self.assertIsNotNone(hold)
        self.assertEqual(hold.reset_at, 900.0)
        self.assertEqual(hold.reason_code, rate.reason_code)

        not_a_park = FailureClassification(FailureClass.FAIL_TEST, "t",
                                           EvidenceGrade.STRUCTURED, "c")
        self.assertIsNone(hold_from_classification(not_a_park, "claude:nicol", now=1.0))

    def test_hold_round_trips_through_its_durable_form(self):
        hold = RateLimitHold("claude:nicol", HoldScope.PROBE, "rl",
                             reset_at=200.0, placed_at=100.0)
        self.assertEqual(RateLimitHold.from_dict(hold.to_dict()), hold)


class TestBootSweep(unittest.TestCase):
    def test_a_live_run_is_left_strictly_alone(self):
        run = StrandedRun("RUN-1", "TASK-1", "RUNNING",
                          process_alive=True, heartbeat_stale_s=5.0)
        outcome = boot_sweep([run])[0]
        self.assertEqual(outcome.disposition, Disposition.UNTOUCHED)
        self.assertEqual(outcome.action, SchedulerAction.CONTINUE)

    def test_a_dead_run_is_readopted_through_the_normal_path(self):
        run = StrandedRun("RUN-2", "TASK-2", "RUNNING",
                          process_alive=False, heartbeat_stale_s=999.0)
        outcome = boot_sweep([run])[0]
        self.assertEqual(outcome.disposition, Disposition.READOPTED)
        self.assertEqual(outcome.action, SchedulerAction.RETRY)
        self.assertEqual(outcome.reason_code, "no_live_process")

    def test_a_hung_but_alive_run_is_readopted_once_stale(self):
        run = StrandedRun("RUN-3", "TASK-3", "RUNNING",
                          process_alive=True, heartbeat_stale_s=600.0)
        outcome = boot_sweep([run], stale_after_s=120.0)[0]
        self.assertEqual(outcome.disposition, Disposition.READOPTED)

    def test_an_escalating_classification_fails_loudly_instead_of_looping(self):
        run = StrandedRun(
            "RUN-4", "TASK-4", "RUNNING", process_alive=False, heartbeat_stale_s=999.0,
            classification=FailureClassification(
                FailureClass.FAIL_SECURITY, "sandbox_violation",
                EvidenceGrade.STRUCTURED, "adapter"),
        )
        outcome = boot_sweep([run])[0]
        self.assertEqual(outcome.disposition, Disposition.FAILED)
        self.assertEqual(outcome.action, SchedulerAction.ESCALATE)
        self.assertEqual(outcome.reason_code, "sandbox_violation")

    def test_a_rate_limited_stranded_run_parks_rather_than_failing(self):
        run = StrandedRun(
            "RUN-5", "TASK-5", "RUNNING", process_alive=False, heartbeat_stale_s=999.0,
            classification=FailureClassification(
                FailureClass.RATE_LIMITED, "rate_limit_structured",
                EvidenceGrade.SEMI_STRUCTURED, "adapter", reset_at=900.0),
        )
        outcome = boot_sweep([run])[0]
        self.assertEqual(outcome.action, SchedulerAction.PARK)
        self.assertEqual(outcome.disposition, Disposition.READOPTED)

    def test_every_stranded_run_leaves_with_a_disposition(self):
        # No ghosts: a record that is neither progressing nor terminal is
        # the one outcome this sweep exists to make impossible.
        runs = [
            StrandedRun("RUN-A", "T", "RUNNING", True, 1.0),
            StrandedRun("RUN-B", "T", "RUNNING", False, 999.0),
            StrandedRun("RUN-C", "T", "RUNNING", None, None),
        ]
        outcomes = boot_sweep(runs)
        self.assertEqual(len(outcomes), len(runs))
        self.assertTrue(all(o.reason_code for o in outcomes))
        self.assertEqual({o.run.run_id for o in outcomes},
                         {"RUN-A", "RUN-B", "RUN-C"})

    def test_sweep_is_idempotent_for_the_same_input(self):
        runs = [StrandedRun("RUN-B", "T", "RUNNING", False, 999.0)]
        first = [o.to_dict() for o in boot_sweep(runs)]
        second = [o.to_dict() for o in boot_sweep(runs)]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
