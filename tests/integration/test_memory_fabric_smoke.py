"""Memory Fabric cross-session smoke test (Phase -1 gate, re-runnable).

Exercises the two primary memory engines through their real CLIs, each
invocation a separate OS process (the honest "fresh session" boundary a
CLI can offer):

- zmem (governance plane): remember -> fresh-process search -> revoke ->
  fresh-process exclusion. Uses standalone ``--db`` mode so no workspace
  is registered in the user's ``~/.zmem``.
- m3 (recall plane): write -> fresh-process search. Uses env-pinned state
  roots (M3_MEMORY_ROOT/M3_ENGINE_ROOT/M3_CONFIG_ROOT) so the user's real
  ``~/.m3`` store is never touched. This is also the integration path that
  works: the ``--database`` flag is known-broken upstream (migration state
  is global, so a fresh file never gets the schema — verified 2026-08-19
  on 2026.8.19.16), while env-pinned roots provision correctly.

Skips cleanly when an engine is not installed, so the suite stays green
on machines without the fabric while still guarding it here.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ZMEM = shutil.which("zmem")
M3 = shutil.which("m3")

# Children must not re-exec (m3's UTF-8 relaunch loses the tool venv under
# uv shims on Windows — verified 2026-08-19); PYTHONUTF8=1 short-circuits it.
CHILD_ENV_BASE = {**os.environ, "PYTHONUTF8": "1"}


def _run(argv: list[str], env: dict[str, str], timeout: float = 300.0) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=timeout)


class _TempDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        # Windows: just-exited children may hold DB handles for a moment.
        for attempt in range(10):
            try:
                self.tmp.cleanup()
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.2)


@unittest.skipIf(ZMEM is None, "zmem CLI not installed")
class TestZmemGovernanceSmoke(_TempDirTestCase):
    def test_remember_cross_process_search_and_revoke(self) -> None:
        db = str(self.dir / "memory.sqlite")
        fact = "Smoke fact: the fabric continuity token is AMBER-CASTLE-41."

        p = _run([ZMEM, "--db", db, "remember", fact, "--type", "semantic",
                  "--source", "system", "--label", "fabric-smoke"], CHILD_ENV_BASE)
        self.assertEqual(p.returncode, 0, p.stderr)
        record = json.loads(p.stdout)
        self.assertEqual(record["status"], "active")
        mem_id = record["id"]

        # Fresh process: the memory must survive the session boundary.
        p = _run([ZMEM, "--db", db, "search", "continuity token"], CHILD_ENV_BASE)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("AMBER-CASTLE-41", p.stdout)

        p = _run([ZMEM, "--db", db, "revoke", mem_id, "--reason", "smoke cleanup"],
                 CHILD_ENV_BASE)
        self.assertEqual(p.returncode, 0, p.stderr)

        # Fresh process again: a revoked memory must not come back.
        p = _run([ZMEM, "--db", db, "search", "continuity token"], CHILD_ENV_BASE)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("AMBER-CASTLE-41", p.stdout)

    def test_agent_proposal_is_quarantined_not_active(self) -> None:
        db = str(self.dir / "memory.sqlite")
        claim = "Smoke claim: the moon base holds the backup."

        p = _run([ZMEM, "--db", db, "propose", claim, "--type", "semantic",
                  "--source", "agent"], CHILD_ENV_BASE)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["status"], "quarantined")

        # Default search (fresh process) must not surface quarantined content.
        p = _run([ZMEM, "--db", db, "search", "moon base"], CHILD_ENV_BASE)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("moon base", p.stdout)


@unittest.skipIf(M3 is None, "m3 CLI not installed")
class TestM3RecallSmoke(_TempDirTestCase):
    def test_write_then_cross_process_search_on_pinned_root(self) -> None:
        root = self.dir / "m3root"
        env = {
            **CHILD_ENV_BASE,
            "M3_MEMORY_ROOT": str(root),
            "M3_ENGINE_ROOT": str(root / "engine"),
            "M3_CONFIG_ROOT": str(root / "config"),
        }
        fact = "Smoke fact: the fabric recall token is COBALT-HARBOR-77."

        p = _run([M3, "memory", "memory_write", "--type", "fact",
                  "--content", fact, "--no-embed", "--yes"], env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Created:", p.stdout)

        # Fresh process against the same pinned root.
        p = _run([M3, "memory", "memory_search", "--query", "COBALT-HARBOR-77"], env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("COBALT-HARBOR-77", p.stdout)

        # The pinned root, and only the pinned root, was provisioned.
        self.assertTrue((root / "engine" / "agent_memory.db").exists())


if __name__ == "__main__":
    unittest.main()
