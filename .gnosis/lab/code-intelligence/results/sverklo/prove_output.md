(node:35464) ExperimentalWarning: SQLite is an experimental feature and might change at any time
(Use `node --trace-warnings ...` to show where the warning was created)
# Sverklo repo-memory proof: fixture-repo

Generated with `sverklo prove --markdown`.

## Index

- Files: 13
- Chunks: 14
- Symbol references: 15
- Languages: `markdown`, `python`
- Trial mode: no project files, MCP configs, or agent instruction files were written
- Cache note: model/index data may still be stored under `~/.sverklo`

## Why this proof

Selected compute_b_renamed because it has a non-test definition and callers across 2 files.

## Central files

| File | PageRank |
| --- | ---: |
| `pkg/__init__.py` | 1.0000 |
| `pkg/circular_x.py` | 1.0000 |
| `pkg/circular_y.py` | 1.0000 |
| `pkg/core.py` | 1.0000 |
| `pkg/dead_code.py` | 1.0000 |

## Proof from this repo

`compute_b_renamed` is defined at `pkg/helpers.py:4`.

Sverklo found 2 references across 2 files.

Sample callers:

- `pkg/core.py:6` (function entrypoint)
- `pkg/new_module.py:5` (function new_feature)

## Prompt to paste into your coding agent

```text
Use sverklo impact on compute_b_renamed and tell me what would break if I changed its signature.
```

## Optional feedback

You can keep this receipt private.

If you choose to share feedback after an invitation, reply in the feedback channel named in that invitation.

If no feedback channel was named and you choose to share publicly, use the proof thread:

https://github.com/sverklo/sverklo/discussions/79

Use a public repo, or redact private file, symbol, caller, and repo identifiers before posting.

Use one label: `external-receipt`, `correction`, `grep-better`, or `setup-friction`.

```markdown
Outcome: external-receipt | correction | grep-better | setup-friction
Repo shape (redact if private):
Selected files/symbol (redact if private):
What matched or failed:
```
