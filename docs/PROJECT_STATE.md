# GNOSIS Project State

**Status:** PHASE -1 COMPLETE; NINE KERNEL-HARDENING DIRECTIVES IMPLEMENTED; ADAPTER MILESTONE COMPLETE; INTEGRATION MILESTONE COMPLETE; RESULTS LAND ON THE SHARED BRANCH; MULTI-WORKER PLANE (QUEUE + BUDGET + ORDERING); RE-REVIEW AS EVIDENCE; WORKER SUPERVISION; THE PROBE HAS A CALLER; MULTI-CREDENTIAL ROTATION
**Target machine:** Nicol
**Phase:** 1 — Kernel hardening per archaeology directives
**Last update:** 2026-08-23 (F-34 closed; F-14 repaired twice and still open; the stale lines below are F-19..F-32, still open)

## Kernel hardening (post-Phase -1)

Archaeology Directives 1–5 are implemented, each unit adversarially
reviewed (multi-agent workflow + refutation verify) with all confirmed
findings repaired pre- or immediately post-commit:

- ADR-0004: `kernel.canonical` single hash contract; hash-chained
  `RunLedger` with fail-closed full-chain verification; frozen transition
  tables (commit 843a72e).
- ADR-0005: `kernel.lease` fenced expiring leases, NO STALE WRITE
  test-enforced (1e176a9).
- ADR-0006: `kernel.claims` durable CAS claims + `WorkAuthority` +
  `GrantHeartbeatPump`; engine write paths fenced (ed32fa2 + repairs in
  2c50a8c). Includes the first independent **Codex** adversarial review
  (FAIL verdict, 3 findings verified true and fixed — notably the
  no-verifier INVALID DONE gate). Raw transcript:
  `.gnosis/lab/kernel-reviews/`.
- ADR-0007: provenance-gated worktree lifecycle (8ec4bfd; 13/14 review
  findings confirmed and repaired, incl. destruction reordering and the
  autosave conflict-gate holes).
- ADR-0008: `kernel.convergence` review-convergence loop (ac76d89; dual review Codex+workflow, 9/9 findings confirmed and repaired — incl. verification flip-detection and strict consecutive-evidence stalemate counting; also fixed two latent git_evidence bugs).
- ADR-0009: governed execution isolation (0efd12a) — worktree-scoped
  execution for governed runs, ownership enforced at the run-store
  boundary, governance-aware orchestrator. Closes the ADR-0006/0007
  structural follow-ups. Dual review: 19 findings, all repaired (incl. a
  heartbeat-pump leak that made a task permanently unreclaimable).
- ADR-0010: strict replay + write-ahead intent (65cef20) — occurrence-aware
  strict-by-default replay and an intent journal that makes rewind safety a
  query. Dual review: 19 findings, all true, all repaired (two criticals
  reproduced: a string mode silently downgraded strict replay to a live
  call; unserializable metadata destroyed the row for a call that happened).
- ADR-0011: fail-closed policy engine + falsifiable enforcement matrix
  (c64b8da, repairs c26f84b). Dual review: 24 findings, all true — a one-
  character quote bypassed every path rule, and an unserializable payload
  made the gate raise instead of deny.
- ADR-0012: typed failure taxonomy wired end-to-end (9d963aa) — graded
  classification, RATE_LIMITED as a credential-scoped park state,
  recovery-as-reconcile. Codex found it was UNWIRED; fixed by wiring the
  engine's retry decision onto the classification, not by documenting it.
- L-0004: a refuted review finding resurrected as a real bug (shared
  FileLock instances) — refutation assumptions are now recorded.

## Adapter milestone (COMPLETE)

The four mechanisms that existed but nothing called. Directive 9's rule
governs the order of work here: **prefer wiring over documenting**.

