# ADR-0015 — Real reviewer/fixer adapters for the convergence loop (adapter milestone, 3/4)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_cli_review_adapters.py` (39 tests); suite
  527/527; mypy strict clean; ruff clean on every file this ADR touches.
- Builds on: ADR-0008 (the loop), ADR-0014 (the runner a loop can be
  recorded through), ADR-0011 (the enforcement matrix).
- Independent review: **not done.** Codex is `RATE_LIMITED` until
  2026-09-19 and the internal reviewer agents died on usage credits (see
  NEXT_ACTIONS 1). Self-review only, which found three real defects
  including a critical one — recorded in the addendum below. Stated
  plainly because every previous unit in this sequence had findings, and
  a unit reviewed only by its author should be read as such.

## Context

ADR-0008 built the convergence loop with `review_fn`/`fix_fn` as
injected callables and a note that real adapters were future work.
Nothing ever supplied them, so the loop had only ever judged
deterministic fakes. Third of the four unwired mechanisms.

## Decision

`gnosis/adapters/` is a new package: provider-specific translation lives
there and **nothing under `kernel/` imports from it**. That is what makes
"provider-neutral by adapters" checkable rather than aspirational.

`CliReviewer` is a `review_fn`; `CliFixer` is a `fix_fn`. Both take an
`AgentRunner` protocol narrow enough that `ReplayingCLIRunner` satisfies
it, so an entire convergence loop can be recorded and replayed.

### A reviewer never modifies what it judges, and we do not take its word

Rule 9 is enforced twice, deliberately at two different strengths. The
review agent runs with edit tools withheld (`--permission-mode=plan`),
which is the provider's promise. Then `CliReviewer` fingerprints the
workspace **before and after** and raises `ReviewerModifiedSubject` if
the tree moved — the kernel's own evidence. The check runs *before* the
output is parsed, because deciding whether to care about tampering after
reading what the tamperer said is not a check.

The fingerprint is `content_fingerprint`, not `workspace_fingerprint`,
and the difference is the whole check — see addendum finding 1.

The matrix records the honest level: `convergence/reviewer_read_only =
SANDBOX_APPROX`. Detection after the fact is not prevention.

### An unreadable review is not a verdict

`InvalidReviewOutput` is raised, and `ConvergenceLoop` already treats a
`review_fn` failure as evidence collection failing: the round cannot
converge and cannot count toward stalemate. The tempting alternative —
returning `UNCERTAIN` — would erase the difference between a reviewer
that thought about the code and one that crashed, and `UNCERTAIN` is a
verdict an agent can deliberately give.

Everything in the payload is validated: an unknown verdict or severity,
a non-list `findings`, an empty description, a confidence outside
`[0,1]`, or `"confidence": true` (which would otherwise become 1.0 —
maximum confidence from a value that expressed none). The **reviewer
attribution comes from the adapter, never from the payload**, so an
agent cannot sign its findings as somebody else.

What the adapter does *not* do is correct the agent. A `PASS` carrying a
`CRITICAL` is passed through intact: the kernel decides what blocks
(`blocking_severities`, the confidence floor), and quietly reconciling a
verdict with its findings here would hide the disagreement the loop
exists to surface.

### An unreadable *fix* report is inconclusive, not `cannot_fix`

Asymmetric with the reviewer, on purpose. `cannot_fix` **ends the loop**;
asserting it from output nobody could parse would stop on no evidence at
all. Meanwhile the fixer may well have changed the repository, and the
next round's verification and review are what decide anyway. So an
unreadable fix round reports "it ran, it claims nothing", which costs one
more round and cannot fake progress. `claims_done` is read with `is True`
— a truthy string is not a claim of doneness.

## Known limitations (stated, not implied)

- Only a Claude-Code-shaped envelope is understood (`parsed_json["result"]`,
  with raw stdout as fallback). A Codex reviewer needs its own message
  extractor over `--json` JSONL; the parser and the read-only check are
  already provider-agnostic, so that is an extractor, not a redesign.
- The reviewer's fingerprint covers git-visible state: tracked content
  (via the full patch), and every untracked file's bytes. A reviewer that
  wrote **outside the repository, or to a `.gitignore`d path**, is not
  detected — `git status` does not list ignored files and enumerating
  them means walking the tree. That needs the sandbox boundary, which the
  matrix already records as unsolved.
- Nothing yet *assembles* a convergence loop from a Director brief. The
  adapters are constructible and tested against the real loop, but the
  brief → loop → report path is the integration milestone's decision.

## Self-review addendum (2026-08-20)

With both independent reviewers unavailable, I red-teamed the module
against the attack surfaces I had written into their briefs. Three real
defects, one critical:

1. *(critical)* **The rule-9 check was blind in the case that matters.**
   It used `workspace_fingerprint`, which hashes `git status --porcelain`
   — and a file already listed as ` M code.py` keeps that exact status
   line however many more times it is rewritten. `diff --stat` is no
   better: any same-length edit keeps "1 insertion(+), 1 deletion(-)".
   During convergence a fix round has *always* already dirtied the tree,
   so this was not an edge case, it was the normal path. Reproduced
   directly: across a reviewer rewriting a tracked file, both probes were
   byte-identical. `content_fingerprint` now hashes the actual patch plus
   every untracked file's bytes, and the old fingerprint's blindness is
   pinned by a test that fails against it.
2. *(major)* `agent_message_text` read stdout unbounded, so an agent that
   dumped a build log could make a review round pull an arbitrarily large
   file into memory. Bounded at `MAX_AGENT_MESSAGE_CHARS`.
3. *(minor)* `extract_json_object` considered only the **last** balanced
   object, so anything brace-shaped appended after the answer — a
   signature, a tool trace — pushed the real review out of reach and
   turned a good round into INVALID. It now considers every top-level
   object, latest first, and prefers one that names a verdict.

A self-review is weaker evidence than an independent one and this does
not substitute for the parked Codex pass. It does show the same thing
every round of this project has shown: the defects are found by asking
"what would a hostile input do here", not by rereading the code.
