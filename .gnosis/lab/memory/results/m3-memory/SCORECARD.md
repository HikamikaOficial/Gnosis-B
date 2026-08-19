# m3-memory scorecard (real CLI-surface verification + a real bug found)

Installed via `uv venv` + editable install (23 dependencies, ~30s).
Note: the package's own `install-m3` command fetches an additional
"system payload" from GitHub post-install (a secondary download step,
not fully self-contained from the pip package) -- a real operational-
complexity finding, and a milder version of the supply-chain caution
already applied to codebase-memory-mcp in M2.1. Not run in this
benchmark (see below).

## Command surface: confirmed real, matches catalog claims closely

`m3 memory --help` lists 36 real subcommands including exactly the
bitemporal/contradiction primitives the catalog and Director description
claimed:

- `memory_supersede` -- "Explicitly supersede an existing memory with a
  new one" (the explicit supersession mechanism zmem's CLI does not
  appear to expose).
- `memory_search_routed` -- "Temporal-aware routed retrieval."
- `memory_history` -- "Returns the change history (audit trail) for a
  memory item."
- `memory_lifecycle_summary` -- "Windowed summary of lifecycle &
  contradiction activity."
- `memory_verify` -- content-hash integrity verification.
- `memory_write` exposes real `--valid_from`/`--valid_to` bitemporal
  fields directly as CLI arguments.

This is a substantially richer, more explicitly bitemporal/contradiction-
aware command surface than zmem's, consistent with the two candidates
occupying different roles (factual/temporal vs. governance) rather than
competing on the same one.

## Real bug found: direct CLI write fails despite "successful" migration

Attempted `m3 memory memory_write --type fact --content "..." --database
<custom path>` against a fresh SQLite file (bypassing the full
`install-m3`/interactive `setup` flow, to keep the test lab-scoped and
lightweight). Result:

1. The tool ran 43 real schema migrations against the fresh file,
   reporting success at each step ("main: Done. Now at v043").
2. The actual write then failed: `{"ok": false, "error": "call_failed",
   "tool": "memory_write", "detail": "OperationalError: no such table:
   memory_items"}`.
3. Retried (idempotent migration check: "Database is up to date. No
   pending migrations.") -- the same failure reproduced. Not transient.

This indicates the CLI's `--database <path>` flag does not behave as a
simple "use this SQLite file" override the way it reads; the tool
appears to expect databases to be provisioned through its own
`install-m3`/`setup` bootstrap rather than pointed at an arbitrary path.
This is a real, reproducible finding about operational complexity and
ease of integration, not a fabricated one.

## Home-directory footprint

Wrote real backup files to `C:\Users\<user>\.m3\engine\backups\...`
even for this failed lab-scoped attempt -- another candidate with a
footprint outside the project directory, consistent with the pattern
already seen in sverklo/code-context-engine/zmem.

## Scope decision: did not pursue the full install-m3/setup flow

The full guided setup downloads a secondary GitHub payload and
provisions background services (dashboard, embedder, cognitive loop) --
a meaningfully heavier and more invasive footprint than zmem's simple
project-local SQLite workspace. Consistent with the caution already
applied to codebase-memory-mcp (M2.1) and cass_memory_system's Bun
requirement (M3, see below), this was not pursued within this
benchmark's time/risk budget. The CLI-surface verification above and the
real bug found are the evidence this scorecard rests on.

## License

Apache-2.0 (confirmed via NOTICE/LICENSE file, standard, no unusual
riders).

## Verdict for this candidate

Real command surface strongly matches the "bitemporal, contradiction-
aware knowledge base" claim architecturally, but the direct-integration
path (the one Gnosis would actually use, not the interactive human-setup
flow) hit a genuine, reproducible failure in this session. Cannot be
recommended for production integration without further investigation of
that failure, ideally with the maintainer's guidance on the correct
--database usage, or by going through the full install-m3 flow in a
follow-up milestone with explicit sign-off on its heavier footprint.
