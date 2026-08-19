# codegraph-mcp scorecard (against fixture ground truth)

Ran from source (built via `npm install && npm run build` in the lab copy),
invoked directly via its CLI (`dist/bin/codegraph.js`), no MCP protocol
driving needed for these tests since it exposes equivalent CLI commands.
Required a portable Node 24 binary (`node:sqlite`, needs Node 22.5+); the
declared `engines` range in package.json (`>=20.0.0 <25.0.0`) does not
match this actual runtime requirement -- a real, reproducible finding.

## Results

| Test | Ground truth | codegraph-mcp result | Verdict |
|---|---|---|---|
| Direct calls (entrypoint callees) | compute_b_renamed, compute_c | compute_b_renamed, compute_c | MATCH |
| Direct calls (compute_c callers) | entrypoint | entrypoint | MATCH |
| Indirect chain (compute_d callers) | compute_b_renamed, compute_c | compute_b_renamed, compute_c | MATCH |
| Blast radius of compute_c change | compute_c, entrypoint, test_entrypoint | same 3, plus 2 file-level nodes | MATCH (function-level exact) |
| Renamed symbol | compute_b absent, compute_b_renamed present | correct | MATCH |
| Deleted symbol | legacy_function absent | "Symbol not found" | MATCH |
| Overloaded names | 2 distinct `process`, disambiguated by file | both returned with file:line | MATCH |
| Dead code | unused_function, 0 callers | "No callers found" | MATCH |
| New file + incremental sync | new_feature added, calls compute_b_renamed; entrypoint still calls it too | both callers found post-sync | MATCH (after fixing a test-construction bug on my end, see below) |
| Circular dependency | pkg.circular_x <-> pkg.circular_y | not explicitly queried via a dedicated cycle-detection command; both symbols indexed correctly | NOT DIRECTLY TESTED (no cycle-report command found in this CLI surface) |

Zero false positives, zero false negatives observed at the function-symbol
level across every test that was run. One self-inflicted test-construction
bug (a synthetic "add one file" overlay left `core.py` inconsistent with
the renamed symbol) was caught and corrected using the actual `git
archive` snapshot of commit c4 instead of a hand-patched partial overlay;
noted for transparency, not a candidate defect.

## Performance

| Metric | Value |
|---|---|
| Initial index (11 files, c1) | 3.2s internal / 7.0s wall |
| Full index (12 files, c5/final) | 3.6s internal / 8.5s wall |
| Incremental sync (4 changed files, c1 index -> c4 state) | 4.8s internal / 8.7s wall |
| Index size on disk | 157-165 KB (SQLite) for this ~12-file fixture |
| Wall-vs-internal gap | ~4-5s, dominated by Node process startup, not indexing work |

Fixture is too small to show a meaningful incremental-vs-full speedup
(both are dominated by fixed Node startup cost); functional correctness
of incremental sync was verified, throughput was not meaningfully
distinguishable at this scale. A real repo-scale test would be needed to
measure the actual incremental-indexing win codegraph-mcp claims.

## Windows behavior

Runs natively on Windows 11 via Git Bash without WSL. Required Node 24
specifically (portable binary, not the system's Node 20.18.0) due to
`node:sqlite`. Colored terminal output requires `FORCE_COLOR=0
NO_COLOR=1` to get clean redirectable text for scripting/logging.

## Reproducing

    node <lab>/candidates/codegraph-mcp/dist/bin/codegraph.js init .
    node <lab>/candidates/codegraph-mcp/dist/bin/codegraph.js callers compute_c
    node <lab>/candidates/codegraph-mcp/dist/bin/codegraph.js impact compute_c

Raw command outputs are the sibling `.txt` files in this directory.
