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

## Evidence

`.gnosis/evidence/20260825T214726Z/`, bound to `fe029f9`.

| | |
|---|---|
| binding | BOUND — pre = post; `head_sha fe029f9…` |
| boundary | CLEAN, 0 violations; 40 `.git` machinery events, **0 judged** |
| covered inputs | 90,314 — `locked` = `identified` = `byte_bound` |
| bundle manifest | `MANIFEST.sha256.json`, 16 files; `verify_bundle` → **verified**; `bundle_digest c3ee6f3b86f8714879bf95a9e77d12c566f6bbdb9f5db59a498f71f243ffdc0f` |
| `identity_digest` | `0314693156fcd58be23652a8c4b811b83e0d112d26bf5faf63d64943b5bd2198` |
| `content_digest` | `7c6ae76972b75fee747027bfbdb0872c503af0b1b1682293a35a8d8f284862e1` |
| pytest | 1051 passed, 70 subtests, 1118 s |
| mypy | clean, 58 source files |
| ruff | 19, the recorded baseline |
| `evidence_valid` / exit | true / 0 |

A normal capture produced 40 `.git` machinery events and judged none — the
`.git` policy does not false-positive on real git bookkeeping. The bundle
manifest was regenerated once after the adversarial transcripts below were
placed in the bundle, so it covers the complete published bundle, not only
what `run_capture` wrote; `verify_bundle` re-derives the whole set.

Three artifacts beyond the gate transcripts:

- `git-machinery-audit.txt` — OS-real: a normal capture leaves the
  machinery fingerprint stable and is CLEAN; a hook install is caught; a
  hook create+delete (ABA) is caught in the interval while a before/after
  machinery fingerprint is blind to it; config rewrite is caught.
- `mutation-check.f14-round15.txt` — 47 mutants, none survived, over
  `fe029f9`, including MF43–MF47 (the manifest, `verify_bundle`, the
  hook/config judgement, the `.sample` exclusion, the `MACHINERY_MUTATED`
  verdict).
- `probe-f14-boundary.txt` — the earlier reviews' attempts re-run; only B0
  breaks, and B0 exists to show why prevention is needed.

## Second independent review addendum — 2026-08-26: **APPROVE_WITH_FINDINGS**

The first review of F-17 approved the implementation provisionally and
raised two blockers. Both are addressed here; F-17 stays OPEN pending
re-review.

### BLOCKER 1 — git worktrees / external gitdir

The first delivery declared "the `.git` machinery contract assumes `.git`
is a directory in the watched tree" as a residual. GNOSIS uses worktrees
in its execution model, so this had to be settled, not deferred.

**OS-real reproduction (Windows/NTFS).** A real repo plus `git worktree
add`:

    worktree toplevel     : …/wt
    worktree git-dir      : …/main/.git/worktrees/wt   (OUTSIDE the tree)
    worktree common-dir   : …/main/.git                (OUTSIDE the tree)
    wt/.git               : a FILE -> "gitdir: …/main/.git/worktrees/wt"

Every trust-relevant path is outside the watched tree: HEAD, index and
`logs/HEAD` in the per-worktree git-dir; **config, hooks and refs in the
common-dir**. A capture run inside the worktree, with a check that
installed a hook into the common dir, returned **CLEAN / evidence_valid
true / exit 0** — the machinery that runs on the next git operation was
tampered and the capture did not see it. Confirmed bypass.

**Fix — fail closed, never degrade.** `git_topology_eligible(repo)`
resolves the topology with `git rev-parse` (treating the `.git` redirect
as adversarial input: it is resolved by git and the resolved paths are
checked to lie inside the canonical tree, never followed blindly) and
returns eligible only when `.git` is a directory and both the git-dir and
the common-dir resolve to `repo/.git`. `run_capture` calls it before
anything runs; an ineligible topology yields **`MACHINERY_UNOBSERVABLE`,
exit 10**, runs no checks, and is never CLEAN. Re-measured: the worktree
capture now returns MACHINERY_UNOBSERVABLE/exit 10 with no checks run; a
capture that rewrites the `.git` redirect itself is refused the same way;
the main repo (a standard `.git` directory) stays eligible and unchanged.

