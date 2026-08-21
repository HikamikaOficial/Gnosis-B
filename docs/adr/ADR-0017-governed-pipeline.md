# ADR-0017 — One brief, one governed and recorded convergent run (integration milestone)

- Status: ACCEPTED
- Date: 2026-08-21
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `.gnosis/evidence/20260821T004647Z/` (captured argv, exit
  codes and output); `tests/test_pipeline.py` (23 tests); 589 passed;
  mypy strict clean over 49 files; ruff at the recorded backlog baseline.
- Independent review: **done, 2026-08-21, verdict FAIL** — Codex,
  read-only. Seven findings, two critical; all repaired. See the
  addendum.
- Builds on: ADR-0013 (the gate), ADR-0014 (record/replay), ADR-0015
  (reviewer/fixer adapters), ADR-0016 (the hold plane), ADR-0008 (the
  convergence loop).

## Context

The adapter milestone left four real mechanisms with production callers
and **no path that runs a real request through all of them**. That is
Directive 9's shape one level up: each unit is wired, the system is not.

## Decision

`GovernedPipeline.run_brief` is that path:

    brief
      -> TaskScheduler        (is the credential's window open?)
      -> TaskEngine           (policy gate, worktree isolation, retries,
                               typed classification, durable evidence)
      -> ConvergenceLoop      (verify -> independent review -> fix, bounded)
           with CliReviewer / CliFixer behind a GatedAgentRunner
      -> EngineerReport       (one status covering BOTH halves)

### Convergence launches agents, so convergence is gated

The reviewer and the fixer run once per round — usually **more agent
launches than the implementation itself**. Before this, the gate covered
the implementation launch and nothing else, which is a worse position
than an ungated system: it reads as governed. `GatedAgentRunner` wraps
the runner the adapters use and consults, per launch, the hold plane
first (a shut window parks the round rather than burning it) and then the
policy engine — and reports each result back to the hold plane
afterwards, because a rate limit hit by a review round used to be
invisible to it (self-review, below).

"Every launch" means **every agent launch**. Verifier subprocesses are
deliberately outside: a policy able to deny verification could switch off
the very evidence requirement that makes a DONE claim checkable, and a
verifier is operator-configured rather than agent-chosen. The enforcement
matrix records that as `convergence/verifier_execution = IGNORED` rather
than leaving it to be discovered.

The snapshot it builds comes from `agent_launch_snapshot`, **extracted
from the engine so there is exactly one**. Two gates with two snapshot
builders would mean an operator approving two different identities for
what is, to them, one decision — and the two would drift apart on the
first field either side forgot to add.

### The reviewer must not be the implementer

Rule 10 says INDEPENDENT BEFORE INTERACTION, and nothing enforced it:
`reviewer_id` was a label, so the implementing agent could review its own
work and produce a COMPLETED report. The pipeline now refuses the same
runner OBJECT for both halves at construction.

That is a partial guarantee and the matrix says so
(`convergence/reviewer_independence = SANDBOX_APPROX`): the kernel can
catch the degenerate case an operator reaches by accident, and it cannot
verify that two different objects are two different minds. Same provider,
same model, different process is still weak independence.

### The report cannot say COMPLETED unless convergence converged

The implementation half can succeed while the review half finds blocking
defects. That is the normal case and the whole reason the loop exists.
`_status_for` reads only the convergence outcome; the implementation's
own verdict never sets the status, because a task closing on the opinion
of the agent that did the work is the first thing ADR-0008 forbids.

### A refused review is a governance event, not an exhausted loop

`ConvergenceLoop` catches everything `review_fn` raises and files it as
evidence collection failing — correctly, since no verdict was collected.
But a policy refusal and a crashed reviewer demand different answers, and
reporting the former as a routine `ROUNDS_EXHAUSTED` would hide it. The
pipeline inspects the loop's typed `evidence_failures` (ADR-0015 finding
5) and maps `LaunchRefused` to `ESCALATION_REQUIRED` carrying the
policy's own reason code, `CredentialHeld` to a park.

### A park is not a failure anywhere along the path

A held credential before the implementation, or during a fix round,
parks the brief with its work intact. `BriefRecordState.PARKED` is new,
because the state was previously inexpressible and writing it as FAILED
would lose the resumability *and* charge a provider's window to the
agent (rules 6 and 7).

### Convergence reviews the worktree

