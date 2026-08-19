# Official Tooling Notes — Snapshot 2026-08

These notes explain assumptions encoded in the pack. Re-verify against current official docs before relying on a version-specific feature.

## Claude Code

The pack expects modern Claude Code with:
- Fable model selection;
- `effortLevel`;
- auto-memory;
- project subagents;
- subagent persistent `memory`;
- hooks;
- file checkpointing;
- permission modes.

Project settings intentionally disable dangerous bypass mode.

## Codex CLI

The pack expects:
- `AGENTS.md` project instructions;
- project `.codex/config.toml`;
- `codex exec`;
- JSON/JSONL non-interactive output;
- sandbox modes;
- ChatGPT login.

The project config defaults Codex to read-only reviewer semantics.

## Principle

Version-specific features are conveniences, not kernel assumptions. GNOSIS must degrade gracefully if a particular CLI feature is unavailable.
