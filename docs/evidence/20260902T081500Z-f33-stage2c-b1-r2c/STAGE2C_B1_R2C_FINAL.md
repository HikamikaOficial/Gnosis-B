# F-33 Stage 2C-B1-R2C — Windows Named-Pipe Readiness Observation

Harness/test/evidence only. Fixes the blocker the OS-real diagnostic run established:
`READINESS OBSERVATION FAILURE`. **No Publisher/protocol/F-17/topology/ACL/runtime/
identity/pipe-name/timeout change; no OS provisioning; no provider call.**

## Diagnostic-run finding (carried in)
OS-real run (baseline 06b948a): service `GnosisPubS2CBProbe` was **RUNNING**
(exit_code null), yet the readiness probe raised on poll 1
(`terminal_reason=observation-error`, elapsed 0.0). The old harness observed the
pipe with `Path(r"\\.\pipe\gnosis-s2cb-probe").exists()`, which **raises** on a Win32
pipe path — so the actual pipe state was never determined. Not a proven Publisher
failure; a broken observation method.

## §1 Production client connection semantics (archaeology)
`gnosis.director.publisher_client.PipePublisherClient._round_trip` (publisher_client.py:102-131):
1. `WaitNamedPipeW(pipe_name, connect_timeout_ms=5000)` — bounded wait for the
   single-instance server to be free; failure → "publisher service unavailable"
   (fail closed).
2. `CreateFileW(pipe_name, GENERIC_READ|WRITE, share=0, OPEN_EXISTING, …)`; invalid
   handle → error with `GetLastError()`.
3. `WriteFile`/`ReadFile` bounded, then `CloseHandle`.
The client's **own availability gate is `WaitNamedPipeW`**. It opens a handle only
after WaitNamedPipeW succeeds; with `share=0` on a single-instance server a probe
`CreateFileW` would *consume* the instance — so a sacrificial connection is unsafe.

## §3/§4 Selected readiness API — `WaitNamedPipeW`
The observer uses **`WaitNamedPipeW`**, the exact primitive the production client
gates on. Chosen over a sacrificial `CreateFileW` because it never opens a handle
and therefore cannot consume/disrupt the single-instance server, while faithfully
answering the readiness predicate ("an instance is available to connect"). `READY`
== WaitNamedPipeW success == the state from which the client proceeds.

## §7/§9 Canonical pipe + busy semantics
The full canonical name `\\.\pipe\gnosis-s2cb-probe` is passed to `WaitNamedPipeW`
**verbatim** — never re-prefixed, stripped, or routed through `pathlib`. Busy
(`ERROR_SEM_TIMEOUT`/`ERROR_PIPE_BUSY`) is represented as **endpoint_present=True,
connectable=False** → transient not-ready (bounded polling continues), consistent
with the production client which waits on a busy pipe. `READY` is asserted only on
WaitNamedPipeW success (connectable), not on mere existence.

## §5/§6/§8 Win32 result / error mapping & structured result
| Win32 outcome | terminal | endpoint_present | connectable | class |
|---|---|---|---|---|
| success | ready | true | true | READY |
| ERROR_FILE_NOT_FOUND (2) | not-ready→timeout | false | false | transient (absent) |
| ERROR_SEM_TIMEOUT (121) / ERROR_PIPE_BUSY (231) | not-ready→timeout | true | false | transient (busy) |
| ERROR_ACCESS_DENIED (5) | **observation-error** | null | false | fail closed (never READY) |
| ERROR_INVALID_NAME (123) | **observation-error** | null | false | fail closed |
| any unmapped error | **observation-error** | null | false | fail closed |

Structured `_last_readiness` now also carries `observation_api`, `win32_error_code`,
`win32_error_name`, `endpoint_present`, `connectable` (no secrets). Transient
absence/busy is distinguished from an observation failure; an unexpected error is
**never** an ordinary not-ready.

## §3 pathlib probe removed
`WindowsRealOperations.pipe_ready` no longer uses any filesystem-existence check for
the pipe; it constructs `NamedPipeReadinessObserver(pipe_name)` and passes
`observer.observe` to the unchanged `wait_pipe_ready`. Enforced structurally
(`test_pathlib_probe_removed`, R1 `test_real_pipe_ready_uses_exact_path_not_reprefixed`).

