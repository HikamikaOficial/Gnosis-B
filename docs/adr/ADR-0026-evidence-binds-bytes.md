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
- Independent review, round 7 (2026-08-24): **FAIL PARCIAL.** Three
  places assumed git-ignored files were outside the boundary, which
  together read as "ignored ⇒ cannot affect the result". Reproduced: a
  check consumed `MALICIOUS` from an ignored file and the bundle reported
  CLEAN, `evidence_valid: true`, `all_passed: true`. Repaired in addendum
  7 with three declared path classes and no use of `git check-ignore`.
- Independent review, round 6 (2026-08-24): **FAIL PARCIAL — ALTA.** The
  reparse check asked whether the TARGET was a reparse point and never
  whether the PATH used to reach it could be redirected. Measured: a
  junction above a covered input was retargeted to another directory on
  the same volume while a handle on the object was held, and the lexical
  path read the other directory. The classifier also forgave every
  directory event because the path was a directory again by the time it
  looked. Both refused in addendum 6.
- Independent review, round 5 (2026-08-23): **FAIL PARCIAL — ALTA.** The
  main repair and the evidence were accepted; one fail-open path
  remained. A directory-like covered input — a submodule gitlink — was
  reopened with `FILE_FLAG_BACKUP_SEMANTICS`, counted as a locked handle
  and never identified, so an outcome could say `enforced: true` while
  holding an object it could not name. Refused rather than supported in
  addendum 5.
- Independent review, round 4 (2026-08-23): **FAIL DE ALCANCE** — no new
  finding against the architecture; the accepted domain was wider than
  the demonstrated one. `ReFS` was in the supported set and had never
  been run on. Narrowed in addendum 4.
- Independent review, round 3 (2026-08-23): **repair accepted, closure on
  hold.** The combination of prevention and observation was accepted; four
  adversarial questions were then asked, and three of them exposed a gap
  between what the boundary claimed and what it had established — the
  object behind each handle, the window while the locks are taken, and
  the volume the guarantee rests on. All four answered by measurement in
  addendum 3.
- **An eighth independent review is OUTSTANDING**; F-14 stays OPEN in
  `docs/V1_COMPLIANCE_MATRIX.md` until one returns without findings.
  Three reviews have now found something this unit's own tests and
  mutants did not.
- Boundary domain: every path git can enumerate — tracked, untracked and
  **ignored** — is an INPUT unless declared an OUTPUT or OUT_OF_SCOPE
  root in `scripts/capture_evidence.py`. `git check-ignore` is not an
  authority anywhere.
- Demonstrated on: **Windows, local volume, drive type `fixed`,
  filesystem `NTFS`** — and nothing else. `ReFS` is a candidate extension
  pending real validation, refused with its own reason until the probe
  has been run on a real volume of that kind. Every other drive type,
  every other filesystem and every UNC path is refused before any input
  is opened.
- Tests: `tests/test_evidence_binding.py` — **118 tests, 19 subtests**
  (36, 20, 9, 19, 3, 7, 10, then 16 with two inverted).
- Mutation check: `scripts/mutation_check_f14.py` — **twenty-five
  mutants, none survived** (nine, four, three, four, one, one, two, one),
  declared as data so a reviewer re-runs the claim rather than reading
  it.
- Break attempts: `scripts/probe_f14_boundary.py` — ten cases in four
  groups, committed and re-runnable, containing the defect and its
  closure side by side.
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

## Third independent review addendum — 2026-08-23: **REPARACIÓN ACEPTADA, CIERRE EN HOLD**

The review accepted the combination of prevention and observation and
then asked four questions that decide whether the mechanism is real
rather than plausible. All four were answered by running something, and
the answers are below. Nothing about the architecture changed; what
changed is that three of the four exposed a gap between what the
boundary claimed and what it had actually established.

### A — a writable section with no file handle left

A section keeps the underlying file object alive with the access it was
created through. If it did not, a view could sit on a covered input with
nothing left to conflict with, the lock would report ENFORCED, and the
whole prevention argument would be void for the exact case it was built
to close.

Measured, in four shapes, each from an independent process:

| shape | lock |
|---|---|
| file handle open, mapping open, view alive | refused, error 32 |
| file handle CLOSED, mapping open, view alive | refused, error 32 |
| file handle closed AND mapping closed, only the view alive | refused, error 32 |
| file handle closed, a DUPLICATE kept alive | refused, error 32 |

`ERROR_SHARING_VIOLATION` in every case, and the capture then runs
nothing: `UNPROTECTED`, exit 6, zero checks, and the check's side-effect
file never appears. The last three are cases A3, A4 and A5 of
`scripts/probe_f14_boundary.py` and are permanent tests in
`TestALiveWritableSectionRefusesTheBoundary`.

### B — the protected handle and the identified object are one object

They were not being tied together at all. Now every handle is recorded
by **`FILE_ID_INFO`** — the volume serial number and the 128-bit file id
— and verified with `GetFinalPathNameByHandleW` to still resolve to the
path it was opened by. A handle whose final path is not its own path is
a refusal, not a note.

The full map goes into the bundle as `input-identities.json`, and
`SUMMARY.json` carries its digest and count, so a reviewer can check that
the objects protected are the objects the fingerprint is about without
reading 700 lines of hex.

Three more refusals came out of asking the question properly:

- **Reparse points are refused outright.** A symlink or junction among
  the covered inputs is a redirection, and what the lock holds need not
  be what a check opens. This tree has never had one; if it acquires one,
  the capture stops rather than reasons about it.
- **A hard link is refused too**, and that one is a property rather than
  a check: the share mode belongs to the FILE, not to the name it was
  opened by, so a second name for the same object cannot be written
  either. Verified.
- **A covered input deleted before its turn** fails the acquisition.

### C — the race while the locks are being taken

Acquiring the locks is not instantaneous, and an input whose turn has not
come is not yet protected. The old code took its identity BEFORE that
window and would have described a tree that could still have moved
inside it.

**The identity that matters is now taken after the inputs are
unwritable.** `run_capture` re-probes once the lock reports enforced and
requires that identity to equal the pre-check one; anything else is
`PREPARATION_DRIFT`, exit 7, and **nothing runs**. The bundle records it
under `boundary.locked_identity`, described in the file as "the bytes the
checks will actually read".

That gives exactly the two outcomes the review allowed. Either the
boundary is invalid, or the recorded identity demonstrably corresponds to
what will be checked — and it is now the second by construction rather
than by argument. A modification made in the window and left in place is
caught (and, since it also survives to the end, the more severe
`TREE_MUTATED` is what the exit code reports — both facts are in the
bundle). A modification made in the window and reverted is caught by the
observer, because an ordinary write still notifies. Both are permanent
tests, driven by a lock that deliberately acquires in two halves so the
window is a real one rather than a mocked one.

