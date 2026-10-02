from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trust_fixtures as tf
from test_pipeline import _permissive

from gnosis.kernel.budget import Budget, BudgetLedger
from gnosis.kernel.run_store import RunStore
from gnosis.runner.capture import ExecutionResult
from gnosis.runner.gated_runner import CredentialHeld, GatedAgentRunner
from gnosis.runner.recorded import RecordedAgentRunner


class _Runner:
    accepts_run_id = True
    binary = "trusted-test-worker"

    def __init__(self):
        self.calls = []
        self.error = None
        self.output = "done"
        self.exit_code = 0

    def run(self, prompt, cwd, stdout_path, stderr_path, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        stdout_path.write_text(self.output)
        stderr_path.write_text(self.output if self.exit_code else "")
        kwargs["heartbeat_fn"](42)
        return ExecutionResult((self.binary,), self.exit_code, False, False, 0.1,
                                str(stdout_path), str(stderr_path), "start", "end")


def _recorder(tmp_path: Path, on_started=None, holds=None, on_launch=None):
    repo = tf.git_repo(tmp_path / "repo")
    runner = _Runner()
    gate = GatedAgentRunner(runner, _permissive(), repo, "convergence_fix", "T1",
                            policy_actor="agent://director", holds=holds,
                            budget=BudgetLedger(Budget(max_agent_launches=3)), on_launch=on_launch)
    store = RunStore(tmp_path / "runs")
    return repo, runner, gate, RecordedAgentRunner(gate, store, task_id="T1",
                 stage="convergence_fix", on_started=on_started)


def _run(recorder, repo):
    return recorder.run("fixing defects", repo, repo.parent / "unused.out",
                         repo.parent / "unused.err")


def test_distinct_runs_preserve_raw_result_and_parent_reference_before_launch(tmp_path: Path):
    seen = []
    repo, runner, _gate, recorder = _recorder(tmp_path, on_started=seen.append)
    first = _run(recorder, repo)
    runner.output = "second"
    second = _run(recorder, repo)
    assert len(set(seen)) == 2
    assert [call["run_id"] for call in runner.calls] == seen
    assert Path(first.stdout_path).read_text() == "done"
    assert Path(second.stdout_path).read_text() == "second"
    for run_id in seen:
        paths = recorder.store.paths_for(run_id)
        assert json.loads(paths.result.read_text())["succeeded"] is True
        assert recorder.store.read_heartbeat(run_id)
        assert recorder.store.read_meta(run_id).state == "SUCCEEDED"
        events = [e.event_type for e in recorder.store.ledger_for(run_id).read_all()]
        assert "policy.decision" in events and "run.attempt_finished" in events
    assert not (repo.parent / "unused.out").exists()


def test_failed_parent_attachment_never_reuses_previous_result_or_launches(tmp_path: Path):
    repo, runner, _gate, recorder = _recorder(tmp_path)
    _run(recorder, repo)
    recorder.on_started = Mock(side_effect=RuntimeError("parent write failed"))
    with pytest.raises(RuntimeError, match="parent write failed"):
        _run(recorder, repo)
    assert len(runner.calls) == 1
    last = recorder.attempts[-1]
    assert last.result is None and last.error_type == "RuntimeError"
    assert not recorder.store.paths_for(last.run_id).result.exists()


def test_infrastructure_exception_keeps_typed_failure_and_prior_work(tmp_path: Path):
    repo, runner, _gate, recorder = _recorder(tmp_path)
    runner.error = OSError("worker unavailable")
    with pytest.raises(OSError):
        _run(recorder, repo)
    last = recorder.attempts[-1]
    assert last.error_type == "OSError" and last.result is None
    assert json.loads((recorder.store.paths_for(last.run_id).root / "attempt.json").read_text())[
        "error_type"] == "OSError"
    assert (repo / "code.py").read_text() == "x = 1\n"


def test_rate_limit_retains_raw_output_and_is_a_park(tmp_path: Path):
    holds = Mock()
    holds.admits.return_value = True
    repo, runner, _gate, recorder = _recorder(tmp_path, holds=holds)
    runner.output = "rate limit exceeded; too many requests; HTTP 429"
    runner.exit_code = 1
    with pytest.raises(CredentialHeld):
        _run(recorder, repo)
    last = recorder.attempts[-1]
    assert last.state == "RATE_LIMITED"
    assert last.result is not None
    assert "429" in Path(last.result.stdout_path).read_text()
    assert recorder.store.paths_for(last.run_id).result.is_file()
    assert holds.observe.called


def test_spend_persistence_failure_prevents_launch(tmp_path: Path):
    persist = Mock(side_effect=OSError("budget cannot be persisted"))
    repo, runner, gate, recorder = _recorder(tmp_path, on_launch=persist)
    with pytest.raises(OSError, match="budget cannot be persisted"):
        _run(recorder, repo)
    assert not runner.calls
    assert gate.budget.launches == 1
