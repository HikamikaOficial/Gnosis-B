"""F-33 Stage-2B.1 — canonical production composition factory qualification.

Proves `build_production_composition` assembles the ONE strong-governance graph
(GovernedPipeline whose implementer is the injected TrustedExecutionRunner over
the F-17 launcher, bound to a deployment-derived runtime), and fails closed on
every invalid input (ADR-0032 §20). Uses the real .venv interpreter as the
deployment runtime so the `trust.deployment.observe_runtime` binding is exercised;
no Worker is launched here (that is Stage-2A / OS-real).
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from gnosis.director import composition as comp
from gnosis.director.composition import (
    AttributionInputs,
    CompositionError,
    OperatorInputs,
    ProductionCompositionConfig,
    TrustedDeploymentInputs,
    build_production_composition,
    trusted_deployment_from_layout,
)
from gnosis.director.execution import ExecutionMode
from gnosis.director.pipeline import GovernedPipeline
from gnosis.director.trusted_runner import TrustedExecutionRunner
from gnosis.kernel.engine import AGENT_RUN_INTERVENTION_POINT
from gnosis.kernel.policy import InterventionPoint, PolicyEngine, RuleOutcome, Verdict
from gnosis.kernel.verification import CommandVerifier
from gnosis.trust.deployment import observe_runtime
from gnosis.trust.worker_launcher import TrustedWindowsWorkerLauncher, WorkerAccount


def _permissive() -> PolicyEngine:
    return PolicyEngine([InterventionPoint(
        name=AGENT_RUN_INTERVENTION_POINT,
        declared_tools=frozenset({"claude_cli"}),
        rules=(("rule", lambda s: RuleOutcome(Verdict.ALLOW, "ok:permitted")),),
        requires_intent=True)])


class _ReviewAgent:
    @property
    def binary(self) -> str:
        return "claude-review"

    def run(self, *a: Any, **k: Any) -> Any:  # pragma: no cover
        raise AssertionError("review runner not invoked in composition tests")


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, capture_output=True, check=False)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _deployment(self, *, runtime: Path | None = None,
                    blob_exists: bool = True) -> TrustedDeploymentInputs:
        blob = self.root / "worker.dpapi"
        if blob_exists:
            blob.write_bytes(b"dpapi-blob-bytes")
        launch = self.root / "launch"
        return TrustedDeploymentInputs(
            runtime_executable=runtime if runtime is not None else Path(sys.executable),
            worker_account=WorkerAccount("Wkr", ".", "S-1-5-21-x-1001", "Medium"),
            credential_blob_path=blob, launch_root=launch)

    def _config(self, *, deployment: TrustedDeploymentInputs | None = None,
                attribution: AttributionInputs | None = None,
                verifier: Any = "default", review_runner: Any = "default",
                execution_mode: ExecutionMode = ExecutionMode.DETERMINISTIC,
                repo: Path | None = None) -> ProductionCompositionConfig:
        return ProductionCompositionConfig(
            deployment=deployment or self._deployment(),
            attribution=attribution or AttributionInputs(
                reviewer_id="reviewer@team-b", policy_actor="agent://director-prod"),
            operator=OperatorInputs(director_root=self.root / "director",
                                    repo_path=repo or self.repo),
            verifier=(CommandVerifier("check", [sys.executable, "-c", "raise SystemExit(0)"])
                      if verifier == "default" else verifier),
            review_runner=_ReviewAgent() if review_runner == "default" else review_runner,
            policy=_permissive(),
            execution_mode=execution_mode)


class TestPositiveComposition(_Base):
    def test_builds_canonical_governed_pipeline(self) -> None:
        pipeline = build_production_composition(self._config())
        self.assertIsInstance(pipeline, GovernedPipeline)
        # Implementer is the trusted runner, injected explicitly (not the legacy default).
        runner = pipeline.scheduler.engine.cli_runner
        self.assertIsInstance(runner, TrustedExecutionRunner)
        # Bound to the deployment-derived, byte-measured interpreter.
        expected = Path(observe_runtime(Path(sys.executable)).executable_path)
        self.assertEqual(runner._port._python, expected)
        # The launcher is the qualified F-17 launcher.
        self.assertIsInstance(runner._port._launcher, TrustedWindowsWorkerLauncher)
        # Attribution flowed to the pipeline.
        self.assertEqual(pipeline.reviewer_id, "reviewer@team-b")
        self.assertEqual(pipeline.policy_actor, "agent://director-prod")

    def test_no_legacy_direct_runner_default(self) -> None:
        pipeline = build_production_composition(self._config())
        runner = pipeline.scheduler.engine.cli_runner
        self.assertIsInstance(runner, TrustedExecutionRunner)
        self.assertNotIn("ClaudeCodeCLIRunner", type(runner).__name__)


class TestFailClosedMatrix(_Base):
    def test_c1_invalid_deployment_runtime(self) -> None:
        # nonexistent absolute interpreter -> observe_runtime fails -> fail closed
        bad = self._deployment(runtime=self.root / "no-such-python.exe")
        with self.assertRaises(CompositionError):
            build_production_composition(self._config(deployment=bad))

    def test_c1_relative_runtime_rejected(self) -> None:
        rel = self._deployment(runtime=Path("python.exe"))
        with self.assertRaises(CompositionError):
            build_production_composition(self._config(deployment=rel))

    def test_c2_missing_worker_credential_blob(self) -> None:
        dep = self._deployment(blob_exists=False)
        with self.assertRaises(CompositionError):
            build_production_composition(self._config(deployment=dep))

    def test_c3_missing_verifier(self) -> None:
        with self.assertRaises(CompositionError):
            build_production_composition(self._config(verifier=None))

    def test_c4_same_implementer_and_reviewer(self) -> None:
        # Force the built implementer to be a known sentinel and pass it as the
        # reviewer: the factory must refuse at construction (§15), not later.
        sentinel = object()
        cfg = self._config(review_runner=sentinel)
        with mock.patch.object(comp, "TrustedExecutionRunner",
                               lambda *a, **k: sentinel), self.assertRaises(CompositionError):
            build_production_composition(cfg)

    def test_c5_empty_reviewer_id(self) -> None:
        with self.assertRaises(CompositionError):
            build_production_composition(self._config(
                attribution=AttributionInputs("  ", "agent://director-prod")))

    def test_c6_empty_policy_actor(self) -> None:
        with self.assertRaises(CompositionError):
            build_production_composition(self._config(
                attribution=AttributionInputs("reviewer@team", "")))

    def test_c7_placeholder_reviewer_id(self) -> None:
        with self.assertRaises(CompositionError):
            build_production_composition(self._config(
                attribution=AttributionInputs("claude-cli", "agent://director-prod")))

    def test_c8_placeholder_policy_actor(self) -> None:
        with self.assertRaises(CompositionError):
            build_production_composition(self._config(
                attribution=AttributionInputs("reviewer@team", "agent://unattributed")))

    def test_c9_unsupported_execution_mode(self) -> None:
        with self.assertRaises(CompositionError):
            build_production_composition(self._config(
                execution_mode=ExecutionMode.PROVIDER_BACKED))

    def test_c10_invalid_repo_path(self) -> None:
        with self.assertRaises(CompositionError):
            build_production_composition(self._config(repo=self.root / "no-repo"))


class TestDirectorOrchestratorNonProduction(_Base):
    def test_factory_returns_governed_pipeline_not_orchestrator(self) -> None:
        pipeline = build_production_composition(self._config())
        self.assertEqual(type(pipeline).__name__, "GovernedPipeline")

    def test_source_does_not_reference_directororchestrator(self) -> None:
        # Guard against ANY code reference (import alias, Name, or attribute) —
        # not the docstring, which may legitimately explain the non-production
        # relationship.
        tree = ast.parse(Path(comp.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(
                    "DirectorOrchestrator", {a.name for a in node.names},
                    "composition must not import DirectorOrchestrator")
                self.assertNotEqual(node.module, "gnosis.director.orchestrator")
            if isinstance(node, ast.Import):
                self.assertNotIn("orchestrator",
                                 {a.name.split(".")[-1] for a in node.names})
            if isinstance(node, ast.Name):
                self.assertNotEqual(node.id, "DirectorOrchestrator")
            if isinstance(node, ast.Attribute):
                self.assertNotEqual(node.attr, "DirectorOrchestrator")


class TestDeploymentBindingFromLayout(_Base):
    def test_from_layout_consumes_config_json_and_paths(self) -> None:
        from gnosis.provision.layout import DeploymentLayout
        code = self.root / "code"
        state = self.root / "state"
        work = self.root / "work"
        layout = DeploymentLayout(code_base=code, state_base=state, work_base=work)
        cfg_path = Path(layout.config_path)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({
            "schema": "gnosis.trust.publisher_service.v1",
            "service_name": "gnosis-trust", "pipe_name": r"\\.\pipe\gnosis",
            "service_sid": "S-1-5-80-x", "trust_state_root": str(state),
            "evidence_root": str(state / "bundles"),
            "authorized_worker_sid": "S-1-5-21-derived-1002",
            "expected_deployment_digest": "d" * 64, "log_path": str(state / "log.txt"),
        }), encoding="utf-8")
        dep = trusted_deployment_from_layout(layout, "GnosisWorker")
        self.assertEqual(dep.worker_account.expected_sid, "S-1-5-21-derived-1002")
        self.assertEqual(dep.worker_account.username, "GnosisWorker")
        self.assertEqual(dep.runtime_executable, Path(layout.runtime_executable))
        self.assertEqual(dep.credential_blob_path, Path(layout.secrets_blob))

    def test_from_layout_missing_config_fails_closed(self) -> None:
        from gnosis.provision.layout import DeploymentLayout
        layout = DeploymentLayout(code_base=self.root / "c", state_base=self.root / "s",
                                  work_base=self.root / "w")
        with self.assertRaises(CompositionError):
            trusted_deployment_from_layout(layout, "GnosisWorker")


if __name__ == "__main__":
    unittest.main()