### D — the volume the guarantee was demonstrated on

Share-mode refusal and `FILE_ID_INFO` are local Windows filesystem
semantics. A network redirector may implement them partially or not at
all, and extrapolating from one local NTFS volume is exactly what the
review said not to do.

The capture now asks the volume and refuses what it cannot demonstrate:
a whitelist of drive type `fixed` and filesystem `NTFS` — it also
admitted `ReFS` at the time, which the fourth review correctly refused;
see addendum 4 — a UNC path refused outright as a redirector, and the
answer recorded in the bundle under `boundary.protection.volume`. **F-14
is demonstrated on: drive type `fixed`, filesystem `NTFS`, local
volume.** Anything else
produces `UNPROTECTED` before a single handle is taken — verified with an
injected volume, because this machine has no share to mount.

### Measurements

733 covered inputs on this repository: locked, identified by file id and
path-verified in **0.45 s**. (The 6.17 s recorded in the previous
addendum was a cold cache; the number is kept there rather than quietly
corrected.)

### Tests: 84, and the 65 are all still here

Nineteen added, across four classes named after the review's four
questions. Of the 65, exactly one changed and only in its fixture:
`test_an_unavailable_post_identity_fails_closed_although_every_check_passed`
injects a sequence of identities and now needs three of them rather than
two, because the identity is taken before the lock, again once the
inputs are unwritable, and again after the checks. Its assertions are
untouched.

### Mutation check: 20, none survived

The sixteen are all here. Four added, one per new guarantee:

| Mutant | Result |
|---|---|
| MF17 a reparse point among the covered inputs is locked like any other file | **red** |
| MF18 the protected handles are never identified | **red** |
| MF19 any volume is assumed to provide the semantics | **red** |
| MF20 the identity is not re-taken once the inputs are unwritable | **red** |

MF19 is the one worth noting: it can only be caught because the volume
probe is injectable, so the refusal is testable on a machine that has
only a supported volume. A guarantee that can only be tested where it
does not apply is not tested.

### The probe, extended to nine cases

`scripts/probe_f14_boundary.py` now runs A0, B0, A1, B1, A3, A4, A5, A2,
B2 and ends with `BROKEN: B0`. That line is the point rather than an
embarrassment: B0 is the observation-only design reconstructed with a
lock that claims enforcement and locks nothing, so the transcript carries
the defect and its closure side by side, in one file, re-runnable.

### Evidence

`.gnosis/evidence/20260823T025127Z/` — **958 passed, 67 subtests**, mypy
strict clean over 58 source files, ruff at 19 findings against a baseline
of 19. Clean tree at `f0f892a`. The bundle states four things about
itself now:

```json
"tree_identity": { "binding": "BOUND", "identical": true,
                   "pre":  {"digest": "21acee64…3a391f"},
                   "post": {"digest": "21acee64…3a391f"} },
"boundary": {
  "verdict": "CLEAN", "observed_events": 65, "violations": [],
  "covered_files": 733,
  "locked_identity": { "available": true, "digest": "21acee64…3a391f" },
  "protection": {
    "enforced": true, "locked_inputs": 733, "identified_objects": 733,
    "identity_digest": "a93d481b…23308f",
    "mechanism": "CreateFileW(GENERIC_READ, FILE_SHARE_READ)",
    "volume": { "supported": true, "drive_type": "fixed",
                "filesystem": "NTFS" } } }
```

`locked_identity.digest` equals the pre-check digest, which is the point
of it: the identity the bundle cites was taken once the inputs were
already unwritable, so it describes the bytes the thirteen-minute suite
actually read rather than the bytes the tree held before the locks went
on. All 733 covered inputs were locked, identified by file id and
path-verified; none was refused; no observed event touched a covered
path.

Three artifacts beyond the gate transcripts, all written after the
capture returned except the first, which the capture writes itself:

- `input-identities.json` — 733 entries, one per protected object, each
  `volume-serial:file-id`. `SUMMARY.json` carries their digest so the map
  can be checked without being read.
- `mutation-check.f14-round4.txt` — twenty mutants, none survived.
- `probe-f14-boundary.txt` — the nine break attempts run against this
  commit. It ends with `BROKEN: B0`, and that is deliberate: B0 is the
  observation-only design reconstructed, so the transcript carries the
  defect and its closure in one file.

### What is still not closed

- **F-14 remains OPEN.** Three reviews, three findings this unit's own
  tests did not have. It closes when an independent review returns
  without findings, and not before.
- **Attributes can still change** on a covered input. No write access
  follows from it while the share mode stands, and the observer reports
  it.
- **Windows and a local NTFS volume.** Everywhere else the capture
  refuses to claim a boundary it cannot demonstrate. (This line said
  "NTFS/ReFS" until the fourth review; addendum 4 narrows it.)
- **`.git/` is counted, not judged**, and is not locked. A check that
  installs a hook is outside this boundary and inside F-17's.
- **F-15..F-18 remain open and untouched.**

## Fourth independent review addendum — 2026-08-23: **FAIL DE ALCANCE**

No new finding against the protection architecture. One confirmed defect,
and it is not in the mechanism: **the domain the code accepted was wider
than the domain anyone had demonstrated.**

`_SUPPORTED_FILESYSTEMS` accepted `{"NTFS", "ReFS"}`. The boundary had
been demonstrated on Windows, a local volume, drive type `fixed`,
filesystem `NTFS` — and on nothing else. No ReFS volume exists on this
machine, no probe has ever run on one, and `git grep ReFS` over
`.gnosis/evidence/` returns nothing. The two tests that named ReFS
admitted it as an alternative in an assertion that always resolved by
NTFS, so the wider half of the set was never exercised by anything.

The uncomfortable part is that L-0053 — "a mechanism inherits the scope
of its demonstration, not the scope of its description" — was written in
the same commit as the violation. Writing a lesson down is not applying
it, and the reviewer had to point at the sentence for it to bite.

### The repair, which is one line and its consequences

```python
_SUPPORTED_FILESYSTEMS = frozenset({"NTFS"})
# Filesystems that plausibly qualify and have not been demonstrated.
# Listed to be refused with a reason, never to be accepted.
_CANDIDATE_FILESYSTEMS = frozenset({"ReFS"})
```

ReFS is now refused, and refused with **its own reason**, because
"nobody has run it there" is a different fact from "it cannot work
there" and an operator who reads the bundle should be able to tell which
one they are looking at:

```
filesystem 'ReFS' is a candidate the boundary has NOT been demonstrated
on; it is refused until the probe has been run on a real volume of that
kind
```

