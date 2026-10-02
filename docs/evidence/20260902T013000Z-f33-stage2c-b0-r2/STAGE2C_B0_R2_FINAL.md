# F-33 Stage 2C-B0-R2 — Crash-Persistent Residue Ownership

Result: **PASS (pending narrow re-acceptance).** The sole B0 blocker — residue
ownership kept only in memory — is closed: ownership is now persisted to disk with
crash-safe ordering, loaded by preflight, and consumed by an ownership-safe
recovery path. Harness/test/evidence only; NO `src/gnosis` change; F-17 unchanged;
no OS provisioning; no provider calls.

## Starting state / prior blocker
- Starting HEAD: `69c3d2a23f8f1cbc22e54bccdebf27b824832b40`.
- Prior blocker (independent B0 acceptance): **HARD-KILL RESIDUE OWNERSHIP IS NOT
  PERSISTED** — `ResidueManifest` existed but the orchestration held ownership only
  in the in-memory `TransactionJournal`, so an abrupt kill could orphan the Worker
  account/service/roots with no recovery record.

## Files changed
- `scripts/stage2cb.py` — added `ResidueRecord`/`ResourceOwnership` (v2 schema,
  INTENDED vs ACQUIRED), `ResidueStore` (atomic, generation-counted),
  `parse_residue_record` (fail-closed), `recover` (ownership-safe), an atomic
  `_atomic_write_json`; wired the store into `Stage2CBOrchestrator.run()` and
  `preflight`; added hard-kill simulation.
- `scripts/stage2cb_ops.py` — `DryOperations.run` now models `sc.exe create`/
  `delete` so service presence tracks reality for recovery/reconciliation.
- `tests/test_stage2cb_backend.py` — `TestCrashPersistentResidue` (13 tests +
  9 HK subtests).
- `src/gnosis` production diff: **NONE**.

## Residue-record location (§2)
`Stage2CBConfig.residue_record_path()` = `residue_record_dir()/<run_id>.residue.json`.
`residue_record_dir()` defaults to `Path(code_base).parent/"GnosisStage2CBRecovery"`
— deterministic, qualification-owned, and validated to be OUTSIDE every owned root
(the disposable code/state/work roots that rollback tears down). Never CWD, env, or
a deleted root.

## Schema (§6, §8, §9) — `gnosis.stage2cb.residue.v2`
`{schema, run_id, generation, status ∈ {active,cleaned}, resources:[{kind ∈
{worker,service,root}, identity, intended:bool, acquired:bool}]}`. No secrets, no
credentials, no session material. Parse is fail-closed: exact keys, no duplicate
keys (`object_pairs_hook`), bounded size, canonical fields, monotonic `generation`.

## Intent vs acquired + persistence order (§3, §4, §5)
1. `write_initial` persists all resources `intended=true, acquired=false, gen=0,
   status=active` **before the first ownership-changing operation**;
2. F-17 `Provisioner.install()` runs (creates worker/service, deploys roots);
3. only **after** confirmed acquisition, `mark_acquired` atomically flips
   `acquired=true` (gen++);
4. in-memory rollback registered;
5. continue.
Atomic writes = temp in same dir → flush + `os.fsync` → `os.replace` (no in-place
update; a torn write leaves the prior valid generation).

## Ambiguous acquisition window (§6)
A kill AFTER OS creation but BEFORE `acquired=true` is persisted leaves
`acquired=false` while the worker/service actually exist. `recover` never assumes
`acquired=false ⇒ unrelated`: it OBSERVES actual OS state by exact identity from the
record's INTENT and plans cleanup only for resources present AND whose identity
exactly matches this qualification. Proven: HK-after-base-before-persist →
`recover → ("PLAN", [worker, service])`.

## Incremental cleanup + terminal conditions (§11, §12, §13)
During rollback, after positive removal the record is updated (`mark_cleaned`,
gen++). The record is **retired only after every owned resource is positively
absent**. If a cleanup fails, the record is KEPT describing the remaining residue,
`ROLLBACK = FAIL`, and recovery targets only the positively-owned remaining
resource. Proven by clean-rollback (resources + record absent) and failed-rollback
(record kept, worker still `acquired=true`, recovery plans only the worker).

