import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from gnosis.director import cli
from gnosis.director.composition import CompositionError, validate_integration_target
from gnosis.director.projects import ProjectPlan, ProjectTask
from tests.test_task_dependencies import brief


@pytest.mark.parametrize("command", ["project-submit", "project-status", "project-run"])
def test_project_cli_dispatches_without_implicitly_running(tmp_path: Path, command: str) -> None:
    plan = ProjectPlan("P", (ProjectTask(brief("P--task")),))
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan.to_dict()))
    executor = Mock()
    executor.status.return_value = {"complete": True}
    executor.run.return_value.to_dict.return_value = {"completed": ["P--task"]}
    args = [command, "--config", "trusted.json"]
    args += ["--plan", str(path)] if command == "project-submit" else ["--project", "P"]
    if command == "project-run":
        args += ["--worker", "controller"]
    with (patch.object(cli, "load_operator_configuration", return_value=("config", "publication")),
          patch("gnosis.director.project_execution.ProjectExecutor", return_value=executor) as factory):
        assert cli.main(args) == cli.EXIT_OK
    factory.assert_called_once_with("P", "config", "publication")
    if command == "project-run":
        executor.run.assert_called_once_with("controller")
    else:
        executor.run.assert_not_called()
    if command == "project-submit":
        executor.submit.assert_called_once_with(plan)
    else:
        executor.submit.assert_not_called()


def test_unfinished_project_is_not_success() -> None:
    executor = Mock()
    executor.status.return_value = {"complete": False}
    executor.run.return_value.to_dict.return_value = {"blocked": ["P--task"]}
    with (patch.object(cli, "load_operator_configuration", return_value=(None, None)),
          patch("gnosis.director.project_execution.ProjectExecutor", return_value=executor)):
        assert cli.main(["project-run", "--config", "config", "--project", "P",
                         "--worker", "controller"]) == cli.EXIT_WORK_FAILED


@pytest.mark.parametrize("body", [
    '{"schema":"gnosis.project.v1","schema":"gnosis.project.v1"}',
    '{"schema":"gnosis.project.v1","project_id":"P","tasks":[],"integration":{"authorized":true}}',
    '{"schema":"gnosis.project.v1","project_id":"../P","tasks":[]}',
])
def test_bad_plan_refused_before_loading_deployment(tmp_path: Path, body: str) -> None:
    path = tmp_path / "bad.json"
    path.write_text(body)
    with patch.object(cli, "load_operator_configuration") as load:
        assert cli.main(["project-submit", "--config", "config", "--plan", str(path)]) == cli.EXIT_USAGE
    load.assert_not_called()


@pytest.mark.parametrize("target", ["", "../main", "-main", "main..old", "main/", "main.lock", "a//b", True])
def test_invalid_trusted_targets_are_refused(target) -> None:
    with pytest.raises(CompositionError):
        validate_integration_target(target)


@pytest.mark.parametrize("target", ["main", "master", "release/v1", "codex/task-1"])
def test_valid_trusted_target_names(target: str) -> None:
    validate_integration_target(target)


@pytest.mark.parametrize("authorized", [True, False, 1, "yes"])
def test_trusted_integration_writer_reader_requires_explicit_authorization(
        tmp_path: Path, authorized) -> None:
    from gnosis.director.composition import build_operator_config
    from tests.test_stage2cb_b1_r3e1 import _inputs

    raw = build_operator_config(replace(_inputs(tmp_path, "test"), integration_target="main"))
    assert raw["integration"] == {"target_branch": "main", "authorized": True}
    raw["integration"]["authorized"] = authorized
    path = tmp_path / "trusted.json"
    path.write_text(json.dumps(raw))
    with (patch.object(cli, "build_reviewer"),
          patch("gnosis.director.composition.trusted_deployment_from_layout"),
          patch("gnosis.trust.deployment.observe_deployment")):
        if authorized is True:
            config, _ = cli.load_operator_configuration(path)
            assert config.integration_target == "main"
        else:
            with pytest.raises(cli.OperatorError, match="explicit trusted authorization"):
                cli.load_operator_configuration(path)