**Topology classification.**

| topology | treatment |
|---|---|
| standard repo (`.git` a directory, git-dir == common-dir == `repo/.git`) | **supported** |
| linked worktree (`.git` a redirect file, external git-dir/common-dir) | **fail closed → MACHINERY_UNOBSERVABLE** |
| submodule working dir (`.git` a redirect file) | **fail closed** (OS-real test with a real `git submodule add`) |
| separate-git-dir clone (`.git` a redirect file) | **fail closed** |
| a `.git` file pointing outside the tree (path confusion) | **fail closed** — resolved and refused, not followed |
| a non-repo directory | eligible — no git machinery to tamper |

No unsupported topology degrades to a protected-looking capture.

### BLOCKER 2 — the real semantics of "tamper-evidence"

The first delivery's manifest, with its `bundle_digest` stored inside the
bundle, is **self-consistency**, not tamper-evidence: an editor who
rewrites a file can recompute the manifest and present a self-consistent
bundle. Formalising the ladder the review asked for:

- **Integrity / self-consistency** — the bundle agrees with its own
  manifest. `verify_bundle(bundle)` provides this: it catches drift,
  corruption, and any edit that does NOT recompute the manifest.
- **Tamper-evidence** — an edit is detectable against a root of trust held
  OUTSIDE the bundle. Provided by `verify_bundle(bundle, expected_digest=…)`
  where `expected_digest` is a `bundle_digest` recorded elsewhere.
- **Authenticity / trusted provenance** — proof of WHO produced it,
  unforgeable. Needs a cryptographic signature over `bundle_digest` with a
  managed key. **Out of scope** (a later Gnosis phase); declared, not
  faked. Nothing here is called "cryptographically tamper-proof".

**What F-17 authoritatively requires.** The frozen audit asks for a
hash-chain (delivered: the manifest) and notes the absence of a signature;
its contrast is the hash-chained ledger, which is tamper-evident because
it is re-verified against a trusted anchor (genesis), not because the
chain lives with the data.

**The root of trust, and it already exists — not invented.** Two anchors
outside the bundle, both already in the repository:

1. **The git commit that carries the bundle.** Git objects are
   content-addressed and the commit DAG is hash-chained; once committed,
   editing a bundle file changes the working tree (git status shows it)
   and presenting a tampered bundle as the committed one requires
   rewriting history to a new commit hash.
2. **`bundle_digest` recorded in this ADR's Evidence section**, a
   *separate committed file*. `verify_bundle(bundle, expected_digest=<that
   value>)` fails closed if the bundle's recomputed digest — manifest
   recomputed or not — does not equal the recorded one.

So tamper-evidence for a Gnosis evidence bundle = the manifest
(`verify_bundle`) checked against the `bundle_digest` recorded in ADR-0027
and anchored by the git commit. The residual: this is only as strong as
the immutability of that committed record; a full anti-forgery guarantee
against an actor who rewrites history needs a signature, which is the
declared out-of-scope limitation. No new root of trust was invented; the
existing commit identity and the committed digest are reused.

### `.git bookkeeping = counted` — audited, and why it is safe

The review asked whether any `.git` path classified as mere bookkeeping
could change executed code, redirect resolution, change which commit/tree
we verify, or alter evidence. Audited:

- **Execute / redirect** — hooks and config — are **judged**
  (`MACHINERY_MUTATED`), not counted.
- **Which commit/tree we verify** — HEAD — is counted, and safe because a
  change to it moves the content fingerprint: measured, a check that runs
  `git checkout` during the interval makes the binding **TREE_MUTATED,
  exit 2**, fail closed. The index and refs are the same: anything that
  changes what git reports about the verified commit changes the pre/post
  fingerprint.
