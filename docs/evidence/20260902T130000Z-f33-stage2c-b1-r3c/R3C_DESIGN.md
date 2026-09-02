# F-33 Stage 2C-B1-R3C — Trust-Boundary / Deployment-Identity Reconciliation (DESIGN ONLY)

Design/archaeology only. **No implementation, no OS provisioning, no ACL/topology/
F-17/trust-record change, no provider call.** HEAD `2d0d5c0…`; `src/gnosis` unchanged.

## 1. Exact OS-real delta (carry-in)
Provision digest `c58b54f4…`, launch digest `4c1afb14…`, match=NO, classification
`PACKAGE_CONTENT_CHANGED`: **47 added, 0 removed, 0 changed** — the composed
application/operator tree (`APPLICATION.json`, `operator_entry.py`,
`gnosis/{adapters,contracts,director,kernel,runner,provision/layout}`). All other
components (runtime, runtime_tree, service, all SDDLs, pipe_policy, paths) UNCHANGED.

## 2/3. Sources & one-tree semantic — PHYSICAL CO-LOCATION REQUIRED
- `operator_stack.canonical_package_root(layout) → Path(layout.trust_root)`, docstring:
  "*the ONE authoritative deployed package root (contains `gnosis/`); the same root the
  F-17 Provisioner deploys the trust plane + `python._pth` into.*" (operator_stack.py:180-183, :6)
- `layout.trust_root = code_release_base\publisher` (layout.py:188-190).
- The trust plane (`gnosis/trust/*`) and the application (`gnosis/director,kernel,runner…`)
  are **sub-packages of one `gnosis/` namespace** under a single `python._pth`.
- ADR-0032 (canonical-production-composition) + ADR-0028 (the-composed-trust-path).

**Classification: `PHYSICAL CO-LOCATION REQUIRED`** — a single unambiguous import root
is the point; separating the sub-packages would create two `gnosis/` roots / import
shadowing (see §13/§14). Not merely "no duplicate copies."

## 4. F-17 deployment-identity semantic — "measure EVERY file under trust_root"
`observe_trust_package(root)` (deployment.py:677-696): "*Measure EVERY file under the
deployed trust root. No file is excluded. An excluded file is an unmeasured file, and
an unmeasured file under the trust root is code that can run without the identity
changing.*" It walks `root.rglob("*")` (`_measure_tree`). So `f17_deployment_digest`
means **the entire physical content of `trust_root`** — and, once the app tree is
co-located there, it necessarily includes the app bytes. F-33 is therefore NOT
permitted to add bytes under `trust_root` after that digest is trusted without the
digest moving — by explicit F-17 security contract.

## 5. application_digest semantic
`measure_application_tree(package_root=trust_root, APPLICATION.json manifest)`
(operator_stack.py:433) → `application_tree_digest`. Closed-world over the deployed
`APPLICATION.json`; `deploy_operator_stack` verifies the staged tree against
`APPLICATION.json` **and** the committed source (operator_stack.py:6-28, provision
lines 257-265). **All 47 files (incl. `APPLICATION.json` and `operator_entry.py`) are
covered** by this independently-verified application identity.

## 6. composed_digest semantic
`composed_deployment_digest = H(f17_deployment_digest, application_tree_digest)`
(gnosis_deployment.py:114-121). Binds base-F-17 ⊗ application. It does NOT separately
bind runtime/paths/policy (those are in the F-17 identity). A valid composed record
cannot exist if either operand changes.

## 7. Current identity-scope collision — PROVEN, ACCIDENTAL
Provision order (gnosis_deployment.py:250-277): (251) `base = _base_provision()` →
F-17 installs the **trust plane only** and `base.deployment_digest =
observe_trust_package(trust_root)` is captured **before** the app tree exists; (257)
`deploy_operator_stack` writes the 47 app files **into** `trust_root`; (272) the record
stores the **pre-app** `f17_deployment_digest`. At launch, `canonical_launch`
(gnosis_deployment.py:367-374) re-observes the **post-app** `trust_root` and compares to
the pre-app recorded digest → inevitable mismatch.

**Classification: `ACCIDENTAL IDENTITY-SCOPE COLLISION`.** The app bytes are *intended*
to be covered by `application_tree_digest`; they are *additionally* folded into the
whole-root F-17 re-observation only because of physical co-location + the "measure
everything" contract, while the recorded `f17_deployment_digest` was captured before
the app tree. This also **violates ADR-0032**, which requires the *composed* deployment
to "*receive a fresh deployment/tree measurement*" and to "*not reuse an old*" digest
(ADR-0032:374,441,447) — the launch gate is instead held to the stale pre-composition
substrate digest.

