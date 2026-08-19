"""The kernel's single canonical-bytes hash primitive.

Every hash in Gnosis (ledger event hashes and chain pointers today;
replay keys, action identities, approval bindings tomorrow) derives from
exactly one byte encoding, defined here, so a third party can re-derive
any hash by hand. This is Directive 1 of the Tier-S archaeology findings
(docs/research/REFERENCE_REPOSITORY_FINDINGS.md): bernstein, opentraces,
agent-capsule, reprise and the governance toolkit each converged on one
canonical-JSON contract under all their chains; the anti-pattern to avoid
is bernstein's five parallel event systems with divergent hashing.

The contract (do not change without a superseding ADR — ADR-0004):

    canonical_json_bytes(obj) =
        json.dumps(obj,
                   sort_keys=True,
                   separators=(",", ":"),
                   ensure_ascii=False,
                   allow_nan=False).encode("utf-8")

- ``sort_keys`` makes dict insertion order irrelevant.
- Compact separators remove whitespace ambiguity.
- ``ensure_ascii=False`` keeps UTF-8 the single text encoding rather than
  ASCII-escaping some code points and not others.
- ``allow_nan=False`` rejects NaN/Infinity, which are not JSON and whose
  textual form is implementation-defined.
- Only JSON-representable values are accepted; anything else raises
  ``TypeError`` loudly instead of hashing a lossy repr.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# The chain anchor for the first entry of any hash chain.
GENESIS_HASH = "0" * 64


def canonical_json_bytes(obj: Any) -> bytes:
    """Encode ``obj`` as canonical JSON bytes (see module contract)."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_canonical(obj: Any) -> str:
    """sha256 hex digest of the canonical JSON encoding of ``obj``."""
    return sha256_hex(canonical_json_bytes(obj))
