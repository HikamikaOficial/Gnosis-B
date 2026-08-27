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

## Fourth review — BLOCKER C resolution: TRUST ANCHOR AUTHORITY SEPARATION NOT YET AVAILABLE

The third-review independent verdict approved BLOCKER A, provisionally
approved B, and left **BLOCKER C blocking**. Its instruction was explicit:
the anchor separation must be of AUTHORITY, not pathname
(`worker_write_authority ∩ anchor_write_authority = ∅`); if the current
architecture cannot separate those authorities, **report the limitation and
do not build a false separation.** This addendum records the outcome.

### Threat model (as set by the review)

- **T1 — accidental corruption.** A legitimate process corrupts evidence by
  accident. **Defeated today** by the manifest + `verify_bundle` (any
  post-capture change is detected).
- **T2 — compromised/malicious worker** with normal authority over its
  worktree/repository: rewrites the bundle, recomputes the manifest,
  substitutes `bundle_digest`, rewrites the anchor record, hides it. **This
  is F-17's minimum bar for tamper-evidence, and it is NOT defeated today.**
- **T3 — Director/Kernel compromised** — out of scope unless the contract
  says otherwise.
- **T4 — full OS/user control** — out of scope without a cryptographic root.

### Trust-boundary model, measured against the code

For an anchor to defeat T2 there must be a boundary the worker cannot cross:
the worker MAY produce the bundle and its digest, and MUST NOT be able to
write/modify/delete the trusted anchor. **No such boundary exists in the
current implementation, and Gnosis documents this itself.**

- The worker is launched by `CLIRunner.run` →
  `subprocess.Popen(argv, cwd=…, env=…)` (`runner/claude_cli_runner.py:97`)
  with **no `user=`, no restricted/low-integrity token, no job object, no
  sandbox, no ACL**. It runs as the **same OS user** as the Director/Kernel
  (`kernel/engine.py:1038`), and F-17 captures require it to run arbitrary
  shell (git, pytest), so it has full filesystem write as that user.
- `--permission-mode plan` is "a permission-layer promise, not a sandbox"
  (`adapters/cli_review.py:49`); the kernel's backstop is a DETECTIVE
  before/after fingerprint, not prevention.
- Gnosis's own machine-checked enforcement matrix
  (`kernel/policy.py:766`, taxonomy `HARD / SANDBOX_APPROX / PROMPT_ONLY /
  IGNORED` at `:661`) records worktree isolation and `reviewer_read_only` as
  **`SANDBOX_APPROX`** ("cwd scope only; an absolute path escapes it";
  "detection after the fact, not prevention… does NOT constrain writes to
  the SOURCE checkout, a sibling worktree, or anywhere else the process can
  reach"). The `HARD` filesystem entries (`file_lock/single_writer`,
  `claims/no_stale_write_after_deposition`) are concurrency/ownership
  serialization **within one trust domain**, not a boundary between the
  worker and a privileged store. No entry claims OS-user separation, ACL,
  container, or a mediating privileged service.
- `RunLedger`'s own docstring: "Filesystem-level immutability is a hardening
  step left for a later milestone" (`kernel/ledger.py:5`); it verifies only
  against `GENESIS_HASH="0"*64` with unkeyed SHA-256 — resists partial edits
  and races, not whole-file regeneration by the same user.

### Why `source_repo.parent/.gnosis-anchors` is REJECTED (a false separation)

The third-review-proposed sibling-of-repo ledger is a **convention**, not an
authority boundary. A T2 worker running shell as the same OS user writes that
sibling path and recomputes its unkeyed chain exactly as it can the in-repo
file. `anchor_path != repository_path` is satisfied; `worker ∩ anchor = ∅`
is NOT. Per the review, this is not built.

### Attack matrix (review §12), current reality

A/B/C (edit bundle ± manifest ± ADR) are caught **only if the anchor is held
by a principal the editor is not** — which for T2 is false today: the same
worker owns bundle, manifest, ADR, git history and every candidate ledger.
D/E/F (worker modifies / deletes / forges the anchor) all **succeed** today,
because the worker has write authority over every anchor location. G/H/I
(missing / corrupt / broken-chain anchor → fail closed) are enforceable in
code and would be honoured, but they protect against T1, not T2. J/K/L
(anchor bound to a different HEAD/run; replay; concurrent runs) are only
meaningful once an unforgeable anchor exists.

### Finding

**`TRUST ANCHOR AUTHORITY SEPARATION NOT YET AVAILABLE`.** Against T2, an
enforced worker∖anchor separation is unreachable in the current single-OS-user
architecture without introducing exactly what the review excludes:

1. **A real OS boundary** — run the worker under a distinct OS user, or a
   restricted / lower-mandatory-integrity token (Windows MIC), and set the
   anchor store to a higher integrity level / an ACL the worker's SID cannot
   write; or a job-object/sandbox/container; or a privileged mediating
   service the worker cannot bypass. All are **new runner infrastructure**,
   none exists today. This is the minimal non-crypto path and it is a
   milestone of its own (and touches ADR-0007/0009's isolation model, which
   the enforcement matrix already flags as `SANDBOX_APPROX`).
