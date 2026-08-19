# m3-memory 2026.8.19.16 integration scorecard (Nicol workstation, 2026-08-19)

Fresh clone `external/repositories/m3-memory` @ `3b4133aa` (same package
version the M3 milestone saw). Installed as an isolated uv tool from a
copy. This pass turned the milestone's "BENCHMARK-LATER, integration path
failed" verdict into a working, understood integration path.

## Blocker #1 root-caused: uv-shim relaunch loses the venv (workaround: permanent)

Every `m3` invocation initially died with
`ModuleNotFoundError: No module named 'm3_memory'`. `python -v` tracing
showed two interpreter bootstraps: `cli.py`'s import-time
`_ensure_utf8()` re-execs via `sys.orig_argv`, and under a uv tool shim
on Windows the re-exec resolves to the base interpreter without the tool
venv, then re-runs the launcher zip whose import fails. Setting
`PYTHONUTF8=1` (user env; also pinned in `.mcp.json` and tests)
short-circuits the re-exec — the package's own documented escape hatch.
With it set, `m3 --version`, `m3 doctor`, and the whole memory surface
work.

## Blocker #2 root-caused: `--database <fresh path>` cannot work by design

Reproduced the milestone's `no such table: memory_items` failure and
found the mechanism: migration bookkeeping is per-install, not per-file.
Against a brand-new `--database` target the migrator reports
"Database is up to date. No pending migrations" while the file contains
**zero tables** (verified via sqlite_master), then the write fails.
Conclusion: `--database` is not a provisioning mechanism.

**Working alternative, verified:** env-pinned roots
(`M3_MEMORY_ROOT`/`M3_ENGINE_ROOT`/`M3_CONFIG_ROOT`) — a fresh root gets
fully migrated and the write→fresh-process-search cycle passes
(`tests/integration/test_memory_fabric_smoke.py::TestM3RecallSmoke`).

## Verified working (default store and env-pinned root)

- `memory_write` → `Created: <uuid>`; fresh-process `memory_search`
  returns the exact fact (score 1.0, FTS-only fallback — no embedder
  tier configured, degradation is explicit in the tool's own logs).
- `memory_delete --no-hard` soft-deletes; search then returns empty.
- `m3 doctor` runs end-to-end (rc=1 only for the unconfigured embedding
  cascade + not-installed optional components; bridge/store/entrypoints
  all OK).

## Still deliberately not done

- `install-m3` / `m3 setup` (secondary GitHub payload, background
  services, cognitive loop): unchanged supply-chain caution from the M3
  milestone. MCP exposure was configured manually in `.mcp.json` instead.
- Embedding tier configuration/benchmark: belongs to the M4 provider
  decision, not the Phase -1 gate.

## Verdict

Upgraded from BENCHMARK-LATER to **INTEGRATION-PATH-PROVEN**: usable for
broad-recall smoke duty today via env-pinned roots + PYTHONUTF8=1; still
needs the M4 benchmark (with an embedder) before production adapter
status.