## 8–11. Option designs (NOT implemented)

### Option A — physical separation (app tree outside trust_root)
Install the app tree under a separate root; keep `trust_root` immutable/substrate-only.
- **Security**: substrate immutable ✓; but two `gnosis/` roots → import ambiguity /
  shadowing under `python -I -B` + `python._pth` (the trust plane and app are the SAME
  `gnosis` namespace). Requires merging path entries → developer-checkout-style
  fragility that ADR-0028 explicitly warns against ("*the fresh-checkout run was
  importing the working tree*", ADR-0028:106).
- **One-tree**: breaks `PHYSICAL CO-LOCATION REQUIRED`.
- **Blast radius: LARGE** (layout, import model, python._pth, F-17 trust_root meaning).
- **Verdict: REJECT** — recreates import-graph ambiguity; weakens the very property
  one-tree exists to guarantee.

### Option B — effective/composed deployment identity (RECOMMENDED)
Keep `f17_deployment_digest` (pre-app substrate) as **immutable provenance** in the
record; add an **`effective_deployment_digest` = `observe_trust_package(trust_root)`
measured AFTER `deploy_operator_stack`** (the final one-tree root). `canonical_launch`'s
fresh pre-spawn predicate becomes: fresh whole-root observation ==
`record.effective_deployment_digest` (detects ANY mutation — substrate, app, or an
injected extra file), AND fresh `application_tree_digest` == recorded (app closed-world
scope), AND composed binding valid, AND runtime/service identity valid.
- **Security**: substrate mutation, app mutation, and injected-file attacks all move the
  whole-root effective digest → fail closed. App bytes are independently verified before
  entering the root (deploy_operator_stack vs APPLICATION.json + source), so this is NOT
  "trust whatever is present." No trusted-digest overwrite; no exclusion; no gate move.
- **One-tree**: preserved (co-location kept).
- **ADR-0032**: satisfied — the *composed* tree gets a fresh measurement; the old
  substrate digest is retained as provenance, not reused as the launch operand.
- **F-17**: `observe_trust_package`/`observe_deployment` UNCHANGED (still measure
  everything); only F-33 composition records an additional digest and `canonical_launch`
  compares against it.
- **Blast radius: MEDIUM** (composed record schema + `provision()` + `canonical_launch`
  + `verify()` + tests + OS-real harness); F-17 untouched.
- **Verdict: RECOMMEND.**

### Option C — post-composition F-17 observation (reuse `f17_deployment_digest`)
Record `f17_deployment_digest` over the final post-app root and keep verifying that.
- **Security**: functionally sound (final root is verified assembly), BUT **blurs the
  F-17 boundary** — `f17_deployment_digest` would now attest F-33 app bytes and lose its
  meaning as substrate provenance (§10 concern), and **reuses one field for two
  meanings** (violates §16). No bootstrap circularity (app pre-verified), but naming/
  provenance clarity is lost.
- **Blast radius: SMALL–MEDIUM.**
- **Verdict: REJECT in favor of B** — B is C done cleanly (distinct field + retained
  provenance).

### Option D — scoped F-17 observation (measure substrate only under one-tree)
Keep co-location but have the F-17 re-observation measure only the substrate manifest.
- **Security**: **DIRECTLY VIOLATES** `observe_trust_package`'s stated invariant ("no
  file is excluded; an unmeasured file under the trust root is code that can run"). Any
  file not in the substrate manifest — including a malicious overlay — would become
  invisible to F-17. Requires an exclusion list, exactly what the contract forbids.
- **Verdict: REJECT (unsafe).**

## 12. Attack analysis (recommended Option B)
- **Injection after base trust / extra-file** → whole-root effective re-observation
  changes → FAIL CLOSED. (A/D would risk invisibility; B catches it because it measures
  everything at launch.)
- **Substrate replacement** → effective digest changes → FAIL.
- **Application mutation** → effective digest AND application_tree_digest change → FAIL.
- **Record substitution** → composed binding + schema versioning + reading the record
  back from disk (provision lines 294+) → FAIL.
- **TOCTOU (change between final observe and spawn)** → `canonical_launch` performs the
  fresh observation immediately before spawn (gnosis_deployment.py:352-361); window is
  the qualified minimum, unchanged by B.
- **Path relocation** → identity-bearing paths participate → PATH change → FAIL.
- **Rollback/recovery mixed state** → residue/journal rollback unchanged; effective
  digest of a partial tree ≠ recorded → FAIL.

## 13. Import/path security
Production launch is `runtime\python.exe -I -B operator_entry.py` with `python._pth`
pointing at the one package root (operator_stack.py:6). Option B keeps ONE `gnosis/`
root → single unambiguous import graph, no shadowing, no checkout fallback. Option A
would introduce a second root and is rejected on this ground.

## 14. Duplicate-copy problem
The PACK/ADR-0028 rejection was of **two competing copies of the same trusted package**
(import shadowing / editable-checkout capture). Option B keeps a single copy. Option A's
"separate substrate + app root" is not literally two copies of one package, but it does
split one `gnosis` namespace across two roots — the same class of import ambiguity — so
it is still rejected.

## 15. Required fresh pre-launch predicate (Option B)
`fresh whole-root effective identity == recorded effective_deployment_digest` ∧ `fresh
application_tree_digest == recorded` ∧ `composed binding valid` ∧ `runtime/service
identity valid` → THEN spawn. Never one stale pre-app record; never "trust present".

## 16. Record semantics (Option B)
Composed record fields: keep `f17_deployment_digest` (**base substrate provenance,
immutable**), `application_tree_digest`; **add `effective_deployment_digest`** (final
one-tree whole-root identity, the launch operand); keep `composed_deployment_digest`
(provenance binding). Distinct names, distinct meanings — no reuse of
`f17_deployment_digest` for the effective tree. Schema version bump.

## 17. F-17 production change — NO
`observe_trust_package`, `observe_deployment`, `provisioner.py`, `layout.py`,
`winapi.py` all UNCHANGED. F-33 adapts around the qualified F-17 boundary (records +
verifies an effective identity). This is the strong-preference path.

## 18. F-33 change surface (Option B, for the future implementation slice)
`src/gnosis/provision/gnosis_deployment.py` (composed record schema +
`composed_deployment_digest` inputs + `provision()` records effective digest post-deploy
+ `canonical_launch`/`verify()` verify effective identity), composed-record tests,
`scripts/run_f33_stage2c_b1_osreal.py` harness (already surfaces identity_delta).
Blast radius **MEDIUM**.

## 19. Qualification/evidence impact (Option B)
Preserved without reopening: 2A, 2B.1/2, 2C-A, 2C-B0, B1-PRE0, B1-R1, R2A/B/C, R3A/B,
NAMED-PIPE READINESS. Requires re-qualification: 2C-PACK composed-record/gate evidence
(schema + canonical_launch predicate change) — a bounded re-qualification of the
composed identity, consistent with ADR-0032's "fresh composed qualification" mandate.

## 20/21. Design invariants & decision matrix
All twelve invariants (§20 of the brief) are satisfied by B (substrate+app mutation
detected, no silent extra file, provision==launch semantics agree, fresh final
verification, no "trust present", no digest overwrite, no gate bypass, no checkout dep,
single package copy, Publisher/Worker on qualified deployment only, exact rollback).

| Criterion | A | B | C | D |
|---|--:|--:|--:|--:|
| preserves F-17 semantics | ~ | **+** | − (boundary blur) | −− (violates) |
| preserves one-tree | −− | **+** | + | + |
| application integrity | + | **+** | + | + |
| unexpected-file detection | − (invisible if outside) | **+** | + | −− |
| bootstrap soundness | + | **+** | + | ~ |
| TOCTOU strength | + | **+** | + | + |
| import/path safety | −− | **+** | + | + |
| impl blast radius | − (large) | ~ (medium) | + (small) | + (small) |
| evidence reuse | − | **~** | + | + |
| conceptual clarity | ~ | **+** | − (field reuse) | − |

## 22. Recommended architecture
**OPTION B — effective/composed deployment identity** (base-F-17 provenance retained
immutable; add `effective_deployment_digest` over the final one-tree; `canonical_launch`
freshly verifies the effective identity + application identity + binding). Accepts the
§23 hypothesis, refined: the fresh launch operand is the **whole-root** effective digest
(because `observe_trust_package` measures everything — a substrate-only launch check is
impossible without violating the F-17 contract), plus the application manifest for
app-scope mutation detection.

## 23/24. Hypotheses
§23 hypothesis **ACCEPTED (refined as above)**. §24 (physical separation stronger only
if one-tree meant "no duplicate copies") **REJECTED** — evidence shows one-tree means a
single co-located `gnosis` import root (`python._pth`), so separation reintroduces import
ambiguity.

## 25/26. Effects & tests
No code, no OS provisioning, no provider calls; live ledger 1/5. Only read-only source/
ADR archaeology performed; no tests run/added (not required for design).
