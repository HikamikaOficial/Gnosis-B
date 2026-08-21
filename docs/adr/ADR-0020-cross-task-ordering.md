# ADR-0020 — Cross-task ordering, and the review that expires when the base moves

- Status: ACCEPTED
- Date: 2026-08-21
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `.gnosis/evidence/20260821T024656Z/`;
  `tests/test_ordering.py` (19 tests); 662 passed; mypy strict clean over
  53 files.
- Independent review: **done, 2026-08-21, verdict FAIL** — Codex,
  read-only. Nine findings, three critical; all repaired or corrected.
  See the addendum.
- Builds on: ADR-0018 (landing), ADR-0019 (the queue), ADR-0008
  (what "converged" means).

## Context

ADR-0018 made landing safe *after the fact*: nothing reaches the shared
branch that did not pass verification on the merged tree. The second of
two conflicting tasks still spends an entire convergence loop before
discovering it cannot land. ADR-0019's Known limitations named the gap:
nothing decides which of several ready tasks lands first.

## Decision

### The real output is not an order

Ordering saves some wasted rounds. What this module is actually for is a
question nobody had asked:

**"Converged" is two pieces of evidence — deterministic verification AND
an independent review — and when the target moves, integration re-runs
the verification and re-runs nothing of the review.** A review is
evidence about a specific tree; the reviewer judged that this change was
correct in the tree it was shown. Once the base moves, that judgement is
about a tree that no longer exists. Half the convergence guarantee was
silently re-established and half was silently assumed.

So every planned landing carries `review_still_applies`, and only a task
that forked from the CURRENT head and lands FIRST gets `True`. That is
deliberately inconvenient: it says a batch of converged tasks is not a
batch of landable tasks.

`LandingCoordinator` acts on it — refusing a stale-review landing by
default — and `GovernedPipeline` routes its landings through the
coordinator, so the gate exists on the path real briefs take rather than
in a module only its own tests import.

### What path overlap is, exactly

Two tasks touching the same file. Not a probability of conflict — git
merges by hunk and two edits to one file routinely combine cleanly — and
nothing whatever about semantic breakage. ADR-0018's headline test is a
semantic break between tasks with **disjoint** paths, and no ordering
built on path names can catch it. `test_ordering_cannot_save_a_semantic
_conflict` pins that limitation so a later change cannot quietly claim
more.

### Planning is pure; landing checks it is still true

`plan_landings` is a function of (head, tasks): same inputs, same plan,
recomputable later from recorded evidence. FIFO among equals with ties
broken by task id, because ordering by "smallest diff" or "fewest
conflicts" would starve large or unlucky tasks and nothing here has
evidence that would justify that.

`land` re-reads the live head first and refuses the whole plan if it
moved, because every `review_still_applies=True` in a stale plan is
about a tree that no longer exists.

## Known limitations (stated, not implied)

- **Ordering prevents nothing.** It reduces wasted rounds and it reports
  review staleness. Post-merge verification remains the only thing that
  decides whether work may land.
- **There is no re-review mechanism.** A stale task can be authorised by
  task id (`stale_review_authorised`), which records an operator's
  decision but not a new review. Representing re-review as evidence —
  a second verdict against the new tree — is the honest next step and
  this ADR does not take it.
- **`preview` reads the fork point and the worktree's uncommitted paths**,
  which is what will land; it does not know what the REVIEWER actually
  saw. If an agent changed the worktree after its review, the plan
  describes the right change set and the wrong reviewed tree.
- **One landing per plan.** After the first, the plan is stale by
  construction and the caller re-plans. Cheap, and honest.
- **No batching across repositories**, no priority, no fairness beyond
  FIFO.

## Codex review addendum (2026-08-21, independent, verdict FAIL)

Nine findings. Transcript:
`.gnosis/lab/kernel-reviews/codex-review-2026-08-21-ordering.jsonl`.

1. *(critical, repaired)* **The central claim was structurally
   unanswerable.** `preview()` returned the SOURCE's current head as
   `base_sha`, not the task's fork point — so `base_sha == head` was true
   by construction, `review_still_applies` was always True for the first
   entry, and STALE_BASE could never fire through the real data path. The
   one question the module exists to answer could not be asked with its
   own inputs. My tests missed it entirely because they fed
   `plan_landings` synthetic bases and never went through `preview`.
   `merge-base` now gives the real fork point, verified end to end.
2. *(critical, repaired)* **The pipeline bypassed the gate.**
   `GovernedPipeline._integrate` called `integrator.integrate` directly;
   `LandingCoordinator` was referenced only by its own tests — Directive
   9's parallel fiction again, in a module whose docstring called the
   coordinator "the production caller". Ordinary landings kept exactly
   the silent stale-review behaviour this ADR claims to prevent.
3. *(critical, repaired)* **A plan could be honoured after its head
   moved.** `land` did not compare `plan.head` with the live head, so a
   `review_still_applies=True` computed minutes earlier was acted on
   against a different tree. The whole plan is now refused
   (`PLAN_SUPERSEDED`) rather than partially trusted.
4. *(major, already repaired)* **Planning saw a different change set than
   landing.** `preview` reported only committed work while `integrate`
   autosaves first, so a freshly worked task previewed as touching
   *nothing* and any overlap signal was blind in the normal case. Found
   by self-review before the verdict, verified with two tasks both
   rewriting `lib.py` planning as disjoint.
5. *(major, repaired)* **`allow_stale_review` was a global switch.** One
   boolean made every stale entry eligible at once and recorded no
   decision about any particular task, which pressures the opt-out into
   being the default. It is now a set of task ids an operator has
   explicitly re-reviewed.
6. *(minor, repaired)* `converged_at` accepted `NaN`, which compares
   neither less nor greater — so a stable sort let INPUT ORDER decide a
   plan the docstring promises is deterministic.
7. *(minor, repaired)* Duplicate task ids planned as two entries, so a
   task could be reported as overlapping itself and integrated twice in
   one pass.
8. *(minor, repaired)* One precedence-selected `reason` concealed the
   others: a task both path-overlapping and stale-based showed only
   PATH_OVERLAP, letting an operator read a merge-risk signal where there
   was also a review-evidence failure. All applicable reasons are
   reported now.
9. *(minor, claims corrected)* "Overlapping paths mean a likely TEXTUAL
   conflict" was unsupported — the code compares path names and makes no
   probability assessment — and "the integrator will hit it anyway" is
   false for entries the coordinator skips without merging. Both
   rewritten.

Codex found no unbounded loop in `land`, and confirmed that a missing
`convergence_for` entry is not silently landed (`integrate` returns
NOT_CONVERGED) and that the integrator's lock plus pre-advance head check
do protect the branch — they simply cannot rescue review evidence, which
is what this module adds.

## A note on the suite

One run during this work failed
`test_autosave_refuses_each_sequencer_state_individually` with
`Permission denied` writing a git object — the L-0002 Windows
file-handle class, already recorded in ADR-0013's test-suite note. Four
isolated re-runs and a full re-run passed. Recorded rather than
dismissed.
