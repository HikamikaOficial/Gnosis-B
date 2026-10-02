# F-17 OS AUTHORITY BOUNDARY — evidence note

BLOCKER C is answered by a REAL, Windows-enforced authority boundary
(src/gnosis/kernel/authority.py):
- AnchorStore labelled HIGH integrity NO_WRITE_UP; publisher/Director HIGH;
  worker launched at MEDIUM integrity (token IL lowered + CreateProcessWithTokenW).
- git-authority-audit.txt: OS-real attack matrix — a Medium worker and its
  children are DENIED {write, create, delete, rename, change-DACL, lower-label,
  take-ownership, shell/python child write, raise-own-integrity}; the High
  publisher is ALLOWED. worker ∩ anchor = ∅ by process authority.
- mutation-check.authority.txt: 7 mutants (AM1..AM7), 0 survived; baseline and
  restored GREEN (13 passed).
- authority-directed.txt: the 13 directed tests (record chain, store append-only,
  publication protocol recomputes the digest and binds the run head, verify uses
  the authoritative digest and fails closed on missing/broken chain).

Threat model: defeats T2 (a malicious same-user Medium worker). NOT T3
(compromised Director — runs HIGH, owns the anchor) or T4 (admin/full-OS —
can relabel). Declared out of scope. No cryptography.

NOT YET DONE (the closure step): wiring the Medium-integrity launch into the
production engine/runner (kernel/engine + runner) and running a fresh FULL
scripts/capture_evidence.py that publishes and verifies against this
authoritative anchor. The full run_capture over ~90k inputs could not be
produced this session (slow synced volume + long-run limit), so F-17 stays
OPEN per the review. §14 (unknown .git -> fail closed) is a decided contract,
implementation deferred to that same closure step.
