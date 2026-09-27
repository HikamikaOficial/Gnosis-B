# Verification identity repair — work in progress

## Latest qualification checkpoint

Session 18848 completed: **22 passed in 57.66 seconds**, covering operator package
closure and two proof/publication/integration restart cases after recovery was
wired. Session 47975 also completed, but **did not pass**: 2188 passed, 72 skipped,
9883 successful subtests, and two failing subtests in 1909.03 seconds. Both failures
are the repository-own-untracked-files check encountering the generated embedded
Git repository and linked task worktree in `v1-relocated-git-20260927`. The fingerprint
function attempts to read these directory entries as files. No permissions were
changed and no test/evaluator/baseline is being weakened to accept them.

All **252** pinned source/test/script hashes still match b02f1cb, recorded at the
original checkout's `.gnosis/evidence/v1-pinned-b02f1cb-20260927/result-validation.json`.
The generated repositories remain preserved. The next full run will use the managed
candidate checkout, which does not contain those embedded test repositories. Its
result must be reported separately from the failed original-checkout run.

Completed worktree JUnit records are being preserved in the original checkout's
`.gnosis/evidence/v1-verifier-isolation-20260927/` before the candidate is pinned.
No Windows installation or account qualification has occurred.

## Recovery development checkpoint

`trust/check_recovery.py` now provides bounded forensic recovery from protected
verification intents. It validates the closed schema, deadline, runtime and
exact assigned output namespace; refuses duplicate JSON fields and redirected
or hardlinked output; skips attempts whose advisory lock is still held; never
overwrites retained output and never reconstructs a passing verdict.

Nine tests passed, including a separate Python process that calls `os._exit(77)`
after writing partial Worker output. The next process recovered those bytes;
recovery was idempotent. This is process-death/component evidence, not a real
dedicated Windows Worker kill. Mypy passed all 104 source modules; new-file Ruff
checks passed.

**Now wired:** WorkerCheckExecutor holds `attempt.lock` throughout its
intent/launch/wait/retention sequence, and canonical startup calls recovery
before executing checks. Tests exercise exclusion while the actual executor's
launch is in progress and prove that rebuilding canonical composition restores
missing retained output without launching code again. The combined factory,
executor and recovery suite passed **41 tests in 5.71 seconds**. Mypy again passed
all 104 modules; touched-file Ruff and diff checks passed.

Broader regression **23305 completed: 117 passed in 451.45 seconds**. Its JUnit is
`.gnosis/evidence/verifier-isolation-components.xml`; that run predates the final
startup-recovery wiring, which has the focused evidence above. Additional package
closure plus proof/integration restart checks are running as **18848**, JUnit
`.gnosis/evidence/verifier-recovery-integration.xml`. Full original pinned-source
regression **47975** remains live (last progress milestone 91%). Neither live run
is being reported as passed. Do not restart on observation timeout.

The pinned b02f1cb candidate is not ready for privileged production execution:
CommandVerifier and proof recapture currently run candidate commands under the
Director identity. A canary reproduced an outside-candidate write without
elevation or access to private files. Do not run candidate tests as administrator.

## Implemented in the managed development worktree

- A CheckExecutor protocol shared by CommandVerifier and evidence capture.
- Proof recapture forwards the very same assigned executor. A refused executor
  cannot fall back to a local subprocess.
- WorkerCheckExecutor uses the existing WorkerLauncher, sealed launch spec,
  finite deadline, cancellation callback and job closure. It reads bounded
  Worker outputs through validated handles and retains them in protected storage.
- Its wrapper runs under the Worker, using the assigned interpreter with -I/-B.
  The Director environment is not inherited; only named cache settings can be
  passed to the wrapper. This does not widen the LaunchSpec environment policy.
- Twelve executor component tests passed; type checking passed. These tests
  use a fake launcher, with one real wrapper subprocess under the test user,
  and do not qualify the real Windows identity boundary.
- The shared-boundary, verification and task-proof regression completed with
  48 passed in 278.87 seconds. The original full regression is still running.

## Remaining before this fixes production

### Latest development result

Canonical composition now replaces the supplied command verifier's executor
with WorkerCheckExecutor in both execution modes. Proof snapshots/caches and
integration staging use the Worker work plane; evidence and coordination remain
in their protected locations. Integration keeps its existing source-repository
lock. Compact hashed snapshot names avoid the Windows path failure observed
with the longer initial layout.

Two complete component paths (proof/publication and proof/publication/integration)
passed in 28.58 seconds. Their fake launcher executes the actual check wrapper
under the test user, so this is not Windows identity qualification. The production
factory suite also checks that the verifier and implementer share the assigned
Worker launcher and that retained verification output goes to protected state.

Each check now records a protected intent before launching. Launch/wait failures
retain available partial streams and are reported as unavailable verification
infrastructure, not as a verdict against the candidate. Timeout excerpts preserve
bytes. The executor generates its own per-run cache paths and ignores ambient
caller environment, including test options. Twenty focused executor/boundary
tests passed after these changes. Mypy passed for all 103 source modules and
touched-file Ruff/diff checks passed.

A broader worktree regression completed in session **23305**, with JUnit output
`.gnosis/evidence/verifier-isolation-components.xml`: 117 passing task proof/restart,
integration, composition and executor/boundary tests. See the top checkpoint for
subsequent recovery changes and the remaining live sessions.

The numbered list below describes the original repair plan. Items 1 and 2 are now
implemented and await the broader regression and real account qualification.
Item 3 now has launch/wait diagnostics and automatic forensic recovery after a
hard kernel kill. Recovery does not reconstruct a verification verdict or skip
required reruns. Real account qualification and final acceptance remain open.
The source is intentionally not repinned or installed yet.

1. Bind this executor in canonical composition, with the measured runtime,
   trusted argv resolution, scope checks, Worker output space and protected
   evidence destination. No optional local fallback in the production graph.
2. Place proof snapshots/caches and integration staging where the Worker has
   appropriate access while keeping checkpoint and evidence authority protected.
   Integration currently creates its staging worktree under the protected
   inbox integration root, so replacing the verifier alone is insufficient.
3. Preserve partial raw output and attribution on launch/wait failures and
   restart; review timeout/cancellation classification at every consumer.
4. Test real composition and proof/integration paths, then qualify the actual
   restricted Windows account, including denial of writes to protected state.
5. Rerun applicable regression, repin installation source/config, and only then
   revisit the cancelled installation. No installation was performed.

The original checkout remains frozen for regression session 47975, which tests
b02f1cb rather than this in-progress repair. No acceptance percentage has been
increased for the component work above.
