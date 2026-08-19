---
name: gnosis-self-correction
description: Run the bounded autonomous repair loop after a failed implementation or verification.
---

Protocol:

1. Classify failure.
2. Capture evidence/fingerprint.
3. Determine whether the failure is code, test, infra, rate-limit, context, policy or integration.
4. Form the cheapest falsifiable hypothesis.
5. Execute the cheapest decisive check.
6. Repair only after evidence supports a cause.
7. Re-run the failed gate.
8. Run nearby regression tests.
9. Stop/escalate to STALEMATE after bounded repeated/no-progress rounds.

Never retry blindly.
