# F-17 FINAL QUALIFICATION — evidence bundle

**Exact source tree:** commit `06cdf00ffb2eee4cd176b7d86b0c84beb764e45c` (master).
Chain: `ad32bba` (Stage 7) → `54b6a69` → `77c639a` → `dae26a0` → `06cdf00`.
Tracked worktree clean; qualification originated from this exact tree.

**Central question:** Under T2 (compromised dedicated Worker; Director, Publisher,
Administrator/SYSTEM, kernel and trusted maintainer are trusted), can a Worker
cause an authoritative publication the trusted plane did not authorize?
**Answer demonstrated: NO.**

## Results

### Structural security proofs (read-only, adversarially verified) — `structural_analysis.json`
All five PASS, each re-checked by an independent skeptic that agreed:
- **single-path** — exactly ONE production authoritative path: worker `PUBLISH <run_id>`
  → `PipeServer` → `Publisher.handle` → `durable_publish` → `build_anchor_record`
  → Anchor V2 record + committed watermark. `durable_publish` has one caller;
  `AnchorStore.append` callers = that path + the TEST-only `publish_anchor`;
  `kernel.authority` is a dead re-export imported by no production module;
  Director/worker_launcher/transport have zero anchor/watermark writers.
- **v1-v2** — the production writer emits `gnosis.anchor.v2` only; V1 is read/verify-only.
- **fault-seam** — the Stage 4 fault-injection seam is settable only by trusted
  in-process code; no worker-controlled input (IPC/LaunchSpec/candidate/env/run_id)
  reaches it.
- **closure** — `publisher_service` import closure = 15 gnosis modules; no
  engine/provider/worker_launcher/deployment/orchestration/legacy leak.
- **dynamic-world** — no worker-triggerable dynamic import; the publish path has
  no dynamic code loading.

### OS-real composition chain — `osreal/` (all rolled back, disposable production-equivalent names)
`OSREAL_ALLOK=YES`:
- Stage 5 worker launcher: ALL CHECKS PASSED (dedicated SID, non-admin, Medium
  integrity, no dangerous privileges, CREATE_SUSPENDED identity verify, Job
  containment, sealed LaunchSpec, no same-user fallback).
- Stage 7 git matrix: **26/26** (2.55.x/files CLEAN; unknown `.git` surfaces
  UNKNOWN→MACHINERY_UNQUALIFIED→no publication; packed-refs/replace/unknown-ns).
- Stage 6 composition: **49/49** (Director→Worker→Publisher→Anchor v2; pre-publish
  REJECT; trusted gate PUBLISHABLE; IPC adversarial matrix; service attacks; bundle
  tamper→REJECT; idempotent retry; restart survives).
- Stage 8 provisioning: **140/140** (clean install; RESTRICTED service SID; ACL
  matrix worker-denied on every trusted root; import provenance; deployment digest
  stable + runtime-tree bound; composition incl. fail-closed on non-CLEAN verdict;
  idempotence; update/failed-update/rollback; uninstall + OS post-check).

### Directed requalification (exact tree, excl work_queue) — `directed/`
**613 passed, 1 skipped, 206 subtests.** Surfaces: trust boundary, deployment,
RunIdentity/authority, durable publication, worker launcher, orchestration,
publisher service + pipe, Git Stage 7 (surface/enforcement/backend/evidence),
provisioning, F-14 (evidence binding).

### Mutation union — `mutation/`
Per suite (each reported separately):

| suite | mutants | genuine survivors | not-applied (stale anchors) |
|---|---|---|---|
| stage8 | 21 | 0 | 0 |
| stage7 | 19 | 0 | 0 |
| worker_launcher | 38 | 0 | 0 |
| run_identity | 17 | 0 | 0 |
| publication | 21 | 0 | 0 |
| authority | 13 | 0 | 0 |
| general (mutation_check) | 9 | 0 | 0 |
| deployment | 11 | 0 | 1 (DM9) |
| f14 | 56 | 0 | 6 (MF44/49/50/52/54/56) |
| stage6 | 34 | **1 (S6M22)** | 0 |

- **DM9 / the 6 f14 NOT-APPLIED are stale anchors, not survivors** — the targeted
  source evolved (V1→V2 deployment `to_dict`; the Stage-7 rework of
  `evidence_capture.py`), so those one-line anchors no longer match and the
  mutation is never applied. Nothing evaded detection. The properties remain
  covered: DM9 ("digest covers the runtime") is guarded by the V2
  `binds_runtime_tree` invariant `create_trusted_run` enforces, the OS-real Stage 8
  "binds the runtime tree / >1000 files" checks, and `test_deployment_identity`.
- **S6M22 is a genuine survivor, analysed as NON-RELEVANT to T2** — see below.

