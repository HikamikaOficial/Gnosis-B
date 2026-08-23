# ADR-0026 — Evidence that cannot name its own bytes is a transcript, not proof

- Status: ACCEPTED
- Date: 2026-08-22
- Repairs: **F-14** (`docs/V1_TRACEABILITY_AUDIT.md`) — and F-14 only.
- Independent review, round 1 (Codex, 2026-08-23): **FAIL CRÍTICO** — the
  two fingerprints proved the endpoints and not the interval between
  them, so a check that changed a file, read the change and restored the
  original bytes produced `evidence_valid: true`. Repaired in addendum 1.
- Independent review, round 2 (2026-08-23): **FAIL CRÍTICO PROVISIONAL** —
  the barrier proves that generated notifications were delivered, not
  that every modification generated one. Reproduced: a write through a
  memory-mapped view notifies nothing, so a check consumed mutated bytes
  inside a bundle that certified itself. Repaired in addendum 2 by making
  the covered inputs unwritable instead of merely watched.
- **A third independent review is OUTSTANDING**; F-14 stays OPEN in
  `docs/V1_COMPLIANCE_MATRIX.md` until one returns without findings. Two
  reviews have now found something this unit's own tests and mutants did
  not.
- Tests: `tests/test_evidence_binding.py` — **65 tests, 3 subtests**
  (36 in the first delivery, 20 added by addendum 1, 9 by addendum 2).
- Mutation check: `scripts/mutation_check_f14.py` — **sixteen mutants,
  none survived** (nine, then four, then three), declared as data so a
  reviewer re-runs the claim rather than reading it.
- Break attempts: `scripts/probe_f14_boundary.py` — six cases, committed
  and re-runnable, containing the defect and its closure side by side.
- Evidence: `.gnosis/evidence/20260822T212531Z/` — **910 passed, 62
  subtests**, mypy strict clean over 56 source files, ruff at **19
  findings against a baseline of 19** (0 added). Captured against a CLEAN
  tree at commit `985023c`, tree
  `75cb37715c2040fdc65c56c04ee552fb4f9bbb46`. This is the first bundle in
  the project whose own `SUMMARY.json` states the identity of the tree it
  ran against: `320dfc5ccebe8904194c78c474af7f1295d637f92f27805ae33555c520fcbf7c`,
  before and after, `BOUND`, drift empty.
- Scope: F-14 only. Of the 43 items in the frozen audit, 6 are PASS, 1 is
  closed (F-34) and 36 are open. This unit closes none of them — F-14
  included, which remains open pending review.

## Context

The audit's answer to "can this project prove which bytes passed its
tests?" was no.

`scripts/capture_evidence.py` recorded two things about the tree: `git
rev-parse HEAD` and `git status --porcelain`. Status prints `XY <path>` —
a state and a NAME. Two different dirty trees that modify the same files
produce a byte-identical bundle, and `git diff --stat` produces identical
counts for any same-length edit. There was no tree hash, no diff and no
content digest anywhere in the bundle.

The finding came with a receipt. The bundle this project cited as proof
of "760 tests passing" (`.gnosis/evidence/20260821T174016Z/`) records
HEAD `92fe18ab` and four ` M` paths. The suite ran against a dirty tree
and nothing in the bundle recovers those bytes. That they probably match
what was committed in `edec96e` is an inference **from the commit**, not
a proof **from the evidence** — and an evidence surface that has to be
corroborated by the thing it exists to corroborate is not one.

Two facts make this the finding to repair first among F-14..F-18. The
primitive was already in the repository: `content_fingerprint()` in
`kernel/git_evidence.py`, used by the engine, the integrator, the review
adapters and the replay runner, and never by the evidence script. And
every one of ADR-0025's four rounds had to write an external
`f34-round*-tree-binding.json` BY HAND around this script to say what the
script should have been saying itself. A workaround performed four times
is not a method.

## Decision

### Identity is content, and it is taken twice

`probe_tree_identity()` wraps `content_fingerprint()`: HEAD, the patch
against it (staged and unstaged, tracked files) and the sha256 of every
untracked file's bytes, listed per path. Both fingerprints — complete,
not summarised — go into `SUMMARY.json`, so a reviewer can re-derive the
digest by hand from what is written down.