2. **A cryptographic authenticity root** — a signature over `bundle_digest`
   with a key the worker cannot read. This is the **AUTHENTICITY** rung,
   explicitly deferred.

The only lever available now — an operator recording the 64-char
`bundle_digest` tail out-of-band — works **only because a human, not the
worker, holds it**; it is not an enforced code boundary and cannot be
automated within the worker's authority.

### The honest current guarantee (scoped, not overclaimed)

F-17 today provides: SELF-CONSISTENCY (manifest/`verify_bundle`, defeats T1)
and TAMPER-EVIDENCE against a **non-adversarial or non-same-user** actor via
the git-commit + recorded-digest anchor. It does **NOT** provide
tamper-evidence against T2 (a malicious same-OS-user worker), because that
requires an authority boundary the platform does not yet enforce. Nothing in
the repo may claim T2 resistance until (1) or (2) above exists.

### States (review §10) — recorded, not yet coded

Keep `SELF_CONSISTENT` (have) distinct from `ANCHORED` (requires the
authority-separated store) and `AUTHENTICATED` (requires crypto). `ANCHORED`
is deliberately **not** introduced in code now: a state nothing can produce
under an enforced boundary would be a false promise, exactly what §8 forbids.
`verify_bundle(bundle, expected_digest=X)` stays a pure hash primitive; a
future `verify_anchored_bundle(...)` obtains `X` from the authorized store —
built only once that store's write authority is enforced.

### §14 — the unknown-`.git` contractual decision (formalized, not re-audited)

Independent of C, the review required one contractual decision before any
future closure: **an UNKNOWN trust-sensitive `.git` surface must never be
treated as inert bookkeeping.** Decision, recorded here as the contract to
implement at closure (no code lands now — the review forbids re-expanding the
git-machinery audit unless C surfaces a new interaction, and C did not):

- **Declared scope.** The machinery guarantee is demonstrated for the git
  implementation family it was audited on: **git ≥ 2.x with the `files` ref
  backend and loose refs (measured on 2.55.0.windows.4)**. A different ref
  backend (e.g. `reftable`) or a materially different version is
  **out of the demonstrated scope** until re-audited.