- **The file bytes themselves** are byte-bound by F-14.
- **The rest** — objects, logs, ORIG_HEAD, packed-refs — is inert
  bookkeeping that does not execute, redirect, or change the verified
  commit/tree.

So the counted class contains nothing that can change executed code,
redirect resolution, or the identity of what is verified without being
caught by either the machinery judgement or the binding. The line is not
widened to byte-bind all of `.git` for a green metric; each counted part
is argued safe.

### Relationship to F-14

F-14 stays CLOSED and untouched. `MACHINERY_UNOBSERVABLE` and
`MACHINERY_MUTATED` are fail-closed additions that only strengthen the
contract; no accepted F-14 guarantee is weakened, and no F-14 guarantee
was found false during this unit.

### Tests and mutants added

Ten tests: the topology predicate over a standard repo, a non-repo, a real
worktree, a real submodule, and a `.git` file pointing outside; a worktree
capture failing closed; a standard capture not refused; a HEAD change
caught by the binding; the external anchor turning self-consistency into
tamper-evidence; and the recomputed-manifest attack caught by the anchor.
Three mutants: MF48 (classifier ignores an ineligible topology), MF49
(run_capture runs checks on an ineligible topology), MF50 (verify_bundle
ignores the external anchor).

### Evidence (second review)

`.gnosis/evidence/20260826T020025Z/`, bound to `0629b8b`.

| | |
|---|---|
| binding | BOUND — `head_sha 0629b8b…` |
| boundary | CLEAN, 0 violations; 40 `.git` machinery events, **0 judged** |
| covered inputs | 90,331 |
| bundle manifest | `MANIFEST.sha256.json`, 17 files; `verify_bundle` → verified; **`bundle_digest e1370faa1e3dab3678d712396b087b8ee6d36719812164421d50bc73a9008754`** (this is the external anchor: `verify_bundle(bundle, expected_digest=<this>)` is the tamper-evidence check) |
| `identity_digest` | `924327c9b17f96bc3d1de250690abffc74b83084dbf58d9e62efea939b4a0528` |
| `content_digest` | `6f9e9d36b5c84f5ffd68e42ae22cd4b5969f90d2c0b6e445fccaca4e8feb646e` |
| pytest | 1061 passed, 70 subtests, 1026 s |
| mypy / ruff | clean / 19 |
| `evidence_valid` / exit | true / 0 |

Three artifacts beyond the gate transcripts:

- `git-worktree-audit.txt` — OS-real: a real `git worktree add`, the
  topology (all trust-relevant machinery outside the tree), and the
  fail-closed result (MACHINERY_UNOBSERVABLE, exit 10, no checks run).
- `mutation-check.f14-round16.txt` — 50 mutants, none survived, over
  `0629b8b`, including MF48–MF50 (the topology gate and the external
  anchor).
- `probe-f14-boundary.txt` — the earlier reviews' attempts re-run.

## Third independent review addendum — BLOCKERS A, B, C

F-17 stays OPEN. This addendum records the third review, scoped by the
operator to three blockers. Only BLOCKER A required a production change;
B is already satisfied by the existing design and is demonstrated rather
than coded; C is a reported GAP with a proposed minimal primitive, not an
implementation. Method: reconstruct → threat-model → OS-real / in-code
evidence → design → implement, on git **2.55.0.windows.4**.

### BLOCKER A — the counted `.git` surfaces that redirect resolution

**The finding, demonstrated.** The machinery judgement judged exactly two
surfaces (`hooks`, `config`) and COUNTED every other `.git` write,
including the surfaces that redirect git's OBJECT / REF / ANCESTRY
resolution. That is a real hole, not a naming worry, and it corrupts the
one thing F-14/F-17 exist to make honest: the tree-identity binding.