The first is taken before the first check runs, the second immediately
after the last one finishes. One fingerprint proves nothing about a tree
that moved underneath a 500-second suite, and a fingerprint taken only at
the end — which is what the old command order produced — describes the
tree the suite LEFT, not the one it ran against.

The identity discloses nothing. Only hashes are recorded, so this repo's
own untracked entries, `.stfolder/syncthing-folder-c9ceae.txt` and
`PROJECT_REPORT.md` — pre-existing, and not to be deleted or added to
`.gitignore` — are part of the identified tree without their contents
appearing anywhere in the bundle. A test asserts exactly that over
whatever untracked entries the working tree actually has.

### Four outcomes, four exit codes

The distinction is not cosmetic. The operator response differs, and
collapsing any pair of these is how a real failure gets read as a known
one.

| Situation | Recorded as | Exit |
|---|---|---|
| every check exited 0 | `ALL_CLEAN` | 0 |
| ruff non-zero, at or below the recorded baseline | `WITHIN_LINT_BASELINE` | 0 |
| a check failed, or lint debt rose above baseline | `FAILED` / `NEW_LINT_DEBT` | 1 |
| the tree changed during the capture | `TREE_MUTATED` | 2 |
| the identity could not be taken | `IDENTITY_UNAVAILABLE` | 3 |

`IDENTITY_UNAVAILABLE` dominates and fails closed: a probe that could not
answer must never read as "nothing changed", or breaking the probe
becomes the way to defeat the check. An untracked file whose bytes
`content_fingerprint` could not read is inside that refusal — a file that
was never hashed is not covered by the identity, and accepting it would
put the same defect one layer down. If the PRE identity is unavailable,
**nothing runs at all**: spending 500 seconds to produce a transcript
that could never be attributed is not caution.

### The summary states one thing, and the raw facts sit beside it

`all_passed` and `gates_clean` are gated on the binding. A summary that
reads `true` while the gate refused the evidence is where a reader stops,
and this project has shipped exactly that bug at a different height with
an independent review having to find it (ADR-0025 round 2; L-0046). The
ungated fact is not deleted, it is renamed: `checks_all_zero_exit` says
what the commands did, `checks_verdict` classifies them, every result
keeps its own `exit_code` and `outcome`, and `verdict` reads
`INVALID EVIDENCE: …` in the two cases where the transcript cannot be
attributed to a tree.

A capture with no checks raises `EmptyCaptureError`. `all([])` has cost
this project one critical finding already; a bundle that ran nothing must
not be able to report a clean run.

### The bundle is not part of the tree it measures

`.gnosis/evidence/` is tracked, so a bundle written in place is an
untracked change in the tree the post fingerprint is about to read: the
capture would report that the tree moved, and it would be right — about
itself. The bundle is therefore built in a temporary directory OUTSIDE
the repository and published, by copy and never over an existing
directory, after the post fingerprint is taken.
`bundle_staged_outside_repo` records that this happened, and a test
proves the choice is load-bearing by staging inside a repository and
watching the capture invalidate itself.

## Consequences

### Accepted

- The evidence script now imports the kernel. It was the last surface in
  the repo still deciding by prose, and the primitive it needed was three
  modules away.
- A capture can now fail for a reason that has nothing to do with the
  code, and that is the point. It will be inconvenient the first time a
  background process writes into the tree mid-suite.
- Exit codes 2 and 3 are new. Anything reading only "zero or not" is
  unaffected.
- The publication step is the one moment the tree changes without the
  capture objecting, because it happens after the post fingerprint by
  construction. `tree_identity.covers` states that in the bundle rather
  than leaving a reviewer to notice it.

### Not fixed here, and named rather than implied

F-15..F-18 are **not repaired and not marked repaired**. What this unit
touches of each is recorded so the next reviewer can measure the overlap
instead of guessing at it:

- **F-15** (the primitive exists and is unused): this script now uses
  `content_fingerprint()`, which is the correction F-15 suggested.
  Whether that is the whole of F-15 is for an independent review to say;
  the finding is about the evidence surface and this unit changed one
  script.
- **F-16** (capture order): the binding no longer depends on the order of
  the command list, because the pre fingerprint is taken before anything
  runs. The list itself is unchanged — `git-head` and `git-status` still
  execute last and `git-status.stdout.txt` is still a post-suite
  artifact. Partial overlap; not repaired.
