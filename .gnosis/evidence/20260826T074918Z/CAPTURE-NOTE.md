# F-17 third review (BLOCKER A) — evidence note

This bundle carries the third review's evidence for the BLOCKER A repair
(commit ff37069): the resolution-redirect classification and the
git_resolution_faithful start gate.

Artifacts:
- mutation-check.f14-round17.txt — 56 mutants (MF1..MF56), 0 survived;
  baseline and restored suites GREEN (204 passed). MF51..MF56 target the
  new BLOCKER A guarantees.
- git-resolution-audit.txt — OS-real (git 2.55.0.windows.4): refs/replace
  (loose, packed, raw packed-refs edit), alternates, grafts, shallow,
  config.worktree; the start gate refuses each and the interval classifier
  judges each; a pre-existing replace fails closed (MACHINERY_REDIRECTED,
  exit 11, 0 checks), an ABA is judged (MACHINERY_MUTATED, exit 9), a clean
  repo stays CLEAN (no false positive).
- capture-summary.json — the SUMMARY of a full scripts/capture_evidence.py
  run over ff37069: BOUND, boundary CLEAN (0 violations, 41 machinery
  events, 0 judged), evidence_valid true, 90,350 byte-bound inputs, mypy
  clean, ruff at the 19 baseline. pytest: 1075 passed, and the ONLY failure
  is the pre-existing work-queue timing flake
  (test_work_queue.py::...::test_concurrent_workers_never_run_a_brief_twice,
  ~1 in 5 under a 50ms lease TTL) — documented in docs/NEXT_ACTIONS.md and
  NOT F-17. Every F-17/F-14 test is in the 1075 passed.

Why capture-summary.json rather than the full run_capture bundle: on this
workstation the evidence capture reads and hashes ~90k inputs (~2.4 GB of
external-repository sources) through their handles before the checks run.
On this sessions synced/slow volume that cold pass, plus the full
suite, exceeds the environments long-run limit; only a warm-cache run
completed (its SUMMARY is here). To regenerate the full bundle when the
input cache is warm, run, detached, from the main checkout:

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/capture_evidence.py

verify_bundle over THIS bundle is self-consistency; verify_bundle with the
recorded bundle_digest (ADR-0027 third-review Evidence) is the
tamper-evidence check.
