---
name: adr-evidence-lines-unverified
description: GNOSIS ADR "Evidence:" header lines are self-reported prose with no captured command output; suite totals have been observed copy-pasted between ADRs
metadata:
  type: project
---

Every `docs/adr/ADR-*.md` carries an `- Evidence: ... suite N/N; mypy strict clean; ruff clean` header line. These are SELF-REPORTED. There is no `.gnosis/evidence/` directory and no captured stdout/exit-code artifact anywhere in the repo backing any of them (verified 2026-08-20 by glob + grep).

Observed defect: ADR-0013 and ADR-0014 (both dated 2026-08-20) each claim `suite 488/488`, yet ADR-0014 states it adds 14 new tests in a new file `tests/test_replay_runner.py`. Every other ADR increments the total monotonically (183 → 194 → 239 → 282 → 376 → 440 → 488). So at least one of the two 488 figures is stale/copied.

**Why:** the project constitution (CLAUDE.md rule 2, "Ninguna Task llega a DONE sin evidencia") treats these ADRs as the evidence of milestone completion. A copied suite total means the DONE gate was passed on an unverified number.

**How to apply:** when auditing any GNOSIS ADR, do not accept the `Evidence:` line. Cross-check the claimed per-file test count against the actual test methods in the named file, and cross-check the suite total against the previous ADR's total plus the delta. Report a mismatch as a score/evidence defect, not a typo.

Related: [[adr-invariants-asserted-not-proven]]