- **F-17** (tamper-evidence): `SUMMARY.json` now carries HEAD, the status
  digest and both complete identities, so the bundle's central claims are
  no longer scattered across `.txt` files. There is still **no hash chain
  and no signature** over the bundle, which is what F-17 is about.
  Partial overlap; not repaired.
- **F-18** (evidence drift): untouched. A binding makes drift detectable;
  it reconciles no document. Nothing here re-points the reports that cite
  bundles for commits those bundles do not describe.

Also unrepaired and out of scope: F-36 (no `ProofPacket`), F-33 and the
inert capabilities, and the `PYTHONUTF8=1` precondition the suite depends
on and nothing in the repo enforces.

### Blind spot, stated

`content_fingerprint` does not enumerate git-ignored files; closing that
means walking the whole tree. Build caches, `.venv` and the ignored parts
of `.gnosis/` are therefore outside the identified tree. Its docstring
has said so since the primitive was written, and the bundle repeats it
under `tree_identity.blind_spot` because this unit now depends on it.

## Mutation check

Nine mutants, each restoring exactly one defect, run by
`scripts/mutation_check_f14.py`. Targeted suite:
`tests/test_evidence_binding.py`, `tests/test_git_evidence.py`; baseline
**38 passed / 5 subtests**.

| Mutant | Result |
|---|---|
| MF1 the identity is `git status --porcelain` again | **red** |
| MF2 the before/after comparison is removed | **red** |
| MF3 an unavailable identity binds anyway | **red** |
| MF4 the post fingerprint is taken BEFORE the checks | **red** |
| MF5 the bundle is staged inside the repository again | **red** |
| MF6 an unreadable untracked file is accepted as identified | **red** |
| MF7 a failed git probe is accepted as an identity | **red** |
| MF8 the summary reports a pass the binding refused | **red** |
| MF9 a capture with no checks reports a result | **red** |

None survived; the tree was restored and re-verified green (38 passed).
The script exits non-zero if any mutant survives or if the baseline is
not green, so it cannot produce a clean transcript for an unguarded tree.

MF1 is the F-14 reproduction as a mutant: it puts the old identity back
and the suite goes red in 1.26 s on the first test, which is the one that
builds two trees with the same status, the same names and different
bytes.

## Evidence

`.gnosis/evidence/20260822T212531Z/` — **910 passed, 62 subtests**, mypy
strict clean over 56 source files, ruff at 19 findings against a baseline
of 19. Captured against a clean tree at `985023c` (tree `75cb3771`), and
for the first time the binding is INSIDE the bundle rather than written
around it by hand:

```json
"tree_identity": {
  "binding": "BOUND", "identical": true, "drift": [],
  "pre":  { "digest": "320dfc5ccebe8904…fcbf7c", "fingerprint": { … } },
  "post": { "digest": "320dfc5ccebe8904…fcbf7c", "fingerprint": { … } }
}
```

Both fingerprints are complete in the file: HEAD `985023c…`, branch,
`status_sha256`, `patch_sha256`, and the two untracked entries
(`.stfolder/syncthing-folder-c9ceae.txt`, `PROJECT_REPORT.md`) with a
sha256 each and no content anywhere. `exit_code` 0 with `all_passed`
false and `gates_clean` true — ruff exited 1 at exactly the baseline,
which is `WITHIN_LINT_BASELINE` and not a failure.

**On the subtest count**, because a reviewer comparing it to F-34's 60
will notice: 910 = 874 + the 36 new tests, and 62 = 60 + 2. The new file
contributes 5 subtests when the working tree has 5 untracked entries and
2 when it has 2 — `test_every_untracked_entry_is_represented_by_a_digest`
runs one subtest per untracked path, and at capture time the tree held
only the two pre-existing ones. The number is data-dependent by design;
the test asserts a property of whatever is actually there.

Beyond the gate transcripts the bundle carries three artifacts, all three
added to the published directory AFTER the capture returned — the capture
writes only its own transcripts and `SUMMARY.json`, and that file is
exactly as produced:

- `mutation-check.f14.txt` — nine mutants, none survived. Produced by the
  committed `scripts/mutation_check_f14.py`, so the claim can be re-run.