## §10/§11 Bounds & liveness unchanged
`timeout_s=15.0`, `poll_s=0.25`, monotonic clock, and the R1 loop
(check-alive → observe → ready/transient/observation-error → bounded retry) are
byte-for-byte unchanged; service death still fails fast. No timeout increase.

## §12 NP1–NP10 (`tests/test_stage2cb_b1_r2c.py`, 18)
NP1 available→READY; NP2 not-created→transient→timeout (bounded polls); NP3
busy→present-not-connectable→timeout; NP4 covered by NP2/NP3; NP5
access-denied→observation-error (never READY); NP6 invalid-name→observation-error;
NP7 unexpected→observation-error; NP8 canonical name passed verbatim; NP9
service-dies→service-died; NP10 delayed-ready after N polls→READY. Plus real-backend
wiring (win32 detail carried; bounds unchanged) and a raising `wait_fn`→
observation-error.

## §14 NPM1–NPM8 — all CAUGHT (`mutation_harness_npm.py`, `npm.txt`)
NPM1 restore pathlib probe; NPM2 any-error→not-ready; NPM3 access-denied→READY;
NPM4 invalid-name→transient; NPM5 reprefix/mangle name; NPM6 ignore service death;
NPM7 unbounded wait; NPM8 invert busy→READY. **8/8 CAUGHT.** No observation-truthfulness survivor.

## §15 Production-client consistency
`test_ready_only_on_wait_success`: for every non-success Win32 outcome the observer
returns False or raises — **never** READY — so it cannot claim a state the client
cannot use. Both the observer and `PipePublisherClient` use `WaitNamedPipeW`.

## §16/§17/§18 No Publisher change; R2A/R2B and R1/R1.1 regression
Publisher server, protocol, and `PipePublisherClient` are **byte-identical**
(`src/gnosis` diff NONE). Service postmortem, service exit code, access UNKNOWN
semantics (no overclaim), topology NOT-PROVEN, diagnostics-before-rollback, and
rollback-on-diagnostic-error are unchanged: ADM 6/6 CAUGHT, DM(R2B) 6/6 CAUGHT.
R1/R1.1 (canonical pipe, 15s bound, service-liveness, auto-cleanup, residue NONE,
PBM/RBM) unchanged — the only R1 test touched was the structural pipe-observer
assertion, updated to the observer (intent — exact path, no reprefix — preserved).

## §19–§21 Failed-readiness / observation-error / delayed-ready replays
True absence for the full bounded interval → **timeout** (not observation-error),
NP2. An unexpected Win32 failure / raising probe → **observation-error**, NP5/
`test_raising_wait_fn_fails_closed` (the historical false occurrence is fixed while
the diagnostic category is preserved). Delayed availability → READY without restart
or timeout extension, NP10.

## Tests / gates
- R2C: 18 passed. Targeted (R2C+R2B+R2A+R1+driver+backend+publisher client/pipe/service):
  **183 passed, 80 subtests, exit 0** (`targeted.txt`).
- F-17 (provisioner + layout): 27 passed, exit 0 (`f17_regression.txt`).
- NPM 8/8 CAUGHT; ADM 6/6; DM(R2B) 6/6.
- Full suite: `full_suite.txt` (`PYTEST_EXIT_CODE` direct; known work_queue flake
  governed separately — a red run stays red).
- `mypy --strict src` Success, 88 files; ruff (changed) clean (`static_gates.txt`).

## §22 Source freeze
Changed: `scripts/stage2cb_ops.py`, `tests/test_stage2cb_b1_r2c.py`,
`tests/test_stage2cb_b1_r1.py` (structural assertion). `src/gnosis` = NONE;
`trust/*` = NONE; historical provisioner/layout/winapi UNCHANGED; Stage-5/6/7/8
probes UNCHANGED (`freeze.txt`). `scripts/stage2cb.py` NOT changed by R2C.

## Guards
`OS provisioning = NONE` · `provider calls = 0` · `live Claude calls = 0` ·
cumulative live calls = 1 / remaining 4 · topology root cause NOT-PROVEN.

## Outcome / next
Named-pipe readiness is now observed with the production primitive; the false
observation-error is fixed while a genuine observation error remains diagnosable.
Recommend narrow independent acceptance, then ONE OS-real B1 retry to establish the
**true** Publisher pipe state (READY, or a genuine failure class). Do not close F-33;
no topology remediation authorized.
