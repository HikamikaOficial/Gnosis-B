# F-17 Stage 1 — independent-review hardening evidence

Acts on the Stage-1 review verdict `APPROVE_WITH_ONE_FINDING` over HEAD
`983edb5`: the trust-plane boundary was enforced by a BLACKLIST of worker-plane
name substrings, the wrong polarity for a TCB. Measured: that blacklist would
have admitted **28 of the 56** non-TCB internal `gnosis.*` modules in silence.

Inverted to a **closed-world allowlist** — `DEFAULT = NOT ALLOWED` for internal
`gnosis.*`, with the enforced property `loaded gnosis module ∉ TRUST_ALLOWLIST
→ TEST FAIL`, name-agnostic (a real, randomly-named new module is created and
imported for real to prove it). A hole in the model itself was found and closed:
a function-body (lazy) import is invisible to any load-time closure, so an AST
scan of `src/gnosis/trust/**` now refuses undeclared internal imports at any
nesting level.

**Production source unchanged** — the diff touches only
`tests/test_trust_boundary.py` and `scripts/mutation_check_authority.py`.

Directed tests 33/33 (HIGH-integrity run, OS-boundary tests executed);
mutation 13/13 CAUGHT, 0 survived, including **AM12** (module-level unqualified
internal dep) and **AM13** (the lazy-import bypass); mypy clean over 62 source
files; ruff clean on the test file with the mutation script at its exact
committed 6-ISC004 baseline.

**TCB size claim corrected, three measured metrics:** static functional slice
**265 LOC**; runtime trusted closure at load time **522 LOC** (`trust.launch` is
trusted code, not "conceptually unused"); runtime trusted closure at publish
time **3966 LOC**, because the lazy `verify_bundle` import drags in
`evidence_capture`+`git_evidence`+`input_lock`+`write_observer` (+3444) and that
code recomputes the digest that gets anchored. The publish-time number is the
security-relevant one. It is **recorded, not reduced** — reducing it is Stage-6
work.

The Stage-1 `229 passed / 1 failed` run is still **NOT** recorded as GREEN; the
F-14 fixture was deliberately not repaired here.

Stage 2 NOT started. F-17 stays OPEN. See `STAGE1-HARDENING-RESULTS.txt`.
