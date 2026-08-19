import unittest

from gnosis.runner.retry import RetryPolicy, execute_with_retry


class TestRetryPolicy(unittest.TestCase):
    def test_rejects_non_positive_max_attempts(self):
        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=0)

    def test_backoff_grows_and_caps(self):
        policy = RetryPolicy(max_attempts=5, backoff_base_s=1.0, backoff_factor=2.0, max_backoff_s=3.0)
        self.assertEqual(policy.backoff_for(1), 1.0)
        self.assertEqual(policy.backoff_for(2), 2.0)
        self.assertEqual(policy.backoff_for(3), 3.0)
        self.assertEqual(policy.backoff_for(4), 3.0)


class TestExecuteWithRetry(unittest.TestCase):
    def test_succeeds_first_try(self):
        calls = []
        records = execute_with_retry(
            attempt_fn=lambda n: calls.append(n) or "ok",
            should_retry=lambda r: False,
            policy=RetryPolicy(max_attempts=5),
            sleep_fn=lambda s: None,
        )
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].is_final)

    def test_stops_at_hard_limit(self):
        calls = []
        records = execute_with_retry(
            attempt_fn=lambda n: calls.append(n) or "fail",
            should_retry=lambda r: True,
            policy=RetryPolicy(max_attempts=3),
            sleep_fn=lambda s: None,
        )
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(records), 3)
        self.assertTrue(records[-1].is_final)
        self.assertTrue(all(r.result == "fail" for r in records))

    def test_succeeds_on_second_attempt(self):
        results = iter(["fail", "ok"])
        records = execute_with_retry(
            attempt_fn=lambda n: next(results),
            should_retry=lambda r: r != "ok",
            policy=RetryPolicy(max_attempts=5),
            sleep_fn=lambda s: None,
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(records[-1].result, "ok")

    def test_on_attempt_callback_invoked(self):
        seen = []
        execute_with_retry(
            attempt_fn=lambda n: "fail",
            should_retry=lambda r: True,
            policy=RetryPolicy(max_attempts=2),
            on_attempt=lambda rec: seen.append(rec.attempt),
            sleep_fn=lambda s: None,
        )
        self.assertEqual(seen, [1, 2])


if __name__ == "__main__":
    unittest.main()
