"""Bootstrap task engine.

Wires together the M0 primitives, state machines, run store, the Claude
Code CLI runner, retry policy, deterministic verification, git evidence,
and redaction, into a single-task execution lifecycle. This is
intentionally the thinnest glue that proves the primitives compose; a real
multi-task orchestrator (scheduling, worktrees, councils, Night Cycle) is
future work with its own extension point here.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..contracts.engineer_report import EngineerReport, ReportStatus
from ..runner.capture import ExecutionResult
from ..runner.claude_cli_runner import CancellationToken, ClaudeCodeCLIRunner, McpRunnerConfig
from ..runner.retry import RetryPolicy, execute_with_retry
from .canonical import hash_canonical
from .claims import GrantHeartbeatPump, StaleClaimError, WorkAuthority, WorkGrant
from .code_intelligence import CodeIntelligenceProvider, CodeIntelligenceUnavailable
from .failures import (
    DEFAULT_CHAIN,
    EvidenceGrade,
    FailureClass,
    FailureClassification,
    FailureClassifierChain,
    FailureSignal,
    SchedulerAction,
    scheduler_action,
)
from .git_evidence import capture_git_evidence
from .ids import new_run_id
from .lease import StaleLeaseError
from .ledger import LedgerEvent, RunLedger
from .policy import (
    ActionSnapshot,
    ApprovalStore,
    CommandIntent,
    PolicyDecision,
    PolicyEngine,
    Verdict,
    parse_command,
    resolve_escalation,
)
from .redaction import redact
from .run_store import RunMeta, RunPaths, RunStore
from .state_machine import RunState, TaskState, TaskStateMachine
from .verification import VerificationResult, Verifier
from .worktree import WorktreeError, WorktreeHandle, WorktreeManager

AGENT_RUN_INTERVENTION_POINT = "before_agent_run"
# The mode the CLI runner actually defaults to. Stated as a constant so
# the value the rules are shown cannot drift from the value used.
DEFAULT_PERMISSION_MODE = "plan"


@dataclass(frozen=True)
class _GateResult:
    decision: PolicyDecision | None
    outcome: TaskExecutionOutcome | None


def _safe_detail(detail: Mapping[str, Any]) -> dict[str, Any]:
    """Rule-supplied detail, guaranteed to survive canonical JSON.

    `PolicyEngine.decide` goes to explicit lengths to be total, but the
    detail it carries is arbitrary rule data validated only as a dict —
    and an unserializable value turned a refusal into an unhandled
    TypeError with no durable record (adversarial review). A refusal must
    always be recordable.
    """
    try:
        hash_canonical(dict(detail))
    except (TypeError, ValueError):
        return {"_unencodable_detail": repr(dict(detail))[:2000]}
    return dict(detail)


def _safe_decision(decision: PolicyDecision) -> dict[str, Any]:
    payload = decision.to_dict()
    payload["detail"] = _safe_detail(decision.detail)
    if payload.get("transform") is not None:
        payload["transform"] = _safe_detail(payload["transform"])
    return payload


def _runner_binary(runner: Any) -> str:
    """The program the rules are told about.

    Inventing a name for a runner that does not expose one would show
    rules a program that is not the one that runs (adversarial review);
    an unknown binary is reported as unknown."""
    binary = getattr(runner, "binary", None)
    return binary if isinstance(binary, str) and binary else "<unknown-runner>"


def _mcp_fingerprint(mcp: McpRunnerConfig | None, exec_root: Path) -> dict[str, Any] | None:
    """Path AND content hash for every MCP config.

    An MCP config decides which tools the agent can reach, and the file's
    CONTENTS decide that, not its name — binding only the path let an
    approval survive a rewrite of the file it approved (adversarial
    review). Unreadable files are recorded as such rather than skipped:
    a config the kernel cannot read is not a config it may vouch for.
    """
    if mcp is None:
        return None
    fingerprints: list[dict[str, Any]] = []
    for raw_path in mcp.config_paths:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = exec_root / candidate
        try:
            fingerprints.append({
                "path": str(raw_path),
                "sha256": hash_canonical(candidate.read_text(encoding="utf-8")),
            })
        except OSError as exc:
            fingerprints.append({"path": str(raw_path), "unreadable": str(exc)})
    return {"configs": fingerprints, "strict": mcp.strict}


def agent_run_intent(binary: str, exec_root: Path, permission_mode: str,
                     model: str | None = None,
                     mcp: McpRunnerConfig | None = None) -> CommandIntent:
    """The structured intent of launching an agent, for policy rules.

    Built explicitly rather than by parsing the CLI argv: the prompt is
    an argv operand, and feeding a whole prompt through the path resolver
    would produce nonsense paths and an unbounded snapshot. The prompt is
    identified by hash in the snapshot payload instead — which still binds
    an approval to the exact prompt without inlining it.
    """
    # Flag VALUES, not bare names: `--permission-mode` alone tells a rule
    # nothing, and the whole point of gating an agent launch is knowing
    # whether it runs in `plan` or `bypassPermissions` (adversarial
    # review — the value was silently discarded).
    flags = [f"--permission-mode={permission_mode}", "--output-format=json"]
    if model:
        flags.append(f"--model={model}")
    if mcp is not None:
        flags.append("--mcp-config")
        if mcp.strict:
            flags.append("--strict-mcp-config")
    # The MCP config paths ARE operands worth gating: they decide which
    # tools the agent can reach.
    operands = list(mcp.config_paths) if mcp is not None else []
    return parse_command([binary, *flags, *operands], cwd=exec_root)


def _report_status(task_state: TaskState,
                   classifications: Sequence[FailureClassification]) -> ReportStatus:
    """Give an escalation its own channel.

    `should_retry` collapses ESCALATE, FAIL and PARK into "stop
    retrying", so without this an escalation was filed as a routine
    PARTIAL and nothing downstream could tell a security refusal or an
    unclassifiable failure from an ordinary miss — even though
    ESCALATION_REQUIRED already existed (adversarial review).
    """
    if task_state == TaskState.COMPLETED:
        return ReportStatus.COMPLETED
    if classifications and scheduler_action(classifications[-1]) is SchedulerAction.ESCALATE:
        return ReportStatus.ESCALATION_REQUIRED
    return ReportStatus.PARTIAL


def _tail(path: Path, limit: int = 4000) -> str:
    """Last bytes of a captured stream, for prose-grade classification."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def _gather_code_intelligence_context(
    provider: CodeIntelligenceProvider,
    repo_path: Path,
    focus_symbols: Sequence[str],
    max_context_chars: int,
) -> tuple[str, dict[str, Any]]:
    """Best-effort structural context gathering for `focus_symbols`, run
    once before the CLI attempt loop. Never raises: any provider failure
    (missing tool, timeout, stale index) is caught and recorded in the
    returned evidence, never blocks task execution -- code intelligence
    is an accelerant, not a dependency (see kernel.code_intelligence).

    Bounded by construction: each explore() call is already capped by
    the adapter, and `max_context_chars` caps the *combined* text
    actually included in the prompt, this is the context-budgeting hook
    a future MemoryRouter can drive with a smarter number.
    """
    provider_name = type(provider).__name__
    queries: list[dict[str, Any]] = []
    blocks: list[str] = []
    total_chars = 0

    try:
        provider.index(repo_path, full=False)
    except CodeIntelligenceUnavailable as exc:
        queries.append({"op": "index", "success": False, "error": str(exc)})

    try:
        index_status = provider.status().to_dict()
    except CodeIntelligenceUnavailable as exc:
        index_status = {"available": False, "stale": True, "detail": str(exc)}

    if index_status.get("available") and index_status.get("stale"):
        blocks.append(
            "**Note:** the code-intelligence index may be stale (pending "
            "changes since last sync) -- verify structural claims before "
            "relying on them."
        )

    for symbol in focus_symbols:
        started = time.monotonic()
        try:
            ctx = provider.explore(symbol)
            latency_ms = round((time.monotonic() - started) * 1000, 1)
            remaining = max_context_chars - total_chars
            included = ctx.text[:remaining] if remaining > 0 else ""
            if included:
                blocks.append(f"### Code intelligence: {symbol}\n{included}")
                total_chars += len(included)
            queries.append({
                "op": "explore", "symbol": symbol, "success": True, "latency_ms": latency_ms,
                "related_symbols": list(ctx.related_symbols), "chars_returned": len(ctx.text),
                "chars_included": len(included),
            })
        except CodeIntelligenceUnavailable as exc:
            latency_ms = round((time.monotonic() - started) * 1000, 1)
            queries.append({
                "op": "explore", "symbol": symbol, "success": False,
                "latency_ms": latency_ms, "error": str(exc),
            })

    evidence = {
        "provider": provider_name, "index_status": index_status,
        "queries": queries, "context_included_chars": total_chars,
    }
    return "\n\n".join(blocks), evidence


