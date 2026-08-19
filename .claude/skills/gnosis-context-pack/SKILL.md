---
name: gnosis-context-pack
description: Build a minimum-sufficient reproducible context pack for an agent task.
---

Include only justified:
- task/spec;
- acceptance criteria;
- ADRs;
- affected files/symbols;
- callers/callees/dependencies;
- tests;
- relevant prior failures;
- policies/capabilities;
- relevant non-stale memory;
- budget.

Hash/version the pack. Raw huge outputs should become artifacts with relevant slices, not be pasted wholesale.
