# zmem scorecard (real execution against a deterministic scenario)

Installed via `uv venv` + editable install (zero required dependencies,
installed in under 2 seconds). Real workspace initialized, real SQLite
DB, all commands below actually executed, not simulated.

## Governance model: confirmed real, not marketing

`remember` (human/system authored, goes active immediately) vs `propose`
(quarantined pending review unless human/system authored) is a real,
enforced distinction. `queue`/`promote`/`reject` are real review-lifecycle
commands. Every write carries `source_kind` (human/system/tool/document/
agent/import) -- real provenance, not optional metadata.

## Temporal truth / supersession: PARTIAL, real limitation found

Stored T1 ("Storage backend is SQLite.") then T2 ("Storage backend
migrated to PostgreSQL.") with the same `--label`. Result: **no automatic
lineage or supersession was created** (`"parents": []` on both). A
`search` for "storage backend" returned **both as equally active**, with
no signal about which is current. `zmem` does not appear to have an
implicit "same label supersedes" mechanism reachable from the CLI --
supersession must be driven by the caller explicitly (not found in this
session's CLI surface; may exist via `propose`+relationship metadata not
discovered in the time available).

## Contradiction detection: real, explicitly self-limited

`zmem audit health` has a `contradictory_or_conflicting` finding
category -- ran it against the SQLite-vs-PostgreSQL pair and got **zero
findings**. The tool's own output states the limitation explicitly:
"The audit does not establish whether memory content is factually or
semantically true... deterministic lexical signals only." This is an
honest, documented boundary, not a bug: zmem provides the governance
scaffolding (quarantine, audit categories, review queue) but does not
itself perform semantic contradiction detection.

## Revocation: excellent, real, verified end-to-end

1. `inject --agent test-agent "What is the storage backend?"` before
   revocation retrieved and injected **both** contradictory memories
   (real cryptographic Merkle-proof receipt: proof root, per-memory leaf
   hashes/paths, `action_id`).
2. `revoke mem_958128795aba468b --reason "..."` revoked the stale SQLite
   memory.
3. A fresh `inject` for the same task now retrieves **only** the
   PostgreSQL memory (1 of 1) -- revocation is respected going forward.
4. `zmem why <original_action_id> --summary-only` on the **original,
   pre-revocation** action still shows the SQLite memory as one that
   "shaped the action," now labeled `[semantic/revoked]` -- **downstream
   influence of a since-revoked memory on a past decision is fully
   traceable**, which is exactly the Director's revocation test.
5. Default `search` (no `--include-quarantined`) also correctly excludes
   the revoked memory afterward.

## Provenance and receipts

Every write and every `inject` produces a verifiable artifact (content
hash, Merkle proof root, per-item leaf hash/path). This is real,
inspectable cryptographic evidence, not a marketing claim.

## Operational notes

- Zero required Python dependencies; installs and runs in seconds.
- Registers a workspace globally at `~/.zmem/workspaces.json` in
  addition to the project-local `.zerker/` directory -- a small
  home-directory footprint, smaller than sverklo's ~90MB model cache.
- MIT license.

## Verdict for this candidate

Real, working, well-evidenced **governance** layer exactly as the
catalog described it ("separates remembering from being authorized to
use a memory"). Does not on its own solve temporal truth or semantic
contradiction detection -- those remain open problems for whatever sits
in the factual/temporal role, or for the caller's own reasoning.
