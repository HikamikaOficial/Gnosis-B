# F-33 Stage 2C-B1-R1.1 — Cleanup-Failure Reporting Assurance

Result: **PASS (pending R1 final re-acceptance).** Closes the sole R1 assurance
blocker: the scaffold cleanup-FAILURE reporting path is now directly qualified, so
the faithful RBM4 mutation (false "removed") is CAUGHT. **Test/mutation/evidence
only — the production/harness behavior was ALREADY correct and is byte-unchanged.**
No OS provisioning, no provider calls, no `src/gnosis`/F-17 change.

## Starting baseline
- HEAD: `8055cb3088e68d3e836b62d10e6e3c6a522edced`; worktree CLEAN.
- Prior independent R1 acceptance: FAIL — `RBM4 = APPLIED / SURVIVED` (an applied
  behavioral mutant reporting `scaffold_cleanup="removed"` even when `rmtree`
  failed survived; the R1 self-report had mis-labeled it STRUCTURAL).

## §2 Current real behavior — ALREADY CORRECT (no defect)
`_finalize_scaffold` (unchanged):
```
_sh.rmtree(scaffold_root, ignore_errors=True)
trace["scaffold_cleanup"] = ("removed" if not scaffold_root.exists()
                             else "FAILED (residue present)")
```
The status is derived from the REAL post-`rmtree` `scaffold_root.exists()`: if the
root remains, it reports **`"FAILED (residue present)"`, never `"removed"`**. So
this is a **test-only assurance gap**, NOT a behavioral defect. Per the
authorization, the implementation was **not modified**; only the missing test was
added.

## §3/§4 Direct cleanup-failure test
`TestDriverScaffoldCleanup::test_cleanup_failure_reports_failed_not_removed`:
- creates a scaffold root (with `GnosisStage2CBRecovery/inputs`), no residue record
  (so the rmtree branch is reached);
- `mock.patch("shutil.rmtree", side_effect=no-op)` so the scaffold REMAINS after
  "cleanup" (deterministic failure injection);
- exercises the REAL `_finalize_scaffold`;
- asserts: cleanup attempted (rmtree called); deletion failed (root still exists —
  filesystem truth); `scaffold_cleanup != "removed"`; status contains `"FAILED"`
  (honest failure); recovery ownership derivable (deterministic run-bound root
  `gnosis-2cb-b1-run-b1-1`). It compares **actual filesystem state vs reported
  state** (not merely `assertRaises`).

## §5 RBM4 (faithful)
Mutation: replace the existence-derived status with unconditional
`trace["scaffold_cleanup"] = "removed"`. Result: **APPLIED / CAUGHT** — killed by
the new direct test (reported "removed" while the root still exists → assertion
fails). Not a downstream/unrelated kill.

## §6 RBM3 recheck
Unchanged: **STRUCTURAL.** Cleanup authority is the exact run-bound
`code_base.parent`, not a prefix/glob; `test_scaffold_root_is_exact_owned_parent`
proves all nested driver artifacts live under that one owned root. No contrived
behavioral mutant invented.

## §7 Historical R1 correction (preserved honestly)
- Historical R1 self-report: `RBM4 = STRUCTURAL`.
- Independent R1 acceptance corrected it to: `RBM4 = APPLIED / SURVIVED`.
- R1.1 records this correction and now makes `RBM4 = APPLIED / CAUGHT`.
The historical R1 bundle is NOT rewritten as if it had originally caught RBM4.

## §8 Final RBM1–RBM4 accounting
- RBM1 = APPLIED / CAUGHT
- RBM2 = APPLIED / CAUGHT
- RBM3 = STRUCTURAL
- RBM4 = APPLIED / CAUGHT
→ **3 behavioral applied / 3 caught; 1 structural** (not "4/4 killed").
(Pipe mutants unchanged: PBM1–PBM5 = APPLIED / CAUGHT.)

## §9 Failed-pipe behavior regression (unchanged)
`test_failed_pipe_replay_self_cleans` still passes: pipe never ready → abort →
automatic Worker/service/F-17-root/scaffold cleanup → residue record retired only
after positive absence → **AUTOMATED RESIDUAL = NONE**. The new assurance test did
not disturb normal cleanup.

## §10 Cleanup-failure behavior
Forced-rmtree-failure case: CLEANUP FAILURE = DETECTED; SCAFFOLD = PRESENT;
REPORTED STATUS != "removed" (= "FAILED (residue present)"); no false fully-clean
terminal state.

## Tests / gates
- New test: 1 passed.
- R1 (`tests/test_stage2cb_b1_r1.py`): 16 passed (P1–P7, canonical name, cleanup
  incl. the new failure-reporting test).
- Targeted (R1 + driver + backend): 85 passed, exit 0.
- F-17 regression subset (publisher service/client/pipe, worker launcher,
  deployment identity, provisioner): 206 passed, 1 skipped, 62 subtests, exit 0.
- PBM/RBM: **8/8 applied CAUGHT, 1 structural** (PBM1–5, RBM1/2/4; RBM3 structural).
- Full suite: see `full_suite.txt` (`PYTEST_EXIT_CODE` captured directly; known
  work_queue flake governed by historical policy).
- `mypy --strict src`: Success, 88 files. Ruff (changed test): clean.

## §11 Production/F-17 freeze
`src/gnosis` diff = NONE; `src/gnosis/trust/*` = NONE; `provisioner.py`/`layout.py`/
`winapi.py` UNCHANGED; Stage-5/6/7/8 probes UNCHANGED. **Harness (`scripts/*`)
byte-identical** — the only change is `tests/test_stage2cb_b1_r1.py` (+ evidence).
No BEHAVIOR DEFECT discovered; scope not broadened.

## Guards
`OS provisioning = NONE` · `provider calls = 0` · `live Claude calls = 0` ·
cumulative live calls = 1 / remaining 4 · F-37 NOT STARTED · NVIDIA/NIM NOT PRESENT.

## Next
Narrow R1 final re-acceptance. Only after PASS is the B1 OS-real retry authorized.
