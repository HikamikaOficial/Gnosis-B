# ADR-0015 — Real reviewer/fixer adapters for the convergence loop (adapter milestone, 3/4)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_cli_review_adapters.py` (39 tests); suite
  527/527; mypy strict clean; ruff clean on every file this ADR touches.
- Builds on: ADR-0008 (the loop), ADR-0014 (the runner a loop can be
  recorded through), ADR-0011 (the enforcement matrix).
- Independent review: **done, 2026-08-21, verdict FAIL** — Codex,
  read-only, after the operator restored its quota. Eight findings, all
  adjudicated; see the second addendum. The self-review addendum below it
  is kept as written, because what a self-review missed is itself
  evidence about self-review.

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

Every field the verdict depends on is validated: an unknown verdict or
severity, a non-list `findings`, an empty description, a confidence
outside `[0,1]`, `"confidence": true` (which would otherwise become 1.0 —
maximum confidence from a value that expressed none), and **duplicate
keys**, since `json.loads` silently keeps the last one and
`{"verdict":"FAIL","verdict":"PASS"}` would read as PASS. Optional
descriptive fields (`category`, `notes`) are coerced rather than
rejected — they carry no decision. The **reviewer attribution comes from
the adapter, never from the payload**, so an agent cannot sign its
findings as somebody else.

The object is taken only from a **fenced block or the whole message**.
An object merely embedded in prose is refused: there is no syntactic
signal separating an agent submitting a verdict from one quoting the
schema while declining to give one (addendum 2, finding 1).

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
- The reviewer's fingerprint (`tamper_fingerprint`) covers tracked
  content via the full patch, every untracked file's bytes, and the
  repository's own machinery (hooks, config). It does **not** cover files
  **outside the repository** or on a **`.gitignore`d path** — `git
  status` does not list ignored files and enumerating them means walking
  the tree. That needs the sandbox boundary, which the matrix records as
  unsolved.
- **Two snapshots prove equal endpoints, not an untouched interval.** A
  reviewer that modifies a file, uses the altered state, and restores the
  original bytes before returning is not detected. This is inherent to
  before/after comparison and cannot be closed by a better fingerprint;
  it needs filesystem-level auditing. Stated because the ADR previously
  implied more than the mechanism delivers.
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

## Codex review addendum (2026-08-21, independent, verdict FAIL)

Eight findings. Transcript:
`.gnosis/lab/kernel-reviews/codex-review-2026-08-21-convergence-adapters.jsonl`.

1. *(major, repaired)* **An object quoted inside prose parsed as a
   verdict.** `"I refuse to submit a review. The requested example was:
   {"verdict":"PASS"}"` returned PASS. The leniency was reading intent
   the parser cannot see, in the one place this module exists to be
   strict about. Only fenced blocks and whole-message JSON are accepted
   now; an agent that cannot follow the format gets INVALID, which costs
   a round and fails closed.
2. *(major, repaired)* **Duplicate JSON keys.** `json.loads` keeps the
   last, so `{"verdict":"FAIL","verdict":"PASS"}` read as PASS and a
   finding could downgrade its own severity the same way. Rejected via
   `object_pairs_hook`.
3. *(major, repaired)* **A rule-9 bypass that needed only an accent.**
   `git status --porcelain` C-quotes non-ASCII paths (`?? "cafÃ©.txt"`).
   The parser stripped quotes but did not decode the escaping, failed to
   read the file, and stored that failure as a **stable** `unreadable:`
   string — so the file's bytes were never hashed and a reviewer could
   edit it freely. Reproduced directly. Fixed with `-z`, which is
   NUL-separated and never quotes.
4. *(major, accepted and documented)* **Modify-then-restore is not
   detected.** Two snapshots establish equal endpoints, not an untouched
   interval, and the untrusted reviewer controls what happens between
   them. No fingerprint closes this; filesystem auditing would. Now in
   Known limitations rather than implied away.
5. *(major, repaired)* **Typed failures collapsed into prose.**
   `InvalidReviewOutput`, `ReviewerModifiedSubject`, a crashed verifier
   and a broken git probe all became one indistinguishable warning
   string, while the constitution requires `INVALID_AGENT_OUTPUT` to stay
   distinct from disagreement. `ConvergenceResult.evidence_failures` now
   carries `(stage, error_type, message)`. The loop still treats them
   identically — correctly, since no evidence was collected either way —
   but the record no longer pretends they are the same thing.
6. *(major, repaired)* **The adapter's read bound bounded nothing.**
   `ClaudeCodeCLIRunner` read and parsed the entire stdout file before
   `agent_message_text` truncated anything, so a multi-gigabyte envelope
   was an out-of-memory before the advertised limit applied — making the
   self-review addendum's "Bounded at `MAX_AGENT_MESSAGE_CHARS`" claim
   false in production. The runner now checks size before reading.
7. *(minor, repaired)* **Evidence files collided.** Two loops sharing an
   evidence directory both wrote `review-1.stdout`. Filenames now carry a
   sanitised agent identity (sanitised because identities contain `/` and
   `:`, which would escape the directory or fail on Windows).
8. *(claims corrected)* Three ADR sentences the code did not support:
   "everything in the payload is validated", "every untracked file's
   bytes", and the bounded-read claim. All three are rewritten above
   rather than defended.

**What this round says about the previous one.** The self-review below
found three real defects and still missed eight, including a rule-9
bypass reachable with a filename. That is the measurement worth keeping:
self-review is not worthless, and it is not a substitute.
