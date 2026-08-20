# ADR-0015 — Real reviewer/fixer adapters for the convergence loop (adapter milestone, 3/4)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_cli_review_adapters.py` (33 tests); suite
  521/521; mypy strict clean; ruff clean on every file this ADR touches.
- Builds on: ADR-0008 (the loop), ADR-0014 (the runner a loop can be
  recorded through), ADR-0011 (the enforcement matrix).
- Independent review: **not yet done.** Codex is `RATE_LIMITED` until
  2026-09-19 (see NEXT_ACTIONS 1). Stated here rather than left implied,
  because every previous unit in this sequence had findings.

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
- The reviewer's fingerprint covers git-visible state. A reviewer that
  wrote outside the repository, or to an ignored path, is not detected
  here — that needs the sandbox boundary, which the matrix already
  records as unsolved.
- Nothing yet *assembles* a convergence loop from a Director brief. The
  adapters are constructible and tested against the real loop, but the
  brief → loop → report path is the integration milestone's decision.