The refusal happens in `classify_volume`, which `WindowsInputLock.acquire`
consults **before opening a single handle**, so an unsupported volume
locks nothing, identifies nothing, and runs no check: `UNPROTECTED`,
exit 6.

The architecture for adding ReFS later is untouched and is now
signposted. What it takes is not a code change first: run
`scripts/probe_f14_boundary.py` and the full suite on a real ReFS volume,
land that bundle, and then move the string from `_CANDIDATE_FILESYSTEMS`
to `_SUPPORTED_FILESYSTEMS`. In that order.

### The demonstrated domain, stated once and plainly

> **F-14 is demonstrated on: Windows, local volume, `drive_type = fixed`,
> `filesystem = NTFS`.**
>
> ReFS is a candidate extension pending real validation. It is not a
> current guarantee. Every other drive type and filesystem, and every UNC
> path, is refused before any input is opened.

### Tests

Two existing assertions tightened to the contract that was actually
demonstrated — `assertIn(filesystem, {"NTFS", "ReFS"})` became
`assertEqual(filesystem, "NTFS")` in both the probe test and the bundle
test. Four added:

- `test_refs_is_a_candidate_and_not_a_guarantee` —
  `classify_volume("fixed", "ReFS").supported` is False, and the reason
  says which kind of refusal it is.
- `test_the_demonstrated_domain_is_exactly_one_filesystem` — asserts the
  sets themselves, so widening the domain fails a test rather than
  passing quietly.
- `test_a_refs_volume_locks_nothing_and_runs_nothing` — takes the refusal
  from the PRODUCTION classifier and injects it as the volume probe (no
  ReFS volume exists here, which is the point), then asserts
  `locked == 0`, `identities == {}`, `checks == ()`, exit 6, the check's
  side-effect file absent, and the bundle recording
  `volume.filesystem == "ReFS"` with `supported: false`.
- the existing injected-volume refusal test is kept as it was.

### Mutation check

**MF21** puts the old line back —
`_SUPPORTED_FILESYSTEMS = frozenset({"NTFS", "ReFS"})` — and the suite
goes red. Twenty-one mutants now, none survived.

### Evidence

`.gnosis/evidence/20260823T043619Z/` — **961 passed, 67 subtests**, mypy
strict clean over 58 source files, ruff at 19 findings against a baseline
of 19. Clean tree at `ed83ed7`.

```json
"tree_identity": { "binding": "BOUND", "identical": true,
                   "pre": {"digest": "1484f782…d7ebca"} },
"boundary": {
  "verdict": "CLEAN", "observed_events": 64, "violations": [],
  "covered_files": 747,
  "locked_identity": { "digest": "1484f782…d7ebca" },
  "protection": { "enforced": true, "locked_inputs": 747,
                  "identified_objects": 747,
                  "volume": { "supported": true, "drive_type": "fixed",
                              "filesystem": "NTFS" } } }
```

`volume.filesystem` is `NTFS`, which is now the whole of the accepted
domain rather than half of it. `locked_identity` equals the pre-check
digest, so the identity the bundle cites was taken with the inputs
already unwritable.

Two artifacts beyond the gate transcripts, added after the capture
returned; `SUMMARY.json` and `input-identities.json` are as the capture
wrote them:

- `mutation-check.f14-round5.txt` — twenty-one mutants, none survived.
- `probe-f14-boundary.txt` — the nine break attempts re-run against this
  commit, unchanged in outcome: only B0, the reconstructed
  observation-only design, breaks.

### Unchanged

Nothing else in this unit was touched. The guarantees accepted by the
first three reviews stand exactly as they were: a pre-existing writer
refuses the boundary; a live writable section refuses it in all four
shapes; `FILE_ID_INFO` identity and final-path binding; reparse points
and hard links; the identity taken after the lock; ABA prevention and
detection; and the volume probe failing closed. The only change is which
volumes the last of those calls supported.

## Fifth independent review addendum — 2026-08-23: **FAIL PARCIAL — ALTA**

The main repair and the evidence over the real tree were accepted: 747
covered, 747 locked, 747 identified, fixed/NTFS, boundary CLEAN,
961 tests, mypy clean, ruff at baseline, 21/21 mutants caught, and the
ABA — writable mapping included — closed for ordinary covered files.

One fail-open path was still inside F-14, and it was in the one place
that had been claiming the strongest guarantee.

### The finding

`WindowsInputLock.acquire` opened each covered path and, when
`CreateFileW` came back with `ERROR_ACCESS_DENIED`, took a branch
commented for exactly the case that matters:

```python
if error == 5:
    # ERROR_ACCESS_DENIED on a directory-like entry (a submodule
    # gitlink); retry with the flag that makes a directory openable
    handle = _kernel32.CreateFileW(
        str(target), _GENERIC_READ, _FILE_SHARE_READ, None,
        _OPEN_EXISTING, _FILE_FLAG_BACKUP_SEMANTICS, None)
    if handle and handle != _INVALID_HANDLE_VALUE:
        self._handles.append(handle)
        continue            # <- _identify never runs
```

That `continue` skipped `_identify`. The handle counted towards
`locked_inputs`, never reached `identities`, and the outcome could still
return `enforced: true` — while this module's own `identity_note`, in
every bundle, says *"every protected handle is recorded by
FILE_ID_INFO"*. It was not.

And even taken on its own terms the branch proved nothing worth having: a
handle on a submodule's DIRECTORY says nothing about the bytes inside
that submodule's working tree, which is what a check would actually read.

### The repair — declined, not extended

Submodule support is not attempted. A directory-like covered input is
refused **before any open is attempted**, by its attributes rather than
by the error code it happens to produce:

```python
if (attributes != _INVALID_FILE_ATTRIBUTES
        and attributes & _FILE_ATTRIBUTE_DIRECTORY):
    refused.append(f"{relative} (directory-like covered input; submodule and "
                   "gitlink semantics are not demonstrated by this boundary)")
    continue
```

The `FILE_FLAG_BACKUP_SEMANTICS` retry is gone from `acquire` entirely.
The flag survives in one place only, `volume_serial_of`, which opens the
repository root, reads its serial and closes it immediately — it holds
nothing and appends nothing.

**There is now no path that appends a handle without identifying it.**
The single `self._handles.append(handle)` is followed immediately by
`self._identify(...)`, and a problem from it is a refusal.

### The invariant, asserted rather than argued

`locked_inputs` and `identified_objects` describe the same domain, so
they have to agree. That is now checked twice, on the principle this
project already paid for in ADR-0025: one rule, and both ends derive
from it.