- **The rule.** Within the classifier's machinery-evaluation area (`.git`),
  a path that is neither in the KNOWN-inert content-addressed/bookkeeping set
  (objects, logs, ORIG_HEAD, FETCH_HEAD, `*.lock`, COMMIT_EDITMSG, index,
  refs/heads, HEAD — each argued safe: content-addressed, or caught by the
  binding) nor in the KNOWN-judged redirect/execute set (this ADR's tables)
  is **UNKNOWN**, and `UNKNOWN != INERT`: it must **fail closed** (lose the
  F-17 guarantee), not be silently counted. The rule must be minimal — it
  must not reclassify a known content-addressed object write as unknown, and
  it must not create absurd cross-version fragility for surfaces already
  argued safe.
- **Goal.** Prevent `new trust-sensitive git machinery → not recognized →
  silently counted → CLEAN`.

This closes the third-review open decision #3 as a **decision** (was: "unknown
stays counted") — the contract is now "unknown fails closed within the
declared git scope"; the implementation is deferred to the closure unit
because it is a machinery change requiring a fresh capture the environment
must be able to produce.

### Verdict of this unit

BLOCKER C is **not resolvable in code today without out-of-scope
infrastructure**, and building a pathname-only anchor is refused. F-17
therefore **stays OPEN**. The next unit is not "write the anchor file" but a
prerequisite **authority milestone**: give the worker a genuinely lower
filesystem authority than the anchor store (separate OS user / restricted
token + ACL, or a mediating service), OR accept the cryptographic
authenticity root. Only then can `ANCHORED` and `verify_anchored_bundle`
exist without being a false promise. No production code changed in this
unit; the finding, the threat model and the §14 contract are the deliverable.

## Fifth review — F-17 OS AUTHORITY BOUNDARY: a real, Windows-enforced boundary

The independent review confirmed BLOCKER C and scoped the next unit to
building a **real OS authority boundary** — one imposed by Windows, not by
Python roles, prompts or path convention — such that
`worker_write_authority ∩ anchor_write_authority = ∅`. Done and demonstrated.

### FASE 1 — the primitive, and the alternatives rejected

**Chosen: Windows Mandatory Integrity Control (MIC).** A process at a lower
integrity level cannot write an object labelled at a higher level
(NO_WRITE_UP), kernel-enforced, regardless of the DACL — an authority
boundary between two processes of the SAME OS user, which is exactly the
worker/Director situation. Minimal and auditable: one `icacls` label + one
token operation.

Rejected as heavier or unavailable here:
- **Separate OS user + DACL** — cleanest conceptually, but creating a user and
  launching as it needs admin provisioning and `CreateProcessAsUser`
  (SeAssignPrimaryTokenPrivilege, not held); heavy infra for no more security
  than MIC gives against T2.
- **Restricted-SID token (`CreateRestrictedToken`)** — can deny SIDs, but
  same-user SID identity makes a SID-deny awkward; MIC separates by the
  orthogonal integrity axis, the right tool.
- **Job Objects / sandbox / container** — lifecycle/containment, not a
  write-authority boundary; not needed.
- **A separate broker service** — a same-user broker is itself
  worker-writable unless it too is integrity- or user-separated; MIC gives the
  separation without a new daemon.

Measured here: `SeImpersonatePrivilege` held (so `CreateProcessWithTokenW`
launches a child with a modified token); `icacls /setintegritylevel
(OI)(CI)High` applies NO_WRITE_UP; the Director session runs elevated
(**High**). No admin-provisioned user, no crypto.

### The design

- **AnchorStore** = an NTFS directory labelled **High, NO_WRITE_UP**,
  inherited. Only a High process can write it.
- **Publisher / Director** = runs at **High** (elevated). Precondition: the
  Director runs elevated — within the trust boundary (T3 is out of scope).
- **Worker** = launched at **MEDIUM** by `authority.run_at_integrity` (a
  duplicate of the Director token with IL lowered to `S-1-16-8192`, via
  `CreateProcessWithTokenW`). Medium is the normal user level, so the worker's
  whole toolchain runs unaffected; only the small anchor is above it.

### OS-real attack matrix (`git-authority-audit.txt`) — all pass

Worker at Medium: `write_worktree` **ALLOWED**; against the High anchor
**DENIED** on every one of `write`, `create`, `delete`, `rename`,
`change-DACL`, `lower-label`, `take-ownership`, a **cmd child** write, a
**python child** write (inheritance — no privilege recovery), and **raising
its own integrity** (winerr 1314 ERROR_PRIVILEGE_NOT_HELD). Publisher at High:
**ALLOWED**. After the run the anchor holds only the seed and the publisher's
record. `worker ∩ anchor = ∅` by effective process authority.

### Anchor record, protocol, confused-deputy defence

`AnchorRecord` binds `{schema, task_id, run_id, repository_id, head_sha,
tree_identity, bundle_path, bundle_digest, seq, prev_record_digest}` —
append-only, hash-chained from `GENESIS_HASH`, re-verified before every append.
`publish_anchor` never trusts the worker: the bundle path comes from the
Director's `RunIdentity`; `verify_bundle` **recomputes** the digest (no
worker-supplied digest parameter exists); the bundle's bound `head_sha` must
equal the Director's, rejecting a cross-run/replay bundle; the record is
chained and re-read. `verify_anchored_bundle` verifies against the
**authoritative** store digest, failing closed on a missing record or broken
chain — a caller cannot pass an arbitrary `expected_digest` and call it trusted.

### Threat model

Defeats **T2** (a malicious same-user Medium worker). NOT **T3** (compromised
Director — runs High, owns the anchor) or **T4** (admin/full-OS — can relabel).
Out of scope; no cryptography. STOP conditions checked — worker keeps full
authority for its own work (Medium is normal); children do not recover
authority; the worker cannot relabel/re-own the anchor; the publisher is not an
arbitrary-write oracle; no worker-readable secret. None triggered.

### Tests, mutants, states

`tests/test_authority_boundary.py` — 13 tests (record chain; store
append-only/chained + refusal to extend a broken chain; honest note that the
last record's authenticity comes from the OS label not the chain; publication
protocol; verify uses the authoritative digest and fails closed). Windows +
elevated only; skips otherwise. `scripts/mutation_check_authority.py` — 7
mutants AM1..AM7, **0 survived**; baseline/restored GREEN (13 passed).
`SELF_CONSISTENT` and `ANCHORED` are now distinct and real; `AUTHENTICATED`
(crypto) stays deferred.

### What is NOT done — why F-17 stays OPEN

1. **Wiring the Medium launch into the production engine/runner** and
   constructing the store + publisher in the pipeline — touches every agent
   launch and ADR-0009's isolation model, so it is not landed half-validated.
2. **A fresh FULL `scripts/capture_evidence.py`** publishing/verifying against
   the anchor. The cold hash of ~90k inputs (~2.4 GB) plus the suite exceeds
   this environment's long-run limit (a detached capture crawled and was
   abandoned), so it could not be produced. Per the review, no fresh full
   capture ⇒ **do not close F-17.**

§14 (unknown `.git` → fail closed) stays the decided contract; it lands with
the same closure step.

### Evidence (fifth review)

