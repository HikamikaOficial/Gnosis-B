# ADR-0027 — The evidence that sustains the claims must be as protected as the claims

- Status: PROPOSED — repaired, PENDING an independent review. F-17 stays
  OPEN in `docs/V1_COMPLIANCE_MATRIX.md` until one returns without findings.
- Date: 2026-08-25
- Repairs: **F-17** (`docs/V1_TRACEABILITY_AUDIT.md`) — and F-17 only.
  F-15, F-16 and F-18 remain open and untouched.
- Builds on ADR-0026 (F-14). The bundle whose bytes F-14 made honest is
  the same bundle this ADR makes tamper-evident.

## The finding, reconstructed from the frozen audit

The authoritative definition (`docs/V1_TRACEABILITY_AUDIT.md`, F-17):

> **tamper-evidence** — `SUMMARY.json` does not contain HEAD or status
> (they live in separate `.txt` files) and the bundle has no hash-chain
> and no signature. Internal contrast: `kernel/ledger.py` is an
> append-only hash-chained ledger, re-verified whole before extending. The
> evidence that sustains the project's claims is the least-protected part
> of the project.

Three concrete complaints, and what is true of each now:

1. **HEAD/status not in SUMMARY.** Already resolved incidentally by F-14's
   rounds: `SUMMARY.json` carries `tree_identity` with `head_sha`,
   `status_sha256`, the patch digest and both content/identity digests,
   before and after. The central claims are no longer scattered across
   `.txt` files. Confirmed, not re-done here.
2. **No hash-chain over the bundle.** The core of what remained, and what
   this ADR repairs.
3. **No signature.** A cryptographic signature needs key management the
   project does not have; it is a declared limitation below, not faked.

**Scope reconstruction — what F-17 is, and is not.** The authoritative
finding is about the BUNDLE. During F-14 I repeatedly tagged a separate
residual — "`.git/` writes are counted, not judged" — as "F-17's
subject". That tag was mine, not the frozen audit's. The audit's F-17 is
tamper-evidence of the evidence, and the `.git/` machinery-during-capture
is a genuine second face of the SAME property: a hook installed while the
checks run tampers with the machinery that produced the evidence. Both are
repaired here, and the distinction is stated so no one mistakes the second
for the authoritative wording.

## Root cause

The project hardened the ledger (append-only, hash-chained, re-verified)
and left the evidence bundle — the thing a reviewer actually reads to
believe a claim — as a directory of loose files that anything could edit
after capture with nothing to notice. And the capture judged every covered
input's bytes (F-14) while forgiving everything under `.git`, including the
two parts of `.git` that can execute or redirect: hooks and config.

## The threat

- **Post-capture edit.** Change `evidence_valid` in `SUMMARY.json`, or
  delete a failing line from `pytest.stdout.txt`, after the capture. The
  bundle still reads as proof.
- **Machinery tamper during capture.** A check installs `.git/hooks/pre-commit`
  (arbitrary code that runs on the next git operation) or rewrites
  `.git/config` (what a filter runs, where a push goes). The tree the
  checks ran against is sound; the machinery that ran them is not, and the
  capture said CLEAN. Reproduced before the repair.

## Prior behaviour

- No manifest over the bundle; no `verify_bundle`.
- `classify_observation` forgave every `.git/` write as "machinery",
  counted not judged.

## The policy

### The bundle is hash-chained, like the ledger

`write_bundle_manifest` runs last in `run_capture`, after `SUMMARY.json`,
and writes `MANIFEST.sha256.json`: the SHA-256 of every file in the bundle,
plus one `bundle_digest` = `hash_canonical` over that sorted map. It cannot
hash itself, so it names itself the one unlisted file and says so — the
rule the review-package manifest already followed.

`verify_bundle(path)` re-derives it and fails closed on any of: a missing
or unparseable manifest; a file present-but-unlisted, listed-but-absent, or
hashed differently; or a `bundle_digest` that disagrees with a recompute
over the files map. Only an exact match verifies. A reviewer re-runs the
claim rather than trusting it, exactly as the mutation check is re-runnable
rather than asserted.

