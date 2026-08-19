# M2.5 Code Intelligence Production Wiring

## Production adapter

`gnosis.kernel.code_intelligence.CodeIntelligenceProvider` extended
beyond the M2.1 benchmark version: `status()` (index health + staleness),
`find()` (symbol lookup), `explore()` (compact, LLM-ready context
retrieval), and `index(repo_path, full=False)` (incremental sync by
default, full rebuild on request). `CodegraphMcpAdapter` implements all
of it against real codegraph-mcp CLI output -- every parser was built
from output actually captured in the M2.5 lab session (status/query/
explore), not guessed.

A real bug was found and fixed while verifying `explore()` against the
live tool: `subprocess.run(..., text=True)` uses the Windows locale
codec (cp1252) by default, which cannot decode some characters
codegraph-mcp emits (em dashes in its markdown output). Fixed by passing
`encoding="utf-8", errors="replace"` explicitly. Caught by running the
real adapter against the real tool, not by the canned-output unit tests
alone -- exactly the kind of thing "VERIFY" exists to catch.

## TaskEngine integration

`TaskEngine.execute_task()` gained three optional parameters:
`code_intelligence`, `focus_symbols`, `max_context_chars` (default
12000). When both `code_intelligence` and `focus_symbols` are supplied,
context is gathered **once**, before the first CLI attempt (not
per-retry -- retries reuse the same augmented prompt), via a new
`_gather_code_intelligence_context()` helper:

1. Best-effort incremental `index()`, best-effort `status()` -- both
   wrapped so a provider failure never propagates.
2. If the index is stale, a warning note is prepended to the context
   block itself, so Claude is told the structural claims may be
   out of date, rather than Gnosis silently presenting stale data as
   current.
3. `explore(symbol)` is called for each `focus_symbols` entry
   independently; a failure on one symbol does not block the others.
4. The combined included text is capped at `max_context_chars` (each
   individual `explore()` call is already capped by the adapter at
   8000 chars) -- this is the context-budgeting hook a future
   MemoryRouter can drive with a smarter number; M2.5 does not build
   that router, only the knob.

The gathered block is prepended to the prompt actually sent to the CLI.
Evidence (provider name, index status, one entry per symbol query with
latency/success/chars, total chars included) is logged as a
`code_intelligence.context_gathered` ledger event on the first attempt
only, and written to `<run_dir>/code_intelligence.json`. The
`run.attempt_started` event also gets a `code_intelligence_used`
boolean for quick auditability alongside the existing `mcp` field. The
raw `explore()` text is not duplicated into the ledger event, only
per-query metadata -- the full text lives once, in the evidence file.

## Index lifecycle

- **Initial/incremental**: `index(repo_path, full=False)` calls `sync`;
  `full=True` calls `index` (rebuild). A "not initialized" response
  falls back to `init` automatically.
- **Stale detection**: `status()` parses codegraph-mcp's own "Pending
  Changes" / "up to date" reporting (verified against real output from
  both states -- clean and after an uncommitted file edit).
- **Deleted/renamed symbols**: already exercised with real execution in
  the M2.1 benchmark (`legacy_function` deletion, `compute_b` ->
  `compute_b_renamed` rename both correctly reflected). Not re-tested at
  the TaskEngine level since TaskEngine delegates index-freshness
  entirely to the provider; re-testing would duplicate M2.1 coverage
  without adding evidence.
- **Provider unavailable / index corruption / failure**: every provider
  call in `_gather_code_intelligence_context` is wrapped; a total
  failure (index down, status down, every explore() failing) still lets
  the task complete normally with an empty context block -- verified by
  `test_provider_unavailable_does_not_block_or_corrupt_run`, which
  checks the run reaches `SUCCEEDED`/`COMPLETED` and the run's meta.json
  is not corrupted.

## Observability

Persisted per task (not per file-write-heavy raw dump): provider class
name, index status snapshot, one record per symbol query (latency_ms,
success, chars_returned, chars_included, related_symbols), and the
total included-char count. This satisfies "avoid storing excessive
duplicated data" by keeping the ledger event to metadata and writing the
one full-text evidence file once, rather than embedding the text itself
in every ledger read.

## Sverklo decision: REFERENCE (for Code Intelligence), carried into M3

Minimum additional investigation performed (per the Director's
instruction): re-ran `sverklo --help` against the M2.1 lab install and
grepped for memory/decision-related commands. Confirmed real (not just
README marketing): `sverklo memory export` is a genuine top-level CLI
command; `wakeup` (compressed project context) and `wiki` (markdown wiki
from the index) are also real. `remember`/`recall` -- the actual
memory-write operations -- are **not** CLI-reachable; they are MCP-tool-
only, consistent with the M2.1 finding that live MCP probing against
sverklo risked an orphaned process and was not safely completed.

Verdict:

- **On the structural graph responsibility** (symbols/callers/callees/
  blast radius): substantial overlap with codegraph-mcp, which already
  won that responsibility on real, executed, zero-false-positive
  evidence in M2.1. Building a second production
  `CodeIntelligenceProvider` adapter here would be exactly the redundant
  subsystem the Director's decision explicitly forbids.
- **On bi-temporal, git-pinned decision memory** (`valid_from_sha`/
  `valid_until_sha`/`superseded_by`, "what did we believe about X at
  commit Y"): this is a real, shipped, non-overlapping capability that
  codegraph-mcp has no equivalent of at all. It matches the Director's
  own examples of complementary value almost exactly ("Git-linked
  architectural/project decisions... decision provenance... code-change
  historical context") -- but it is a **factual/temporal memory**
  concern, not a code-intelligence concern.

Result: **REFERENCE** for M2.5/Code Intelligence scope -- no
`SverkloAdapter` is built now. Carried forward as an additional M3.1
memory-arena candidate (beyond the Director-named m3-memory/zmem/
cass_memory_system), justified by this real evidence rather than by
catalog score, per the Director's own "include another candidate only
if previous corpus research gives a strong technical reason" allowance.
