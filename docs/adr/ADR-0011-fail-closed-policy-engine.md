# ADR-0011 — Fail-closed policy engine + enforcement honesty (Directive 8)

- Status: ACCEPTED
- Date: 2026-08-20
- Deciders: Claude Fable 5 (autonomous, per standing mandate)
- Evidence: `tests/test_policy.py` (48 tests, incl. a live probe that
  demonstrates the worktree escape its own claim admits); suite 376/376;
  mypy strict clean; dual adversarial review pre-commit.
- Source: `docs/research/REFERENCE_REPOSITORY_FINDINGS.md` §8
  (agent-governance-toolkit ACS, agentjail parsed-intent verdicts, nono
  deny-by-default floor, orca enforcement-honesty matrix, opentraces'
  "unknown is never coerced to safe").

## Decisions

### 1. `PolicyEngine.decide` is pure, stateless and total

A complete `ActionSnapshot` in, exactly one `PolicyDecision` out. No
clock, no filesystem, no hidden state — so a verdict is reproducible from
recorded evidence, which is what makes it auditable.

### 2. Every internal failure denies, in a reserved namespace

A rule that raises, returns a non-`RuleOutcome`, returns a malformed one
(wrong verdict type, empty reason, non-dict detail/transform), emits a
reserved reason, or `TRANSFORM`s without a payload becomes DENY with a
`runtime_error:*` reason. Rules may not emit those prefixes, so
"the policy said no" and "the engine broke" are never confused. A broken
rule short-circuits: if one opinion is untrustworthy, the remaining ones
are not a complete picture.

### 3. Configuration gaps are never consent

Unconfigured intervention point → deny. Undeclared tool → deny. No rule
matched → deny. Silence is not permission.

### 4. Approvals bind to the exact action

`ActionSnapshot.action_id()` is the canonical sha256 of everything
evaluated, and snapshots are **deep-frozen** so an approved action cannot
be edited afterwards. `resolve_escalation` refuses when the decision and
the snapshot describe different actions. An approval never upgrades a
DENY.

### 5. Rules key on parsed intent, never on strings

`parse_command` yields program, flags, operands, attached flag values and
lexically-resolved paths, with **`cwd` inside the intent** — `rm -rf
build` in a scratch worktree and in a production checkout are different
actions and must have different identities. Path resolution is
deliberately **over-inclusive**: for a fail-closed engine, mistaking a
non-path operand for a path is the safe direction; missing a real path is
not.

### 6. The enforcement matrix is falsifiable, not decorative

`GNOSIS_ENFORCEMENT` is a single source of truth in the module (not
restated per test), and `EnforcementMatrix.verify(probes)` checks claims
against **evidence**: a probe reports whether a restriction can actually
be escaped, and a HARD claim that a probe escapes is reported as a
contradiction. The suite runs a real probe showing a process whose cwd is
a worktree still writes outside it via an absolute path — confirming
`shared_repo_isolation` is `SANDBOX_APPROX`, exactly as ADR-0009 says,
and that `orphaned_child_termination` is `IGNORED`.

## Known limitation (documented, not fixed)

The engine is not yet wired into any intervention point: no adapter calls
it before a tool runs. This milestone delivers the mechanism, its
fail-closed semantics and the honesty matrix; wiring it into the CLI
runner and the engine's write paths lands with the adapter milestone,
alongside the `InteractionStore` and `ConvergenceLoop` wiring already
tracked. Until then the matrix's own claims are the honest statement of
what the kernel actually enforces.

## Review outcome and repairs (2026-08-20, pre-commit)

**Self-found before review** (both reproduced first, both bypasses):
`--output=/etc/x` was classified as an opaque flag so its path never
reached `resolved_paths` while the equivalent `-o /etc/x` was denied; and
`rm -rf build` produced the **same action_id** in a sandbox and in
production, so one approval would have covered both.

**Codex** (`exec --sandbox read-only --json`): FAIL, 6 findings — the two
above independently, plus four more, all verified true and repaired:

1. *(critical)* `resolve_escalation` never checked that the decision and
   the snapshot describe the same action: an approval could be looked up
   for one action and granted to another.
2. *(critical)* `ActionSnapshot` was only shallowly frozen — `payload`
   and `context` stayed mutable, so an approved action could be edited
   after approval. Contents are deep-frozen now.
3. *(major)* Only the `RuleOutcome` container type was validated; a
   string verdict reached the precedence table and raised a `KeyError`
   **out of `decide()`** — the engine crashing rather than denying.
4. *(major)* The enforcement matrix checked nothing against reality.
   `verify(probes)` and a real escape probe now make it falsifiable.