- **Producer.** Before returning, `acquire` computes
  `len(self._handles) - len(identities)` and, if it is not zero, appends
  a refusal that says so. Unreachable through the branches above, and
  present precisely because it was reachable once.
- **Consumer.** `classify_observation` refuses a lock whose
  `fully_identified` is false with `UNPROTECTED`, whatever `enforced`
  says. A hand-built inconsistent outcome cannot get past it either, and
  a test builds one to prove it.
- **Bundle.** `protection.fully_identified` is recorded, so a reader can
  check the invariant without re-deriving it.

The other `continue` in the loop — `ERROR_FILE_NOT_FOUND` on a tracked
path deleted from the working tree — appends no handle and so cannot
break the invariant. There is nothing to open and nothing to mutate, and
if such a path reappears during the run the write observer reports it,
because the path is in the covered set. The two halves cover each other
here as everywhere else.

### Ancestor reparse points

The per-path check asks `GetFileAttributesW` about the target, which
cannot see a junction or mount point in an ANCESTOR directory. The answer
is not another attribute query: it is the `VolumeSerialNumber` that comes
back inside `FILE_ID_INFO` for every protected object. The root's serial
is read once from a handle on the root itself, and **an object whose
serial is not that serial is refused**:

```
<path> (object is on volume <serial>, not the probed volume <serial>)
```

A junction above a covered path that stays on the probed volume moves the
path and not the guarantee: the object is identified, its serial matches,
its final path resolves to what the lock holds, and writing through the
REAL path is refused by the share mode. That case is a test, built with
`mklink /J`. A junction that crosses to another volume is refused; that
one is tested by injecting the expected serial, because this machine has
exactly one volume — the same device used for the ReFS and network
refusals, and for the same reason.

Reading the serial per covered input turned a 0.5 s acquisition into
7.4 s, so it is read once and cached: 761 inputs locked and identified in
**0.66 s**.

### Tests

Seven added:

- a directory covered input is refused before it is opened, and the
  invariant still holds in the refusal;
- a directory handle cannot pass as a protected input — through
  `run_capture`: `UNPROTECTED`, exit 6, zero checks, side-effect file
  absent;
- **a real submodule**, created with `git submodule add` from a local
  URI, whose gitlink is a covered path: refused, zero checks;
- an enforced outcome identifies every handle it holds;
- an outcome holding an unnamed handle is not protection — built by hand,
  refused by the consumer;
- an input on another volume is refused;
- a covered file under an ancestor junction stays on the probed volume,
  is identified, and cannot be written through its real path.

### Mutation check

**MF22** restores the defect verbatim, in three edits at once, because
removing any one of them alone would not reproduce it: the directory
refusal is disabled, the `FILE_FLAG_BACKUP_SEMANTICS` retry with its
unidentified `append` is put back, and the producer-side invariant is
switched off. The suite goes red. Twenty-two mutants now, none survived.

### Evidence

`.gnosis/evidence/20260823T132444Z/` — **968 passed, 67 subtests**, mypy
strict clean over 58 source files, ruff at 19 findings against a baseline
of 19. Clean tree at `b783a39`.

```json
"tree_identity": { "binding": "BOUND", "identical": true,
                   "pre": {"digest": "f07927fc…2ddff0"} },
"boundary": {
  "verdict": "CLEAN", "observed_events": 65, "violations": [],
  "covered_files": 761,
  "locked_identity": { "digest": "f07927fc…2ddff0" },
  "protection": { "enforced": true, "locked_inputs": 761,
                  "identified_objects": 761, "fully_identified": true,
                  "identity_digest": "a84fbea9…302bf8",
                  "volume": { "supported": true, "drive_type": "fixed",
                              "filesystem": "NTFS" } } }
```

`fully_identified: true` is the new line, and it is the one this addendum
exists for: 761 handles held, 761 objects named, and the bundle says so
rather than leaving a reader to compare two counts and hope they were
meant to match.

Two artifacts beyond the gate transcripts, added after the capture
returned; `SUMMARY.json` and `input-identities.json` are as the capture
wrote them:

- `mutation-check.f14-round7.txt` — twenty-two mutants, none survived.
- `probe-f14-boundary.txt` — the nine break attempts re-run against this
  commit, unchanged in outcome: only B0, the reconstructed
  observation-only design, breaks.

### What is still not closed

- **F-14 remains OPEN.** Five reviews, five findings this unit's own
  tests did not have.
- **Submodules are refused, not supported.** A repository with a gitlink
  cannot produce valid evidence through this capture until the objects
  inside the submodule's working tree are locked and identified too.
- Everything named in the previous four addenda stands: attributes can
  still change on a covered input; `.git/` is counted rather than judged,
  which is F-17; the boundary is Windows on a local `fixed` NTFS volume;
  ReFS is a candidate, not a guarantee.
- **F-15..F-18 remain open and untouched.**

## Sixth independent review addendum — 2026-08-24: **FAIL PARCIAL — ALTA**

The fifth repair was accepted in full: no `append` without `_identify`,
`fully_identified` in producer, consumer and bundle, 761 = 761 = 761,
968 tests, 22/22 mutants, gitlinks refused. None of that is reopened
here.

What the review found is that the reparse check had been asking the
wrong question. It asked whether the TARGET was a reparse point. It never
asked whether the PATH USED TO REACH IT could be pointed somewhere else.

### The attack, measured before it was fixed

```
repo\linked -> dirA           lock: enforced=True over dirA\under.py
rmdir linked                  succeeded WHILE a handle on dirA\under.py was held
mklink /J linked dirB         succeeded
read repo\linked\under.py  -> SWAPPED-B
rmdir linked; mklink /J linked dirA
read repo\linked\under.py  -> ORIGINAL-A       (the tree looks untouched)
```

Every line of that is a run on this machine, not a hypothesis. The lock
held the right object and a check reading the lexical path got a
different one. A junction is a directory entry: holding a handle on a
file underneath it protects the FILE, not the NAME. The
`VolumeSerialNumber` check cannot see it either — `dirA` and `dirB` are
on the same NTFS volume, so both objects carry the same serial.

The review also found the second half, in `classify_observation`:

```python
elif (repo / path).is_dir():
    allowed_count += 1
```

Any directory event was forgiven — `added`, `removed`, `renamed_from`,
`renamed_to` — purely because the path happened to be a directory again
by the time the classifier looked. A junction removed and recreated
against another target leaves exactly that shape. The attack would have
been observed and then excused.

### The repair — refuse the chain, judge the structure

**Refuse the chain.** `reparse_in_chain()` walks from the drive down to a
path and returns the first component that can redirect resolution; an
unreadable component counts as one, because a link that cannot be
examined is not a link that can be trusted. It is applied twice:

