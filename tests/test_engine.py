import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from gnosis.contracts.engineer_report import ReportStatus
from gnosis.kernel.claims import ClaimStatus, ClaimStore, StaleClaimError, WorkAuthority
from gnosis.kernel.code_intelligence import (
    CodeIntelligenceProvider,
    CodeIntelligenceUnavailable,
    CompactContext,
    IndexStatus,
)
from gnosis.kernel.engine import AGENT_RUN_INTERVENTION_POINT, TaskEngine
from gnosis.kernel.failures import FailureClass
from gnosis.kernel.lease import LeaseStore, StaleLeaseError
from gnosis.kernel.policy import (
    ActionSnapshot,
    ApprovalStore,
    InterventionPoint,
    PolicyEngine,
    RuleOutcome,
    Verdict,
)
from gnosis.kernel.run_store import RunStore
from gnosis.kernel.state_machine import RunState, TaskState
from gnosis.kernel.verification import CommandVerifier, VerificationResult, Verifier
from gnosis.kernel.worktree import WorktreeError, WorktreeManager
from gnosis.runner.capture import ExecutionResult
from gnosis.runner.claude_cli_runner import McpRunnerConfig
from gnosis.runner.retry import RetryPolicy

_FAST_RETRY = RetryPolicy(max_attempts=3, backoff_base_s=0.01, backoff_factor=2.0, max_backoff_s=0.02)

# Every task now needs deterministic verification to reach COMPLETED: the
# engine refuses a verifier-less run before it launches anything, and
# `completion_is_evidenced` refuses the transition without a passing
# result (F-34). This is REAL verification — a child process and the exit
# code the OS reports — not a stand-in that says "passed" without looking,
# which is the fixture mistake L-0013 was earned on.
_PASSING_VERIFIER = CommandVerifier(
    "always-pass", [sys.executable, "-c", "raise SystemExit(0)"])


