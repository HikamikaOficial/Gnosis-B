# R2 Full-Suite Evidence-Hygiene Correction (R2.1)

The historical PACK-R2 raw evidence is preserved unchanged at
`docs/evidence/20260901T190000Z-f33-stage2c-pack-r2-final/full_suite.txt`. This
note records the correct interpretation; it does NOT rewrite the R2 run.

## Historical R2 suite — correct classification
- Classification: **RED — KNOWN PRE-EXISTING FLAKE**.
- Raw summary: `1 failed, 1666 passed, 1 skipped, 285 subtests passed`.
- Failed node: `tests/test_work_queue.py::TestOwnershipIsTheClaimsPlane::test_concurrent_workers_never_run_a_brief_twice`
  (Windows file-access timing race: expected `[]`, got
  `[PermissionError(13, 'Acceso denegado')]` at `test_work_queue.py:75`).
- **`pytest` process exit = 1** (a test failed).
- **pipeline/`tail` exit = 0** — the R2 capture used `pytest … | tail -8`, and a
  shell pipeline reports the LAST command's status (`tail` = 0). The harness-
  appended `[exited with code 0]` and the R2 note's phrase "process exit 0" both
  referred to the pipeline/`tail`, NOT to pytest.

## Why the previous wording was misleading
"process exit 0" read as if pytest itself passed. It did not; pytest exited 1
because of the flake. The raw file was truthful ("1 failed"), but the derived
phrasing conflated pytest's exit with the pipeline's. The flake was correctly
adjudicated non-blocking (no R2 diff to `test_work_queue`, provisioning-only
footprint, isolated rerun passes), but the run was RED, not GREEN.

## Corrected capture method (used for R2.1)
```
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider > full_suite.txt 2>&1
echo "PYTEST_EXIT_CODE=$?"   # pytest's own process exit, not a viewer's
```
`PYTEST_EXIT_CODE` is recorded in `full_suite.txt`, distinct from any
formatter/viewer command. No output is piped through `tail`/`head` as the
authoritative gate.
