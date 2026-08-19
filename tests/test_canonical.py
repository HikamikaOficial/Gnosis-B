import math
import unittest

from gnosis.kernel.canonical import (
    GENESIS_HASH,
    canonical_json_bytes,
    hash_canonical,
    sha256_hex,
)


class TestCanonicalJsonBytes(unittest.TestCase):
    def test_key_order_is_irrelevant(self):
        a = {"b": 1, "a": {"d": 2, "c": 3}}
        b = {"a": {"c": 3, "d": 2}, "b": 1}
        self.assertEqual(canonical_json_bytes(a), canonical_json_bytes(b))
        self.assertEqual(hash_canonical(a), hash_canonical(b))

    def test_compact_separators_and_utf8(self):
        self.assertEqual(canonical_json_bytes({"k": [1, 2]}), b'{"k":[1,2]}')
        # ensure_ascii=False: UTF-8 bytes, not \u escapes.
        self.assertEqual(canonical_json_bytes("caña"), '"caña"'.encode())

    def test_known_vector_is_stable(self):
        # Pinned so an accidental contract change fails loudly. sha256 of
        # b'{"a":1}' — re-derivable by hand per the module docstring.
        self.assertEqual(
            hash_canonical({"a": 1}),
            "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862",
        )

    def test_nan_and_infinity_are_rejected(self):
        for bad in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                canonical_json_bytes({"v": bad})

    def test_non_json_types_are_rejected(self):
        with self.assertRaises(TypeError):
            canonical_json_bytes({"v": object()})

    def test_sha256_hex_and_genesis_shape(self):
        digest = sha256_hex(b"")
        self.assertEqual(len(digest), 64)
        self.assertEqual(len(GENESIS_HASH), 64)
        self.assertEqual(GENESIS_HASH, "0" * 64)


if __name__ == "__main__":
    unittest.main()