class _FakeCliRunner:
    """Duck-types ClaudeCodeCLIRunner.run() without shelling out to claude,
    keeping the engine integration test hermetic and free."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0
        self.prompts_seen = []

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        self.calls += 1
        self.prompts_seen.append(prompt)
        outcome = self._outcomes[min(self.calls, len(self._outcomes)) - 1]
        stdout_path.write_text('{"ok": true}' if outcome == "succeed" else "", encoding="utf-8")
        stderr_path.write_text("" if outcome == "succeed" else "simulated failure", encoding="utf-8")
        return ExecutionResult(
            command=("fake-claude",), exit_code=0 if outcome == "succeed" else 1,
            timed_out=False, cancelled=False, duration_s=0.01,
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            started_at="t0", ended_at="t1",
        )


class TestTaskEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        self.store = RunStore(self.root / "runs")

    def tearDown(self):
        self.tmp.cleanup()

    def test_success_path_completes_task(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-1", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        self.assertEqual(len(outcome.run_ids), 1)
        self.assertEqual(outcome.report.status.value, "COMPLETED")

    def test_retries_then_succeeds(self):
        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["fail", "fail", "succeed"]),
            retry_policy=_FAST_RETRY,
        )
        outcome = engine.execute_task(
            task_id="TASK-2", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        self.assertEqual(len(outcome.run_ids), 3)

    def test_exhausts_retries_and_fails(self):
        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["fail", "fail", "fail"]),
            retry_policy=_FAST_RETRY,
        )
        outcome = engine.execute_task(
            task_id="TASK-3", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertEqual(len(outcome.run_ids), 3)

    def test_verifier_failure_fails_task_even_if_cli_succeeds(self):
        failing_verifier = CommandVerifier("always-fail", [sys.executable, "-c", "import sys; sys.exit(1)"])
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-4", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=failing_verifier,
        )
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertFalse(outcome.verification.passed)

    def test_mcp_config_forwarded_and_audited_in_ledger(self):
        cfg = McpRunnerConfig(config_paths=("tool.json",))
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-MCP", objective="Demo", prompt="do it", repo_path=self.repo, mcp=cfg,
            verifier=_PASSING_VERIFIER,
        )
        events = self.store.ledger_for(outcome.run_ids[-1]).read_all()
        started = next(e for e in events if e.event_type == "run.attempt_started")
        self.assertEqual(started.data["mcp"], {"config_paths": ["tool.json"], "strict": False})

    def test_no_mcp_config_audited_as_none(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-NOMCP", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=_PASSING_VERIFIER,
        )
        events = self.store.ledger_for(outcome.run_ids[-1]).read_all()
        started = next(e for e in events if e.event_type == "run.attempt_started")
        self.assertIsNone(started.data["mcp"])

    def test_git_evidence_captured_per_run(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-5", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=_PASSING_VERIFIER,
        )
        git_dir = self.store.paths_for(outcome.run_ids[-1]).git_dir
        self.assertTrue((git_dir / "pre.json").exists())
        self.assertTrue((git_dir / "post.json").exists())


class _RateLimitedRunner(_FakeCliRunner):
    """A CLI that reports a structured rate limit — the shape a real
    adapter surfaces from a provider response."""

    def __init__(self):
        super().__init__(["fail"])

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        result = super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs)
        stderr_path.write_text("Error: usage limit reached", encoding="utf-8")
        return result


class TestFailureTaxonomyWiring(unittest.TestCase):
    """Directive 9 end-to-end: the reason code flows from the adapter's
    classification into the append-only event and into the retry
    decision. A taxonomy nothing consults is a parallel fiction."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        self.store = RunStore(self.root / "runs")

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_attempt_is_classified_into_the_ledger(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-CLS", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=_PASSING_VERIFIER,
        )
        events = self.store.ledger_for(outcome.run_ids[-1]).read_all()
        classified = next(e for e in events if e.event_type == "run.attempt_classified")
        self.assertEqual(classified.data["failure"], "PASS")
        self.assertEqual(classified.data["evidence_grade"], "STRUCTURED")
        # The same reason code the scheduler saw, not a paraphrase.
        self.assertEqual(classified.data["reason_code"], outcome.classification.reason_code)

    def test_a_rate_limited_attempt_parks_instead_of_burning_retries(self):
        # Rule 6: RATE_LIMITED != FAIL_CODE. Retrying against a shut
        # window is exactly what the park state exists to prevent.
        engine = TaskEngine(
            run_store=self.store, cli_runner=_RateLimitedRunner(),
            retry_policy=RetryPolicy(max_attempts=3, backoff_base_s=0.01,
                                     backoff_factor=1.0, max_backoff_s=0.01),
        )
        outcome = engine.execute_task(
            task_id="TASK-RL", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(outcome.classification.failure.value, "RATE_LIMITED")
        self.assertEqual(len(outcome.run_ids), 1)  # parked, not retried 3x
        self.assertFalse(outcome.classification.penalizes_agent)  # rule 7

    def test_a_park_is_durable_on_disk_not_just_in_memory(self):
        # A park recorded as FAILED is not a park: no scheduler can resume
        # what looks like an agent failure (adversarial review).
        engine = TaskEngine(
            run_store=self.store, cli_runner=_RateLimitedRunner(),
            retry_policy=RetryPolicy(max_attempts=2, backoff_base_s=0.01,
                                     backoff_factor=1.0, max_backoff_s=0.01),
        )
        outcome = engine.execute_task(
            task_id="TASK-PARK", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=_PASSING_VERIFIER,
        )
        meta = self.store.read_meta(outcome.run_ids[-1])
        self.assertEqual(meta.state, RunState.RATE_LIMITED.value)
        self.assertNotEqual(meta.state, RunState.FAILED.value)

    def test_an_escalating_failure_gets_its_own_report_status(self):
        # ESCALATE used to be filed as a routine PARTIAL, indistinguishable
        # from an ordinary miss (adversarial review).
        class _UnclassifiableRunner(_FakeCliRunner):
            def __init__(self):
                super().__init__(["fail"])

            def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
                result = super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs)
                stdout_path.write_text("", encoding="utf-8")
                stderr_path.write_text("", encoding="utf-8")
                return ExecutionResult(
                    command=result.command, exit_code=None, timed_out=False,
                    cancelled=False, duration_s=0.01,
                    stdout_path=result.stdout_path, stderr_path=result.stderr_path,
                    started_at="t0", ended_at="t1",
                )

        engine = TaskEngine(
            run_store=self.store, cli_runner=_UnclassifiableRunner(),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        outcome = engine.execute_task(
            task_id="TASK-ESC", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(outcome.classification.failure.value, "UNCLASSIFIED")
        self.assertEqual(outcome.report.status, ReportStatus.ESCALATION_REQUIRED)

    def test_an_ordinary_code_failure_still_retries(self):
        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["fail", "fail", "succeed"]),
            retry_policy=_FAST_RETRY,
        )
        outcome = engine.execute_task(
            task_id="TASK-RETRY", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        self.assertEqual(len(outcome.run_ids), 3)


class TestPolicyGate(unittest.TestCase):
    """ADR-0011 wired: the fail-closed engine now gates a real
    intervention point, before any repository-writing child exists."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        self.store = RunStore(self.root / "runs")

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _engine_with(rule):
        return PolicyEngine([InterventionPoint(
            name=AGENT_RUN_INTERVENTION_POINT,
            declared_tools=frozenset({"claude_cli"}),
            rules=(("test-rule", rule),),
            requires_intent=True,
        )])

    def _run(self, policy, approvals=None, runner=None):
        engine = TaskEngine(
            run_store=self.store, cli_runner=runner or _FakeCliRunner(["succeed"]),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        return engine.execute_task(
            task_id="TASK-POL", objective="Demo", prompt="do it",
            repo_path=self.repo, policy=policy, approvals=approvals,
            policy_actor="agent://worker-a",
            verifier=_PASSING_VERIFIER,
        )

    def test_allow_lets_the_run_proceed_and_records_the_verdict(self):
        outcome = self._run(self._engine_with(
            lambda s: RuleOutcome(Verdict.ALLOW, "baseline:permitted")))
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        events = self.store.ledger_for(outcome.run_ids[-1]).read_all()
        decision = next(e for e in events if e.event_type == "policy.decision")
        self.assertEqual(decision.data["verdict"], "ALLOW")
        # An allowed action is evidence too, not just a refused one.
        self.assertEqual(decision.data["reason"], "baseline:permitted")

    def test_deny_never_launches_the_child(self):
        runner = _FakeCliRunner(["succeed"])
        outcome = self._run(
            self._engine_with(lambda s: RuleOutcome(Verdict.DENY, "security:forbidden")),
            runner=runner,
        )
        self.assertEqual(runner.calls, 0)  # the process never existed
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertEqual(outcome.classification.failure, FailureClass.FAIL_POLICY)
        # The policy's own reason code travels into the taxonomy.
        self.assertEqual(outcome.classification.reason_code, "security:forbidden")
        self.assertEqual(outcome.report.status, ReportStatus.ESCALATION_REQUIRED)

    def test_a_refusal_is_durable_evidence_not_silence(self):
        outcome = self._run(self._engine_with(
            lambda s: RuleOutcome(Verdict.DENY, "security:forbidden")))
        run_id = outcome.run_ids[-1]
        events = [e.event_type for e in self.store.ledger_for(run_id).read_all()]
        self.assertIn("policy.decision", events)
        self.assertIn("run.attempt_classified", events)
        # CANCELLED, not FAILED: the run never started, and PENDING->FAILED
        # is not a legal run transition (adversarial review).
        self.assertEqual(self.store.read_meta(run_id).state, RunState.CANCELLED.value)

    def test_an_unconfigured_intervention_point_denies_the_run(self):
        # Configuration gaps are never consent — including the gap of
        # never declaring this engine's own intervention point.
        outcome = self._run(PolicyEngine([]))
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertEqual(outcome.classification.reason_code,
                         "policy_gap:unconfigured_intervention_point")

    def test_escalation_blocks_until_the_exact_action_is_approved(self):
        policy = self._engine_with(
            lambda s: RuleOutcome(Verdict.ESCALATE, "human:review_required"))
        approvals = ApprovalStore()
        blocked = self._run(policy, approvals)
        # ESCALATED, not FAILED: "approve, then resubmit" is not terminal.
        self.assertEqual(blocked.final_task_state, TaskState.ESCALATED)
        self.assertEqual(blocked.report.status, ReportStatus.ESCALATION_REQUIRED)

        # Approve exactly what was evaluated, then it proceeds.
        action_id = blocked.classification.detail["action_id"]
        approvals.grant(action_id, approver="nicol")
        allowed = self._run(policy, approvals)
        self.assertEqual(allowed.final_task_state, TaskState.COMPLETED)

    def test_an_approval_does_not_transfer_to_a_different_prompt(self):
        # Anti-TOCTOU at the engine boundary: the prompt is part of the
        # action identity via its hash.
        policy = self._engine_with(
            lambda s: RuleOutcome(Verdict.ESCALATE, "human:review_required"))
        approvals = ApprovalStore()
        first = self._run(policy, approvals)
        approvals.grant(first.classification.detail["action_id"], approver="nicol")

        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        other = engine.execute_task(
            task_id="TASK-POL", objective="Demo", prompt="do something ELSE",
            repo_path=self.repo, policy=policy, approvals=approvals,
            policy_actor="agent://worker-a",
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(other.final_task_state, TaskState.ESCALATED)
        self.assertEqual(other.report.status, ReportStatus.ESCALATION_REQUIRED)

    def test_a_warning_proceeds_but_is_recorded(self):
        outcome = self._run(self._engine_with(
            lambda s: RuleOutcome(Verdict.WARN, "style:unusual_prompt")))
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        events = self.store.ledger_for(outcome.run_ids[-1]).read_all()
        decision = next(e for e in events if e.event_type == "policy.decision")
        self.assertEqual(decision.data["verdict"], "WARN")

    def test_rules_see_the_real_workspace_and_mcp_configs(self):
        seen: list[ActionSnapshot] = []

        def capture(snapshot):
            seen.append(snapshot)
            return RuleOutcome(Verdict.ALLOW, "ok:seen")

        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        engine.execute_task(
            task_id="TASK-POL", objective="Demo", prompt="do it",
            repo_path=self.repo, policy=self._engine_with(capture),
            mcp=McpRunnerConfig(config_paths=("tools/dangerous.json",)),
            policy_actor="agent://worker-a",
            verifier=_PASSING_VERIFIER,
        )
        intent = seen[0].intent
        self.assertTrue(intent.has_flag("--mcp-config"))
        self.assertTrue(any(p.endswith("tools/dangerous.json")
                            for p in intent.resolved_paths))
        self.assertEqual(seen[0].payload["task_id"], "TASK-POL")
        self.assertIn("prompt_sha256", seen[0].payload)

    def test_a_refusal_undoes_the_workspace_it_minted(self):
        # The gate stops the dangerous side effect but used to leave its
        # OWN behind: a DENY still minted `gnosis/<task>` and a worktree
        # (verified before the fix).
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init", "--allow-empty"],
                       cwd=self.repo, check=True, capture_output=True)
        worktrees = WorktreeManager(self.repo, self.root / "worktrees")
        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        engine.execute_task(
            task_id="TASK-POL", objective="Demo", prompt="do it", repo_path=self.repo,
            policy=self._engine_with(lambda s: RuleOutcome(Verdict.DENY, "security:no")),
            worktrees=worktrees, policy_actor="agent://worker-a",
            verifier=_PASSING_VERIFIER,
        )
        self.assertFalse(worktrees.planned_path("TASK-POL").exists())
        branches = subprocess.run(
            ["git", "branch", "--list", "gnosis/TASK-POL"], cwd=self.repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(branches, "")

    def test_a_refusal_never_removes_a_pre_existing_workspace(self):
        # A reattached worktree may hold a previous attempt's work; only a
        # workspace THIS call minted may be undone.
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init", "--allow-empty"],
                       cwd=self.repo, check=True, capture_output=True)
        worktrees = WorktreeManager(self.repo, self.root / "worktrees")
        handle = worktrees.create("TASK-POL")          # pre-existing work
        (Path(handle.path) / "prior_work.txt").write_text("keep me", encoding="utf-8")

        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        engine.execute_task(
            task_id="TASK-POL", objective="Demo", prompt="do it", repo_path=self.repo,
            policy=self._engine_with(lambda s: RuleOutcome(Verdict.DENY, "security:no")),
            worktrees=worktrees, policy_actor="agent://worker-a",
            verifier=_PASSING_VERIFIER,
        )
        self.assertTrue((Path(handle.path) / "prior_work.txt").exists())

    def test_no_child_runs_before_the_verdict_including_code_intelligence(self):
        # ADR-0013's headline invariant was false: code intelligence
        # SHELLS OUT and ran ~120 lines before the gate, so a denied
        # action had already launched kernel subprocesses (adversarial
        # review).
        provider = _FakeCodeIntelligenceProvider()
        runner = _FakeCliRunner(["succeed"])
        engine = TaskEngine(
            run_store=self.store, cli_runner=runner,
            retry_policy=RetryPolicy(max_attempts=1),
        )
        engine.execute_task(
            task_id="TASK-POL", objective="Demo", prompt="do it", repo_path=self.repo,
            policy=self._engine_with(lambda s: RuleOutcome(Verdict.DENY, "security:no")),
            code_intelligence=provider, focus_symbols=["compute"],
            policy_actor="agent://worker-a",
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(runner.calls, 0)
        self.assertEqual(provider.index_calls, [])    # no subprocess at all
        self.assertEqual(provider.explore_calls, [])

    def test_the_final_prompt_is_re_gated_after_context_is_prepended(self):
        # Kernel-generated context derived from the repo is added AFTER
        # the first verdict, so the prompt that runs is re-judged.
        seen: list[str] = []

        def capture(snapshot):
            seen.append(snapshot.payload["stage"])
            return RuleOutcome(Verdict.ALLOW, "ok:seen")

        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        engine.execute_task(
            task_id="TASK-POL", objective="Demo", prompt="do it", repo_path=self.repo,
            policy=self._engine_with(capture),
            code_intelligence=_FakeCodeIntelligenceProvider(), focus_symbols=["compute"],
            policy_actor="agent://worker-a",
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(seen, ["pre_context", "final_prompt"])

    def test_rules_see_the_permission_mode_value_not_just_the_flag_name(self):
        seen: list[ActionSnapshot] = []

        def capture(snapshot):
            seen.append(snapshot)
            return RuleOutcome(Verdict.ALLOW, "ok:seen")

        self._run(self._engine_with(capture))
        intent = seen[0].intent
        # The whole point of gating a launch is knowing whether it runs in
        # `plan` or `bypassPermissions`.
        self.assertEqual(intent.value_for("--permission-mode"), "plan")
        self.assertEqual(intent.cwd, str(self.repo).replace("\\", "/").lower()
                         if str(self.repo)[1:2] == ":" else str(self.repo).replace("\\", "/"))

    def test_mcp_configs_are_bound_by_content_not_only_path(self):
        # An approval must not survive a rewrite of the config file that
        # decides which tools the agent can reach.
        config = self.repo / "tools.json"
        config.write_text('{"mcpServers": {}}', encoding="utf-8")
        seen: list[ActionSnapshot] = []

        def capture(snapshot):
            seen.append(snapshot)
            return RuleOutcome(Verdict.ALLOW, "ok:seen")

        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        def run():
            engine.execute_task(
                task_id="TASK-POL", objective="Demo", prompt="do it", repo_path=self.repo,
                policy=self._engine_with(capture),
                mcp=McpRunnerConfig(config_paths=(str(config),)),
                policy_actor="agent://worker-a",
                verifier=_PASSING_VERIFIER,
            )

        run()
        before = seen[0].action_id()
        config.write_text('{"mcpServers": {"danger": {"command": "sh"}}}', encoding="utf-8")
        run()
        self.assertNotEqual(seen[-1].action_id(), before)

    def test_transform_is_refused_at_this_intervention_point(self):
        # This point cannot rewrite an agent invocation; silently dropping
        # a mitigation it cannot apply is worse than stopping.
        runner = _FakeCliRunner(["succeed"])
        outcome = self._run(
            self._engine_with(lambda s: RuleOutcome(
                Verdict.TRANSFORM, "rewrite:safer", transform={"prompt": "safer"})),
            runner=runner,
        )
        self.assertEqual(runner.calls, 0)
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)

    def test_a_rule_cannot_overwrite_the_kernels_action_id(self):
        # The action_id is the identity an operator approves; rule detail
        # is untrusted data (adversarial review).
        outcome = self._run(self._engine_with(
            lambda s: RuleOutcome(Verdict.DENY, "security:no",
                                  detail={"action_id": "FORGED"})))
        self.assertNotEqual(outcome.classification.detail["action_id"], "FORGED")
        self.assertEqual(len(outcome.classification.detail["action_id"]), 64)

    def test_an_unserializable_rule_detail_still_produces_a_durable_refusal(self):
        # decide() goes to lengths to be total; the refusal path must not
        # then die on the detail it carries.
        outcome = self._run(self._engine_with(
            lambda s: RuleOutcome(Verdict.DENY, "security:no",
                                  detail={"obj": object()})))
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertIn("_unencodable_detail", outcome.classification.detail)

    def test_engine_breakage_and_config_gaps_do_not_penalize_the_agent(self):
        # Rule 7: the kernel's own problems are not the agent's fault.
        broken = self._run(self._engine_with(
            lambda s: (_ for _ in ()).throw(ValueError("rule exploded"))))
        self.assertEqual(broken.classification.failure, FailureClass.FAIL_INFRA)
        self.assertFalse(broken.classification.penalizes_agent)

        gap = self._run(PolicyEngine([]))
        self.assertEqual(gap.classification.failure, FailureClass.NEEDS_HUMAN)
        self.assertFalse(gap.classification.penalizes_agent)

    def test_a_denied_run_never_mints_a_worktree_or_a_branch(self):
        # `git worktree add` is a child process that creates a branch and a
        # directory, and it used to run BEFORE the first verdict — so the
        # unit's headline invariant was false a second time (Codex review).
        worktrees = WorktreeManager(self.repo, self.root / "worktrees")
        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        engine.execute_task(
            task_id="TASK-POL", objective="Demo", prompt="do it", repo_path=self.repo,
            worktrees=worktrees, policy_actor="agent://worker-a",
            policy=self._engine_with(lambda s: RuleOutcome(Verdict.DENY, "security:no")),
            verifier=_PASSING_VERIFIER,
        )
        self.assertFalse(worktrees.exists("TASK-POL"))
        self.assertFalse(worktrees.planned_path("TASK-POL").exists())
        branches = subprocess.run(
            ["git", "branch", "--list", worktrees.planned_branch("TASK-POL")],
            cwd=self.repo, capture_output=True, text=True, check=True,
        ).stdout
        self.assertEqual(branches.strip(), "")

    def test_rules_are_told_where_the_agent_would_run_before_it_exists(self):
        (self.repo / "seed.txt").write_text("seed", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "seed"], cwd=self.repo,
                       check=True, capture_output=True)
        worktrees = WorktreeManager(self.repo, self.root / "worktrees")
        seen: list[ActionSnapshot] = []

        def capture(snapshot):
            seen.append(snapshot)
            return RuleOutcome(Verdict.ALLOW, "ok:seen")

        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        engine.execute_task(
            task_id="TASK-POL", objective="Demo", prompt="do it", repo_path=self.repo,
            worktrees=worktrees, policy=self._engine_with(capture),
            policy_actor="agent://worker-a",
            verifier=_PASSING_VERIFIER,
        )
        planned = str(worktrees.planned_path("TASK-POL"))
        self.assertEqual(seen[0].context["exec_root"], planned)
        self.assertEqual(seen[0].payload["worktree_branch"],
                         worktrees.planned_branch("TASK-POL"))

    def test_every_attempt_is_gated_not_just_the_first(self):
        # Gating once before the retry loop let attempt 2 launch under
        # attempt 1's authorization (Codex review).
        seen: list[str] = []

        def capture(snapshot):
            seen.append(snapshot.payload["stage"])
            return RuleOutcome(Verdict.ALLOW, "ok:seen")

        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["fail", "fail"]),
            retry_policy=_FAST_RETRY,
        )
        engine.execute_task(
            task_id="TASK-POL", objective="Demo", prompt="do it", repo_path=self.repo,
            policy=self._engine_with(capture), policy_actor="agent://worker-a",
            verifier=_PASSING_VERIFIER,
        )
        self.assertIn("attempt_2", seen)

    def test_a_retry_refused_by_policy_stops_and_reports_as_a_refusal(self):
        calls = {"n": 0}

        def deny_after_first(snapshot):
            calls["n"] += 1
            if snapshot.payload["stage"].startswith("attempt_"):
                return RuleOutcome(Verdict.DENY, "security:revoked")
            return RuleOutcome(Verdict.ALLOW, "ok:first")

        runner = _FakeCliRunner(["fail", "fail", "fail"])
        engine = TaskEngine(
            run_store=self.store, cli_runner=runner, retry_policy=_FAST_RETRY,
        )
        outcome = engine.execute_task(
            task_id="TASK-POL", objective="Demo", prompt="do it", repo_path=self.repo,
            policy=self._engine_with(deny_after_first), policy_actor="agent://worker-a",
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(runner.calls, 1)          # attempt 2 never launched
        self.assertEqual(outcome.classification.reason_code, "security:revoked")
        self.assertEqual(outcome.report.status, ReportStatus.ESCALATION_REQUIRED)

    def test_an_mcp_rewrite_between_attempts_is_a_new_decision(self):
        # The approved configuration and the configuration a retry consumes
        # could differ: the CLI re-reads the file (Codex review).
        config = self.repo / "tools.json"
        config.write_text('{"mcpServers": {}}', encoding="utf-8")
        fingerprints: list[object] = []

        def capture(snapshot):
            fingerprints.append(snapshot.payload["mcp"])
            config.write_text('{"mcpServers": {"danger": {}}}', encoding="utf-8")
            return RuleOutcome(Verdict.ALLOW, "ok:seen")

        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["fail", "fail"]),
            retry_policy=_FAST_RETRY,
        )
        engine.execute_task(
            task_id="TASK-POL", objective="Demo", prompt="do it", repo_path=self.repo,
            mcp=McpRunnerConfig(config_paths=(str(config),)),
            policy=self._engine_with(capture), policy_actor="agent://worker-a",
            verifier=_PASSING_VERIFIER,
        )
        self.assertNotEqual(fingerprints[0], fingerprints[-1])

    def test_the_workspace_state_is_part_of_the_action_identity(self):
        # An approval for "run the migration" must not survive HEAD moving
        # underneath it (Codex review).
        ids: list[str] = []

        def capture(snapshot):
            ids.append(snapshot.action_id())
            return RuleOutcome(Verdict.ALLOW, "ok:seen")

        def run_once():
            TaskEngine(
                run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]),
                retry_policy=RetryPolicy(max_attempts=1),
            ).execute_task(
                task_id="TASK-POL", objective="Demo", prompt="do it",
                repo_path=self.repo, policy=self._engine_with(capture),
                policy_actor="agent://worker-a",
                verifier=_PASSING_VERIFIER,
            )

        run_once()
        (self.repo / "moved.txt").write_text("changed", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "move HEAD"], cwd=self.repo,
                       check=True, capture_output=True)
        run_once()
        self.assertNotEqual(ids[0], ids[-1])

    def test_both_gate_verdicts_reach_a_ledger(self):
        # Overwriting a single slot meant the pre-context verdict — what was
        # authorized BEFORE repository-derived context existed — was never
        # auditable (Codex review).
        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        outcome = engine.execute_task(
            task_id="TASK-POL", objective="Demo", prompt="do it", repo_path=self.repo,
            policy=self._engine_with(lambda s: RuleOutcome(Verdict.ALLOW, "ok:seen")),
            code_intelligence=_FakeCodeIntelligenceProvider(), focus_symbols=["compute"],
            policy_actor="agent://worker-a",
            verifier=_PASSING_VERIFIER,
        )
        events = self.store.ledger_for(outcome.run_ids[-1]).read_all()
        decisions = [e for e in events if e.event_type == "policy.decision"]
        self.assertEqual(len(decisions), 2)

    def test_a_rule_detail_whose_repr_raises_still_records_the_refusal(self):
        # `repr()` is arbitrary rule code too, and it sat outside the
        # protective try on the very path that keeps refusals alive.
        class Hostile:
            def __repr__(self):
                raise RuntimeError("no repr for you")

        outcome = self._run(self._engine_with(
            lambda s: RuleOutcome(Verdict.DENY, "security:no", detail={"x": Hostile()})))
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        self.assertIn("_unencodable_detail", outcome.classification.detail)

    def test_an_ungoverned_run_says_so_on_its_own_ledger(self):
        # The gate is opt-in at this milestone, so silence must not be
        # indistinguishable from "nothing was asked" (Codex review).
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-UNGOVERNED", objective="Demo", prompt="do it",
            repo_path=self.repo,
            verifier=_PASSING_VERIFIER,
        )
        events = [e.event_type for e in self.store.ledger_for(outcome.run_ids[-1]).read_all()]
        self.assertIn("policy.ungoverned", events)
        self.assertNotIn("policy.decision", events)

    def test_a_run_without_a_policy_is_unchanged(self):
        # The gate is opt-in at this milestone; ungoverned runs behave
        # exactly as before.
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-FREE", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        events = [e.event_type for e in self.store.ledger_for(outcome.run_ids[-1]).read_all()]
        self.assertNotIn("policy.decision", events)


class _FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _CancellationAwareRunner(_FakeCliRunner):
    """Simulates a long CLI run that honors cooperative cancellation, so
    the pump->token->child chain is actually exercised. Signals `started`
    so tests can schedule a deposition strictly inside the CLI window."""

    def __init__(self, started):
        super().__init__(["succeed"])
        self.observed_cancel = False
        self._started = started

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        self._started.set()
        token = kwargs.get("cancellation_token")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if token is not None and token.is_cancelled():
                self.observed_cancel = True
                break
            time.sleep(0.02)
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("cancelled" if self.observed_cancel else "timeout", encoding="utf-8")
        return ExecutionResult(
            command=("fake-claude",), exit_code=1, timed_out=False,
            cancelled=self.observed_cancel, duration_s=0.1,
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            started_at="t0", ended_at="t1",
        )


class _SlowClockVerifier(Verifier):
    """A verifier whose (fake-clock) duration exceeds the lease TTL,
    advanced in steps with real sleeps in between so the heartbeat pump
    gets the chance a real deployment's wall clock would give it."""

    name = "slow-clock"

    def __init__(self, clock, steps, step_s, sleep_s):
        self._clock = clock
        self._steps = steps
        self._step_s = step_s
        self._sleep_s = sleep_s

    def run(self, cwd):
        for _ in range(self._steps):
            self._clock.advance(self._step_s)
            time.sleep(self._sleep_s)
        return VerificationResult(
            name=self.name, passed=True, exit_code=0, duration_s=0.5,
            stdout_excerpt="", stderr_excerpt="",
        )


class _SignalOnFirstAttemptRunner(_FakeCliRunner):
    """Sets an event when attempt 1 finishes, so a test can schedule a
    deposition deterministically inside the retry backoff window."""

    def __init__(self, outcomes, attempt1_done):
        super().__init__(outcomes)
        self._attempt1_done = attempt1_done

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        result = super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs)
        if self.calls == 1:
            self._attempt1_done.set()
        return result


