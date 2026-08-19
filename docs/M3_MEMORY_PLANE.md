# M3 Gnosis Memory Plane

## IMPORTANT: license finding on cass_memory_system

Before any technical evaluation: `cass_memory_system`'s LICENSE
("MIT License with OpenAI/Anthropic Rider") explicitly bars Anthropic,
its affiliates, and anyone "acting... under the direction of" Anthropic
from using, copying, benchmarking, testing, or analyzing the software.
This session (Claude Code, an Anthropic product, acting under the
Director's direction) is squarely inside that definition. On discovery,
all engagement was stopped immediately and the lab copy was deleted (the
rider itself requires this on breach). Full detail:
`.gnosis/lab/memory/results/cass_memory_system/LICENSE_FINDING.md`.
**Recommendation: REJECT cass_memory_system outright, on license
grounds, independent of any technical merit.**

## Candidates tested

Director-named: m3-memory, zmem, cass_memory_system (rejected above,
license). The reference corpus (`11-cognitive-memory/`, 19 repos, 8
analyzed) independently confirms the Director's three-role split:
`INDICE.md` describes zmem's differentiator as "governance, not
retrieval -- the one function not covered by the other 8" candidates,
and m3-memory as "bitemporal, contradiction-aware." No additional
candidate was added beyond Sverklo (carried forward from M2.5, see
below) -- the corpus's own characterization already matches the
Director's category design closely enough that hunting for a fourth
candidate would not have added evidence.

## Methodology

Both m3-memory and zmem were copied out of the reference corpus into
`.gnosis/lab/memory/` (never executed in place) and installed via `uv
venv` + editable install. Real commands were run against real local
SQLite-backed workspaces; every claim below is backed by actual command
output, not README claims. Raw evidence: `.gnosis/lab/memory/results/`.

## zmem: real, deep execution -- governance role confirmed

Installed in under 2 seconds (zero required dependencies). Ran a full
deterministic scenario: `remember` two contradictory facts (SQLite vs.
PostgreSQL storage backend) with real cryptographic receipts on
`inject`; `revoke`d the stale one; confirmed future `inject` excludes it
while `why` on the *original* pre-revocation action still shows it,
correctly labeled `[semantic/revoked]` -- downstream influence of a
since-revoked memory on a past decision is fully, verifiably traceable.
`audit health` has a real `contradictory_or_conflicting` finding
category but returned zero findings on the SQLite/PostgreSQL pair,
matching its own documented limitation ("does not establish whether
memory content is factually or semantically true... lexical signals
only"). No automatic supersession was found reachable from the CLI in
the time available. MIT license. Full scorecard:
`.gnosis/lab/memory/results/zmem/SCORECARD.md`.

## m3-memory: CLI-surface verified, a real bug found

Command surface (`m3 memory --help`, 36 tools) genuinely matches the
"bitemporal, contradiction-aware" claim: `memory_supersede`,
`memory_search_routed` ("temporal-aware routed retrieval"),
`memory_history`, real `--valid_from`/`--valid_to` CLI flags. A direct
`memory_write --database <custom path>` against a fresh SQLite file ran
43 real schema migrations successfully, then failed the actual write:
`OperationalError: no such table: memory_items` -- reproduced on retry,
not transient. The full `install-m3`/interactive `setup` flow (which
downloads a secondary GitHub payload and provisions background
services) was not pursued, consistent with the operational-complexity
caution already applied to codebase-memory-mcp (M2.1). Apache-2.0
license, no unusual terms. Full scorecard:
`.gnosis/lab/memory/results/m3-memory/SCORECARD.md`.

## Sverklo (carried forward from M2.5)

M2.5 confirmed real bi-temporal, git-pinned decision memory
(`valid_from_sha`/`valid_until_sha`/`superseded_by`, `sverklo memory
export`) as a genuinely non-overlapping capability from code
intelligence. Not independently re-benchmarked in M3 (its MCP-native
interface remains untested end-to-end per the M2.1/M2.5 findings); noted
here as a candidate worth a dedicated, careful MCP-protocol evaluation
in a future milestone, not folded into this pass's verdicts.

## Gnosis Memory Contract (owned, implemented, tested)

`gnosis.kernel.memory`: `MemoryStatus` (OBSERVED -> CANDIDATE ->
QUARANTINED -> ACTIVE -> SUPERSEDED/REVOKED, with a real transition
table and `IllegalMemoryTransitionError`, matching kernel.state_machine's
established pattern), `MemoryRecord` (content, type, status, evidence,
bitemporal valid_from/valid_to, supersedes/superseded_by), `MemoryEvidence`
(provenance: source_kind/source_uri/actor_uri/confidence), `MemoryQuery`
(text, `as_of` for point-in-time truth, scope, include_superseded,
limit), `MemoryResult`, `MemoryInfluence` (action_id -> memory_ids
receipt, optional proof token), `MemoryRevision` (one audit-trail
entry), `MemoryProvider` (ABC: remember/propose/promote/reject/
supersede/revoke/query/inject/why/history), `MemoryUnavailable`,
`NullMemoryProvider` (default, always-unavailable, matching
`NullCodeIntelligenceProvider`'s M2 pattern).

Every method on the contract maps to something actually exercised
against zmem's real CLI in this session, not a speculative API surface.

`gnosis.kernel.memory_reference.InMemoryMemoryProvider`: a real, correct
implementation (not a mock) proving the contract is coherently
implementable, and giving Gnosis's own test suite deterministic
scenarios that do not depend on any external tool being installed. A
future adapter for zmem or m3-memory would satisfy the same contract by
shelling out, exactly like `CodegraphMcpAdapter` does for code
intelligence.

`gnosis.kernel.memory_router.MemoryRouter`: composes multiple
`MemoryProvider` instances by role, retrieves a bounded number of
records per role and in total (mirrors the exact context-budgeting
pattern already proven in `kernel.engine._gather_code_intelligence_context`,
M2.5), and records per-role failures without one role's provider outage
blocking the others.

## Deterministic scenario tests: all 8 Director-specified categories, real

20 tests in `tests/test_memory.py`, all passing against
`InMemoryMemoryProvider`:

- **Temporal truth**: query `as_of` T1 returns the SQLite fact; current
  query returns PostgreSQL; the old fact remains reachable with
  `include_superseded=True` rather than disappearing.
- **Contradictions**: two independently-sourced contradictory facts both
  surface from `query()` unresolved (no fabricated merge, no silent
  pick-one); a `propose()`d contradiction stays QUARANTINED and is never
  returned as active truth.
- **Supersession**: `history()` preserves both transitions; `query()`
  unambiguously returns only the current record.
- **Provenance**: every record's `evidence.source_kind`/`source_uri`/
  `actor_uri` round-trips.
- **Revocation**: a revoked memory is excluded from all *future*
  `inject()` calls, but a *past* action's `why()` still shows it,
  correctly reflecting its current REVOKED status via `history()` --
  downstream influence is identifiable.
- **Procedural learning**: the `memory_type="procedure"` flows through
  the identical lifecycle and is retrievable; extraction-*quality*
  judgment (is this actually a good, reusable procedure?) is explicitly
  out of scope for a deterministic unit test and is not claimed as
  tested.
- **Noise resistance**: a targeted query finds the one relevant record
  among 50 irrelevant ones; `limit` bounds result count under heavy
  match volume.
- **Stale knowledge**: a superseded old decision never outranks the
  current active one in a default query.

A real bug was found and fixed while writing these tests:
`InMemoryMemoryProvider.query()`'s original matching was exact-substring,
which failed on natural-language queries ("What is the API rate limit?")
against terse stored content ("The API rate limit is 1000 req/s.") --
replaced with word-overlap matching, documented as a reference-quality
heuristic, not a retrieval-precision claim.

## Relationship to the run ledger (kernel.ledger) and to code intelligence

The run ledger stays exactly what M0/M1 built it to be: immutable,
append-only, raw execution evidence. Memory is a separate, curated,
revisable layer above it -- not every ledger event deserves to become a
memory, and the ledger is never replaced by or routed through the
Memory Plane. Code intelligence answers "what does the repository look
like right now"; memory answers "what do we know about it, why, what
happened before, and what have we learned" -- the two are meant to
compose (e.g. a future MemoryRouter call alongside a
`_gather_code_intelligence_context` call), not duplicate each other.

## Verdicts

| Role | Candidate | Verdict | Why |
|---|---|---|---|
| Governance | zmem | **ADOPT-COMPLEMENT-track** (not yet integrated) | Deep real execution, all core governance behaviors verified working end-to-end; MIT; zero deps |
| Factual/temporal | m3-memory | **BENCHMARK-LATER** | Command surface is real and matches claims, but the direct-integration path failed with a reproducible bug; needs follow-up before production use |
| Procedural | cass_memory_system | **REJECT** | License bars Anthropic-affiliated use entirely; no technical verdict possible or attempted |
| Governance-adjacent (code-linked decision memory) | Sverklo | **REFERENCE** | Real capability confirmed in M2.5, but MCP-native interface still untested; not re-evaluated this milestone |

No production `MemoryProvider` adapter was built for any external tool
this milestone -- consistent with "do not manufacture a winner." The
contract, the in-process reference implementation, and the router are
the concrete M3 deliverables; picking a production governance/factual
provider is recommended for M4, once m3-memory's integration bug is
either resolved or explained by its maintainers, and once zmem's lack of
an explicit supersession command is confirmed absent (not just
undiscovered) or found.

## Remaining risks

- No procedural-memory candidate was safely evaluated (license
  rejection). Gnosis has a contract-level procedural story
  (`memory_type="procedure"`) but no vetted provider recommendation.
- m3-memory's real bug means it cannot be recommended without further
  investigation of the `--database` custom-path failure.
- zmem's automatic-supersession mechanism (if any) was not found within
  this session's CLI exploration; supersession may require the caller to
  drive it explicitly, which is a real integration cost if zmem is later
  chosen for the factual/temporal role instead of m3-memory.
- The reference corpus's own license-type classification missed
  `cass_memory_system`'s restrictive rider; other repositories in the
  corpus may carry similarly undiscovered restrictive terms that a
  first-pass "MIT/Apache" read would not catch. This session did not
  have the scope to re-audit every previously-reviewed repository.
- `InMemoryMemoryProvider`'s word-overlap query matching is a reference-
  quality heuristic, not a retrieval-precision-tested search engine; a
  production adapter should delegate search to the backing tool.
