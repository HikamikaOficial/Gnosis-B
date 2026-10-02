# F-33 Stage 2C-B1 — OS-Real Run on the R2C Baseline — Findings

Baseline HEAD `9d9380b363a3b44f3a71ba390b6942c007d98ea5`. ONE authorized OS-real
execution, no remediation, no provider call. **Two headline results:** the pipe
readiness now PASSES (R2C validated OS-real), and a **new, different** blocker is
revealed at the startup self-verification gate.

## Headline 1 — NAMED-PIPE READINESS = PASS (R2C validated OS-real)
Stages reached: `base_provision → composed_deployment → trusted_record → acls →
service_start → pipe_ready → route_selected`. For the first time the run passed
`pipe_ready`; `pipe_readiness` and `publisher_failure_class` are **null** (no pipe
failure captured). The R2C `WaitNamedPipeW` observer determined the pipe was
available where the old `Path.exists()` probe raised. This **confirms** the R2C
diagnosis: the historical "publisher pipe not ready" was a **harness observation
defect**, not a Publisher initialization failure. The Publisher service started and
exposed its named pipe.

## Headline 2 — NEW blocker: startup self-verification F-17 digest mismatch
The run then failed at `GnosisDeploymentProvisioner.canonical_launch` **step (2)**,
the mandatory startup self-verification
(`src/gnosis/provision/gnosis_deployment.py:372-374`):

> `re-observed F-17 deployment digest does not match the trusted record`

`canonical_launch` re-observes the current F-17 deployment identity
(`reobserve_f17()` → `observe_deployment(...).digest()`) and compares it to
`record.f17_deployment_digest` from the trusted composed record written at provision
time. They differ, so the gate **fails closed** before any process launch.

This is a **production integrity gate behaving correctly** (it refuses to launch on a
deployment whose F-17 identity changed since it was trusted). The F-17 +
`gnosis_deployment` regression suite passes (56 passed), so the gate logic is sound —
the mismatch is a genuine **runtime inconsistency**: the F-17 deployment tree's
observed digest at launch time differs from the digest recorded at provision time.
Plausible (UNPROVEN) causes to investigate in a separate slice: the ACL application,
the Publisher service create/start, or the composed-deployment step mutating the
F-17-observed tree after its digest was recorded; or a difference between the
provision-time observer and the `reobserve_f17` wiring. **Not diagnosed further here
and NOT patched** (no patch-and-continue).

## Live effects / ledger
L2 **not** consumed (failure preceded operator/reviewer launch). Cumulative live
calls **1 / 5**; provider calls 0; OS provisioning was performed and fully rolled
back.

## Rollback / residue (independently verified)
Automatic rollback PASS: service `GnosisPubS2CBProbe` absent (sc 1060), Worker
account `GnosisWkrS2CB` absent, deployment/scaffold root absent, residue manifest
absent. **RESIDUAL OS STATE = NONE**; no manual cleanup.

## Source freeze
HEAD unchanged; `src/gnosis` diff = NONE; driver/harness/production hashes identical
pre/post; no implementation change during the run. Evidence-only artifacts committed
afterward.

## Stage outcomes
| Stage | Result |
|---|---|
| Composed OS-real deployment (base/composed/trusted/acls) | PASS |
| Publisher service create/start | PASS |
| Named-pipe readiness (WaitNamedPipeW) | **PASS** |
| Route selection | PASS |
| Startup self-verification (F-17 digest re-observe) | **FAIL (new blocker)** |
| Worker boundary / verifier / L2 / governance / publication / ANCHORED | NOT-RUN |

## Exact next action (separately authorized; NOT done here)
Authorize a narrow **diagnostic slice** to establish WHY the re-observed F-17
deployment digest differs from the trusted record: capture the provision-time
recorded digest vs the launch-time re-observed digest and the observed file set/
manifest delta (read-only), and determine whether an intervening step (ACL / service
start / composed deployment) mutates the F-17-observed tree, or whether the
provision-time and launch-time observers diverge. Only after that evidence may a
remediation be authorized. Do NOT change topology; do NOT close F-33.
