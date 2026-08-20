# ADR-0014 — Record/replay wired to the real CLI runner (adapter milestone, 2/4)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_replay_runner.py` (14 tests, incl. a full
  Director brief recorded and replayed with the live runner replaced by
  one that raises if called); suite 488/488; mypy strict clean; ruff
  clean on every file this ADR touches.
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

### The key is content, never paths

A cassette keyed on the absolute worktree path would be unreplayable on
another machine, and would still happily replay a recording made against
a *different tree at the same path*. `workspace_fingerprint()` (now in
`kernel/git_evidence.py`, shared with the policy gate) identifies a
workspace by HEAD, branch, and a hash of the dirty state. MCP configs
are keyed by content hash for exactly the reason ADR-0013 binds
approvals to content: the file decides which tools the agent can reach,
so a rewrite is a different call.

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

- The cassette binds the workspace, the prompt, the model, the flags and
  the MCP config contents — not the identity of the `claude` binary
  itself or ambient CLI configuration outside those files. Codex raised
  the equivalent gap for policy approvals; the same residual applies
  here and closing it needs an executable fingerprint, which belongs
  with the sandbox boundary work.
- `cancellation_token` is not consulted on the replay path: a replayed
  run reproduces recorded history and returns immediately.
- Nothing yet *selects* a mode from configuration. A caller chooses
  RECORD or REPLAY explicitly when constructing the runner; a
  cassette-per-task convention belongs with the scheduler.
