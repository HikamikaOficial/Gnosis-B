# ADR-0014 — Record/replay wired to the real CLI runner (adapter milestone, 2/4)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: **captured, not asserted** —
  `.gnosis/evidence/20260820T214621Z/` holds each command's argv, exit
  code and output (`pytest` 535 passed, `mypy` clean over 47 files,
  `ruff` at the recorded backlog baseline, and the HEAD it was taken at).
  Produced by `scripts/capture_evidence.py`, which exits non-zero if
  anything fails, so it cannot mint a green transcript for a red tree.
  `tests/test_replay_runner.py` (24 tests), including a runner that
  MUTATES the repository, recorded and replayed end to end.
- Builds on: ADR-0010 (`InteractionStore`, strict replay), ADR-0013 (the
  same "wire it or it is fiction" rule, and the same content-hash
  lesson).

## Context

ADR-0010 built occurrence-aware, strict-by-default replay and stated
plainly that nothing called it. That is the second of the four unwired
mechanisms, and Directive 9's rule applies unchanged: **a mechanism
nothing calls is a parallel fiction**. L-0006 adds the sharper version
learned one milestone later: wiring it to the primitive is not wiring it
to production.

## Decision

`ReplayingCLIRunner` duck-types `ClaudeCodeCLIRunner.run()` and routes
every invocation through an `InteractionStore`. It is a drop-in wherever
a runner is accepted — `TaskEngine(cli_runner=...)`, and therefore
`DirectorOrchestrator` — so a real brief can be recorded once and
replayed with no model, no network and no bill.

### The key is content, never paths — and it is the tree the session started from

A cassette keyed on the absolute worktree path would be unreplayable on
another machine, and would still happily replay a recording made against
a *different tree at the same path*. `content_fingerprint()` (in
`kernel/git_evidence.py`, shared with the policy gate) identifies a
workspace by HEAD, branch, the full patch, and every untracked file's
bytes.

The fingerprint is captured **once per workspace per session**, not per
call. That is not an optimisation: fingerprinting each call keyed call 2
on call 1's edits, and since a replay reproduces stdout but not the
agent's edits, no recording of a repository-mutating agent was replayable
past its first call. See addendum finding 1.

MCP configs are keyed by content hash for exactly the reason ADR-0013
binds approvals to content: the file decides which tools the agent can
reach, so a rewrite is a different call.

`timeout_s` is in the key too. It is tempting to treat a deadline as
non-determining, but a shorter one can turn a success into a timeout,
and "probably still valid" is the guessing this project bans.

### Replay reproduces the side effects, not just the return value

The engine does not read `ExecutionResult.parsed_json` alone: it reads
the stdout/stderr **files** for evidence and for failure classification.
A replay that returned a result object without materialising those files
would look like a pass and classify like a blank run. The runner writes
them on both paths, so a recording run and a replaying run observe the
same bytes — the same round-trip rule ADR-0010 had to learn when RECORD
saw `('a','b')` and REPLAY saw `['a','b']`.

### Output is stored byte-exact or refused

Streams are recorded as text when they are valid UTF-8 and as base64
when they are not. A lossy decode would mean the replayed run observes
different bytes than the live one, which is the quiet kind of falsehood
that makes "deterministic replay" untrue much later.

A stream over `MAX_RECORDED_STREAM_BYTES` (1 MiB) cannot be stored
faithfully. It is marked rather than dropped — the call really happened
and its occurrence must stay in the cassette, because dropping the row
would silently shift every later occurrence. Replaying it raises
`UnreplayableStream` instead of handing back a truncated prefix. But the
*recording* run keeps its own real output on disk: refusing to hand a
live run its own stdout would be the audit breaking the thing it audits.

## Known limitations (stated, not implied)

The review found this list incomplete — a section promising that
limitations are stated rather than implied has to actually contain them.

- The cassette binds the workspace, the prompt, the model, the flags and
  the MCP config contents — **not** the identity of the `claude` binary
  itself, nor ambient CLI configuration outside those files. The same
  residual applies to policy approvals; closing it needs an executable
  fingerprint, which belongs with the sandbox boundary work.
- **A replay reproduces stdout, stderr and the result — never the agent's
  edits to the repository.** Replaying therefore requires starting from
  the tree the recording started from. That is now the design (a session
  baseline) rather than an accident, but it is a real constraint on how a
  cassette can be used.
