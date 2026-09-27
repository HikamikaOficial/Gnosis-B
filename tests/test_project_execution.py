from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.director import cli
from gnosis.director.composition import (
    AttributionInputs,
    OperatorInputs,
    ProductionCompositionConfig,
    PublicationCompositionInputs,
    TrustedDeploymentInputs,
)
from gnosis.director.project_execution import ProjectExecutor
from gnosis.director.projects import ProjectPlan, ProjectTask
from gnosis.director.publisher_client import InProcessPublisherClient
from gnosis.kernel.engine import AGENT_RUN_INTERVENTION_POINT
from gnosis.kernel.integration import INTEGRATION_INTERVENTION_POINT
from gnosis.kernel.policy import InterventionPoint, PolicyEngine, RuleOutcome, Verdict
from gnosis.kernel.verification import CommandVerifier
from gnosis.trust.anchor import AnchorStore
from gnosis.trust.worker_launcher import WorkerAccount
from tests import trust_fixtures as tf
from tests.test_cli_review_adapters import _PASS_REVIEW, _ScriptedAgent
from tests.test_pipeline_trusted_execution import _SpyLaunched, _SpyLauncher


@pytest.mark.skipif(os.name != "nt", reason="real Windows proof capture")
@pytest.mark.parametrize("allow_integration,crash_after_parent,takeover_during_reply",
    [(True, False, False), (True, True, False), (False, False, False), (True, False, True)])
