---
name: gnosis-codex-review
description: Obtain an independent Codex review without allowing the reviewer to edit the candidate.
---

Use Codex CLI only if available and authenticated.

Default:
- sandbox = read-only
- non-interactive
- machine-readable output

Ask Codex for:
verdict, findings, severity, file/symbol, evidence, confidence, cheapest verification.

Then independently verify findings. Record true/false positives.
