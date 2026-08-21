"""Landing reviewed work, without believing that a clean merge means it works.

The constitution states the whole problem in two rules:

    15. Worktree != solución completa a conflictos.
    16. Textual merge != semantic integration.

A worktree isolates *while* work happens. It does nothing about what
happens when two isolated results meet. And git's merge answers exactly
one question — "can these text edits be combined without overlapping?" —
which is not the question anybody actually has. Two branches that each
pass their own tests can merge with no conflict at all and produce a
tree that does not work: rename a function on one branch, add a caller
of the old name on the other, and git is perfectly happy.

So the load-bearing decision here is that **integration is verified after
the merge, in the merged tree, and the target only moves if that
passes.** Everything else is arrangement around that:

- The merge happens in a **throwaway integration worktree**, never in the
  operator's checkout. A merge that is about to be discarded must not
  pass through the tree a human is looking at.
- The target advances by fast-forward to a commit that has **already been
  verified**, so the shared branch is never observably broken. Failure
  means nothing moved, which is the cheapest possible rollback.
- A checkpoint ref is written before anything moves, so "undo this" is a
  named ref rather than an operator reading a log (rule 14: git is part
  of the architecture, and so is rollback).
- Conflicts are typed and carry their paths. `MERGE_CONFLICT` is already
  in the failure taxonomy; "merge failed" is not an answer anyone can act
  on.
- Integration is a write to SHARED state, so it is serialized by a lock
  and CAN be gated by policy at its own intervention point. Rule 13 is
  deny-by-default for sensitive actions, and there is no more sensitive
  action in this system than moving the branch everyone else builds on —
  but like every other gate here, this one is opt-in until a default rule
  set exists. `integration/shared_branch_gate` records that as
  PROMPT_ONLY rather than letting this paragraph imply more.

And the limit of the central claim, stated where the claim is made:
verification is **the operator's verifier**, not the kernel's judgement.
What is mechanically guaranteed is the ORDERING — nothing lands that did
not run that check and pass, on a base re-read immediately before the
advance. Whether that check would notice a given break is outside the
kernel entirely (`integration/semantic_correctness = IGNORED`).
"""
from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .convergence import ConvergenceOutcome, ConvergenceResult
from .file_lock import FileLock, lock_path_for
from .git_evidence import capture_git_evidence
from .policy import (
    ActionSnapshot,
    ApprovalStore,
    PolicyEngine,
    Verdict,
    parse_command,
    resolve_escalation,
)
from .verification import VerificationResult, Verifier
from .worktree import BRANCH_PREFIX, WorktreeError, WorktreeManager

INTEGRATION_INTERVENTION_POINT = "before_integration"
CHECKPOINT_REF_PREFIX = "refs/gnosis/checkpoints/"


class IntegrationOutcome(str, Enum):
    INTEGRATED = "INTEGRATED"
    # Refused before touching anything.
    NOT_CONVERGED = "NOT_CONVERGED"
    SOURCE_DIRTY = "SOURCE_DIRTY"
    NOTHING_TO_INTEGRATE = "NOTHING_TO_INTEGRATE"
    REFUSED_BY_POLICY = "REFUSED_BY_POLICY"
    WRONG_TARGET = "WRONG_TARGET"
    # Attempted, and the target did not move.
    MERGE_CONFLICT = "MERGE_CONFLICT"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    INTEGRATION_ERROR = "INTEGRATION_ERROR"


# Outcomes in which the shared branch is guaranteed not to have moved.
UNMOVED_OUTCOMES = frozenset(IntegrationOutcome) - {IntegrationOutcome.INTEGRATED}


@dataclass(frozen=True)
class IntegrationResult:
    outcome: IntegrationOutcome
    task_id: str
    branch: str
    reason: str
    base_sha: str | None = None
    merged_sha: str | None = None
    checkpoint_ref: str | None = None
    conflicts: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    verification: VerificationResult | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def integrated(self) -> bool:
        return self.outcome is IntegrationOutcome.INTEGRATED

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value, "task_id": self.task_id,
            "branch": self.branch, "reason": self.reason,
            "base_sha": self.base_sha, "merged_sha": self.merged_sha,
            "checkpoint_ref": self.checkpoint_ref,
            "conflicts": list(self.conflicts),
            "changed_paths": list(self.changed_paths),
            "verification": self.verification.to_dict() if self.verification else None,
            "detail": self.detail,
        }


