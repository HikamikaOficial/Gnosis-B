# GNOSIS — Master Autonomous Build Directive
## Fable 5 / Claude Code

You are responsible for building GNOSIS end to end.

Read `CLAUDE.md` and every core document in `gnosis-spec/` first.

## Mission

Build a local multi-agent software-engineering system in which Claude Code, Codex and future agents are replaceable cognitive workers governed by a deterministic, durable, auditable kernel.

The system must eventually be capable of:

- specification;
- planning;
- task decomposition/DAG;
- agent routing;
- context compilation;
- implementation;
- deterministic verification;
- adversarial review;
- bounded rework;
- integration;
- proof packets;
- recovery;
- memory;
- replay;
- evaluation;
- controlled learning;
- safe progressive autonomy.

## Do not ask the user about reversible technical decisions

When ambiguous:

```text
inspect
→ research
→ compare
→ choose safe reversible option
→ ADR
→ continue
```

Do not stop after a phase just to ask whether to continue.

## First mission: environment and evidence

Before substantial implementation:

1. determine OS/runtime and project root;
2. inspect bootstrap report;
3. run environment audit;
4. inspect Git;
5. inventory external repositories;
6. inspect selected Tier S/A references;
7. write `docs/research/REFERENCE_REPOSITORY_FINDINGS.md`;
8. update Blueprint/ADRs if evidence changes assumptions.

External repositories are read-only until copied to isolated experiments.

## Priority repository mechanisms

Study first, when locally available:

### Bernstein
Kernel authority, deterministic scheduling, gates, journal, lineage, replay.

### VirtusLab Orca
Workflow-as-code: deterministic structure owns deterministic operations.

### Agent Workspace Fabric
Task→worktree→isolated execution→validation→PR/CI/review→integration lifecycle.

### Cezar
Claude/Codex multi-runner workflows, worktrees, recovery, review gate.

### Ralphex
Implementation-review-rework convergence, specialized reviewers, stalemate.

### Smithers
Durable workflows, pause/resume, rewind/fork/replay.

### Beads / Gas Town
Persistent task graph, dependency-aware work, handoffs and disposable workers.

### Microsoft Agent Governance Toolkit / AgentJail
Fail-closed policy, intervention points, least privilege.

### Grit / Symlock
Symbol ownership/claims for parallel work.

### Sverklo / CodeGraph
Code graph, blast radius and context retrieval.

### Agent Arena / Senate
Independent-first, evidence-first deliberation protocols.

### Reprise / Catacomb / OpenTraces / Agent Capsule
Replay, behavioral regression, forensics and tamper-evident evidence.

### Dagger
Portable verification pipeline.

## Technical baseline

Unless evidence proves a better option:

- Python >= 3.12
- uv
- asyncio
- SQLite V1
- Pydantic only where contracts justify it
- pytest / pytest-asyncio
- ruff
- mypy
- Git CLI
- subprocess adapters
- JSON/JSONL
- OpenTelemetry-compatible event semantics

Keep production dependencies minimal.

## Build sequence

### Phase 0 — Environment / research / ADRs
Gate: reproducible environment + architecture decisions grounded in evidence.

### Phase 1 — Deterministic kernel
Build:
- schemas/contracts
- task/project IDs
- state machine
- SQLite state/migrations
- event ledger
- task DAG
- leases/fencing
- scheduler
- failure taxonomy
- circuit breakers
- minimal CLI

Gate:
all kernel behaviors work with fake agents.

### Phase 2 — Agent adapters
Build generic `AgentAdapter`, then Claude and Codex.

Capabilities:
- health/version
- start
- resume where supported
- cancel
- structured output
- raw transcript/artifact capture
- timeout
- error classification
- rate-limit classification

Do not parse terminal output throughout the kernel. Encapsulate adapters.

### Phase 3 — Workspaces/Git
- worktree per mutating task
- base/result commit tracking
- branch/workspace lifecycle
- cleanup/recovery
- no shared writable tree

### Phase 4 — Verification / Review / Proof
- verification profiles by risk
- deterministic gates
- read-only reviewer contract
- bounded rework
- proof packet
- no `DONE` without proof

### Phase 5 — Recovery
Chaos tests:
- worker crash
- kernel restart
- rate limit
- timeout
- malformed output
- stale lease
- DB lock
- repeated failure/no diff
- merge conflict

Gate:
NO LOST WORK / NO INVALID DONE / NO STALE WRITE / NO INFINITE LOOP.

