from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trust_fixtures as tf

from gnosis.contracts.director_brief import BriefSource, DirectorBrief
from gnosis.contracts.engineer_report import EngineerReport, ReportStatus
from gnosis.director.pipeline import PipelineOutcome
from gnosis.director.proof import capture_task_proof
from gnosis.director.publication import PublicationError
from gnosis.kernel.convergence import (
    ConvergenceOutcome,
    ConvergenceResult,
    ReviewReport,
    ReviewVerdict,
    RoundRecord,
)
from gnosis.kernel.engine import TaskExecutionOutcome
from gnosis.kernel.evidence_capture import CheckCommand, run_capture
from gnosis.kernel.scheduler import ScheduleOutcome
from gnosis.kernel.state_machine import TaskState
from gnosis.kernel.subject import observe_subject
from gnosis.kernel.verification import CommandVerifier, VerificationResult
from gnosis.runner.capture import ExecutionResult
from gnosis.trust.bundle_verify import verify_bundle


def _inputs(root: Path):
    repo = tf.git_repo(root / "repo")
    (repo / "code.py").write_text("x = 2\n")
    subject = observe_subject(repo)
    brief = DirectorBrief("B1", "change x", "set x to two", BriefSource.MANUAL,
                          acceptance_criteria=("x == 2",))
    report = EngineerReport("T1", "run-1", ReportStatus.COMPLETED, brief.title)
    verification = VerificationResult("check", True, 0, 0.1, "verified", "")
    round_record = RoundRecord(1, subject.digest(), True, verification,
                              ReviewReport(ReviewVerdict.PASS, reviewer="independent"),
                              (), (), None, (), 0, subject)
    convergence = ConvergenceResult(ConvergenceOutcome.CONVERGED, (round_record,), (), (), ())
    stdout, stderr = root / "stdout", root / "stderr"
    stdout.write_text("raw provider output")
    stderr.write_text("")
    execution = ExecutionResult(("provider",), 0, False, False, 0.1,
                                str(stdout), str(stderr), "start", "end")
    implementation = TaskExecutionOutcome("T1", ["run-1"], TaskState.COMPLETED,
                                          verification, execution, report)
    work = PipelineOutcome("B1", "T1", ReportStatus.COMPLETED, "converged", report,
                           ScheduleOutcome("T1", True, "ok", implementation), convergence)
    spec = replace(tf.spec(), cwd=str(repo), stdout_path=str(stdout), stderr_path=str(stderr))
    convergence_dir = root / "convergence"
    convergence_dir.mkdir()
    (convergence_dir / "review-independent-1.stdout").write_text('{"verdict":"PASS"}')
    verifier = CommandVerifier("x is two", [sys.executable, "-c",
                               "from pathlib import Path; assert Path('code.py').read_text() == 'x = 2\\n'"],
                               timeout_s=10)
    return {"bundle_dir": root / "evidence" / "run-1", "source": repo, "brief": brief,
            "work": work, "run_id": "run-1", "spec": spec, "verifier": verifier,
            "convergence_dir": convergence_dir}


