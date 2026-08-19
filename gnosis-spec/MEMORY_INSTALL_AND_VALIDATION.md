# GNOSIS — Memory Installation & Validation

## Official project root

```text
C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi
```

## Repository root

```text
C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi\external\repositories
```

## Required primary memory engines

### M3 Memory
GitHub:
https://github.com/skynetcmd/m3-memory

Expected local clone:
```text
C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi\external\repositories\m3-memory
```

### ZMem
GitHub:
https://github.com/zerkerlabs/zmem

Expected local clone:
```text
C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi\external\repositories\zmem
```

The user reports these repositories have already been reviewed by Claude and considered safe.
Claude should still verify the exact local `origin`, commit/version and current install instructions before executing installers.

## Installation mission

Before substantial GNOSIS implementation:

1. inventory local repositories;
2. find M3/ZMem by Git origin, not folder guess;
3. inspect current README/install docs;
4. install each in a dedicated, reversible tool environment where practical;
5. connect both to Claude Code;
6. connect both to Codex if supported;
7. run their own doctor/smoke tests;
8. build `docs/research/MEMORY_FABRIC_STATUS.md`;
9. perform a cross-session continuity smoke test;
10. implement a thin GNOSIS Memory Fabric adapter boundary before letting project code depend on either engine.

## Required smoke test

Store/propose a harmless synthetic project fact.

Restart/reopen a fresh agent session.

Verify:
- M3 can retrieve it;
- ZMem can explain trust/admission/provenance for a governed memory;
- GNOSIS can distinguish candidate recall from trusted memory;
- stale/contradictory synthetic memory is not silently injected as truth.

Delete/revoke synthetic test data after proof if the backend supports it.

## Optional Graphify

GitHub:
https://github.com/Graphify-Labs/graphify

Do not install automatically merely because it exists.

Benchmark against the selected code-intelligence alternatives first.

## Optional Obsidian mirror

Candidate:
https://github.com/breferrari/obsidian-mind

Do not make runtime correctness depend on Obsidian.

Use plain Markdown as the interchange format.
