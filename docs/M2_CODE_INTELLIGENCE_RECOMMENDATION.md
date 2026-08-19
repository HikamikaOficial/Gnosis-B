# M2 Code Intelligence -- Candidate Comparison and Recommendation

Prepared as part of M1 closeout, per Director instruction. Read-only research
against the local reference corpus at
`Pruebas de rendimiento/recursos/09-code-intelligence`.
No candidate was cloned elsewhere, built, or executed; nothing in the corpus
was modified (verified: every interaction with that path was ls/cat/head/
Read/Grep -- zero Write, Edit, git, npm, pip, or cargo commands against it).
This mirrors the corpus's own disclaimer: nothing here is VERIFIED,
findings are INFERRED from reading code and docs, exactly as the M0/M1
constitution requires: no LLM may mark work verified merely by claiming it
is correct.

## Scope note: Graphify

The Director brief named Graphify among the candidates to inspect. It does
not exist anywhere in the local corpus: not among the 17 cloned
09-code-intelligence repos, not in INDICE.md, not in the _reportes
directory. Either it was not harvested into this corpus, was renamed, or
was conflated with a similarly named candidate (Graft, glyphtrail). This
recommendation is based on the 17 candidates that are actually present,
which fully cover the category the Director described: symbol graphs, call
graphs, blast radius, repo memory.

## Candidates inspected

17 total in 09-code-intelligence/: 6 already scored by the SkinAI first
pass (codebase-memory-mcp, m1nd, rag-rat, serena, Lore, glyphtrail), 11
UNTRIAGED (only mechanically scanned, GNOSIS-corpus score only). Source and
config were read directly for the three the Director named by name plus the
highest-scored analyzed candidates; the remaining untriaged ones were left
at catalog-level evidence (see "Not evaluated further" below), deliberately,
since this milestone explicitly excludes integrating code intelligence, so
exhaustive due diligence on a 17-candidate, already-saturated category is
not warranted yet.

| Candidate | License | Lang/Runtime | Tests | Windows | MCP | Verdict |
|---|---|---|---|---|---|---|
| sverklo | MIT | TS/Node | 95 test files, own 180-task public bench | explicit, path bug fixed v0.18 | native | BENCHMARK |
| codegraph-mcp | MIT | TS/Node, self-contained bundle | 138 test files | explicit, no Node required | native, 8+ agents | BENCHMARK |
| code-context-engine | MIT | Python 3.11+ | 36 test files, CI badge | explicit | native, MCP registry listed | REFERENCE (complementary) |
| codebase-memory-mcp | MIT | tree-sitter+LSP, precompiled binaries | present | via installer | native, 15 tools | REFERENCE (schema); reject as default |
| m1nd | MIT | Rust workspace, single binary | present | unconfirmed | native | not evaluated further |
| rag-rat | MIT | Rust | present | unconfirmed | native | not evaluated further |
| serena | MIT | Python, LSP-delegated | present | unconfirmed | native | ADOPT-AS-REFERENCE (pattern) |
| Lore | MIT | SCIP+LSP | present | unconfirmed | native | not evaluated further |
| glyphtrail | EUPL-1.2 | Rust | present | unconfirmed | native | REJECT (copyleft, saturated arena) |
| ultracode | AGPL-3.0 | TS | -- | -- | -- | REJECT (copyleft) |
| cartographer, context-mode | none on disk | -- | -- | -- | -- | REJECT (no license) |
| sense, Graft, wonk, roam-code, code-review-graph | mixed | -- | -- | -- | -- | not evaluated further |

## Detail on the three Director-named candidates

sverklo -- MIT. 280 TS source files, 95 test files (colocated *.test.ts),
plus a dedicated benchmark harness with a public, hand-verified 180-task
ground truth (sverklo/sverklo-bench) and a published leaderboard. Minimal
runtime deps (MCP SDK, chokidar, onnxruntime-node for bundled local
embeddings, optional tree-sitter). Telemetry off by default, opt-in.
Bi-temporal memory pinned to git SHAs (valid_from_sha/valid_until_sha) is a
genuinely distinct capability: it can answer "what did we believe about X
at commit Y." Windows support is explicit and was patched (v0.18 changelog:
path handling fixed). Actively released (v0.20.2 at inspection time). The
embedding model downloads from HuggingFace on first run (about 86 MB,
network-dependent once, then cached locally), worth noting as a first-run
network dependency, not an ongoing one.

