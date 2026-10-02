# F-33 Stage 2C-A — Final Production Composition (reviewer + Publisher-service client)

Result: **QUALIFIED.** F-33 remains **OPEN**; **Stage 2C-B NOT AUTHORIZED**. No provider calls, no
OS provisioning; F-17 implementation unchanged.

## Identity / tree
- Starting HEAD (pre-2C-A): `26e605260a7521cb43ee0e8400c43422fff1d15d`
- Commit A: `959b4ef3c949a674642bd436760d282f83f2e76d` · `src/gnosis` tree `82d0046262246346f2129c409c7b275f8dfc4ebd`
- New Stage-2C-A source/tree identity (distinct from prior stages).

## PRE0 findings consumed
No F-17 change required; reviewer components already exist; F-37 is a separate stronger
cross-provider-independence finding (F-33 does not require it); NVIDIA/NIM NOT present; the CLI
previously failed closed before reviewer construction; real Publisher service exists but had no
reusable production client. All preserved.

## Production reviewer wiring
- `cli.build_reviewer` constructs the REAL `ClaudeCodeCLIRunner` (a distinct runner object from the
  trusted-execution implementer). Executable = trusted/deployment config: **absolute + must exist**;
  never PATH, never operator input. Never a replay runner; never an always-pass fake.
- `build_operator_composition` now builds the real composition (construction only); the Stage-2B.2
  unconditional reviewer-deferred raise is removed. Reviewer unavailable → fail closed (exit 4).
- Replay (`ReplayingCLIRunner`) stays test/harness-only; the production source references it nowhere
  (R2; the only references are the NON-PRODUCTION `director/orchestrator.py`).

## Reviewer credential handling
The `claude` CLI owns its authenticated session; GNOSIS ingests/persists NO provider credential
(none in argv/evidence/env/Worker path). No secret broker invented.

## F-17 Publisher-service client
- `director/publisher_client.py`: `PipePublisherClient` sends exactly one bounded `PUBLISH <run_id>`
  over the trusted, deployment-owned named pipe; bounded request (≤512B) / response (≤256B);
  connect + op time-bounded; endpoint from trusted config (rejects non-pipe / operator override);
  fails closed on unavailable / malformed / oversized / timeout; no arbitrary-command surface.
  The live `CreateFileW` round-trip is exercised OS-real in Stage 2C-B.
- `InProcessPublisherClient` = NON-PRODUCTION test/component client (ADR-0032 §16), drives the real
  `durable_publish` in-process so the seam is qualified without a running service.

## Canonical publication call graph
governed work COMPLETED → `capture_publishable_bundle` → `create_trusted_run` →
`authorize_publishable` → **PublisherClient.publish (F-17 service)** → real durable publication →
Anchor V2/watermark → `PublicationState.ANCHORED` (read back from the persisted store) → operator
success. The client response text is NEVER the authority — `publish_governed_run` re-reads the
persisted ANCHORED state (PC8/PC10). `publish_governed_run` no longer calls `durable_publish`
directly on the operator route (PC9).

## RunIdentity + deployment cross-binding
- One sealed `run_id` flows execution → `create_trusted_run(plan.run_id==spec.run_id)` →
  `authorize_publishable` → client `PUBLISH run_id` → anchor (I1/I2).
- `build_production_deployment` fails closed unless the execution-runtime digest
  (`observe_runtime(runtime_executable)`) equals the publication deployment's runtime digest — one
  digest scheme (`trust.deployment`), no second scheme (I4/C2A-10).

## Tests
- Reviewer R1–R8: R1 real ClaudeCodeCLIRunner; R2 no replay in production source; R3 unavailable →
  fail closed; R4 malformed review output → `InvalidReviewOutput`; R8 relative/PATH executable
  rejected; missing binary → usage error. R5 (FAIL verdict → no completion) and R6 (placeholder
  reviewer_id) are covered by existing pipeline convergence + composition C7 tests; R7 (brief cannot
  override reviewer config) by forbidden-flags + trusted-config-only construction.
- Publisher client PC1–PC10: endpoint binding + non-pipe rejection (PC1); bounded request (PC2);
  arbitrary command impossible (PC3); service unavailable → fail closed (PC4/PC7); malformed (PC5)
  and oversized (PC6) responses → fail closed; response-not-authority + persisted-ANCHORED required
  (PC8/PC10); no direct-durable_publish bypass (PC9).
- Identity I1–I5: same run_id reaches publication (I1); mismatched run_id (I2) and deployment digest
  (I3) fail closed; runtime/deployment mismatch fails closed + matched builds (I4); worker output has
  no path to identity (I5).
- Full F-33 targeted set: **112 passed, 26 subtests**.
- Trust/publication regression (durable_publication, trusted_orchestration, authority_boundary,
  deployment_identity): **172 passed, 31 subtests**.
- Full suite (authoritative): **1622 passed, 1 skipped, 285 subtests, exit 0** (`full_suite.txt`; clean on first run, no work_queue flake this run).
- `mypy --strict src`: **Success, 86 source files**. Ruff: changed files clean; baseline untouched.

## Applied-mutant / adversarial set (C2A-1..C2A-12) — 9/9 applied CAUGHT
Applied behavioral CAUGHT: C2A-2 reviewer-unavailable-accept · C2A-5 arbitrary reviewer executable ·
C2A-6 bypass the client (never publish) · C2A-7 accept malformed response · C2A-8 success without
persisted ANCHORED · C2A-9 substitute a different run_id · C2A-10 ignore runtime/deployment mismatch ·
C2A-11 accept a non-pipe endpoint.
Structural guard (separate): C2A-1 production route imports ReplayingCLIRunner → R2.
NOT APPLIED (scope): C2A-3 malformed review acceptance and C2A-4 reviewer-FAIL-allows-publication are
in the F-17/pipeline/adapter contracts (not this slice; covered by existing tests); C2A-12
service-unavailable-fallback has no code path to mutate (no fallback exists; proven by PC4).

## Guards
- Provider calls: **0**. OS provisioning: **NONE**. F-17 `src/gnosis/trust/*` diff: **NONE**.
- F-37: NOT started (using the existing Claude reviewer does not resolve it; the relationship is
  PARTIAL / stronger cross-provider independence remains separate). NVIDIA/NIM: NOT present.
- DirectorOrchestrator: NON-PRODUCTION (unchanged). Operator success = COMPLETED ∧ persisted ANCHORED.

## Deferred to Stage 2C-B
Fresh OS-real composed E2E (`gnosis run` → real Worker → real deployment observation → real Publisher
SERVICE/pipe → ANCHORED) and the bounded live provider-backed reviewer qualification (≤5 calls).