### Phase 6 — Policy / Sandbox
- capabilities
- before-tool/write/network/dependency/merge transition policies
- deny-by-default sensitive actions
- sandbox adapter
- sandbox probes
- secret protection

### Phase 7 — Context / Memory
- ContextPack
- artifact virtualization
- knowledge/episodic/procedural separation
- provenance/staleness
- code graph benchmark

### Phase 8 — Parallelism / Integration
- parallel DAG scheduling
- resource budget
- path/symbol leases
- integration queue
- post-integration verification

### Phase 9 — Replay / Eval
- FakeClaude / FakeCodex / FakeBroken / FakeRateLimited / FakeMalicious
- record/replay
- GNOSIS-Bench
- harness regressions
- shadow tests

### Phase 10 — Advanced cognition
Only after V1 is robust:
- adaptive router
- writer/reviewer matrix
- independent pair
- best-of-N
- court/parliament/red-team protocols
- hypothesis tournament
- skill lab
- attribution engine

### Phase 11 — Supply chain/release
- dependency admission
- SBOM
- vulnerability scan
- provenance/signing
- rollback/promotion profiles

### Phase 12 — Control Room
Mission / Operations / Forensics UI only after backend stability.

## Core contracts

Create versioned, typed models for:

- Project
- Task
- TaskDependency
- Lease
- TransitionRequest
- Event
- AgentInvocation
- AgentResult
- Failure
- Workspace
- VerificationRun
- Review
- Finding
- ProofPacket
- ContextPack
- PolicyDecision
- Artifact
- MemoryRecord
- SkillCandidate
- EvalRun

## State machine

Core states:

```text
NEW
SPECIFYING
SPECIFIED
PLANNING
PLANNED
READY
CLAIMED
EXECUTING
VERIFYING
REVIEWING
REWORK
PROVING
INTEGRATING
DONE
```

Exception states include:

```text
BLOCKED
RATE_LIMITED
WAITING_RETRY
WAITING_HUMAN
FAILED_CODE
FAILED_TEST
FAILED_REVIEW
FAILED_SECURITY
FAILED_ARCHITECTURE
FAILED_PERFORMANCE
FAILED_POLICY
FAILED_INFRA
TIMEOUT
AGENT_CRASH
STALEMATE
CANCELLED
```

No agent mutates status directly.

## Leases

Assignment is a fenced lease:
- lease_id
- holder
- fencing_token
- issue/expiry/heartbeat

Old workers must be denied after transfer.

Write tests.

## Events

Append-oriented event ledger should make a task reconstructable.

Include:
- event/run/task
- actor
- type
- timestamp
- input/output/context hashes
- workspace
- base/result commit
- tool
- policy verdict
- lease/fencing
- metadata

## Review

Reviewer workspace is read-only.

Structured verdict:
PASS / FAIL / UNCERTAIN.

A finding includes:
severity, category, file, symbol, description, evidence, suggested verification/action, confidence.

Verify reviewer findings rather than blindly accepting them.

## Proof

A ProofPacket is mandatory for DONE.

Map acceptance criteria to evidence.

## Context

Build minimum-sufficient reproducible ContextPacks.

Do not paste massive tool output. Store raw artifacts and give slices/pointers.

## Memory / learning

Follow `MEMORY_AND_LEARNING.md`.

Claude auto-memory and subagent memory help construction, but Gnosis runtime memory must be explicit and governed.

Learning is evidence-gated. No live self-rewrite.

## Training

Prepare, do not prematurely train.

If project history later supplies enough high-quality data, compare cheap local classifiers/rerankers/fine-tunes against deterministic heuristics and frontier-model routing.

Only train when:
- problem is repeated;
- dataset is sufficiently large/clean;
- baseline exists;
- expected savings/quality justify maintenance.

## Codex

Use official Codex CLI and existing ChatGPT authentication.

Reviewer default:
read-only.

Do not fall back to paid API automatically.

## Self-correction during this build

For every significant module:

```text
IMPLEMENT
→ TEST
→ INSPECT DIFF
→ SELF-REVIEW
→ INDEPENDENT REVIEW WHEN VALUABLE
→ VERIFY FINDINGS
→ FIX
→ RETEST
→ PROOF
```

Do not trust your own statement that something works.

## Session continuity

Before stopping:
- tests
- checkpoint
- commit when coherent
- update PROJECT_STATE
- update NEXT_ACTIONS
- record blockers
- record exact next step

If context is getting crowded, externalize state instead of continuing chaotically.

## Final rule

You are not finished when GNOSIS “looks sophisticated”.

You are finished with a milestone only when its gate has reproducible evidence.

Start now.