- [x] **PolicyEngine → a real intervention point** (ADR-0013). The gate
  runs at `before_agent_run` before any process that could act on the
  repository or on the agent's behalf, again after kernel context is
  prepended, and again before every retry; refusals are durable evidence
  (`policy.decision` + classification + `escalations/` file). Enableable
  from `DirectorOrchestrator`, the path real briefs travel. **Two
  independent reviews, and both found the headline invariant false**: the
  workflow review (21 findings, adjudicated by hand after the verify
  phase died on quota) caught code intelligence shelling out before the
  gate and no production path being able to enable it; Codex then caught
  `git worktree add` still running first, retries riding the first
  attempt's authorization, and the identity not binding the workspace.
  All repaired. What cannot be enforced (rule purity, the opt-in gate) is
  recorded in the enforcement matrix rather than implied away. See
  L-0005..L-0010, D-018..D-020.
- [x] **`InteractionStore` → the real CLI runner** (ADR-0014).
  `ReplayingCLIRunner` records and replays actual runs byte-exact,
  reproducing the stdout/stderr files the engine reads, and is reachable
  from `recording_orchestrator()`. **Independent review returned FAIL
  with 8 reproducible defects**, all repaired — the critical one being
  that the cassette key was computed from the tree the recorded agent
  itself mutates, so no recording of a repo-mutating agent replayed past
  its first call (L-0012). The review also caught the test that "proved"
  the wiring using a stand-in incapable of exhibiting the failure
  (L-0013), and the evidence line being self-reported prose — hence
  `scripts/capture_evidence.py` and D-023.
