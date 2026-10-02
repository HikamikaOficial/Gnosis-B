# F-33 Stage 2C-PACK-R2.1 — Provision-Gate Assurance Closure — Final Evidence

Result: **PASS (pending narrow independent acceptance).** F-33 remains **OPEN**;
Stage 2C-PACK **READY FOR FINAL NARROW ACCEPTANCE**; **Stage 2C-B NOT RESUMED**.
Test/evidence-only slice: **production behaviour diff = NONE**.

## The assurance gap this slice closes
The R2 final review accepted the architecture but blocked on
`PROVISION-TIME GATE ASSURANCE TEST MISSING`: the production provision-time
verification and its fail-closed behaviour were implemented and correct, but no
qualification test asserted that layer independently, so mutants `E-M1`
(remove provision-time verify) and `E-M2` (return despite verify failure) survived
against the R2 tests (which only exercised earlier-stage failures and the happy
path). This slice adds the missing direct assertions. **No production semantics
changed.**

## Starting state
- Starting HEAD (R2 evidence commit): `3e6112f7a104f136f8f8ae4e728be22428abbbbb`
- R2.1 implementation commit A: `65fd631` · `src/gnosis` tree
  `df0522c4c91fa0530501f02d85f0ab1e0ec5f1f9` — **byte-identical to the R2 src
  tree**, i.e. production source is unchanged.

## Full-suite result (R2.1, authoritative exit capture)
`1670 passed, 1 skipped, 288 subtests passed in 611.75s` · **`PYTEST_EXIT_CODE=0`**
(captured directly, not through a pipe). Classification: **GREEN** — the known
`work_queue` concurrency flake did not recur this run; no isolation rerun needed.
(+3 vs the R2 count = the three new provision-gate assurance tests.)

## Production source freeze
`git diff 3e6112f..HEAD -- src/gnosis` = **NONE** (no `.py` change). The only
tracked change is `tests/test_gnosis_deployment.py`. R2 architecture untouched:
GnosisDeploymentProvisioner, trusted composed record, composed digest,
`canonical_launch`, startup self-verifier, `APPLICATION.json`, one-trust-tree,
`operator_entry`, Worker image, F-17 integration, rollback semantics — all as
accepted.

## New direct provision-gate assertions (`TestProvisionGateAssurance`)
Test seam: patch the provisioner's OWN `verify` (`unittest.mock.patch.object`) to
raise a sentinel — observing the provision-time gate SPECIFICALLY, not a
downstream `canonical_launch`/startup refusal. No production code was changed to
enable this (the static method is patched from the test).

- **`test_e4_final_verify_invoked_before_return_and_failure_blocks`** — forces the
  final verify to fail after base + application deployment succeed; asserts the
  gate was invoked exactly once (`verify.call_count == 1`), `provision()` raised
  (no valid result returned), the sentinel propagated, and rollback fired once.
  This is the assertion R2's E1–E4 lacked. Fails if the final verify call is
  removed (E-M1) or if a result is returned after verify failure (E-M2).
- **`test_e2_composed_verify_failure_at_provision_fails_closed`** — a
  composed-identity verification failure at provision time (the final verify *is*
  the composed-identity check) yields no valid result + rollback.
- **`test_final_verify_failure_with_failing_rollback_is_unknown_state`** — final
  verify fails AND base rollback also fails → fail closed as "unknown state"; still
  no valid composed result (§8).

## Provision return behaviour (re-confirmed)
`provision()` has exactly one successful `return comp`, reachable only after
`self.verify(...)` did not raise; every failure path calls `_rollback_or_unknown`
(`NoReturn`). With the final verify forced to fail, `provision()` returns nothing
and raises. Rollback invoked per the existing contract; broadened nowhere.

## E1–E4 mapping (normalised)
- **E1** application/deployment verification failure → provision fails:
  `TestProvisionGate::test_e1_application_failure_rolls_back_base`.
- **E2** composed-identity verification failure at provision → provision fails:
  `TestProvisionGateAssurance::test_e2_composed_verify_failure_at_provision_fails_closed`
  (and `test_e4_...` exercises the same final-verify gate).
- **E3** trusted-record write/finalisation failure → provision fails:
  `TestProvisionGate::test_e3_record_write_failure_rolls_back_base`
  (+ `test_e3b_rollback_failure_reports_unknown_state`).
- **E4** NO valid composed result returned before the mandatory final verify
  succeeds: `TestProvisionGateAssurance::test_e4_final_verify_invoked_before_return_and_failure_blocks`.

