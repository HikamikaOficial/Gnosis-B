# GNOSIS — Target Architecture

The following are **conceptual planes**, not necessarily separate services.

1. Product / Mission Plane
2. Specification Plane
3. Cognitive / Deliberation Plane
4. Context Plane
5. Agent Routing Plane
6. Deterministic Kernel
7. Policy / Trust Plane
8. Durable State Plane
9. Execution / Sandbox Plane
10. Git / Parallelism Plane
11. Verification Plane
12. Adversarial Review Plane
13. Merge / Integration Plane
14. Supply Chain Plane
15. Delivery / Release Plane
16. Memory Plane
17. Observability / Forensics Plane
18. Evaluation / Learning Lab
19. Resilience / Chaos Plane
20. Control Room

## Dependency direction

The Kernel must not depend on UI.

Adapters depend on contracts, not vice versa.

Reviewers cannot own mutable candidate workspace.

Policy evaluation precedes sensitive side effects.

Memory cannot mutate project truth.

Evaluation/promotion criteria cannot be rewritten by the candidate being evaluated.

## V1 component graph

```text
CLI
 │
 ▼
APPLICATION SERVICE
 │
 ├──────── POLICY
 │
 ▼
KERNEL / STATE MACHINE
 │
 ├── TASK STORE / DAG
 ├── EVENT LEDGER
 ├── LEASE MANAGER
 ├── SCHEDULER
 ├── FAILURE CLASSIFIER
 │
 ├───────────────┐
 ▼               ▼
WORKSPACE       AGENT ADAPTERS
MANAGER         ├─ Claude
 │              └─ Codex
 ▼
VERIFICATION
 │
 ▼
REVIEW
 │
 ▼
PROOF
 │
 ▼
INTEGRATION CANDIDATE
```