- once to the repository root and every ancestor above it, at the start
  of `acquire`. If the root is reached through a redirection, every
  covered path inherits it and nothing below can be trusted, so the
  capture stops with `enforced: false`, zero handles taken.
- once per covered input, over every directory component between the
  root and the file, cached per directory because hundreds of inputs
  share a handful of ancestors. The refusal names the component:
  `<path> (ancestor <dir> is a reparse point; the path used to reach this
  input can be redirected while the object stays locked)`.

Junction support is not attempted. It is declined, exactly as submodules
are: protecting one means protecting the resolution chain as well as the
object, and that is a different architecture from the one this unit has
demonstrated.

**Judge the structure.** The classifier now forgives exactly one thing
about a directory, and it forgives it because it is a fact about the
filesystem rather than a concession:

```python
elif event.action == "modified" and (repo / path).is_dir():
```

A directory's timestamp moves whenever its entries move, and the entries
produce their own events. Creating, removing or renaming a directory is
a structural change to the tree and goes through the ordinary rules:
allowed prefix, machinery, git-ignore, otherwise a violation.

The measured cost of the chain walk is nothing: 775 covered inputs
locked, identified and chain-checked in **0.52 s** warm.

### One existing test changed, and its assertion was the defect

`test_a_covered_file_under_an_ancestor_junction_is_still_on_the_volume`
asserted that such an input WAS accepted — "the junction redirects the
path and not the guarantee". That sentence is now known to be false, and
it is renamed
`test_a_covered_file_under_an_ancestor_junction_is_refused` with the
opposite assertion. The volume-serial property it also covered is
unaffected and is still tested by the injected-serial case.

### Tests

Ten added, in two classes.

`TestAnAncestorCannotRedirectTheInput`:

- the retarget attack, end to end: the capture refuses
  (`UNPROTECTED`, exit 6, zero checks, side-effect file absent) **and**
  the same test then demonstrates that the retarget really is possible on
  this platform while a handle on the object is held, so the refusal is
  load-bearing rather than defensive decoration;
- a repository root reached through a junction is refused before a single
  handle is taken;
- a plain chain is still accepted, including a nested directory;
- the chain walker names the component that redirects.

`TestStructuralDirectoryEventsAreJudged`:

- a directory removed and recreated is a violation;
- a directory renamed and restored is a violation;
- a directory whose timestamp moved is still forgiven — the false
  positive the branch exists to avoid;
- an ignored directory created during a run is still allowed;
- a directory created and removed inside a check is caught end to end
  (`INPUTS_MUTATED`, exit 4).

### Mutation check

Two added, one per half, and both go red:

| Mutant | Result |
|---|---|
| MF23 an ancestor junction is accepted again (root chain and per-path check both disabled) | **red** |
| MF24 a directory event is forgiven for being a directory | **red** |

Twenty-four mutants now, none survived. MF1..MF22 are unchanged.

### The probe grows a fourth group

`scripts/probe_f14_boundary.py` now runs ten cases. Group 4 is case J:
the junction retarget, printing whether the OS prevented it (it does
not), what the lexical path read after the swap (`SWAPPED-B`), and what
the capture did (`UNPROTECTED`, exit 6, zero checks). The transcript
still ends with `BROKEN: B0`, which remains the reconstructed
observation-only design and is there on purpose.

### Evidence

`.gnosis/evidence/20260824T032013Z/` — **977 passed, 67 subtests**, mypy
strict clean over 58 source files, ruff at 19 findings against a baseline
of 19. Clean tree at `29efab4`.

```json
"tree_identity": { "binding": "BOUND", "identical": true,
                   "pre": {"digest": "c613bb70…eba009"} },
"boundary": {
  "verdict": "CLEAN", "observed_events": 65, "violations": [],
  "allowed_events": 15, "machinery_events": 40, "covered_files": 775,
  "locked_identity": { "digest": "c613bb70…eba009" },
  "protection": { "enforced": true, "locked_inputs": 775,
                  "identified_objects": 775, "fully_identified": true,
                  "volume": { "supported": true, "drive_type": "fixed",
                              "filesystem": "NTFS" } } }
```

775 covered inputs, every one of them reached through a chain with no
reparse point in it, locked and identified; 65 observed events and no
violation, now that a structural directory event would be one.

Two artifacts beyond the gate transcripts, added after the capture
returned; `SUMMARY.json` and `input-identities.json` are as the capture
wrote them:

- `mutation-check.f14-round8.txt` — twenty-four mutants, none survived.
- `probe-f14-boundary.txt` — ten cases against this commit. Case J
  records both halves of the answer: `the OS does NOT prevent it: True`
  — the junction really does retarget while the object is held — and
  `boundary: UNPROTECTED, checks that ran: 0, exit_code: 6`.

### What is still not closed

- **F-14 remains OPEN.** Six reviews, six findings this unit's own tests
  did not have.
- **Junctions, mount points and symlinks anywhere in the resolution
  chain are refused, not supported**, alongside submodules.
- Everything named in the previous five addenda stands: attributes can
  still change on a covered input; `.git/` is counted rather than judged,
  which is F-17; the boundary is Windows on a local `fixed` NTFS volume;
  ReFS is a candidate, not a guarantee.
- **F-15..F-18 remain open and untouched.**

## Seventh independent review addendum — 2026-08-24: **FAIL PARCIAL**

Everything the previous six rounds repaired was verified and is
untouched. The new finding is that three separate places all assumed
git-ignored files were outside the boundary, and together they read as a
rule nobody would have written down deliberately:

> ignored by git ⇒ cannot affect the result

`content_fingerprint` does not enumerate ignored files, `covered_paths`
did not add them, and `classify_observation` forgave a change to
anything `git check-ignore` accepted. An ignored file can be a real
input: a `.env`, a local config, a database, a fixture, a plugin — or the
interpreter and the tools in `.venv`, which are what pytest, mypy and
ruff actually are.

### The bypass, reproduced before anything was changed

```
covered paths                     : ['.gitignore', 'a.txt']
ignored-input.txt covered         : False
present in the fingerprint        : False
bytes before the check            : ORIGINAL
what the CHECK read               : MALICIOUS
bytes after the restore           : ORIGINAL
PRE == POST                       : True
violations                        : []
boundary                          : CLEAN
evidence_valid                    : True
all_passed                        : True
exit_code                         : 0
```

A check consumed `MALICIOUS` and the bundle certified itself. Every
guarantee from the previous six rounds held perfectly and none of them
applied, because the file was never in the set they protect.

### What the measurements decided

The obvious repair — cover every ignored file — was measured before it
was chosen, and it does not survive contact with this repository:

