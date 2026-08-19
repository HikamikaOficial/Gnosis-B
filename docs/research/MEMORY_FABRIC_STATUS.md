# GNOSIS Memory Fabric Status

## Required architecture

- **M3** = broad recall / cross-agent retrieval.
- **ZMem** = trust, authority, quarantine, lineage, receipts.
- **Graphify** = optional structural code graph after benchmark.
- **Obsidian** = optional human-readable mirror only.

## Local clones

- M3: ['C:\\Users\\nicol\\Desktop\\Claude Code Proyectos\\GnosisAgentAi\\external\\repositories\\m3-memory']
- ZMem: ['C:\\Users\\nicol\\Desktop\\Claude Code Proyectos\\GnosisAgentAi\\external\\repositories\\zmem']
- Graphify: ['C:\\Users\\nicol\\Desktop\\Claude Code Proyectos\\GnosisAgentAi\\external\\repositories\\graphify']

## CLI state

- M3: **FOUND** — `C:\Users\nicol\.local\bin\m3.EXE`
- ZMem: **FOUND** — `C:\Users\nicol\.local\bin\zmem.EXE`

### M3 checks

- `m3 --version` → rc=0

```text
m3-memory 2026.8.19.16
```
- `m3 doctor` → rc=1

```text
[~] m3 DEGRADED · 0 memories · embedder: pure-Python (HTTP) · chatlog: wired (0 rows yet)


agent MCP configs:
  (no agent config declares an m3 'memory' server)
[OK] resolved bridge: C:\Users\nicol\AppData\Roaming\uv\tools\m3-memory\Lib\site-packages\m3_memory\bin\memory_bridge.py
store: SQLite — C:\Users\nicol\.m3\engine\agent_memory.db
❌ embedding-cascade: broken (tier1 not-configured, tier2 offline, 2836ms)
embed-server: not installed (optional)
⚠️  oxidation: not installed (pure-Python fallback, slower)
✅ governor: OK (no legacy scheduled tasks)
locks: ok
embed-space: ok (no embeddings yet)
✅ schedules: OK (installed jobs resolve to a real interpreter)
⚠️  shared-embedder: 3 issue(s) — run `m3 doctor --fix`
plugin: not installed via Claude Code (CLI-only / unknown)
✅ entrypoints: OK — `m3` on PATH runs this install (2026.8.19.16)
✅ chatlog hooks: OK (0 verified against disk)
agent paths: no wired agent configs found
⚠️  cognitive loop: not installed — derived knowledge won't build; `m3 setup`
claude mcp: no m3 memory server registered (run `m3 setup`)

For full detail, run:  m3 doctor --verbose
```
### ZMem checks

- `zmem --version` → rc=0

```text
zmem.EXE 0.1.17
```
- `zmem status --summary-only` → rc=1

```text
Traceback (most recent call last):
  File "C:\Users\nicol\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none\Lib\shutil.py", line 633, in _rmtree_unsafe
    os.unlink(fullname)
PermissionError: [WinError 32] El proceso no tiene acceso al archivo porque está siendo utilizado por otro proceso: 'C:\\Users\\nicol\\AppData\\Local\\Temp\\tmp7cgk06gm\\memory.sqlite'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "C:\Users\nicol\.local\bin\zmem.EXE\__main__.py", line 10, in <module>
  File "C:\Users\nicol\AppData\Roaming\uv\tools\zerker-memory\Lib\site-packages\zerker_memory\cli.py", line 2036, in main
    result = build_status_report(
             ^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\nicol\AppData\Roaming\uv\tools\zerker-memory\Lib\site-packages\zerker_memory\cli.py", line 4949, in build_status_report
    doctor = run_doctor(
             ^^^^^^^^^^^
  File "C:\Users\nicol\AppData\Roaming\uv\tools\zerker-memory\Lib\site-packages\zerker_memory\doctor.py", line 69, in run_doctor
    checks.append(check_eval())
                  ^^^^^^^^^^^^
  File "C:\Users\nicol\AppData\Roaming\uv\tools\zerker-memory\Lib\site-packages\zerker_memory\doctor.py", line 402, in check_eval
    result = run_eval()
             ^^^^^^^^^^
  File "C:\Users\nicol\AppData\Roaming\uv\tools\zerker-memory\Lib\site-packages\zerker_memory\eval.py", line 27, in run_eval
    with tempfile.TemporaryDirectory() as tmp:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\nicol\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none\Lib\tempfile.py", line 950, in __exit__
    self.cleanup()
  File "C:\Users\nicol\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none\Lib\tempfile.py", line 954, in cleanup
    self._rmtree(self.name, ignore_errors=self._ignore_cleanup_errors)
  File "C:\Users\nicol\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none\Lib\tempfile.py", line 934, in _rmtree
    _shutil.rmtree(name, onexc=onexc)
  File "C:\Users\nicol\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none\Lib\shutil.py", line 781, in rmtree
    return _rmtree_unsafe(path, onexc)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\nicol\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none\Lib\shutil.py", line 635, in _rmtree_unsafe
    onexc(os.unlink, fullname, err)
  File "C:\Users\nicol\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none\Lib\tempfile.py", line 909, in onexc
    _os.unlink(path)
PermissionError: [WinError 32] El proceso no tiene acceso al archivo porque está siendo utilizado por otro proceso: 'C:\\Users\\nicol\\AppData\\Local\\Temp\\tmp7cgk06gm\\memory.sqlite'
```