No provision-gate property is claimed via a downstream launch test.

## Authoritative mutation table (E-M1…E-M12)
| Mutant | Property | Result | Killing test |
|---|---|---|---|
| E-M1 remove provision-time verify | provision gate present | **APPLIED / CAUGHT** | `TestProvisionGateAssurance::test_e4_...` |
| E-M2 return despite verify failure | provision gate fail-closed | **APPLIED / CAUGHT** | `TestProvisionGateAssurance::test_e4_...` |
| E-M3 launch skips app re-measurement | pre-launch re-measure | APPLIED / CAUGHT | `TestPreLaunchGate::test_e6_application_tamper_refused` |
| E-M4 launch skips composed-digest compare | one of two redundant launch checks | **APPLIED / SURVIVED — NON-BLOCKING REDUNDANT DEFENSE-IN-DEPTH** | (sibling app-digest check catches; see below) |
| E-M5 launch reuses record F-17 digest | fresh F-17 re-observation | APPLIED / CAUGHT | `TestPreLaunchGate::test_e8_f17_digest_change_refused` |
| E-M6 startup skips record comparison | startup trusted-record binding | APPLIED / CAUGHT | `TestStartupSelfVerify::test_e15_...` |
| E-M7 startup imports before verify | startup verify-before-import | APPLIED / CAUGHT | `TestStartupSelfVerify::test_e16_malformed_manifest_aborts` |
| E-M8 coherent tamper | — | FOLDED → E-M3 (launch) / E-M6 (startup) | — |
| E-M9 startup ignores per-file tamper | startup per-file re-measure | APPLIED / CAUGHT | `TestStartupSelfVerify::test_startup_byte_tamper_without_manifest_regen_aborts` |
| E-M10 launch without `-I` | isolation | APPLIED / CAUGHT | `TestPreLaunchGate::test_e5_valid_launch_returns_isolated_argv` |
| E-M11 arbitrary composed-record path | — | STRUCTURAL (no path parameter) | — |
| E-M12 direct supported CLI bypass | — | STRUCTURAL / FOLDED → E-M7 (no deployed console script) | — |

**8/9 applied mutants CAUGHT.** The sole survivor E-M4 is honestly preserved: it
removes one of two redundant pre-launch comparisons; disabling BOTH the
`measured != record.application_tree_digest` sibling AND the composed-digest
comparison is required before tamper slips (independently demonstrated in the R2
review). Not artificially killed by coupling tests.

Note on the previous harness: R2's E-M1/E-M2 transformations were semantically
valid behavioural mutations; they SURVIVED only because the R2 tests did not
exercise the final-verify path (a test gap), NOT because the mutations were
malformed. `PREVIOUS E-M2 HARNESS INVALID` does NOT apply.

## Full-suite evidence-capture fix
R2 captured the suite with `pytest … | tail -8`; a pipeline's exit status is
`tail`'s (0), which masked pytest's real exit (1 on the flake). R2.1 captures the
suite as `pytest … > full_suite.txt 2>&1; echo "PYTEST_EXIT_CODE=$?"` so
`PYTEST_EXIT_CODE` is pytest's own process exit, independent of any viewer command.
See `R2_EVIDENCE_HYGIENE_CORRECTION.md`.

## Tests / gates (recorded)
- Targeted: `tests/test_operator_stack.py` + `tests/test_gnosis_deployment.py` =
  **48 passed** (PYTEST_EXIT_CODE=0) — see `targeted.txt`.
- Mutants — see `mutants_r21.txt`.
- Full suite — see `full_suite.txt` (`PYTEST_EXIT_CODE` recorded directly).
- Production byte-identical, so `mypy --strict` is not required for implementation
  assurance; ruff on the changed test = clean. (mypy result, if run, in
  `static_gates.txt`.)

## Guards
Provider calls = 0. Live Claude calls = 0. OS provisioning = NONE.
`src/gnosis` production diff = NONE. `src/gnosis/trust/*` diff = NONE. Historical
provisioner (`provisioner.py`,`layout.py`,`winapi.py`) = UNCHANGED. F-37 = NOT
STARTED. NVIDIA/NIM = NOT PRESENT. Cumulative live calls = 1 / remaining 4 (L2 not
consumed).

## Next
Recommend a NARROW independent acceptance verifying only: production source
unchanged; provision-gate direct test; E-M1 kill; E-M2 kill; rollback assertion;
suite exit-code integrity. Only after independent PASS may Stage-2C-B resume.
