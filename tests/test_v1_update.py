import hashlib
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stage2cb import OrchestrationError
from v1_update import activate_update, stage_update

from gnosis.provision.gnosis_deployment import composed_record_path
from tests.test_stage2cb_backend import F17D, FakeObserved
from tests.test_v1_installation import install, prepared


def setup_update(tmp_path):
    config, ops = prepared(tmp_path)
    install(config, ops)
    candidate = replace(config, layout=replace(config.layout, release_id="v1-next"))
    claude = tmp_path / "claude.exe"
    claude.write_bytes(b"native Claude test fixture")
    digest = hashlib.sha256(claude.read_bytes()).hexdigest()
    ops.log.clear()
    return config, candidate, ops, claude, digest


def stage(config, candidate, ops, claude, digest):
    return stage_update(config, candidate, ops,
        source_root=Path(__file__).resolve().parents[1] / "src",
        claude_binary=claude, claude_digest=digest,
        observe_current=lambda: F17D, observe_fn=lambda _: FakeObserved(F17D))


def test_staging_preserves_active_record_service_and_credentials(tmp_path):
    config, candidate, ops, claude, digest = setup_update(tmp_path)
    paths = [Path(config.layout.config_path), Path(config.layout.secrets_blob),
             composed_record_path(config.layout), Path(config.layout.deployment_json)]
    original = {path: path.read_bytes() for path in paths}
    staged = stage(config, candidate, ops, claude, digest)
    assert json.loads(staged.journal.read_text())["status"] == "staged-not-active"
    assert all(path.read_bytes() == content for path, content in original.items())
    assert (Path(candidate.layout.runtime_root) / "providers/claude/claude.exe").read_bytes() == claude.read_bytes()
    assert not ops.ops_of("create_worker")
    assert not ops.ops_of("protect_secret")
    assert not ops.ops_of("service_start")
    assert not ops.ops_of("service_stop")
    assert not any(call[0][:2] == ("sc.exe", "config") for call in ops.ops_of("run"))
    with pytest.raises(OrchestrationError, match="already exists"):
        stage(config, candidate, ops, claude, digest)


@pytest.mark.parametrize("change", ["same-release", "account", "escape", "source-drift"])
def test_invalid_update_rejected_before_deployment_mutation(tmp_path, change):
    config, candidate, ops, claude, digest = setup_update(tmp_path)
    if change == "same-release":
        candidate = replace(candidate, layout=config.layout)
    elif change == "account":
        candidate = replace(candidate, worker_username="different")
    elif change == "escape":
        candidate = replace(candidate, layout=replace(candidate.layout, release_id="../escape"))
    else:
        claude.write_bytes(b"changed")
    with pytest.raises(OrchestrationError):
        stage(config, candidate, ops, claude, digest)
    assert not ops.ops_of("copyfile")
    assert not ops.ops_of("copytree")


def test_partial_staging_keeps_old_install_and_records_failure(tmp_path, monkeypatch):
    config, candidate, ops, claude, digest = setup_update(tmp_path)
    previous = composed_record_path(config.layout).read_bytes()
    def fail(*args, **kwargs):
        raise OSError("injected staging failure")
    monkeypatch.setattr("v1_update.deploy_operator_stack", fail)
    with pytest.raises(OSError, match="injected"):
        stage(config, candidate, ops, claude, digest)
    journal = Path(config.residue_record_dir()) / "update-v1-next.json"
    assert json.loads(journal.read_text())["status"] == "staging-failed-retained"
    assert composed_record_path(config.layout).read_bytes() == previous
    assert not ops.ops_of("service_stop")
    assert not ops.ops_of("rmtree")


@pytest.mark.parametrize("fail_start", [False, True])
def test_activation_or_rollback_retains_original_state(tmp_path, monkeypatch, fail_start):
    config, candidate, ops, claude, digest = setup_update(tmp_path)
    staged = stage(config, candidate, ops, claude, digest)
    path = Path(config.residue_record_dir()) / "installation.json"
    path.write_text(json.dumps(asdict(config)), encoding="utf-8")
    snapshots = [path, Path(config.layout.config_path), composed_record_path(config.layout),
                 Path(config.layout.deployment_json), Path(config.layout.secrets_blob)]
    before = {p: p.read_bytes() for p in snapshots}
    active = {"new": False, "starts": 0}
    run = ops.run

    def recording_run(argv):
        if argv[:2] == ["sc.exe", "config"]:
            active["new"] = candidate.layout.release_id in argv[-1]
        return run(argv)

    def start():
        active["starts"] += 1
        if fail_start and active["starts"] == 1:
            raise RuntimeError("new service readiness failed")

    monkeypatch.setattr(ops, "run", recording_run)
    arguments = {"configuration_path": path, "observe_current": lambda: F17D,
        "observe_candidate": lambda: "a" * 64, "stop_service": lambda: None, "start_service": start,
        "observe_fn": lambda _: FakeObserved("a" * 64 if active["new"] else F17D)}
    if fail_start:
        with pytest.raises(RuntimeError, match="readiness failed"):
            activate_update(config, candidate, ops, **arguments)
        assert not active["new"]
        assert all(p.read_bytes() == content for p, content in before.items())
        assert json.loads(staged.journal.read_text())["status"] == "rolled-back"
    else:
        activate_update(config, candidate, ops, **arguments)
        assert active["new"]
        assert json.loads(path.read_text())["layout"]["release_id"] == "v1-next"
        assert json.loads(staged.journal.read_text())["status"] == "active"
        assert Path(config.layout.secrets_blob).read_bytes() == before[Path(config.layout.secrets_blob)]


def test_staged_drift_refused_before_stopping_service(tmp_path):
    config, candidate, ops, claude, digest = setup_update(tmp_path)
    stage(config, candidate, ops, claude, digest)
    stops = []
    with pytest.raises(OrchestrationError, match="staged release changed"):
        activate_update(config, candidate, ops,
            configuration_path=Path(config.residue_record_dir()) / "installation.json",
            observe_current=lambda: F17D, observe_candidate=lambda: "a" * 64,
            stop_service=lambda: stops.append(True), start_service=lambda: None,
            observe_fn=lambda _: FakeObserved("b" * 64))
    assert stops == []
