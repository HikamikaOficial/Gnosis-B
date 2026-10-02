# ADR-0031 — F-17 is CLOSED

**Status:** accepted / closure record (2026-08-31). **Does not reopen** F-14.
This is a documentation/state closure record only: no production source, test,
or qualification evidence was changed to close F-17.

## Decision

F-17 is **CLOSED** by independent decision after the exact-tree final
qualification demonstrated the composed T2 property.

**Qualified production tree:** `06cdf00ffb2eee4cd176b7d86b0c84beb764e45c` — the
exact production tree exercised by final qualification.
**Final qualification evidence/state commit:** `871792f` — adds final
qualification evidence and state only; its production/test source is identical to
`06cdf00` (0 production files changed).

## Closure basis (the claim — do not broaden)

Under the qualified Windows / Git 2.55.x files-backend / Python-runtime /
deployment contract, a compromised dedicated Worker cannot cause an authoritative
historical-evidence publication that the trusted plane did not authorize, and
relevant unsupported or ambiguous conditions fail closed.

**Explicitly not claimed:** resistance to a compromised Director, Publisher,
Administrator/SYSTEM, kernel, or trusted maintainer; external-PKI source
authenticity; absolute power-loss durability; arbitrary future Git or Python
runtime compatibility.

## Final validation record (exact current-tree results)

- Directed current-tree qualification: **613 passed, 1 skipped, 206 subtests**.
- Full suite: **1510 passed, 1 skipped, 291 subtests, exit 0 — GREEN**.
- Corrected isolated fresh checkout: **475 passed, 1 skipped, 143 subtests**
  (import provenance proven to the extraction).
- Structural proofs 5/5, adversarially verified: exactly ONE production
  authoritative path, Anchor-V2-only writer, worker-unreachable Stage-4 fault
  seam, 15-module publisher closure, no dynamic loading in the publish path.
- OS-real (disposable, rolled back): Stage 5 launcher PASS; Stage 7 git 26/26;
  Stage 6 composition 49/49; Stage 8 provisioning 140/140.
- `mypy --strict` PASS (79 files); Ruff PASS over the F-17 scope; secret scan
  PASS; OS rollback CLEAN by post-check; tracked worktree CLEAN at qualification.
- Accepted pre-existing out-of-scope untracked: `.stfolder/`, `PROJECT_REPORT.md`.

## Final evidence (referenced, not rewritten)

`.gnosis/evidence/20260831T025855Z-f17-final-qualification/`
Final bundle root (SHA-256 of `MANIFEST.sha256`, anchored in the commit message
of `871792f`, outside the mutable bundle):
`f27a5f8acdaa65c0d7b29bb663b48de179342e3287a26aace38b6f2dbccb7305`.
Root-of-trust control: pristine verification PASS; one-byte tamper FAIL;
fresh extraction PASS.

## Stage status

Stages 1–8: **PASS / CLOSED**. Final F-17 Qualification: **PASS**. **F-17: CLOSED.**
**F-14: remains CLOSED.** No stage is reopened absent a future demonstrated
contradiction.

## S6M22 disposition

`S6M22 = NON-BLOCKING / NON-AUTHORITY SURVIVOR.` The mutant removes a redundant
early authorization check in `authorize_publishable`, but cannot change the
authoritative security verdict from REJECT to ACCEPT: the authoritative
`build_anchor_record` boundary gate independently enforces the property (tested
OS-real and by `test_durable_publication`; Stage-7 mutants S7M15/S7M16 on that
chokepoint were CAUGHT), the Worker cannot reach `authorize_publishable` (IPC
grammar accepts only `PUBLISH <run_id>`), and the Stage-7 boundary gate
additionally masks the specific Stage-6 tamper test. It is diagnostic /
defense-in-depth mutation coverage, not an independent T2 barrier. Production code
was NOT modified to kill it. Future assurance-tooling cleanup may
redesign/remove/reclassify it.

## Stale mutation anchors

deployment `DM9` NOT-APPLIED and six F-14 NOT-APPLIED anchors are
mutation-harness maintenance debt from code/schema evolution (V1→V2 deployment
`to_dict`; the Stage-7 rework of `evidence_capture.py`). They are **not** mutation
survivors and were not repaired during this closure-only operation.

## work_queue flake (preserved history)

Stage 8 earlier full-suite runs were RED due to the pre-existing real-clock/50 ms
lease-timing flaky `work_queue` tests (byte-identical to the `ad32bba` baseline,
adjudicated). The final F-17 qualification obtained a genuinely GREEN complete
full suite (1510 passed / exit 0). Earlier RED runs are preserved. The
`work_queue` timing issue is separate test-quality debt outside F-17.

## Historical fresh-checkout note (preserved)

Earlier stages used a fresh-checkout method later shown capable of resolving
imports through the editable `.pth`; those historical claims remain
methodologically degraded and are superseded, for the final F-17 tree, by the
corrected isolated requalification with demonstrated import provenance. Historical
evidence is not rewritten.

## Residuals carried forward (none reopens F-17)

1. S6M22 diagnostic mutation debt.
2. Stale mutation-anchor maintenance (DM9 + six F-14).
3. `work_queue` real-clock flaky test.
4. DPAPI machine binding depends on the NTFS ACL preventing Worker blob read.
5. Physical power-loss / storage durability remains best-effort / bounded.
6. Git support remains the qualified 2.55.x / files contract.
7. Windows 8.3 short-name aliases remain a fail-closed compatibility residual.
8. External source authenticity / PKI remains outside F-17.
9. `kernel.authority` facade cleanup remains technical debt.

Also disclosed at qualification: a content-identical CRLF→LF line-ending artifact
from mutation restore on five kernel files, restored to exact committed bytes via
`git checkout` (`git diff` empty).
