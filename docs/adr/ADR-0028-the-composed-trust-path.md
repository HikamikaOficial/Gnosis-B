# ADR-0028 — The composed trust path: one executable security route

**Status:** accepted (F-17 Stage 6, 2026-08-28)
**Supersedes nothing. Extends** ADR-0025 (evidence is a property of the engine),
ADR-0026 (evidence binds bytes), ADR-0027 (evidence is tamper-evident).

## Context

Stages 1–5 qualified the parts independently: a trust-plane split, a deployment
identity, a trusted run identity with a publish gate, a durable publication
protocol, and a dedicated-worker launcher. Each was proved on its own. None of
them was wired to any other, and a design that is correct part by part is not
yet a system.

Stage 6 joins them into one route and asks the only question that matters at the
join: under T2, where the Worker is assumed compromised, can it cause a
publication the trusted plane did not authorize?

## Decision

### The route

    Trusted Director
      observe deployment -> seal LaunchSpec -> launch dedicated Worker
      -> observe the ACTUAL token SID -> freeze RunIdentity
      -> run -> trusted completion gate -> NOT_PUBLISHABLE -> PUBLISHABLE
    Worker
      "PUBLISH <run_id>"                      the entire request surface
    Restricted Service-SID Publisher
      load trusted RunIdentity -> authorize -> verify bundle
      -> durable publish -> Anchor v2 committed

### The request surface is the defence

`PUBLISH <run_id>` and nothing else. The Worker cannot name a path, a digest, a
HEAD, a tree, a SID, an epoch, a watermark or an operation — not because each is
filtered, but because the grammar has nowhere to put them. A `run_id` is a
selector, not an authorization.

### The order is enforced by types

`create_trusted_run` requires a `LaunchedWorkerIdentity`, which exists only after
`verify_worker_token` accepted the child's token. No code path invents an owner
SID in advance because none produces that argument in advance. `RunPlan` — what
the Director intends before any worker exists — has no field for an owner SID, a
deployment digest or a launch digest: those are observations, and a plan that
could carry them is a plan that could assert them.

### Two schema extensions, both explicit

`RunIdentity` v2 carries `launch_spec_digest`, so an anchor is traceable to the
exact sealed launch intent through `run_identity_digest` — bound once and
transitively rather than copied into the anchor and kept in agreement.

`TrustPlaneDeploymentIdentity` v2 carries `runtime_tree`, because a V1 identity
measured the interpreter as ONE FILE while the deployed runtime is 3434 files
that decide what that file does. The runtime root is declared, never inferred,
and an executable that does not resolve inside it is refused.

Neither field has a default meaning "unknown": a V2 without it is refused, and a
V1 carrying it is refused. Adding them turned 114 existing tests red until every
construction site stated the value deliberately, which is the point.

### The publisher's TCB is what it needs and no more

The verification primitives moved to `gnosis.trust.bundle_verify`;
`kernel.evidence_capture` imports them rather than the reverse. Before, the
default verify path reached — lazily, inside `publish_anchor`, so a static graph
showed nothing — into evidence capture, git evidence, the input lock and the
write observer. A publisher that can execute Git is a publisher that can be made
to execute Git.

Measured after a REAL publication: 14 modules → 11, all four forbidden modules
absent. The service's own load closure is 15 modules and contains neither
`trust.deployment` (1052 lines it would only need to carry a digest it compares)
nor `trust.orchestration` (the writer's seam) nor `trust.worker_launcher`.

## What the OS-real probe found that no in-process test could

**The store rewrote what the identity measures.** `AnchorStore.__init__` applied
a mandatory integrity label unconditionally. `deployment_digest` binds the
observed security descriptor of that very directory, so OPENING the store
changed the hash of the deployment. The probe watched the digest move between
two observations of a machine nobody had reconfigured. Every publication then
failed closed with `deployment-mismatch` — correct behaviour for a mismatch, but
there should have been no mismatch. Under P2 the boundary is the NTFS DACL on
the restricted service SID, not a label; the relabel now happens only where it
IS the boundary.

**The service could not read its own code.** The tool root granted
Administrators, SYSTEM and the Worker, and nothing else, so `sc start` returned
ACCESS_DENIED. Provisioning must grant the service identity read/execute on the
trusted code it runs — Stage 8 owes this for the production layout.

## What the checking itself got wrong, recorded rather than smoothed over

- **The probe damaged the checkout.** It aimed a real "can the Worker write
  this?" attack at repository source instead of the deployed copy, and the
  Worker could write it. Bytes removed surgically; the guard now refuses any
  worker write outside the disposable roots. The underlying finding stands: on
  this machine the Worker can write the checkout, and a trusted code root must
  not be worker-writable.
- **The probe once reported success over nothing.** A crash inside setup printed
  "ALL CHECKS PASSED" because the failure list was empty. The verdict now counts
  the checks that ran and reports INCONCLUSIVE below a floor.
- **The fresh-checkout run was importing the working tree.** The venv's editable
  `.pth` put the repository's `src` on `sys.path`, so an extracted checkout
  resolved to the repository — inconsistently, giving one process two `gnosis`
  packages. The check now proves which tree won the import and refuses to run
  otherwise.
- **A test corrupted the interpreter to take its measurement.** The closure test
  popped modules out of `sys.modules` and never restored them, so a later file
  compared against stale classes. It measures in a subprocess now.

Every one of these is the same shape as the defects this stage exists to
prevent: a check that could not tell what it was looking at.

## Consequences

Accepted: the run identity is frozen just AFTER the worker starts, because Stage
5's launcher resumes the child inside `launch()`. The window is closed by
consequence — no identity means `unknown-run`, no gate means refused — not by
sequencing, and restructuring the launcher would reopen frozen work.

Accepted: only the owner SID and the deployment digest are INDEPENDENT at the
publisher. The run-scoped expectations come from the trusted store, which is
sound because the Worker cannot write it, but it is not a second source and is
not claimed to be.

Deferred to Stage 8: production ACLs, the real service account, `python._pth`,
and the trusted code root that must not be worker-writable.

## Evidence

`.gnosis/evidence/20260828T180538Z/` — OS-real composition 49/49 with verified rollback;
mutation 34/34 caught on a clean tree; isolated fresh checkout of `27a3a3c` 362
passed with the import proved; full suite 1438 passed / 156 subtests GREEN;
mypy strict clean over 74 files.

    bundle_digest  98528d1f25d70f2bef25f751378fbfba81a9acac3c061e7ed49e9bd72c67a856

    project-source Trust Plane   ~6174 LOC
    trusted Python runtime       ~62 MB / 3434 files

Neither may be quoted without the other.
