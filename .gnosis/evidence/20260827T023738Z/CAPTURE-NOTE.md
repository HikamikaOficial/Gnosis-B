# F-17 Stage 1 (trust-plane split) evidence

Structural split; behavior_before == behavior_after. Implementation tree at
HEAD 7d9d075. Directed tests 26/26; mutation 11/11 CAUGHT (0 survived); mypy
clean (62 files); ruff clean on new files; TCB load-closure = canonical +
trust.* only (zero forbidden worker modules). One F-14 evidence-binding test
hit a git-subprocess environment flaky under load (exit 128) and passes in
isolation - recorded, not a split regression, full run NOT declared GREEN.
See STAGE1-RESULTS.txt.
