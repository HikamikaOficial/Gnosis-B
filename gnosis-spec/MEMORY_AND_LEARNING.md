# GNOSIS — Memory, Learning and Training Architecture

## 1. Claude Code memory during construction

### Main agent
Use Claude Code auto-memory for build commands, stable project patterns and recurring debugging knowledge.

### Subagents
Project subagents use `memory: project` where useful.

Their memory is specialized:
- architecture
- kernel
- security
- evidence
- reliability
- memory governance
- research

## 2. Durable project memory

The project also maintains explicit versioned files:

```text
docs/PROJECT_STATE.md
docs/NEXT_ACTIONS.md
docs/DECISIONS.md
docs/LEARNINGS.md
docs/ASSUMPTIONS.md
```

These survive machine/session changes when transferred with the repo.

## 3. Gnosis runtime memory model

Gnosis itself must implement five logically separate stores:

### Project Truth
- source
- Git
- SPEC
- ADR
- tests
- schemas

This is authority.

### Operational State
- tasks
- dependencies
- leases/fencing
- queues
- attempts
- workers
- workspaces
- gates

### Knowledge Memory
- verified discoveries
- incidents
- component knowledge
- external evidence

Must include provenance/staleness.

### Episodic Memory
- runs
- attempts
- trajectories
- outcomes
- reviews

### Procedural Memory
- skills
- workflows
- debugging recipes
- successful procedures

## 4. Memory governance

Memory != Truth.

Every memory should carry where applicable:
- source
- timestamp
- commit
- file
- symbol
- confidence
- verification state
- staleness state.

A code memory anchored to an old commit must be revalidated after relevant code changes.

## 5. Learning loop

GNOSIS learns conservatively:

```text
RUN
↓
OBSERVATION
↓
CANDIDATE LESSON
↓
ENCODE AS SKILL / POLICY / ROUTER RULE / CONTEXT RULE / TEST
↓
OFFLINE EVAL
↓
HELD-OUT / REGRESSION
↓
SHADOW MODE
↓
PROMOTE OR REJECT
```

No direct live self-promotion.

## 6. Training

Do not claim Claude/Fable or Codex weights are being trained by this project.

Future training is for models/components we control.

Prepared areas:

```text
lab/training/datasets/
lab/training/experiments/
lab/training/models/
```

Future options if cost/benefit justifies them:
- train/fine-tune a local routing classifier;
- train task/risk classifiers;
- train retrieval/reranking models;
- distill successful trajectories into smaller local models;
- fine-tune open-weight coding/reviewer models;
- learn failure attribution classifiers.

Every trained candidate must have:
- dataset provenance;
- train/validation/test separation;
- leakage checks;
- immutable held-out set;
- baseline;
- regression suite;
- version/hash;
- rollback.

## 7. Protected evaluators

A system being trained/improved must never modify its own:
- held-out tests;
- gold labels;
- evaluator;
- promotion rules;
- baseline results;
- security policies

during the evaluation that decides promotion.