- **refs/replace/**** — OS-real: a `refs/replace/<C1> → <C2>` ref makes
  `git cat-file HEAD:file` return C2's bytes, `git diff HEAD` report a
  diff, and `git status` say `M file`, **with C1's original object bytes
  unchanged on disk**. `GIT_NO_REPLACE_OBJECTS=1` reverses all of it, and
  `git rev-parse HEAD` (the value of the ref) is *not* substituted — so
  the git-head check is untouched, but the binding's `git diff HEAD` /
  `git status` are not. In-code: `content_fingerprint` (the F-14/F-17
  binding primitive) recomputes a different `patch_sha256` /
  `status_sha256` under a replace ref, with `head_sha` unchanged. A
  replace ref active at capture start is present at BOTH endpoints, so the
  binding certifies a false tree identity with `identical: true`, and
  nothing else catches it — the replace surface is `.git`,
  counted-not-judged.
- **packed-refs** — the assumption `packed-refs → inert` is **REVOKED and
  refuted by demonstration**. `git pack-refs --all` moves a replace ref
  into `packed-refs` and it still redirects; and a **raw append to
  `.git/packed-refs`** (no `git replace` command) installs a replace ref
  that `for-each-ref` sees and object resolution honours. packed-refs is
  therefore a REF backend that can carry an OBJECT_RESOLUTION redirection.
- **objects/info/alternates**, **objects/info/http-alternates** — redirect
  object lookup to an external store (OBJECT_RESOLUTION; content-addressing
  bounds substitution, but it is a trust-boundary redirection to a path
  outside the tree).
- **info/grafts** — still honoured by git 2.55 (deprecated, prints a hint):
  truncated ancestry, `rev-list --count` dropped. ANCESTRY.
- **shallow** — `.git/shallow` set `is-shallow-repository=true` and
  truncated ancestry. ANCESTRY.
- **config.worktree** — not read in a standard repo UNLESS
  `extensions.worktreeConfig` is enabled; when it is, it is read and honours
  executable keys (`core.fsmonitor` demonstrated). EXECUTION/CONFIG,
  conditional on the extension.
- **HEAD / index / refs/heads** — a persisted change moves the binding
  (`git rev-parse HEAD` / `git diff HEAD`), caught as `TREE_MUTATED`
  (measured). REF_RESOLUTION / TREE_IDENTITY, safely counted for the
  persisted case.

**Classification (semantic category → treatment after this repair).**

| surface | category | treatment |
|---|---|---|
| `refs/replace/**` | OBJECT_RESOLUTION | **judged**: refused if active at start (MACHINERY_REDIRECTED), judged if written in the interval (MACHINERY_MUTATED) |
| `packed-refs` | REF_RESOLUTION (replace carrier) | **judged** in the interval; an active packed replace ref is caught by the start gate via `for-each-ref` |
| `objects/info/alternates`, `objects/info/http-alternates` | OBJECT_RESOLUTION | **judged** (start gate + interval) |
| `info/grafts` | ANCESTRY | **judged** (faithful-repo precondition) |
| `shallow` | ANCESTRY | **judged** (faithful-repo precondition) |
| `config.worktree` | EXECUTION/CONFIG | **judged** in the interval (config's per-worktree twin) |
| `commondir` | TOPOLOGY/REDIRECTION | **judged** in the interval (defence; only exists in worktrees, already refused by the topology gate) |
| `config`, `hooks/**` (non-`.sample`) | EXECUTION/CONFIG | judged (unchanged, F-17 first delivery) |
| `HEAD`, `refs/heads/**`, `index`, `sharedindex.*` | REF_RESOLUTION / TREE_IDENTITY | counted; a persisted change moves the binding → `TREE_MUTATED` (measured) |
| `objects/**`, `logs/**`, `ORIG_HEAD`, `*.lock`, `COMMIT_EDITMSG` | CONTENT_OBJECT / BOOKKEEPING_INERT | counted (content-addressed or inert; do not redirect or execute) |

**The fix (additive, two halves mirroring F-14's snapshot + interval).**

1. `git_evidence.git_resolution_faithful(repo) -> (bool, reason)`: a
   read-only START gate. Refuses (fails closed) when a redirection is
   ALREADY ACTIVE — any `refs/replace/*` ref (loose OR packed, via
   `for-each-ref`), a shallow repository, or a non-empty `alternates` /
   `http-alternates` / `grafts`. `run_capture` calls it after
   `git_topology_eligible`; an active redirection yields
   **`MACHINERY_REDIRECTED`, exit 11**, no checks run, never CLEAN. This
   catches a PRE-EXISTING replace the observer cannot see.
2. `_is_git_resolution_redirect(path)`: an interval classifier. A WRITE to
   any redirect surface during the capture is judged like a hook →
   **`MACHINERY_MUTATED`, exit 9** — so an ABA (install+remove inside the
   interval, e.g. a raw packed-refs edit) is caught, which the endpoints
   are blind to.

**Grafts / shallow, stated honestly.** They change ANCESTRY, which the
current binding and checks do NOT consume (`git diff HEAD` is unaffected —
measured), so they do not corrupt today's evidence. They are refused as a
**faithful-repository precondition**, not as a demonstrated evidence
corruption, at zero cost (the product repo is neither shallow nor grafted).
This distinction is offered for the independent review to accept or narrow.

**Not an F-14 reopen.** F-14 hashes each covered input's bytes THROUGH the
handle that holds it, never through git, so a replace ref cannot move a
`content_digest`; the 90k byte-bound inputs are untouched. What refs/replace
corrupts is the git-DERIVED identity fields the bundle carries, which F-14
explicitly assigned to F-17 (".git counted-not-judged belongs to F-17").
No accepted F-14 guarantee is contradicted. This judgement is flagged for
the independent review rather than acted on as a silent reopen.

**The unknown-`.git` line, deliberately not moved.** The catch-all still
COUNTS an unrecognised `.git` write rather than failing closed on it.
Flipping it to fail-closed-on-unknown was rejected: it is fragile across
git versions (git writes many transient files) and the operator's own rule
forbids protection without demonstrated effect. Residual: a genuinely novel
execute/redirect surface a future git introduces would be counted until
classified.

### BLOCKER B — Gnosis-managed worktrees: already satisfied, demonstrated

**Reconstruction (ADR-0007/0009 + code).** GNOSIS mints per-task worktrees
via `WorktreeManager` (`kernel/worktree.py`), provenance-recorded in a
`.<task_id>.worktree.json` marker outside the tree, used as the CLI child's
`exec_root` (`kernel/engine.py`), with landing by `WorkIntegrator` in a
throwaway detached staging worktree (`kernel/integration.py`).

**The decision: does F-17 need to run inside a linked worktree in normal
operation? NO — demonstrated architecturally.**

- The F-17 tool `run_capture` has **zero callers in `src/`**. Its only
  production invocation is `scripts/capture_evidence.py`, hard-anchored to
  the main checkout (`REPO = __file__.parent.parent`), and the working
  method runs captures from the main checkout, never a worktree.
- What runs INSIDE worktrees is the lightweight `capture_git_evidence`, the
  verifier, and the CLI reviewers — none of them the F-17 tamper-evidence
  tool.
- The eligibility gate checks the CAPTURED path's own topology; a main
  checkout that merely HAS linked worktrees registered stays eligible
  (its `.git` is a directory, git-dir == common-dir == `repo/.git`).

So the collision named in the first delivery is **latent, not actual**. If
someone ever wired a governed run whose `Verifier` shelled out to the F-17
capture with cwd = a task worktree, every such run would exit 10 /
`MACHINERY_UNOBSERVABLE` and fail closed — safely and loudly, by design.

**Arbitrary external gitdir stays refused, demonstrated.**
`git_topology_eligible` refuses a `.git` FILE **before** resolving it
(`.git` file → refused, never followed), so a `.git` redirect pointing at
an external/other gitdir (path confusion, foreign repository identity) is
refused — reproduced in-code against a `.git` file pointing outside the
tree, a real linked worktree, and a real submodule working dir.

**Design IF a future milestone needs capture inside a Gnosis-managed
worktree** (not built now — no production path needs it): admit a worktree
ONLY when its provenance is proven first — the `WorktreeManager` marker
must exist and bind `{canonical repository, canonical worktree root,
canonical gitdir, canonical common-dir, creator/owner}`; every path is
resolved, canonicalised and checked against the recorded identity; a
git-dir/common-dir that does not match the recorded expectation FAILS
CLOSED. A `.git` redirect is never followed because git accepts it. An
arbitrary external gitdir and an unknown topology stay refused. Until such
a milestone exists, `linked worktree → fail closed` is the correct,
demonstrated behaviour.

### BLOCKER C — TRUST ANCHOR GAP (reported, not silently invented)

The ladder is unchanged: **self-consistency ≠ tamper-evidence ≠
authenticity**, authenticity still out of scope.

**Requirement:** the anchor holding `expected_digest` must lie outside the
surface the producer/worker who writes the bundle can rewrite —
`worker write-authority ∩ anchor write-authority = ∅`.

**Finding: no existing Gnosis primitive satisfies this. GAP.**

- Every durable candidate — `RunLedger` (`kernel/ledger.py`), the claims
  plane (`kernel/claims.py`), `.gnosis/state/**`, `BriefRecordStore` —
  lives INSIDE `<repo>/.gnosis/**` or `runs/`, inside the git working tree
  the bundle producer writes; the tracked `.gnosis/state/*.json` sit in the
  very commits that carry the bundle. `worker ∩ anchor` is non-empty
  everywhere.
- `.gnosis/state/**` is specifically the WORST candidate: it is a declared
  capture OUTPUT (`ALLOWED_WRITES`), writable during the very capture it
  would anchor.
- Even `RunLedger`, the most disciplined, verifies only against the
  constant `GENESIS_HASH = "0"*64` with unkeyed SHA-256: it resists partial
  edits and races, **not** whole-file regeneration by a same-user process
  (its own docstring concedes this). Today's actual producer — the agent
  running `capture_evidence.py` in the main checkout — has total write
  authority over ALL candidates including ADR-0027, so moving
  `expected_digest` into any of them changes the file format, not the
  authority model.

**Proposed minimal primitive (no Cosign/in-toto/TUF/PKI/keys):** reuse
`RunLedger`'s append-only hash-chain mechanics but change its LOCATION and
WRITER — an anchor ledger at `source_repo.parent/.gnosis-anchors/…jsonl`
(the sibling-of-repo convention `.gnosis-integration` already uses),
written only by the Director/Kernel publication step (never by the checks,
never in `ALLOWED_WRITES`), each entry binding
`{task_id, run_id, head_sha, bundle_path, bundle_digest}`. This moves the
anchor OUT of every worktree checkout, out of `git status`, and out of any
commit. Verification: `verify_chain()` on the anchor ledger, then
`verify_bundle(bundle, expected_digest=entry.bundle_digest)`. Honest
residual: against a same-OS-user adversary the anchor file is still
regenerable (unkeyed hashes, constant genesis); the real gain is shrinking
the trusted out-of-band surface to a single 64-char tail hash the operator
records — anything stronger (distinct OS identity, off-machine replica) is
operational hardening, and full anti-forgery remains the declared
out-of-scope authenticity rung. **This primitive is proposed, not built —
it is its own unit under Dependency/authority review.**

### Relationship to F-14

F-14 stays CLOSED and untouched. `MACHINERY_REDIRECTED` is a fail-closed
addition that only strengthens the contract; no F-14 guarantee is weakened,
and none was found false.

### Tests and mutants added

Fifteen tests (`TestGitResolutionMustBeUnredirected`): the predicate; the
gate over a clean repo, a non-repo, a loose replace ref, a packed replace
ref, alternates, grafts, a shallow repo, an empty redirection file; the
in-code proof that a replace ref fools `content_fingerprint`; and end-to-end
— a pre-existing replace ref failing closed (MACHINERY_REDIRECTED, exit 11,
nothing ran), an ABA `git replace` and a raw packed-refs replace injection
judged in the interval, and a standard capture not refused. Six mutants
(MF51–MF56): the predicate returns False; run_capture ignores the gate; the
classifier drops the MACHINERY_REDIRECTED branch; `git_resolution_faithful`
stops looking for replace refs; it stops checking alternates/grafts; the
interval classifier stops routing redirects to the judged set.

### Evidence (third review)

`.gnosis/evidence/20260826T074918Z/`, carrying the third-review artifacts,
`verify_bundle` → verified.

| | |
|---|---|
| directed suite | 202 passed (`test_evidence_binding.py`), 204 with `test_git_evidence.py`, incl. the 15 new `TestGitResolutionMustBeUnredirected` tests |
| mutation | `mutation-check.f14-round17.txt` — **56 mutants (MF1–MF56), 0 survived**; baseline and restored GREEN (204 passed). MF51–MF56 target the BLOCKER A guarantees |
| OS-real audit | `git-resolution-audit.txt` — refs/replace (loose / packed / raw packed-refs), alternates, grafts, shallow, config.worktree; start gate refuses each, interval classifier judges each; pre-existing replace → MACHINERY_REDIRECTED (exit 11, 0 checks), ABA → MACHINERY_MUTATED (exit 9), clean repo stays CLEAN |
| full capture over `ff37069` | `capture-summary.json`: **BOUND**, boundary **CLEAN** (0 violations; 41 machinery events, **0 judged**), `evidence_valid` true, **90,350 byte-bound inputs**, `identity_digest d9cd7e54…`, `content_digest 329d904f…`; mypy clean (58 files); ruff at the 19 baseline; git-head `ff37069…` |
| pytest | 1075 passed, 70 subtests; the sole failure is the pre-existing work-queue timing flake (`test_concurrent_workers_never_run_a_brief_twice`, ~1 in 5, `docs/NEXT_ACTIONS.md`), NOT F-17 — every F-17/F-14 test is in the 1075 passed |
| bundle manifest | `MANIFEST.sha256.json`; `verify_bundle` → verified; **`bundle_digest ed3aef4843530fe8d4a8ec5937a0eb48e1c3fec8dba3587e78f13ebf40f8446b`** (external anchor: `verify_bundle(bundle, expected_digest=<this>)` is the tamper-evidence check; a wrong digest is refused) |

**On the bundle shape.** The full `run_capture` bundle hashes ~90k inputs
(~2.4 GB of external-repository sources) through their handles before the
checks run. On this workstation's slow synced volume that cold pass plus the
full suite exceeds the environment's long-run limit; only a warm-cache run
completed, and its SUMMARY is `capture-summary.json` here (BOUND / CLEAN /
evidence_valid true over `ff37069`). The third-review evidence is therefore
delivered as this verify_bundle-verified bundle of the review's artifacts,
with the completed capture's SUMMARY inside it; the full bundle is
reproducible with a warm cache via `scripts/capture_evidence.py` run
detached from the main checkout. `CAPTURE-NOTE.md` states this in the bundle.

### Decisions this repair makes that need independent review

1. **BLOCKER A judged set.** refs/replace, packed-refs, alternates,
   http-alternates, config.worktree, commondir judged as machinery; grafts
   and shallow refused as a faithful-repository precondition (ANCESTRY, not
   demonstrated to corrupt today's binding). Confirm the line, especially
   whether grafts/shallow should be judged or merely counted.
2. **Not an F-14 reopen.** The review judges that refs/replace corrupts only
   the git-derived identity fields (F-17's charge), not F-14's byte-binding.
   Confirm no accepted F-14 guarantee is contradicted.
3. **Unknown-`.git` stays counted**, not failed-closed. Confirm this is the
   right trade against git-version fragility.
4. **BLOCKER C is a reported GAP**, not an implementation; the proposed
   anchor-ledger-outside-the-tree primitive is unbuilt and needs its own
   authority review.
5. **Evidence delivered as an artifact bundle** with the completed capture's
   SUMMARY, not a fresh full `run_capture` bundle, for the environment
   reason above. Confirm this is acceptable or require a warm-cache re-run.