- `reproduction.f14.txt` — F-14 reproduced against the repaired tree and
  the repair exercised: two dirty trees with an identical `git status`,
  an identical `git diff --stat` and an identical OLD bundle digest
  (`ae106a23…` for both) produce two DIFFERENT content identities
  (`fd7d6ce4…` / `d04ea2cf…`); an untracked file's path is in the payload
  and its bytes are not; a tracked file touched mid-check gives
  `TREE_MUTATED` / exit 2 with `checks_all_zero_exit` still true and
  `all_passed` false; an untracked file touched mid-check names itself in
  the drift; a broken probe gives `IDENTITY_UNAVAILABLE` / exit 3 with
  zero checks run and the side-effect file absent; and a bundle staged
  inside the tree refuses its own capture.
- `reproduce_f14.py` — the script that produced it, so the transcript is
  re-runnable rather than quotable. It also echoes its own source at the
  end of the transcript.

The mutation check ran against the same working tree as the commit,
before it, and `scripts/mutation_check_f14.py` is committed so a reviewer
can re-run it against the exact committed tree.

The suite is run with `PYTHONUTF8=1`, this workstation's documented
baseline (ADR-0001, L-0003). Without it,
`tests/test_cli_review_adapters.py` fails on a filename with an accent —
an environment precondition, not anything this unit changed.

**The baseline was not green when this unit started, and it is not
because of this unit.** The full suite at `aea62b0` returned **1 failed,
873 passed, 60 subtests** — `tests/test_work_queue.py::`
`TestACrashedWorkerLosesNothing::test_recovery_never_takes_a_brief_from_a_live_worker`.
Root cause, diagnosed rather than dismissed: the class fixture
`_short_lived()` sets `default_ttl_s=0.05`, and this test — unlike its
neighbours, which sleep 150 ms *in order to* let the lease expire — needs
the lease to still be alive across `recover()`, `running_ids()` and
`complete()`, four file-locked JSON round-trips on Windows. Under load
the 50 ms budget is exceeded and `complete()` raises `StaleLeaseError`.
Reproduced in isolation: **1 failure in 5 runs**. mypy was clean over 55
files and ruff sat at exactly the 19-finding baseline in the same run.
It is a pre-existing flaky test, unrelated to F-14, and it is recorded
here rather than repaired because this unit is scoped to F-14 — and
because a flaky test is repaired by making it deterministic, which is a
change to `tests/` that no F-14 evidence should be carrying.

## Files

- `src/gnosis/kernel/evidence_capture.py` — new. `TreeIdentity`,
  `probe_tree_identity`, `TreeBinding`, `bind_tree`, `describe_drift`,
  `CheckCommand` / `CheckResult` / `CheckOutcome` / `ChecksVerdict`,
  `run_capture`, `build_summary`, `publish_bundle`, `EmptyCaptureError`
  and the four exit codes.
- `scripts/capture_evidence.py` — rewritten as a driver over that module:
  the command list, the lint baseline, a staging root outside the repo,
  and publication after the post fingerprint.
- `scripts/mutation_check_f14.py` — new, the nine mutants as data. Kept
  separate from `scripts/mutation_check.py`, which is part of F-34's
  closed evidence and must keep producing the same nine mutants over the
  same targeted suite.
- `tests/test_evidence_binding.py` — new, named after the property rather
  than the module, as `tests/test_no_invalid_done.py` is.

## First independent review addendum — Codex, 2026-08-23: **FAIL CRÍTICO**

The delivery above was reviewed independently and returned FAIL CRÍTICO.
The identity is right at both ends and the derivation is right; the claim
built on them is not. Two fingerprints prove the tree was the same at two
instants. They prove nothing about the interval between them, and the
interval is where the checks run.

### The finding, reproduced

```python
# a check that changes a covered file, reads the change, and puts it back
st = os.stat("a.txt"); original = open("a.txt","rb").read()
open("a.txt","wb").write(b"TAMPERED"); assert open("a.txt","rb").read() == b"TAMPERED"
open("a.txt","wb").write(original); os.utime("a.txt", (st.st_atime, st.st_mtime))

# -> binding=BOUND  identical=true  evidence_valid=true  all_passed=true  exit=0
```

Bytes, size, status and timestamps all restored, so every endpoint
comparison agrees — correctly. The suite did not run against the bytes
the bundle names; it ran against `TAMPERED` for part of the interval and
the bundle says otherwise. This is the ABA problem, and the previous 36
tests could not have caught it: every mutation they make stays visible
until the post fingerprint, so all of them are detected by an endpoint
comparison and none of them exercises change → read → restore.

