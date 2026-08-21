# ADR-0024 — Multi-credential rotation: a privilege boundary, not a pool

- Status: ACCEPTED
- Date: 2026-08-21
- Evidence: `.gnosis/evidence/20260821T154202Z/` (740 passed, mypy strict
  clean over 55 files, ruff at the 19-finding baseline);
  `tests/test_credentials.py` (16 tests),
  `tests/test_pipeline.py::TestRotationReachesTheLaunch` (8),
  `tests/test_scheduler.py::TestRotationAtTheEnginesLaunch` (5).
- Independent review: **DONE 2026-08-21, verdict FAIL, 15 findings** —
  by an independent read-only SECURITY reviewer in a clean context, not
  Codex. One critical, ten major. Nine repaired, six recorded as still
  open; see the addendum. Two enforcement-matrix levels were downgraded
  as a result.
- Builds on: ADR-0023 (the probe), ADR-0016 (the residual this closes),
  ADR-0012 (holds keyed per credential all along).

## Context

`TaskScheduler` took one `credential` string fixed at construction, so
"the account is held" and "this key is held" were the same statement and
there was nothing to rotate to. The durable hold rows were already
credential-keyed; only the scheduler was bound to one.

**The finding that set the scope:** `subprocess.Popen` was called without
`env`, so every child inherited the parent's environment. There was no
mechanism by which a launch could run as a different identity at all. Any
"rotation" built on top would have decided one thing while the child
authenticated as another — a fiction, and this time a fiction about
billing.

## Decision

### A credential set is a privilege boundary

Two constitution rules live exactly here: rule 25 (subscription
credentials are not an improvised API) and rule 26 (no silent fallback to
paid APIs). Both are about **crossing**, so the boundary is data the
kernel checks rather than prose someone remembers. `CredentialKind` is
`SUBSCRIPTION | METERED | LOCAL`, and `CredentialPool.select` stays inside
the primary's kind unless another kind is **explicitly authorised** —
with METERED never selected without authorisation whatever the primary
is, since a metered primary otherwise authorised every metered key
(addendum finding 6).

An exhausted seat is therefore a reason to wait, not a reason to start
billing. Every credential held → park (rule 6), nobody charged (rule 7).

### Secrets are never in the kernel

A `Credential` names the environment variables its value lives in:
`{"ANTHROPIC_API_KEY": "GNOSIS_KEY_B"}` maps the child's variable to the
parent's. The kernel can name, order, hold, audit and record a credential
without ever holding its secret, so no ledger, run record, cassette or
evidence file can leak one. `to_dict` carries ids and variable *names*.

### The binding is real, or the launch does not happen

`Credential.environment` **raises** when a source variable is unset.
Returning the ambient environment would launch as whatever identity is
configured, report a successful rotation, and bill somebody nobody chose.
It is bound before the policy verdict and before the budget is charged: a
credential that cannot be bound is a configuration fault, and paying a
launch for it is waste on top of a fault.

### The child sees one identity

`CredentialPool.launch_environment` strips every credential's source
variable AND a named list of ambient provider variables
(`SENSITIVE_ENVIRONMENT_VARIABLES`) before binding the chosen one. The
first version stripped only the pool's own declarations, which left an
operator's ambient key readable by a child on a seat (addendum finding
5). It is a deny-list, not an allow-list, and the matrix says so.
Binding alone left the metered key readable in the environment of a child
running on a seat — which enforces the boundary against the kernel and
not against the agent, the only party the rule is about (rule 13).

### Both launch paths, because there are two

`GatedAgentRunner` (review, fix, re-review) and `TaskScheduler.submit` →
`TaskEngine.execute_task` (the implementation) are different paths.
Wiring one would leave the other on a single credential while the
mechanism claimed otherwise — the ADR-0023 lesson, one unit later.
`GovernedPipeline` takes the pool for the gated launches; the scheduler
takes one for its own.

`ReplayingCLIRunner` FORWARDS `env` to the inner runner and keeps it out
of the cassette key. The first version accepted and ignored it, reasoning
that a replayed launch spends no credential — true in REPLAY mode, and
false in RECORD, which is the default: a cassette miss runs a real child
(addendum finding 1). Keeping the environment out of the key remains
right, because a cassette is a file that gets committed.

## Known limitations (stated, not implied)

- **The kernel cannot verify the child honoured the binding.** It builds
  the environment and passes it to `Popen`; a CLI that prefers a cached
  session token, a config file or an OS keychain would run every
  "rotation" as the same identity and every check here would still pass.
  Declared as `credentials/child_honours_the_binding = IGNORED` —
  downgraded from PROMPT_ONLY by the independent review, because
  PROMPT_ONLY means asked-for-not-enforced and nothing asks.
  **This is the limit of the whole mechanism** and it is not small.
- **A declared kind is trusted.** A credential labelled SUBSCRIPTION
  could be a metered key. `credentials/declared_kind_is_true = IGNORED`.
- **The base environment is captured once**, at construction. An operator
  who exports a new key mid-process is not seen until a restart. Chosen
  for reproducibility: a binding built from an environment that changed
  underneath is not one.
- **No per-credential budget.** `BudgetStore` bounds launches per brief,
  not spend per key, so "this metered key may cost at most X" is not
  expressible.
- **Selection is first-fit in declared order**, not least-loaded or
  round-robin. Deterministic on purpose — two workers reading the same
  configuration must rotate the same way — but it concentrates load on
  the first credential.
- **An unbindable credential raises rather than being skipped.** Routing
  around it would hide a misconfiguration behind an availability
  behaviour.