| | paths | lock time |
|---|---|---|
| tracked + untracked only (before) | 789 | 0.5 s |
| everything ignored, nested clones expanded | 90,237 | **1,218 s** |
| the policy below | **2,944** | **2.3 s** |

The expansion is 86,073 files inside nested git clones under
`external/repositories/` and `.gnosis/lab/**/candidates|tools|datasets`.
Twenty minutes of locking per capture is not a boundary anybody will keep
running.

The same measurement found something the design had to accommodate:
`.zerker/memory.sqlite`, `-shm` and `-wal` refuse the lock with
`ERROR_SHARING_VIOLATION`, because the ZMem server holds them open. An
OUTPUT class is therefore a necessity and not a convenience — without
one, a live runtime store wedges every capture.

### The repair: three declared classes, and the default is conservative

```
INPUT          covered, locked, identified. Everything git can enumerate
               — tracked, untracked AND ignored — that is not declared
               below. An undeclared path is an INPUT.
OUTPUT         a declared root the checks legitimately write. Events
               there are allowed.
OUT_OF_SCOPE   a declared root the evidence makes no claim about. NOT
               locked, NOT identified, and any event under it is a
               VIOLATION — "outside the claim" is not "allowed".
```

`git check-ignore` is no longer called anywhere in the capture. The
classes are declared in `scripts/capture_evidence.py`, each entry
carrying the reason it is there, and both lists are recorded in the
bundle under `boundary.allowed_writes` and `boundary.out_of_scope` with
the policy stated in `boundary.input_policy`. A reviewer can challenge
any single line of the declaration; nothing is exempt by inference.

**`.venv/` is an INPUT.** It is the toolchain, and 2,130 of the 2,944
locked inputs are in it. That is the single most important consequence of
this round: the bytes of pytest, mypy and ruff are now inside the
boundary rather than outside it by accident.

The `OUT_OF_SCOPE` roots are the six that contain nested clones, each
justified from something already written down — the constitution says
`external/repositories/**` is READ-ONLY SOURCE, and `.gitignore` already
describes the lab directories as reproducible installs and rebuildable
datasets containing nested git repos.

### After the repair

```
covered paths                     : ['.gitignore', 'a.txt', 'ignored-input.txt']
the meddler's write               : REFUSED PermissionError
what the CHECK read               : ORIGINAL
locked_inputs                     : 3      identified_objects : 3
violations                        : ['modified: ignored-input.txt']
boundary                          : INPUTS_MUTATED
evidence_valid                    : False   all_passed : False
exit_code                         : 4
```

Both halves fire: the lock refuses the write, and the attempt is still an
observed event on a covered path, so the capture also refuses to certify.

### Two existing tests were inverted, and their assertions were the defect

`test_a_git_ignored_cache_written_during_a_check_is_not_a_violation` and
`test_an_ignored_directory_created_during_a_run_is_still_allowed` both
asserted that being git-ignored was sufficient. They now assert the
opposite for an undeclared path and the same outcome for a declared one,
which is the distinction the review asked for. Nothing else changed.

### Tests

Sixteen in a new class, covering the review's A–F plus the policy itself:
the input domain includes ignored files; a declared OUTPUT root does not;
a declared OUT_OF_SCOPE root does not; the three classes come from
declaration and not from git; an ignored input a check reads is locked
against it; an ignored-input ABA cannot produce valid evidence; an
ignored file created mid-run is not silently an input; an ignored input
deleted and recreated is caught; the same input cannot be deleted while
locked; a declared cache may change freely; an undeclared ignored path is
not authorised by `.gitignore`; an out-of-scope root that moves
invalidates rather than passes; the bundle records the declared classes;
and the capture script declares all three, with `.venv/` in neither
exemption list.

### Mutation check

MF13's anchor moved with the code it names and its meaning is unchanged.
**MF25** is new and restores the finding in both halves at once — ignored
files leave the input domain AND `git check-ignore` is consulted again —
because either alone leaves the other half of the repair standing.

### The first protected capture falsified one of its own declarations

Worth recording, because it is the mechanism doing its job to its author.
The first full capture under this policy came back **exit 4**, with six
violations, all of them:

```
added:    .gnosis/lab/code-intelligence/datasets/fixture-repo/.codegraph/codegraph.db-wal
modified: .gnosis/lab/code-intelligence/datasets/fixture-repo/.codegraph
removed:  .gnosis/lab/code-intelligence/datasets/fixture-repo/.codegraph/codegraph.db-shm
                                                        … (declared out of scope)
```

`.gnosis/lab/code-intelligence/datasets/` had been declared OUT_OF_SCOPE
on the strength of `.gitignore` calling it rebuildable — and the
code-intelligence suite writes a CodeGraph index into it. The
declaration said nothing writes there and the declaration was wrong.
Under the old rule the writes were git-ignored and would have passed in
silence; under the new one they stopped the capture.

The repair is a carve-out rather than a widening: `classify_path` now
matches OUTPUT **before** OUT_OF_SCOPE, and `.codegraph` is declared an
OUTPUT segment. The generated index may change; the fixture around it is
still unclaimed. Both the ordering and the carve-out have their own
tests.

### What is still not closed

- **F-14 remains OPEN.** Seven reviews, seven findings this unit's own
  tests did not have.
- **An OUT_OF_SCOPE root is described by nothing.** A change made to one
  BEFORE a capture starts is not part of any identity. The bundle names
  the roots so the reader knows the shape of what is not claimed; that is
  a disclosure, not a defence.
- **An ignored INPUT is covered, locked and identified by object, but its
  BYTES are not in `content_fingerprint`**, which is git-based and shared
  with the policy gate and the replay runner. It cannot change during a
  capture; what it was before the capture is recorded as a file id rather
  than a content digest. Hashing `.venv` on every run was not paid for.
- Everything named in the previous six addenda stands.
- **F-15..F-18 remain open and untouched.**

### Evidence

`.gnosis/evidence/20260824T200836Z/` — **992 passed, 67 subtests**, mypy
strict clean over 58 source files, ruff at 19 against a baseline of 19.
Clean tree at `04b851e`.

```json
"boundary": {
  "verdict": "CLEAN", "observed_events": 64, "violations": [],
  "allowed_events": 24, "machinery_events": 40, "covered_files": 2942,
  "out_of_scope": ["external/repositories/", ".gnosis/lab/…", …],
  "allowed_writes": [".git/", "__pycache__", …, ".codegraph"],
  "protection": { "enforced": true, "locked_inputs": 2942,
                  "identified_objects": 2942, "fully_identified": true }
}
```

