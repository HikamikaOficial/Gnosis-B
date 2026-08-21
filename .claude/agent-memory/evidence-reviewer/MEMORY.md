# evidence-reviewer — Project Memory

## Status
Seeded by the GNOSIS environment pack.

## Rules
- Store only durable, reusable learnings.
- Attach provenance where possible.
- Mark uncertain items explicitly.
- Mark code knowledge stale when the referenced implementation changes.
- Do not treat memory as authority over source/spec/tests.

## Learnings
- [ADR evidence lines are unverified](learning_adr_evidence_lines_unverified.md) — ADR-0013 and ADR-0014 both claim "suite 488/488"; no captured command output exists anywhere.
- [Replay fingerprint is self-referential](learning_replay_fingerprint_self_reference.md) — cassette key depends on a workspace the recorded agent mutates but replay never reproduces.
