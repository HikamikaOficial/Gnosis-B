"""Durable reservation and truthful policy identity precede actual dispatch."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from gnosis.kernel.engine import AGENT_RUN_INTERVENTION_POINT, TaskEngine
from gnosis.kernel.policy import InterventionPoint, PolicyEngine, RuleOutcome, Verdict
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.verification import CommandVerifier
from gnosis.runner.capture import ExecutionResult
from gnosis.runner.retry import RetryPolicy


class EditingRunner:
    binary = "explicit-test-worker"
    default_permission_mode = "acceptEdits"
    accepts_run_id = True

    def __init__(self, reserved: list[str]):
        self.reserved = reserved
        self.calls = 0

    def run(self, prompt, cwd, stdout_path, stderr_path, **kwargs):
        assert kwargs["permission_mode"] == self.default_permission_mode
        assert kwargs["run_id"] in self.reserved  # dispatch cannot precede reservation
        self.calls += 1
        (cwd / "result.txt").write_text("actual work")
        stdout_path.write_text("worker output")
        stderr_path.write_text("")
        return ExecutionResult((self.binary,), 0, False, False, 0.1,
                               str(stdout_path), str(stderr_path), "t0", "t1")


def _engine(root: Path, reserved: list[str]):
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    store = RunStore(root / "runs")
    runner = EditingRunner(reserved)
    return TaskEngine(store, runner, retry_policy=RetryPolicy(max_attempts=1)), repo


def _verify():
    return CommandVerifier("file exists", [sys.executable, "-c",
        "from pathlib import Path; assert Path('result.txt').read_text() == 'actual work'"])


def _policy(rule):
    return PolicyEngine([InterventionPoint(AGENT_RUN_INTERVENTION_POINT,
        declared_tools=frozenset({"claude_cli"}), rules=(("test-rule", rule),), requires_intent=True)])


def test_actual_edit_mode_is_gated_and_durable_reference_precedes_child(tmp_path: Path):
    reserved = []
    engine, repo = _engine(tmp_path, reserved)
    seen = []

    def rule(snapshot):
        seen.append(snapshot.intent.value_for("--permission-mode"))
        return RuleOutcome(Verdict.ALLOW, "test:allow")

    def reserve(run_id):
        assert engine.run_store.read_meta(run_id).task_id == "task-1"
        assert not (repo / "result.txt").exists()
        reserved.append(run_id)

    outcome = engine.execute_task("task-1", "create file", "implement", repo,
        verifier=_verify(), policy=_policy(rule), before_attempt=reserve)
    assert seen and set(seen) == {"acceptEdits"}
    assert reserved == outcome.run_ids
    assert engine.cli_runner.calls == 1


def test_a_rule_refusing_edits_cannot_be_bypassed_with_a_plan_snapshot(tmp_path: Path):
    reserved = []
    engine, repo = _engine(tmp_path, reserved)

    def refuse_edits(snapshot):
        return RuleOutcome(Verdict.DENY if snapshot.intent.value_for("--permission-mode")
                           == "acceptEdits" else Verdict.ALLOW, "test:edit-denied")

    engine.execute_task("task-1", "create file", "implement", repo, verifier=_verify(),
                        policy=_policy(refuse_edits), before_attempt=reserved.append)
    assert engine.cli_runner.calls == 0
    assert reserved == []
    assert not (repo / "result.txt").exists()


def test_reservation_storage_failure_aborts_before_child_and_leaves_audit(tmp_path: Path):
    engine, repo = _engine(tmp_path, [])
    created = []

    def failed(run_id):
        created.append(run_id)
        raise OSError("reservation storage failed")

    with pytest.raises(OSError, match="reservation storage failed"):
        engine.execute_task("task-1", "create file", "implement", repo,
                            verifier=_verify(), before_attempt=failed)
    assert engine.cli_runner.calls == 0
    assert len(created) == 1
    assert engine.run_store.read_meta(created[0]).state == "FAILED"
    events = [json.loads(line) for line in engine.run_store.paths_for(created[0]).ledger.read_text().splitlines()]
    assert any(e.get("event_type") == "run.attempt_start_refused" for e in events)


@pytest.mark.parametrize("mode", [None, "bypassPermissions", True, "unknown"])
def test_invalid_declared_mode_never_falls_back_to_a_weaker_snapshot(tmp_path: Path, mode):
    engine, repo = _engine(tmp_path, [])
    engine.cli_runner.default_permission_mode = mode
    with pytest.raises(ValueError, match="unsupported permission"):
        engine.execute_task("task-1", "create file", "implement", repo, verifier=_verify(),
            policy=_policy(lambda snapshot: RuleOutcome(Verdict.ALLOW, "test:allow")))
    assert engine.cli_runner.calls == 0