- [x] **`ConvergenceLoop` → real reviewer/fixer adapters** (ADR-0015).
  New `gnosis/adapters/` package (nothing in `kernel/` imports it, which
  is what makes provider-neutrality checkable). Rule 9 is enforced twice
  at two honest strengths: edit tools withheld (the provider's promise)
  AND a before/after workspace fingerprint that refuses a reviewer which
  moved the tree (the kernel's evidence, recorded as SANDBOX_APPROX
  because detection is not prevention). An unreadable review raises
  rather than becoming a verdict nobody gave; an unreadable FIX report is
  inconclusive rather than `cannot_fix`, because `cannot_fix` ends the
  loop. **Codex review 2026-08-21: FAIL, 8 findings, all repaired** —
  including a rule-9 bypass reachable with nothing but an accent in a
  filename (`git status` C-quotes non-ASCII paths, and the failure to
  read one was stored as a *stable* value), an object quoted in prose
  parsing as a verdict, and duplicate JSON keys resolving in the
  author's favour. The earlier self-review found 3 real defects and
  missed these 8 — see L-0016.
- [x] **Hold/park plane + `boot_sweep` under a scheduler** (ADR-0016).
  `TaskScheduler` consults holds before a launch (a refusal PARKS, never
  fails), places a durable hold when a run classifies RATE_LIMITED, and
  sweeps stranded runs at boot. Self-review found `probe()` was inert —
  a PROBE row could never narrow an ACCOUNT hold under the
  most-restrictive rule — so the store now separates observations (which
  compete) from decisions (which supersede, with a reason). No
  independent review: both channels are unavailable.

Suite: **760 tests, all passing**; mypy strict clean (47 files); ruff at
the recorded backlog baseline (19 pre-existing findings in untouched
files, ratcheted down from 20; `.gnosis/state/lint_baseline.json` fails the run if it rises).
Captured transcript, not prose: `.gnosis/evidence/20260821T174016Z/`.

## Integration milestone (COMPLETE)

`GovernedPipeline.run_brief` (ADR-0017) is the path a real request takes
through the whole kernel: schedule (hold plane) → implement (policy gate,
worktree isolation, retries, typed classification) → converge (verify →
independent review → fix, bounded, with every reviewer and fixer launch
behind the same gate) → one `EngineerReport` whose status can only say
COMPLETED if convergence converged.

**Codex review: FAIL, 7 findings, all repaired** — two critical. Nothing
enforced that the reviewer was independent of the implementer
(`reviewer_id` was a label, and the test fixture used one agent for
both), and a crashing fixer stranded an already-consumed brief with no
report. Self-review separately found a rule 6 violation created purely by
composition: a rate limit hit by a review round never reached the hold
plane, so the next round launched into the same shut window. See L-0019.

## Integration of results (COMPLETE)

`WorkIntegrator` (ADR-0018) lands a converged task's worktree on a
**named** target branch, and only ever by fast-forward to a commit whose
MERGED tree already passed the verifier — the answer to constitution
rule 16. The headline test demonstrates the rule instead of asserting
it: two tasks fork from one base, one renames a function and updates its
own caller, the other adds a caller of the old name; git reports zero
conflicts and the merged tree raises ImportError, so nothing lands.

**Codex review: FAIL, 8 findings, all repaired or corrected** - two
critical. There was no designated target branch (it merged into whatever
was checked out, including a detached HEAD, while reporting the shared
branch had landed work), and the policy snapshot was taken before
`autosave`, so an approval for one path could authorise landing another.
The matrix's `post_merge_verification = HARD` was itself false and is
now two true claims: `verified_before_landing = HARD` (ordering) and
`semantic_correctness = IGNORED` (meaning). See L-0021, L-0022.

## Multi-worker plane (queue + budget)

`WorkQueue` (ADR-0019) is durable pending work whose OWNERSHIP is
delegated to the claims plane: every worker scans the same directory and
`WorkAuthority.acquire`'s CAS lets exactly one through. Proven by 6 real
threads racing on 24 briefs. `Budget` is the circuit breaker rule 8 named
and nothing implemented — wall clock and agent launches, durable per
brief.

**Codex review: FAIL, 7 findings, all repaired** - two critical. A crash
after the file move stranded a brief forever (found by self-review
first); and the FIX for it was itself wrong in one case, returning
already-completed work to `pending` to be re-executed. Also: a stale
grant could hand out work the worker no longer owned, and the budget was
per INVOCATION rather than per brief, so a park/resume cycle launched
agents without limit while each run looked bounded. See L-0023.

## Cross-task ordering (ADR-0020)

`plan_landings` orders converged tasks, and its real output is
`review_still_applies`: "converged" is verification AND an independent
review, and when the target moves only the verification gets re-run.
`LandingCoordinator` refuses a stale-review landing by default and the
pipeline routes landings through it.

**Codex review: FAIL, 9 findings, all repaired** - three critical. The
sharpest: `preview` returned the target's head as a task's base, so
"the base is stale" was structurally impossible to detect through the
module's own data path, and every test passed because they fed the
planner synthetic bases (L-0026). The pipeline also bypassed the
coordinator entirely, and a plan could be honoured after its head moved.

## Re-review as evidence (ADR-0021)

L-0027 said a review expires when its tree moves, and left only a
waiver. Now the integrator DERIVES staleness (fork point vs target head)
and runs an independent reviewer against the MERGED tree before the
fast-forward, using the same blocking rule convergence uses. Both halves
of convergence are re-established against the tree that lands.

**Codex review: FAIL, 5 findings, all repaired or recorded** - two
critical. `require_rereview` was a caller flag defaulting to False, so
the public API landed expired reviews silently (L-0028); and the
re-review was neither budgeted nor its refusals caught, while a comment
claimed otherwise. Self-review separately caught the pipeline assigning
the reviewer onto the shared integrator, which would have recorded every
later task's re-review under the first task's name (L-0029).

## Worker supervision and backoff (ADR-0022)

`drain` was a generator with no worker, no restart and no pacing.
`WorkerSupervisor` claims, runs, paces parks with a DURABLE exponential
`not_before`, and bounds itself against rule 8's full list. The design
question was authority, not retry: it may pace, stop and take work out of
circulation; it may not clear an attempt count or resurrect a blocked
brief.

**Shipped WITHOUT an independent review** — Codex refused with a usage
limit (reset reported 2026-09-20). The first unit since ADR-0016 with a
weaker evidence claim, and the ADR says so at the top. Self-review found
four defects, three repaired: a crash between the claims-plane call and
the file move ERASED a block decision and dropped a park's backoff
(L-0030), and a handler returning `None` was silently treated as a park
(L-0031). The first two are mutation-checked.

## The probe has a caller (ADR-0023)

ADR-0016 built `probe()` and invoked it from nowhere. Reproduced first:
an ACCOUNT hold on a window the kernel GUESSED admits nobody while it
stands and every queued resume one second after it elapses — and the
evidence that it was a guess vanishes with the hold, so the moment a
caller would want to probe there is nothing left to probe. So the probe
is claimed BEFORE the guess elapses, by exactly one caller (a
compare-and-set under one lock), with its own TTL rather than the window
it replaces, and a clean launch supersedes the hold.

**Shipped WITHOUT an independent review** — Codex still refuses on a
usage limit, re-checked at the start of this unit. Two units of review
debt now. Self-review found six defects; the one that mattered was that
the new caller went into `submit()`, which the pipeline never uses —
fixing "nothing calls it" with a caller nothing reaches (L-0033). A
concurrency test also passed with its guard mutated away, because the
race it was named after never occurred (L-0032).

## Multi-credential rotation (ADR-0024)

The last ADR-0016 residual. The scope was set by one check made BEFORE
designing anything: `Popen` was called without `env`, so no launch could
run as a different identity under any design — everything above it would
have been a decision plane with nothing underneath (L-0034).

A credential set is a **privilege boundary, not a pool**. Rules 25 and 26
are about crossing one, so the boundary is data the kernel checks:
rotation stays inside the primary credential's KIND unless another kind
is explicitly authorised, and an exhausted seat parks rather than
starting to bill. Secrets never enter the kernel — a credential names the
variables its value lives in.

**Shipped WITHOUT an independent review** (Codex usage limit) — three
units of debt now. Self-review found five defects, two critical: the
launch could not bind a credential at all, and once it could, the child
still had every OTHER credential's secret in its environment, so an agent
could spend the key the kernel had refused to select (L-0035).

## Review debt paid: three FAILs, 47 findings (2026-08-21)

Codex is rate-limited until 2026-09-20, so ADR-0022, ADR-0023 and
ADR-0024 had shipped self-reviewed. Rather than add a fourth unreviewed
unit they were reviewed by independent read-only agents in clean
contexts — a weaker channel than a different model, and each ADR header
says so.

**All three returned FAIL.** 47 findings against the 14 the self-reviews
had found; six criticals none of them saw (L-0041). The worst was not in
the new code at all: `WorkAuthority.sweep()` had **no production caller**,
so every recovery claim in this repo that depends on a claim ageing out
of ACTIVE was inert, and the suite was green because every test swept by
hand (L-0036). The second worst was a probe whose failure mode left the
credential MORE open than not probing at all (L-0037).

28 findings repaired and verified; 15 still open and listed in the
addenda rather than carried silently. The two closed since: concurrent
`recover()` — where the obvious fix was wrong and a test caught it
(L-0042) — and unpaced crash recovery. Rule 9 verified mechanically: the
tree fingerprint was identical before and after the reviews.

## Traceability audit, and F-34 — repaired four times, CLOSED on the fourth review (ADR-0025, 2026-08-22)

A read-only audit of the whole V1 surface — `docs/V1_TRACEABILITY_AUDIT.md`,
frozen at commit `83ae84e` and never edited afterwards — produced 42
findings. It refuted two of `PROJECT_REPORT.md`'s own claims (the
"repeated identical failure" and "no-diff loop" scenarios ARE tested;
"invalid state transition" is tested too, but only on the one state plane
that does not survive the process), and it found one defect no previous
review had.

