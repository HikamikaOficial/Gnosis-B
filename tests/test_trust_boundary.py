"""Trust-plane boundary tests (F-17 Stage 1 — trust-plane split).

These keep the Trust Plane minimal: they fail if `gnosis.trust` starts
importing worker-plane code, if a second canonical-hash implementation appears,
if the compatibility facade stops pointing at the authoritative implementation,
or if probe code (ProbeAnchorStore) leaks into `src/`. The load-time import
closure is measured in a CLEAN subprocess so pytest's own imports do not
pollute it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"

# Worker-plane / development substrings the Trust Plane must never pull in at
# import time. evidence_capture is allowed only via a LAZY import inside
# publish_anchor/verify_anchored_bundle, so it must NOT be present at load.
FORBIDDEN = (
    "engine", "planner", "scheduler", "policy", "runner", "adapter",
    "claude", "codex", "plugin", "director", "evidence_capture",
    "integration", "convergence", "worktree",
)


def _load_closure(module: str) -> set[str]:
    """gnosis.* modules loaded by importing `module` in a fresh interpreter."""
    code = (
        f"import {module}; import sys; "
        "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('gnosis'))))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, check=True, cwd=str(REPO))
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def test_trust_anchor_load_closure_has_no_forbidden_modules() -> None:
    closure = _load_closure("gnosis.trust.anchor")
    leaked = [m for m in closure for bad in FORBIDDEN if bad in m]
    assert not leaked, f"trust.anchor pulled forbidden modules at load: {leaked}"
    # exactly the minimal TCB closure
    assert closure == {
        "gnosis", "gnosis.kernel", "gnosis.kernel.canonical",
        "gnosis.trust", "gnosis.trust.anchor", "gnosis.trust.launch",
    }, f"unexpected trust.anchor closure: {sorted(closure)}"


def test_trust_launch_load_closure_has_no_forbidden_modules() -> None:
    closure = _load_closure("gnosis.trust.launch")
    leaked = [m for m in closure for bad in FORBIDDEN if bad in m]
    assert not leaked, f"trust.launch pulled forbidden modules at load: {leaked}"


def test_evidence_capture_is_only_a_lazy_import() -> None:
    # importing the anchor module must NOT eagerly import the capture machinery
    closure = _load_closure("gnosis.trust.anchor")
    assert "gnosis.kernel.evidence_capture" not in closure


def test_facade_points_at_the_single_authoritative_implementation() -> None:
    import gnosis.kernel.authority as facade
    from gnosis.trust import anchor, launch

    assert facade.AnchorStore is anchor.AnchorStore
    assert facade.AnchorRecord is anchor.AnchorRecord
    assert facade.RunIdentity is anchor.RunIdentity
    assert facade.publish_anchor is anchor.publish_anchor
    assert facade.verify_anchored_bundle is anchor.verify_anchored_bundle
    assert facade.AuthorityUnavailable is launch.AuthorityUnavailable
    assert facade.process_integrity is launch.process_integrity
    assert facade.assert_integrity is launch.assert_integrity
    assert facade.label_high_no_write_up is launch.label_high_no_write_up
    assert facade.assert_publisher_identity is launch.assert_publisher_identity


def test_canonical_hash_is_not_duplicated() -> None:
    from gnosis.kernel import canonical
    from gnosis.trust import anchor

    # the anchor module uses the ONE canonical primitive, not a private copy
    assert anchor.hash_canonical is canonical.hash_canonical
    assert anchor.GENESIS_HASH is canonical.GENESIS_HASH


def test_no_probe_anchor_store_in_production_source() -> None:
    hits = [
        p for p in SRC.rglob("*.py")
        if "ProbeAnchorStore" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not hits, f"ProbeAnchorStore (probe code) leaked into src/: {hits}"


def test_publisher_identity_precondition_fails_closed_when_not_the_publisher() -> None:
    # The AnchorStore precondition locus (Stage 1 = the same-user-MIC HIGH
    # check; future = the RESTRICTED service-SID gate). It must fail closed when
    # the current identity is not the trusted publisher, and stay silent when it
    # is. Windows-only: the MIC gate is a Windows mechanism.
    if sys.platform != "win32":
        import pytest
        pytest.skip("publisher-identity precondition is a Windows mechanism")
    from gnosis.trust import launch

    original = launch.process_integrity
    try:
        launch.process_integrity = lambda: "Medium"
        raised = False
        try:
            launch.assert_publisher_identity(require_high=True)
        except launch.AuthorityUnavailable:
            raised = True
        assert raised, "precondition must fail closed for a non-publisher identity"

        launch.process_integrity = lambda: "High"
        launch.assert_publisher_identity(require_high=True)  # must not raise
    finally:
        launch.process_integrity = original


def test_authority_facade_re_exports_the_public_api() -> None:
    import gnosis.kernel.authority as facade

    for name in (
        "ANCHOR_SCHEMA", "AnchorRecord", "AnchorStore", "AuthorityUnavailable",
        "RunIdentity", "SID_HIGH", "SID_LOW", "SID_MEDIUM", "assert_integrity",
        "label_high_no_write_up", "lowered_primary_token", "process_integrity",
        "publish_anchor", "run_at_integrity", "verify_anchored_bundle",
    ):
        assert hasattr(facade, name), f"facade dropped {name}"