class _DeposingCliRunner(_FakeCliRunner):
    """Succeeds, but simulates a deposition during the CLI window: the
    lease TTL elapses, the sweep reclaims the claim, and another worker
    takes the task over — all while this 'CLI run' is still executing."""

    def __init__(self, authority, clock, ttl_s):
        super().__init__(["succeed"])
        self.authority = authority
        self.clock = clock
        self.ttl_s = ttl_s

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        self.clock.advance(self.ttl_s + 1)
        self.authority.sweep()
        self.authority.acquire("TASK-AUTH", "worker-b")
        return super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs)


class TestTaskEngineWorkAuthority(unittest.TestCase):
    """Directive 4 part two: the engine's durable write paths are fenced
    by the two-plane WorkAuthority (ADR-0006)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        self.store = RunStore(self.root / "runs")
        self.clock = _FakeClock()
        self.claims = ClaimStore(self.root / "claims.json", clock=self.clock)
        self.leases = LeaseStore(self.root / "leases.json", clock=self.clock)
        self.authority = WorkAuthority(
            self.claims, self.leases, default_ttl_s=60,
            reclaim_grace_s=30, clock=self.clock,
        )
        # Authority-governed runs now REQUIRE a verifier (no DONE without
        # evidence — Codex review); tests that reach resolve use this one.
        self.passing_verifier = CommandVerifier(
            "noop-pass", [sys.executable, "-c", "import sys; sys.exit(0)"],
        )

    def _depose_via_rival(self):
        """Expire worker-a's lease, sweep, and hand the task to worker-b."""
        self.clock.advance(61)
        self.authority.sweep()
        self.authority.acquire("TASK-AUTH", "worker-b")

    def tearDown(self):
        self.tmp.cleanup()

    def test_completed_task_resolves_claim_and_releases_lease(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-AUTH", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=self.passing_verifier,
            authority=self.authority, worker_id="worker-a",
        )
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        claim = self.claims.get("TASK-AUTH")
        self.assertEqual(claim.status, ClaimStatus.RESOLVED)
        self.assertEqual(claim.outcome, "COMPLETED")
        self.assertIsNone(self.leases.current("task/TASK-AUTH"))

    def test_verifier_required_with_authority(self):
        # No DONE without evidence: a run without a verifier is refused at
        # entry (Codex review, INVALID DONE). The refusal used to be
        # conditional on `authority is not None`, which made the rule a
        # property of governed runs rather than of the engine (F-34) — it
        # is now unconditional, and this test keeps the governed half of
        # the guarantee pinned: refused BEFORE the claims plane is
        # touched, so nothing has to be recovered.
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        with self.assertRaises(ValueError):
            engine.execute_task(
                task_id="TASK-AUTH", objective="Demo", prompt="do it",
                repo_path=self.repo, authority=self.authority, worker_id="worker-a",
                verifier=None,
            )
        self.assertIsNone(self.claims.get("TASK-AUTH"))  # nothing was claimed
        self.assertIsNone(self.leases.current("task/TASK-AUTH"))  # and no lease

    def test_worker_id_required_with_authority(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        with self.assertRaises(ValueError):
            engine.execute_task(
                task_id="TASK-AUTH", objective="Demo", prompt="do it",
                repo_path=self.repo, verifier=self.passing_verifier,
                authority=self.authority,
            )

    def test_deposed_worker_aborts_without_writing_final_state(self):
        runner = _DeposingCliRunner(self.authority, self.clock, ttl_s=60)
        engine = TaskEngine(run_store=self.store, cli_runner=runner)
        with self.assertRaises((StaleLeaseError, StaleClaimError)):
            engine.execute_task(
                task_id="TASK-AUTH", objective="Demo", prompt="do it",
                repo_path=self.repo, verifier=self.passing_verifier,
                authority=self.authority, worker_id="worker-a",
            )
        # NO STALE WRITE: the deposed attempt never recorded its outcome —
        # the run's durable state still says RUNNING and the ledger stops
        # at attempt_started.
        run_ids = self.store.list_run_ids()
        self.assertEqual(len(run_ids), 1)
        self.assertEqual(self.store.read_meta(run_ids[0]).state, "RUNNING")
        events = self.store.ledger_for(run_ids[0]).read_all()
        self.assertEqual(events[-1].event_type, "run.attempt_started")
        # The task now belongs to worker-b at a strictly greater epoch.
        claim = self.claims.get("TASK-AUTH")
        self.assertEqual(claim.holder, "worker-b")
        self.assertEqual(claim.status, ClaimStatus.ACTIVE)

    def test_pump_detects_mid_run_deposition_and_cancels_child(self):
        # Pins the whole heartbeat-pump chain (adversarial-review finding:
        # previously untested): rival takeover mid-run -> pump renewal
        # fails -> child cancelled cooperatively -> typed abort with no
        # final state written.
        started = threading.Event()
        runner = _CancellationAwareRunner(started)
        engine = TaskEngine(run_store=self.store, cli_runner=runner)

        def depose_inside_cli_window():
            started.wait(timeout=10)
            self._depose_via_rival()

        deposer = threading.Thread(target=depose_inside_cli_window)
        deposer.start()
        try:
            with self.assertRaises((StaleLeaseError, StaleClaimError)):
                engine.execute_task(
                    task_id="TASK-AUTH", objective="Demo", prompt="do it",
                    repo_path=self.repo, verifier=self.passing_verifier,
                    authority=self.authority,
                    worker_id="worker-a", lease_heartbeat_interval_s=0.05,
                )
        finally:
            deposer.join()
        self.assertTrue(runner.observed_cancel)  # child was not leaked
        run_ids = self.store.list_run_ids()
        self.assertEqual(len(run_ids), 1)
        self.assertEqual(self.store.read_meta(run_ids[0]).state, "RUNNING")

    def test_attempt_entry_guard_blocks_deposed_retry(self):
        # Pins the attempt-entry guard specifically (adversarial-review
        # finding: only the post-run guard was load-bearing): deposition
        # lands during the retry backoff, so attempt 2 must be refused
        # BEFORE it creates a second run.
        attempt1_done = threading.Event()
        engine = TaskEngine(
            run_store=self.store,
            cli_runner=_SignalOnFirstAttemptRunner(["fail", "succeed"], attempt1_done),
            retry_policy=RetryPolicy(max_attempts=2, backoff_base_s=0.8,
                                     backoff_factor=1.0, max_backoff_s=0.8),
        )

        def depose_during_backoff():
            attempt1_done.wait(timeout=10)
            time.sleep(0.2)  # attempt 1's post-run guard has passed by now
            self._depose_via_rival()

        deposer = threading.Thread(target=depose_during_backoff)
        deposer.start()
        try:
            with self.assertRaises((StaleLeaseError, StaleClaimError)):
                engine.execute_task(
                    task_id="TASK-AUTH", objective="Demo", prompt="do it",
                    repo_path=self.repo, verifier=self.passing_verifier,
                    authority=self.authority,
                    worker_id="worker-a", lease_heartbeat_interval_s=0.05,
                )
        finally:
            deposer.join()
        # Attempt 1 ran; the deposed worker never opened a second run.
        self.assertEqual(len(self.store.list_run_ids()), 1)

    def test_slow_verifier_survives_via_pump(self):
        # Adversarial-review major finding on the first version: a verifier
        # outliving the lease TTL self-deposed a healthy worker after
        # verified success. The pump must keep the lease alive through
        # verification so resolve() lands.
        verifier = _SlowClockVerifier(self.clock, steps=12, step_s=15, sleep_s=0.1)
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-AUTH", objective="Demo", prompt="do it",
            repo_path=self.repo, verifier=verifier,
            authority=self.authority, worker_id="worker-a",
            lease_ttl_s=120, lease_heartbeat_interval_s=0.05,
        )
        # 180 fake-seconds elapsed against a 120s TTL (which renewals must
        # honor — the grant's own TTL, not the 60s facade default), and the
        # task still completed and resolved: no self-deposition.
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        self.assertEqual(self.claims.get("TASK-AUTH").status, ClaimStatus.RESOLVED)

    def test_failed_task_keeps_claim_active_until_swept(self):
        engine = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["fail"]),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        outcome = engine.execute_task(
            task_id="TASK-AUTH", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=self.passing_verifier,
            authority=self.authority, worker_id="worker-a",
        )
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        # Failure does not silently release ownership (grit's lesson):
        claim = self.claims.get("TASK-AUTH")
        self.assertEqual(claim.status, ClaimStatus.ACTIVE)
        # ...the lease expires instead, and the sweep reclaims audibly.
        self.clock.advance(61)
        reclaimed = self.authority.sweep()
        self.assertEqual([c.task_id for c in reclaimed], ["TASK-AUTH"])
        self.assertEqual(self.claims.get("TASK-AUTH").status, ClaimStatus.RECLAIMED)


