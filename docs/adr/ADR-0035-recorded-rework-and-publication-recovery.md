# ADR-0035 — Recorded rework and durable publication recovery

Date: 2026-09-27
Status: implemented; component regression verified; full regression and V1 qualification pending

## Decision

Corrections use the implementation runner, never the independent review runner.
The canonical composition supplies the same trusted execution seam used for the
initial implementation. Policy, credential holds and budget apply to each launch.
The budget is persisted before launching a correction or review.

`RecordedAgentRunner` records corrections in the existing RunStore. Each gets a
distinct run ID, raw output paths, result, state, heartbeat and append audit. The
parent brief receives its run reference before launch. Infrastructure exceptions
keep their type; a quota response keeps both raw output and RATE_LIMITED state.
The wrapper does not grant authority or declare task completion. The proof binds
the final successful correction to its actual trusted launch and also retains
the initial implementation and correction outputs.

Queue transitions now share the queue lock with enqueue, claim, recovery and
operator requeue. The claim must be current before its running record is touched,
and that record carries holder/epoch. Recovery honours a terminal intent only if
the same claim committed the corresponding resolve/release. Expiry after intent
but before the claims-plane commit returns work to pending, never DONE. Moves
persist their details then rename once, so interruption does not create records
in two queue buckets. No claim, lease or completion-policy rule was relaxed.

After a successful real proof capture, the Director persists a publication
checkpoint under `trust_state_root/director-publication`. It contains the observed
launch, spec, identity inputs, exact brief and an external digest of the sealed
proof bundle. This location relies on the existing qualified protected-root ACL
contract: the Worker cannot write it. It is not a Worker-provided receipt.

On restart, the composition checks the exact brief, deployment, repository,
epoch, verifier, proof digest and current worktree subject against that checkpoint.
It then re-enters `publish_governed_run` with the same observed launch and identity,
using existing F-17 identity creation, authorization and Publisher reconciliation.
Even an ANCHORED record is reconciled. There is no direct status-to-success shortcut,
new Publisher verb, in-process production Publisher or replacement trust policy.
An operation lock prevents concurrent execution of the same brief by this entry.

## Evidence and limits

The composed test reconstructs a fresh production object from disk after a
Publisher refusal or a lost reply following an actual anchor. It verifies that
neither implementation nor review runs again, IDs remain unchanged, the Publisher
is contacted again, and an altered bundle with a recomputed manifest is refused
against the saved digest. Worker and service transport are explicit doubles;
worktree operations, proof capture on Windows, sealing and anchoring are real.

This checkpoint covers recovery **after the completed proof checkpoint was
persisted**. It does not yet recover a crash during implementation, convergence,
proof copying/capture, or the interval before checkpoint persistence. Stable
task/worktree resumption and project scheduling/integration remain required.
Publication still proves reviewed task content, not base-branch integration.
No live dedicated-Worker login or installed-service qualification is claimed.