## Self-review (written before any independent verdict was available)

1. *(critical, repaired before it shipped)* **The launch could not bind a
   credential at all.** `Popen` had no `env`. Found by asking, before
   designing, whether the child process could actually run as a different
   identity — the question that decides whether the unit is real.
2. *(critical, repaired)* **The child could read the other credentials'
   secrets.** Binding the chosen credential left every other source
   variable in its environment, so an agent on a subscription seat could
   have spent the metered key directly. The boundary was enforced against
   the kernel, not against the agent. Mutation-checked.
3. *(major, repaired)* **Only one of the two launch paths rotated.** The
   pipeline passed no pool, and the implementation launch goes through
   the engine, not the gated runner. Caught by grepping the production
   wiring before writing this ADR — the same check that caught ADR-0023's
   critical, applied on purpose this time.
4. *(major, repaired)* **The binding was built after the budget was
   charged**, so an unbindable credential cost a launch that never
   happened.
5. *(minor, repaired)* **`ReplayingCLIRunner` would have raised on `env`**,
   and a naive fix would have put the environment in the cassette key —
   writing a secret into a committed file.

## Independent review addendum (2026-08-21, verdict FAIL, 15 findings)

Reviewed by an independent read-only security agent. The self-review
found five defects; this pass found fifteen, and its most important
contribution is not a bug but a **level**: two matrix rows claimed HARD
for properties the code did not deliver.

1. *(critical, repaired)* **The record path dropped the binding.**
   `ReplayingCLIRunner.live()` re-invoked the inner runner without
   `env`, and RECORD is the default mode — so on a cassette miss a real
   child ran, spent a real credential, and authenticated as the ambient
   identity while `Rotation` recorded the one the kernel chose. The
   "deliberately ignored" reasoning in the self-review was right about
   the cassette KEY and wrong about the launch. Forwarded now, still out
   of the key.
2. *(major, repaired)* **A pool with no hold gate was silently ignored.**
   The guard was `holds is not None and credentials is not None`, so a
   caller who configured rotation but no gate got no rotation, no
   binding, and no error — the one guarantee the mechanism sells, given
   away by a missing collaborator.
3. *(major, repaired)* **An empty source variable bound "successfully".**
   Every CLI treats an empty key as unset and falls back to its config
   file or keychain, so an empty binding IS the ambient fallback wearing
   a successful rotation's clothes — and `set VAR=` produces exactly it.
4. *(major, repaired)* **`env_clear` and `env_from` had opposite
   precedence** in `environment()` and `launch_environment()`. The same
   credential yielded two different environments, and on the launch path
   a variable named in both was cleared *after* being bound — silently
   unbinding the chosen credential while `rotations` recorded success.
   "Clear the stale one, then bind mine" now means that in both.
5. *(major, repaired)* **The child could still see ambient provider
   keys.** `launch_environment` stripped only the pool's OWN declared
   source variables, so an operator's live `ANTHROPIC_API_KEY` — declared
   by no credential — sat in the environment of a child launched on a
   subscription seat, which could simply spend it. The self-review's
   finding 2 was therefore only half-repaired: it closed the
   kernel-declared leak and left the ambient one. A named deny-list
   (`SENSITIVE_ENVIRONMENT_VARIABLES`) now goes too. It is a deny-list,
   not an allow-list, and the matrix says so.
6. *(major, repaired)* **A METERED primary authorised every metered
   key.** `allowed = {primary.kind}` meant an exhausted metered key
   simply became a second one, with no authorisation and no record.
   Rule 26 is about money nobody authorised and the per-key case is
   exactly that: METERED is now never selected without explicit
   authorisation, whatever the primary is.
7. *(major, corrected)* **`no_ambient_fallback = HARD` was not honest** —
   four paths reached the ambient environment with a pool configured and
   no error (findings 1-4). All are repaired, and the level is now
   SANDBOX_APPROX because the guarantee still depends on every
   duck-typed wrapper runner forwarding `env`, which no type enforces.
8. *(major, corrected)* **`child_honours_the_binding = PROMPT_ONLY` was
   one level too generous.** PROMPT_ONLY means asked-for-not-enforced;
   nothing asks. There is no instruction to the CLI, no post-hoc check,
   and `HOME` reaches the child so a cached session token is right
   there. It is `IGNORED`.

**Still open:**

- **Crossing the boundary is a constructor kwarg, not an approval.**
  `agent_launch_snapshot` contains no credential, so an operator's
  approval for a seat launch is byte-identical to the same launch on a
  metered key. Binding the credential into the policy action identity is
  the fix and it is not done.
- **Nothing in `src/` constructs a pool, a scheduler or a pipeline.**
  `billing_boundary = HARD` is real but inert until an entry point
  exists — the same parallel-fiction condition, at the level of the
  program rather than the mechanism.
- **Cassettes and evidence store child streams byte-exact and
  unredacted.** `redact()` is never applied on the cassette path, and a
  child that echoes its environment writes a bound credential into a
  file that gets committed. The existing patterns would not match a bare
  OAuth token anyway.
- **Rotation provenance is never persisted.** `GatedAgentRunner.
  rotations` is an in-memory list nothing reads, and the scheduler path
  records no credential at all — so "why is this running on the metered
  key" must still be reconstructed.
- **`HOME`/`CLAUDE_CONFIG_DIR` necessarily reach the child**, which is
  the mechanism behind `child_honours_the_binding`.
- **`frozen=True` over a mutable `Mapping`**: a caller passing a live
  dict can mutate `env_from` after validation.

Evidence for the repairs: `.gnosis/evidence/20260821T170951Z/`.
