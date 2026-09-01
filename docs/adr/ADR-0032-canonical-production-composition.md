# ADR-0032 — Canonical production composition: wiring GovernedPipeline to the F-17 trust plane

**Status:** proposed (F-33 Stage 1 — 2026-09-01); awaiting independent review. NOT accepted; Stage 2 (implementation) is NOT authorized by this document.
**Consumes** (does not reopen or modify) ADR-0017 (GovernedPipeline), ADR-0018 (integration), ADR-0028 (composed trust path), ADR-0030 (provisioning), ADR-0031 (F-17 CLOSED). **Does not reopen** F-14 or F-17.

## 1. Context

F-33 established (VALID, ALTA, product-completeness) that `GovernedPipeline`
(`src/gnosis/director/pipeline.py`) is implemented but **production-inert**: zero
`GovernedPipeline(` constructions in `src/`, no `[project.scripts]`, no
`__main__`, no service that constructs the Director orchestration. The only
production entry points are the F-17 trust-plane primitives
`trust/bootstrap.py:main` (worker-side sealed-spec exec) and
`trust/publisher_service.py:main` (restricted Publisher host). There is no
operator-usable command that drives one governed brief end-to-end.

## 2. Problem

`GovernedPipeline` predates F-17 and is **doubly decoupled** from it:

- **Execution:** its implementation launch uses `scheduler.engine.cli_runner` (a
  plain `CLIRunner`), not the F-17 trusted worker-launch boundary.
- **Completion:** it "completes" via `kernel.integration.WorkIntegrator`
  fast-forward land onto `gnosis/<task_id>` plus an `EngineerReport`, not the
  F-17 authoritative publication path.

`trust/` references none of `GovernedPipeline`/`WorkIntegrator`/`EngineerReport`,
and vice-versa. A compliant F-33 closure must make the composition **consume**
F-17 on both seams (F-33 closure criteria forbid a path that bypasses F-17
launch or publication). Those seams do not exist and must be designed here
before any code.

## 3. Existing pre-F-17 architecture (consumed, not changed)

`GovernedPipeline.run_brief` / `run_pending`: DirectorInbox (dedup by brief_id) →
policy/authority gate (`kernel.policy.PolicyEngine`) → schedule/lease
(`kernel.scheduler.TaskScheduler`, `kernel.lease`, `kernel.claims`) → implement
(via `scheduler.engine.cli_runner`) → verify (`Verifier`, **required at
construction**) → independent review (a **distinct** runner;
`pipeline.py:179` refuses `review_runner is scheduler.engine.cli_runner`) →
converge (`ConvergencePolicy`) → integrate (`WorkIntegrator` → `gnosis/<task_id>`)
→ `EngineerReport`.

## 4. Existing F-17 architecture (consumed, not changed) — exact symbols

- **Worker launch:** `trust.worker_launcher.WorkerLauncher` (Protocol) with
  `launch(self, spec: LaunchSpec) -> WorkerLaunchResult`; `LaunchSpec`
  (`trust.launch_spec.LaunchSpec`), `child_environment(spec, …)`;
  `LaunchedWorkerIdentity`, `WorkerLaunchResult`; failures
  `WorkerLaunchFailed`/`WorkerIdentityMismatch`; worker entry
  `trust.bootstrap.main`.
- **Publication authorization / Publisher:**
  `trust.orchestration.authorize_publishable(store: TrustedRunIdentityStore,
  identity: RunIdentity, evidence: CompletionEvidence) -> TrustedRunRecord`
  ("The ONLY path from NOT_PUBLISHABLE to PUBLISHABLE");
  `trust.run_identity.PublicationState` (NOT_PUBLISHABLE / PUBLISHABLE / ANCHORED),
  `TrustedRunIdentityStore`, `TrustedRunRecord`, `run_identity_digest`;
  `trust.anchor.build_anchor_record`, `trust.anchor.publish_anchor`, `AnchorStore`;
  `trust.publisher.Publisher(config: PublisherConfig)` whose request surface is
  exactly `PUBLISH <run_id>` (a run_id is a **selector, not an authorization**);
  Publisher entry `trust.publisher_service.main`.

These symbols were verified against the current tree; the ADR treats them as
normative consumption points and **must not** duplicate or modify them.

## 5. Decision (design only)

Introduce **one** canonical production composition root and **one** operator
entry point that construct `GovernedPipeline` (the strong-governance
orchestration) and connect it to the F-17 trust plane through **two explicit
seams** — a trusted-execution port and an authoritative-publication port —
consuming the F-17 public APIs above. No second authority, launcher, anchor, or
publication ledger is created.

## 6. Canonical composition root

