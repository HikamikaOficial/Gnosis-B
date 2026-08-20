# ADR-0010 — Strict replay + write-ahead intent (Directive 7)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_replay.py` (39 tests incl. a concurrent-recorder
  race, a crash-resume scenario and a golden-fixture round trip); suite
  328/328; mypy strict clean; dual adversarial review pre-commit
  (outcome below).
- Source: `docs/research/REFERENCE_REPOSITORY_FINDINGS.md` §7 (bernstein
  `DeterministicStore`, reprise occurrence-aware strict replay, smithers
  `intended` journal rows, dagger memoization, catacomb fixtures).

## Decisions

### 1. `InteractionStore` — occurrence-aware, strict-by-default replay

Calls are keyed by `hash_canonical({tool, params})` where the **caller
declares** the response-determining parameters in a `CallSpec` — the
store never guesses which fields matter. Non-determining data goes in
`metadata`: recorded, never keyed (a timestamp in the key would make
every replay a miss).

Replay is occurrence-aware (per-key FIFO: the same key called three
times replays the first, second, third responses in order) and **strict
by default** — a miss raises `ReplayMiss` and `live_fn` is never invoked,
so a replayed run cannot reach the network even when a key is missing.
Fall-through is `ReplayMode.REPLAY_OR_RECORD`: an explicit opt-in.

**Round-trip fidelity is part of the contract.** The recording path
returns the value *as serialized*, not the live object — otherwise a
recorder observes `("a","b")` where the replayer later observes
`["a","b"]` and "deterministic replay" is false on its first tuple
(found and fixed by self-testing before review).

**Occurrence numbers are allocated under the file lock**, from what is on
disk, so concurrent recorders sharing a cassette cannot both claim
occurrence 0.

**A call that happened is always recorded.** If a response cannot be
serialized, the row is still written (flagged `unrecordable`) so the
audit trail and occurrence numbering stay complete, the recording call
fails loudly, and replaying that occurrence fails closed instead of
inventing a value.

### 2. `IntentJournal` — write-ahead intent on the hash-chained ledger

`intent.declared` (with `SideEffect`: side_effect, idempotent,
has_revert, idempotency_key) is persisted **before** the side effect
runs; the outcome is a second row. Rewind safety is then a query:
`rewind_blockers()` returns effects that neither repeat safely nor
revert, **plus every unresolved intent** — an unknown outcome is never
declared safe. A body that raises is recorded FAILED; a body that never
claims an outcome stays DECLARED, because inventing a completion is
exactly the guess this mechanism exists to eliminate.

Intent ids are globally unique (uuid4) and folding is **scoped by
run_id**: a resumed run shares its predecessor's ledger, and per-instance
counters previously let a resumed run's completion erase the crashed
run's still-unresolved dangerous intent.

**Safety queries verify the chain.** `records()` recomputes the ledger's
hash chain by default: an answer about whether destroying work is safe,
read from an unverified chain, is worthless.

## Review outcome and repairs (2026-08-20, pre-commit)

**Self-found before review** (reproduced, then fixed and pinned): the
tuple/list round-trip infidelity, and unserializable responses raising a
bare `TypeError` after the live call with the cursor left unadvanced.

**Codex** (`exec --sandbox read-only --json`): FAIL, 4 findings, all
verified true and repaired:

1. *(critical)* Intent-id reuse across journal instances — the crash-
   resume case — let a later completion mark a still-unresolved
   dangerous intent as done. Fixed with uuid4 ids + run_id scoping;
   pinned by `test_resumed_journal_never_reuses_intent_ids`.
2. *(major)* Occurrence allocation happened outside the lock: concurrent
   recorders wrote duplicate occurrences. Now allocated on-disk under the
   lock; pinned by an 8-thread race test.
3. *(major)* Rewind-safety queries read an unverified ledger. Now
   `verify_chain()` by default.
4. *(major)* A live call whose response could not be serialized left no
   cassette row. Now recorded as `unrecordable`.

**Multi-agent workflow** (3 lenses delivered 15 findings; its verify
phase was cut by a session limit, so each finding was adjudicated
manually against the code — three were reproduced first). All were true;
all are repaired:

5. *(critical, reproduced)* **`ReplayMode` subclasses `str`**, so the
   dispatch `mode in (...)` matched a bare `"REPLAY"` while the abort
   guard `mode is ReplayMode.REPLAY` did not — a mode passed as a string
   turned strict replay into a **silent live call** (reproduction
   returned `'LIVE-LEAK'`). The mode is now coerced at construction.
6. *(critical, reproduced)* Unserializable **metadata** — which the
   `CallSpec` docstring explicitly invites (timestamps, request ids) —
   destroyed the row for a call that had already happened (zero rows on
   disk). Metadata now degrades to a printable form; the row always
   lands.
7. *(major, reproduced)* Replay served records **positionally** while
   occurrence labels were never validated, so a gapped or duplicated
   cassette replayed a *different call's response* instead of aborting.
   `_load` now requires occurrences to be exactly 0..n-1 per key.
8. *(major)* An exception in an intent body was recorded as a definite
   FAILED, indistinguishable from a caller-asserted non-occurrence — yet
   an exception proves only that the call did not *return*, never that
   the effect did not *land*. Such outcomes are now marked
   `certain=False` and stay in `unresolved()`/`rewind_blockers()`.
9. *(major)* A failed ledger write inside `complete()` let `__exit__`
   record **FAILED for a side effect that had succeeded**. An attempted
   outcome now suppresses the fallback; the intent stays DECLARED —
   "we could not record what happened" is the honest state.
10. *(major)* `golden_fixture()` was a one-way exporter with no import
    path, and it emitted **key-hash order rather than call order**.
    `records()` now preserves true call order, and
    `write_golden_fixture()`/`load_golden_fixture()` close the round trip
    (pinned end-to-end, including drift aborting).
11. *(minor)* No point-in-time rewind query — rewind is inherently
    rewind-*to a checkpoint*. `rewind_blockers(since_seq=…)` added.
12. *(minor)* A torn final line bricked the whole cassette (and appends
    did not `fsync`). Now fsync'd, with the same torn-tail tolerance the
    ledger has; interior corruption still raises.
13. *(minor)* Every append re-parsed the entire cassette **while holding
    the lock** (quadratic). Replaced by an incremental tail scan.
14. *(minor ×2)* Coverage gaps: metadata actually being recorded, and the
    `_load` occurrence sort, were both unpinned. Now tested.

Three bugs of my own in these repairs (double-counted occurrences,
`records()` missing freshly appended rows, a test that collided with the
new torn-tail tolerance) were caught by the suite before commit.

## Known limitation (documented, not fixed)

`InteractionStore` is not yet wired into `ClaudeCodeCLIRunner` or the
engine: this milestone delivers the mechanism and its contract. Wiring
the runner (so a real Claude/Codex invocation records and replays) lands
with the adapter milestone, together with `ConvergenceLoop`'s reviewer/
fixer adapters. `golden_fixture()` exports rows in the cassette's own
format, so a golden run is replayable by pointing an `InteractionStore`
at the recorded file — no second format, but no end-to-end engine-level
regression fixture exists yet either.
