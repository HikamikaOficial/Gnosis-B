# F-33 Stage 2C-B1-PRE0 — OS-Real Execution Driver Construction + Dry Qualification

Result: **PASS (pending narrow acceptance).** The authorized OS-real execution
driver now exists and is dry-qualified; after this, Stage-2C-B1 requires only
`run qualified driver --execute-os-real --confirm <token>` — nothing substantial
to write or rewire. Harness/driver/test/evidence only; **no `src/gnosis` change**;
F-17 unchanged; no OS mutation; no provider calls.

## Starting state / prior B1 blocker
- Starting HEAD: `042a7a9aba8226eec7587f94a758a55c6f7dd6aa`.
- B1 correctly returned BLOCKED: the qualified harness had **no authorized OS-real
  entrypoint** (the `--os-real` path was a guard that refuses), and the operator
  argv, real F-17 re-observation, `runtime_src`, and `observe_fn` wiring were
  missing.

## §2 Archaeology (read-only, before editing)
- **Relocatable runtime source:** F-17 Stage-8 (`probe_stage8._make_provisioner`)
  uses `runtime_src=sys.base_prefix`. This is the qualified mechanism — reused
  verbatim as `QUALIFIED_RUNTIME_SRC = sys.base_prefix`. A legitimate source
  exists; no download/invention needed.
- **F-17 re-observation:** `gnosis.trust.deployment.observe_deployment(DesiredDeploymentConfig(...)).digest()`.
- **`observe_fn` semantics:** `Provisioner._observe`: `observer = self.observe_fn or observe_deployment` — so `observe_fn=None` means the REAL `observe_deployment` (proven from source; test `test_observe_fn_none_means_real`).
- **CLI contract (CORRECTED):** `gnosis run --config <trusted config JSON path> --brief <operator brief JSON path>` — BOTH required; `--brief` is a **JSON path**, not a run_id. The prior assumption `run --brief <run_id>` is **parser-invalid** (missing `--config`). Success requires COMPLETED ∧ persisted ANCHORED (`cli._run` → EXIT_OK only on `outcome.success`).
- **Reviewer:** `cli.build_reviewer` requires an ABSOLUTE `binary` → `ClaudeCodeCLIRunner`; PATH/relative rejected.
- Config schema (`_REQUIRED_CONFIG`): deployment, attribution, operator, publication, verifier, reviewer.

## Deliverables
- `scripts/run_f33_stage2c_b1_osreal.py` — the dedicated authorized execution
  driver (composition/bootstrap only; ~250 LOC).
- `scripts/stage2cb.py` — one small change: the orchestrator's `operator_args` is
  now driver-supplied (the hardcoded placeholder was the parser-invalid
  `("run","--brief",run_id)`; the default is retained for back-compat dry tests,
  the driver passes the corrected argv). No other harness change.
- `tests/test_stage2cb_b1_driver.py` — D1–D18 (21 tests).
- `src/gnosis` diff: **NONE**.

## §4/§5 Explicit authorization + gating
Default invocation mutates nothing (dry trace). OS-real requires **both**
`--execute-os-real` and `--confirm EXECUTE-F33-2CB1-OS-REAL`. `WindowsRealOperations(authorized=True)` is constructed **only after** auth →
HEAD → residue → runtime → preflight gates. Any failing gate returns a
`BLOCKED-*` result and constructs **no** real backend (D2/D3/D4/D8/D9).

## §6/§7 Real F-17 observation
`make_real_reobserve` returns a closure calling `observe_deployment(...).digest()`
fresh (D5: proven to invoke `observe_deployment`, not a cached constant). The
os-real branch passes `observe_fn=None` → the F-17 Provisioner uses the real
`observe_deployment` internally (proven from source).

## §8/§9 Runtime source
`runtime_src = sys.base_prefix` (Stage-8-qualified), a real relocatable interpreter
tree; runtime preflight refuses a missing/non-relocatable source before mutation
(D8). Not `.venv`, not downloaded, not ad hoc.

## §10/§11 Operator argv (corrected + verified)
The driver emits the verified `("run","--config",<config.json>,"--brief",<brief.json>)`.
D13 proves it reaches `cli._run` with `(config, brief)`; D14 proves the old
`run --brief <run_id>` is parser-invalid (→ EXIT_USAGE, `_run` never called). The
driver writes a structurally-valid operator config (all 6 required sections) and a
`DirectorBrief`-shaped brief. (§12: dry argv qualification proves entry→parser→run
command only; COMPLETED∧ANCHORED remain B1 OS-real properties.)

