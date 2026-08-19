# sverklo scorecard (against fixture ground truth)

Ran from source (built via `npm install && npm run build` in the lab
copy). Required a portable Node 24 binary (`node:sqlite` needs Node
22.5+; this machine's system Node is 20.18.0). CLI query surface is
narrower than codegraph-mcp's -- most structural queries (callers,
impact/blast-radius) are MCP tools, not CLI subcommands; `sverklo prove`
is the CLI-accessible window into the same underlying symbol-graph
engine and was used for the accuracy test below.

## Indexing performance

| Run | Internal time | Wall time | Notes |
|---|---|---|---|
| First-ever reindex (cold) | 10.5s | 20.6s | includes mandatory ~90MB embedding-model download (`provider_init` alone: 8.8s) |
| Second reindex (model cached) | 2.7s | 4.7s | `provider_init` drops to 1.2s once the model is on disk |

Real, comparable to codegraph-mcp's steady-state numbers (2.7-3.6s
internal for a similarly sized fixture) once the one-time model download
is out of the way. The first-run cost is a genuine operational
difference from codegraph-mcp, which needs no model download.

## Accuracy: `sverklo prove --no-write --guided --markdown`

Selected `compute_b_renamed` as the central symbol and reported:
- Defined at `pkg/helpers.py:4` -- correct.
- 2 references across 2 files: `pkg/core.py:6` (entrypoint),
  `pkg/new_module.py:5` (new_feature) -- exact match to ground truth
  (compute_b_renamed's only callers are core.entrypoint and
  new_module.new_feature). Zero false positives, zero false negatives.

## MCP protocol integration: attempted, not completed

A generic MCP stdio JSON-RPC probe script was written
(`tools/mcp_probe.py`) and run against sverklo's server mode. It hung
past a reasonable timeout (framing-format mismatch was suspected --
Content-Length-header framing vs newline-delimited JSON -- not root
caused) and left one orphaned `node` process holding stdin open, which
was identified via `Get-CimInstance Win32_Process` (its command line
made it unambiguous which process it was) and terminated with
`Stop-Process -Force`. Given the real risk of leaving orphaned
long-running processes -- something the Director explicitly flagged as
an operational discipline in the M2 preflight -- further live-protocol
debugging was stopped in favor of the CLI-based evidence above, which
exercises the same underlying query engine `sverklo prove` documents
itself as using.

This is a genuine, reportable finding, not a candidate defect: sverklo's
primary interface is MCP-native (correct for its purpose), which means
CLI-only benchmarking under-tests it relative to codegraph-mcp, whose
CLI commands mirror its MCP tools 1:1 by the author's own documentation.

## Windows behavior

Runs natively via Git Bash, no WSL required. Required a portable Node 24
binary distinct from the system's Node 20.18.0. `sverklo doctor`
documents a specific Windows path-normalization fix (v0.18 changelog),
consistent with genuine Windows testing by the upstream project.

## Reproducing

    node <lab>/candidates/sverklo/dist/bin/sverklo.js reindex . --force --timing
    node <lab>/candidates/sverklo/dist/bin/sverklo.js prove --no-write --guided --markdown

Raw outputs are the sibling files in this directory.