`.gnosis/evidence/20260826T181515Z/`, `verify_bundle` → verified,
**`bundle_digest 0dfbeb855240bfde29d2f02dd333eced36ece3c7768c366c301c6e0342ffce5a`**.
Contains `git-authority-audit.txt` (OS-real matrix), `mutation-check.authority.txt`
(7/7 caught), `authority-directed.txt` (13 passed), `CAPTURE-NOTE.md`. New code:
`authority.py`, `tests/test_authority_boundary.py`,
`scripts/mutation_check_authority.py`; engine/runner untouched (wiring is the
closure step). mypy clean (59 files), ruff at baseline.

## Sixth review — the three bypass blockers (handle inheritance, publisher code, RunIdentity)

The review approved the MIC primitive within T2 and required three
bypass properties be proven OS-real BEFORE wiring the runtime. Done.

### BLOCKER A — privileged handle inheritance: satisfied (structural)

A High handle the Director holds open must not reach the worker: an inherited
handle carries already-granted access and would bypass MIC. Demonstrated
OS-real (`git-authority-audit.txt` §2): the Director opened the anchor for
WRITE with an **inheritable** handle, then launched the worker via
`run_at_integrity`; the Medium worker's `WriteFile` through that handle failed
with **ERROR_INVALID_HANDLE (6)** and the file stayed empty. The guarantee is
**structural**: `CreateProcessWithTokenW` has no `bInheritHandles` parameter
and does not inherit handles, so `WorkerInheritedPrivilegedHandles = ∅` by
construction — there is no inheritance-enabling branch in `authority.py` to
flip (the launch API cannot express it), and `run_at_integrity` sets no
inheritable std handles. Test:
`test_the_worker_does_not_inherit_a_privileged_handle`.

### BLOCKER B — trusted publisher code integrity: mechanism proven, real gap found

The High publisher must not execute worker-controlled code. Two facts,
OS-real:
- **Mechanism (works).** Trusted code labelled **High NO_WRITE_UP** is
  READ/imported by a Medium worker but **cannot be overwritten** by it
  (`overwrite → PermissionError`; `import` still returns the original) — MIC's
  no-write-up blocks writes while allowing reads, so a High-labelled code root
  is worker-executable but worker-immutable. Test:
  `test_high_labelled_trusted_code_is_readable_but_not_writable_by_the_worker`.
- **Finding (open).** The product's OWN trusted code is **currently
  Medium-writable**: a Medium worker can append to
  `src/gnosis/kernel/authority.py` right now (measured). So as things stand a
  worker could poison the very module the High Director later imports. **The
  closure wiring MUST label the trusted-code root — the `gnosis` package under
  `src/` and the `.venv` interpreter — High NO_WRITE_UP** (readable, not
  writable) before the boundary is complete. Until then B is not closed; this
  is one reason F-17 stays OPEN.

`assert_integrity(expected)` is added as the verifiable introspection the
review asked for: the worker calls `assert_integrity("Medium")` and the
publisher `assert_integrity("High")` at startup, failing closed if the process
runs at the wrong level (a launch that silently ran the worker High is
refused, not proceeded). Tests: `test_assert_integrity_fails_closed_on_the_wrong_level`,
`test_a_medium_worker_asserts_medium_and_refuses_high`.

### BLOCKER C — authoritative RunIdentity: design proven, wiring requirement stated