class _WorkspaceWritingRunner(_FakeCliRunner):
    """Writes an artifact into its cwd, like a real repo-mutating agent."""

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        (Path(cwd) / "agent_artifact.txt").write_text("wrote", encoding="utf-8")
        return super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs)


class _WritingThenDeposedRunner(_WorkspaceWritingRunner):
    """Writes into cwd, then gets deposed while still 'running'."""

    def __init__(self, depose):
        super().__init__(["succeed"])
        self._depose = depose

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        result = super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs)
        self._depose()
        return result


class TestGuardedRunStore(unittest.TestCase):
    """The store-boundary enforcement (ADR-0006 follow-up): every durable
    write re-proves ownership; a forgotten guard() call cannot stale-write."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = RunStore(Path(self.tmp.name) / "runs")

    def tearDown(self):
        self.tmp.cleanup()

    def test_failing_guard_blocks_every_durable_write(self):
        from gnosis.kernel.engine import _GuardedRunStore

        def deposed_guard() -> None:
            raise StaleLeaseError("deposed")

        self.raw.create_run("RUN-X", "TASK-X")  # pre-existing state to write to
        guarded = _GuardedRunStore(self.raw, deposed_guard)
        with self.assertRaises(StaleLeaseError):
            guarded.create_run("RUN-Y", "TASK-X")
        with self.assertRaises(StaleLeaseError):
            guarded.update_state("RUN-X", RunState.RUNNING)
        with self.assertRaises(StaleLeaseError):
            guarded.heartbeat("RUN-X")
        with self.assertRaises(StaleLeaseError):
            guarded.ledger_for("RUN-X").append("RUN-X", "evil.write", {})
        # Reads stay open: evidence inspection is never fenced.
        self.assertTrue(guarded.paths_for("RUN-X").root.exists())
        self.assertEqual(guarded.ledger_for("RUN-X").read_all(), [])

    def test_passing_guard_delegates(self):
        from gnosis.kernel.engine import _GuardedRunStore

        guarded = _GuardedRunStore(self.raw, lambda: None)
        guarded.create_run("RUN-OK", "TASK-OK")
        guarded.update_state("RUN-OK", RunState.RUNNING)
        guarded.ledger_for("RUN-OK").append("RUN-OK", "run.progress", {})
        self.assertEqual(self.raw.read_meta("RUN-OK").state, "RUNNING")


class TestTaskEngineWorktreeIsolation(unittest.TestCase):
    """ADR-0006 + ADR-0007 composition: the repository-writing child runs
    inside the task's kernel-minted worktree, never the shared repo."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        (self.repo / "README.md").write_text("root\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.repo,
                       check=True, capture_output=True)
        self.store = RunStore(self.root / "runs")
        self.clock = _FakeClock()
        self.claims = ClaimStore(self.root / "claims.json", clock=self.clock)
        self.leases = LeaseStore(self.root / "leases.json", clock=self.clock)
        self.authority = WorkAuthority(
            self.claims, self.leases, default_ttl_s=60,
            reclaim_grace_s=30, clock=self.clock,
        )
        self.worktrees = WorktreeManager(self.repo, self.root / "worktrees")
        self.passing_verifier = CommandVerifier(
            "noop-pass", [sys.executable, "-c", "import sys; sys.exit(0)"],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _repo_is_pristine(self) -> bool:
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=self.repo,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return status == "" and not (self.repo / "agent_artifact.txt").exists()

    def test_governed_run_executes_inside_task_worktree(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_WorkspaceWritingRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-ISO", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=self.passing_verifier, authority=self.authority,
            worker_id="worker-a", worktrees=self.worktrees,
        )
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        handle = self.worktrees.load_handle("TASK-ISO")
        self.assertTrue((Path(handle.path) / "agent_artifact.txt").exists())
        self.assertTrue(self._repo_is_pristine())
        self.assertEqual(self.claims.get("TASK-ISO").status, ClaimStatus.RESOLVED)
        # The worktree is recorded as run evidence.
        events = self.store.ledger_for(outcome.run_ids[0]).read_all()
        started = next(e for e in events if e.event_type == "run.attempt_started")
        self.assertEqual(started.data["worktree"], handle.to_dict())

    def test_deposed_child_cannot_touch_shared_repo(self):
        def depose():
            self.clock.advance(61)
            self.authority.sweep()
            self.authority.acquire("TASK-ISO", "worker-b")

        engine = TaskEngine(run_store=self.store, cli_runner=_WritingThenDeposedRunner(depose))
        with self.assertRaises((StaleLeaseError, StaleClaimError)):
            engine.execute_task(
                task_id="TASK-ISO", objective="Demo", prompt="do it", repo_path=self.repo,
                verifier=self.passing_verifier, authority=self.authority,
                worker_id="worker-a", worktrees=self.worktrees,
            )
        # The deposed child's writes landed in the isolated worktree only.
        handle = self.worktrees.load_handle("TASK-ISO")
        self.assertTrue((Path(handle.path) / "agent_artifact.txt").exists())
        self.assertTrue(self._repo_is_pristine())

    def test_isolation_works_without_authority_too(self):
        engine = TaskEngine(run_store=self.store, cli_runner=_WorkspaceWritingRunner(["succeed"]))
        outcome = engine.execute_task(
            task_id="TASK-FREE", objective="Demo", prompt="do it", repo_path=self.repo,
            worktrees=self.worktrees,
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        handle = self.worktrees.load_handle("TASK-FREE")
        self.assertTrue((Path(handle.path) / "agent_artifact.txt").exists())
        self.assertTrue(self._repo_is_pristine())

    def test_verification_runs_inside_the_worktree_not_the_shared_repo(self):
        # Verification is the DONE gate: validating the pristine shared
        # repo instead of the worktree the agent wrote in would be an
        # INVALID DONE (adversarial review: the cwd was unpinned).
        verifier = _CwdRecordingVerifier()
        engine = TaskEngine(run_store=self.store, cli_runner=_WorkspaceWritingRunner(["succeed"]))
        engine.execute_task(
            task_id="TASK-ISO", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=verifier, authority=self.authority,
            worker_id="worker-a", worktrees=self.worktrees,
        )
        handle = self.worktrees.load_handle("TASK-ISO")
        self.assertEqual(verifier.cwds, [Path(handle.path)])
        self.assertNotEqual(verifier.cwds[0].resolve(), self.repo.resolve())

    def test_worktree_manager_repo_mismatch_is_refused(self):
        other = self.root / "other_repo"
        other.mkdir()
        subprocess.run(["git", "init"], cwd=other, check=True, capture_output=True)
        mismatched = WorktreeManager(other, self.root / "worktrees-other")
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        with self.assertRaises(ValueError):
            engine.execute_task(
                task_id="TASK-MISMATCH", objective="Demo", prompt="do it",
                repo_path=self.repo, verifier=self.passing_verifier,
                authority=self.authority, worker_id="worker-a", worktrees=mismatched,
            )
        # Nothing was executed against the wrong repository.
        self.assertEqual(self.store.list_run_ids(), [])

    def test_worktree_creation_failure_does_not_leak_the_pump(self):
        # Reported independently by four reviewers: a create() failure
        # outside the try/finally left the daemon pump renewing a dead
        # worker's lease forever, making the task unreclaimable.
        poisoned = self.root / "worktrees" / "TASK-POISON"
        poisoned.mkdir(parents=True)
        (poisoned / "squatter.txt").write_text("unregistered", encoding="utf-8")
        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        with self.assertRaises(WorktreeError):
            engine.execute_task(
                task_id="TASK-POISON", objective="Demo", prompt="do it",
                repo_path=self.repo, verifier=self.passing_verifier,
                authority=self.authority, worker_id="worker-a", worktrees=self.worktrees,
                lease_heartbeat_interval_s=0.05,
            )
        # The lease must now expire on schedule and the sweep must be able
        # to reclaim the claim: no surviving pump keeps renewing it.
        time.sleep(0.2)  # a leaked pump would have renewed by now
        self.clock.advance(61)
        reclaimed = self.authority.sweep()
        self.assertEqual([c.task_id for c in reclaimed], ["TASK-POISON"])

    def test_heartbeat_callback_never_escapes_into_the_runner_loop(self):
        # A deposition surfaces as cooperative cancellation; any other
        # heartbeat failure is swallowed. Either way the callback must not
        # raise inside the runner's poll loop (which would leak the child).
        runner = _HeartbeatingRunner(beats=4)
        engine = TaskEngine(run_store=self.store, cli_runner=runner)

        original_heartbeat = self.store.heartbeat
        calls = {"n": 0}

        def flaky_heartbeat(run_id, fingerprint=None):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("transient sharing violation")
            original_heartbeat(run_id, fingerprint)

        self.store.heartbeat = flaky_heartbeat  # type: ignore[method-assign]
        try:
            outcome = engine.execute_task(
                task_id="TASK-ISO", objective="Demo", prompt="do it", repo_path=self.repo,
                verifier=self.passing_verifier, authority=self.authority,
                worker_id="worker-a", worktrees=self.worktrees,
            )
        finally:
            self.store.heartbeat = original_heartbeat  # type: ignore[method-assign]
        # The transient failure did not kill a healthy run.
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        self.assertGreaterEqual(calls["n"], 2)

    def test_deposition_during_verification_is_blocked_at_the_store_boundary(self):
        # Proves the engine actually ROUTES writes through the guarded
        # store: the verification-result ledger append happens after the
        # last explicit guard(), so only the boundary can stop it.
        class _DeposingVerifier(Verifier):
            name = "deposing"

            def __init__(self, depose):
                self._depose = depose

            def run(self, cwd):
                self._depose()
                return VerificationResult(
                    name=self.name, passed=True, exit_code=0, duration_s=0.01,
                    stdout_excerpt="", stderr_excerpt="",
                )

        def depose():
            self.clock.advance(61)
            self.authority.sweep()
            self.authority.acquire("TASK-ISO", "worker-b")

        engine = TaskEngine(run_store=self.store, cli_runner=_FakeCliRunner(["succeed"]))
        with self.assertRaises((StaleLeaseError, StaleClaimError)):
            engine.execute_task(
                task_id="TASK-ISO", objective="Demo", prompt="do it", repo_path=self.repo,
                verifier=_DeposingVerifier(depose), authority=self.authority,
                worker_id="worker-a", worktrees=self.worktrees,
            )
        # NO INVALID DONE: the deposed worker never resolved the claim.
        self.assertEqual(self.claims.get("TASK-ISO").holder, "worker-b")
        self.assertEqual(self.claims.get("TASK-ISO").status, ClaimStatus.ACTIVE)

    def test_failed_run_keeps_worktree_and_retry_reattaches_it(self):
        failing = TaskEngine(
            run_store=self.store, cli_runner=_FakeCliRunner(["fail"]),
            retry_policy=RetryPolicy(max_attempts=1),
        )
        outcome = failing.execute_task(
            task_id="TASK-ISO", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=self.passing_verifier, authority=self.authority,
            worker_id="worker-a", worktrees=self.worktrees,
        )
        self.assertEqual(outcome.final_task_state, TaskState.FAILED)
        first_handle = self.worktrees.load_handle("TASK-ISO")
        self.assertTrue(Path(first_handle.path).exists())

        # Same worker retries (its lease is still live): the claim retry is
        # idempotent and the worktree is reattached, not recreated. The
        # marker alone proves nothing (create()'s idempotent path never
        # rewrites it), so pin where execution ACTUALLY happened.
        verifier = _CwdRecordingVerifier()
        retry = TaskEngine(run_store=self.store, cli_runner=_WorkspaceWritingRunner(["succeed"]))
        outcome2 = retry.execute_task(
            task_id="TASK-ISO", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=verifier, authority=self.authority,
            worker_id="worker-a", worktrees=self.worktrees,
        )
        self.assertEqual(outcome2.final_task_state, TaskState.COMPLETED)
        self.assertEqual(self.worktrees.load_handle("TASK-ISO"), first_handle)
        self.assertEqual(verifier.cwds, [Path(first_handle.path)])  # reattached, not shared repo
        self.assertTrue((Path(first_handle.path) / "agent_artifact.txt").exists())
        self.assertEqual(self.claims.get("TASK-ISO").status, ClaimStatus.RESOLVED)


class _CwdRecordingVerifier(Verifier):
    """Records the directory it was actually run in, so a verifier
    silently validating the pristine shared repo cannot pass unnoticed."""

    name = "cwd-recording"

    def __init__(self):
        self.cwds: list[Path] = []

    def run(self, cwd):
        self.cwds.append(Path(cwd))
        return VerificationResult(
            name=self.name, passed=True, exit_code=0, duration_s=0.01,
            stdout_excerpt="", stderr_excerpt="",
        )


class _HeartbeatingRunner(_FakeCliRunner):
    """Actually invokes heartbeat_fn like the real CLIRunner does, so the
    engine's liveness callback has execution coverage."""

    def __init__(self, beats=3, outcomes=("succeed",)):
        super().__init__(list(outcomes))
        self.beats = beats
        self.observed_cancel = False

    def run(self, prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs):
        heartbeat_fn = kwargs.get("heartbeat_fn")
        token = kwargs.get("cancellation_token")
        for _ in range(self.beats):
            if heartbeat_fn is not None:
                heartbeat_fn(4242)  # must never raise into the poll loop
            if token is not None and token.is_cancelled():
                self.observed_cancel = True
                break
            time.sleep(0.02)
        return super().run(prompt, cwd, stdout_path, stderr_path, timeout_s, **kwargs)


class _FakeCodeIntelligenceProvider(CodeIntelligenceProvider):
    """Deterministic test double -- never shells out to a real tool, so
    TaskEngine's code-intelligence integration is testable without the
    M2.1 lab install present."""

    def __init__(self, available=True, stale=False, fail_symbols=()):
        self.available = available
        self.stale = stale
        self.fail_symbols = set(fail_symbols)
        self.index_calls = []
        self.explore_calls = []

    def index(self, repo_path, full=False):
        self.index_calls.append((repo_path, full))
        if not self.available:
            raise CodeIntelligenceUnavailable("fake: provider unavailable")

    def status(self):
        if not self.available:
            raise CodeIntelligenceUnavailable("fake: provider unavailable")
        return IndexStatus(available=True, files_indexed=5, nodes=10, edges=8, stale=self.stale)

    def find(self, query):
        raise CodeIntelligenceUnavailable("fake: not implemented")

    def callers(self, symbol):
        raise CodeIntelligenceUnavailable("fake: not implemented")

    def callees(self, symbol):
        raise CodeIntelligenceUnavailable("fake: not implemented")

    def impact(self, symbol):
        raise CodeIntelligenceUnavailable("fake: not implemented")

    def explore(self, query):
        self.explore_calls.append(query)
        if not self.available or query in self.fail_symbols:
            raise CodeIntelligenceUnavailable(f"fake: explore failed for {query}")
        return CompactContext(query=query, text=f"relevant context for {query}", related_symbols=(query,))


class TestTaskEngineCodeIntelligence(unittest.TestCase):
    """M2.5 section 6: provider available, provider unavailable, stale
    index, provider failure without run-state corruption, evidence
    recording, TaskEngine context retrieval."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "e@x.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=self.repo, check=True)
        self.store = RunStore(self.root / "runs")

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_context_gathered_when_not_configured(self):
        cli = _FakeCliRunner(["succeed"])
        engine = TaskEngine(run_store=self.store, cli_runner=cli)
        outcome = engine.execute_task(
            task_id="TASK-CI-0", objective="Demo", prompt="do it", repo_path=self.repo,
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(cli.prompts_seen, ["do it"])
        events = self.store.ledger_for(outcome.run_ids[-1]).read_all()
        self.assertFalse(any(e.event_type == "code_intelligence.context_gathered" for e in events))

    def test_provider_available_context_prepended_to_prompt(self):
        cli = _FakeCliRunner(["succeed"])
        provider = _FakeCodeIntelligenceProvider(available=True)
        engine = TaskEngine(run_store=self.store, cli_runner=cli)
        engine.execute_task(
            task_id="TASK-CI-1", objective="Demo", prompt="do it", repo_path=self.repo,
            code_intelligence=provider, focus_symbols=["entrypoint"],
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(len(cli.prompts_seen), 1)
        self.assertIn("relevant context for entrypoint", cli.prompts_seen[0])
        self.assertIn("do it", cli.prompts_seen[0])
        self.assertEqual(provider.explore_calls, ["entrypoint"])

    def test_evidence_recorded_in_ledger_and_run_dir(self):
        cli = _FakeCliRunner(["succeed"])
        provider = _FakeCodeIntelligenceProvider(available=True)
        engine = TaskEngine(run_store=self.store, cli_runner=cli)
        outcome = engine.execute_task(
            task_id="TASK-CI-2", objective="Demo", prompt="do it", repo_path=self.repo,
            code_intelligence=provider, focus_symbols=["entrypoint", "helper"],
            verifier=_PASSING_VERIFIER,
        )
        run_id = outcome.run_ids[-1]
        events = self.store.ledger_for(run_id).read_all()
        gathered = next(e for e in events if e.event_type == "code_intelligence.context_gathered")
        self.assertEqual(gathered.data["provider"], "_FakeCodeIntelligenceProvider")
        symbols_queried = {q["symbol"] for q in gathered.data["queries"] if q.get("op") == "explore"}
        self.assertEqual(symbols_queried, {"entrypoint", "helper"})

        evidence_path = self.store.paths_for(run_id).root / "code_intelligence.json"
        self.assertTrue(evidence_path.exists())

        started = next(e for e in events if e.event_type == "run.attempt_started")
        self.assertTrue(started.data["code_intelligence_used"])

    def test_provider_unavailable_does_not_block_or_corrupt_run(self):
        cli = _FakeCliRunner(["succeed"])
        provider = _FakeCodeIntelligenceProvider(available=False)
        engine = TaskEngine(run_store=self.store, cli_runner=cli)
        outcome = engine.execute_task(
            task_id="TASK-CI-3", objective="Demo", prompt="do it", repo_path=self.repo,
            code_intelligence=provider, focus_symbols=["entrypoint"],
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(outcome.final_task_state, TaskState.COMPLETED)
        self.assertEqual(cli.prompts_seen, ["do it"])  # no context to prepend, provider was down
        run_id = outcome.run_ids[-1]
        self.assertEqual(self.store.read_meta(run_id).state, RunState.SUCCEEDED.value)
        events = self.store.ledger_for(run_id).read_all()
        gathered = next(e for e in events if e.event_type == "code_intelligence.context_gathered")
        self.assertFalse(gathered.data["queries"][-1]["success"])

    def test_partial_symbol_failure_still_includes_successful_ones(self):
        cli = _FakeCliRunner(["succeed"])
        provider = _FakeCodeIntelligenceProvider(available=True, fail_symbols={"broken_symbol"})
        engine = TaskEngine(run_store=self.store, cli_runner=cli)
        engine.execute_task(
            task_id="TASK-CI-4", objective="Demo", prompt="do it", repo_path=self.repo,
            code_intelligence=provider, focus_symbols=["entrypoint", "broken_symbol"],
            verifier=_PASSING_VERIFIER,
        )
        self.assertIn("relevant context for entrypoint", cli.prompts_seen[0])
        self.assertNotIn("relevant context for broken_symbol", cli.prompts_seen[0])

    def test_stale_index_note_included_in_context(self):
        cli = _FakeCliRunner(["succeed"])
        provider = _FakeCodeIntelligenceProvider(available=True, stale=True)
        engine = TaskEngine(run_store=self.store, cli_runner=cli)
        engine.execute_task(
            task_id="TASK-CI-5", objective="Demo", prompt="do it", repo_path=self.repo,
            code_intelligence=provider, focus_symbols=["entrypoint"],
            verifier=_PASSING_VERIFIER,
        )
        self.assertIn("may be stale", cli.prompts_seen[0])

    def test_context_gathered_once_not_duplicated_across_retries(self):
        cli = _FakeCliRunner(["fail", "fail", "succeed"])
        provider = _FakeCodeIntelligenceProvider(available=True)
        engine = TaskEngine(
            run_store=self.store, cli_runner=cli, retry_policy=_FAST_RETRY,
        )
        outcome = engine.execute_task(
            task_id="TASK-CI-6", objective="Demo", prompt="do it", repo_path=self.repo,
            code_intelligence=provider, focus_symbols=["entrypoint"],
            verifier=_PASSING_VERIFIER,
        )
        self.assertEqual(len(outcome.run_ids), 3)
        self.assertEqual(provider.explore_calls, ["entrypoint"])  # gathered once, not per retry
        first_run_events = self.store.ledger_for(outcome.run_ids[0]).read_all()
        self.assertTrue(any(e.event_type == "code_intelligence.context_gathered" for e in first_run_events))
        for run_id in outcome.run_ids[1:]:
            later_events = self.store.ledger_for(run_id).read_all()
            self.assertFalse(any(e.event_type == "code_intelligence.context_gathered" for e in later_events))

    def test_max_context_chars_bounds_included_text(self):
        cli = _FakeCliRunner(["succeed"])
        provider = _FakeCodeIntelligenceProvider(available=True)
        engine = TaskEngine(run_store=self.store, cli_runner=cli)
        outcome = engine.execute_task(
            task_id="TASK-CI-7", objective="Demo", prompt="do it", repo_path=self.repo,
            code_intelligence=provider, focus_symbols=["entrypoint"], max_context_chars=5,
            verifier=_PASSING_VERIFIER,
        )
        run_id = outcome.run_ids[-1]
        events = self.store.ledger_for(run_id).read_all()
        gathered = next(e for e in events if e.event_type == "code_intelligence.context_gathered")
        self.assertLessEqual(gathered.data["context_included_chars"], 5)


if __name__ == "__main__":
    unittest.main()
