# ADR-0026 — Evidence that cannot name its own bytes is a transcript, not proof

- Status: ACCEPTED
- Date: 2026-08-22
- Repairs: **F-14** (`docs/V1_TRACEABILITY_AUDIT.md`) — and F-14 only.
- Independent review: **OUTSTANDING.** This unit is delivered for review,
  not declared closed by it. F-14 stays OPEN in
  `docs/V1_COMPLIANCE_MATRIX.md` until an independent pass returns
  without findings. That is the rule ADR-0025 had to learn three times,
  and it applies to a repair that looks clean on its first pass exactly
  as much as to one that does not.
- Tests: `tests/test_evidence_binding.py` — 36 tests, 5 subtests.
- Mutation check: `scripts/mutation_check_f14.py` — **nine mutants, none
  survived**, declared as data so a reviewer re-runs the claim rather
  than reading it.
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
