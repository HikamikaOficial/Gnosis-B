# ADR-0021 — Re-review as evidence: replacing an expired verdict, not waiving it

- Status: ACCEPTED
- Date: 2026-08-21
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `.gnosis/evidence/20260821T125747Z/`;
  `tests/test_integration.py::TestRereviewIsEvidence` (9 tests) plus the
  gate-ordering test beside it; 672 passed; mypy strict clean over 53
  files.
- Independent review: **done, 2026-08-21, verdict FAIL** — Codex,
  read-only. Five findings, two critical; all repaired or recorded. See
  the addendum.
- Builds on: ADR-0020 (which found the expiry), ADR-0018 (landing),
  ADR-0008 (what convergence means).

## Context

ADR-0020 established L-0027: "converged" is two pieces of evidence —
deterministic verification AND an independent review — and when the
target branch moves, integration re-runs the verification on the merged
tree and re-runs **nothing** of the review. It surfaced that as
`review_still_applies`, and left exactly one way past it: an operator
authorising a task id. That records a **decision**, not a verdict.

## Decision

**A re-review runs the independent reviewer against the merged tree,
before the fast-forward.** That tree is the one that will land, so the
verdict is evidence about the thing being decided rather than about a
tree that no longer exists. Both halves of convergence are then
re-established against the same object.

### Staleness is derived, never asserted by the caller

The integrator computes it: the task's fork point (`merge-base`) against
the target's current head. The first version took `require_rereview` as a
parameter defaulting to `False`, which meant the public API's default
landed an expired review in silence and every direct caller was one
forgotten argument away from the hole this ADR exists to close (addendum
1). The caller can now only **waive**, explicitly, per task.

### The same blocking rule as convergence

`classify_findings` is extracted from `ConvergenceLoop` and used by both.
A finding that blocked convergence but not landing — or the reverse —
would be a contradiction an operator could only discover by experiment.
Non-blocking findings are gated, not lost, and ride on the result.

### Rule 9 at the moment it matters most

The re-reviewer runs inside the staging worktree that is about to be
fast-forwarded. The tree is fingerprinted either side of the call and a
reviewer that moved it is refused. What LANDS is the captured
`merged_sha`, so a tampering reviewer cannot reach the branch — but its
verdict is worthless, and saying so is the point.

### The reviewer is built per task and passed per call

Never assigned onto the shared integrator. The closure captures
`task_id` for its policy identity and its evidence directory, so an
integrator that kept the first one would have gated and recorded every
later task's re-review under the **first** task's name. Found by
self-review before the verdict; the general form is that mutating shared
state to carry per-call context is how identities get crossed.

### It is a launch like any other

The pipeline builds it through `GatedAgentRunner`: gated at its own
intervention point (`integration_rereview` — approving a convergence
review is not approving the re-judging of a merged tree), held by the
rate-limit plane, and charged to the brief's budget. A refusal or a hold
is caught by the pipeline and reported as an escalation or a park, not
left to escape after convergence has already been paid for.

## Known limitations (stated, not implied)

- **The kernel cannot verify that a verdict came from an independent
  agent.** `re_reviewer` is an injected callable returning a
  `ReviewReport`, exactly like convergence's `review_fn`; a caller could
  fabricate, cache or self-author a PASS. Provenance comes from *how* the
  caller builds it — the pipeline builds it from `CliReviewer` behind the
  gate — and the kernel does not check that. Recorded as
  `integration/rereview_provenance = IGNORED`.
- **The rule-9 check covers the tree being judged, not the process.** A
  reviewer that writes to the SOURCE checkout, to a sibling task's
  worktree, or anywhere else it can reach is not detected. That needs the
  sandbox boundary; the matrix note on
  `convergence/reviewer_read_only` now says so explicitly.
- **A waiver is still available**, per task. It is now the exception
  rather than the only route, which is the point: an escape hatch that is
  the sole path becomes the default.
- **One re-review, no loop.** A failing re-review stops the landing; it
  does not start a fix round. Feeding integration-time findings back into
  convergence is a larger design and this ADR does not take it.

## Codex review addendum (2026-08-21, independent, verdict FAIL)

Five findings. Transcript:
`.gnosis/lab/kernel-reviews/codex-review-2026-08-21-rereview.jsonl`.

1. *(critical, repaired)* **Two bypasses.** `WorkIntegrator.integrate`
   defaulted `require_rereview=False`, so a direct call landed an expired
   review without one; and the waiver path asked for no verdict at all.
   Staleness is derived by the integrator now, so the default is safe and
   the waiver is an explicit, per-task exception.
2. *(critical, recorded)* **An arbitrary callable can fabricate a PASS.**
   True, and it is the same shape as every other injected evidence
   producer in this kernel. It cannot be fixed by a type; it is recorded
   in the enforcement matrix as `rereview_provenance = IGNORED` rather
   than left for someone to discover.
3. *(major, repaired)* **Not budgeted, and its refusals escaped.** The
   `GatedAgentRunner` was built without the brief's ledger — while a
   comment claimed the launch was "gated, budgeted, held" — and a
   `CredentialHeld` or `LaunchRefused` from it escaped `_integrate`,
   stranding a brief after convergence had already been paid for. Both
   fixed.
4. *(major, recorded)* **The tamper check does not bound the process.** A
   reviewer can write outside the staging tree. The matrix note now says
   what the check covers and what it does not.
5. *(minor, resolved)* Comments cited "ADR-0021" while the governing
   decision was ADR-0020. This ADR is 0021, which makes them accurate —
   intended, but only correct once written.

**Found by self-review before the verdict:** the pipeline assigned
`integrator.re_reviewer` once and only when unset, so every later task's
re-review would have run under the first task's identity — wrong policy
snapshot, wrong evidence directory.

Codex confirmed the blocking rule is genuinely shared with convergence
(one `classify_findings`), and that fast-forwarding the captured
`merged_sha` does keep a detected staging edit off the branch.
