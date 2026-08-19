# code-context-engine (CCE) scorecard (against fixture ground truth)

Ran from source in an isolated `uv venv` inside the lab copy (no system
Python packages touched). No Node/runtime version issues (Python
3.11+ requirement, system has 3.13).

## Important category clarification

CCE is a semantic/embedding retrieval index (94% token-savings pitch),
not a structural symbol/call-graph tool like sverklo or codegraph-mcp.
This was the M1 research conclusion and this benchmark confirms it
empirically: `cce search` returns relevance-ranked chunks, not exact
caller/callee/blast-radius answers. It should be scored as a
complementary tool, not a losing competitor in the same category.

## Indexing performance

| Run | Wall time | Notes |
|---|---|---|
| First-ever index (cold) | 55.6s | dominated by embedding-model download from HuggingFace Hub (largest cold-start cost of the three candidates tested) |
| Re-index (model cached) | 5.5s | "93% cache hit" reported internally |

## Accuracy: `cce search <query>`

| Query | Top result | Ground truth relevance |
|---|---|---|
| "compute_c" | compute_c itself, then entrypoint, compute_d, compute_b_renamed, new_feature (all 5 fixture functions) | correct symbol ranked #1; not scoped to only true callers/callees (expected for semantic search, not a structural query) |
| "what calls compute_b_renamed" | compute_b_renamed, entrypoint, new_feature, compute_c, compute_d | both true callers (entrypoint, new_feature) ranked in top 3, but not cleanly separated from non-callers |
| "process function overloaded" | overload_ns1.process, overload_ns2.process (both, ranked #1 and #2) | correct -- both overloaded symbols surfaced together |
| "unused dead code function" | dead_code.unused_function (#1) | correct |

Reports its own token-savings metric per query (e.g. "135 tokens served
vs 167 full file tokens, 19% saved") -- this is a real, self-measured
number from an actual run, not a vendor claim taken on faith, though it
is still CCE measuring itself rather than an independent measurement.

## Data locality (operational-complexity finding)

CCE stores its index globally under `~/.cce/projects/<name-hash>/`, not
inside the project directory -- unlike codegraph-mcp (`.codegraph/` in
the repo) or sverklo (project index local, only the embedding model
cached globally under `~/.sverklo`). For this fixture: 1.7 MB under
`~/.cce`. This is a real operational-complexity difference: cleanup and
discovery require knowing to look outside the project tree.

## Windows behavior

Installed and ran natively via `uv venv` + editable install, no WSL
required. No crashes encountered; the project's own pyproject.toml
documents a real past Windows-relevant bug (tree-sitter ABI mismatch
causing SIGSEGV, issues #113/#114) with a defensive version pin -- a
genuine maturity signal (the maintainers hit and fixed a real crash).

## Reproducing

    cce index
    cce search "compute_c"

Raw outputs are the sibling files in this directory.
