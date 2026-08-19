# GNOSIS SYSTEM BLUEPRINT — Constitution v0.2

## Mission

GNOSIS is a local multi-agent autonomous engineering platform that transforms high-level specifications into verified software through bounded AI workers governed by a deterministic, durable, auditable kernel.

## North Star

A human should increasingly act as:

```text
OWNER
PRODUCT AUTHORITY
ARCHITECTURAL AUTHORITY
EXCEPTION HANDLER
```

not as a prompt operator.

## Trust hierarchy

```text
EXECUTABLE REALITY
tests / compiler / runtime / benchmark
        >
PROJECT ARTIFACTS
source / Git / SPEC / ADR / schemas
        >
VERIFIED EXTERNAL EVIDENCE
        >
MEMORY
        >
MULTI-AGENT AGREEMENT
        >
SINGLE-AGENT CONFIDENCE
```

## System principles

- The model proposes; the kernel decides.
- The intelligence can be ephemeral; the work cannot.
- Evidence before consensus.
- Independent before interaction.
- A judge does not modify what it judges.
- No task is done without proof.
- No failure should destroy work.
- No system improvement reaches production without beating baseline.
- Minimum agents, maximum evidence.
- Small deterministic core + replaceable modules.

## Priority order

1. correctness / quality
2. security
3. recoverability
4. autonomy
5. resource/quota efficiency
6. speed

## V1

```text
SPEC
↓
TASK DAG
↓
DURABLE KERNEL
↓
CLAUDE WORKER
↓
DETERMINISTIC VERIFICATION
↓
CODEX REVIEW
↓
REWORK IF TRUE FINDINGS
↓
REVERIFY
↓
PROOF PACKET
↓
CANDIDATE INTEGRATION / COMMIT
```

V1 includes:
- SQLite durable state;
- typed/versioned contracts;
- task DAG;
- event ledger;
- state machine;
- leases/fencing;
- Claude adapter;
- Codex adapter;
- worktrees;
- failure taxonomy;
- circuit breakers;
- verification profiles;
- read-only review;
- proof packet;
- basic policies;
- recovery;
- fake agents;
- CLI.

## Deferred until evidence justifies them

- massive swarms;
- distributed cluster;
- Kubernetes;
- unrestricted self-modification;
- autonomous production deployment;
- giant vector-memory dependency;
- always-on councils;
- fully automatic semantic merge;
- complex GUI before backend stability.