`publish_anchor` takes `RunIdentity` as a **parameter** and never adopts
identity from the bundle: the record's `task_id`/`run_id`/`repository_id`/
`head_sha`/`bundle_path` come from the Director's identity, and the bundle is
only cross-checked (its bound head must equal the Director's). Demonstrated:
`test_publish_binds_the_directors_identity_not_the_bundles` (distinctive
Director values land in the record) and the head-mismatch rejection. **Wiring
requirement (open):** the Director must SOURCE `RunIdentity` from
High-integrity state — its own run registration written before the worker
runs, on the High side — not from any worker-written record. That store is the
same High-labelled surface as the AnchorStore; building it is part of the
closure wiring.

### Tests, mutants

`tests/test_authority_boundary.py` — **18 tests** (adds A: no handle
inheritance; B: High code readable-not-writable; C: identity from the Director;
assert_integrity fail-closed on the wrong level, from High and from a Medium
child). `scripts/mutation_check_authority.py` — **8 mutants (AM1..AM8), 0
survived** (AM8: assert_integrity stops failing closed). A/B/C's core
guarantees are **structural** (no handle-inheritance branch; identity is a
parameter never read from the bundle; code integrity is a label/wiring
property), demonstrated by the OS-real tests; the mutable enforcement knobs —
launch at Medium (AM1), label High (AM2), fail-closed on wrong integrity (AM8)
— are mutation-covered.

### Why F-17 stays OPEN (unchanged verdict, expanded)

BLOCKER A satisfied; B's mechanism proven but the **real trusted-code root is
still worker-writable** (must be High-labelled in the wiring); C's design
proven but the **RunIdentity source must be wired to High state**. On top:
wiring the Medium launch into the production engine/runner, §14 unknown-`.git`,
and a **fresh FULL `run_capture`** (env-blocked). Per the review, no fresh full
capture ⇒ **do not close F-17**.

### Evidence (sixth review)

`.gnosis/evidence/20260826T184603Z/`, `verify_bundle` → verified,
**`bundle_digest 5b2b4c68c27efde207392a43fd1661aed578293155c44c22edb82b595bf5ca56`**.
`git-authority-audit.txt` (attack matrix + A/B OS-real + the real-src B
finding), `mutation-check.authority.txt` (8/8 caught, 18-test baseline),
`authority-directed.txt` (18 passed), `CAPTURE-NOTE.md`. New code:
`assert_integrity` in `authority.py`, the A/B/C tests, the AM8 mutant. No fresh
full `run_capture` (environment). mypy clean (59 files), ruff at baseline.

## Seventh review — AUTHORITY BOUNDARY REQUALIFICATION (research/design; no wiring)

Before promoting same-user MIC to the production boundary, the review asked to
compare a stronger boundary. Research + OS-real probes + comparison. No
production wiring; the MIC lab is preserved as evidence and defense-in-depth.

### Current design analysed (OS-real)

`run_at_integrity` builds the worker token by **duplicating the Director's
elevated token and lowering its integrity to Medium** — it does not strip
privileges. Measured:
- Worker and Director share **one user SID** (`S-1-5-21-…-1000`); the ONLY
  difference is the integrity level (Worker Medium, Director High).
- The **Medium worker token still holds all 24 admin privileges** (present but
  disabled), including SeBackup, SeRestore, SeTakeOwnership, SeDebug — the
  Director differs only in which are *enabled*.
- Enforced-by-kernel and held against direct probes: enabling SeDebug /
  SeRestore / SeTakeOwnership at Medium **fails (ERROR_NOT_ALL_ASSIGNED 1300)**;
  `OpenProcess(High Director, PROCESS_VM_WRITE)` is **DENIED (5)**; every
  file-write / relabel / take-ownership on the High anchor is denied; no handle
  inheritance (`CreateProcessWithTokenW`).

### Candidate A — same-user MIC: DEFENSE-IN-DEPTH, not a boundary

Strengths: kernel-enforced no-write-up; no admin-provisioned account; worker
keeps its full toolchain; my direct escalation probes were all denied.
Weakness that decides it: it is **same-user**, and Microsoft does **not** treat
the Medium→High integrity split as a security boundary (UAC / integrity
bypasses are not serviced as vulnerabilities). The worker shares the user's SID
and profile, so the T2 attack surface for elevation is large (auto-elevating
COM, UAC bypasses, and — measured earlier — worker-writable trusted code the
High Director later imports). The retained-but-gated admin privileges are a
latent risk. Hardening A' = `CreateRestrictedToken(DISABLE_MAX_PRIVILEGE)` to
remove the privileges outright; still same-SID, so still no ACL separation.
**Keep A/A' as defense-in-depth, not the primary boundary.**

### Candidate B — dedicated non-admin worker user: the qualified boundary

A separate non-admin local account gives the worker a **different SID**, so
NTFS DACLs genuinely separate the two principals — and **user-account
isolation IS a Microsoft-recognised security boundary**. A fresh standard-user
token also has **minimal privileges natively** (no SeBackup/SeRestore/SeDebug/
SeTakeOwnership even present). Anchor/RunIdentity/trusted-code DACLs deny the
worker SID; the worker gets RW on its worktree and RX on the toolchain by
explicit grant.
**OS-real probe BLOCKED:** creating a local user was refused by this
environment's auto-mode classifier (a system-state change needing operator
authorization), so B's feasibility (toolchain read-access, Git/Python/Claude/
Codex under a separate profile, credential provisioning, cleanup/recovery)
could NOT be demonstrated here. B's SECURITY is established Windows behaviour;
its COMPAT must be probed once user provisioning is authorised.

### Candidate C — trusted service / service SID (publisher only)

A minimal publisher as a Windows service or virtual service account gives the
PUBLISHER a distinct service SID and a semantic named-pipe IPC (never an
arbitrary-write oracle). Stronger publisher isolation, but more moving parts
(service install/lifecycle, IPC protocol) and it does not by itself constrain
the worker — best as an *addition* to B for the publisher principal, not a
replacement.

### Candidate D — AppContainer worker: impractical (reasoned)

AppContainer denies filesystem/network by default and requires explicit
capabilities; a full dev toolchain (Python, Git, the Claude/Codex CLIs,
subprocess, networking, credentials) needs so many capabilities/brokered
exceptions that the container stops being a meaningful boundary. Not probed
OS-real; **rejected** for production on that basis (and `CreateProcessInSandbox`
stays LAB/FUTURE while experimental).

### Comparison (summary)

