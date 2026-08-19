import unittest

from gnosis.kernel.redaction import redact, redact_mapping


class TestRedaction(unittest.TestCase):
    def test_redacts_anthropic_key(self):
        text = "Using key sk-ant-api03-abcdefghijklmnopqrstuvwx for auth"
        out = redact(text)
        self.assertNotIn("sk-ant-", out)
        self.assertIn("REDACTED:ANTHROPIC_API_KEY", out)

    def test_redacts_generic_assignment(self):
        text = 'password: "SuperSecret123!"'
        out = redact(text)
        self.assertNotIn("SuperSecret123", out)

    def test_redacts_private_key_block(self):
        text = "-----BEGIN RSA PRIVATE KEY-----\nabc\ndef\n-----END RSA PRIVATE KEY-----"
        out = redact(text)
        self.assertNotIn("abc", out)

    def test_leaves_normal_text_alone(self):
        text = "The build passed with 42 tests."
        self.assertEqual(redact(text), text)

    def test_redact_mapping_recurses(self):
        data = {"note": "token=abcdef1234567890", "nested": {"x": "AKIAABCDEFGHIJKLMNOP"}}
        out = redact_mapping(data)
        self.assertNotIn("abcdef1234567890", out["note"])
        self.assertNotIn("AKIAABCDEFGHIJKLMNOP", out["nested"]["x"])


if __name__ == "__main__":
    unittest.main()
