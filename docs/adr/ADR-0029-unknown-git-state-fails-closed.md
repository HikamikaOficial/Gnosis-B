# ADR-0029 — Unknown `.git` state fails closed

**Status:** accepted (F-17 Stage 7, 2026-08-28)
**Extends** ADR-0028 (the composed trust path). **Does not reopen** F-14.

## Context

The evidence capture judged an allowlist of KNOWN-dangerous `.git` surfaces
(hooks, config, the resolution-redirect files) and forgave everything else under
`.git/` as bookkeeping. That is an inverted closed world: a surface nobody had
enumerated — a future Git namespace, a `refs/` namespace this project does not
use (`refs/codex/` exists on this machine), a control file under
`objects/info/` — read as benign by default. `UNKNOWN -> inert`.

Worse, the machinery verdict, however computed, had no reader in the trust
plane. A `MACHINERY_*` capture still produced a bound bundle that
`build_anchor_record` and `verify_bundle` accepted, so it could become an
Anchor V2. The classifier, such as it was, was disconnected from publication.

## Decision

### Three classes, and UNKNOWN is the only catch-all

`gnosis.kernel.git_surface` puts every `.git` path in exactly one of
`KNOWN_TRUST_SENSITIVE`, `KNOWN_CONTENT_OR_BOOKKEEPING`, or `UNKNOWN`. The
required fallback is `UNKNOWN -> MACHINERY_UNQUALIFIED -> fail closed`. A surface
becomes allowed only by being moved, explicitly and with a stated property, into
a known class. There is no "denied unless it looks dangerous" — the danger list
is gone, replaced by a safety list plus a fail-closed default.

### Order-independent by construction

The classifier collects EVERY matching rule and requires at most one. Two
matches are a defect in the rule set, not a precedence puzzle, so it raises
rather than silently choosing. Reverse or shuffle the rules and the result is
identical, because a set has no order. There are no first-match security
semantics.

### Known parent + unknown child != known child

No `objects/**` or `refs/**` blanket. Rules name qualified namespaces
(`refs/heads/`, the loose-object shape `objects/<2hex>/<hash>`), so a sibling
under a known parent (`refs/codex/x`, `objects/info/commit-graph`) matches
nothing and is UNKNOWN. A brand-new nested directory under a known parent is
UNKNOWN with zero new code — that is the principal guarantee.

### The trust-sensitive set is defined by a property, not a name

It grew on measured reasoning: HEAD (defines the checkout), `info/exclude`
(steers enumeration), `info/attributes` (drives filters/diff), and the resolving
ref namespaces `refs/heads|tags|remotes/**` — the loose form of the packed-refs
risk the earlier review already judged. Treating packed-refs as dangerous while
forgiving loose `refs/heads` would have been the same attack by another
spelling.

### The bookkeeping set is grounded, not guessed

Observed OS-real: a read-only capture writes exactly `.git/index`; a commit
additionally writes `COMMIT_EDITMSG`, `logs/*`, `refs/heads/*` and loose
objects. Each bookkeeping rule states the property that makes a write to it
unable to change the trusted identity (index: identity is working-tree-vs-HEAD
plus endpoint-captured status; loose object: name is the hash of its bytes;
reflog: never consulted in ref->object resolution).

### A qualified backend and version, or fail closed

`git_backend_and_version_qualified` runs before the topology and resolution
gates. It requires git 2.55.x and the `files` ref backend
(`rev-parse --show-ref-format`). reftable, an unknown backend, a materially
different version, or a broken git → `MACHINERY_UNQUALIFIED`, nothing runs.
Deliberately strict: a git upgrade fails closed until re-qualified rather than
silently broadening compatibility. The resolution probes' fail-opens (a failed
replace-ref or shallow probe, an unreadable redirection file reading as absent)
are closed: a probe that cannot answer is UNKNOWN, not "all clear".

### Connected to publication

`build_anchor_record` — the one chokepoint every Anchor V2 passes through — reads
the capture's boundary verdict from SUMMARY.json and refuses anything but
`CLEAN`, including an ABSENT verdict (a pre-Stage-7 bundle cannot pass by lacking
the field). `authorize_publishable` applies the same check earlier, as defence
in depth. The trust plane gains ZERO new imports: it reads a JSON string, it does
not import the kernel classifier, and the publisher's import closure is
unchanged at 15 modules.

## Consequences

- A check that commits during a capture now fails closed (it moves `refs/heads`),
  which it did not before. Legitimate read-only captures are unaffected: the only
  `.git` write they make is `index`, which is bookkeeping.
- The 8.3 short-name residual: a Windows short name (`CONFIG~1`) that the observer
  reports instead of the long name will not match an exact rule and falls to
  UNKNOWN — still fail closed, never forgiven, but misclassified as unqualified
  rather than as the specific surface. Recorded as a residual.
- A git upgrade beyond 2.55.x fails captures closed until re-qualified. This is
  the intended reading of "do not silently broaden compatibility."
- The old `_is_git_machinery_tamper` / `_is_git_resolution_redirect` predicates
  are retained for their historical BLOCKER-A contract; a lockstep test asserts
  every surface they flag is TRUST_SENSITIVE in the classifier, so the two
  catalogues cannot drift.

## F-14

Unchanged and not reopened. Stage 7 does not touch ADS observation, the
create-delete ABA handling, completeness semantics, or byte binding; it only
stops unknown `.git` administration from being implicitly safe. The F-14
directed regression (`tests/test_evidence_binding.py`) passes.

## Evidence

`.gnosis/evidence/20260830T213109Z/` — classifier 22 tests / 84 subtests; enforcement
9 tests; backend gate 9 tests incl. a real reftable rejection; e2e machinery
10 tests; mutation 19/19 caught on a green baseline; OS-real git matrix 26/26
with rollback; Stage 6 composition regression; F-14 regression; full suite;
isolated fresh checkout with import provenance proved. mypy strict clean over
75 files; ruff unchanged at the repo baseline.

    bundle_digest  ea959ee6254a2d9459201b588617d3eea8729d3fe9b028e250b8dc60683f1485
