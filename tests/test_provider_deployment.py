"""Provider selection derives from the runtime tree, never an operator binary."""
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from gnosis.director.composition import (
    CompositionError,
    bind_codex_runtime,
    build_production_composition,
    build_production_deployment,
)
from gnosis.director.execution import ExecutionMode
from gnosis.provision.operator_stack import worker_bootstrap_files
from gnosis.provision.provisioner import Provisioner, ProvisioningError
from gnosis.trust.deployment import observe_runtime_tree
from tests.test_cli import _config_file
from tests.test_codex_package import make_package
from tests.test_composition import _Base
from tests.test_git_package import package as make_git_package
from tests.test_provider_execution import configured
from tests.test_provisioner import _config, _RecordingOps


def runtime(tmp_path: Path):
    python = tmp_path / "python.exe"
    python.write_bytes(b"not executed")
    package = make_package(tmp_path / "providers" / "codex")
    codex = package / "bin" / "codex.exe"
    make_git_package(tmp_path / "toolchains" / "git")
    for source, relative in worker_bootstrap_files(Path(__file__).resolve().parents[1] / "src"):
        destination = tmp_path / "worker-bootstrap" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(Path(source).read_bytes())
    return python, codex, observe_runtime_tree(tmp_path)


def test_provider_path_and_digest_come_from_measured_runtime(tmp_path: Path) -> None:
    python, codex, tree = runtime(tmp_path)
    bound = bind_codex_runtime(python, tree)
    assert bound.executable == codex
    assert bound.trusted_path == (tmp_path, tmp_path / "toolchains" / "git" / "cmd")
    assert bound.bootstrap == tmp_path / "worker-bootstrap" / "gnosis" / "trust" / "bootstrap.py"
    bound.verify()


@pytest.mark.parametrize("change", ["executable", "sidecar", "missing"])
def test_any_runtime_drift_refuses_provider(tmp_path: Path, change: str) -> None:
    python, codex, tree = runtime(tmp_path)
    if change == "executable":
        codex.write_bytes(b"modified")
    elif change == "sidecar":
        (codex.parent / "extra.dll").write_bytes(b"unmeasured")
    else:
        codex.unlink()
    with pytest.raises(CompositionError, match="drifted"):
        bind_codex_runtime(python, tree)


