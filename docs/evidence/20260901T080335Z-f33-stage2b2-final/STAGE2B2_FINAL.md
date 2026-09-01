# F-33 Stage 2B.2 — Authoritative Publication + Operator Entry — Final Evidence

Result: **QUALIFIED (component/integration) with documented deferrals.** F-33 remains **OPEN**;
**Stage 2C NOT AUTHORIZED**. The complete real-worker + real-deployment composed operator E2E and
the provider-backed production reviewer are **explicitly deferred to Stage 2C** (see "Deferrals").

## Stage-2B.1 evidence-honesty correction (carried forward)
- B1–B7 + B9 = **8/8 applied/behavioral mutants CAUGHT**; **B8 = STRUCTURAL GUARD PASS**;
  **SURVIVED = 0**. Historical raw evidence unchanged.
- The earlier pre-existing `test_work_queue` concurrency flake is preserved as historical
  evidence: one 2B.1 full-suite run hit it; isolated rerun was 6/6 green; the authoritative 2B.1
  rerun was 1579 passed / 1 skipped / exit 0. Not attributed to any code change.

## Identity / tree
- Starting HEAD (pre-2B.2): `4f4b64ce927a617ec632ea906d1466ca4697172e`
- Commit A (publication seam + composition): `46e61e8` · Commit B (operator CLI + entry): `551a4d9`
- Resulting HEAD / `src/gnosis` tree recorded at Commit C time; **new Stage-2B.2 identity** (not the
  historical F-17 / Stage-2A / Stage-2B.1 identities). Final composed deployment measurement → 2C.

## F-17 publication archaeology (consumed, unmodified)
- `authorize_publishable(store, identity, evidence) -> TrustedRunRecord` (`trust/orchestration.py`) —
  the ONLY NOT_PUBLISHABLE → PUBLISHABLE path; needs `CompletionEvidence(exit_code, timed_out,
  cancelled, bundle_dir)` over a verifiable bundle with a CLEAN boundary verdict.
- `create_trusted_run(store, plan, *, spec, deployment, launched)` — freezes `RunIdentity` from
  OBSERVED values (`launched.observed_sid`, `launched.launch_spec_digest`, `deployment.digest()`;
  requires a V2 deployment that binds the runtime tree; `spec.run_id == plan.run_id`).
- `durable_publish(anchor_store, run_store, request, bundle_dir)` (`trust/publication.py`) —
  PUBLISHABLE → anchor → `mark_anchored` → `PublicationState.ANCHORED`; idempotent (ALREADY_ANCHORED).
- `PublicationState` = NOT_PUBLISHABLE → PUBLISHABLE → ANCHORED (monotonic).
- **Additive-consumption confirmed:** all symbols are public; `probe_stage6_composition.py` is the
  existence proof; `src/gnosis/trust/*` diff = **NONE**. NOT `STAGE 2B.2 BLOCKED`.

## Canonical operator object + entry
- Entry: `[project.scripts] gnosis = "gnosis.director.cli:main"` — the ONE operator entry.
- `ProductionComposition` (composition.py) wraps the canonical `GovernedPipeline` + the publication
  seam; `build_production_deployment(config, publication)` builds it (reusing the 2B.1
  `build_production_composition` for the governed graph). No second orchestration engine.

## Operator-success invariant (§14)
`operator success = governed work COMPLETED AND publication ANCHORED`. Non-COMPLETED work is never
published (P1); a publication that does not reach ANCHORED is never operator success (P3/P4). Worker
stdout is UNTRUSTED and reaches no authority field (P6). RunIdentity is deployment-bound: owner SID
from the launched token, deployment digest from the measured V2 identity (D11).

## Call graph
CLI `main` → `build_operator_composition` → `build_production_deployment` → `ProductionComposition`
→ (work) `GovernedPipeline → scheduler → engine(cli_runner=TrustedExecutionRunner) →
TrustedExecutionPort → F-17 Worker` → (publish) capture bundle → `create_trusted_run →
authorize_publishable → durable_publish → ANCHORED`.

## Tests (all against the REAL trust code where publication is exercised)
- Publication seam: **6** — full chain reaches real ANCHORED; fail-closed on non-zero exit / seal
  mismatch / tampered bundle; idempotent; worker-data cannot reach authority.
- Operator-success composition: **6** — COMPLETED∧ANCHORED → success; failed/escalation work not
  published; no-recorded-launch fail-closed; publication failure → not success.
- CLI: **8 (+9 subtests)** — forbidden-flag rejection, usage errors, delegation, exit codes, honest
  fail-closed on the deferred reviewer, incomplete-config usage error.
- Full F-33 targeted set: **89 passed, 17 subtests**.
- Trust/publication regression (durable_publication, trusted_orchestration, deployment_identity,
  authority_boundary): **172 passed, 31 subtests**.
- Full suite (authoritative rerun): **1599 passed, 1 skipped, 276 subtests, exit 0** (`full_suite.txt`).
  TWO earlier full-suite runs each hit ONE pre-existing `test_work_queue` concurrency flake (a
  different test each time: `TestConcurrentRecovery...` then `TestOwnershipIsTheClaimsPlane...`); the
  latter fails ~1-in-6 even in ISOLATION, and `git diff 4f4b64c..HEAD -- src/gnosis/kernel
  src/gnosis/trust` = 0, so it is independent of this director-only additive slice. The clean
  authoritative rerun above has all of them green.
- `mypy --strict src`: **Success, 85 source files**. Ruff: changed files **clean**; baseline untouched.

## Applied-mutant / adversarial set (D1–D11)
Behavioral (applied, CAUGHT): **D1** bypass authorize_publishable · **D2** CLI success before
ANCHORED · **D3** success when publication fails · **D4** publish after failed work · **D11**
detached/fake RunIdentity (owner SID not deployment-bound). **5/5 applied behavioral CAUGHT.**
Structural guards / defense-in-depth (reported separately, not applied behavioral mutants):
**D5/D6** operator runtime/governance override — the forbidden-flag blocklist is defense-in-depth over
argparse's unknown-argument rejection (both yield EXIT_USAGE); **D7** legacy runner — caught by 2B.1
B1 + the `build_production_deployment` isinstance assertion; **D8** placeholder attribution — caught by
2B.1 B5/B6 (C7/C8); **D9** worker-data → authority — structural (PublicationInputs has no worker field);
**D10** DirectorOrchestrator as operator root — AST guard (2B.1) + factory returns GovernedPipeline.

## Guards
- Provider calls: **0**. F-17 `src/gnosis/trust/*` implementation diff: **NONE**. No F-35–F-40 touched.

## Deferrals (to Stage 2C, per §29 / the reviewer's scope decision)
1. **Provider-backed independent reviewer.** A production `gnosis run` needs a provider-backed reviewer
   to reach COMPLETED; provider-backed execution is deferred. `build_operator_composition` therefore
   **fails closed (exit 4)** rather than run an unsafe always-pass reviewer.
2. **Complete composed OS-real operator E2E** (§28) — CLI → real Worker boundary → real deployment
   observation → publication → ANCHORED — is deferred to Stage 2C. The publication seam is qualified
   against the REAL trust code in-process (reaches ANCHORED); the Worker boundary itself is OS-real
   qualified in Stage 2A/2B.1. What is NOT yet done is the single composed real-worker+real-deployment
   run through `gnosis run`.
3. Real Publisher SERVICE/pipe boundary (§29) and final composed deployment measurement (§36) — 2C.
