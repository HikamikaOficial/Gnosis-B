# ADR-0037 — serialize checkpoint commits with ownership replacement

Status: implemented for protected pipeline checkpoints; remaining mutation
boundaries still require audit. This is not V1 acceptance.

## Problem

A before-write ownership check releases its locks before persistence. A new owner
can replace the grant between that check and the actual write. Atomic file rename
does not establish ownership: it only prevents a torn individual file.

## Decision

WorkAuthority.commit uses the existing claims -> leases lock order. It validates
the active holder/epoch and live lease while retaining both locks over a bounded
persistence callback. ExecutionScope.borrowed supplies this operation to consumers.
Callbacks must not reenter the authority or either store, acquire earlier locks,
or run agents. Cancellation is checked inside the protected commit boundary.

PipelineCheckpointStore prepares encoding outside the ownership critical section.
Its existing checkpoint lock then protects CAS while the authority commit protects
both the immutable generation and selector writes. If ownership changed during
encoding, neither is written. If expiry crosses during an admitted commit, that
commit finishes before any replacement can acquire the next epoch. Expiry is an
entry condition; it does not roll back an already linearized write.

ClaimStore.assert_active now performs its check under the same claim lock. The
underlying policy, epoch rules, lease TTL and reclaim grace are unchanged.

## Evidence and limits

tests/test_checkpoint_commit_fencing.py covers replacement during encoding,
concurrent expiry/sweep/acquisition between generation and selector, rejection of
old-owner updates after takeover, cancellation and expiry at entry, and lock
release after refusal. Claim/lease/supervisor/queue regression passed 57 cases.

The supervisor retains its heartbeat and outer ownership. This change does not
yet fence publication RPCs, Git branch advancement, or every artifact write.
Before/after guards at those boundaries must not be mistaken for an atomic fence.
Manual ExecutionScope instances without a commit callback retain check-only
semantics; production scopes are constructed with borrowed().

## Extension: publication receipt and Git advancement

PublicationCheckpointStore now accepts the borrowed scope and serializes its
immutable receipt write against ownership replacement after bundle verification.
WorkIntegrator serializes its final fast-forward command through the same commit
primitive after the existing review, verification and policy gates. Agent review
and verification remain outside these locks. Git retains its existing subprocess
timeout; a slow Git operation can still cause an authority-lock wait to time out,
which must be treated as infrastructure failure, not a successful task.

The added integration race test changes the actual authority epoch after the final
guard and proves the source branch stays unchanged. The publication race test
changes authority after bundle verification and proves no receipt is persisted.
Publication service RPC fencing is still unqualified; the extension does not
claim to cancel a remote request already accepted by the Publisher.