| | A same-user MIC | B dedicated user | C service/SID (publisher) | D AppContainer |
|---|---|---|---|---|
| T2 boundary strength | mitigation only | **strong (SID ACL)** | strong (publisher) | strong but unusable |
| MS-recognised boundary | no (integrity) | **yes (user acct)** | yes | yes |
| filesystem isolation | label only, same SID | **ACL by SID** | ACL by service SID | capability-gated |
| privilege surface | retains admin (gated) | **minimal native** | minimal | minimal |
| toolchain compat | **full (Medium)** | grant-dependent (unproven) | full | poor |
| complexity / TCB | low | medium | higher | high |
| probe status here | **OS-real done** | blocked (classifier) | reasoned | reasoned |

### Selected architecture

**Dedicated non-admin WORKER user + a minimal TRUSTED PUBLISHER principal;
NTFS ACL (by SID) as the PRIMARY boundary; MIC (worker Medium / anchor High
NO_WRITE_UP) retained as DEFENSE-IN-DEPTH; explicit no-inherit handle policy
(proven); minimal semantic IPC.** The publisher principal may be the elevated
High Director user (simplest) or a service SID (Candidate C, stronger) — to be
decided with the feasibility probe. This is the reviewer's hypothesis, and the
evidence supports it: A is not a real boundary, B is the recognised one.

### TCB (trust plane) — kept minimal

trusted launcher, RunIdentity store/reader, AnchorStore, evidence verifier,
publisher, and the minimal runtime they need — labelled/owned so the worker SID
cannot write them. NOT the whole `src/` + `.venv`: a dedicated **trusted
runtime** (a protected interpreter + the trust-plane package) is preferred over
labelling everything. The worker plane (Claude, Codex, work repos, generated
code, tests, dev tools) stays worker-writable and worker-owned.

### Migration / wiring plan (NOT executed this round)

1. Operator-authorised feasibility probe of B: provision a non-admin worker
   user; grant worktree RW + toolchain RX; verify Git/Python/Claude/Codex,
   credentials (per-user isolation), networking, cleanup/recovery.
2. Lay the trust plane on a worker-non-writable root (ACL by SID; MIC as DiD).
3. Launch the worker as the worker user (CreateProcessWithLogonW / a broker);
   `assert_integrity`-style startup checks extended to SID/privilege.
4. Build the High RunIdentity store + AnchorStore + publisher on the trust
   plane; wire `publish_anchor`/`verify_anchored_bundle`.
5. §14 unknown-`.git`; then a fresh FULL `run_capture`.

### Residual risks / decisions for review

- B's **feasibility is unproven here** (classifier blocked user creation) — the
  compat/credentials matrix is the immediate gated step.
- Provisioning a worker user + credential isolation for Claude/Codex/Git is an
  operational change the operator must approve.
- A/A' (same-user MIC) stays as defense-in-depth; the MIC lab is kept.
- No wiring, no §14, no fresh capture this round (by instruction). F-17 OPEN.

## Eighth-review addendum — Dedicated-worker TOOLCHAIN qualification (2026-08-26)

Operator-authorized, reversible OS-real probe. The feasibility probe (seventh
review) qualified the *security boundary* but left the *toolchain* untested
relocated. This probe proves the full Gnosis worker toolchain runs from a
worker-non-writable root outside the operator profile.

**Setup.** Dedicated non-admin worker `GnosisWorkerProbe` (group `Usuarios`,
admin=False), launched via `CreateProcessWithLogonW` (no handle inheritance),
crypto-random SecureString password never materialized as plaintext, deleted in
rollback. Toolchain root `C:\ProgramData\GnosisWorkerToolchainProbe` holds
disposable copies of python 3.12.14 + venv site-packages, `claude.exe`,
`codex.ps1` + `@openai/codex`, and the gnosis package. ACL = allowlist-only:
`/inheritance:r` + Administrators:F + SYSTEM:F + Usuarios:(OI)(CI)**RX** — no
DENY (a DENY on `Usuarios` also blocks admins who are members). Node and Git are
the shared Program Files installs (read-only to Users). Worktree/scripts under
`C:\ProgramData\GnosisWorkerTCprobe`, OUTSIDE `C:\Users\nicol`.

**Result = `TOOLCHAIN RESULT: QUALIFIED`.** As the worker: all five toolchain
binaries WRITE-DENIED (`UnauthorizedAccessException`); python runs, imports the
stdlib and `gnosis.kernel.canonical`, and runs pytest (`1 passed in 0.03s`);
node v24.19.0; git commit PASS; claude 2.1.246 and codex-cli 0.148.0 both
STARTUP PASS (`--version` only, no login — missing-auth is EXPECTED ISOLATION,
not a bug); a worker-planted `evilmod.py` in the worker's CWD did NOT poison the
trusted import from the RX-only ToolRoot (`TRUSTED_IMPORT_STILL_CLEAN`); operator
`.claude`/`.codex`/`.ssh` are ABSENT-from-worker.