def test_project_dependencies_use_published_landed_parent(tmp_path: Path,
                    allow_integration: bool, crash_after_parent: bool,
                    takeover_during_reply: bool) -> None:
    repo = tf.git_repo(tmp_path / "repo")
    target = subprocess.run(["git", "branch", "--show-current"], cwd=repo,
                            capture_output=True, text=True, check=True).stdout.strip()
    seen = []
    check_workspaces = []

    class EditingLauncher(_SpyLauncher):
        def launch(self, spec):
            if spec.run_id.startswith("check-"):
                # Verification is now launched as a Worker too. Execute its real
                # command instead of impersonating another provider edit. Only
                # the Windows identity transition is replaced by this fixture.
                workspace = Path(spec.cwd)
                before = (workspace / "code.py").read_bytes()
                with (Path(spec.stdout_path).open("wb") as out,
                      Path(spec.stderr_path).open("wb") as err):
                    checked = subprocess.run(spec.argv, cwd=workspace, stdout=out,
                                             stderr=err, timeout=20, check=False)
                assert (workspace / "code.py").read_bytes() == before
                check_workspaces.append(workspace)
                return _SpyLaunched(checked.returncode, False)
            path = Path(spec.cwd) / "code.py"
            seen.append(path.read_text())
            path.write_text(f"x = {self.launch_count + 2}\n")
            Path(spec.stderr_path).write_text("")
            worker = super().launch(spec)
            worker.identity = tf.launched()
            return worker

    launcher = EditingLauncher()
    blob = tmp_path / "worker.dpapi"
    blob.write_bytes(b"component-test-only")
    reviewer = _ScriptedAgent([_PASS_REVIEW, _PASS_REVIEW])
    reviewer.binary = "component-reviewer"
    points = [InterventionPoint(name=AGENT_RUN_INTERVENTION_POINT,
        declared_tools=frozenset({"claude_cli"}), requires_intent=True,
        rules=(("test", lambda _: RuleOutcome(Verdict.ALLOW, "ok:test")),))]
    if allow_integration:
        points.append(InterventionPoint(name=INTEGRATION_INTERVENTION_POINT,
            declared_tools=frozenset({"git_merge"}), requires_intent=True,
            rules=(("test", lambda _: RuleOutcome(Verdict.ALLOW, "ok:test")),)))
    config = ProductionCompositionConfig(
        deployment=TrustedDeploymentInputs(Path(sys.executable),
            WorkerAccount("ComponentWorker", ".", tf.SID_OBSERVED, "Medium"),
            blob, tmp_path / "launch"),
        attribution=AttributionInputs("independent", "agent://test-director"),
        operator=OperatorInputs(tmp_path / "director", repo),
        verifier=CommandVerifier("changed", [sys.executable, "-c",
            "from pathlib import Path; assert Path('code.py').read_text() in ('x = 2\\n', 'x = 3\\n')"],
            timeout_s=10), review_runner=reviewer, policy=PolicyEngine(points),
        integration_target=target)
    pub = PublicationCompositionInputs(tmp_path / "trust", tmp_path / "trust" / "evidence",
        tf.v2_deployment_for_runtime(Path(sys.executable)), "repo", r"\\.\pipe\test")
    publisher = InProcessPublisherClient(pub.trust_state_root, pub.deployment.digest(), tf.SID_OBSERVED)
    plan = ProjectPlan("P", (
        ProjectTask(DirectorBrief("P--parent", "parent", "set x to two", BriefSource.MANUAL)),
        ProjectTask(DirectorBrief("P--child", "child", "set x to three", BriefSource.MANUAL),
                    ("P--parent",)),
    ))
    with (patch("gnosis.director.composition.TrustedWindowsWorkerLauncher", return_value=launcher),
          patch("gnosis.director.composition.PipePublisherClient", return_value=publisher),
          patch.object(cli, "load_operator_configuration", return_value=(config, pub))):
        executor = ProjectExecutor("P", config, pub)
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan.to_dict()))
        with redirect_stdout(io.StringIO()):
            assert cli.main(["project-submit", "--config", "trusted", "--plan", str(plan_path)]) == 0
        assert launcher.launch_count == 0
        if takeover_during_reply:
            current_work, replacements, published = [], [], []
            execute, publish = executor._execute, publisher.publish

            def track_work(work):
                current_work.append(work)
                return execute(work)

            def reply_after_takeover(run_id):
                reply = publish(run_id)
                published.append(run_id)
                authority = executor.queue.authority
                authority.release(current_work[-1].grant)
                replacements.append(authority.acquire("P--parent", "replacement"))
                return reply

            with (patch.object(executor, "_execute", side_effect=track_work),
                  patch.object(publisher, "publish", side_effect=reply_after_takeover)):
                interrupted = executor.run("old-controller")
            assert not interrupted.completed
            assert executor.queue.done_ids() == []
            assert seen == ["x = 1\n"]
            assert (repo / "code.py").read_text() == "x = 1\n"
            assert executor.status()["dependencies_waiting"] == ["P--child"]
            assert len(published) == 1
            executor.queue.authority.release(replacements[0])
        elif crash_after_parent:
            complete = executor.queue.complete
            def crash(work, outcome):
                complete(work, outcome)
                raise SystemExit("controller died after completing parent")
            with patch.object(executor.queue, "complete", side_effect=crash), pytest.raises(SystemExit):
                executor.run("controller")
        else:
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli.main(["project-run", "--config", "trusted", "--project", "P",
                                 "--worker", "controller"])
            assert code == (cli.EXIT_OK if allow_integration else cli.EXIT_WORK_FAILED)
            report = json.loads(output.getvalue())["supervision"]
        restored = ProjectExecutor("P", config, pub)
        resumed = restored.run("replacement")
        if takeover_during_reply:
            # Recovery deliberately paces an interrupted attempt. Respect that
            # persisted deadline, advancing only the queue's scheduling clock.
            waiting = restored.queue.waiting()
            assert [item[0] for item in waiting] == ["P--parent"]
            assert not resumed.completed
            due = max(item[1] for item in waiting)
            restored.queue.clock = lambda: due + 1
            resumed = restored.run("replacement")
    assert len(check_workspaces) >= 3
    assert all(path.is_relative_to(tmp_path / "launch") for path in check_workspaces)
    if allow_integration:
        if takeover_during_reply:
            assert resumed.completed == ("P--parent", "P--child"), resumed.to_dict()
            anchors = AnchorStore(pub.trust_state_root / "anchors", require_high=False)
            assert anchors.verify_chain()
            assert len(anchors.records()) == 2
            assert sum(record.run_id == published[0] for record in anchors.records()) == 1
        elif crash_after_parent:
            assert resumed.completed == ("P--child",), resumed.to_dict()
        else:
            assert report["completed"] == ["P--parent", "P--child"], report
        assert seen == ["x = 1\n", "x = 2\n"]
        assert (repo / "code.py").read_text() == "x = 3\n"
        assert restored.status()["complete"]
    else:
        assert report["blocked"] == ["P--parent"], report
        assert seen == ["x = 1\n"]
        assert (repo / "code.py").read_text() == "x = 1\n"
        assert restored.status()["dependencies_waiting"] == ["P--child"]
        assert not restored.status()["complete"]
