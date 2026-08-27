"""GNOSIS Trust Plane — the minimal TCB whose compromise would defeat F-17.

This package holds only the authoritative anchor and launch/identity
primitives (see `anchor.py`, `launch.py`). It must NOT import worker-plane
code (engine, planner, scheduler, policy, runner, the Claude/Codex adapters,
plugins, or development tooling); `tests/test_trust_boundary.py` enforces that
import boundary so the Trust Plane cannot start small and grow silently.
"""