**2,942 covered inputs, up from 775.** The difference is the ignored
files that were never inside the boundary: 2,130 of them are `.venv`.
Every one is locked and identified, `fully_identified` is true, and both
declared lists are in the bundle for a reviewer to argue with.

Four artifacts beyond the gate transcripts:

- `ignored-input-attack-before.txt` — the bypass as it was: check reads
  `MALICIOUS`, `boundary: CLEAN`, `evidence_valid: true`, exit 0.
- `ignored-input-attack-after.txt` — the same script against the repair:
  the write is `REFUSED PermissionError`, the check reads `ORIGINAL`, and
  the attempt is still an observed event on a covered path, so
  `INPUTS_MUTATED`, exit 4.
- `mutation-check.f14-round10.txt` — twenty-five mutants, none survived.
- `probe-f14-boundary.txt` — the ten earlier break attempts re-run
  against this commit, unchanged.

### Review-package procedure, corrected

`F14_REVIEW_ROUND7.zip` carried 39 files and `FILE_SHA256.txt` listed 37:
the manifest cannot hash itself, and `REVIEW_SCOPE.txt` was written after
it. The generator now writes `REVIEW_SCOPE.txt` first and the manifest
last, so exactly one file — the manifest — is unlisted, and it says so in
its own footer.

## Eighth independent review addendum — 2026-08-25: **FAIL ALTO**

The review took this unit's own residual and made it the finding, which
is the right call: I wrote it down and then shipped around it.

> An ignored INPUT is covered, locked and identified by object, but its
> BYTES are not in `content_fingerprint`.

Three guarantees had been running together under one word. A **file id**
says WHICH object. A **lock** says the object did not change while the
checks ran. Neither says WHAT was in it, and F-14's original sentence is
about bytes: *evidence must identify the exact bytes that passed the
tests*. Two thousand of the inputs — the whole of `.venv`, which is to
say the interpreter and the tools themselves — were inside the boundary
by object and outside it by content.

### Every input is hashed, through the handle that holds it

`handle_digest()` seeks the locked handle to zero and reads it with
`ReadFile`, so the bytes hashed are read through the very handle that is
keeping the file unwritable. Not by path: a second open would be a second
object, and this cannot be pointed anywhere else.

- `LockOutcome.content_digests` — path to SHA-256 for every locked input.
- `LockOutcome.content_digest` — one hash over that map, and deliberately
  a different number from `identity_digest`. One answers "which
  objects", the other "which bytes".
- `LockOutcome.fully_bound` — `locked == len(content_digests)`. Checked
  at the producer, where a handle that cannot be read is a refusal, and
  again at the consumer, where an enforced-but-unhashed lock is
  `UNPROTECTED`. That is a DIFFERENT failure from `fully_identified` and
  says so in its own words.
- `input-manifest.json` — the map, in the bundle, so a third party
  re-derives the claim from the files instead of believing it.

Path, size, timestamps, file id, git status and the lock are all still
recorded. None of them is the identity.

### `.venv`: option (A), and the measurement is why

Measured before choosing, on the input set as the SEVENTH review's
declaration defined it — **2,958 files and 99.4 MB**, hashed in **2.39 s
warm** (37.5 s cold), of which `.venv` is 2,130 files. That is the
comparison the `.venv` decision turns on, and it is not the input set
this round ships: deleting OUT_OF_SCOPE took the real one to 90,245. A
fourth TOOLCHAIN class with a provenance manifest would have been more
machinery for a weaker guarantee and no saving. `.venv` stays an INPUT and is byte-bound
like everything else, so two toolchains reporting the same versions with
different bytes produce different evidence — by the same rule as any
other file, with no special case to get wrong.

### OUT_OF_SCOPE is gone

The review gave two admissible models. Both were tested.

**Model (a) — prove no check can consume it.** A directory handle opened
with `FILE_SHARE_NONE` blocks *listing* the directory and does **not**
block opening files inside it by path; measured, both reads succeeded.
There is no share-mode seal, so the model cannot be demonstrated.

**Model (b) — bind it.** That is what shipped. The class is deleted from
the code, not merely emptied of entries, so no future declaration can
re-create an unbound root. `covered_paths` now expands the directory
entries git reports for nested clones instead of leaving them to be
refused: git declining to descend is not a reason for the evidence to
decline too.

The price, measured rather than estimated: **88,424 files and 2.4 GB**
under what used to be the out-of-scope roots — 1,170 s to hash cold and
1,218 s to lock cold. Paid. A class whose contents cannot be stated is a
silent input channel however loudly it is declared, and "outside the
claim" was doing no work that "unbound" was not also doing.

### OUTPUT cannot smuggle a prior input

Whatever already exists under a declared OUTPUT root when the capture
begins is hashed into `outputs_at_start`. An output is still allowed to
change — that is what the class is for — but a file planted there before
a run and read by a check is now named in the manifest rather than
anonymous. The digest is honest about what it is: bytes at the start, not
bytes throughout.

### Tests

Eight added in `TestEveryInputIsByteBound`, one per mandated item and
three more that pin the invariant itself:

| Item | Test |
|---|---|
| 9 — same path, metadata and file id, different bytes | `test_same_path_and_metadata_different_bytes_differ_in_identity` |
| 10 — changed bytes change the durable identity | `test_changing_the_bytes_between_captures_changes_the_durable_identity` |
| 11 — locked and named but unhashed is not evidence | `test_a_locked_but_unhashed_input_cannot_produce_valid_evidence` (end to end, `evidence_valid` false, exit 6) and `test_an_outcome_holding_an_unhashed_input_is_not_protection` (the classifier alone) |
| 12 — a toolchain artefact is bound by the same rule | `test_a_toolchain_artefact_is_an_input_and_its_bytes_are_bound` |
| 13 — a TOOLCHAIN class with nominal versions | **not applicable**: option (A) was chosen, so there is no such class to test. Item 12 is the form the question takes here |
| 14 — a check depending on a formerly out-of-scope file | `test_a_check_depending_on_a_formerly_unclaimed_file_reads_named_bytes` |
| 15 — content planted under an OUTPUT root | `test_content_planted_under_an_output_root_is_still_named` |
| — | `test_the_manifest_is_re_derivable_from_the_files`, `test_every_locked_input_is_hashed` |

Item 11 is tested twice on purpose. The producer can no longer build an
unbound outcome — the invariant refuses before `acquire` returns — so the
consumer's half is only reachable by handing it one, which
`_ForgetfulLock` does: the real lock with the digests thrown away after
the fact.