**F-34.** The constitution's second rule — no task reaches DONE without
evidence — was enforced inside `if authority is not None`. The default
`DirectorOrchestrator` supplies no authority, so on the path D-018 calls
"the path real briefs travel" the rule was off, and the transition read
`verification_result.passed if verification_result else True`. That does
not mean "no verifier configured"; it means ABSENCE OF EVIDENCE IS
SUCCESS. Two lines produced a COMPLETED brief that had proved nothing.

Now: `TaskStateMachine.complete()` is the single authority for
`TaskState.COMPLETED` — `completion_is_evidenced` is the predicate it
applies, and calling it "the authority" was the round-1 overclaim
(L-0044); `execute_task` refuses a verifier-less task before it
launches anything; `run_pending` refuses before it consumes a brief.
`tests/test_no_invalid_done.py` is the first suite in this repo named
after one of the four invariants, and the mutation check that proves it
bites is CAPTURED (`mutation-check.f34.txt`) rather than asserted —
restoring the old expression turns 11 tests red across all three heights.

Evidence: `.gnosis/evidence/20260822T005432Z/` — **781 passed**, mypy
strict clean over 55 files, ruff at the 19-finding baseline exactly,
captured against a CLEAN code tree at `29d3666` (tree `cf7a2657`), with
`f34-tree-binding.json` recording `content_fingerprint()` before and
after the run.

