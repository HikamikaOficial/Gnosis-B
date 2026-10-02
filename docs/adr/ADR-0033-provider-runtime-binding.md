# ADR-0033 — Native provider belongs to the measured runtime

Date: 2026-09-27
Status: implemented at component level; fresh OS qualification pending

## Context

V1 requires real provider execution through the dedicated Worker boundary.
The historical deterministic composition has no provider call. A native binary
under the operator's profile would neither be part of the Publisher's deployment
identity nor inherit the deployment's Worker-read-only runtime permissions.

## Decision

The optional native Codex bundle is copied by the existing Provisioner to
`runtime/providers/codex/` before ACL application and deployment observation.
The fixed executable is `providers/codex/codex.exe`. The complete bundle, including
support executables and libraries, is part of the existing V2 runtime tree. No
new identity format, authority store, trust rule or anchor meaning is introduced.

The operator configuration selects only the closed mode/provider pair. It cannot
provide an arbitrary provider executable or expected hash. Composition derives
the executable and hash from the observed runtime manifest, verifies the complete
runtime again, and cross-binds that tree to publication. Provider construction
also requires the observed deployment digest to equal the expectation from the
Publisher's protected service configuration.

Login status and task execution both traverse WorkerLauncher. The Director's
login is not the Worker's login. Only existing ChatGPT login is accepted; neither
credentials nor a subscription token are copied. Authentication failure requires
operator action and is not reported as a code-repair attempt.

The trusted port chooses sandboxed argv, bounds the prompt and deadline, closes
the Worker job on cancellation/failure, and normalizes bounded JSONL output.
Heartbeat callbacks use launcher-observed process IDs. The provider's narrative
is not completion authority: verification, read-only review and publication
remain mandatory and separate.

## Verification and remaining obligations

Tests exercise real filesystem runtime measurement with inert fixture bytes,
configuration reader/factory wiring with an explicit fake launcher, refusal of
executable/sidecar drift, missing native bundle, identity mismatches, and existing
composition/provisioning regression. These are not OS-real provider qualification.

Fresh provisioning must preserve the existing runtime ACL guarantees. The expected
Publisher digest must be the effective deployed tree after application assembly;
an old base digest is refused. Real dedicated-Worker login, sandboxed engineering
execution, proof packets, task integration and restart/crash qualification remain
required before V1 can be declared complete. ADR-0034 now replaces the minimal
publication bundle with proof of the actual reviewed subject and observed capture
on an independent Git copy. Full provider/deployment qualification remains pending.
