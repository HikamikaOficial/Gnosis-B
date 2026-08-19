# ADR-0002 — Reconcile package layout to `src/gnosis/`

- Status: ACCEPTED
- Date: 2026-08-19
- Deciders: Claude Fable 5 (autonomous, reversible technical decision)

## Context

The M0–M3 baseline built the real kernel in a top-level `gnosis/`
package. The v0.3 environment pack's constitution (CLAUDE.md, "Desarrollo
propio") names `src/gnosis/` as the home of Gnosis code and shipped an
empty `src/gnosis/` scaffold. Two competing locations for the same
package is an active hazard: future sessions/agents would split code
across both.

## Decision

`git mv gnosis src/gnosis` (history preserved as renames). Packaging made
explicit: hatchling build backend with `packages = ["src/gnosis"]`;
pytest resolves imports via `pythonpath = ["src"]`, so the suite runs
without installing the package. Import name (`gnosis.*`) is unchanged —
only the on-disk location moved. Documentation references updated
(README). Milestone docs (docs/M*.md) keep their historical paths as
written records of past states.

## Alternatives considered

- Keep `gnosis/` and delete the scaffold: cheaper today, but leaves the
  constitution permanently contradicting the tree it governs.
- Defer: highest risk — the ambiguity window is exactly when a future
  agent splits the package.

## Verification

Full suite after the move: 167/167 passing
(`uv run --no-project --with pytest --with pytest-asyncio python -m pytest tests/`).