**Four independent reviews: three FAILs, then a PASS.** Round 1 (Codex,
FAIL PARCIAL): the state machine itself walked
`VERIFYING -> COMPLETED` for anybody who asked, so the invariant was a
property of one caller. Round 2 (FAIL PARCIAL): `state` and
`completion_evidence` were public attributes, and the engine's report
printed `PASSED` for a `VerificationResult(passed=1)` the authority had
just refused. Round 3 (**FAIL CRÍTICO**): `CompositeVerifier` read its
members with `all(r.passed for r in results)` and returned a brand-new,
well-formed `VerificationResult(passed=True)` — so every strict reader
downstream was correct about evidence that had been laundered one frame
earlier — and `CompositeVerifier("empty", [])` passed on `all([]) is
True`, a DONE minted by running no check at all. The three truthy readers
round 2 named and deferred (`convergence.py`, `integration.py`,
`cli_review.py`) were still live.

The repair makes the third verdict representable as a TYPE:
`MalformedEvidence`, which is not a `VerificationResult`, so
`verification_verdict` classifies it MALFORMED by construction.
`Verifier.run` returns `Evidence`, which is what let mypy — rather than a
grep — enumerate every production reader. `CompositeVerifier` refuses an
empty collection at construction, classifies members only by verdict, and
never converts a malformed member into a pass or into an ordinary
failure. `ConvergenceLoop`, `WorkIntegrator`, `cli_review` and
`GovernedPipeline` each fail closed on MALFORMED with a differentiable
reason. Nine mutants, none survived — and the mutation check is now a
committed script (`scripts/mutation_check.py`) rather than a hand-made
transcript, so the next reviewer can re-run it. Evidence:
`.gnosis/evidence/20260822T181937Z/` — **874 passed**, mypy strict clean
over 55 files, ruff at the 19-finding baseline exactly, captured against
a clean tree at `9c6064c` (tree `baca7d24`), with
`f34-round3-tree-binding.json` recording `content_fingerprint()` strictly
before and after the run.

**Round 4 (2026-08-22): PASS — and F-34 is CLOSED.** The fourth
independent review read code `9c6064c` against evidence `f02e18e` and
verified for itself, without accepting the author's transcript, that:
both critical reproductions fail closed (a composite with a member
returning `passed=1` produces `MalformedEvidence` and the engine finishes
FAILED / PARTIAL with the problem recorded); an empty composite raises
`EmptyCompositeError` at construction; convergence, integration, the
pipeline and `cli_review` all decide on the strict verdict; and **no
productive reader of `.passed` decides outside `verification_verdict()`**
— the claim rounds 1, 2 and 3 each made and each got wrong at a different
height, now checked and empty. 249 tests and 39 subtests, targeted,
passed in the reviewer's own run. No new findings in scope.

F-34 closes by the rule this project set for itself and then had to apply
against its own earlier closure: a finding is resolved when an
independent review returns without findings, not when it looks resolved.
It is **1 of 43** — the frozen audit has 6 PASS items, 1 closed finding
and **36 open**. L-0044..L-0048 record the mechanisms; the process change
that made round 4 cheap is `scripts/mutation_check.py`, committed with
its mutants as data so a reviewer re-runs the claim instead of reading
it.

