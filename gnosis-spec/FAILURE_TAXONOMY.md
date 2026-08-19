# GNOSIS Failure Taxonomy

```text
PASS

FAIL_CODE
FAIL_TEST
FAIL_REVIEW
FAIL_SECURITY
FAIL_ARCHITECTURE
FAIL_PERFORMANCE
FAIL_POLICY

FAIL_INFRA
RATE_LIMITED
TIMEOUT
AGENT_CRASH
INVALID_AGENT_OUTPUT
STALEMATE
STALE_LEASE
MERGE_CONFLICT
CONTEXT_ERROR
DEPENDENCY_ERROR

NEEDS_HUMAN
```

## Routing principle

Failure type determines response.

Examples:

- RATE_LIMITED → park/retry after backoff or eligible fallback.
- FAIL_CODE → return evidence to worker for bounded rework.
- FAIL_INFRA → repair infrastructure; do not blame code.
- INVALID_AGENT_OUTPUT → bounded schema repair.
- STALE_LEASE → deny write and reload durable task state.
- STALEMATE → change strategy/protocol/agent or stop; never infinite retry.
- NEEDS_HUMAN → only when decision/effect cannot safely be automated.