The implementation's changes are in `gnosis/<task_id>`, not in the source
tree. Reviewing the source repo would judge code nobody wrote and report
a clean bill for work that never happened. Pinned by a test that asserts
the reviewer's `cwd` is the worktree and is not the source repo.

## Known limitations (stated, not implied)

- **Independence is checked, not proved.** See above: object identity
  only.
- **Verifier subprocesses run outside the gate and the hold**, on
  purpose. Recorded in the enforcement matrix.
- **A permanent review refusal still consumes the round budget.** The
  loop cannot know that a DENY will deny again, so it retries up to
  `max_rounds` before the pipeline maps the refusal to an escalation. It
  is bounded (rule 8) and launches nothing, but the round records
  describe rounds that could never have succeeded.
- **One brief at a time, synchronously.** `run_pending` iterates; there
  is no concurrency, no queue and no cross-brief scheduling. That is the
  multi-worker milestone.
- **The worktree is not integrated.** A COMPLETED brief leaves reviewed
  work on `gnosis/<task_id>`; merging it is the integration-of-results
  decision this ADR does not make (ADR-0007 deliberately leaves branch
  destruction and merge to a later milestone).
- **No wall-clock or token budget across the whole pipeline.** Each loop
  is bounded by `max_rounds` and each run by `max_attempts`, but nothing
  bounds a brief's total cost. A budget belongs with the scheduler that
  owns a work list.
- **`recording_orchestrator`'s cassette is not threaded through here.**
  The pipeline accepts any runner, so a `ReplayingCLIRunner` composes,
  but nothing in the pipeline *arranges* record/replay for a whole brief
  — including the convergence launches, which would need the cassette to
  span both halves.

## Codex review addendum (2026-08-21, independent, verdict FAIL)

Seven findings. Transcript:
`.gnosis/lab/kernel-reviews/codex-review-2026-08-21-pipeline.jsonl`.

1. *(critical, repaired)* **A COMPLETED report could follow the
   implementing agent reviewing its own work.** Nothing established
   independence; `reviewer_id` was only a label. The reviewer named it
   precisely: my own test fixture used one `_Agent` for both halves,
   which is why nothing noticed. The pipeline refuses the same runner
   object now, the fixture uses a separate implementer, and the matrix
   records how partial that guarantee is.
2. *(critical, repaired)* **A crashing fixer stranded a consumed brief.**
   ADR-0008 lets `fix_fn` exceptions propagate on purpose — this pipeline
   is the caller that was supposed to catch them, and it caught only the
   two refusal types. The brief stayed `IN_PROGRESS` with no report and
   no evidence. Repairing it exposed a second instance of the same shape:
   `_exec_root` was called OUTSIDE the guard, so its (new, correct)
   refusal escaped `run_brief` the same way. Both are inside now.
3. *(major, repaired)* **Convergence verdicts were not durably recorded.**
   `GatedAgentRunner.decisions` was transient and nothing consumed it, so
   an operator could not prove which review or fix launches were
   authorised — in a path this ADR calls governed *and recorded*, and
   after ADR-0013 established that an allowed action is evidence too.
   They are written into `convergence.json` now.
4. *(major, repaired)* **A report for a brief that never ran carried
   `<task_id>-no-run`** — a string shaped like a run id that resolves to
   nothing, beside a comment saying inventing such a reference was the
   thing to avoid. The marker is now unmistakably not an id.
5. *(major, repaired)* **A lost worktree handle silently fell back to the
   source repository.** That was the dangerous branch: the reviewer *and
   the fixer* would have run in the shared tree, and a PASS there would
   have reported COMPLETED for code nobody looked at. It raises now;
   failing closed costs a brief, falling back costs the guarantee.
6. *(major, claim corrected)* **Verifier subprocesses run outside the
   gate and the hold.** True, and deliberate — see above — but the ADR
   claimed the gate covered "every launch a brief causes", which was
   false. Corrected here and recorded in the enforcement matrix.
7. *(major, repaired)* **Calling `run_brief` twice for one brief id
   overwrote the record**, orphaning the first task's runs and report.
   `run_pending` dedups through the inbox claim; the public method did
   not. A brief whose record is still live is refused; one that finished
   or parked may legitimately be resubmitted.

**Found by self-review before the verdict arrived**, and worth recording
because it is the same class: a rate limit hit by a *review* round never
reached the hold plane. The reviewer's output was unparseable, the loop
filed `INVALID_AGENT_OUTPUT`, no hold was placed, and the next round
launched straight into the same shut window — a rule 6 violation created
purely by composition, where each part was correct alone.