### S6M22 — the one genuine survivor (non-relevant to the T2 guarantee)
S6M22 removes the **early** bundle-verify check inside `authorize_publishable`
(`if not result.verified: raise` → `if False:`). It survives, but does not weaken
the T2 guarantee, for three independent reasons:
1. **Worker-unreachable.** The IPC grammar accepts only `PUBLISH <run_id>`
   (`publisher.py:59`); `authorize_publishable` is trusted-Director-only. The T2
   adversary (Worker) cannot invoke the weakened check at all.
2. **Authoritative gate independently enforces it.** `build_anchor_record`
   (`anchor.py:475-477`), the single Anchor-V2 chokepoint every publication passes,
   re-runs `verify_bundle` and raises `AuthorityUnavailable` on an unverifiable
   bundle — so no unverifiable bundle can be anchored regardless of the authorize
   check. This is tested OS-real (Stage 6 `REJECTED:AuthorityUnavailable`) and by
   `test_durable_publication` (cross-head/tampered refusals); Stage 7 mutants
   S7M15/S7M16 on `build_anchor_record` gates were CAUGHT.
3. **Why it survives its suite:** the Stage-6 killing test
   (`test_a_tampered_bundle_is_refused`) tampers by writing `SUMMARY.json = "{}"`,
   which fails BOTH the verify check AND the Stage-7 boundary-verdict gate that now
   immediately follows it in `authorize_publishable`; with the verify check removed,
   the boundary gate still refuses that tamper, so the test still passes.
It is a redundant defense-in-depth check masked by two other layers. Per the
qualification mandate it was **not** repaired. Suggested future (out of scope):
add a Stage-6 test with an unverifiable-but-CLEAN-boundary bundle to kill S6M22.

### Isolated fresh checkout — `fresh_checkout/`
**475 passed, 1 skipped, 143 subtests.** Preflight proved `import gnosis` resolved
to the git-archive **extraction** (`...\gnosis-fresh-*\tree\src\gnosis\__init__.py`),
not the working tree — corrected-method provenance.

### Full suite — `full_suite/`
**GREEN — 1510 passed, 1 skipped, 291 subtests passed, exit 0** (16:35), on the
exact tree. The known `work_queue` real-clock/50 ms-TTL timing flake (adjudicated
under Stage 8 as pre-existing and code-byte-identical to `ad32bba`) did not fire
this run, so a genuine exit-0 complete run was obtained; no full-suite adjudication
was needed.

### Static quality
- `mypy --strict src`: clean (79 source files).
- `ruff`: clean over F-17 code; 13 pre-existing findings in unrelated modules
  (runner/contracts/other kernel), none in trust/provision/F-17-kernel — reported
  as the existing baseline.
- secret scan: clean (only redaction-test fixtures in `tests/test_redaction.py`).

### Line-ending restore artifact (disclosed; content-identical)
The f14/general mutation harnesses restore edited files with `write_text(newline="")`
(LF). Five kernel files committed as CRLF (`capture_evidence.py`,
`evidence_capture.py`, `git_evidence.py`, `input_lock.py`, `write_observer.py`)
were left LF after the mutation phase — `git diff` shows **zero textual change**
(line-ending only). Python is newline-agnostic, so the directed/fresh-checkout/
full-suite runs executed identical code; the OS-real probes ran BEFORE the mutation
phase on pristine bytes, so no measured deployment digest was affected. The working
tree was restored to the exact committed bytes with `git checkout` (verified: each
file's blob == its `06cdf00` blob).

## TCB (reported separately; never summed)
- project-source Trust Plane (`src/gnosis/trust`): **5,976 LOC / 15 modules**.
- Publisher import closure: **15 modules / 3,334 LOC**.
- Bootstrap closure: **8 modules / 1,131 LOC**.
- Trusted Python runtime: **3,434 files / 65,373,965 bytes (~62.3 MB)**.
- Provisioning maintenance code (`src/gnosis/provision`): **963 LOC / 4 modules**
  (not imported by the publisher runtime).

## OS post-check (observed)
No worker accounts, no services, no trusted/state/toolchain roots, no DPAPI blob,
no probe pipe/process, only the main git worktree, no probe temp dirs.

## Root of trust
`MANIFEST.sha256` lists a SHA-256 for every other file in this bundle;
`BUNDLE_ROOT_SHA256` (SHA-256 of the manifest) is recorded in the git commit
message that adds this bundle — an anchor OUTSIDE the mutable bundle. Tamper
negative control: a pristine copy verifies; a 1-byte flip changes the root
(detected); a fresh re-extract verifies again.

## Claim boundary
Under the qualified Windows / Git (2.55.x, files) / Python-runtime / deployment
contract and the T2 threat model, a compromised Worker cannot cause an
authoritative historical-evidence publication that the trusted plane did not
authorize, and relevant unsupported/ambiguous conditions fail closed. NOT claimed:
resistance to a compromised Director/Publisher/Administrator/SYSTEM/kernel/trusted
maintainer; external-PKI source authenticity; absolute power-loss durability;
arbitrary future Git/Python compatibility.