def test_runtime_without_provider_cannot_enable_it(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.write_bytes(b"fake")
    with pytest.raises(CompositionError, match="exactly one"):
        bind_codex_runtime(python, observe_runtime_tree(tmp_path))


def test_provider_requires_publishers_expected_identity() -> None:
    config = Mock(execution_mode=ExecutionMode.PROVIDER_BACKED)
    config.deployment.expected_deployment_digest = "expected"
    publication = Mock()
    publication.deployment.digest.return_value = "different"
    with patch("gnosis.director.composition.build_production_composition") as build:
        with pytest.raises(CompositionError, match="trusted expectation"):
            build_production_deployment(config, publication)
        build.assert_not_called()


def test_provider_tree_must_match_publication_tree(tmp_path: Path) -> None:
    _, _, tree = runtime(tmp_path)
    config = Mock(execution_mode=ExecutionMode.PROVIDER_BACKED,
                  provider_runtime_tree=tree)
    config.deployment.expected_deployment_digest = "expected"
    publication = Mock()
    publication.deployment.digest.return_value = "expected"
    publication.deployment.runtime_tree = replace(tree, files=tree.files[:-1])
    with patch("gnosis.director.composition.build_production_composition") as build:
        with pytest.raises(CompositionError, match="same runtime tree"):
            build_production_deployment(config, publication)
        build.assert_not_called()


def test_provisioning_places_complete_native_bundle_inside_runtime(tmp_path: Path) -> None:
    ops = _RecordingOps()
    source = str(make_package(tmp_path / "codex-bundle"))
    provisioner = Provisioner(_config(), ops, r"C:\source\python", [], [], [],
                              codex_runtime_src=source)
    provisioner._deploy_code()
    target = str(Path(provisioner.config.layout.runtime_root) / "providers" / "codex")
    assert ("copytree", (source, target)) in ops.calls


def test_provisioning_refuses_bundle_without_native_executable() -> None:
    provisioner = Provisioner(_config(), _RecordingOps(), "runtime", [], [], [],
                              codex_runtime_src="missing")
    with pytest.raises(ProvisioningError, match="invalid native Codex package"):
        provisioner._deploy_code()


@pytest.mark.parametrize("entry", ["install", "_deploy_code"])
def test_invalid_provider_input_causes_no_provisioning_mutation(tmp_path: Path, entry: str) -> None:
    package = make_package(tmp_path / "package")
    (package / "codex-resources" / "codex-windows-sandbox-setup.exe").write_bytes(b"")
    ops = _RecordingOps()
    provisioner = Provisioner(_config(), ops, "runtime", [], [], [],
                              codex_runtime_src=str(package))
    with pytest.raises(ProvisioningError):
        if entry == "install":
            provisioner.install("test-only-password")
        else:
            provisioner._deploy_code()
    assert ops.calls == []


class TestProviderComposition(_Base):
    def test_claude_review_uses_measured_binary_and_worker(self) -> None:
        from gnosis.director.worker_review import WorkerClaudeReviewer
        from gnosis.runner.claude_cli_runner import ClaudeCodeCLIRunner

        runtime_dir = self.root / "runtime"
        runtime_dir.mkdir()
        python, _, _ = runtime(runtime_dir)
        claude = runtime_dir / "providers/claude/claude.exe"
        claude.parent.mkdir()
        claude.write_bytes(b"measured test executable")
        config = replace(self._config(review_runner=ClaudeCodeCLIRunner(str(claude))),
            execution_mode=ExecutionMode.PROVIDER_BACKED,
            provider_runtime_tree=observe_runtime_tree(runtime_dir))
        with patch("gnosis.director.composition._bind_deployment_runtime", return_value=python):
            pipeline = build_production_composition(config)
        self.assertIsInstance(pipeline.review_runner, WorkerClaudeReviewer)
        self.assertIs(pipeline.review_runner.launcher, pipeline.scheduler.engine.cli_runner._port._launcher)

    def test_unmeasured_claude_review_is_refused(self) -> None:
        from gnosis.runner.claude_cli_runner import ClaudeCodeCLIRunner

        runtime_dir = self.root / "runtime"
        runtime_dir.mkdir()
        python, _, tree = runtime(runtime_dir)
        config = replace(self._config(review_runner=ClaudeCodeCLIRunner(str(self.root / "claude.exe"))),
            execution_mode=ExecutionMode.PROVIDER_BACKED, provider_runtime_tree=tree)
        with patch("gnosis.director.composition._bind_deployment_runtime", return_value=python), \
                self.assertRaisesRegex(CompositionError, "measured provider runtime"):
            build_production_composition(config)

    def test_canonical_factory_reaches_dedicated_worker_provider(self) -> None:
        runtime_dir = self.root / "runtime"
        runtime_dir.mkdir()
        python, codex, tree = runtime(runtime_dir)
        fake_port, _, specs, _, _ = configured(self.root)
        config = replace(self._config(), execution_mode=ExecutionMode.PROVIDER_BACKED,
                         provider_runtime_tree=tree)
        with patch("gnosis.director.composition._bind_deployment_runtime", return_value=python), \
                patch("gnosis.director.composition.TrustedWindowsWorkerLauncher",
                      return_value=fake_port._launcher):
            pipeline = build_production_composition(config)
        runner = pipeline.scheduler.engine.cli_runner
        result = runner.run("implement", self.root, self.root / "out", self.root / "err")
        self.assertTrue(result.succeeded)
        self.assertEqual(specs[1].executable, str(codex))
        self.assertEqual(specs[1].argv[-1], "implement")


@pytest.mark.parametrize("extra", [False, True])
def test_cli_reads_only_closed_provider_selection(tmp_path: Path, extra: bool) -> None:
    from gnosis.director.cli import OperatorError, build_operator_composition

    path = _config_file(tmp_path)
    raw = json.loads(path.read_text())
    raw["execution"] = {"mode": "provider_backed", "provider": "codex"}
    if extra:
        raw["execution"]["binary"] = "C:/arbitrary.exe"
    path.write_text(json.dumps(raw))
    with patch("gnosis.director.cli.build_reviewer"), \
            patch("gnosis.director.composition.trusted_deployment_from_layout"), \
            patch("gnosis.trust.deployment.observe_deployment") as observe, \
            patch("gnosis.director.composition.build_production_deployment") as build:
        if extra:
            with pytest.raises(OperatorError, match="unsupported"):
                build_operator_composition(path)
            build.assert_not_called()
        else:
            build_operator_composition(path)
            config, publication = build.call_args.args
            assert config.execution_mode is ExecutionMode.PROVIDER_BACKED
            assert config.provider_runtime_tree is observe.return_value.runtime_tree
            assert publication.deployment is observe.return_value
