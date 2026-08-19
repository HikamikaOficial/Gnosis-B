# GNOSIS V1 — Definition of Done

V1 is not done because it launches Claude.

It is done only when automated tests prove that it can repeatedly:

- create a durable project/task;
- represent task dependencies;
- detect ready tasks;
- claim task with lease/fencing token;
- reject stale writes;
- create isolated worktree;
- invoke FakeClaude/FakeCodex in CI;
- invoke real Claude/Codex adapters when available;
- capture structured/raw outputs;
- classify rate limits separately from code failures;
- handle malformed agent output with bounded repair;
- timeout/cancel hung subprocess;
- execute deterministic verification;
- execute read-only review;
- run bounded rework;
- create a proof packet;
- refuse `DONE` when required evidence is absent;
- survive kernel restart with task/work preserved;
- recover after worker crash;
- avoid infinite loops;
- keep append-oriented audit events;
- preserve Git integrity.

## Survival suite

Must include deliberate:

- worker kill;
- kernel restart;
- stale lease;
- repeated identical failure;
- no-diff loop;
- malformed JSON;
- timeout;
- rate limit simulation;
- reviewer disagreement;
- merge conflict;
- invalid state transition.

Expected invariant:

```text
NO LOST WORK
NO INVALID DONE
NO STALE WRITE
NO INFINITE LOOP
```