@pytest.mark.skipif(os.name != "nt", reason="real Windows locks and write observer")
def test_real_capture_binds_dirty_reviewed_bytes_not_head_tree(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    tree = capture_task_proof(**inputs)
    bundle = inputs["bundle_dir"]
    assert verify_bundle(bundle).verified
    packet = json.loads((bundle / "PROOF.json").read_text())
    manifest = json.loads((bundle / "input-manifest.json").read_text())
    assert manifest["inputs"] == packet["subject"]["files"]
    assert tree.tree_identity == packet["capture_content_digest"]
    assert packet["brief"]["acceptance_criteria"] == ["x == 2"]
    assert packet["convergence"]["rounds"][-1]["review"]["reviewer"] == "independent"
    assert (bundle / "raw" / "worker.stdout").read_text() == "raw provider output"
    assert (inputs["source"] / "code.py").read_text() == "x = 2\n"
    summary = json.loads((bundle / "SUMMARY.json").read_text())
    assert summary["boundary"]["verdict"] == "CLEAN"
    assert summary["boundary"]["protection"]["byte_bound_inputs"] == 1


@pytest.mark.parametrize("missing", ["subject", "review", "verification", "launch", "brief"])
def test_absent_or_mismatched_required_evidence_never_captures(tmp_path: Path, missing: str) -> None:
    inputs = _inputs(tmp_path)
    work = inputs["work"]
    convergence = work.convergence
    final = convergence.rounds[-1]
    if missing == "subject":
        final = replace(final, subject=None)
    elif missing == "review":
        final = replace(final, review=ReviewReport(ReviewVerdict.UNCERTAIN))
    elif missing == "verification":
        final = replace(final, verification=None)
    elif missing == "launch":
        inputs["spec"] = replace(inputs["spec"], cwd=str(tmp_path))
    else:
        inputs["brief"] = replace(inputs["brief"], brief_id="OTHER")
    inputs["work"] = replace(work, convergence=replace(convergence, rounds=(final,)))
    with patch("gnosis.director.proof.run_capture") as capture:
        with pytest.raises(PublicationError):
            capture_task_proof(**inputs)
        capture.assert_not_called()


def test_edits_after_review_refuse_copy(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    (inputs["source"] / "code.py").write_text("x = 3\n")
    with pytest.raises(PublicationError, match="changed before"):
        capture_task_proof(**inputs)
    assert not inputs["bundle_dir"].exists()


def test_proof_reuses_assigned_verifier_execution_boundary(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    boundary = object()
    inputs["verifier"].executor = boundary
    with patch("gnosis.director.proof.run_capture",
               side_effect=RuntimeError("boundary reached")) as capture:
        with pytest.raises(RuntimeError, match="boundary reached"):
            capture_task_proof(**inputs)
    assert capture.call_args.kwargs["executor"] is boundary


def test_unbounded_verifier_is_refused_before_copy(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    inputs["verifier"].timeout_s = None
    with pytest.raises(PublicationError, match="finite verifier deadline"):
        capture_task_proof(**inputs)
    assert not inputs["bundle_dir"].exists()


@pytest.mark.skipif(os.name != "nt", reason="real Windows capture")
@pytest.mark.parametrize("code", ["raise SystemExit(1)", "import time; time.sleep(20)"])
def test_failed_or_timed_out_reverification_cannot_publish(tmp_path: Path, code: str) -> None:
    inputs = _inputs(tmp_path)
    inputs["verifier"] = CommandVerifier("failing", [sys.executable, "-c", code], timeout_s=0.2)
    with pytest.raises(PublicationError, match="checks=FAILED"):
        capture_task_proof(**inputs)
    assert not (inputs["bundle_dir"] / "PROOF.json").exists()
    assert (inputs["source"] / "code.py").read_text() == "x = 2\n"


@pytest.mark.skipif(os.name != "nt", reason="real Windows capture")
def test_copy_mutated_before_locked_check_is_not_reviewed_content(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)

    def changed(repo, commands, staging):
        (repo / "extra-input").write_text("not reviewed")
        return run_capture(repo, commands, staging)

    with (patch("gnosis.director.proof.run_capture", side_effect=changed),
          pytest.raises(PublicationError, match="no longer matches")):
        capture_task_proof(**inputs)


@pytest.mark.parametrize("timeout", [float("inf"), float("nan"), 0, -1, True])
def test_capture_timeout_must_be_finite(timeout: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        CheckCommand("test", (sys.executable,), timeout_s=timeout)


@pytest.mark.skipif(os.name != "nt", reason="real Windows evidence capture")
@pytest.mark.parametrize("needs_fix", [False, True])
@pytest.mark.parametrize("interruption", [None, "before_publish", "after_anchor", "before_proof",
                                         "after_capture", "after_receipt", "after_finalize"])
def test_canonical_pipeline_to_proof_and_anchor_with_fake_worker(tmp_path: Path,
                needs_fix: bool, interruption: str | None, integrate: bool = False) -> None:
    """Only Worker/provider/service transport are doubles; the full graph runs.

    In particular this catches a second run_id minted by the runner, observing
    the base repository instead of the task worktree, and absent review binding.
    """
    from test_cli_review_adapters import _PASS_REVIEW, _ScriptedAgent
    from test_pipeline import _FAIL_REVIEW
    from test_pipeline_trusted_execution import _permissive, _SpyLauncher

    from gnosis.director.composition import (
        AttributionInputs,
        OperatorInputs,
        ProductionCompositionConfig,
        PublicationCompositionInputs,
        TrustedDeploymentInputs,
        build_production_deployment,
    )
    from gnosis.director.publisher_client import InProcessPublisherClient, PublisherClientError
    from gnosis.kernel.claims import ClaimStore, WorkAuthority
    from gnosis.kernel.execution_scope import ExecutionScope
    from gnosis.kernel.lease import LeaseStore
    from gnosis.runner.claude_cli_runner import CancellationToken
    from gnosis.trust.worker_launcher import WorkerAccount

    class EditingLauncher(_SpyLauncher):
        def launch(self, spec):
            if spec.run_id.startswith("check-"):
                # Exercise the real verifier wrapper in this component test.
                # Only the OS identity transition is replaced by this fake.
                from test_pipeline_trusted_execution import _SpyLaunched

                with (Path(spec.stdout_path).open("wb") as out,
                      Path(spec.stderr_path).open("wb") as err):
                    checked = subprocess.run(spec.argv, cwd=spec.cwd, stdout=out, stderr=err,
                                             timeout=20, check=False)
                return _SpyLaunched(checked.returncode, False)
            value = 1 if needs_fix and self.launch_count == 0 else 2
            (Path(spec.cwd) / "code.py").write_text(f"x = {value}\n")
            Path(spec.stderr_path).write_text("")
            worker = super().launch(spec)
            worker.identity = tf.launched()
            return worker

    repo = tf.git_repo(tmp_path / "repo")
    blob = tmp_path / "worker.dpapi"
    blob.write_bytes(b"component-test-only")
    pub = PublicationCompositionInputs(
        tmp_path / "trust", tmp_path / "trust" / "evidence",
        tf.v2_deployment_for_runtime(Path(sys.executable)), "repo", r"\\.\pipe\test")
    reviewer = _ScriptedAgent([_FAIL_REVIEW, _PASS_REVIEW] if needs_fix else [_PASS_REVIEW])
    reviewer.binary = "component-reviewer"
    policy = _permissive()
    if integrate:
        from gnosis.kernel.engine import AGENT_RUN_INTERVENTION_POINT
        from gnosis.kernel.integration import INTEGRATION_INTERVENTION_POINT
        from gnosis.kernel.policy import InterventionPoint, PolicyEngine, RuleOutcome, Verdict

        policy = PolicyEngine([InterventionPoint(
            name=name, declared_tools=frozenset({tool}), requires_intent=True,
            rules=(("component-test-authorization", lambda _: RuleOutcome(Verdict.ALLOW, "ok:test")),),
        ) for name, tool in [(AGENT_RUN_INTERVENTION_POINT, "claude_cli"),
                            (INTEGRATION_INTERVENTION_POINT, "git_merge")]])
    target = subprocess.run(["git", "branch", "--show-current"], cwd=repo,
                            capture_output=True, text=True, check=True).stdout.strip()
    config = ProductionCompositionConfig(
        deployment=TrustedDeploymentInputs(Path(sys.executable),
            WorkerAccount("ComponentWorker", ".", tf.SID_OBSERVED, "Medium"),
            blob, tmp_path / "launch"),
        attribution=AttributionInputs("independent", "agent://test-director"),
        operator=OperatorInputs(tmp_path / "director", repo),
        verifier=CommandVerifier("x is two", [sys.executable, "-c",
            "from pathlib import Path; assert Path('code.py').read_text() == 'x = 2\\n'"],
            timeout_s=10),
        review_runner=reviewer, policy=policy,
        integration_target=target if integrate else None)
    client = InProcessPublisherClient(pub.trust_state_root, pub.deployment.digest(), tf.SID_OBSERVED)
    class InterruptedPublisher:
        calls = 0

        def publish(self, run_id):
            self.calls += 1
            if self.calls == 1 and interruption == "before_publish":
                raise PublisherClientError("service not reachable")
            result = client.publish(run_id)
            if self.calls == 1 and interruption == "after_anchor":
                raise PublisherClientError("reply lost after anchor")
            return result

    publisher = InterruptedPublisher()
    launcher = EditingLauncher()
    claimed = integrate or interruption in {"before_proof", "after_receipt", "after_finalize"}
    authority = WorkAuthority(ClaimStore(tmp_path / "claims"), LeaseStore(tmp_path / "leases"),
                              default_ttl_s=300)
    grant = None
    def next_scope():
        nonlocal grant
        if not claimed:
            return None
        if grant is not None:
            authority.release(grant)
        grant = authority.acquire("B1", "controller")
        return ExecutionScope.borrowed(authority, grant, CancellationToken())
    with (patch("gnosis.director.composition.TrustedWindowsWorkerLauncher", return_value=launcher),
          patch("gnosis.director.composition.PipePublisherClient", return_value=publisher)):
        production = build_production_deployment(config, pub, scope=next_scope())
    brief = DirectorBrief("B1", "set x", "set x to two", BriefSource.MANUAL)
    if interruption in {"before_proof", "after_capture", "after_receipt", "after_finalize"}:
        if interruption == "before_proof":
            crash = patch("gnosis.director.composition.capture_task_proof",
                          side_effect=SystemExit("power loss"))
        elif interruption == "after_finalize":
            crash = patch.object(production._checkpoints, "save", side_effect=SystemExit("power loss"))
        else:
            original_update = production.pipeline.checkpoints.update
            def interrupt_update(prior, **changes):
                if changes.get("proof") is not None and interruption == "after_capture":
                    raise SystemExit("power loss")
                result = original_update(prior, **changes)
                if changes.get("proof") is not None:
                    raise SystemExit("power loss")
                return result
            crash = patch.object(production.pipeline.checkpoints, "update", side_effect=interrupt_update)
        with crash, pytest.raises(SystemExit):
            production.run_brief(brief)
        saved = production.pipeline.checkpoints.load(brief.brief_id)
        assert saved.trusted_attempt is not None
        assert saved.proof_attempts == 1
        assert (saved.proof is not None) == (interruption in {"after_receipt", "after_finalize"})
        launches = launcher.launch_count
        reviews = list(reviewer.permission_modes)
        with (patch("gnosis.director.composition.TrustedWindowsWorkerLauncher", return_value=launcher),
              patch("gnosis.director.composition.PipePublisherClient", return_value=publisher)):
            production = build_production_deployment(config, pub, scope=next_scope())
        with patch.object(production.pipeline.scheduler, "submit", side_effect=AssertionError("reimplemented")):
            out = production.run_brief(brief)
        assert out.success, out.reason
        assert out.task_id == saved.task_id and out.run_id == saved.trusted_attempt.spec.run_id
        assert launcher.launch_count == launches and reviewer.permission_modes == reviews
        recovered = production.pipeline.checkpoints.load(brief.brief_id)
        assert recovered.proof_attempts == (2 if saved.proof is None else 1)
    else:
        out = production.run_brief(brief)
    original = out
    if interruption in {"before_publish", "after_anchor"}:
        assert not out.success
        assert "could not be anchored" in out.reason
    else:
        assert out.success, out.reason
    launches = launcher.launch_count
    reviews = list(reviewer.permission_modes)
    # Rebuild the composition from persisted files, with no in-memory launch.
    with (patch("gnosis.director.composition.TrustedWindowsWorkerLauncher", return_value=launcher),
          patch("gnosis.director.composition.PipePublisherClient", return_value=publisher)):
        production = build_production_deployment(config, pub, scope=next_scope())
    with patch.object(production.pipeline, "run_brief", side_effect=AssertionError("re-executed")):
        out = production.run_brief(brief)
    assert out.run_id == original.run_id and out.task_id == original.task_id
    assert launcher.launch_count == launches
    assert reviewer.permission_modes == reviews
    assert publisher.calls == 2  # even ANCHORED is reconciled by the Publisher
    assert out.success, out.reason
    assert out.publication_state == "ANCHORED"
    if claimed:
        authority.assert_current(grant)
        saved = production.pipeline.checkpoints.load(brief.brief_id)
        assert saved.trusted_attempt.epoch == 1
        assert grant.claim.epoch > 1
        publication_record = json.loads(production._checkpoints.path_for(brief.brief_id).read_text())
        assert publication_record["epoch"] == 1
    bundle = pub.evidence_root / out.run_id
    assert verify_bundle(bundle).verified
    proof = json.loads((bundle / "PROOF.json").read_text())
    assert proof["run_id"] == proof["report"]["run_id"] == out.run_id
    assert Path(proof["source"]) != repo
    assert (repo / "code.py").read_text() == ("x = 2\n" if integrate else "x = 1\n")
    if integrate:
        phase = production.pipeline.checkpoints.load(brief.brief_id)
        assert phase.integration.integrated
        assert phase.prepared_integration is not None
        assert phase.integration_attempts == 1
    assert (Path(proof["source"]) / "code.py").read_text() == "x = 2\n"
    assert reviewer.permission_modes == (["plan", "plan"] if needs_fix else ["plan"])
    if needs_fix:
        attempts = proof["convergence"]["rework_attempts"]
        assert len(attempts) == 1
        assert attempts[-1]["run_id"] == out.run_id
        assert attempts[-1]["state"] == "SUCCEEDED"
        store = production.pipeline.scheduler.engine.run_store
        assert store.read_meta(out.run_id).task_id == out.task_id
        assert store.paths_for(out.run_id).result.is_file()
        assert len(production.pipeline.records.get("B1").run_ids) == 2
    # Recomputing the bundle manifest cannot replace the externally saved digest.
    from gnosis.trust.bundle_verify import write_bundle_manifest
    (bundle / "raw/worker.stdout").write_text("edited after checkpoint")
    write_bundle_manifest(bundle)
    with patch.object(production.pipeline, "run_brief", side_effect=AssertionError("re-executed")):
        refused = production.run_brief(brief)
    assert not refused.success and "digest mismatch" in refused.reason
    assert publisher.calls == 2


@pytest.mark.skipif(os.name != "nt", reason="real Windows evidence capture")
@pytest.mark.parametrize("needs_fix", [False, True])
@pytest.mark.parametrize("interruption", [None, "after_anchor"])
def test_canonical_published_work_lands_and_recovers(tmp_path: Path, needs_fix: bool,
                                                   interruption: str | None) -> None:
    test_canonical_pipeline_to_proof_and_anchor_with_fake_worker(
        tmp_path, needs_fix, interruption, integrate=True)