The reviewer was also right about what does not fix it. Polling, `mtime`,
`git status` and a third fingerprint are all samples of a moment, and a
transient change lives between moments. Sampling harder narrows the
window; it never closes it.

### The repair — the interval gets its own authority

**`kernel/write_observer.py`** streams every change under the tree from
`ReadDirectoryChangesW`, watching recursively, filtering on file name,
directory name, attributes, size, last write, creation and security. The
kernel queues a notification for each change from the moment the first
read is issued, so a write and its undo both appear. Attributes are in
the filter because clearing a read-only bit in order to write is itself
a change worth seeing.

Two ways the stream can lie by omission are treated as loudly as a
violation:

- **Overflow.** If changes arrive faster than they are drained the kernel
  drops the queue and returns a zero-length read. Events were lost; the
  observation is INCOMPLETE and the capture fails closed.
- **The undelivered tail.** Waiting "long enough" after the last check is
  a timer, and a timer is what was just proved insufficient. `stop()`
  instead writes a barrier file into the watched tree and blocks until it
  OBSERVES that barrier. Notifications are delivered in order, so seeing
  the barrier proves every earlier change was already delivered. If the
  barrier never arrives, the observation is incomplete and the capture
  fails closed. The barrier is this module's only write: it lives in
  `.gnosis-capture-barrier/`, is removed in a `finally`, and is always an
  allowed path.

**The order in `run_capture` is the argument.** The observer is armed
FIRST, so the pre fingerprint is itself inside the observed window; the
checks run; the post fingerprint is taken while the observer is still
running; only then is the stream closed behind the barrier. The
unobserved windows are the instant before arming and the instant after
the barrier, and nothing runs in either.

**Two new outcomes, two new exit codes**, because the operator response
differs again:

| Situation | Recorded as | Exit |
|---|---|---|
| a covered input was written during the run | `INPUTS_MUTATED` | 4 |
| the interval could not be observed, or not completely | `UNOBSERVED` | 5 |

`UNOBSERVED` outranks `INPUTS_MUTATED` for the same reason
`IDENTITY_UNAVAILABLE` outranks `TREE_MUTATED`: not knowing is worse than
knowing. `evidence_valid` is now the conjunction — the endpoints agree
AND the interval was observed clean. Either half alone is what the review
just refuted.

**Classification, and how a legitimate cache stops being a false
positive.** Everything a check writes that CAN be redirected is
redirected out of the tree: `PYTHONPYCACHEPREFIX`, `MYPY_CACHE_DIR`,
`RUFF_CACHE_DIR` and `PYTEST_ADDOPTS=-p no:cacheprovider` all point at a
scratch directory beside the bundle and outside the repository. What is
left is judged by rule, in this order: a path in the covered set is a
violation; a path under `.git/` is COUNTED as a machinery event and not
judged, because git rewrites its index while merely reading the tree; a
path under an explicitly allowed prefix is allowed; a directory's own
timestamp event is allowed, since its entries produce their own events;
anything else is checked in one batch against git's ignore rules, and a
path git does not ignore is a violation. That last clause is what catches
a file created and deleted inside the run — it is in neither fingerprint,
and only the stream ever saw it. `git check-ignore` classifies paths the
stream already produced; it is never asked what changed.

### One existing test changed, and only one

`test_evidence_valid_is_derived_from_the_binding` asserted that a BOUND
binding is sufficient for `evidence_valid`. That assertion is the defect,
stated as a test, so it could not survive the repair intact. Its
construction now passes a boundary and its assertion is the same one with
the half it was missing; a companion test asserts the negative case — a
BOUND binding over an unobserved interval is NOT valid. The other 35 pass
unedited, and the nine original mutants all still bite. MF4's anchor text
was updated because the code it names moved; the mutant is the same.

### Mutation check

Thirteen mutants now, run by `scripts/mutation_check_f14.py`. Targeted
suite `tests/test_evidence_binding.py` + `tests/test_git_evidence.py`;
baseline **58 passed / 3 subtests**.