**Not closed, and named so the closure of one row is not read as the
closure of the surface around it:** F-36 (there is no `ProofPacket`),
F-14..F-18 (`capture_evidence.py` still does not bind bytes — all four
rounds worked around it with an external tree binding, and a workaround
repeated four times is a finding, not a method), the `PYTHONUTF8=1`
environment precondition that nothing in the repo enforces, and F-33 with
the thirteen capabilities that remain correct as modules and unreachable
as a program.

**Scope discipline: F-34 only.** The other 36 open findings are
untouched across all four passes — 43 items in the frozen audit, of which
6 are PASS and not defects (F-06, F-09, F-11, F-29b, F-41, F-42) and 1 is
now closed (F-34). That
includes the documentation drift THIS FILE still carries
(F-19..F-32: the stale 164-test line and mypy file count below, the
resolved-vs-pending Codex contradiction, the `src/gnosis/` "empty
scaffold" claim ADR-0002 already settled) and the absence of a production
entry point (F-33). The living matrix is `docs/V1_COMPLIANCE_MATRIX.md`;
this unit changed exactly one of its rows.

**Independent review: DONE, verdict FAIL PARCIAL (Codex, 2026-08-22).**
The reachable production route was genuinely closed. What was NOT closed
— and what ADR-0025 and the V1 matrix both overdeclared — is that the
invariant sat at the lowest point authorising COMPLETED: a bare
`TaskStateMachine` still walked `VERIFYING -> COMPLETED` with no evidence,
and `test_happy_path` asserted that it did. `6c4859a` moves the gate into
the state authority: `transition()` refuses `COMPLETED` outright and
`complete(verification)` validates a real `VerificationResult`, never a
caller-supplied flag. Evidence `.gnosis/evidence/20260822T142519Z/` —
800 passed on a clean tree at `6c4859a`, two mutants captured. See
ADR-0025's addendum and L-0044.

**Second independent review: FAIL PARCIAL again (2026-08-22).** The
gated methods held; two defects of the same closure did not.
(1) `state` and `completion_evidence` were still PUBLIC attributes, so
`sm.state = TaskState.COMPLETED` reached a terminal DONE with no
evidence, past every guard — a lock on each door and no wall (L-0045).
(2) With a `VerificationResult(passed=1)` the authority correctly refused
the DONE and the REPORT of that same task printed
`verification=("malformed: PASSED",)` with an empty problems list,
because the predicate read `passed is True` and the printer read
`if passed` — two independent readings of one field (L-0046). Both are
repaired: the storage is private behind read-only properties, and
`verification_verdict()` is now the single reader, with a third answer
(MALFORMED) that the ledger, the report and the completion predicate all
derive from. Six mutants captured, none survived. Evidence
`.gnosis/evidence/20260822T162729Z/` — 822 passed (60 subtests) on a
clean tree at `1591aa7` (tree `67d2bb9c`), mypy strict clean, ruff at the
19-finding baseline with nothing added. A third independent review was
outstanding at that point; it ran, returned FAIL CRÍTICO, and its repair
and the fourth review's PASS are recorded above. Named and NOT repaired
at the time, as candidates for that third review — all three were in fact
repaired in `9c6064c` and verified by round 4: the
same truthy read of `passed` remains in `kernel/convergence.py` (3
sites), `kernel/integration.py` and `adapters/cli_review.py`, which are
decision logic in other subsystems; none can forge a COMPLETED, but
"cannot forge a DONE" is weaker than "cannot be misread".

## F-14 — the evidence surface binds bytes, and now the interval too (ADR-0026 + addendum, 2026-08-23)

`scripts/capture_evidence.py` recorded HEAD and `git status --porcelain`.
Status is a state and a NAME: two different dirty trees that touch the
same files produce a byte-identical bundle, and `git diff --stat` gives
the same counts for any same-length edit. Nothing in a bundle said WHICH
bytes passed the suite. The audit's receipt for that is the bundle this
project cited as proof of "760 tests passing": HEAD `92fe18ab`, four ` M`
paths, contents unrecoverable. Agreement with a later commit is an
inference from the commit, not a proof from the evidence.

The primitive was already here and this was the last surface not using
it. `probe_tree_identity()` wraps `content_fingerprint()` — HEAD, the
patch against it, and the sha256 of every untracked file's bytes per path
— and the identity is taken BEFORE the first check and again immediately
AFTER the last. Both complete fingerprints go into `SUMMARY.json`. Two
identical available fingerprints, or the capture is not evidence: a tree
that moved is `TREE_MUTATED` (exit 2) and a probe that could not answer
is `IDENTITY_UNAVAILABLE` (exit 3), both fail closed whatever the tests
said, and an unavailable PRE identity means nothing runs at all. Failed
checks (exit 1) and lint debt within the recorded baseline (exit 0) stay
distinct from both, because the operator response differs. The bundle is
built outside the repository and published after the post fingerprint, so
evidence cannot invalidate itself by existing. `all_passed` is gated on
the binding, with the ungated fact kept beside it as
`checks_all_zero_exit` — L-0046 applied to this surface before someone
had to find it again.

All four ADR-0025 rounds wrote an external `tree-binding.json` by hand
around this script. That workaround is now unnecessary.

**First independent review (Codex, 2026-08-23): FAIL CRÍTICO.** The
identity was right at both ends and the claim built on them was not. Two
fingerprints prove the tree was the same at two INSTANTS; the checks run
in the INTERVAL. A check that changed a covered file, read the change and
restored the bytes, the size and the timestamps produced
`evidence_valid: true` — and the 36 tests could not have caught it, since
every mutation they make is still visible at the post fingerprint, so all
of them are found by an endpoint comparison and none exercises
change -> read -> restore.

Nothing sampled closes that: polling, `mtime`, `git status` and a third
fingerprint are all samples of a moment, and a transient change lives
between moments. So the interval got its own authority.
`kernel/write_observer.py` streams every change under the tree from
`ReadDirectoryChangesW` — name, directory, attributes, size, last write,
creation, security — armed BEFORE the pre fingerprint and closed AFTER
the post one, so both endpoints sit inside the observed window. A stream
that could have missed something is not a clean stream: an overflowed
kernel queue fails closed, and rather than waiting out a timer for the
tail, `stop()` writes a barrier file and blocks until it OBSERVES that
barrier — notifications arrive in order, so seeing it proves everything
earlier was already delivered. Two new outcomes with their own exit
codes: `INPUTS_MUTATED` (4) for a covered input written during the run
whatever the endpoints say, and `UNOBSERVED` (5) for an interval that
could not be watched completely. `evidence_valid` is now the conjunction.

Legitimate writes stop being false positives by being moved rather than
forgiven: `PYTHONPYCACHEPREFIX`, `MYPY_CACHE_DIR`, `RUFF_CACHE_DIR` and
`PYTEST_ADDOPTS=-p no:cacheprovider` send every cache to a scratch
directory outside the tree. What remains is judged by rule, and writes
under `.git/` are COUNTED as machinery rather than judged, because git
rewrites its index while merely reading the tree.

**F-14 is still NOT closed.** It is repaired twice now, tested (56 tests,
3 subtests) and mutation-checked (thirteen mutants, none survived,
`scripts/mutation_check_f14.py`), and it awaits a SECOND independent
review. The first one found this in a unit that had 36 tests, nine
mutants and a clean self-review. It closes when a review returns without
findings.

**Overlap recorded, not claimed:** F-15 (the unused primitive) is what
this script now uses; F-16 (capture order) no longer affects the binding
though the command list is unchanged; F-17 now has HEAD, the status
digest and both identities inside `SUMMARY.json` but still **no hash
chain and no signature**; F-18 is untouched. None of them are marked
repaired. The addendum adds one more overlap, also unclaimed: `.git/`
writes are counted and not judged, so a hook installed during a capture
is outside this boundary and inside F-17's.

**The baseline was not green at the start of this unit, and not because
of it.** The full suite at `aea62b0` returned 1 failed, 873 passed:
`test_work_queue.py::TestACrashedWorkerLosesNothing::`
`test_recovery_never_takes_a_brief_from_a_live_worker`. The fixture
`_short_lived()` sets a 50 ms lease TTL, and that test needs the lease
alive across four file-locked round-trips while its neighbours sleep
150 ms precisely to let it expire. Reproduced at 1 failure in 5 runs in
isolation; mypy clean, ruff at the 19 baseline in the same run. A
pre-existing flaky test, left alone because this unit is scoped to F-14
and because making a test deterministic is a change to `tests/` that no
F-14 evidence should carry.

## Fixed locations

- Project: `C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi`
- External repositories: `C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi\external\repositories`

## Inherited baseline (pre-pack milestones, committed M0→M3)

The repo already contains a working kernel baseline built in an earlier
session: `gnosis/` package (state machine, ledger, leases via file locks,
worktrees, CLI runner, verification, recovery, code-intelligence wiring,
memory contract + router) with a 164-test suite, plus milestone evidence
in `docs/M*.md` and `.gnosis/lab/*/results/`. The v0.3 environment pack
was extracted on top of that baseline (commit 8955932). Note the layout
conflict pending decision: real code lives in `gnosis/`, the v0.3
constitution names `src/gnosis/` (currently an empty scaffold).

## Target-machine gates

- [x] Bootstrap executed (doctor/inventory state present).
- [x] Claude Code Fable 5 + Ultracode validated (this session runs on it).
- [x] Codex CLI installed (0.148.0) and authenticated ("Logged in using ChatGPT", 2026-08-19 evening). Usage quota exhausted until 2026-08-20; adversarial review parked as RATE_LIMITED until then.
- [x] External repos inventoried: 27/130 resolved locally (all Tier S/S+ except the license-blocked one; report: `.gnosis/state/clone_report.json`).
- [x] M3 installed/configured/smoke-tested (uv tool, PYTHONUTF8=1, env-pinned roots; ADR-0001).
- [x] ZMem installed/configured/smoke-tested (uv tool; governance loop revalidated on 0.1.17).
- [x] Cross-session Memory Fabric test passed (`tests/integration/test_memory_fabric_smoke.py`, 3/3; docs/research/MEMORY_FABRIC_STATUS.md).
- [x] Tier S architecture archaeology completed: 23 repos analyzed (10 deep + 3 group sweeps, 14 agents, read-only) → `docs/research/REFERENCE_REPOSITORY_FINDINGS.md` (summary table, 9 kernel architecture directives, contradictions/open questions, per-repo findings with evidence labels).
- [x] Initial ADRs confirmed (ADR-0001; D-017; L-0001..L-0003).
- [ ] Kernel implementation (Phase 1 continuation) begins after archaeology.

## Suite status

- 164 unit/contract tests + 3 memory-fabric integration tests, all passing
  (`uv run --no-project --with pytest --with pytest-asyncio python -m pytest tests/`).

## Known open items / caveats

- Codex login pending (human-only step) — until then no independent Codex review.
- Docker absent (LOW; sandbox/integration later).
- cass_memory_system: never clone/copy/analyze — license bars Anthropic-affiliated use.
- zmem 0.1.17 `status`/`doctor` crash on Windows (diagnostic-only; use `audit health`).
- m3 embedding tier unconfigured (FTS fallback); `m3 setup` deliberately not run.
- Bernstein clone required `core.longpaths=true` (now set globally).
- `security-audit/` contains non-GNOSIS leftovers (Minecraft-skin audit logs, 16MB) — gitignored, awaiting operator decision to delete/move.
- MCP servers for both engines are declared in `.mcp.json`; they attach on next Claude Code session approval.
