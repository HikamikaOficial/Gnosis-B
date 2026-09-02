# F-33 Stage 2C-B1-R1 — Pipe Readiness + Driver-Owned Cleanup Remediation

Result: **PASS (pending narrow acceptance).** The two harness blockers from the
first real B1 run are fixed: the publisher-pipe failure (root cause **NAME-MISMATCH**,
not a mere race) and the driver-owned scaffold not fully removed by automated
rollback. Filesystem/mock/test-only; **no OS provisioning, no provider calls, no
`src/gnosis` change, no F-17 change.**

## Starting state / prior B1 result
- Starting HEAD: `dad1d15b9b1f0d4eccc8c5b0e8110c5eb10bf782`.
- First OS-real B1: composed deployment + provision gate + ACLs + service
  create/start PASSED; then `publisher pipe not ready`; rollback removed the
  security-critical resources; the driver scaffold required manual cleanup.

## §1 Pipe archaeology — ROOT CAUSE = NAME-MISMATCH
Identity flow inspected:
- Stage2CB driver config `pipe_name` was **`"gnosis-s2cb-probe"`** (a BARE name).
- F-17 `service_config_json` copies `pipe_name` verbatim into the service config.
- The Publisher creates `PipeServer(config.pipe_name)` → `CreateNamedPipeW(name)`
  **verbatim** (no `\\.\pipe\` prepend) — a bare name is an invalid pipe path, so
  the Publisher cannot create the endpoint.
- `PipePublisherClient.__init__` **requires** `pipe_name.startswith(r"\\.\pipe")`.
- `WindowsRealOperations.pipe_ready` did `Path(rf"\\.\pipe\{pipe_name}").exists()`
  — prepending `\\.\pipe\` to a bare name — so it checked a pipe that was never
  created.
- Canonical form (Stage-8/Stage-6/tests): `PIPE_NAME = r"\\.\pipe\gnosis-s8-probe-publish"` — the FULL local path.

**Classification: `NAME-MISMATCH`.** The harness invented a bare pipe name where
the qualified contract requires the full `\\.\pipe\<name>` path. F-17 (PipeServer,
PipePublisherClient, provisioner) is CORRECT — fix is harness-only.

## §2 Canonical pipe identity (fixed, harness only)
- Driver config `pipe_name` → **`r"\\.\pipe\gnosis-s2cb-probe"`** (full path), so
  it flows unchanged: Stage2CB config → F-17 service config → PipeServer →
  PipePublisherClient → readiness checker. No invented harness name.
- `WindowsRealOperations.pipe_ready` now checks the EXACT path
  (`pipe_exists=lambda: Path(pipe_name).exists()`) — never re-prefixed (a full name
  is not double-prefixed).
- `src/gnosis/trust/*` unchanged.

## §3 Bounded readiness (secondary — a correct-named pipe still has a start→creation window)
`stage2cb.wait_pipe_ready(pipe_name, *, pipe_exists, service_alive, now, timeout_s,
poll_s, sleep, max_polls)`: service-start acknowledged → monotonic deadline → poll
the EXACT pipe while verifying Publisher liveness. Finite timeout, bounded polling,
monotonic clock, **no service-restart loop, no infinite retry, no blind fixed sleep
as sole strategy**. Diagnostics: reason ∈ {ready, service-died, timeout,
observation-error}, polls, elapsed. `WindowsRealOperations.pipe_ready` wires it to
`Path(pipe_name).exists()` + `sc query …RUNNING` + `time.monotonic`, timeout 15s.

## §4 Pipe readiness tests (P1–P7) — all PASS
P1 ready immediately; P2 ready after multiple polls; P3 never-ready → timeout;
P4 Publisher dies → immediate `service-died`; P5 exact-pipe checked (no reprefix);
P6 observation exception → fail closed (`observation-error`); P7 bounded finite
polls (deadline-limited).

## §5 Pipe mutants (PBM1–PBM5) — all APPLIED / CAUGHT
PBM1 one-shot (no poll loop) → P2; PBM2 timeout-as-success → P3; PBM3 real
pipe_ready re-prefixes/wrong pipe → source-exactness test; PBM4 ignore Publisher
death → P4; PBM5 unbounded readiness → P7. No survivor.

## §6 Rollback-history normalization (first B1 run)
- AUTOMATED F-17/OS RESOURCE ROLLBACK = PASS (worker/service/roots/credential/
  residue-record removed).
- AUTOMATED DRIVER-SCAFFOLD CLEANUP = INCOMPLETE (mkdtemp root + inputs left).
- MANUAL CLEANUP WAS REQUIRED.
- FINAL RESIDUAL OS/FILESYSTEM STATE AFTER MANUAL CLEANUP = NONE.
Not rewritten as a fully-automated PASS.

## §7 Driver-owned resource inventory
Enumerated in `plan_trace().driver_owned_resources`: the **scaffold_root** (the
exact run-bound `code_base.parent`) and, nested beneath it, `operator_config.json`,
`operator_brief.json`, and the residue record. All driver-owned persistent
artifacts are contained by that one exactly-owned root (proved by
`test_scaffold_root_is_exact_owned_parent`).

## §8 Crash-persistent ownership
The scaffold root is now **deterministic/run-bound**
(`<temp>/gnosis-2cb-b1-<run_id>`, not random `mkdtemp`), so an abrupt kill leaves a
root reconstructable from the run_id / derivable as the parent of the residue
record's `owned_roots`. No broad-prefix (`GnosisStage2CBRecovery/*`) cleanup — one
exactly-owned root covers all nested artifacts.

## §9 Automatic cleanup
`_finalize_scaffold` runs on EVERY terminal path (PASS/FAIL/BLOCKED). It removes
the scaffold root ONLY after the residue record is retired (full rollback); if a
residue record remains, the scaffold is KEPT (`RETAINED`) so recovery can act —
recovery metadata is never deleted first.

## §10 Failed-pipe replay (self-cleans)
`test_failed_pipe_replay_self_cleans`: DryOperations(pipe_not_ready=True) replays
the exact failure → orchestration fails at `publisher pipe not ready` → rollback
retires the residue record → driver removes its scaffold → `scaffold_cleanup =
"removed"`, scaffold root absent. AUTOMATED RESIDUAL STATE = NONE (no manual step).

## §11 Cleanup failure
`test_retained_when_residue_present`: an active residue record → `_finalize_scaffold`
RETAINS the scaffold and preserves the residue record (recovery metadata). No false
PASS. (RBM2 proves removal-despite-residue is caught.)

## §13 Cleanup mutants (RBM1–RBM4)
APPLIED / CAUGHT (2): RBM1 (omit scaffold cleanup) → success-self-clean test;
RBM2 (clean despite residue) → retained test. STRUCTURAL (2): RBM3 (broad-prefix —
cleanup uses the exact `code_base.parent`, proved nested-owned), RBM4 (ignore
failure + report PASS — status computed from real `Path.exists()`, a surviving
root reports `FAILED`). No security-relevant survivor.

## §12 Hard-kill scaffold cases
The deterministic run-bound root + the crash-persistent residue store (from B0-R2)
mean an abrupt kill after root/config/brief/provisioning/service-start/readiness
leaves a recoverable, exactly-owned root; recovery classifies conservatively via
the residue record + exact-ownership `recover` (B0-R2). No manual knowledge needed.

## Tests / gates
- R1 (`tests/test_stage2cb_b1_r1.py`): 15 passed (P1–P7, canonical name, cleanup).
- Targeted (R1 + driver + backend + operator_stack + gnosis_deployment + publisher
  client/pipe): **150 passed**, exit 0.
- F-17 regression: 298 passed, 1 skipped, 62 subtests, exit 0.
- PBM/RBM: 7/7 applied CAUGHT, 2 structural.
- Full suite: **1754 passed, 1 skipped, 306 subtests, PYTEST_EXIT_CODE=0 (GREEN)**.
- `mypy --strict src`: Success, 88 files (production unchanged). Ruff: clean.

## Guards
`OS PROVISIONING = NONE` · `PROVIDER CALLS = 0` · `LIVE CLAUDE CALLS = 0` ·
`src/gnosis diff = NONE` · `src/gnosis/trust/* diff = NONE` · historical provisioner
+ Stage-5/6/7/8 probes UNCHANGED · F-37 NOT STARTED · NVIDIA/NIM NOT PRESENT ·
cumulative live calls = 1 / remaining 4.

## Next
Narrow independent acceptance of the pipe-readiness + cleanup remediation. Only
after PASS is the B1 OS-real retry authorized (from the new R1 HEAD).
