# GNOSIS — Repository Analysis Protocol

Use the same schema for every serious external candidate.

## Identity

- canonical repository
- local path
- commit SHA
- branch/tag
- license
- primary languages
- size
- build system
- runtime requirements

## Evidence labels

Every claim:

- VERIFIED
- SELF-REPORTED
- INFERRED
- NOT TESTED
- BLOCKED

## Static safety audit before execution

Check:
- install scripts/postinstall;
- shell/subprocess/eval;
- downloads/remote code;
- telemetry;
- secrets;
- network listeners;
- destructive filesystem/Git;
- privileged Docker;
- unsafe model loading/deserialization;
- MCP exposure.

Risk:
LOW / MEDIUM / HIGH / CRITICAL.

## Architecture extraction

Identify concrete mechanisms:

- scheduler
- state model
- event model
- task graph
- recovery
- retry/failure taxonomy
- worktree lifecycle
- leases/locks
- review
- verification
- proof/evidence
- policy
- sandbox
- context
- memory
- replay
- observability
- routing
- skills
- UI/control plane

For each:
- file/module/symbol
- how it works
- invariant
- failure modes
- complexity
- dependencies

## GNOSIS decision

One of:

- REIMPLEMENT_PATTERN
- ADAPT_IDEA
- DEPENDENCY_CANDIDATE
- BENCHMARK_AGAINST
- REJECT
- DEFER

Record the decision in a comparison or ADR when it influences architecture.

## Score dimensions

0–10:
- determinism
- durability
- security
- recovery
- auditability
- modularity
- testability
- Windows/WSL suitability
- operational complexity
- unique value
- evidence quality
- fit for Gnosis

Do not rank by stars/README quality.