The file went from **118 tests to 127**: fourteen added, five deleted,
six adapted. The five deleted are the ones that described OUT_OF_SCOPE —
a class that no longer exists cannot keep a test that says it behaves
correctly — and `test_there_is_no_class_for_bytes_the_evidence_cannot_state`
is what replaces them, asserting on `PathClass` itself that no third
member can come back. The six adapted are fixtures that build a
`LockOutcome` by hand and now have to supply digests;
`test_an_outcome_holding_an_unnamed_handle_is_not_protection` was split
from its byte-invariant twin so that the file-id failure and the
byte failure are each tested alone, because they are different failures
with different wording.

### Mutation check

Four added, one per line of the review's item 16, and MF25's anchor moved
with the code it names. Twenty-nine mutants, none survived.

| Mutant | Removes | Result |
|---|---|---|
| MF26 | the byte binding of every input, ignored ones included — identities are still recorded, the digests are empty | **red** |
| MF27 | the expansion of an ignored nested clone, which is what put the former out-of-scope content inside a bound class | **red** |
| MF28 | the hashing of content that already exists under an OUTPUT root | **red** |
| MF29 | the consumer's check that every locked input was hashed | **red** |

Item 16's second line — "toolchain identity, if introduced" — has no
mutant because no TOOLCHAIN class was introduced. MF26 is the mutant that
covers `.venv`, by covering every input without exception.

### Evidence

`.gnosis/evidence/20260825T011601Z/`, bound to `de74053`.

| | |
|---|---|
| binding | BOUND — pre, post and post-lock identity all `87a56324…` |
| boundary | CLEAN, 0 violations; 64 events, 24 allowed, 40 `.git/` machinery |
| covered inputs | **90,245** — `locked_inputs` = `identified_objects` = `byte_bound_inputs` |
| `fully_identified` / `fully_bound` | true / true |
| `identity_digest` | `ec4dbb5cea3e58bae9cf29f390e333bce48d55942c6318656e313a4af42c5090` |
| `content_digest` | `55d64f5bd9f0597320bc86e197fa60a5a5aa4158f176dd6e185941ca6f4d8bb9` |
| volume | `fixed`, `NTFS`, supported |
| pytest | 1001 passed, 70 subtests, 831 s |
| mypy | clean, 58 source files |
| ruff | 19, the recorded baseline |
| `evidence_valid` / exit | true / 0 |

The two digests are different numbers over the same 90,245 files, which
is the whole point of the round: one answers "which objects", the other
"which bytes".

Re-derivation was checked rather than asserted: a 301-file sample spread
across the manifest re-hashed to the recorded digest, 301 of 301, none
missing and none mismatched. `outputs_at_start` names 207 files that
already existed under a declared OUTPUT root.

Three artifacts beyond the gate transcripts:

- `mutation-check.f14-round11.txt` — 29 mutants, none survived, with the
  baseline and the restored tree both green in the same transcript.
- `probe-f14-boundary.txt` — the ten break attempts of the earlier
  reviews re-run against `de74053`; only B0 is broken, which is the case
  that exists to show why prevention is needed.
- `out-of-scope-seal-attempt.txt` — the measurement behind requirement 7,
  with the script that produced it. A directory held by
  `CreateFileW(GENERIC_READ, FILE_SHARE_NONE, FILE_FLAG_BACKUP_SEMANTICS)`
  refuses to be listed (`PermissionError` 32) and does not stop a file
  inside it being opened by path and read. Model (a) is unavailable, so
  model (b) shipped.

### What is still not closed

- **F-14 remains OPEN.** Eight reviews, eight findings.
- **An OUTPUT's bytes are stated at the start and not throughout.** That
  is the class's definition rather than a gap, but a check that reads an
  output written by an earlier check in the same capture reads bytes no
  digest names.
- **The manifest is bytes at lock time.** It says what was there when
  nothing could change it any more; it is not a history of how the tree
  got that way.
- **Captures are slower and bundles are large.** The input set went from
  2,958 files to **90,245**, of which 58,117 are the read-only clones
  under `external/`. `input-manifest.json` is 14.98 MB and
  `input-identities.json` 13.42 MB, so a bundle is ~28 MB and every later
  capture hashes the earlier bundles as inputs. That compounding is real
  and is not addressed here.
- **F-15..F-18 remain open and untouched.**
- **The full suite is not green, and not because of this unit.** Two
  concurrency tests in `tests/test_work_queue.py` —
  `test_concurrent_workers_never_run_a_brief_twice` and
  `test_a_brief_never_ends_up_in_two_directories_at_once` — fail with
  `PermissionError(13)` on concurrent file operations. Measured rather
  than assumed: the same two tests, isolated, failed **5 times in 20**
  against a pristine export of HEAD `43bc232` and **3 times in 20**
  against this tree, in alternating runs on the same machine. The twelve
  `gnosis` modules those tests import include none of the three this unit
  changed. Same family as the flake recorded in addendum 5, wider than
  first thought; left alone, because making `tests/` deterministic is not
  a change F-14's evidence should carry.

### Three sentences the repair had left behind

The first full capture under this policy came back clean — 90,245 inputs
locked, identified and hashed — and reading its own bundle turned up
three strings that still described the previous model:

- `tree_identity.blind_spot` said git-ignored files are not enumerated by
  `content_fingerprint`. True of that function, and read as an admission
  that `.venv` is outside the evidence, which is now exactly backwards.
  It now says which digest they are missing from and which one has them.
- `classify_observation`'s docstring said a violation is a path "neither
  explicitly allowed nor ignored by git" — contradicting both the code
  and the paragraph four lines below it in the same docstring.
- `capture_evidence.py` justified the `.codegraph` carve-out by "OUTPUT is
  matched before OUT_OF_SCOPE", a mechanism that no longer exists.

None of them changes a guard and no mutant anchors any of them; all three
are the same defect the fourth review named, where the artifact's wording
outlives the mechanism it describes. The capture that found them
(`68338c2`, 90,245 covered files, `content_digest`
`430b79ef81d99701ced39802ce374ceaa88eaec4966a921bee2a26bf93cbfea3`,
boundary CLEAN, `evidence_valid` true) is superseded by the one committed
below and is not kept: it describes a tree that no longer exists.

### The mutation runner has a hole this round exposed

Two runs were killed mid-flight — one by a ten-minute foreground cap, one
by the harness — and each left a mutant applied to `evidence_capture.py`
(MF15, then MF12). The `finally` that restores the sources runs on Ctrl-C
and does not survive a hard kill, exactly as the module docstring says.
Both were caught by re-checking every anchor against the tree and
reverted, and the run that produced the transcript was launched detached
so nothing could stop it at ten minutes. The transcript's own `RESTORED:`
line is the check that matters: it re-runs the suite against the restored
tree, and it is green.
