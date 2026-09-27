import shutil
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest
from stage2cb import OrchestrationError, ResidueStore
from v1_installation import install_persistent, verify_persistent

from tests.test_codex_package import make_package
from tests.test_git_package import package as make_git_package
from tests.test_stage2cb_backend import F17D, DryOperations, FakeObserved, _config


def prepared(tmp_path, **options):
    native = make_package(tmp_path / "native")
    git = make_git_package(tmp_path / "git")
    config = replace(_config(tmp_path), codex_runtime_src=str(native), git_runtime_src=str(git))

    class FilesystemProviderOps(DryOperations):
        def copytree(self, src, dst):
            if Path(src) in (native, git):
                self._rec("copytree", src, dst)
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                super().copytree(src, dst)

    return config, FilesystemProviderOps(**options)


def install(config, ops):
    return install_persistent(config, ops, expected_head="test-head", actual_head="test-head",
        f17_stable=True, source_root=Path(__file__).resolve().parents[1] / "src",
        observe_effective=lambda: F17D, observe_fn=lambda _: FakeObserved(F17D))


def test_success_retains_installation_and_refuses_reinstall(tmp_path):
    config, ops = prepared(tmp_path)
    result = install(config, ops)
    assert result.operator_entry.is_file()
    assert not ops.account_absent(config.worker_username)
    assert not ops.service_absent(config.service_name)
    record = ResidueStore(config.residue_record_path(), config.run_id).load()
    assert record is not None and all(resource.acquired for resource in record.resources)
    assert not ops.ops_of("delete_worker")
    assert not ops.ops_of("rmtree")
    with pytest.raises(OrchestrationError, match="preflight refused"):
        install(config, ops)


def test_readiness_failure_retains_recovery_record_without_claiming_success(tmp_path):
    config, ops = prepared(tmp_path, pipe_not_ready=True)
    with pytest.raises(OrchestrationError, match="not ready"):
        install(config, ops)
    record = ResidueStore(config.residue_record_path(), config.run_id).load()
    assert record is not None and record.status == "active"
    assert all(resource.acquired for resource in record.resources)
    assert not ops.ops_of("delete_worker")


def test_non_elevated_preflight_has_no_install_mutations(tmp_path):
    config, ops = prepared(tmp_path, elevated=False)
    with pytest.raises(OrchestrationError, match="not elevated"):
        install(config, ops)
    assert not config.residue_record_path().exists()
    assert not ops.ops_of("create_worker")
    assert not ops.ops_of("copytree")


@pytest.mark.parametrize("change", ["none", "application", "identity", "ownership"])
def test_fresh_verification_after_restart_refuses_drift(tmp_path, change):
    config, ops = prepared(tmp_path)
    installed = install(config, ops)
    if change == "application":
        installed.operator_entry.write_text("print('changed')")
    elif change == "ownership":
        store = ResidueStore(config.residue_record_path(), config.run_id)
        store.mark_cleaned({config.worker_username})
    digest = "a" * 64 if change == "identity" else F17D
    if change == "none":
        reloaded = verify_persistent(config, observe_effective=lambda: digest)
        assert reloaded == installed
    else:
        from gnosis.provision.gnosis_deployment import GnosisDeploymentError
        with pytest.raises((OrchestrationError, GnosisDeploymentError)):
            verify_persistent(config, observe_effective=lambda: digest)