**Hygiene.** `pycache_in_toolchain_after=True` is pre-existing `.pyc` from the
site-packages copy plus an admin self-test; every worker write to the toolchain
is denied, so pytest ran without caching bytecode into the RX root — RX-only does
not break pytest. Secret scan clean (the only match is a SecureString *variable
reference*, no value).

**Required worker-writable locations (for the wiring).** worktree/CWD (untrusted
code runs here); a per-worker temp; the git working repo. The trust plane
(toolchain root, `src/` package + interpreter, AnchorStore, RunIdentity) stays
RX/worker-non-writable. The worktree and trust plane must both live OUTSIDE the
operator profile (worker cannot traverse `C:\Users\nicol`).

**External anchor (BLOCKER 2 root of trust).** Evidence bundle
`.gnosis/evidence/20260826T213728Z/` `bundle_digest` =
`b23dc24a2d7196ee5eedb36eae4b56a40a44dbd40314c323f064fd46b7c7bf1f`, recorded here
and on the git commit that carries the bundle; re-derive with
`verify_bundle(expected_digest=…)`.

**P2 (service-SID publisher) — DESIGN ONLY, not installed.** A publisher running
under a service account / virtual service SID (`NT SERVICE\<svc>`) would own the
AnchorStore DACL (service SID: Full; worker SID: no access; SYSTEM/Administrators:
Full) and run detached from any interactive operator logon, so a compromised
worker session cannot reach it even by the operator's own token. Trade-offs vs
P1 (Director-High): P2 survives operator logoff and needs no interactive
elevation, but requires service install + start authority (a privileged,
non-reversible operational change) — deferred to the wiring decision, unbuilt.

**Rollback.** No Gnosis* users / services / scheduled tasks / Win32 profiles;
toolchain root and probe dir deleted; no operator or production ACL changed
(real paths were only read/copied-from); HEAD unchanged. This probe does NOT
close F-17: production wiring, §14, and a fresh FULL `run_capture` remain.

## Ninth-review addendum — P2 service-SID publisher probe: QUALIFIED (2026-08-27)

Operator-authorized, reversible OS-real probe of the P2 design (with the review's
mandatory corrections). F-17 stays OPEN. **`P2 PROBE RESULT: QUALIFIED —
RESTRICTED SERVICE SID`.**

**SCM host (P2A, no gap).** A pure-ctypes SCM host (`StartServiceCtrlDispatcher`
/ `ServiceMain` / control handler / `SetServiceStatus`) — no pywin32, keeping the
TCB minimal — reached RUNNING, reported status, and stopped cleanly (~360 ms).
`python.exe -I -S main.py` alone is NOT a service; the ctypes dispatcher is what
makes it one. **No `P2A SCM HOST GAP`.**

**RESTRICTED first, verified in the OS-real token** (not just `sc` config).
token-dump from inside the running service: `user_sid` = the service SID
`S-1-5-80-…`; `is_token_restricted = true` with the service SID in the
restricting-SID list; `privileges_present = [SeChangeNotifyPrivilege]` only (no
SeDebug/SeImpersonate/SeBackup/SeRestore/SeTakeOwnership/SeTcb/SeAssignPrimaryToken/
SeCreateToken); integrity High (services' default — the boundary is the DACL-by-SID
plus the write-restricted token, MIC is DiD). RESTRICTED did NOT block startup, the
trust-code read, RunIdentity read, AnchorStore append, or pipe creation — so **no
fallback to UNRESTRICTED was needed** (and none was taken silently).

**Attack matrix — worker = a distinct non-admin SID (`GnosisP2Worker`).** Legit
`PublishCompletedRun(run_A)` → `ANCHORED seq=0`; duplicate → `ALREADY_ANCHORED`;
cross-run (a run owned by another SID) → `owner-mismatch`; unknown/malformed/
oversized → rejected; worker create-pipe → DENIED; worker writes to the service
binary / trust python / anchor code / RunIdentity / AnchorStore / a shadow module →
ALL DENIED (`UnauthorizedAccessException`); worker `sc` change-config / stop /
delete → ERROR 5; worker `OpenProcess(publisher, VM_WRITE|DUP_HANDLE|CREATE_THREAD|
VM_OPERATION|CREATE_PROCESS)` → ALL DENIED err 5.

**Confused-deputy defense.** The worker sends only `run_id`; the publisher derives
task_id/repo/head/tree/bundle_path/owner from the trusted RunIdentity, recomputes
the bundle digest from bytes, and checks the bound head — never a worker-supplied
value. Authorization root = the pipe DACL (only the exact worker SID can open the
endpoint, granted `0x0012019B` — read+write-data, NOT `FILE_CREATE_PIPE_INSTANCE` /
not GENERIC_WRITE) **plus** `RunIdentity.owner_worker_sid`; no
`GetNamedPipeClientProcessId`/token as the trust root, no `SeImpersonatePrivilege`.