class _GuardedLedger:
    """RunLedger wrapper that re-proves ownership before every append, so
    a forgotten guard() call in the engine cannot produce a stale ledger
    write. Reads are unguarded."""

    def __init__(self, inner: RunLedger, guard: Callable[[], None]):
        self._inner = inner
        self._guard = guard

    def append(self, run_id: str, event_type: str, data: dict[str, Any] | None = None) -> LedgerEvent:
        self._guard()
        return self._inner.append(run_id, event_type, data)

    def read_all(self, tolerant: bool = True) -> list[LedgerEvent]:
        return self._inner.read_all(tolerant=tolerant)


class _GuardedRunStore:
    """RunStore wrapper enforcing the ownership guard structurally at
    every durable write path the engine uses (ADR-0006 follow-up: token
    enforcement at the store boundary, not by call-site convention)."""

    def __init__(self, inner: RunStore, guard: Callable[[], None]):
        self._inner = inner
        self._guard = guard

    def create_run(self, run_id: str, task_id: str) -> RunPaths:
        self._guard()
        return self._inner.create_run(run_id, task_id)

    def update_state(self, run_id: str, state: RunState) -> RunMeta:
        self._guard()
        return self._inner.update_state(run_id, state)

    def heartbeat(self, run_id: str, fingerprint: Any | None = None) -> None:
        self._guard()
        self._inner.heartbeat(run_id, fingerprint)

    def ledger_for(self, run_id: str) -> _GuardedLedger:
        return _GuardedLedger(self._inner.ledger_for(run_id), self._guard)

    def paths_for(self, run_id: str) -> RunPaths:
        return self._inner.paths_for(run_id)

    def write_evidence(self, path: Path, text: str) -> None:
        """Guarded write for the run directory's raw evidence files
        (result.json, code_intelligence.json, git/pre|post.json), so no
        durable run-directory write is left to call-site convention."""
        self._guard()
        path.write_text(text, encoding="utf-8")