codegraph-mcp -- MIT. Largest test suite of the three (138 files under
__tests__/). Self-contained bundled runtime (no separate Node.js install
required, unlike sverklo). Explicit Windows/macOS/Linux support with native
installers. Broadest agent coverage (Claude Code, Cursor, Codex, OpenCode,
Gemini, Antigravity, Kiro). Telemetry is opt-out (asked at install, default
unclear from docs alone) with a public, auditable telemetry-worker and a
documented field allowlist (no code, paths, or filenames collected). Backed
by a commercial "CodeGraph platform" in beta, active-maintenance incentive,
but worth monitoring for future open-core feature bifurcation.

code-context-engine (CCE) -- MIT. Python 3.11+, PyPI-published, CI badge
green, listed in the MCP registry. Architecturally different from the other
two: it is a semantic/embedding retrieval index optimized for token savings
(94% fewer input tokens claimed), not a structural symbol/call graph. This
makes it complementary rather than competing with sverklo/codegraph-mcp: a
retrieval layer versus a structural-relationship layer.

## Why BENCHMARK, not ADOPT, for sverklo and codegraph-mcp

Both are credible: MIT, Windows-verified, MCP-native, well-tested, actively
maintained. Neither has been run against Gnosis's own code or any repo
under this project's control, every claim (F1 scores, token savings,
coverage) is self-reported by the vendor, exactly the class of claim
CLAUDE.md forbids treating as verified. The right next step is a real,
deterministic comparison using Gnosis's own M0/M1 Verifier interface, not a
catalog-score pick.

## Recommended M2 architecture

Per Gnosis's own design principle (intelligence inside agents, deterministic
control outside agents), a code-intelligence graph belongs inside the
agent's toolset, not inside the Gnosis kernel. The kernel's job is only to
wire the MCP config into the claude CLI invocation, it already has the
hook: `claude --help` (verified in M0) exposes `--mcp-config <configs...>`,
and ClaudeCodeCLIRunner.build_argv() already accepts extra_args.
Concretely:

1. M2.0 (small, additive): add first-class mcp_config support to
   ClaudeCodeCLIRunner alongside the existing extra_args escape hatch.
2. M2.1: stand up sverklo and codegraph-mcp against a real repository
   (Gnosis's own once it has grown, or a borrowed representative OSS repo),
   build a small hand-verified ground-truth task set (sverklo's own bench
   methodology is the strongest template present in the corpus), and run
   both through Gnosis's CommandVerifier/CompositeVerifier so the
   comparison itself produces deterministic, computer-checked evidence
   rather than another self-reported number.
3. M2.2: pick one as the default mcp_config for Director-run tasks against
   the Gnosis codebase (or keep both swappable behind the same config knob
   if the benchmark does not produce a clear winner).
4. Never build a Gnosis-native code graph from scratch. That is exactly the
   redundant-infrastructure outcome the reference-corpus process exists to
   prevent, two strong, actively maintained, MIT, Windows-verified,
   MCP-native candidates already exist.

code-context-engine's pattern (token-savings retrieval index) and serena's
pattern (LSP-delegated semantic ops instead of a bespoke graph) are both
worth keeping as reference architectures for later, complementary
milestones, not part of the M2.1 benchmark, since the Director's ask was
specifically about symbol/call graphs and blast radius.

## Not evaluated further this milestone

m1nd, rag-rat, Lore, sense, Graft, wonk, roam-code, code-review-graph,
cartographer, context-mode, ultracode: an already-saturated 17-candidate
arena where two credible, well-tested, Windows-verified finalists (sverklo,
codegraph-mcp) are sufficient to carry into an M2 benchmark. ultracode
(AGPL-3.0) and glyphtrail (EUPL-1.2) are blocked on copyleft licensing;
cartographer and context-mode ship no license file at all and are blocked
until that is resolved upstream.
