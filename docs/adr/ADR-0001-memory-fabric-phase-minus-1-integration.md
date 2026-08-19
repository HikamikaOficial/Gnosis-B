# ADR-0001 — Memory Fabric Phase -1 integration decisions

- Status: ACCEPTED
- Date: 2026-08-19
- Deciders: Claude Fable 5 (autonomous, per 01_START_HERE.md mandate)
- Evidence: `docs/research/MEMORY_FABRIC_STATUS.md`,
  `tests/integration/test_memory_fabric_smoke.py`,
  `.gnosis/lab/memory/results/zmem-0.1.17/`,
  `.gnosis/lab/memory/results/m3-memory-2026.8.19.16/`

## Context

Phase -1 requires M3 (broad recall) and ZMem (governance) installed,
connected and smoke-tested before substantial kernel work. A previous
milestone (docs/M3_MEMORY_PLANE.md) already defined the Gnosis-owned
memory contract (`gnosis.kernel.memory.MemoryProvider`, the in-process
reference implementation and `MemoryRouter`) and benchmarked both engines
from a reference corpus; this ADR covers how the engines are actually
installed and integrated on the Nicol workstation.

## Decisions

### 1. Engines are installed as isolated `uv tool` environments, built from copies

`external/repositories/{zmem,m3-memory}` stay read-only clones. Copies in
`.gnosis/lab/memory/candidates/{zmem,m3-memory}-fresh/` are the build
sources (`uv tool install --from <copy> <package>`). This keeps installs
reversible (`uv tool uninstall`), keeps the originals byte-identical, and
puts `zmem`/`m3` on PATH where doctors and adapters expect them.

### 2. `PYTHONUTF8=1` is part of the workstation baseline

m3's `cli.py` re-execs the interpreter for UTF-8 mode; under uv tool
shims on Windows the re-exec loses the tool venv and every `m3` call dies
with `ModuleNotFoundError`. `PYTHONUTF8=1` (user env var, plus explicit
pinning in `.mcp.json` and tests) short-circuits the re-exec — the
package's own documented escape hatch. UTF-8 mode is also the direction
CPython itself is heading on Windows.

### 3. m3 state isolation uses env-pinned roots, never `--database`

`--database <fresh path>` is broken upstream (migration bookkeeping is
per-install, so a fresh file gets no schema; verified, zero tables +
`no such table: memory_items`). `M3_MEMORY_ROOT`/`M3_ENGINE_ROOT`/
`M3_CONFIG_ROOT` provision correctly and are the only isolation mechanism
a future Gnosis adapter may use.

### 4. MCP wiring is config-only; m3's guided `setup` stays unexecuted

Both engines are exposed to Claude Code through the project `.mcp.json`
(zmem: `zmem --db <project>/.zerker/memory.sqlite mcp --profile agent`;
m3: tool-venv python + installed `memory_bridge.py` with pinned roots).
The `install-m3`/`m3 setup` flow (secondary GitHub payload download,
background services) remains out of bounds pending a dedicated
supply-chain review — carried over from the M3-milestone caution.

### 5. Role assignment is unchanged from D-012/D-013

ZMem = governance/trust/receipts (fully validated live on 0.1.17).
M3 = broad recall (write/search validated; embeddings unconfigured, FTS
fallback accepted for Phase -1). No production `MemoryProvider` adapter
is selected yet — that is the M4 decision, now unblocked because both
engines have a proven working integration path.

## Consequences

- The Phase -1 memory gate is PASSED; kernel work may proceed.
- The M4 adapter decision inherits two live upstream caveats (zmem
  Windows diagnostic-command crash; m3 embedding tier unconfigured) and
  one hard rule (no `--database`).
- If either engine is upgraded, rerun
  `tests/integration/test_memory_fabric_smoke.py` and `scripts/memory_doctor.py`
  before trusting it (see L-0001..L-0003 in docs/LEARNINGS.md).