### `.git` is judged where it can execute or redirect, counted elsewhere

Most writes under `.git` are git's own bookkeeping during a read — index,
refs, logs, ORIG_HEAD, packed-refs, loose objects — and stay counted, or
the mechanism would fail on every ordinary git operation (measured: a
normal capture produces ~37 such events and stays CLEAN). Two parts are
different: `_is_git_machinery_tamper` judges any observed write to
`.git/hooks/**` (except the inert `.sample` examples) or `.git/config`,
including a stream on either. Such a write is `MACHINERY_MUTATED`, exit 9,
its own verdict because the operator response differs: the tree was sound,
the machinery was tampered.

This is caught IN THE INTERVAL by the write observer, so a hook created and
deleted inside the run (an ABA) is caught too — measured, a before/after
machinery fingerprint is blind to that, the same lesson F-14 learned about
endpoints. The judged set is exactly the set `_machinery_fingerprint`
already treats as dangerous, so the two notions of "dangerous `.git`" agree.

## `.git/` treatment, case by case

| change | treatment | why |
|---|---|---|
| `.git/hooks/<name>` (not `.sample`) written/created/deleted | **judged → MACHINERY_MUTATED** | code that runs on the next git op |
| `.git/config` written | **judged → MACHINERY_MUTATED** | chooses filters, remotes |
| a named stream on a hook or on config | **judged** | a write channel to the same |
| `.git/hooks/*.sample` | counted | git ships them inert |
| `.git/index`, `refs/**`, `logs/**`, `ORIG_HEAD`, `packed-refs`, `objects/**`, `MERGE_*`, `FETCH_HEAD`, `*.lock` | counted (machinery) | git's own bookkeeping during reads |
| anything else under `.git` | counted (machinery) | not the execute/redirect surface |

## Guarantees this establishes

- A bundle carries a re-derivable manifest; any file added, removed or
  changed after capture is detected by `verify_bundle`, fail-closed.
- A hook or config written during the capture — persisted or reverted —
  makes the capture `MACHINERY_MUTATED`, never CLEAN.
- Ordinary git bookkeeping during a read stays counted and does not
  false-positive (measured).

## Guarantees this does NOT establish — declared, not hidden

- **No cryptographic signature.** The manifest detects any edit that does
  not also recompute the manifest; an editor with write access who
  recomputes `MANIFEST.sha256.json` to match is not stopped by a hash
  alone. That is what a signature over `bundle_digest` would prevent, and
  it needs key management (a keystore, a signing identity) that is out of
  scope and a separate unit under Dependency Admission. The external
  anchor available today is git itself: once the bundle is committed, its
  blobs are content-addressed, so an edit shows as a working-tree change.
  This matches the ledger's own protection level, which is also
  recomputable by a local writer and relies on verification plus an
  external anchor. Stated as a limitation, not a claim.
- **The `.git` machinery contract assumes `.git` is a directory in the
  watched tree.** A linked worktree or a submodule whose git-common-dir
  lies outside the watched tree keeps its hooks/config where the observer
  cannot see them; that case is out of this contract, the same family as
  F-14 refusing submodules and junctions. A repository whose `.git` is a
  file is not covered by the machinery-tamper judgement.
- **`.git` bookkeeping is counted, not byte-bound.** The machinery events
  are counted; only the execute/redirect surface is judged. A tamper of,
  say, a packed object is not judged here (and is not an execute/redirect
  channel).

## Relationship to F-14

F-14 is closed and none of its accepted contracts change. This ADR only
ADDS: a manifest file to the bundle, and a judged subset of a
previously-counted class. No F-14 guarantee is weakened —
`fully_identified`, `fully_bound`, `COMPLETE`, the lock and the observer
are untouched. The new `MACHINERY_MUTATED` verdict strengthens the
boundary; it does not relax it.

## Consequences

- The bundle grows by one small file (`MANIFEST.sha256.json`).
- A previously-CLEAN capture that writes a hook or config now fails closed.
  No legitimate check does this; a normal capture is unaffected (measured).
- `MACHINERY_MUTATED` (exit 9) joins the exit vocabulary.
