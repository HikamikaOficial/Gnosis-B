# F-33 Stage 2C-B1 — OS-Real Identity-Delta Run — Findings

Baseline HEAD `583a0ebdf83cb3facb268da429ed2dc68bd2bcc7`. ONE authorized OS-real
execution, no remediation, no provider call. **The mismatch reproduced and the exact
differing F-17 identity component is now PROVEN.**

## Result: the delta is a PACKAGE (trust-tree) CONTENT change
- Digests: `provision = c58b54f4…609f73`, `launch = 4c1afb14…68e69a6`, **match = NO**.
- Stages: `base_provision → composed_deployment → trusted_record → acls →
  service_start → pipe_ready → route_selected` — then the canonical-launch
  re-observation gate failed closed.
- `identity_delta.delta.status = OK`; **classification = `PACKAGE_CONTENT_CHANGED`**.
- Component map: **only `package` = CHANGED**; `runtime`, `runtime_tree`, `service`,
  `trust_root`, `runidentity_store`, `anchorstore`, `pipe_policy`, `schema` = all
  UNCHANGED. `sddl_delta = {}` (empty).
- Package manifest delta: **47 ADDED, 0 removed, 0 changed.** Component digest moved
  `722de89a… → 6db1dcca…`.

## What was added (the entire composed application/operator tree)
`APPLICATION.json`, `operator_entry.py`, and `gnosis/**`:
`adapters/{__init__,cli_review,review_payload}.py`;
`contracts/{__init__,director_brief,engineer_report}.py`;
`director/{__init__,brief_record,cli,composition,deterministic_worker,execution,
inbox,pipeline,publication,publisher_client,trusted_runner}.py`;
`kernel/{budget,claims,code_intelligence,convergence,credentials,engine,failures,
git_evidence,ids,integration,lease,ledger,ordering,policy,redaction,run_store,
scheduler,state_machine,verification,worktree}.py`;
`provision/{__init__,layout}.py`; `runner/{__init__,capture,claude_cli_runner,
gated_runner,liveness,retry}.py`.

These are the application/operator files — **not** trust-plane files and **not**
anything the Publisher writes at runtime.

## Interpretation (DELTA proven; MUTATOR strongly indicated, not proven)
The F-17 deployment digest measures `package = observe_trust_package(trust_root)`
(a content manifest of `trust_root`). At **provision time** (F-17 base install),
`trust_root` held only the base trust package, and that digest became
`record.f17_deployment_digest`. By **canonical-launch time**, `trust_root` also
contains the **composed application/operator tree**, so the fresh re-observation of
the same root hashes 47 more files and the F-17 digest no longer matches. The gate
therefore fails closed — correctly.

- **DELTA = PROVEN**: `PACKAGE_CONTENT_CHANGED` — 47 application/operator files added
  to `trust_root` between the trusted observation and the re-observation.
- **MUTATOR = NOT-PROVEN (strongly indicated: the composed-deployment step)**: the
  added set is exactly the composed application tree (`operator_entry.py`,
  `director/`, `kernel/`, `runner/`, …), which the composed model installs into the
  deployment; the Publisher writes none of these. The single intervening stage that
  adds an application tree is `composed_deployment` (it runs immediately after
  `base_provision`). Per DELTA≠MUTATOR this is not asserted as proven without an
  intermediate snapshot, but no other stage plausibly adds these files.

This confirms R3A's leading family (real mutation inside the observed set) and
narrows it precisely: the composed application tree is co-located under the same
`trust_root` that the F-17 base digest measures, so recording the F-17 digest
*before* composition and re-observing *after* composition cannot agree.

## Gate / live / rollback
- **TRUST GATE = FAIL (fail-closed)** — correct; Worker NOT reached; L2 NOT consumed;
  ledger **1 / 5**; `anchored = false`.
- **Automatic rollback = PASS**; independently verified: service absent (sc 1060),
  worker account absent, deployment/scaffold root absent, residue manifest absent →
  **RESIDUAL OS STATE = NONE**; no manual cleanup.
- Source freeze: HEAD unchanged; `src/gnosis` diff = 0; driver/harness/`deployment.py`
  hashes identical pre/post. No implementation change during the run.

## Diagnostic outcome vs qualification
Per §19 this run is a **diagnostic SUCCESS** (mismatch reproduced, exact component
identified truthfully, gate failed closed) even though **B1 qualification = FAIL**.

## Exact next action (separately authorized; NOT done here)
Design — for independent review, NOT to apply — a remediation for the co-location:
the F-17-observed `trust_root` and the composed application tree must be reconciled
so the trusted F-17 identity is stable across composition. Candidate directions (to
be evaluated, none chosen here): record the F-17 digest **after** the composed tree
is in place (so the trusted observation matches what launch re-observes); or place
the composed application tree outside the F-17-observed `trust_root` (separate app
root) so the F-17 package identity is unaffected by composition; or re-observe/record
the composed identity as the trusted operand. **MUST NOT** update the trusted digest
to the fresh value as a bypass, disable/move the gate, or exclude files to force a
pass. Do NOT change topology/ACLs/Publisher/F-17 without authorization. Do not close
F-33.
