# ADR-0024 — Multi-credential rotation: a privilege boundary, not a pool

- Status: ACCEPTED
- Date: 2026-08-21
- Evidence: `.gnosis/evidence/20260821T154202Z/` (740 passed, mypy strict
  clean over 55 files, ruff at the 19-finding baseline);
  `tests/test_credentials.py` (16 tests),
  `tests/test_pipeline.py::TestRotationReachesTheLaunch` (8),
  `tests/test_scheduler.py::TestRotationAtTheEnginesLaunch` (5).
- Independent review: **NOT DONE — Codex usage limit** (reset reported
  2026-09-20). Third consecutive self-reviewed unit; recorded as review
  debt in `NEXT_ACTIONS.md`.
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
the primary's kind unless another kind is **explicitly authorised**.

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

`CredentialPool.launch_environment` strips **every** credential's source
variable from the child's environment before binding the chosen one.
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

`ReplayingCLIRunner` accepts `env` and deliberately ignores it: a
replayed launch spends no credential, and putting the environment in the
cassette key would write a secret into a file that gets committed.

## Known limitations (stated, not implied)

- **The kernel cannot verify the child honoured the binding.** It builds
  the environment and passes it to `Popen`; a CLI that prefers a cached
  session token, a config file or an OS keychain would run every
  "rotation" as the same identity and every check here would still pass.
  Declared as `credentials/child_honours_the_binding = PROMPT_ONLY`.
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

## Self-review (no independent verdict available)

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