def _git(cwd: Path, args: list[str], timeout_s: float = 120.0
         ) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        timeout=timeout_s, check=False,
    )


def _git_dir(repo: Path) -> tuple[int, Path | None]:
    """The COMMON git dir, so a worktree and its source share one lock."""
    proc = _git(repo, ["rev-parse", "--git-common-dir"])
    if proc.returncode != 0:
        return proc.returncode, None
    candidate = Path(proc.stdout.strip())
    if not candidate.is_absolute():
        candidate = repo / candidate
    return 0, candidate


class WorkIntegrator:
    """Merges a task's reviewed worktree into the source branch, or does not."""

    def __init__(
        self,
        source_repo: Path,
        worktrees: WorktreeManager,
        verifier: Verifier,
        target_branch: str | None = None,
        integration_root: Path | None = None,
        lock_timeout_s: float = 120.0,
        policy: PolicyEngine | None = None,
        approvals: ApprovalStore | None = None,
        policy_actor: str = "agent://unattributed",
    ) -> None:
        self.source_repo = Path(source_repo)
        self.worktrees = worktrees
        # A verifier is REQUIRED. Integration without post-merge
        # verification is precisely the "textual merge == semantic
        # integration" mistake rule 16 names, and making it optional would
        # make the mistake the easy path.
        self.verifier = verifier
        # The branch this integrator is allowed to move, named up front.
        # Without it, integration advanced WHATEVER the source repo
        # happened to have checked out — an operator's feature branch, or
        # a detached HEAD — while reporting that the shared branch had
        # landed work (Codex review). `None` means "resolve the current
        # branch once, at construction, and hold that", so the target is
        # still a fixed decision rather than whatever is checked out at
        # merge time.
        self.target_branch = target_branch or self._current_branch()
        self.integration_root = Path(
            integration_root or (self.source_repo.parent / ".gnosis-integration"))
        self.lock_timeout_s = lock_timeout_s
        # Integration is the most sensitive action in this system: it
        # moves the branch everyone else builds on. Rule 13 is
        # deny-by-default for exactly this, and the gate is opt-in here
        # for the same reason it is opt-in everywhere else — no default
        # rule set exists yet — with `policy.ungoverned`-style honesty in
        # the result rather than silence.
        self.policy = policy
        self.approvals = approvals
        self.policy_actor = policy_actor

    def _current_branch(self) -> str | None:
        proc = _git(self.source_repo, ["rev-parse", "--abbrev-ref", "HEAD"])
        if proc.returncode != 0:
            return None
        name = proc.stdout.strip()
        # "HEAD" is what git prints for a detached checkout: not a branch.
        return name if name and name != "HEAD" else None

    # -- the decision ------------------------------------------------------

    def integrate(self, task_id: str, convergence: ConvergenceResult | None) -> IntegrationResult:
        branch = self.worktrees.planned_branch(task_id)

        if convergence is None or convergence.outcome is not ConvergenceOutcome.CONVERGED:
            # Rule: no Task reaches DONE without evidence. Unreviewed work
            # landing on the shared branch is the failure this whole
            # apparatus exists to prevent.
            outcome = convergence.outcome.value if convergence else "no convergence result"
            return IntegrationResult(
                IntegrationOutcome.NOT_CONVERGED, task_id, branch,
                reason=f"not_converged:{outcome}",
            )

        with FileLock(lock_path_for(self._lock_path()), timeout_s=self.lock_timeout_s):
            return self._integrate_locked(task_id, branch)

    def _lock_path(self) -> Path:
        """Serialize integrations on the SOURCE REPO, not per task and not
        per configured directory.

        Two tasks integrating at once is the case rules 15 and 16 are
        about: each merge is computed against a base the other is moving.
        The lock therefore has to be a property of the repository being
        written to — anchored in its git dir — because two integrators
        pointed at the same repo with different `integration_root`s would
        otherwise take two different locks and serialize nothing.
        """
        code, git_dir = _git_dir(self.source_repo)
        if code == 0 and git_dir is not None:
            return git_dir / "gnosis-integration.lock"
        # No git dir means the repo check below will refuse anyway; taking
        # a lock somewhere harmless keeps that the refusal path rather
        # than an exception here.
        self.integration_root.mkdir(parents=True, exist_ok=True)
        return self.integration_root / "integration.lock"

    def _integrate_locked(self, task_id: str, branch: str) -> IntegrationResult:
        evidence = capture_git_evidence(self.source_repo)
        if not evidence.is_repo or evidence.head_sha is None:
            return IntegrationResult(
                IntegrationOutcome.INTEGRATION_ERROR, task_id, branch,
                reason="source_not_a_repo",
            )
        if evidence.status_porcelain.strip():
            # Merging into a dirty checkout mixes uncommitted human work
            # with agent work, and rollback could not tell them apart
            # afterwards. Refusing costs a retry; proceeding costs the
            # ability to undo.
            return IntegrationResult(
                IntegrationOutcome.SOURCE_DIRTY, task_id, branch,
                reason="source_dirty", base_sha=evidence.head_sha,
                detail={"status": evidence.status_porcelain[:2000]},
            )

        # The target must be a real branch, it must be THE branch this
        # integrator was told to move, and it must be the one checked out
        # — because the advance below moves the checked-out ref and its
        # working tree together.
        current = self._current_branch()
        if self.target_branch is None or current is None or current != self.target_branch:
            return IntegrationResult(
                IntegrationOutcome.WRONG_TARGET, task_id, branch,
                reason=f"target_mismatch:expected={self.target_branch}:actual={current}",
                base_sha=evidence.head_sha,
            )

        base_sha = evidence.head_sha
        try:
            handle = self.worktrees.load_handle(task_id)
        except (WorktreeError, FileNotFoundError, OSError) as exc:
            return IntegrationResult(
                IntegrationOutcome.INTEGRATION_ERROR, task_id, branch,
                reason=f"worktree_unavailable:{type(exc).__name__}",
                base_sha=base_sha, detail={"error": str(exc)},
            )

        # Commit whatever the agents left uncommitted, onto the minted
        # branch, through the hardened path that already refuses
        # mid-merge/mid-rebase states and off-branch HEADs (ADR-0007).
        try:
            self.worktrees.autosave(handle, reason=f"integration:{task_id}")
        except WorktreeError as exc:
            return IntegrationResult(
                IntegrationOutcome.INTEGRATION_ERROR, task_id, branch,
                reason=f"autosave_refused:{type(exc).__name__}",
                base_sha=base_sha, detail={"error": str(exc)},
            )

        changed = self._changed_paths(base_sha, branch)

        # The gate runs AFTER autosave, not before. Asking first meant the
        # snapshot described only what was already committed, while
        # autosave then committed the agent's uncommitted files too — so
        # a rule allowing `safe.py` could authorise an action that landed
        # `restricted.py` as well (Codex review). Autosave writes only to
        # the task's OWN branch, which is inert if this refuses; the
        # shared branch is what the gate protects, and it is still
        # untouched here.
        refusal = self._gate(task_id, branch, base_sha, changed)
        if refusal is not None:
            return refusal
        if not changed:
            return IntegrationResult(
                IntegrationOutcome.NOTHING_TO_INTEGRATE, task_id, branch,
                reason="no_changes_against_base", base_sha=base_sha,
            )

        checkpoint_ref = self._write_checkpoint(task_id, base_sha)
        if checkpoint_ref is None:
            return IntegrationResult(
                IntegrationOutcome.INTEGRATION_ERROR, task_id, branch,
                reason="checkpoint_write_failed", base_sha=base_sha,
                changed_paths=changed,
            )

        self._sweep_stale_staging()
        staging = self.integration_root / f"merge-{task_id}-{uuid.uuid4().hex[:8]}"
        try:
            return self._merge_and_verify(
                task_id, branch, base_sha, checkpoint_ref, changed, staging)
        finally:
            self._discard(staging)

    def _merge_and_verify(
        self, task_id: str, branch: str, base_sha: str, checkpoint_ref: str,
        changed: tuple[str, ...], staging: Path,
    ) -> IntegrationResult:
        add = _git(self.source_repo, ["worktree", "add", "--detach", str(staging), base_sha])
        if add.returncode != 0:
            return IntegrationResult(
                IntegrationOutcome.INTEGRATION_ERROR, task_id, branch,
                reason="staging_worktree_failed", base_sha=base_sha,
                checkpoint_ref=checkpoint_ref, changed_paths=changed,
                detail={"stderr": add.stderr.strip()[:2000]},
            )

        merge = _git(staging, ["merge", "--no-ff", "--no-edit", branch])
        if merge.returncode != 0:
            conflicts = tuple(
                line.strip() for line in
                _git(staging, ["diff", "--name-only", "--diff-filter=U"]).stdout.splitlines()
                if line.strip()
            )
            _git(staging, ["merge", "--abort"])
            return IntegrationResult(
                IntegrationOutcome.MERGE_CONFLICT, task_id, branch,
                reason="merge_conflict", base_sha=base_sha,
                checkpoint_ref=checkpoint_ref, conflicts=conflicts,
                changed_paths=changed,
                detail={"stderr": merge.stderr.strip()[:2000]},
            )

        merged_sha = _git(staging, ["rev-parse", "HEAD"]).stdout.strip()

        # THE POINT OF THIS MODULE. The merge succeeded textually; that
        # says nothing about whether the result works. Two branches that
        # each passed their own review can combine into a tree that does
        # not — a rename on one side and a new caller of the old name on
        # the other conflict semantically and not textually.
        verification = self.verifier.run(staging)
        if not verification.passed:
            return IntegrationResult(
                IntegrationOutcome.VERIFICATION_FAILED, task_id, branch,
                reason="merged_tree_failed_verification", base_sha=base_sha,
                merged_sha=merged_sha, checkpoint_ref=checkpoint_ref,
                changed_paths=changed, verification=verification,
            )

        # Only now does the shared branch move, and only by fast-forward
        # to a commit that has already been verified: there is no moment
        # at which an observer can see a broken target.
        #
        # `--ff-only` guarantees ANCESTRY, not "the target is still what
        # was verified against" — a writer that rewound the ref to an
        # ancestor of the merge would be silently overwritten (Codex
        # review). So the base is re-read immediately before the advance
        # and must be unchanged.
        still = _git(self.source_repo, ["rev-parse", "HEAD"]).stdout.strip()
        if still != base_sha:
            return IntegrationResult(
                IntegrationOutcome.INTEGRATION_ERROR, task_id, branch,
                reason="base_moved_during_verification", base_sha=base_sha,
                merged_sha=merged_sha, checkpoint_ref=checkpoint_ref,
                changed_paths=changed, verification=verification,
                detail={"observed_head": still},
            )
        advance = _git(self.source_repo, ["merge", "--ff-only", merged_sha])
        if advance.returncode != 0:
            return IntegrationResult(
                IntegrationOutcome.INTEGRATION_ERROR, task_id, branch,
                reason="fast_forward_failed", base_sha=base_sha,
                merged_sha=merged_sha, checkpoint_ref=checkpoint_ref,
                changed_paths=changed, verification=verification,
                detail={"stderr": advance.stderr.strip()[:2000]},
            )

        return IntegrationResult(
            IntegrationOutcome.INTEGRATED, task_id, branch,
            reason="integrated", base_sha=base_sha, merged_sha=merged_sha,
            checkpoint_ref=checkpoint_ref, changed_paths=changed,
            verification=verification,
        )

    def _gate(self, task_id: str, branch: str, base_sha: str,
              changed_paths: tuple[str, ...]) -> IntegrationResult | None:
        """Ask policy before the shared branch can be touched.

        Its own intervention point, not `before_agent_run`: an operator
        approving "let this agent run" has not approved "and then move
        main", and folding the two into one identity would make the
        second invisible inside the first.
        """
        if self.policy is None:
            return None
        snapshot = ActionSnapshot(
            intervention_point=INTEGRATION_INTERVENTION_POINT,
            tool="git_merge", actor=self.policy_actor,
            intent=parse_command(
                ["git", "merge", "--ff-only", branch], cwd=self.source_repo),
            payload={
                "task_id": task_id,
                "branch": branch,
                "base_sha": base_sha,
                # What this integration would claim ownership of, computed
                # from the FINAL tree. A rule can refuse on path, which is
                # the only lever available before semantic ownership
                # exists (rule 15).
                "changed_paths": sorted(changed_paths),
                "target_branch": self.target_branch,
                "source_repo": str(self.source_repo),
            },
            context={"exec_root": str(self.source_repo)},
        )
        decision = self.policy.decide(snapshot)
        if self.approvals is not None:
            decision = resolve_escalation(decision, snapshot, self.approvals)
        if decision.verdict in (Verdict.ALLOW, Verdict.WARN):
            return None
        return IntegrationResult(
            IntegrationOutcome.REFUSED_BY_POLICY, task_id, branch,
            reason=decision.reason, base_sha=base_sha,
            detail={"verdict": decision.verdict.value,
                    "action_id": snapshot.action_id()},
        )

    # -- provenance and rollback ------------------------------------------

    def _write_checkpoint(self, task_id: str, base_sha: str) -> str | None:
        """Name the pre-integration state, before anything moves.

        Rollback is then `git reset --hard <ref>` against a ref the kernel
        wrote, rather than an operator reconstructing a sha from a log.
        The kernel never runs that reset itself: undoing an integration is
        an irreversible act on shared state and belongs to a human.

        The ref includes the BASE SHA, so re-integrating the same task id
        cannot overwrite an earlier rollback point and send an operator's
        `reset --hard` to the wrong commit. And a failed `update-ref` is
        reported rather than swallowed: no checkpoint means no rollback,
        and proceeding without one would trade the guarantee for nothing
        (Codex review).
        """
        ref = f"{CHECKPOINT_REF_PREFIX}{task_id}/{base_sha}"
        proc = _git(self.source_repo, ["update-ref", ref, base_sha])
        if proc.returncode != 0:
            return None
        return ref

    def rollback_command(self, result: IntegrationResult) -> str | None:
        """The exact command a human would run to undo this. Not run here."""
        if not result.integrated or not result.checkpoint_ref:
            return None
        return f"git -C {self.source_repo} reset --hard {result.checkpoint_ref}"

    def _changed_paths(self, base_sha: str, branch: str) -> tuple[str, ...]:
        """What this task touched, relative to the base it forked from.

        Recorded on every result — rule 15's "prepare semantic ownership".
        Two tasks touching disjoint paths are not necessarily safe to
        combine, but two touching the SAME paths are a signal worth having
        before a scheduler starts running them concurrently.
        """
        proc = _git(self.source_repo, ["diff", "--name-only", f"{base_sha}...{branch}"])
        if proc.returncode != 0:
            return ()
        return tuple(line.strip() for line in proc.stdout.splitlines() if line.strip())

    def _sweep_stale_staging(self) -> None:
        """Clear staging worktrees a crashed process left registered.

        The `finally` that discards a staging tree only runs on a normal
        unwind; a kill during verification leaves the worktree registered
        forever (Codex review). This is the same shape as ADR-0016's boot
        sweep: recovery is reconcile, and it runs under the integration
        lock so it cannot race a live one.
        """
        if not self.integration_root.exists():
            return
        for candidate in self.integration_root.glob("merge-*"):
            if candidate.is_dir():
                self._discard(candidate)
        _git(self.source_repo, ["worktree", "prune"])

    def _discard(self, staging: Path) -> None:
        """Remove the throwaway worktree; never fail the result over it.

        `--force` is used, and it is provenance-gated the way ADR-0007
        requires: only a path THIS class created, under its own
        integration root, with the `merge-` prefix it mints. Rule 27 bans
        forced destruction as a shortcut, not as the disposal of a
        scratch tree whose entire contents are a merge we are throwing
        away — but the check is what keeps those two different.
        """
        try:
            resolved = staging.resolve()
            root = self.integration_root.resolve()
        except OSError:
            return
        if not staging.name.startswith("merge-") or root not in resolved.parents:
            return
        _git(self.source_repo, ["worktree", "remove", "--force", str(staging)])
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        _git(self.source_repo, ["worktree", "prune"])


def integration_branches(source_repo: Path) -> tuple[str, ...]:
    """Kernel-minted branches present in the repo, for an operator view."""
    proc = _git(Path(source_repo), ["for-each-ref", "--format=%(refname:short)",
                                    f"refs/heads/{BRANCH_PREFIX}*"])
    if proc.returncode != 0:
        return ()
    return tuple(line.strip() for line in proc.stdout.splitlines() if line.strip())
