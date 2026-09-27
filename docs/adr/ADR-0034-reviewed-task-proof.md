# ADR-0034 — Publication proves the reviewed task content

Date: 2026-09-27
Status: implementation and component/Windows-capture verification; full V1 qualification pending

## Problem

The canonical operator wrapper previously observed HEAD in the base repository
and wrote a minimal SUMMARY with an unconditional CLEAN boundary. Work actually
happens in an isolated linked worktree. Neither that HEAD tree nor a static CLEAN
statement proves the edited files. F-17 intentionally rejects linked worktrees
as capture roots because their Git machinery lives outside its observed boundary.

## Decision

The canonical convergence loop records a byte identity before verification, after
verification and after independent review. It covers tracked, untracked and
ignored regular files, empty directories, executable bits where meaningful, and
HEAD. A changing/unavailable subject cannot converge. This is explicitly an
endpoint comparison, not an interval guarantee. Full verification/review records
are serialized with the final subject. Review receives the complete brief,
including constraints and acceptance criteria, and a nonzero reviewer exit cannot
produce a passing verdict.

Before publication, a standalone Git clone with independent objects preserves
the reviewed HEAD/history. No checkout, source hooks/config, alternates or source
index is copied. The actual reviewed files (including dirty and ignored inputs)
are copied and compared against the recorded subject. The source is never edited
or deleted. The copy's index is HEAD's index; staging distinctions are not evidence
of file content and are not transferred. Verification runs again on this copy.

The existing F-17 run_capture supplies the locks, write observer, topology and
resolution gates, and CLEAN verdict. Its input hashes, read through the lock
handles, must exactly match the reviewed files. A passing verifier alone is not
sufficient. No F-17 acceptance rule or promotion boundary is weakened.

PROOF.json includes the brief, actual source and proof-copy paths, byte identity,
structured convergence/review/verification, report and verifier command/deadline.
Raw Worker and convergence output and the original capture artifacts are included
in the sealed bundle. Publication binds the capture's content digest and actual
reviewed HEAD; it no longer observes the unrelated base tree. A failed copy or
capture is retained and is never silently overwritten/reused. Synthetic CLEAN
bundle generation has been removed from production and exists only in test fixtures.

The engine supplies its durable attempt ID to explicitly capable runners; the
trusted runner seals that same ID. The proof checks it against the final attempt
and authorized workspace. Re-publication calls the existing idempotent identity
creation and Publisher reconciliation even for ANCHORED records, so an old ID or
status file cannot substitute for another task/launch/deployment or a missing
committed watermark.

## Scope and remaining work

The packet proves reviewed task content, not base-branch integration. Proof copies
reject links/reparse points, nested repositories/submodules, named streams and
subjects above explicit file/byte bounds, rather than silently dropping content.
The canonical verifier must be a reproducible bounded command. Legacy standalone
capture commands retain their existing optional timeout; the new proof path uses
the configured verifier deadline and records timeout as a failing check.

Windows tests exercise real Git, file locks and the write observer. An additional
canonical graph test uses a fake Worker/provider and in-process Publisher transport
while running the real engine, worktree, review adapter, capture, proof and durable
anchor code. This does not qualify a live dedicated Worker login or installed
Publisher service. ADR-0035 subsequently moves bounded rework onto the trusted
implementer with durable attempts, and recovers publication after a completed
proof checkpoint. Canonical project scheduling, integration, recovery before that
checkpoint, full regression and fresh elevated OS deployment qualification
remain required before V1 completion.
