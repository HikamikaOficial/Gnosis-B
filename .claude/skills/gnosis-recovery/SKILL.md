---
name: gnosis-recovery
description: Recover a GNOSIS task/run after crash, timeout, rate limit or interrupted session.
---

Do not start by re-running everything.

1. Read durable task state/events.
2. Validate current lease/fencing.
3. Validate workspace and Git commit.
4. Determine last completed gate.
5. Classify interruption.
6. Reuse valid artifacts.
7. Resume from the smallest safe boundary.
8. Never let a stale worker write after transfer.
9. Record recovery event and evidence.
