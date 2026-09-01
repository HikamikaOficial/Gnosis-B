"""F-33 Stage-2B.2 — canonical operator entry (gnosis.director.cli:main).

Qualifies the CLI's own logic: it delegates to the ONE canonical composition,
rejects trusted-override / governance-bypass flags, maps operator outcomes to
deterministic exit codes, and fails closed. The governed-work + publication
behaviour is qualified separately against the real trust code.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.director import cli


def _brief_file(root: Path) -> Path:
    brief = DirectorBrief(brief_id="B-1", title="demo", mission="do the thing",
                          source=BriefSource.MANUAL)
    path = root / "brief.json"
    path.write_text(json.dumps(brief.to_dict()), encoding="utf-8")
    return path


def _config_file(root: Path, *, complete: bool = True) -> Path:
    body = {
        "deployment": {"code_base": "C:/c", "state_base": "C:/s", "work_base": "C:/w",
                       "worker_username": "Wkr", "trust_root": "C:/trust"},
        "attribution": {"reviewer_id": "reviewer@team", "policy_actor": "agent://dir"},
        "operator": {"director_root": "C:/dir", "repo_path": "C:/repo"},
        "publication": {"trust_state_root": "C:/ts", "evidence_root": "C:/ev",
                        "repository_id": "gnosis", "service_name": "GnosisPub",
                        "pipe_name": r"\\.\pipe\gnosis"},
        "verifier": {"name": "check", "command": ["python", "-c", "raise SystemExit(0)"]},
        "reviewer": {"binary": r"C:\nonexistent\claude.exe"},
    }
    if not complete:
        del body["publication"]
    path = root / "config.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


class _FakeComposition:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome
        self.calls = 0

    def run_brief(self, brief: object) -> object:
        self.calls += 1
        return self._outcome


def _outcome(success: bool, work_status: str, pub_state: str | None):
    from gnosis.director.composition import OperatorOutcome
    return OperatorOutcome(success=success, task_id="T-1", run_id="run-1",
                           work_status=work_status, publication_state=pub_state,
                           reason="x")


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.brief = _brief_file(self.root)
        self.config = _config_file(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, comp: object) -> tuple[int, object]:
        with mock.patch.object(cli, "build_operator_composition",
                               return_value=comp):
            code = cli.main(["run", "--config", str(self.config),
                             "--brief", str(self.brief)])
        return code, comp


class TestForbiddenFlags(unittest.TestCase):
    def test_governance_and_trusted_override_flags_rejected(self) -> None:
        for flag in ("--skip-review", "--no-verify", "--unsafe-direct",
                     "--python=C:/evil.exe", "--worker-sid=S-1-5-x",
                     "--reviewer-id=claude-cli", "--credential-blob=C:/b",
                     "--deployment-digest=abc", "--direct-runner"):
            with self.subTest(flag=flag):
                code = cli.main(["run", "--config", "c", "--brief", "b", flag])
                self.assertEqual(code, cli.EXIT_USAGE)


class TestUsage(unittest.TestCase):
    def test_missing_subcommand_is_usage_error(self) -> None:
        self.assertEqual(cli.main([]), cli.EXIT_USAGE)

    def test_missing_required_args_is_usage_error(self) -> None:
        self.assertEqual(cli.main(["run"]), cli.EXIT_USAGE)


class TestDelegationAndExitCodes(_Base):
    def test_success_when_completed_and_anchored(self) -> None:
        comp = _FakeComposition(_outcome(True, "COMPLETED", "ANCHORED"))
        code, comp = self._run(comp)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(comp.calls, 1)  # delegated to the one composition

    def test_work_failure_exit_code(self) -> None:
        code, _ = self._run(_FakeComposition(_outcome(False, "PARTIAL", None)))
        self.assertEqual(code, cli.EXIT_WORK_FAILED)

    def test_publication_failure_exit_code(self) -> None:
        # work COMPLETED but not ANCHORED -> non-zero publication exit (§20).
        code, _ = self._run(_FakeComposition(_outcome(False, "COMPLETED", None)))
        self.assertEqual(code, cli.EXIT_PUBLICATION)


class TestRealBuildFailsClosed(_Base):
    def test_missing_reviewer_binary_fails_closed(self) -> None:
        # No substitution: the real build_operator_composition constructs the REAL
        # reviewer; a missing reviewer executable → fail closed (reviewer
        # unavailable), NOT an always-pass fallback.
        code = cli.main(["run", "--config", str(self.config),
                         "--brief", str(self.brief)])
        self.assertEqual(code, cli.EXIT_EXECUTION)

    def test_incomplete_trusted_config_is_usage_error(self) -> None:
        bad = _config_file(self.root, complete=False)
        code = cli.main(["run", "--config", str(bad), "--brief", str(self.brief)])
        self.assertEqual(code, cli.EXIT_USAGE)


if __name__ == "__main__":
    unittest.main()