## Gate

Memory Fabric is READY only after both primary engines are installed, connected to the active Claude/Codex environment where supported, and pass a synthetic cross-session continuity/governance smoke test.

---

# Phase -1 validation (2026-08-19, this machine)

## Verdict: GATE PASSED, with two documented upstream caveats

Both engines are installed as isolated `uv tool` environments (built from
copies of the fresh clones under `.gnosis/lab/memory/candidates/*-fresh/`;
the originals in `external/repositories/` were never modified), both are
wired to Claude Code via the project `.mcp.json`, and the synthetic
cross-session continuity/governance smoke test passed end to end. The
re-runnable form lives in `tests/integration/test_memory_fabric_smoke.py`
(3 tests, all passing; they skip cleanly on machines without the CLIs).

## Versions validated

- zmem 0.1.17 (`external/repositories/zmem` @ `84ffd2de`)
- m3-memory 2026.8.19.16 (`external/repositories/m3-memory` @ `3b4133aa`)

## What was verified live (each step a separate OS process)

### ZMem — governance plane (all confirmed on 0.1.17)

- `remember` (system) → active/trust 0.9; `propose` (agent) →
  quarantined/trust 0.5. Default `search` and `inject` exclude quarantine.
- `inject` produced a Merkle-proof receipt (root + per-memory leaves +
  `action_id`) over the two deliberately contradictory active facts.
- `revoke` of the stale fact: subsequent `inject` retrieves only the
  current fact; `why` on the pre-revocation action still lists the revoked
  memory labeled `[semantic/revoked]` — backward influence traceability.
- `audit health`: healthy, honest self-limitation ("lexical signals only").
- Synthetic data was revoked/rejected after proof. Raw artifacts:
  `.gnosis/lab/memory/results/zmem-0.1.17/`.

### M3 — recall plane

- `memory_write` then fresh-process `memory_search` on the default store:
  exact recall (FTS-only fallback; no embedder configured yet).
- Same flow verified against a fully fresh, env-pinned state root
  (`M3_MEMORY_ROOT`/`M3_ENGINE_ROOT`/`M3_CONFIG_ROOT`): migrations
  provision the new root and the write/read cycle works. **Env-pinned
  roots are the correct integration path for a future Gnosis adapter.**
- Synthetic data soft-deleted after proof (search returns empty).

## Root-caused findings (both reproducible, neither blocks the gate)

1. **m3 `--database <path>` is broken upstream** (carried over from the
   M3-milestone scorecard, now root-caused): migration state is tracked
   per-install, not per-file, so a fresh `--database` target reports
   "up to date. No pending migrations" while containing **zero tables**,
   and the write then fails with `no such table: memory_items`. Workaround
   is above (env-pinned roots); do not use `--database` for isolation.
2. **m3 under `uv tool` shims on Windows initially failed with
   `ModuleNotFoundError: No module named 'm3_memory'`**: `cli.py`'s
   `_ensure_utf8()` re-execs via `sys.orig_argv`, and the re-exec resolves
   to the base interpreter without the tool venv. Fixed permanently by
   setting the user-level env var `PYTHONUTF8=1` (the package's own
   documented short-circuit); `.mcp.json` and the smoke tests also pin it
   explicitly for portability.
3. **zmem 0.1.17 diagnostic subcommands crash on Windows** (`status`,
   `doctor` — the rc=1 traceback above): `doctor.check_eval → eval.run_eval`
   builds a temp workspace and `TemporaryDirectory` cleanup fails with
   WinError 32 because a SQLite handle is still open (POSIX tolerates
   unlinking open files; Windows does not). Core memory commands
   (remember/propose/search/inject/revoke/why/audit) are unaffected —
   `audit health` is the working health probe on Windows.

## Degradations accepted for Phase -1 (revisit at M4 adapter selection)

- No embedding tier configured for m3 → hybrid search degrades to FTS
  lexical. Good enough for smoke/recall-of-exact-facts; a benchmark with a
  local embedder belongs to the M4 provider decision.
- m3's full `install-m3`/`setup` flow (secondary GitHub payload, background
  services, cognitive loop) remains deliberately NOT run, consistent with
  the M3-milestone supply-chain caution. MCP wiring was done with config
  only (`.mcp.json`), no installer executed.
- Claude Code must be restarted (or the project MCP config approved) for
  the two MCP servers to appear in a session; config is in place.

