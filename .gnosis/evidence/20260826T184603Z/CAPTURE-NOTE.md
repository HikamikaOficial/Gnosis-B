# F-17 OS AUTHORITY BOUNDARY (sixth review) — evidence note

The Windows-enforced boundary (src/gnosis/kernel/authority.py) plus the three
review-added blockers, demonstrated OS-real:
- git-authority-audit.txt (1): worker Medium DENIED all anchor writes; publisher High ALLOWED.
- git-authority-audit.txt (2): BLOCKER A — no privileged-handle inheritance
  (CreateProcessWithTokenW); BLOCKER B — High-labelled trusted code is
  readable/importable but not worker-writable. assert_integrity() fails closed
  if the worker/publisher runs at the wrong level.
- mutation-check.authority.txt: 8 mutants (AM1..AM8), 0 survived; baseline/restored GREEN (18 passed).
- authority-directed.txt: 18 directed tests.

Threat: defeats T2 (malicious same-user Medium worker). NOT T3/T4 (declared).

OPEN findings that keep F-17 OPEN (closure steps):
1. BLOCKER B, real: the product src/ (and the .venv interpreter) are CURRENTLY
   Medium-writable, so a worker could poison the publisher code the High
   Director later runs. The closure wiring MUST label the trusted-code root
   High NO_WRITE_UP (readable, not writable) before the boundary is complete.
2. BLOCKER C: publish_anchor takes identity as a parameter and never adopts it
   from the bundle (demonstrated), but the wiring must SOURCE RunIdentity from
   High-integrity Director state (its run registration), not from worker output.
3. Wiring the Medium launch into the production engine/runner.
4. §14 unknown-.git fail-closed implementation.
5. A fresh FULL run_capture (env-blocked on this slow volume).
Per the review, no fresh full capture => do NOT close F-17.