`src/gnosis/director/composition.py` (Director domain; no parallel roots). Public
factory `build_production_composition(config) -> <canonical orchestration>`.
It **owns assembly/lifecycle only** (construction/shutdown order of paths, run
store, scheduler, verifier, policy engine, runners, integrator, credential pool,
trust-plane clients). It **MUST NOT** reimplement policy logic, worker isolation,
credential authority, RunIdentity, publication authorization, Publisher, scheduler
internals, or verifier semantics.

## 7. Operator entry point

**One** `[project.scripts]` console entry `gnosis = "gnosis.director.cli:main"`
(a `python -m gnosis.director` shim may delegate to the same `main`). Intended
semantics: `gnosis run [--once|--watch]` and `gnosis submit <brief.json>`. No
co-equal alternative entry points; service wrappers delegate to
`build_production_composition`.

## 8. GovernedPipeline / DirectorOrchestrator relationship — **Decision: A**

`GovernedPipeline` is the **canonical production orchestration**;
`DirectorOrchestrator`/`recording_orchestrator()` remain a **non-production
record/replay + test harness**. Justification: `GovernedPipeline` is the only path
that makes `verifier` and `policy` mandatory and enforces implementer≠reviewer;
`DirectorOrchestrator` makes the verifier optional and `require_policy=False` by
default, so it cannot become operator-reachable without weakening governance.
`DirectorOrchestrator` must **not** be given an operator entry point. (Option B/C
— merging — is deferred; not required for F-33.) There must be exactly one
supported production orchestration root.

## 9. Seam A — trusted execution port (contract only)

Define an interface `GovernedExecutionPort` (name indicative) that GovernedPipeline
uses for every governed worker launch:

- accepts an already-authorized unit of work (post policy/lease);
- constructs/consumes the required trusted `LaunchSpec`;
- executes **only** through the F-17 `WorkerLauncher.launch(spec)` boundary;
- returns bounded execution evidence to Director-side orchestration;
- **never** creates an unrestricted `subprocess`; **never** falls back to the
  plain `cli_runner` in production.

**Trusted-launch invariant:** all provider-backed **and** replay-backed governed
worker execution initiated through the canonical composition traverses the
qualified F-17 worker-launch boundary. No hidden `subprocess`, no
`DirectCLIRunner` production escape hatch, no debug fallback on missing
infrastructure.

## 10. Deterministic (provider-free) qualification architecture — Correction 2

Provider-free qualification MUST still traverse the worker boundary. The chosen
model (subject to §18 blocker check): **shape A** — the trusted worker is launched
normally via `WorkerLauncher.launch(spec)`, and a **sealed deterministic/replay
execution backend is selected inside the worker** (the launch identity/isolation/
`LaunchSpec` boundary is unchanged; only the in-worker executor is the replay
backend). **Unacceptable:** `composition → ReplayingCLIRunner` directly in the
Director process (it would not exercise the production launch seam). **If current
F-17 launch APIs cannot express an in-worker deterministic backend without
modification, this is recorded as a STAGE-2 DESIGN BLOCKER** (see §18) rather than
weakening qualification.

## 11. Provider boundary

Distinguish the **execution protocol/interface** (`GovernedExecutionPort`,
`WorkerLauncher`, runner interface) from **provider-specific implementations** (the
current local `claude` CLI is one provider-backed executor). No NVIDIA/NIM is
introduced. Provider-backed execution is not required for Stage-1 acceptance;
provider-free qualification is the first qualification mode. Provider plurality
(F-37) is separate.

## 12. Seam B — authoritative evidence-publication port (contract only)

GovernedPipeline (Director, trusted) produces a `RunIdentity` + `CompletionEvidence`
for a run and calls `authorize_publishable(store, identity, evidence)` → the run
becomes PUBLISHABLE → the F-17 `Publisher` (`PUBLISH <run_id>`) appends the anchor
→ `PublicationState.ANCHORED`. GovernedPipeline **may request/prepare** publication
eligibility; it may **not** independently declare authoritative publication. No new
anchor implementation and no second authoritative publication ledger.

## 13. Dual state-machine semantics (Correction 1 — not collapsed)

Two distinct dimensions, distinct ownership; `ANCHORED` is **not** redefined as
"all engineering semantics complete":

**A. Governed-work lifecycle:** accepted → authorized (policy) → leased →
executing (via Seam A) → verified → independently reviewed → converged →
integrated/landed (`WorkIntegrator`, `gnosis/<task_id>`) → *work-complete
(eligible for publication)*.