## §13/§14 Driver call graph / single orchestration
The driver performs no production semantics; it invokes the exact existing
`Stage2CBOrchestrator.run()` (D10). No second orchestration graph; no account/ACL/
service/review/publication/RunIdentity/composed-identity logic in the driver.

## §16/§17/§18/§19 Reviewer / ledger / residue / recovery
Reviewer bound to the absolute Claude executable → `ClaudeCodeCLIRunner` (D11;
relative rejected). Live ledger starts at cumulative `used=1` (D12/D12b: run never
resets to 0). Residue store bound; an active/malformed record STOPs before mutation
(D4). Recovery is an explicit separate entrypoint (`--recover-owned-residue`) that
consumes the ownership-safe `recover` (D18); no auto-recovery of unknown residue.

## §20/§21 Pre-mutation trace / zero side effects
`plan_trace` reports expected HEAD, runtime_src, reviewer executable, worker/service/
pipe names, residue path, F-17 observer, OS backend, live ledger, canonical argv.
Dry execution: `WindowsRealOperations` **not** constructed (D1/D16), operator
subprocess seam faked (D17) — real OS effects = 0, provider calls = 0.

## §24 Complete dry driver trace
`run_driver(execute_os_real=False)` runs the SAME orchestration graph via
`DryOperations`: `base_provision → composed_deployment → trusted_record → acls →
service_start → pipe_ready → route_selected → operator_launch → anchored_check →
success`, then rollback. Result `DRY-TRACE-OK`; `real_ops_constructed=False`;
OS effects 0; provider calls 0; `OS-REAL EXECUTION = NOT RUN`.

## D1–D18
All 21 driver tests pass (D1 non-mutating default; D2/D3/D4/D8/D9 gates; D5 real
observer; D7 Stage-8 runtime; D10 same orchestrator; D11 absolute reviewer;
D12/D12b ledger; D13/D14 argv; D15 pipe-publisher route; D16/D17 zero effects; D18
recovery refusal; plus config-sections and observe_fn-source proofs).

## §22 EDM1–EDM12
APPLIED / CAUGHT (7): EDM1 (auth bypass), EDM3 (cached reobserve), EDM6 (runtime
preflight omitted), EDM7 (parser-invalid argv), EDM9 (ledger reset to 0), EDM10
(active residue ignored), EDM12 (PATH-controlled reviewer). STRUCTURAL/FOLDED (5):
EDM2 (construction is after residue+runtime gates; gate-fail tests show no
construction), EDM4 (os-real branch sets `observe_fn=None`; None==real proven),
EDM5 (config condition, folded into D8), EDM8 (driver uses the orchestrator, not
`cli.main`; D10), EDM11 (no duplicate orchestration; D10). **No security-relevant
survivor.**

## §25 Remaining deferred list — ZERO implementation items
Only inherently-live facts remain: real Worker SID/integrity/Job containment; real
ACL observation; real service SID; real named pipe; real Worker execution; live
Claude L2 review; real persisted ANCHORED; OS recovery/residue behavior; final
residue observation. No `wire/implement/choose runtime/add entrypoint/fix args/
connect observer/create driver` item remains.

## Tests / gates
- Driver (D1–D18): 21 passed. Targeted (driver + backend + operator_stack +
  gnosis_deployment): 117 passed, exit 0.
- Backend regression (stage2cb.py changed): 48 passed (no regression).
- EDM: 7/7 applied CAUGHT, 5 structural.
- F-17 regression: 298 passed, 1 skipped, 62 subtests, exit 0.
- Full suite: 1738 passed, 1 skipped, 307 subtests; **1 failed = the KNOWN
  work_queue concurrency flake** (aggravated by concurrent capture runs), isolated
  rerun 3/3 pass. Classification: RED — KNOWN PRE-EXISTING FLAKE. See
  `full_suite_note.txt`.
- `mypy --strict src`: Success, 88 files (production unchanged). Ruff: clean.

## Guards
Provider calls = 0. Live Claude calls = 0. OS provisioning = NONE. `src/gnosis`
diff = NONE. `src/gnosis/trust/*` diff = NONE. Historical provisioner + Stage-5/6/7/8
probes UNCHANGED. F-37 = NOT STARTED. NVIDIA/NIM = NOT PRESENT. Cumulative live
calls = 1 / remaining 4.

## Next
Narrow independent acceptance of the execution driver. Only after PASS is
Stage-2C-B1 (the real privileged run, from the new PRE0-qualified HEAD) authorized.
The B1 expected-HEAD baseline is the PRE0 evidence HEAD, supplied via
`--expected-head` (not hard-coded to the pre-driver HEAD).
