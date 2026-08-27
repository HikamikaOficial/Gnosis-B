# F-17 Stage 3 (trusted RunIdentity + publish authorization) evidence

Stage 2 CLOSED at `c45c547`; Stage 3 implementation tree at HEAD `a6dd6aa`.

The property: **knowing a run_id is NOT enough to produce ANCHORED.** A
publisher may anchor run R only if trusted state shows R is exactly the run
authorized for that worker SID, that generation, that deployment, that evidence
identity and that lifecycle state.

**No Windows production wiring.** No worker account, no DPAPI, no launcher, no
service, no named pipe, no provisioning, no engine/runner change, no
unknown-`.git`, no Stage-4 durability. Contract, model, store and tests only;
nothing persistent was installed.

Reused rather than invented, after inspecting what already exists:
`TaskClaim.epoch` is the generation (no nonce was created), `RunStore`'s
`mkdir(exist_ok=False)` is the existing run-id locus (the gap it leaves is
closed in the trust plane), `hash_canonical` stays the only hashing
implementation, and `atomic_io` + `file_lock` are reused — which is why both
enter `TRUST_ALLOWLIST` by explicit diff. `RunIdentity` was **extended in
place**, not duplicated.

`PublicationState` is a new primitive for one reason: `RunState` lives in the
run directory the **worker can write**, so it could never gate the worker's own
publication. Immutable identity and monotonic state are kept structurally
apart — `transition()` carries no identity at all — and every update is a
compare-and-set, which is what closes the delete-and-recreate (ABA) route.

`gnosis.anchor.v2` adds exactly two fields, each carrying a guarantee V1 could
not. V1 stays readable under its historical contract and its digest re-derives
byte for byte; it can never satisfy a deployment-bound verification.

**A mutant survived the first run and the model changed because of it**: RM13
showed the V1 schema guard was refusing by coincidence, collapsing "carries no
binding" and "bound to another trust plane" into one error. Repaired by making
the distinction a type. Recorded in full — a check that cannot fail is not a
check.

Directed 209 passed / 18 subtests; fresh checkout of `a6dd6aa` identical;
mutation 17/17 CAUGHT (0 survived); **full suite 1218 passed / 72 subtests,
GREEN**; mypy clean over 64 source files; ruff clean on every new and changed
file; negative control and secret scan (0 findings) captured.

`deployment_digest` proves exact observed deployment identity — **not** that the
deployed bytes were built from the claimed commit. Binding and provenance stay
separate concepts.

F-14 remains **CLOSED**; the historical flaky event stays an evidence note.
Stage 4 NOT started. F-17 stays OPEN. See `STAGE3-RESULTS.txt`.
