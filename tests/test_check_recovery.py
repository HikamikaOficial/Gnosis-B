from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gnosis.kernel.check_execution import CheckExecutionUnavailable
from gnosis.kernel.file_lock import FileLock
from gnosis.trust.check_recovery import ATTEMPT_SCHEMA, recover_check_outputs
from gnosis.trust.launch_spec import LaunchSpec


def attempt(root):
    run_id = "check-" + "a" * 32
    stage, retained = root / "worker" / run_id, root / "protected" / run_id
    stage.mkdir(parents=True)
    retained.mkdir(parents=True)
    spec = LaunchSpec(run_id, sys.executable, (sys.executable, "-c", "pass"), str(root),
                      str(stage / "stdout"), str(stage / "stderr"), run_id=run_id)
    (retained / "intent.json").write_text(json.dumps({
        "schema": ATTEMPT_SCHEMA, "spec": spec.to_dict(), "timeout_s": 3}))
    (stage / "stdout").write_bytes(b"partial stdout")
    (stage / "stderr").write_bytes(b"partial stderr")
    return run_id, stage, retained


def recover(root):
    return recover_check_outputs(evidence_root=root / "protected", output_root=root / "worker",
                                 runtime=Path(sys.executable))


def test_recovery_is_idempotent_and_cannot_mint_success(tmp_path):
    run_id, stage, retained = attempt(tmp_path)
    assert recover(tmp_path) == (run_id,)
    assert (retained / "stdout").read_bytes() == b"partial stdout"
    (stage / "stdout").write_bytes(b"forged replacement")
    assert recover(tmp_path) == ()
    assert (retained / "stdout").read_bytes() == b"partial stdout"
    assert {p.name for p in retained.iterdir()} == {"stdout", "stderr", "intent.json", "attempt.lock"}


def test_active_attempt_is_not_recovered(tmp_path):
    _, _, retained = attempt(tmp_path)
    with FileLock(retained / "attempt.lock"):
        assert recover(tmp_path) == ()
        assert not (retained / "stdout").exists()
    assert len(recover(tmp_path)) == 1


def test_missing_stream_is_not_a_failed_verdict(tmp_path):
    run_id, stage, retained = attempt(tmp_path)
    (stage / "stderr").unlink()
    assert recover(tmp_path) == (run_id,)
    assert not (retained / "stderr").exists()


@pytest.mark.parametrize("field", ["stdout_path", "run_id", "executable"])
def test_intent_cannot_select_other_files(tmp_path, field):
    _, _, retained = attempt(tmp_path)
    path = retained / "intent.json"
    data = json.loads(path.read_text())
    data["spec"][field] = ("check-" + "b" * 32 if field == "run_id"
                           else str(tmp_path / "outside"))
    path.write_text(json.dumps(data))
    with pytest.raises(CheckExecutionUnavailable):
        recover(tmp_path)
    assert not (retained / "stdout").exists()


def test_untrusted_hardlink_is_refused(tmp_path):
    _, stage, retained = attempt(tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(b"must not copy")
    (stage / "stdout").unlink()
    os.link(outside, stage / "stdout")
    with pytest.raises(CheckExecutionUnavailable):
        recover(tmp_path)
    assert not (retained / "stdout").exists()


def test_duplicate_intent_fields_are_refused(tmp_path):
    _, _, retained = attempt(tmp_path)
    path = retained / "intent.json"
    path.write_text('{"schema":"unrecognized",' + path.read_text()[1:])
    with pytest.raises(CheckExecutionUnavailable):
        recover(tmp_path)
    assert not (retained / "stdout").exists()


def test_hard_process_exit_leaves_recoverable_attributed_output(tmp_path):
    code = '''
import os,sys
from pathlib import Path
from gnosis.trust.check_executor import WorkerCheckExecutor
root=Path(sys.argv[1])
class Launcher:
    def launch(self,spec):
        Path(spec.stdout_path).write_bytes(b"before kernel kill")
        Path(spec.stderr_path).write_bytes(b"")
        os._exit(77)
WorkerCheckExecutor(launcher=Launcher(),runtime=Path(sys.executable),
    output_root=root/"worker",evidence_root=root/"protected",
    guard=lambda:None,is_cancelled=lambda:False).execute(
        [sys.executable,"-c","pass"],cwd=root,timeout_s=3)
'''
    source = Path(__file__).resolve().parents[1] / "src"
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], timeout=15,
                            env={**os.environ, "PYTHONPATH": str(source)}, check=False)
    assert result.returncode == 77
    recovered = recover(tmp_path)
    assert len(recovered) == 1
    retained = tmp_path / "protected" / recovered[0]
    assert (retained / "stdout").read_bytes() == b"before kernel kill"
    assert not (retained / "result.json").exists()
    assert recover(tmp_path) == ()
