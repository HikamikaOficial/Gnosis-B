# cass_memory_system: STOPPED on license grounds (important -- read first)

`Dicklesworthstone/cass_memory_system`'s LICENSE file is titled "MIT
License (with OpenAI/Anthropic Rider)". The rider is not boilerplate --
it is a categorical restriction:

> "Restricted Parties" means OpenAI, L.L.C.; Anthropic, PBC; any of their
> respective Affiliates; and any person or entity acting directly or
> indirectly on behalf of, for the benefit of, or under the direction of
> any of the foregoing... Notwithstanding any other provision of this
> License, no rights are granted to any Restricted Party... "use"
> includes, without limitation: copying, modifying,... benchmarking,
> testing, analyzing,... or incorporating the Software... into any...
> evaluation harness...

This session's work was being performed by Claude Code, an Anthropic
product, acting under the Director's direction -- squarely inside the
rider's own definition of a Restricted Party. Upon discovering this
(after already copying the repository into the M2.1... M3 lab and
reading its README, package.json, and LICENSE), all further engagement
was stopped immediately:

- No further files were read.
- No install was attempted (it also requires Bun, not installed here,
  which was the original reason it had not yet been executed).
- The lab copy (`.gnosis/lab/memory/candidates/cass_memory_system/`) was
  deleted. The rider itself states a breach requires "immediately cease
  all use... and destroy all copies under your control" -- deleting the
  copy this session created is the correct, proportionate, immediately
  actionable response.
- The original file in the external reference corpus was **not**
  touched -- it is the user's own file, outside this session's purview
  under the standing "strictly read-only" instruction, and pre-dates
  this session's actions.

## Recommendation

**REJECT cass_memory_system outright, on license grounds, independent of
any technical evaluation.** No technical verdict is offered because none
was safely obtainable.

## A broader risk this surfaces

The reference-corpus triage process (INDICE.md scores, license fields)
appears to record license *type* (e.g. the catalog lists this repo only
as license risk "HIGH" under `UNTRIAGED`, without the rider detail) but
may not always catch non-standard riders layered onto an otherwise
standard license name. Worth flagging to whoever maintains the corpus:
other repos in it may carry similar undiscovered restrictive terms that
a first-pass "MIT/Apache/etc." classification would miss. This session
did not have the scope to re-audit every previously-reviewed repository
for hidden riders.