- **`branch` is part of the key**, and under a `WorktreeManager` the
  branch is `gnosis/<task_id>`, so a cassette does not transfer across
  task ids even with a byte-identical tree. Defensible — an agent that
  shells out to git can see its branch — but previously undisclosed.
- **Heartbeats are not reproduced.** A replayed run never invokes
  `heartbeat_fn`, so `heartbeat_failures` in `run.attempt_finished`
  replays as empty even when the recording logged some.
- `cancellation_token` is not consulted on the replay path: a replayed
  run reproduces recorded history and returns immediately.
- Replay is free of model calls, network and billing, but **not of
  processes**: the baseline fingerprint shells out to `git`.
- The cassette is not hash-chained the way `RunLedger` is. Recomputing
  each row's key on load (addendum finding 5) stops a row from claiming
  to be a different call, but an edited *response* on an otherwise
  well-formed row is not detected. Full tamper-evidence is a real gap.
- Mode is chosen by the caller (`recording_orchestrator(..., mode=)`);
  nothing selects it from configuration or manages a cassette-per-task
  convention. That belongs with the scheduler.

## Independent review addendum (2026-08-20)

An independent read-only review returned **FAIL**. With Codex parked, it
came from an internal reviewer agent given the same adversarial brief.
Eight findings were reproducible defects; all are repaired here.

1. *(critical)* **The key depended on state a replay cannot restore.**
   The workspace was fingerprinted per call, so a repository-mutating
   agent — the only kind GNOSIS runs — produced a different key on call
   2, which a replay could never recompute. The mechanism did not work
   for its own subject past the first call. It now anchors on a session
   baseline. The reviewer also caught *why* the end-to-end test missed
   it: the stand-in runner wrote only to stdout paths placed outside the
   repo, making it structurally incapable of exhibiting the failure.
   `_MutatingRunner` fixes that, and a second test pins that the repair
   did not buy multi-call replay by making cassettes indifferent to which
   tree they replay against.
2. *(major)* **The audit wrapper silently changed the security
   decision.** `TaskEngine` shows policy rules `runner.binary`; the
   wrapper had none, so the gate saw `<unknown-runner>` — a different
   `action_id`, invalidated human approvals, and silence from any rule
   matching the real program. Now a passthrough property.
3. *(major)* **A call that raised was never recorded.** The live call had
   happened and may have cost money, but `live_fn` raising meant no row,
   so the next recording took occurrence 0 and a failed call replayed as
   a later success. Failures are recorded now and re-raise as
   `ReplayedFailure` on replay.
4. *(major)* **A torn tail was swallowed, then bricked the cassette.**
   Appending onto an unterminated row glued them together, discarding the
   just-recorded call silently; one more append moved the tear off the
   last line and made `_load` raise, losing every intact row. Appends now
   terminate a tear, and an unreadable row is skipped and reported
   (`store.damaged`) rather than being fatal. This opens no permissive
   path: a genuinely lost row leaves a gap the occurrence-contiguity
   check still turns into a hard error, and a key with no readable rows
   simply misses, which strict replay already aborts on.
5. *(major)* **The stored `key` was trusted verbatim**, so a row could
   claim to be a different call's response. Keys are recomputed from
   `tool` + `params` on load and on the append-time tail scan.
6. *(major)* **The stream cap bounded storage, not memory.** The whole
   file was read before the size check, so a multi-gigabyte log dump was
   an OOM *after* the paid call. Size is checked first — the pattern
   `adapters/cli_review.py` already used and this module had not.
7. *(major)* **An unencodable response stole the live run's own result.**
   `call()` returns `replayed_response()`, which raises for an
   unrecordable row, so a successful live call handed its caller an
   exception instead. The recording path now falls back to its own live
   response — the rule this module already applied to oversized streams.
8. *(minor)* A `missing` stream overwrote real output with zero bytes;
   `b64decode` ran without `validate=True`, so tampered characters were
   silently discarded; and an `OSError` message put an absolute path into
   the supposedly portable key.

**And the process findings, which were the fair ones.** This ADR shipped
with no independent review at all, on a claim class the previous two
rounds had already falsified twice — and its evidence line was
self-reported prose with no artifact behind it. Both are addressed: the
review happened (this addendum), and `scripts/capture_evidence.py` now
writes a real transcript with exit codes that ADRs cite by path.

`ReplayingCLIRunner` also had **zero production constructions** — the
exact condition this ADR's opening paragraph condemns.
`recording_orchestrator()` is the fix.