| Mutant | Result |
|---|---|
| MF1..MF9 (the first delivery's nine, unchanged in meaning) | **red** |
| MF10 an observed write to a covered input is not a violation | **red** |
| MF11 an observation that could have missed something is accepted | **red** |
| MF12 validity goes back to the binding alone — the reviewed defect, restored | **red** |
| MF13 a path that appears and disappears inside the run is not judged | **red** |

None survived; the tree was restored and re-verified green. MF12 is the
review's finding put back verbatim: with it in place the change → read →
restore tests all report valid evidence again.

### Evidence

Two bundles, both committed, because hiding the red one would be the same
kind of dishonesty this whole finding is about.

**`.gnosis/evidence/20260822T231831Z/` — the capture this addendum
stands on.** 930 passed, 73 subtests, mypy strict clean over 57 source
files, ruff at 19 findings against a baseline of 19. Clean tree at
`92e76c3`. `binding` BOUND with pre and post digest
`274f45959969d73ba47aede62ca42360dfdafc4c2b4676a0a3557d774d68384b`, and
`boundary` CLEAN over a 19-minute suite: **56 events observed, 0
violations**, 32 of them machinery (`.git/`) and 14 allowed, over 703
covered files. `exit_code` 0 with `all_passed` false and `gates_clean`
true, because ruff sits at the baseline.

Two numbers move for reasons worth stating rather than leaving a reviewer
to reconcile. The subtest count is 73 rather than 62 because
`test_every_untracked_entry_is_represented_by_a_digest` runs one subtest
per untracked path and the tree held thirteen at that moment. And the
identity's untracked map includes the eleven files of the bundle below,
which were on disk and uncommitted when this capture ran: the digest
describes the working tree that was actually checked, which is the point.

**`.gnosis/evidence/20260822T225826Z/` — the same commit, one flaky test
red.** 1 failed, 929 passed. `binding` BOUND, `boundary` CLEAN (57 events,
0 violations), `evidence_valid` **true**, `exit_code` **1**. It is kept
because it is the clearest demonstration in the repository that the four
axes are independent: the tree was identified, the interval was observed
quiet, and the code was red. The bundle is exactly as the capture
produced it; nothing was added to it.

The failure is the pre-existing flaky family recorded in the first
delivery, and it is now characterised rather than sighted:
`tests/test_work_queue.py::_short_lived()` sets `default_ttl_s=0.05`, and
**eight tests across two classes** call it. The ones that need the lease
to still be alive race a 50 ms wall-clock budget across several
file-locked JSON round-trips, while their neighbours sleep 150 ms
precisely so it expires. Two different tests in that family have now
failed this way —
`TestACrashedWorkerLosesNothing::test_recovery_never_takes_a_brief_from_a_live_worker`
at `aea62b0` (1 failure in 5 runs in isolation) and
`TestRepairsFromTheIndependentReview::test_a_brief_is_not_re_offered_forever`
here (**3 failures in 8 runs** in isolation). It is a timing defect in
the tests, not in the queue, it predates this unit, and it is left alone
because repairing it means editing `tests/` in a unit scoped to F-14.

Beyond the gate transcripts the green bundle carries three artifacts,
added to the published directory after the capture returned:

- `mutation-check.f14-round2.txt` — thirteen mutants, none survived.
- `reproduction.f14-aba.txt` — the review's finding reproduced against
  the repaired tree, eleven cases, each printing BOTH answers. The
  endpoint column reads `BOUND identical=True` in every transient case —
  that IS the finding — while the interval column reads `INPUTS_MUTATED`
  and the capture exits 4. It also shows the two fail-closed paths
  (exit 5), the two no-false-positive paths (exit 0), a stable run, and
  the raw event stream in which one write and its undo both appear.
- `reproduce_f14_aba.py` — the script that produced it, which echoes its
  own source into the transcript.

### What this does not close, stated rather than implied

- **F-14 is still OPEN**, pending a second independent review. The first
  one found this in a unit that had 36 tests, nine mutants and a clean
  self-review.
- **F-15..F-18 remain open and untouched by this addendum.** The overlap
  recorded in the first delivery is unchanged, with one addition: writes
  under `.git/` are counted and not judged, so a check that installs a
  hook or rewrites a ref is outside this boundary. That is precisely
  F-17's subject (`tamper_fingerprint` exists and covers hooks and
  config) and it is not repaired here.
- **The mechanism is Windows-only.** On any other platform
  `create_write_observer` returns an observer that reports itself
  unavailable, so a capture there exits 5 and produces no valid evidence.
  Fail-closed, and a real limitation.
- **Memory-mapped writes** may be reported when the section is flushed
  rather than when the memory is written.
