# ADR-0030 — Provisioning realizes the boundaries

**Status:** accepted (F-17 Stage 8, 2026-08-31)
**Extends** ADR-0028 (the composed trust path) and ADR-0029 (unknown `.git` fails
closed). **Does not reopen** F-14.

## Context

Stages 1–7 qualified the trust plane's *design*: a dedicated worker, a restricted
service SID, a durable anchor ledger, a measured deployment identity, and a
fail-closed `.git` classifier. Every one of those guarantees assumes an OS state
that provisioning is responsible for creating — an account that exists, ACLs that
deny, a runtime that imports only what was deployed, a service whose ImagePath and
SID type are what the identity measured. Until Stage 8 that OS state was produced
by hand in the probes, so the guarantees were real but the *installer* was not: a
maintainer had no reproducible, fail-closed way to reach the qualified state, and
nothing checked that the state a real install produced matched the state the trust
plane was qualified under.

## Decision

### The layout and the ACL matrix are data, checked before any OS state exists

`gnosis.provision.layout` is pure: it answers *where every authority-bearing thing
lives* (`DeploymentLayout`) and *who may do what to each* (the `_ROOTS` ACL
matrix), with no filesystem, `icacls`, or Git. The matrix's invariants —
the worker never holds write on a trusted root, the credential blob / authoritative
bundles / anchors / run identities / publisher code grant the worker **no ACE**,
every protected root strips inheritance, and the worker-writable set is exactly
`{work}` — are pure predicates a unit test asserts. A mutant that weakens the
matrix is caught with no OS involved.

### Absence of an ACE, on an inheritance-stripped root, is the deny

`C:\Program Files` and `C:\ProgramData` grant `BUILTIN\Users` read/execute (and,
on ProgramData, create) by inheritance, and the worker is a `Users` member. Every
protected root therefore strips inheritance first (`icacls /inheritance:r`) and
then grants exactly the matrix principals by **SID**, never by name. There is no
explicit `DENY` ACE for the worker: on a root with inheritance removed, a
principal with no ACE has no access, and that is stated by omission, not defaulted.

### Grants are replacing, so the installer is idempotent

`icacls /grant:r` replaces a principal's ACE rather than adding one, `copytree` is
`dirs_exist_ok`, the worker account is reused when it already exists, and the
service is reconfigured rather than re-created. Re-running the installer converges
to the same state; it cannot broaden an ACL or create a second account or service.

### Well-known principals are SIDs, not localized names

The maintenance principal is the Administrators **group**, whose SID
(`S-1-5-32-544`) is identical on every install and every locale. Resolving it by
the name `BUILTIN\Administrators` returns `ERROR_NONE_MAPPED` on a non-English
Windows — found OS-real on this Spanish-locale machine. The provisioner uses the
constant SID directly; every ACL grant is by SID for the same reason.

### Code is versioned; state is stable; update flips, never overwrites

Code lives under `releases\<id>` in Program Files; state (anchors, run identities,
authoritative bundles, the credential blob, config) is stable in ProgramData. An
update *stages a new release beside the running one*, verifies it independently of
the service, and only then flips the service's ImagePath (`sc config`) and rebinds
`config.json`; rollback flips back to a still-present prior release. The deployment
digest is observed **after** the ImagePath flip, so the digest written to
`config.json` is exactly what the service will require. A failed update — a staged
release that does not verify — never flips the service, so the last good release
stays active. Nothing is overwritten in place before its replacement is verified.

### The candidate / authoritative split is realized in the ACLs (Stage 7 R5)

The worker writes its candidate output under `Work\<run_id>`, which it may modify.
The authoritative evidence the Stage-7 boundary gate reads lives under the state
base's `bundles` root, where the worker has no ACE. The property "a worker cannot
write the SUMMARY whose verdict authorizes publication" is now an ACL fact, proved
OS-real by the adversarial matrix, not only a code invariant.

### Provisioning is testable without the OS, and qualified with it

Every side effect is behind an `Operations` protocol. A recording fake asserts the
transaction *order* (ACLs before observation; the worker denied on every trusted
root; the service made restricted; the blob written) with no account, service, or
ACL created. `RealOperations` performs them, and `scripts/probe_stage8_provisioning.py`
qualifies the whole thing OS-real against disposable, production-equivalent roots
(same `C:\Program Files` / `C:\ProgramData` ancestors, disposable leaf names),
then rolls everything back. No permanent install is left behind.

## Consequences

- A trusted maintainer has one reproducible, fail-closed path to the qualified
  state, and one command to observe whether the resulting OS state matches it.
- The Stage 6 debt "the service must be able to read its own code" is discharged
  by the matrix (the service SID is granted RX on the runtime and publisher).
- Toolchain relocation (worker-readable, not the Director's profile) is modelled
  as a first-class root; the compat cost noted in Stage 5 is now priced into the
  layout.
- The trusted computing base is unchanged in kind; provisioning adds a small,
  pure layout module and a side-effecting provisioner that is not imported by the
  publisher runtime (the publisher import closure stays at 15 modules).

## Scope

This ADR is about realizing, in OS state, boundaries already qualified in Stages
1–7. It does not expand PKI, signing, or authenticity, and it does not reopen
F-14. Final F-17 qualification remains a separate, not-yet-authorized step.
