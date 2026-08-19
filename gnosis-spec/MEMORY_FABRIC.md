# GNOSIS Memory Fabric — M3 + ZMem + Structural Memory

## Goal

GNOSIS must have excellent long-term memory **without allowing remembered text to become truth or authority by accident**.

The v0.3 architecture combines complementary systems instead of choosing a single memory database.

```text
                        GNOSIS MEMORY FABRIC
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
             ▼                  ▼                  ▼
        M3 Memory              ZMem             Graphify
        HIGH RECALL        GOVERNED MEMORY      STRUCTURAL
        cross-agent       trust / authority     code graph
        hybrid search      quarantine           relationships
        sessions/files     lineage/receipts      blast radius
             │                  │                  │
             └──────────────┬───┴──────────────────┘
                            ▼
                 TRUTH / FRESHNESS VALIDATOR
                 Git + SPEC + ADR + tests
                            ▼
                     CONTEXT COMPILER
                            ▼
                     Claude / Codex
```

## Backend responsibilities

### M3 — broad recall / retrieval

Primary role:
- cross-session recall;
- cross-agent shared memory;
- hybrid semantic/lexical retrieval;
- session/chat history;
- file/entity/task memory where useful.

M3 is a **candidate-recall engine**, not final authority.

A memory returned only by M3 is not automatically allowed to influence a high-risk action.

Canonical repo:
https://github.com/skynetcmd/m3-memory

### ZMem — governed memory / trust plane

Primary role:
- approved vs quarantined memory;
- trust and authority;
- lineage;
- revocation;
- policy gating;
- proof/receipts;
- explain why a memory influenced an action.

For high-risk actions, memory should normally need:
1. valid provenance;
2. freshness;
3. sufficient authority/trust;
4. policy admission.

Canonical repo:
https://github.com/zerkerlabs/zmem

### Graphify — optional structural memory

Graphify is not a replacement for M3/ZMem.

Its possible role:
- code symbols;
- relationships;
- communities;
- repository graph;
- current structural context.

Canonical repo:
https://github.com/Graphify-Labs/graphify

It MUST pass GNOSIS-Bench against alternatives such as Sverklo/CodeGraph before becoming a production dependency.

### Obsidian — optional human knowledge mirror

Obsidian is **not** the runtime source of truth.

A Markdown vault can mirror:
- ADRs;
- architecture;
- decisions;
- research;
- lessons;
- project timeline.

Candidate integration:
https://github.com/breferrari/obsidian-mind

GNOSIS must still function if Obsidian is not installed or running.

## Claude native auto-memory

Claude Code auto-memory remains enabled as a convenience layer for the build agent.

Authority:
LOW.

It can remember:
- build commands;
- debugging patterns;
- workflow preferences.

It cannot overrule:
- source;
- Git;
- SPEC;
- ADR;
- tests;
- Gnosis durable state;
- ZMem policy.

## GNOSIS durable memory

GNOSIS itself keeps five logical memory types:

1. PROJECT TRUTH
2. OPERATIONAL STATE
3. KNOWLEDGE MEMORY
4. EPISODIC MEMORY
5. PROCEDURAL MEMORY

External memory systems are **adapters behind these contracts**, never architectural owners.

## Retrieval pipeline

For each task:

```text
Task
↓
M3 broad candidate retrieval
+
ZMem governed recall
+
optional structural graph retrieval
↓
deduplicate
↓
provenance check
↓
freshness check against Git/spec
↓
risk-aware trust/authority policy
↓
rank
↓
ContextPack
```

## Write pipeline

Avoid blind dual-write.

### Raw run/event data
Store in GNOSIS Event/Episodic Store.

### Searchable summaries / broad recall
May be indexed in M3.

### High-value durable memory
Propose to ZMem quarantine/governed workflow.

### Code structure
Rebuild/revalidate from source using structural index, never treat old graph data as truth.

## Conflict resolution

If memories disagree:

```text
PROJECT TRUTH / EXECUTION EVIDENCE
>
fresh governed ZMem record
>
fresh M3 observation with provenance
>
Claude auto-memory
>
unverified remembered text
```

Do not silently pick the most semantically similar result.

Record conflict and cheapest verification.

## Memory benchmark

Before production promotion measure:
- recall precision/recall;
- stale-memory rate;
- duplicate rate;
- contradiction rate;
- context tokens;
- retrieval latency;
- memory write overhead;
- cross-agent continuity;
- task success impact.

Compare:
- M3 alone;
- ZMem alone;
- M3 + ZMem;
- M3 + ZMem + structural graph.

Only keep a layer if its measurable benefit exceeds complexity/cost.