**B. Evidence-publication lifecycle (F-17):** NOT_PUBLISHABLE →
(`authorize_publishable`) PUBLISHABLE → Publisher processing → **ANCHORED**
(authoritative historical-evidence publication — F-17's bounded claim, preserved).

**Relation:** integration is a Director-controlled **intermediate**, not
authoritative publication; a successful git integration does **not** imply
"authoritative evidence published"; an `ANCHORED` record asserts only what its
`CompletionEvidence` payload/contracts establish, not arbitrary engineering
semantics.

## 14. Operator-success semantics

`gnosis run` reports **final success only** when all mandatory governed-work
conditions (A) hold **AND** the evidence reaches **ANCHORED** (B). Integration
without ANCHORED = *integrated-but-unpublished* (not final success).

## 15. Authority ownership matrix (no state has two owners)

| Transition | Owner |
|---|---|
| brief accepted / dedup | GovernedPipeline / Director |
| authority/policy gate | Kernel `PolicyEngine` (Director-invoked) |
| lease/claim | Kernel `TaskScheduler` / `lease` / `claims` |
| worker execution | **Worker** (via Seam A → F-17 `WorkerLauncher`) |
| verification | `Verifier` (Director-invoked) |
| independent review | independent reviewer runner (Director-orchestrated) |
| integration/land | `WorkIntegrator` (Director) — intermediate |
| publication eligibility | **trusted `authorize_publishable`** (not Worker) |
| PUBLISH → anchor → ANCHORED | **Publisher** |
No Worker-controlled value may directly manufacture a trusted eligibility/anchor
transition.

## 16. Verifier-required contract

`Verifier` is required at composition/construction (GovernedPipeline positional)
and re-checked in the engine (`engine.py:457` for authority-governed tasks).
Startup **fails closed** if the verifier is absent; runtime **fails closed** if
verification cannot run (never reaches work-complete). No optional production
verifier mode.

## 17. Implementer≠reviewer identity semantics

Current enforcement is **Python object inequality** (`pipeline.py:179`:
`review_runner is scheduler.engine.cli_runner`). This ADR keeps that construction
gate and flags as a **Stage-2 assurance question** (not silently broadened here)
whether a stronger identity (provider/model/process identity, normalized equality,
runtime revalidation) should replace object identity. The composition must pass
two **distinct** runner objects; no fallback to one runner for both roles.

## 18. F-35–F-40 dependency boundaries

- **F-35** (`WorkAuthority.sweep()` inert): **SOFT** — the Stage-2 slice is
  **single-brief** via `TaskScheduler`, which does not require the multi-worker
  `WorkerSupervisor`/`sweep()`. A single governed brief **can** complete safely
  without `sweep()`. F-35 stays NOT STARTED; a multi-worker composition would make
  it a hard blocker and must STOP.
- **F-36** (`ProofPacket` absent): **SOFT/INDEPENDENT** — Seam B consumes the
  existing `CompletionEvidence` contract (already in `authorize_publishable`'s
  signature), not a `ProofPacket`; no pseudo-ProofPacket is invented. If the
  `CompletionEvidence` contract cannot be satisfied from GovernedPipeline outputs,
  that is a Stage-2 design blocker to report, not a substitute object.
- **F-37** (partial provider adapters): **INDEPENDENT** — reachability needs one
  provider path + two distinct runner objects; no new adapter.
- **F-38** (coupling): the composition root must **reduce** coupling (central
  assembly, one root); it must not reach into worker-plane internals.
- **F-39** (mandatory contracts): **INDEPENDENT** — the composition uses existing
  types; missing contracts are not required for reachability.
- **F-40** (inert subsystems: memory/code-intelligence/transport): **OVERLAP,
  different subsystems** — shares the "no composition root" root cause but F-33
  wires only the governed pipeline; it does **not** make memory/code-intel/
  transport reachable and does **not** close F-40.

## 19. Security consequences

Previously inert code (`GovernedPipeline`, `TaskScheduler`/engine, `WorkIntegrator`,
`CredentialPool` selection, `PolicyEngine` gate) becomes end-to-end reachable and
therefore newly security-sensitive even if bytes are unchanged; each needs E2E
(not only component) tests. The new `composition.py`/`cli.py` and the two seam
adapters are HIGH / trust-plane-adjacent. Reachability changes the threat surface:
the invariants "verifier always present," "reviewer always distinct," "no
work-complete without verify+review," "no eligibility without CLEAN boundary,"
"worker runs only under the trusted launcher" now need end-to-end proof.

## 20. Startup fail-closed rules

Fail closed (no weaker fallback) on: missing verifier; implementer==reviewer;
invalid/absent deployment identity; unavailable/unqualified F-17 worker-launch
capability; unavailable/misconfigured Publisher; invalid policy matrix; required
state/repo directory unavailable; unsupported Git/runtime qualification; ambiguous
execution backend; inability to establish the authoritative publication seam.

## 21. Shutdown / crash / recovery

Reuse existing semantics only: lease released/expired (`kernel.lease` fencing);
worker terminated via the F-17 launcher job-object; queue item recovered by the
scheduler; partial evidence + publication handled by the F-17 watermark
(`trust.publication`) — a run stuck PUBLISHABLE with no anchor recovers, never
fabricates ANCHORED; Publisher crash → watermark recovery. **Completion-failure
semantics:** if integration succeeds but publication fails, the operator command
does **not** report success; the run is durably *integrated-but-unpublished*; the
F-17 watermark/Publisher owns retry/recovery; repository integration remains
(no unsafe rollback invented).

## 22. Configuration / dependency input model

`TRUSTED` (deployment identity, policy matrix, trust-plane store roots) — never
accepted from a CLI flag asserting truth; `SERVICE-DERIVED` (Publisher config,
authorized worker SID); `OPERATOR-PROVIDED` (director-root, repo path, brief) —
validated; `UNTRUSTED` (brief contents, worker output). No security-critical
authority is trusted because an argument says so.

## 23. Stage-2 minimum implementation slice (proposed; not authorized)

1. `src/gnosis/director/composition.py` — canonical factory.
2. one `[project.scripts] gnosis` entry (`src/gnosis/director/cli.py`).
3. GovernedPipeline production construction.
4. Seam A into F-17 `WorkerLauncher.launch`.
5. Seam B into `authorize_publishable` → `Publisher` → anchor.
6. deterministic provider-free E2E through the **same** worker boundary (§10).
7. fail-closed startup (§20).
8. bypass/adversarial tests (§25).
9. fresh-isolated qualification.
No provider expansion; no F-35–F-40 repair.

## 24. Stage-2 file plan (proposed; nothing changed now)

| Path | Action | Sensitivity |
|---|---|---|
| `src/gnosis/director/composition.py` | CREATE | HIGH |
| `src/gnosis/director/cli.py` | CREATE | HIGH |
| `src/gnosis/director/pipeline.py` | MODIFY (seam hooks) | HIGH |
| `src/gnosis/trust/**` | CONSUME ONLY | TRUST-PLANE-ADJACENT |
| `pyproject.toml` | MODIFY (`[project.scripts]`) | MEDIUM |
| `tests/test_composition_e2e.py` (+ negatives/mutation) | CREATE | — |

## 25. Stage-2 qualification gates (tests) and mutation matrix

Tests: entry reachability; canonical construction (strong-governance path);
deterministic trusted-launch E2E (traverses F-17 boundary); missing verifier →
fail closed; implementer/reviewer identity violation → fail closed; policy denial →
no governed success; publication success via F-17 Publisher; publication failure →
no final success, durable recoverable state; crash/restart; fresh isolated install.

Mutation → killer test → protected invariant:
- delete verifier gate → missing-verifier/E2E → verify-required.
- accept same implementer/reviewer → identity test → independence.
- skip policy authorization → policy-denial → authority gate.
- call plain `cli_runner` directly / bypass F-17 launcher / direct subprocess →
  launch-bypass mutation (AST/boundary) → trusted-launch invariant.
- skip independent review → bypass-resistance → review-required.
- mark work complete before gates → bypass-resistance → work-lifecycle order.
- skip `authorize_publishable` / skip Publisher / fabricate ANCHORED / swallow
  publication failure → publication-bypass → single publication authority.
- make DirectorOrchestrator independently reachable → construction assertion →
  single production orchestration root.

## 26. Rejected alternatives

- Construct GovernedPipeline behind a CLI with the current `cli_runner` + git land
  (bypasses both F-17 seams; forbidden by F-33 closure criteria).
- A second anchor/publication ledger (violates single publication authority).
- In-Director `ReplayingCLIRunner` for E2E (does not exercise the launch seam).
- Two co-equal production orchestrators (GovernedPipeline + DirectorOrchestrator).

## 27. Non-goals

Repairing F-35–F-40; provider plurality; making memory/code-intel/transport
reachable; multi-worker scaling; changing F-17 guarantees.

## 28. Supersession / interaction

Consumes ADR-0017/0018 (GovernedPipeline/integration) and ADR-0028/0030/0031
(F-17). Does not supersede or modify them. F-17 remains CLOSED; its bounded
"authoritative historical-evidence publication" claim is preserved. Any guarantee
the composition needs beyond F-17 is labelled a **NEW F-33 COMPOSITION GUARANTEE**,
not attributed to F-17 (none identified in Stage 1).

## 29. New-guarantee / blocker note

No new trust guarantee beyond F-17 is required for the design. **One potential
Stage-2 design blocker** (§10): if current F-17 launch APIs cannot host an
in-worker deterministic/replay backend while preserving identity/isolation, the
provider-free E2E-through-the-boundary requirement cannot be met without extending
the launch API — to be resolved in Stage 2 design before implementation.