## Preflight disk load (§14, §15)
`preflight(..., store=...)` reads the record from disk BEFORE mutation: no record →
normal collision preflight; **active record → STOP** (recovery/adjudication);
malformed → STOP; cleaned-but-resource-present → STOP. A pre-existing same-name
resource with no record is an UNKNOWN COLLISION and STOPs via the existing
collision checks. Never silently overwrites an existing record.

## Recovery flow + refusals (§16, §17)
`recover(store, config, ops)`: load (fail-closed) → run_id match → observe OS by
exact identity → PLAN only positively-owned present resources → AMBIGUOUS_RESIDUE
if any present resource is not owned (no destructive cleanup) → STALE_VERIFIED_
ABSENT if all absent → MALFORMED_RECORD / REFUSE_RUN_MISMATCH refusals. Never more
aggressive to force cleanup.

## Hard-kill matrix (§18, §19) — HK0..HK10
Simulated at HK0 (before base), the ambiguous window (after OS create, before
persist), after-acquired, and at base/composed/acls/service_start/operator_launch/
anchored boundaries. For each: the on-disk record is valid and present (written
before the first mutation); positively-persisted resources are recoverable;
ambiguous acquisitions are not destructively assumed; a subsequent run refuses to
continue while an active record exists.

## HBM17–HBM20 (§26–§29) — all APPLIED / CAUGHT
- HBM17 (no persist before first acquisition) → `test_manifest_persisted_before_
  first_acquisition`.
- HBM18 (acquired but state never updated) → `test_acquisition_persisted_
  incrementally`.
- HBM19 (delete manifest before rollback fully succeeded) → `test_failed_rollback_
  keeps_record_with_remaining_residue`.
- HBM20 (recovery cleans ambiguous/unproven ownership — security-significant) →
  `test_recovery_refuses_ambiguous_ownership`.
**4/4 CAUGHT.**

## Prior HBM (§30) — unchanged, no regression
HBM1–HBM8, HBM10–HBM14, HBM16 APPLIED/CAUGHT (14); HBM9, HBM15 STRUCTURAL.
Re-run at HEAD: 14/14 CAUGHT.

## H20 normalization (§31)
Previously overstated. Now **H20 = PASS**: on-disk persistence + preflight loading +
recovery consumption are all directly proven (write_initial before mutation;
mark_acquired/mark_cleaned; preflight disk load; recover + refusals).

## Remaining deferred list (§32) — ZERO implementation items
Only inherently-live facts remain: real Worker SID / integrity / Job containment;
real ACL observation; service SID; real named pipe; real Worker execution; live
Claude reviewer; real persisted ANCHORED; OS-real recovery behavior; final residue
inspection. No `persist/wire/load/implement` item remains.

## Tests / gates
- Backend `tests/test_stage2cb_backend.py`: 48 passed, 18 subtests.
- Targeted (backend + operator_stack + gnosis_deployment): 96 passed, exit 0.
- F-17 regression: 298 passed, 1 skipped, 62 subtests, exit 0.
- HBM1–16: 14/14 CAUGHT; HBM17–20: 4/4 CAUGHT.
- Full suite: see `full_suite.txt` (`PYTEST_EXIT_CODE` captured directly).
- `mypy --strict src`: Success, 88 files (production unchanged). Ruff: clean.

## Guards
Provider calls = 0. Live Claude calls = 0. OS provisioning = NONE. `src/gnosis`
diff = NONE. `src/gnosis/trust/*` diff = NONE. Historical provisioner + Stage-5/6/7/8
probes = UNCHANGED. F-37 = NOT STARTED. NVIDIA/NIM = NOT PRESENT. Cumulative live
calls = 1 / remaining 4.

## Next
Narrow independent re-acceptance of crash-persistent residue ownership. Only after
PASS is Stage-2C-B0 fully qualified and B1 authorized.
