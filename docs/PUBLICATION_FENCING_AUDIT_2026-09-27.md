# Publication concurrency audit — 2026-09-27

Verdict: **component regressions pass; deployment qualification pending**.
The original finding below was recorded by a read-only audit while the
integrated regression runs. This file neither changes trust policy nor approves
a weaker completion contract.

## Implementation and verification update

The seam now receives ExecutionScope on both production composition paths.
Local run creation/authorization uses its atomic commit; RPC remains outside
authority locks, with ownership checks before sending and after receiving.
The observed launch epoch is preserved on recovery.

tests/test_publication_checkpoint_fencing.py proves refusal before authorization,
serialization of admitted authorization against an expiry/sweep/new epoch, and
refusal of old-caller success after a delayed response with exact-run recovery.
Four tests passed. The combined project scenario in test_project_execution.py
now publishes the parent, replaces ownership before delivering the reply, proves
the old caller did not advance the branch/complete the queue/release the child,
then resumes after the persisted recovery delay. It proves exactly two Worker
launches for two tasks, the child observes the landed parent, and a valid anchor
chain contains exactly one record for the interrupted parent's run. This scenario
passed in 28.29s, using real Git, Windows proof capture and trust stores but a
component Worker/reviewer and in-process Publisher. It does not qualify a live
Windows service or real provider identity. Full final regression is pending.

The historical finding and test requirements below are preserved for traceability.

## Confirmed boundaries

1. `director.publication.publish_governed_run` creates an immutable trusted run,
   conditionally authorizes PUBLISHABLE, sends the run ID, and reads authoritative
   state. Those first two local operations currently have no borrowed scope.
2. `trust.run_identity.TrustedRunIdentityStore.transition` locks the record and
   compares its immutable identity digest. It refuses identity substitution and
   backward publication transitions, independently of queue ownership.
3. `trust.publisher.Publisher._handle` derives the owner, deployment, epoch, head,
   tree and launch intent from protected state. The wire supplies only run ID.
4. `trust.publication.durable_publish` locks the anchor ledger, reconciles first,
   validates authorization and commits the anchor/watermark. A lost response is
   reconciled using the same run; it is not permission to mint a new identity.
5. The pipe ACL permits SYSTEM/administrative maintenance and the configured
   Worker rights. The enabled local Worker account alone does not qualify this
   boundary; a real deployment and observed identities are still needed.

## Actionable finding

- Severity: high, correctness/ownership.
- File/symbol: src/gnosis/director/publication.py, publish_governed_run.
- Finding: a stale Director can pass a prior outer check and reach local trusted
  run creation / PUBLISHABLE authorization after ownership replacement.
- Evidence: ProductionComposition checks its scope before the call, but the
  called function contains no scope/commit guard around create_trusted_run and
  authorize_publishable. The queue and receipt fences do not cover these writes.
- Confidence: high for this unprotected interval; impact on end-to-end completion
  remains bounded by later guards and must be tested rather than assumed safe.
- Proposed verification/fix: pass the borrowed scope to the local authorization
  boundary and serialize that bounded commit against ownership replacement.
  Keep service communication outside the authority locks; changing the immutable
  launch epoch to a new controller epoch would misattribute evidence.

## Separate question that must not be hidden

Publication records immutable historical evidence; queue completion and shared
branch advancement are separate states. A request accepted for an already
authorized immutable run may finish after its requesting controller dies. Killing
the pipe helper does not revoke that authorization or cancel server execution.

Whether such an anchor satisfies the original historical-evidence contract is
different from permitting a deposed controller to authorize NEW publication,
advance Git, resolve a task, or release a dependent task. Preserve those separate
authorities. Do not claim whole-system NO STALE WRITE solely because an anchor is
immutable; prove that no stale controller can make the authoritative task writes.

## Required tests before closing this audit

- Ownership replaced before local publication authorization: no new authorization
  and no service request from that path.
- Ownership contention during admitted authorization: either the exact run is
  fully authorized before takeover, or a later controller must reconcile it;
  never substitute a different task, tree, deployment or launch epoch.
- Response lost/delayed after service acceptance and ownership changes: old caller
  cannot record task success, advance Git or resolve/release dependencies.
- Replacement controller resumes the exact protected proof/run, reconciles one
  anchor and completes only with its own current grant and verified integration.
- All RPC waits are bounded and classified as infrastructure/unknown outcome,
  with proof and work retained. No fabricated success or duplicate launch.

The existing timeout and recovery tests provide parts of this evidence. They do
not yet cover this combined scenario, so the acceptance audit stays open.