@dataclass
class TaskExecutionOutcome:
    task_id: str
    run_ids: list[str]
    final_task_state: TaskState
    verification: VerificationResult | None
    execution_result: ExecutionResult | None
    report: EngineerReport
    # Directive 9: the typed classification of the last attempt, so a
    # caller schedules on the reason code rather than re-deriving it.
    classification: FailureClassification | None = None


class TaskEngine:
    """Executes a single task: run the Claude Code CLI (with retries and
    crash-safe durable state), then deterministically verify the result."""

    def __init__(
        self,
        run_store: RunStore,
        cli_runner: Any = None,
        retry_policy: RetryPolicy | None = None,
        failure_chain: FailureClassifierChain | None = None,
    ):
        self.run_store = run_store
        self.cli_runner = cli_runner or ClaudeCodeCLIRunner()
        self.retry_policy = retry_policy or RetryPolicy()
        self.failure_chain = failure_chain or DEFAULT_CHAIN

    def execute_task(
        self,
        task_id: str,
        objective: str,
        prompt: str,
        repo_path: Path,
        verifier: Verifier | None = None,
        timeout_s: float = 1800.0,
        cancellation_token: CancellationToken | None = None,
        mcp: McpRunnerConfig | None = None,
        code_intelligence: CodeIntelligenceProvider | None = None,
        focus_symbols: Sequence[str] | None = None,
        max_context_chars: int = 12000,
        authority: WorkAuthority | None = None,
        worker_id: str | None = None,
        lease_ttl_s: float | None = None,
        lease_heartbeat_interval_s: float | None = None,
        worktrees: WorktreeManager | None = None,
        policy: PolicyEngine | None = None,
        approvals: ApprovalStore | None = None,
        policy_actor: str | None = None,
    ) -> TaskExecutionOutcome:
        # Two-plane ownership (Directive 4 / ADR-0006): when a WorkAuthority
        # is supplied, this engine invocation must hold the durable claim
        # and the live lease for the task, and re-proves both before every
        # durable mutation. A deposed worker raises StaleLeaseError /
        # StaleClaimError instead of writing — the NO STALE WRITE invariant
        # enforced at the engine's write paths, not by convention.
        grant: WorkGrant | None = None
        pump: GrantHeartbeatPump | None = None
        if authority is not None:
            if not worker_id:
                raise ValueError("worker_id is required when a WorkAuthority is supplied")
            if verifier is None:
                # Resolving a claim is the durable DONE, and the
                # constitution is absolute: no DONE without evidence. A
                # bare CLI exit code is not evidence (Codex review,
                # INVALID DONE finding). Callers must choose a verifier
                # consciously — even a cheap one — or run ungoverned.
                raise ValueError(
                    "a WorkAuthority-governed task requires a verifier: "
                    "claims resolve to DONE only on verification evidence"
                )
            grant = authority.acquire(task_id, worker_id, ttl_s=lease_ttl_s)
            if cancellation_token is None:
                # Deposition detected mid-run cancels the child process
                # instead of leaking it.
                cancellation_token = CancellationToken()
            token = cancellation_token
            # The pump keeps the lease alive for the grant's WHOLE lifetime
            # — CLI runs, retry backoffs, verification, resolve — so a slow
            # verifier can no longer self-depose a healthy worker
            # (adversarial-review finding on the first version of this
            # unit). Deposition cancels the child cooperatively.
            interval = (
                lease_heartbeat_interval_s
                if lease_heartbeat_interval_s is not None
                else min(max(grant.ttl_s / 4.0, 0.05), 15.0)
            )
            pump = GrantHeartbeatPump(
                authority, grant, interval_s=interval,
                on_deposed=lambda exc: token.cancel(),
            )
            pump.start()

        def guard() -> None:
            # Surface a pump-detected deposition deterministically, then
            # re-prove both planes.
            if pump is not None and pump.deposed is not None:
                raise pump.deposed
            if authority is not None and grant is not None:
                authority.assert_current(grant)

        try:
            # Workspace isolation (ADR-0006 + ADR-0007 composition): with a
            # WorktreeManager the repository-writing child runs with its cwd
            # inside the task's kernel-minted worktree instead of the shared
            # repo, so its ordinary relative-path work lands on the task's
            # own isolated branch. Ownership first, workspace second: the
            # grant is already held. The worktree deliberately survives this
            # call regardless of outcome (bound to the unresolved/integrable
            # work; removal is the integration milestone's decision).
            #
            # This creation MUST stay inside the try: it can raise (corrupt
            # marker, unregistered directory, git failure) and the finally
            # below is the only thing that stops the heartbeat pump — a leak
            # here would renew a dead worker's lease forever and make the
            # task permanently unreclaimable (adversarial review, reported
            # independently by four reviewers with a live reproduction).
            worktree_handle: WorktreeHandle | None = None
            worktree_was_fresh = False
            exec_root = repo_path
            if worktrees is not None:
                if worktrees.source_repo.resolve() != Path(repo_path).resolve():
                    # Otherwise the task would silently execute, verify and
                    # report against a DIFFERENT repository than the caller
                    # named (Codex review).
                    raise ValueError(
                        f"worktree manager operates on {worktrees.source_repo}, "
                        f"but this task was given repo_path {repo_path}"
                    )
                # Whether we minted it matters: a policy refusal may
                # only undo the workspace THIS call created, never one
                # that already held a previous attempt's work.
                worktree_was_fresh = not worktrees.exists(task_id)
                worktree_handle = worktrees.create(task_id)  # idempotent/reattach
                exec_root = Path(worktree_handle.path)

            return self._execute_guarded(
                task_id=task_id, objective=objective, prompt=prompt,
                exec_root=exec_root, worktree=worktree_handle,
                verifier=verifier, timeout_s=timeout_s,
                cancellation_token=cancellation_token, mcp=mcp,
                code_intelligence=code_intelligence, focus_symbols=focus_symbols,
                max_context_chars=max_context_chars, authority=authority,
                grant=grant, guard=guard, policy=policy, approvals=approvals,
                policy_actor=policy_actor or worker_id or "agent://unattributed",
                worktrees=worktrees, worktree_was_fresh=worktree_was_fresh,
            )
        finally:
            if pump is not None:
                pump.stop()

    def _gate(
        self, *, stage: str, task_id: str, objective: str, prompt: str,
        exec_root: Path, mcp: McpRunnerConfig | None,
        worktree: WorktreeHandle | None, policy: PolicyEngine,
        approvals: ApprovalStore | None, policy_actor: str,
        code_intelligence: CodeIntelligenceProvider | None,
        focus_symbols: Sequence[str] | None,
        store: _GuardedRunStore, task_sm: TaskStateMachine,
        run_ids: list[str], classifications: list[FailureClassification],
        worktrees: WorktreeManager | None,
    ) -> _GateResult:
        """Ask the policy engine once, at one stage, and act on the answer."""
        snapshot = ActionSnapshot(
            intervention_point=AGENT_RUN_INTERVENTION_POINT,
            tool="claude_cli", actor=policy_actor,
            intent=agent_run_intent(
                _runner_binary(self.cli_runner), exec_root,
                permission_mode=DEFAULT_PERMISSION_MODE, model=None, mcp=mcp,
            ),
            payload={
                "stage": stage,
                "task_id": task_id,
                # The prompt binds an approval without being inlined.
                "prompt_sha256": hash_canonical(prompt),
                # Content, not just path: a config file can be rewritten
                # between the verdict and the launch, and the PATHS do not
                # decide which tools the agent reaches — the CONTENTS do
                # (adversarial review).
                "mcp": _mcp_fingerprint(mcp, exec_root),
                "code_intelligence": (
                    type(code_intelligence).__name__ if code_intelligence else None
                ),
                "focus_symbols": sorted(focus_symbols or ()),
                # Stable worktree identity only: `created_at` is a
                # per-submission value that made every approval
                # un-reusable, defeating the documented "approve, then
                # resubmit" flow (adversarial review).
                "worktree_branch": worktree.branch if worktree else None,
            },
            context={"exec_root": str(exec_root)},
        )
        decision = policy.decide(snapshot)
        if approvals is not None:
            decision = resolve_escalation(decision, snapshot, approvals)
        if decision.verdict in (Verdict.ALLOW, Verdict.WARN):
            return _GateResult(decision=decision, outcome=None)
        return _GateResult(decision=None, outcome=self._refused_outcome(
            task_id, objective, decision, store, task_sm, run_ids,
            classifications, worktrees=worktrees, worktree=worktree,
        ))

    def _refused_outcome(
        self,
        task_id: str,
        objective: str,
        decision: PolicyDecision,
        store: _GuardedRunStore,
        task_sm: TaskStateMachine,
        run_ids: list[str],
        classifications: list[FailureClassification],
        worktrees: WorktreeManager | None = None,
        worktree: WorktreeHandle | None = None,
    ) -> TaskExecutionOutcome:
        """Materialize a policy refusal as durable evidence, and undo the
        workspace this call minted.

        A refused action still opens a run: "policy said no" must leave a
        trace with the same shape as any other outcome, or a denial is
        indistinguishable from a task that was never attempted. No child
        process is created and the repository is never touched.

        The kernel does mint the task's worktree before asking (rules are
        told where the agent would run, which needs the real path), so a
        refusal cleans up after itself: a branch minted for an action that
        was then forbidden is a side effect the gate should not have left
        behind (verified: a DENY used to leave `gnosis/<task>` behind).
        Only a workspace THIS call created is removed — a reattached one
        may hold a previous attempt's work, and ADR-0007's provenance gate
        refuses anything dirty regardless.
        """
        if worktrees is not None and worktree is not None:
            try:
                worktrees.remove(worktree, delete_branch=True)
            except WorktreeError:
                # Cleanup is best-effort: a refusal that cannot tidy up is
                # still a refusal, and ADR-0007 forbids forcing it.
                pass
        run_id = new_run_id()
        run_ids.append(run_id)
        store.create_run(run_id, task_id)
        ledger = store.ledger_for(run_id)
        ledger.append(run_id, "policy.decision", _safe_decision(decision))

        # A deny caused by the engine breaking, or by missing
        # configuration, is NOT the agent violating a policy: billing
        # either to the agent would penalise it for the kernel's own
        # problems, which rule 7 forbids (adversarial review).
        if decision.is_runtime_error:
            failure = FailureClass.FAIL_INFRA
        elif decision.is_policy_gap:
            failure = FailureClass.NEEDS_HUMAN
        else:
            failure = FailureClass.FAIL_POLICY
        classification = FailureClassification(
            failure=failure,
            # The policy's own reason code travels unchanged into the
            # taxonomy and out to the scheduler (Directive 9).
            reason_code=decision.reason,
            evidence_grade=EvidenceGrade.STRUCTURED,
            classifier_id="policy_engine",
            evidence=f"{decision.verdict.value} by {decision.rule_id}",
            # Rule-supplied detail is untrusted data and goes FIRST: the
            # kernel's own action_id is the identity an operator approves
            # and a rule must not be able to overwrite it.
            detail={**_safe_detail(decision.detail),
                    "action_id": decision.action_id},
        )
        classifications.append(classification)
        ledger.append(run_id, "run.attempt_classified", classification.to_dict())
        # CANCELLED, not FAILED: the run never started, and PENDING->FAILED
        # is not a legal transition — RunStore does not validate, so the
        # illegal edge used to land on disk unchallenged (adversarial
        # review).
        store.update_state(run_id, RunState.CANCELLED)
        # An unapproved escalation is not terminal: ESCALATED exists for
        # exactly the "approve, then resubmit" state the report describes.
        task_sm.transition(
            TaskState.ESCALATED if decision.verdict is Verdict.ESCALATE
            else TaskState.FAILED
        )

        report = EngineerReport(
            task_id=task_id, run_id=run_id,
            status=_report_status(task_sm.state, classifications),
            objective=objective,
            work_completed=("No work performed: the policy engine refused the action.",),
            verification=("Not reached: execution was refused before it started.",),
            problems_encountered=(
                f"{decision.verdict.value} ({decision.reason}) from rule {decision.rule_id}",
            ),
            recommended_next_step=(
                "Obtain an approval bound to this action id, or change the action, "
                "then resubmit."
                if decision.verdict is Verdict.ESCALATE
                else "Review the policy rule and the requested action before retrying."
            ),
        )
        return TaskExecutionOutcome(
            task_id=task_id, run_ids=run_ids, final_task_state=task_sm.state,
            verification=None, execution_result=None, report=report,
            classification=classification,
        )

    def _execute_guarded(
        self,
        task_id: str,
        objective: str,
        prompt: str,
        exec_root: Path,
        worktree: WorktreeHandle | None,
        verifier: Verifier | None,
        timeout_s: float,
        cancellation_token: CancellationToken | None,
        mcp: McpRunnerConfig | None,
        code_intelligence: CodeIntelligenceProvider | None,
        focus_symbols: Sequence[str] | None,
        max_context_chars: int,
        authority: WorkAuthority | None,
        grant: WorkGrant | None,
        guard: Callable[[], None],
        policy: PolicyEngine | None = None,
        approvals: ApprovalStore | None = None,
        policy_actor: str = "agent://unattributed",
        worktrees: WorktreeManager | None = None,
        worktree_was_fresh: bool = False,
    ) -> TaskExecutionOutcome:
        task_sm = TaskStateMachine(TaskState.CREATED)
        task_sm.transition(TaskState.PLANNED)
        task_sm.transition(TaskState.IN_PROGRESS)

        # Every durable run-store write below re-proves ownership at the
        # store boundary — a forgotten guard() call cannot stale-write.
        store = _GuardedRunStore(self.run_store, guard)

        run_ids: list[str] = []
        classifications: list[FailureClassification] = []
        last_result: ExecutionResult | None = None
        refusal_worktrees = worktrees if worktree_was_fresh else None

        # Fail-closed gate BEFORE any child process exists at all.
        # Stage 1 runs before code intelligence, which SHELLS OUT: the
        # previous single gate sat after it, so a denied action had
        # already run kernel-launched subprocesses against the workspace,
        # falsifying this unit's headline invariant (adversarial review).
        policy_decision: PolicyDecision | None = None
        if policy is not None:
            refusal = self._gate(
                stage="pre_context", task_id=task_id, objective=objective,
                prompt=prompt, exec_root=exec_root, mcp=mcp, worktree=worktree,
                policy=policy, approvals=approvals, policy_actor=policy_actor,
                code_intelligence=code_intelligence, focus_symbols=focus_symbols,
                store=store, task_sm=task_sm, run_ids=run_ids,
                classifications=classifications, worktrees=refusal_worktrees,
            )
            if refusal.outcome is not None:
                return refusal.outcome
            policy_decision = refusal.decision

        pre_git = capture_git_evidence(exec_root)

        ci_evidence: dict[str, Any] | None = None
        effective_prompt = prompt
        if code_intelligence is not None and focus_symbols:
            context_block, ci_evidence = _gather_code_intelligence_context(
                code_intelligence, exec_root, focus_symbols, max_context_chars,
            )
            if context_block:
                effective_prompt = f"{context_block}\n\n---\n\n{prompt}"
                if policy is not None:
                    # The prompt the rules judged is no longer the prompt
                    # that will run: kernel-generated context derived from
                    # the repository was prepended, so ask again about the
                    # real thing. Stage 1 already ensured nothing executed
                    # before a first verdict.
                    refusal = self._gate(
                        stage="final_prompt", task_id=task_id, objective=objective,
                        prompt=effective_prompt, exec_root=exec_root, mcp=mcp,
                        worktree=worktree, policy=policy, approvals=approvals,
                        policy_actor=policy_actor,
                        code_intelligence=code_intelligence,
                        focus_symbols=focus_symbols, store=store, task_sm=task_sm,
                        run_ids=run_ids, classifications=classifications,
                        worktrees=refusal_worktrees,
                    )
                    if refusal.outcome is not None:
                        return refusal.outcome
                    policy_decision = refusal.decision

        heartbeat_failures: list[str] = []

        def on_heartbeat(run_id: str) -> None:
            # NOTHING may escape this callback: it runs inside the runner's
            # polling loop, and an exception there unwinds past the child
            # process and leaks it (adversarial review). A deposition
            # cancels the child cooperatively; any other failure (lock
            # timeout under contention, a transient Windows sharing
            # violation on heartbeat.json — the L-0002 class) is a liveness
            # hiccup that must not kill a healthy run: the ownership guards
            # and the recovery scanner remain the authority.
            try:
                store.heartbeat(run_id)
            except (StaleClaimError, StaleLeaseError):
                if cancellation_token is not None:
                    cancellation_token.cancel()
            except Exception as exc:  # noqa: BLE001 - see above: never unwind the poll loop
                # Kept as data on the run instead of vanishing: the next
                # guarded write records it, and a heartbeat gap is already
                # visible to the recovery scanner.
                heartbeat_failures.append(repr(exc))

        def attempt(attempt_number: int) -> ExecutionResult:
            nonlocal last_result
            guard()
            run_id = new_run_id()
            run_ids.append(run_id)
            paths = store.create_run(run_id, task_id)
            ledger = store.ledger_for(run_id)
            if attempt_number == 1 and ci_evidence is not None:
                ledger.append(run_id, "code_intelligence.context_gathered", ci_evidence)
                store.write_evidence(
                    paths.root / "code_intelligence.json",
                    json.dumps(ci_evidence, indent=2, sort_keys=True),
                )
            if policy_decision is not None:
                # The verdict the child actually ran under, on the run's
                # own ledger: an allowed action is evidence too, not just
                # a refused one.
                ledger.append(run_id, "policy.decision", _safe_decision(policy_decision))
            ledger.append(run_id, "run.attempt_started", {
                "attempt": attempt_number, "objective": objective,
                "mcp": mcp.to_dict() if mcp is not None else None,
                "code_intelligence_used": ci_evidence is not None,
                "worktree": worktree.to_dict() if worktree is not None else None,
            })
            store.update_state(run_id, RunState.RUNNING)
            store.heartbeat(run_id)

            # Last re-proof before the repository-writing child launches
            # (Codex review): shrinks the pre-launch stale window from
            # "attempt entry -> launch" to milliseconds. The in-flight
            # child window that remains is handled cooperatively by the
            # pump; its structural closure (worktree isolation + token
            # enforcement inside RunStore) is tracked in NEXT_ACTIONS.
            guard()
            result = self.cli_runner.run(
                prompt=effective_prompt, cwd=exec_root, stdout_path=paths.stdout, stderr_path=paths.stderr,
                timeout_s=timeout_s, cancellation_token=cancellation_token, mcp=mcp,
                heartbeat_fn=lambda pid: on_heartbeat(run_id),
            )

            # The CLI run is a long window in which a deposition can happen
            # (the pump detects it and cancels the child); re-prove
            # ownership before recording the outcome.
            guard()

            # Directive 9: every attempt is CLASSIFIED before it can be
            # repeated, and the reason code flows unchanged from here into
            # the run's durable state, the ledger event and the retry
            # decision below — a taxonomy nothing consults is a parallel
            # fiction. The classification comes FIRST because the durable
            # state depends on it.
            classification = self.failure_chain.classify(FailureSignal(
                exit_code=result.exit_code, timed_out=result.timed_out,
                cancelled=result.cancelled,
                structured=result.parsed_json if isinstance(result.parsed_json, dict) else {},
                stderr_text=_tail(paths.stderr), stdout_text=_tail(paths.stdout),
            ))
            classifications.append(classification)

            if result.succeeded:
                final_state = RunState.SUCCEEDED
            elif result.timed_out:
                final_state = RunState.TIMED_OUT
            elif result.cancelled:
                final_state = RunState.CANCELLED
            elif classification.is_park:
                # A park recorded as FAILED is not a park: the state has
                # to survive on disk for a scheduler to resume it, and it
                # must not read as an agent failure (adversarial review).
                final_state = RunState.RATE_LIMITED
            else:
                final_state = RunState.FAILED

            store.update_state(run_id, final_state)
            ledger.append(run_id, "run.attempt_classified", classification.to_dict())
            ledger.append(run_id, "run.attempt_finished", {
                "attempt": attempt_number, "exit_code": result.exit_code,
                "timed_out": result.timed_out, "cancelled": result.cancelled,
                "duration_s": result.duration_s,
                # Liveness hiccups swallowed by on_heartbeat surface here
                # rather than vanishing (they never abort a healthy run).
                "heartbeat_failures": list(heartbeat_failures),
            })
            store.write_evidence(
                paths.result, json.dumps(result.to_dict(), indent=2, sort_keys=True),
            )
            last_result = result
            return result

        def should_retry(result: ExecutionResult) -> bool:
            if result.cancelled or result.succeeded:
                return False
            if not classifications:
                return True
            # The classification decides, not the exit code: RATE_LIMITED
            # parks (burning retries against a shut window is exactly what
            # rule 6 forbids), and an UNCLASSIFIED or escalating failure
            # stops rather than repeating an action nobody understood.
            return scheduler_action(classifications[-1]) is SchedulerAction.RETRY

        execute_with_retry(attempt, should_retry, self.retry_policy)

        guard()
        post_git = capture_git_evidence(exec_root)
        latest_run_id = run_ids[-1] if run_ids else None
        if latest_run_id:
            git_dir = store.paths_for(latest_run_id).git_dir
            store.write_evidence(git_dir / "pre.json", json.dumps(pre_git.to_dict(), indent=2))
            store.write_evidence(git_dir / "post.json", json.dumps(post_git.to_dict(), indent=2))

        cli_succeeded = bool(last_result and last_result.succeeded)
        verification_result: VerificationResult | None = None

        if cli_succeeded:
            task_sm.transition(TaskState.VERIFYING)
            if verifier is not None:
                verification_result = verifier.run(exec_root)
                if latest_run_id:
                    store.ledger_for(latest_run_id).append(
                        latest_run_id, "task.verification_result", verification_result.to_dict(),
                    )
            verification_passed = verification_result.passed if verification_result else True
            task_sm.transition(TaskState.COMPLETED if verification_passed else TaskState.FAILED)
        else:
            task_sm.transition(TaskState.FAILED)

        # Verified success resolves the claim and releases the lease in the
        # same authority call. On failure/cancellation the claim deliberately
        # stays ACTIVE, bound to the unresolved work (grit's merge-failure
        # lesson); the lease is left to expire so the TTL sweep reclaims it
        # as an audited RECLAIMED transition instead of a silent release.
        if authority is not None and grant is not None and task_sm.state == TaskState.COMPLETED:
            authority.resolve(grant, outcome="COMPLETED")

        problems: tuple[str, ...] = ()
        if not cli_succeeded and latest_run_id:
            stderr_path = store.paths_for(latest_run_id).stderr
            if stderr_path.exists():
                tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                problems = (redact(tail),) if tail.strip() else ()
        elif verification_result is not None and not verification_result.passed:
            problems = (redact(verification_result.stderr_excerpt),)

        report = EngineerReport(
            task_id=task_id,
            run_id=latest_run_id or "NONE",
            status=_report_status(task_sm.state, classifications),
            objective=objective,
            work_completed=(f"Executed {len(run_ids)} run attempt(s) via the Claude Code CLI runner.",),
            verification=(
                (f"{verification_result.name}: " + ("PASSED" if verification_result.passed else "FAILED"),)
                if verification_result else ("No verifier supplied.",)
            ),
            problems_encountered=problems,
            recommended_next_step=(
                "None, task completed and verified." if task_sm.state == TaskState.COMPLETED
                else "Investigate the run/verification failure captured in this run's evidence before retrying."
            ),
        )

        return TaskExecutionOutcome(
            task_id=task_id, run_ids=run_ids, final_task_state=task_sm.state,
            verification=verification_result, execution_result=last_result, report=report,
            classification=classifications[-1] if classifications else None,
        )