- **Ignored files are still outside the covered set**, exactly as
  `content_fingerprint` defines it. The boundary does not widen the
  claim; it defends the claim that was already being made.

## Second independent review addendum — 2026-08-23: **FAIL CRÍTICO PROVISIONAL**

The write observer closed the ABA the first review demonstrated, and the
review confirmed that. It then asked the right next question: the barrier
proves that every notification Windows had already **generated** was
delivered, and proves nothing about whether every modification generated
one. `FILE_NOTIFY_CHANGE_SIZE` and `FILE_NOTIFY_CHANGE_LAST_WRITE` are
documented as detected when a change reaches storage or the cache, last
write may not settle until write handles close, and modifications through
a memory-mapped section have weaker guarantees still.

The instruction was to try to break the thing before changing it. So the
two reproductions were built and run against the shipped implementation
first. Both are committed as `scripts/probe_f14_boundary.py` (with
`scripts/probe_f14_meddler.py` as the second process), every ordering is
a handshake on a pipe, and there is not one sleep in the synchronisation.

### The result: one held, one broke

**A — an independent process holds a raw write handle open across the
whole capture, never calls `FlushFileBuffers`, and closes only after
`stop()`. HELD.** The check demonstrably read the mutated bytes, PRE and
POST were identical, and the observer reported `modified: a.txt` anyway:
`INPUTS_MUTATED`, exit 4. On this platform an ordinary buffered write
does generate its notification when it reaches the cache, without waiting
for the handle to close.

**B — the same, through a writable memory-mapped view that is never
flushed and stays alive across the barrier. BROKE IT.**

```
digest before                     : 02f2442a…
digest after MODIFY (fresh read)  : ca6d8c6f…
what the CHECK read               : ca6d8c6f…   <- mutated bytes consumed
PRE == POST                       : True
notification for a.txt received   : False       <- nothing to deliver
boundary                          : CLEAN
evidence_valid                    : True
exit_code                         : 0
```

That is the whole finding in eight lines. The check ran against bytes the
bundle does not name, and the bundle certified itself. No barrier could
have helped: the barrier orders a stream that never contained the event.

### The repair: stop watching for it, start refusing it

Patching the specific case — a settle delay, a `FlushFileBuffers`, an
exception for mapped files — would have been treating the symptom, and
the review said so in advance. What is wrong is the category: **a
mechanism that reports writes cannot be the whole boundary when a write
can decline to be reported.**

So the covered inputs stop being writable. For the duration of the checks
`kernel/input_lock.py` holds every covered file open with `GENERIC_READ`
and a share mode of `FILE_SHARE_READ` alone. Measured on this repository
rather than assumed — **718 covered inputs locked in 6.17 s**:

| another process… | result |
|---|---|
| reads the file | allowed |
| opens it for writing | `ERROR_SHARING_VIOLATION` |
| **maps it writable** | **`ERROR_SHARING_VIOLATION`** |
| deletes it | `ERROR_SHARING_VIOLATION` |
| renames it | `ERROR_SHARING_VIOLATION` |
| changes its attributes | allowed — and notified |

The mapping row is the one that matters. A writable section needs a
handle with write access and there is no way to obtain one, so
reproduction B is not detected late, it is refused early.

**Prevention and observation are complementary by construction, and the
split is not arbitrary.** Prevention covers what a notification can be
withheld for: content written into a file that already exists. Observation
covers what no cache can defer: creating, deleting and renaming a path,
which are directory-entry operations, plus the attribute changes that
remain legal. Neither half is sufficient and each covers exactly the
other's blind spot.

**If the boundary cannot be built, nothing runs.** A covered input that
another process already holds open for writing cannot be locked, so the
capture stops before the first check with `UNPROTECTED` and exit **6**.
That is reproductions A1 and B1 in the probe: the attacker gets its handle
first and wins nothing, because the suite never starts. Discovering that
in six seconds is better than discovering it after nineteen minutes.

### The probe, now committed and re-runnable

`scripts/probe_f14_boundary.py` runs six cases and prints, for each, the
five things the review asked to see separately: whether the mutation was
observable BY THE CHECK, whether PRE == POST, whether a notification
arrived, the boundary verdict, and `evidence_valid`.

