# M2.1 Code Intelligence Arena: Benchmark Report

Real, executed benchmarks against a deterministic fixture repo with known
ground truth, run entirely inside Gnosis-controlled lab storage
(`.gnosis/lab/code-intelligence/`). Nothing was executed inside the
external reference corpus; candidates were copied out first (`cp -r`),
confirmed by an unchanged source directory listing afterward.

## Candidates

Director-named: `sverklo`, `codegraph-mcp`, `Graphify`, `code-context-engine`.
`Graphify` does not exist anywhere in the reference corpus (confirmed in
M1 via full-corpus grep, reconfirmed here) -- substituted per the
Director's own fallback clause ("If your M1 research identified another
candidate that has a genuinely non-overlapping or superior capability,
include it") with `codebase-memory-mcp`, the corpus's highest-catalog-
scored candidate, precisely so the substitution is not just "drop to 3."

`codebase-memory-mcp` was deliberately **not executed**: its installer
downloads a precompiled `.exe` from GitHub releases at runtime (no Go
toolchain available locally to build from source instead). Running an
unverified precompiled binary is a real supply-chain decision that
should not be made implicitly inside a benchmark script; recommend a
dedicated, deliberate security review (release-signature/SHA-256
verification, sandboxed execution) before ever running it, consistent
with the risk this candidate was already flagged with in M1.

## Fixture and ground truth

`.gnosis/lab/code-intelligence/datasets/build_fixture.py` generates a
small, real git repo (5 commits) with known-by-construction facts:
direct calls, an indirect call chain, a renamed symbol, a deleted
symbol, a new file added after initial indexing, a circular import,
two similarly-named overloaded symbols in different modules, one
intentionally dead function, and one behavior change with a known
3-symbol blast radius. `ground_truth.json` records the expected answer
for every one of these. The fixture's own test suite was verified to
actually pass (`entrypoint(3) == 115` post-change; the circular import
resolves; overloaded/dead-code symbols behave as intended) before any
candidate touched it.

## Environment

Windows 11, Node 20.18.0 (system) + a portable Node 24.9.0 (lab-scoped
zip extraction, not a system-wide install -- both `sverklo` and
`codegraph-mcp` require `node:sqlite`, Node 22.5+; their declared
package.json `engines` ranges do not reflect this for `codegraph-mcp`
specifically, a real reproducible finding), Python 3.13 + `uv` for
`code-context-engine`. All three installed and built from the lab
copies (`npm install && npm run build`, or `uv venv` + editable install)
-- none from the npm/PyPI registries' published releases, so this tests
the actual candidate source in the corpus, not whatever is currently
live upstream.

## Results