**Pipe squatting.** With the service down, the worker pre-created a pipe of the same
name; on start the service refused (`FILE_FLAG_FIRST_PIPE_INSTANCE` failed →
"refuse to attach") and did NOT connect to the worker's pipe — fail-closed, no
retry onto an unauthenticated endpoint.

**Crash consistency.** An unconfirmed ledger record beyond the committed watermark
was truncated by the trusted startup recovery, and the committed `ANCHORED` record
survived — never a false `ANCHORED`. The watermark lives in worker-non-writable
trusted state; truncation is an explicit trusted recovery action, not a property of
append-only.

**T2 defeated; T3/T4 excluded.** The guarantee demonstrated is exactly `Worker SID
cannot obtain Publisher authority`. SYSTEM/Admins retain full control of the service
and stores (T4, declared, not a boundary).

**Reversibility.** Full rollback verified: no Gnosis* services / users / profiles /
scheduled tasks / files / pipe; no real-path ACL changed; HEAD unchanged.

**External anchor.** Evidence `.gnosis/evidence/20260826T234424Z/` `bundle_digest` =
`4cfb63712ae4ad2372b4265b16a912a1c047dac1dd73468c2240bf3398b4aefb`, recorded here
and on the carrying commit; re-derive with `verify_bundle(expected_digest=…)`.

**Still to do before closing F-17 (unchanged):** production worker + publisher +
trusted-RunIdentity wiring; §14 unknown-`.git`; full validation; a fresh FULL
`run_capture`; authoritative anchor; a final independent review.

## Tenth-review addendum — production wiring & closure design FROZEN (2026-08-27)

`docs/F17_PRODUCTION_WIRING_AND_CLOSURE.md` is the closure design; the independent
review returned **APPROVE_WITH_ONE_BLOCKING_DESIGN_FINDING**, and this addendum
records the frozen result. **Docs only — no production code. F-17 stays OPEN.**

Approved & frozen: dedicated non-admin Worker; RESTRICTED service-SID Publisher;
NTFS ACL/SID primary T2 boundary; MIC as DiD; service High permitted (NOT the
boundary); `assert_publisher_identity` replacing `require_high` semantically;
`owner_worker_sid` from the OS-real token; a trusted `PUBLISHABLE` state; reuse of
the existing epoch/generation; trusted RunIdentity; semantic named pipe; trusted
AnchorStore; deployment identity; minimal trust plane; a clean local fixed-NTFS
non-synced qualification workspace; process/service crash guaranteed; power-loss/
storage best-effort/bounded; end-to-end composition qualification. F-14 CLOSED.

BLOCKER resolved (unknown-`.git`): the allowlist was too broad (whole `refs/` /
`objects/` categories contain trust-sensitive surfaces). Corrected to a **total,
single-valued `classify(path)`** with three exhaustive classes — `KNOWN_TRUST_SENSITIVE`
(judged/fail-closed), `KNOWN_CONTENT_OR_BOOKKEEPING` (counted only where the concrete
semantics are qualified), `UNKNOWN` → `MACHINERY_UNQUALIFIED` fail closed — with
**most-specific-wins precedence robust to rule ordering** (a trust-sensitive path can
never match a benign rule; `objects/info/**` never inherits the payload class;
`refs/replace/**` never the ref-bookkeeping class; index classified by the property
it cannot alter, not the label "benign"), plus a backend/version precondition
(reftable/other → NOT QUALIFIED). An 11-point unknown-`.git` test plan (incl. an
ordering-mutant that must die) is specified. The third/fourth-review classifications
(HEAD/refs/packed-refs/refs-replace/config/config.worktree/commondir/hooks/alternates/
grafts/shallow/topology) are preserved, not re-audited.

Corrections also frozen: the **launch credential contract** no longer claims "never
in cleartext" (`CreateProcessWithLogonW` needs transient cleartext in launcher
memory) — the guarantee is **no plaintext at rest/repo/source/JSON/persistent-env/
command-line/logs/evidence**, transient-in-launcher-only, best-effort zeroization;
a full **DPAPI lifecycle** (scope, decrypt principal, blob location+ACL with Worker
denied, rotation, corrupt/rotated/decrypt-failure → all fail closed); the launcher
**stop condition** reworded to "cannot launch without a *persistent/exposed* plaintext
secret". **Deployment identity** is built from **observed** post-deployment system
queries (not desired config), with **canonicalized** security descriptors before the
digest. A **deployment-drift** matrix (A–H) and **composition extensions** (wrong/
missing worker SID, credential decrypt/rotation failure, publisher missing/wrong-SID-
type, precondition false, deployment mismatch, non-PUBLISHABLE, epoch mismatch,
same-user `Popen` fallback attempted) are added — **all fail closed; there is NO
fallback to same-user `subprocess.Popen`**. Durability contract unchanged.

`publish_anchor`/`verify_anchored_bundle`/`AnchorStore` still have **no production
caller** (greenfield). The next review decides whether to authorize
`F-17 PRODUCTION WIRING IMPLEMENTATION`. Do NOT wire yet.