| case | boundary | result |
|---|---|---|
| A0 raw handle, observation only | `INPUTS_MUTATED`, exit 4 | held |
| **B0 mapped write, observation only** | `CLEAN`, exit 0 | **BROKEN** |
| A1 raw handle taken before the capture | `UNPROTECTED`, exit 6, 0 checks | held |
| B1 mapping taken before the capture | `UNPROTECTED`, exit 6, 0 checks | held |
| A2 the check opens an input for writing | refused, `CLEAN` | held |
| B2 the check maps an input writable | refused, `CLEAN` | held |

A0 and B0 use a lock that claims enforcement and locks nothing — the
reviewed design, reconstructed — so the transcript contains the defect
and its closure side by side rather than only the closure.

### Tests: 65, of which the 56 are all still here

Nine added. Of the 56, **six were given one extra argument** —
`input_lock=_no_prevention` — and **not one assertion was changed**. Those
six are the tests whose check writes a covered input; with prevention on,
the write is refused and the observation half of the boundary would never
be exercised. Disabling prevention in those six keeps the detector under
test, which matters: it is the only half that covers a path which did not
exist when the lock was taken, and the only half a platform without the
share-mode mechanism could ever have. The prevention half has its own
class, `TestTheInputsCannotBeWritten`, including both reproductions and a
deliberate characterisation test asserting that a mapped write produces
no notification — if Windows ever changes that, it goes red, and that is
worth learning.

### Mutation check: 16, none survived

The thirteen are all still here. MF4's anchor text was rewritten because
the code it names moved again and its mutation is now "the post
fingerprint is never taken"; its subject is unchanged. Three added, each
removing the new prevention:

| Mutant | Result |
|---|---|
| MF14 the covered inputs are never made unwritable | **red** |
| MF15 a lock that could not be enforced is recorded as if it had been | **red** |
| MF16 the checks run even when the inputs could not be protected | **red** |

MF14 is the review's finding put back: with it in place, B2 tampers
successfully and the bundle certifies itself again.

### Evidence

`.gnosis/evidence/20260823T011759Z/` — **939 passed, 62 subtests**, mypy
strict clean over 58 source files, ruff at 19 findings against a baseline
of 19. Clean tree at `dc466a3`. The bundle now states three things about
itself rather than two:

```json
"tree_identity": { "binding": "BOUND", "identical": true, "drift": [],
                   "pre": {"digest": "2e963063…f0476c"},
                   "post": {"digest": "2e963063…f0476c"} },
"boundary": { "verdict": "CLEAN", "observed_events": 57, "violations": [],
              "machinery_events": 32, "covered_files": 720,
              "protection": { "enforced": true, "locked_inputs": 720,
                              "refused": [],
                              "mechanism": "CreateFileW(GENERIC_READ, FILE_SHARE_READ)" } }
```

Every one of the 720 covered inputs was unwritable for the whole
thirteen-minute suite, none was refused, and the write stream recorded 57
events of which none touched a covered path. `exit_code` 0 with
`gates_clean` true and `all_passed` false, because ruff sits at the
baseline.

Two artifacts were added to the published directory after the capture
returned; `SUMMARY.json` is exactly as produced:

- `mutation-check.f14-round3.txt` — sixteen mutants, none survived.
- `probe-f14-boundary.txt` — the six break attempts run against this
  commit, `dc466a3`. It ends with `BROKEN: B0` and that line is the
  point: B0 is the reviewed design reconstructed with a lock that claims
  enforcement and locks nothing, so the transcript carries the defect and
  its closure side by side. A0 held, A1/B1 refused the capture before it
  started, A2/B2 had their writes refused by the operating system.

### What is still not closed

- **F-14 remains OPEN**, pending a third independent review. Two reviews
  have now found something in this unit that its own tests and mutants
  did not.
- **Attributes can still change** on a covered input. `chmod` cannot
  grant write access while the share mode stands, and the observer
  reports it, so it is visible and inert — but it is not prevented.
- **Windows only.** Both halves of the boundary are Windows mechanisms.
  Elsewhere the lock and the observer both report themselves unavailable
  and the capture exits 6 or 5 rather than pretending; no valid evidence
  can be produced on another platform, which is a real limitation and not
  a fail-open.
- **`.git/` is counted, not judged**, and is not lockable in this scheme.
  A check that installs a hook is outside this boundary and inside F-17's.
- **F-15..F-18 remain open and untouched.**