| Dimension | sverklo | codegraph-mcp | code-context-engine |
|---|---|---|---|
| Category | symbol graph + bi-temporal memory | symbol/call graph, blast radius | semantic retrieval (different category) |
| License | MIT | MIT | MIT |
| Runtime | Node (24+ required) | Node (24+ required; self-contained release avoids this) | Python 3.11+ |
| Cold index (this fixture) | 10.5s internal / 20.6s wall (incl. ~90MB model download) | 3.6s internal / 8.5s wall | 55.6s wall (incl. embedding model download, largest cold cost) |
| Warm-cache index | 2.7s internal / 4.7s wall | 3.2-3.6s internal / 7-8.5s wall | 5.5s wall |
| Index location | project-local + `~/.sverklo` model cache | project-local `.codegraph/` (157-165 KB) | global `~/.cce/projects/<hash>/` (1.7 MB) |
| Direct calls (callees) | not tested via CLI (see below) | exact match, 0 FP/FN | ranked #1-3 but not precisely scoped (expected for semantic search) |
| Callers | exact match via `prove` (2/2 correct) | exact match, 0 FP/FN | ranked, not exact |
| Blast radius | not tested via CLI | exact match, 3/3 function-level, 0 FP/FN | not applicable (no blast-radius concept) |
| Renamed/deleted symbol handling | correct (not directly queried) | correct ("not found" reported cleanly) | correct (absent from search results) |
| Overloaded names | not tested via CLI | both disambiguated by file:line | both ranked top-2 |
| Dead code | not tested via CLI | "No callers found" correctly | ranked #1 for a "dead code" query |
| Incremental update | not tested (no equivalent CLI verified) | verified correct after fixing a self-inflicted test bug; fixture too small to show a timing win | N/A (full reindex only, 93% internal cache hit noted) |
| MCP integration test | attempted, abandoned (see below) | not attempted (CLI is documented as MCP-output-identical) | not attempted |
| Windows behavior | works, needs Node 24 specifically | works, needs Node 24 specifically (or the vendor's bundled release) | works natively, no runtime friction |
| Test suite (candidate's own) | 95 files | 138 files | present, CI badge green |
| Maturity signal | public 180-task bench, v0.20.2 active | 1.0 released, commercial platform waitlist (open-core) | documents a real fixed SIGSEGV bug (#113/#114) |

## MCP protocol integration: a real, reportable finding

A generic MCP stdio JSON-RPC probe was written and run against sverklo's
server mode. It hung (suspected Content-Length-header framing mismatch
vs newline-delimited JSON -- not root-caused) and left one orphaned
`node` process holding stdin open. It was identified unambiguously via
`Get-CimInstance Win32_Process` (its full command line named the exact
lab paths involved) and terminated with `Stop-Process -Force`. Given the
Director's explicit M2 preflight instruction about not leaving orphan
processes, further live-protocol debugging was stopped there in favor
of the strong CLI-based evidence already gathered. This is a genuine
finding, not a shortcut: sverklo's primary interface is MCP-native
(correct for its purpose), so CLI-only testing structurally under-tests
it relative to codegraph-mcp, whose CLI commands are documented by the
author as identical output to the MCP tools -- which is exactly why
codegraph-mcp got the deeper, more complete test pass here.

## Resource/disk footprint left behind

- `.gnosis/lab/code-intelligence/` (project-local, evidence, tens of MB
  incl. node_modules/.venv): intentional, disposable, safe to delete
  after this report is reviewed.
- `~/.sverklo/models/` (~90 MB embedding model cache): outside the
  project, a normal consequence of running sverklo as designed.
- `~/.cce/projects/fixture-repo-*/` (1.7 MB): outside the project, ditto
  for code-context-engine.

Neither home-directory cache was deleted (they are harmless, and
deleting them is not necessary for the evidence trail); noted here for
full transparency per the M2 preflight's "no unexpected files outside
the project root" discipline -- these are expected, not unexpected,
consequences of real execution, but visibility matters regardless.

## Recommendation: HYBRID, but only as BENCHMARK-validated, not blind adoption

**codegraph-mcp: BENCHMARK winner for the structural graph role.**
Zero false positives or false negatives across every ground-truth
category actually tested (direct calls both directions, indirect chain,
blast radius, rename, deletion, overloading, dead code). CLI surface
maps 1:1 to its MCP tools (author-documented), so this benchmark's CLI-
only methodology tested it fairly and completely. Real cost: requires
Node 22.5+/24 (declared `engines` range is wrong), an operational
dependency Gnosis's own kernel does not otherwise have.

**sverklo: credible but incompletely tested here.** Every query actually
run against it matched ground truth exactly, and its bi-temporal,
git-pinned memory model is a real, non-overlapping capability
(codegraph-mcp has no equivalent "what did we believe about X at commit
Y" memory). Its MCP-native design means a fair, complete comparison
requires either a working MCP client (not achieved safely within this
session) or driving it through the same-quality proof/audit CLI paths
used here, which give partial but positive evidence, not full coverage.

**code-context-engine: REFERENCE, not a competitor in this category.**
Confirmed empirically to be a semantic retrieval index, not a structural
graph tool -- valuable for token-savings-oriented context retrieval, a
genuinely different, non-overlapping responsibility from callers/
callees/blast-radius. A HYBRID pairing (structural graph + semantic
retrieval) is legitimate under the Director's own rule ("acceptable
when responsibilities are clearly non-overlapping"), not two systems
doing the same job.

**codebase-memory-mcp: REJECT as a default; defer to a dedicated
security review.** Broadest language coverage on paper, but this
benchmark declined to run an unverified precompiled binary, so it has
no execution-backed evidence at all, only the M1 catalog/README read.

## Exact recommended architecture

Gnosis owns `gnosis.kernel.code_intelligence.CodeIntelligenceProvider`
(implemented, tested this milestone): `index()`, `callers()`,
`callees()`, `impact()`, returning typed `SymbolLocation`/`ImpactResult`
values, with a `CodeIntelligenceUnavailable` exception so code
intelligence is always optional, never a hard dependency of task
execution. `NullCodeIntelligenceProvider` is the default (always
unavailable) -- Gnosis works with zero code-intelligence configured.

`gnosis.kernel.code_intelligence_adapters.CodegraphMcpAdapter` is a real,
tested (including one end-to-end integration test against the actual
lab-installed tool, not just canned output) adapter satisfying the
contract by shelling out to codegraph-mcp's CLI. No other kernel code
imports codegraph-mcp directly -- everything goes through the interface,
so swapping in a `SverkloAdapter` later (once its MCP integration is
properly tested) or dropping codegraph-mcp entirely requires touching
only the adapter, never task/engine code. This satisfies the Director's
explicit architectural rule: Gnosis owns the contract, external tools
satisfy it, nothing wins by default.

**Not yet done, and deliberately out of scope for M2**: wiring
`CodegraphMcpAdapter` into `TaskEngine`/`DirectorOrchestrator` via the
M2.0 `McpRunnerConfig`, and building a `SverkloAdapter` once its MCP
protocol has been properly, safely tested (not CLI-only). Both are
small, additive follow-ups with the contract already in place.

## Remaining risks

- No candidate was benchmarked at real-repo scale (Gnosis's own repo has
  under 50 Python files; the fixture has 12-13). Incremental-vs-full
  indexing advantages several candidates advertise are invisible at this
  scale and were only functionally, not performance-, verified.
- sverklo's MCP integration remains untested end-to-end; its CLI-based
  evidence is positive but partial.
- codebase-memory-mcp has zero execution-backed evidence.
- The chosen adapter (codegraph-mcp) requires a Node runtime Gnosis's
  own kernel does not otherwise depend on -- an operational cost, not a
  correctness risk, since it is invoked as an external MCP server/CLI,
  never imported into the Python kernel.
