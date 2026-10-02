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
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .convergence import (
    ConvergenceOutcome,
    ConvergencePolicy,
    ConvergenceResult,
    GatedFinding,
    ReviewReport,
    ReviewVerdict,
    classify_findings,
)
from .execution_scope import ExecutionScope
from .file_lock import FileLock, lock_path_for
from .git_evidence import capture_git_evidence, tamper_fingerprint
from .policy import (
    ActionSnapshot,
    ApprovalStore,
    PolicyEngine,
    Verdict,
    parse_command,
    resolve_escalation,
)
from .subject import SubjectIdentity, observe_subject
from .verification import (
    Evidence,
    VerificationVerdict,
    Verifier,
    evidence_reason,
    verification_verdict,
)
from .worktree import BRANCH_PREFIX, WorktreeError, WorktreeManager

INTEGRATION_INTERVENTION_POINT = "before_integration"
CHECKPOINT_REF_PREFIX = "refs/gnosis/checkpoints/"
# `git status -z` separates records with NUL rather than quoting paths.
NUL = chr(0)


class IntegrationOutcome(str, Enum):
    INTEGRATED = "INTEGRATED"
    # Refused before touching anything.
    NOT_CONVERGED = "NOT_CONVERGED"
    SOURCE_DIRTY = "SOURCE_DIRTY"
    NOTHING_TO_INTEGRATE = "NOTHING_TO_INTEGRATE"
    REFUSED_BY_POLICY = "REFUSED_BY_POLICY"
    WRONG_TARGET = "WRONG_TARGET"
    # The task converged against a tree the target has since left behind:
    # its verification can be re-run, its independent REVIEW cannot.
    REVIEW_STALE = "REVIEW_STALE"
    # A re-review ran against the merged tree and did not pass.
    REVIEW_FAILED = "REVIEW_FAILED"
    # The re-reviewer changed the tree it was judging (rule 9).
    REVIEWER_MODIFIED_SUBJECT = "REVIEWER_MODIFIED_SUBJECT"
    # Attempted, and the target did not move.
    MERGE_CONFLICT = "MERGE_CONFLICT"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    # The merged tree was verified and the verifier stated no verdict.
    # NOT a synonym for VERIFICATION_FAILED: that one says the merged code
    # is wrong and a human should read the diff, while this one says the
    # verification apparatus is wrong and the diff is not the problem.
    # Landing on either is refused; sending an operator to the wrong one
    # costs them the afternoon (third F-34 review).
    VERIFICATION_INVALID = "VERIFICATION_INVALID"
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
    # `Evidence`: the merged tree's verification may be a result or a
    # record that no verdict could be produced, and the second is kept
    # rather than discarded so the refusal is inspectable.
    verification: Evidence | None = None
    # The independent verdict against the MERGED tree, when one was
    # required. This is what makes a stale review recoverable as
    # evidence rather than only waivable as a decision (ADR-0021).
    rereview: ReviewReport | None = None
    rereview_gated: tuple[GatedFinding, ...] = ()
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
            "rereview": ({"verdict": self.rereview.verdict.value,
                          "reviewer": self.rereview.reviewer,
                          "findings": [f.to_dict() for f in self.rereview.findings],
                          "notes": self.rereview.notes}
                         if self.rereview else None),
            "rereview_gated": [g.to_dict() for g in self.rereview_gated],
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PreparedIntegration:
    """Verified merge awaiting advancement; never itself an INTEGRATED verdict."""

    task_id: str
    branch: str
    target_branch: str
    task_sha: str
    base_sha: str
    merged_sha: str
    checkpoint_ref: str
    changed_paths: tuple[str, ...]
    verification: Evidence
    rereview: ReviewReport | None = None
    rereview_gated: tuple[GatedFinding, ...] = ()

    def completed(self) -> IntegrationResult:
        return IntegrationResult(IntegrationOutcome.INTEGRATED, self.task_id, self.branch,
            "integrated", self.base_sha, self.merged_sha, self.checkpoint_ref,
            changed_paths=self.changed_paths, verification=self.verification,
            rereview=self.rereview, rereview_gated=self.rereview_gated)


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
        re_reviewer: Callable[[Path], ReviewReport] | None = None,
        convergence_policy: ConvergencePolicy | None = None,
        scope: ExecutionScope | None = None,
        on_prepared: Callable[[PreparedIntegration], None] | None = None,
        staging_root: Path | None = None,
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
        # Keep the coordination lock protected even when candidate verification
        # needs a Worker-readable/writable scratch worktree.
        self.staging_root = Path(staging_root) if staging_root is not None else self.integration_root
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
        # Injected as a callable for the same reason `verify_fn` is: the
        # kernel declares what evidence it needs and never learns which
        # provider produced it. Nothing under `kernel/` imports
        # `adapters/`.
        self.re_reviewer = re_reviewer
        # The SAME blocking rule convergence uses. A finding that blocks
        # convergence but not landing would be a contradiction an
        # operator could only discover by experiment.
        self.convergence_policy = convergence_policy or ConvergencePolicy(max_rounds=1)
        self.scope = scope
        self.on_prepared = on_prepared

    def _guard(self) -> None:
        if self.scope is not None:
            self.scope.check()

    def _current_branch(self) -> str | None:
        proc = _git(self.source_repo, ["rev-parse", "--abbrev-ref", "HEAD"])
        if proc.returncode != 0:
            return None
        name = proc.stdout.strip()
        # "HEAD" is what git prints for a detached checkout: not a branch.
        return name if name and name != "HEAD" else None

    # -- the decision ------------------------------------------------------

    def integrate(self, task_id: str, convergence: ConvergenceResult | None,
                  waive_stale_review: bool = False,
                  re_reviewer: Callable[[Path], ReviewReport] | None = None,
                  ) -> IntegrationResult:
        self._guard()
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

        reviewer = re_reviewer or self.re_reviewer

        # STALENESS IS DERIVED HERE, not asserted by the caller. The first
        # version took `require_rereview` as a parameter defaulting to
        # False, so the public API's default landed an expired review in
        # silence and every direct caller was one forgotten argument away
        # from the exact hole this milestone exists to close (independent
        # review). The integrator knows the task's fork point and the
        # target's head; it can answer the question itself.
        stale = self._review_is_stale(task_id)
        if stale and not waive_stale_review and reviewer is None:
            # Evidence is required and cannot be produced. Refusing is the
            # only honest answer.
            return IntegrationResult(
                IntegrationOutcome.REVIEW_STALE, task_id, branch,
                reason="rereview_required_but_no_reviewer_configured",
            )
        require_rereview = stale and not waive_stale_review

        with FileLock(lock_path_for(self._lock_path()), timeout_s=self.lock_timeout_s):
            self._guard()
            # The target may have moved while this caller waited for the lock.
            stale = self._review_is_stale(task_id)
            if stale and not waive_stale_review and reviewer is None:
                return IntegrationResult(IntegrationOutcome.REVIEW_STALE, task_id, branch,
                                         "rereview_required_but_no_reviewer_configured")
            require_rereview = stale and not waive_stale_review
            reviewed_subject = convergence.rounds[-1].subject if convergence.rounds else None
            return self._integrate_locked(task_id, branch, require_rereview, reviewer, reviewed_subject)

    def _review_is_stale(self, task_id: str) -> bool:
        """Did the target move after this task forked from it?

        If so, the independent review it converged with judged a tree
        that no longer exists. Read-only, and cheap enough to ask on
        every landing rather than trusting a flag.
        """
        base_sha, _ = self.preview(task_id)
        if base_sha is None:
            return False
        evidence = capture_git_evidence(self.source_repo)
        return bool(evidence.head_sha) and evidence.head_sha != base_sha

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

    def _integrate_locked(self, task_id: str, branch: str,
                          require_rereview: bool = False,
                          reviewer: Callable[[Path], ReviewReport] | None = None,
                          reviewed_subject: SubjectIdentity | None = None,
                          ) -> IntegrationResult:
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
            self._guard()
            if reviewed_subject is not None and observe_subject(Path(handle.path)) != reviewed_subject:
                raise WorktreeError("task changed after its byte-bound review")
            self.worktrees.autosave(handle, reason=f"integration:{task_id}")
            if reviewed_subject is not None and observe_subject(Path(handle.path)) != reviewed_subject:
                raise WorktreeError("autosave changed reviewed identity; commit before review is required")
        except WorktreeError as exc:
            return IntegrationResult(
                IntegrationOutcome.INTEGRATION_ERROR, task_id, branch,
                reason=f"autosave_refused:{type(exc).__name__}",
                base_sha=base_sha, detail={"error": str(exc)},
            )

        task_sha = _git(self.source_repo, ["rev-parse", branch]).stdout.strip()
        if reviewed_subject is not None and task_sha != reviewed_subject.head_sha:
            return IntegrationResult(IntegrationOutcome.INTEGRATION_ERROR, task_id, branch,
                                     "task_branch_moved_after_review", base_sha=base_sha)
        changed = self._changed_paths(base_sha, task_sha)

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
        self.staging_root.mkdir(parents=True, exist_ok=True)
        staging = self.staging_root / f"merge-{task_id}-{uuid.uuid4().hex[:8]}"
        try:
            return self._merge_and_verify(
                task_id, branch, base_sha, checkpoint_ref, changed, staging,
                require_rereview, reviewer, task_sha)
        finally:
            self._discard(staging)

    def _merge_and_verify(
        self, task_id: str, branch: str, base_sha: str, checkpoint_ref: str,
        changed: tuple[str, ...], staging: Path, require_rereview: bool = False,
        reviewer: Callable[[Path], ReviewReport] | None = None,
        task_sha: str | None = None,
    ) -> IntegrationResult:
        add = _git(self.source_repo, ["worktree", "add", "--detach", str(staging), base_sha])
        if add.returncode != 0:
            return IntegrationResult(
                IntegrationOutcome.INTEGRATION_ERROR, task_id, branch,
                reason="staging_worktree_failed", base_sha=base_sha,
                checkpoint_ref=checkpoint_ref, changed_paths=changed,
                detail={"stderr": add.stderr.strip()[:2000]},
            )

        if task_sha is None:
            task_sha = _git(self.source_repo, ["rev-parse", branch]).stdout.strip()
        merge = _git(staging, ["merge", "--no-ff", "--no-edit", task_sha])
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
        #
        # Read through `verification_verdict`, never off `passed`. This
        # line was `if not verification.passed`, and a third independent
        # F-34 review showed what that admits: `not 1` is `False`, so a
        # verifier whose evidence the state authority refuses would have
        # advanced the shared branch. Landing is the most irreversible
        # action in the system, so it is the last place that may guess.
        verification = self.verifier.run(staging)
        verdict = verification_verdict(verification)
        if verdict is VerificationVerdict.MALFORMED:
            return IntegrationResult(
                IntegrationOutcome.VERIFICATION_INVALID, task_id, branch,
                reason="merged_tree_verification_stated_no_verdict",
                base_sha=base_sha, merged_sha=merged_sha,
                checkpoint_ref=checkpoint_ref, changed_paths=changed,
                verification=verification,
                detail={"evidence": evidence_reason(verification)},
            )
        if verdict is not VerificationVerdict.PASSED:
            return IntegrationResult(
                IntegrationOutcome.VERIFICATION_FAILED, task_id, branch,
                reason="merged_tree_failed_verification", base_sha=base_sha,
                merged_sha=merged_sha, checkpoint_ref=checkpoint_ref,
                changed_paths=changed, verification=verification,
            )

        # The other half of convergence, re-established against the tree
        # that will actually land. ADR-0020 found that integration re-ran
        # the VERIFICATION on the merged tree and re-ran nothing of the
        # independent review — so after a base move, half the guarantee
        # was rebuilt and half was assumed. This is that half.
        rereview: ReviewReport | None = None
        gated: tuple[GatedFinding, ...] = ()
        if require_rereview and reviewer is not None:
            before = tamper_fingerprint(staging)
            rereview = reviewer(staging)
            after = tamper_fingerprint(staging)
            if after != before:
                # Rule 9, at the moment it matters most: a reviewer that
                # edited the tree it was judging has not produced
                # evidence about anything. What LANDS is the captured
                # merged_sha, so the edit cannot reach the branch — but
                # the verdict is worthless and saying so is the point.
                return IntegrationResult(
                    IntegrationOutcome.REVIEWER_MODIFIED_SUBJECT, task_id, branch,
                    reason="rereviewer_modified_the_merged_tree",
                    base_sha=base_sha, merged_sha=merged_sha,
                    checkpoint_ref=checkpoint_ref, changed_paths=changed,
                    verification=verification,
                )

            blocking, gated_list = classify_findings(
                rereview, self.convergence_policy, round_index=0)
            gated = tuple(gated_list)
            if rereview.verdict is not ReviewVerdict.PASS or blocking:
                return IntegrationResult(
                    IntegrationOutcome.REVIEW_FAILED, task_id, branch,
                    reason=f"rereview:{rereview.verdict.value}",
                    base_sha=base_sha, merged_sha=merged_sha,
                    checkpoint_ref=checkpoint_ref, changed_paths=changed,
                    verification=verification, rereview=rereview,
                    rereview_gated=gated,
                    detail={"blocking": [f.to_dict() for f in blocking]},
                )

        # Only now does the shared branch move, and only by fast-forward
        # to a commit that has already been verified: there is no moment
        # at which an observer can see a broken target.

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
        assert self.target_branch is not None
        prepared = PreparedIntegration(task_id, branch, self.target_branch, task_sha, base_sha,
            merged_sha, checkpoint_ref, changed, verification, rereview, gated)
        self._guard()
        # Keep the verified commit reachable after staging cleanup/process death.
        # The rollback checkpoint names the old base; this ref preserves the new
        # commit whose verification is about to be durably recorded.
        keep = _git(self.source_repo, ["update-ref",
            f"refs/gnosis/prepared/{task_id}/{merged_sha}", merged_sha])
        if keep.returncode != 0:
            return IntegrationResult(IntegrationOutcome.INTEGRATION_ERROR, task_id, branch,
                                     "prepared_commit_could_not_be_retained", base_sha=base_sha)
        if self.on_prepared is not None:
            self.on_prepared(prepared)
        return self._advance_prepared(prepared, already_gated=True)

    def resume_prepared(self, prepared: PreparedIntegration) -> IntegrationResult:
        """Complete an already verified merge from a trusted durable receipt."""
        self._guard()
        with FileLock(lock_path_for(self._lock_path()), timeout_s=self.lock_timeout_s):
            return self._advance_prepared(prepared)

    def _advance_prepared(self, prepared: PreparedIntegration, *,
                          already_gated: bool = False) -> IntegrationResult:
        self._guard()
        def refused(reason: str) -> IntegrationResult:
            return IntegrationResult(IntegrationOutcome.INTEGRATION_ERROR,
                prepared.task_id, prepared.branch, reason, base_sha=prepared.base_sha,
                merged_sha=prepared.merged_sha, checkpoint_ref=prepared.checkpoint_ref,
                changed_paths=prepared.changed_paths, verification=prepared.verification)

        if (verification_verdict(prepared.verification) is not VerificationVerdict.PASSED
                or prepared.branch != self.worktrees.planned_branch(prepared.task_id)
                or prepared.target_branch != self.target_branch
                or self._current_branch() != self.target_branch):
            return refused("prepared_integration_identity_or_evidence_invalid")
        if prepared.rereview is not None:
            blocking, _ = classify_findings(prepared.rereview, self.convergence_policy, 0)
            if prepared.rereview.verdict is not ReviewVerdict.PASS or blocking:
                return refused("prepared_integration_review_invalid")
        for sha in (prepared.task_sha, prepared.base_sha, prepared.merged_sha):
            if len(sha) not in (40, 64) or any(c not in "0123456789abcdef" for c in sha):
                return refused("prepared_integration_commit_invalid")
        retained = _git(self.source_repo, ["rev-parse",
            f"refs/gnosis/prepared/{prepared.task_id}/{prepared.merged_sha}"])
        if retained.returncode != 0 or retained.stdout.strip() != prepared.merged_sha:
            return refused("prepared_merge_retention_ref_changed")
        if _git(self.source_repo, ["rev-parse", prepared.branch]).stdout.strip() != prepared.task_sha:
            return refused("task_branch_moved_after_preparation")
        for parent in (prepared.task_sha, prepared.base_sha):
            if _git(self.source_repo, ["merge-base", "--is-ancestor", parent,
                                      prepared.merged_sha]).returncode != 0:
                return refused("prepared_merge_does_not_include_its_inputs")
        # A crash after the advance needs no second merge or re-verification.
        # The original verified commit must actually be in the target history.
        if _git(self.source_repo, ["merge-base", "--is-ancestor", prepared.merged_sha,
                                  "HEAD"]).returncode == 0:
            self._guard()
            return prepared.completed()
        evidence = capture_git_evidence(self.source_repo)
        if evidence.head_sha != prepared.base_sha or evidence.status_porcelain.strip():
            return refused("integration_target_changed_after_preparation")
        if not already_gated:
            # A fresh merge was gated before preparing it. A recovered merge
            # must ask again in the new controller/configuration context.
            refusal = self._gate(prepared.task_id, prepared.branch, prepared.base_sha,
                                 prepared.changed_paths)
            if refusal is not None:
                return refusal
        self._guard()
        advance: subprocess.CompletedProcess[str] | None = None

        def commit() -> None:
            nonlocal advance
            advance = _git(self.source_repo, ["merge", "--ff-only", prepared.merged_sha])

        if self.scope is not None:
            self.scope.commit(commit)
        else:
            commit()
        assert advance is not None
        if advance.returncode != 0:
            return IntegrationResult(
                IntegrationOutcome.INTEGRATION_ERROR, prepared.task_id, prepared.branch,
                reason="fast_forward_failed", base_sha=prepared.base_sha,
                merged_sha=prepared.merged_sha, checkpoint_ref=prepared.checkpoint_ref,
                changed_paths=prepared.changed_paths, verification=prepared.verification,
                detail={"stderr": advance.stderr.strip()[:2000]},
            )
        self._guard()
        return prepared.completed()

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

    def preview_head(self) -> tuple[str | None, None]:
        """The target's current head, for a caller checking plan freshness."""
        evidence = capture_git_evidence(self.source_repo)
        return (evidence.head_sha if evidence.is_repo else None), None
    def preview(self, task_id: str) -> tuple[str | None, tuple[str, ...]]:
        """(base_sha, changed_paths) for a task, touching nothing.
        Planning needs the same change set integration will land, and a
        planner that had to integrate in order to learn it would not be a
        planner.
        Two things this had to learn, both from independent review:
        **The base is the task's FORK POINT, not the target's head.**
        Reporting the head made `base_sha == head` true by construction,
        so a planner asking "did the target move since this was
        reviewed?" always heard no — the one question the ordering
        mechanism exists to answer, structurally unanswerable through its
        own data path.
        **Committed work is not enough.** Agents leave their work
        UNCOMMITTED and `integrate` autosaves it, so a preview of the
        committed diff reported nothing at all for a freshly worked task
        and any planner reading it saw no paths and therefore no overlap.
        Verified: two tasks both rewriting `lib.py` planned as disjoint.
        """
        evidence = capture_git_evidence(self.source_repo)
        if not evidence.is_repo or evidence.head_sha is None:
            return None, ()
        branch = self.worktrees.planned_branch(task_id)
        merge_base = _git(self.source_repo, ["merge-base", evidence.head_sha, branch])
        if merge_base.returncode != 0:
            return None, ()
        fork_point = merge_base.stdout.strip()
        paths = set(self._changed_paths(fork_point, branch))
        paths.update(self._uncommitted_paths(task_id))
        return fork_point, tuple(sorted(paths))
    def _uncommitted_paths(self, task_id: str) -> tuple[str, ...]:
        """What the agent has changed but not committed, from the worktree.
        `-z` for the same reason `content_fingerprint` needs it: plain
        porcelain C-quotes any non-ASCII path, and a planner that cannot
        read a filename cannot reason about overlap on it.
        """
        try:
            worktree = Path(self.worktrees.load_handle(task_id).path)
        except (WorktreeError, FileNotFoundError, OSError):
            return ()
        if not worktree.exists():
            return ()
        proc = _git(worktree, ["status", "--porcelain", "-z",
                               "--untracked-files=all"])
        if proc.returncode != 0:
            return ()
        found = [entry[3:] for entry in proc.stdout.split(NUL) if len(entry) > 3]
        return tuple(sorted(set(found)))
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
        if not self.staging_root.exists():
            return
        for candidate in self.staging_root.glob("merge-*"):
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
            root = self.staging_root.resolve()
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
