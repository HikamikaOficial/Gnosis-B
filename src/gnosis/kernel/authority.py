"""Compatibility re-export for the F-17 authority boundary.

The authoritative implementation moved to the Trust Plane in the Stage-1
trust-plane split (see `docs/F17_PRODUCTION_WIRING_AND_CLOSURE.md` §3):

  - `gnosis.trust.anchor`  — AnchorRecord / AnchorStore / RunIdentity /
    publish_anchor / verify_anchored_bundle (the anchor slice);
  - `gnosis.trust.launch`  — AuthorityUnavailable / process_integrity /
    lowered_primary_token / run_at_integrity / assert_integrity /
    label_high_no_write_up / assert_publisher_identity (the launch/identity
    slice).

This module keeps NO implementation of its own — it re-exports those single
authoritative primitives so existing importers of `gnosis.kernel.authority`
keep working, without a second, divergent copy. There is exactly one
implementation of each primitive.
"""
from __future__ import annotations

from gnosis.trust.anchor import (
    ANCHOR_SCHEMA,
    ANCHOR_SCHEMA_V2,
    CURRENT_ANCHOR_SCHEMA,
    RUN_IDENTITY_SCHEMA,
    SUPPORTED_ANCHOR_SCHEMAS,
    AnchorNotDeploymentBound,
    AnchorRecord,
    AnchorStore,
    RunIdentity,
    _bundle_content_digest,
    _bundle_head_sha,
    publish_anchor,
    verify_anchored_bundle,
)
from gnosis.trust.launch import (
    SID_HIGH,
    SID_LOW,
    SID_MEDIUM,
    AuthorityUnavailable,
    assert_integrity,
    assert_publisher_identity,
    label_high_no_write_up,
    lowered_primary_token,
    process_integrity,
    run_at_integrity,
)

__all__ = [
    "ANCHOR_SCHEMA",
    "ANCHOR_SCHEMA_V2",
    "CURRENT_ANCHOR_SCHEMA",
    "RUN_IDENTITY_SCHEMA",
    "SID_HIGH",
    "SID_LOW",
    "SID_MEDIUM",
    "SUPPORTED_ANCHOR_SCHEMAS",
    "AnchorNotDeploymentBound",
    "AnchorRecord",
    "AnchorStore",
    "AuthorityUnavailable",
    "RunIdentity",
    "_bundle_content_digest",
    "_bundle_head_sha",
    "assert_integrity",
    "assert_publisher_identity",
    "label_high_no_write_up",
    "lowered_primary_token",
    "process_integrity",
    "publish_anchor",
    "run_at_integrity",
    "verify_anchored_bundle",
]
