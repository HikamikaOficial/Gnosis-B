# F-17 Stage 4 (durable publication + crash recovery) evidence

Stage 3 CLOSED at `b3c0feb`; Stage 4 implementation tree at HEAD `8b58509`.

The window this closes: `PUBLISHABLE` → anchor written → **CRASH** → `RunIdentity`
not yet `ANCHORED`, with nothing on disk able to say whether that anchor was
authoritatively published or was the debris of an attempt.

**One authoritative commit point.** The mistake refused here is modelling *the
anchor line is on disk* and *the state says ANCHORED* as two independent
decisions; two independent decisions are two sources of truth, and after a crash
they disagree with nothing to arbitrate between them. There is exactly one commit:
the **durable, re-read, ledger-verified committed watermark**. The ledger holds
candidates and a record's presence proves nothing; the watermark says which record
is committed; `PublicationState.ANCHORED` is the **consequence** of that commit and
never a second authority. Recovery may *complete* it from the watermark alone;
recovery may never *manufacture* it. An `ANCHORED` state with no commit behind it
is corruption that fails closed — never repaired by fabricating the anchor that
would make it true.

**A genesis watermark, because an absence cannot be trusted.** This is the largest
design change relative to the review's sketch and the one to look at hardest. A
crash during the *first* publication leaves a record — or half of one — in a ledger
with no watermark; so does a pre-Stage-4 ledger whose records may be perfectly
committed history. Reading "no file" as "nothing is committed" would repair the
first and silently **demote** the second. Writing `committed_seq = -1` /
`GENESIS_HASH` before anything can be appended removes the ambiguity at its source:
from then on the absence of a watermark means only "this store is not under the
durable protocol", and that is refused. A watermark is **never** inferred from the
ledger's last record.

**What the watermark carries, and what it deliberately does not.** `schema`,
`committed_seq`, `committed_record_digest` — nothing else. The record digest already
binds the chain position, the deployment, the exact authorized run identity (owner
SID and epoch inside it), the run_id and the bundle digest, with no way for the two
to drift apart. Chain hash, `run_identity_digest`, `deployment_digest` and `run_id`
were each **evaluated and rejected as duplicates**: a copy could detect nothing the
digest does not, and Stage 3's RM13 already cost the project one check that read as
load-bearing while the real refusal came from elsewhere.

**Tail truncation is deliberately narrow.** The protocol truncates *before* it
appends, so at any instant at most one uncommitted record **or** one partial line
can exist, never both. Anything richer did not come from this protocol and is
corruption, not debris. Committed history is never cut.

**Real process crashes, not simulations.** F0–F9 kill a real child with `os._exit`
— no cleanup, no `atexit`, no buffer flush. F0/F2 leave nothing on disk, F1 a
genuinely partial line, F3–F6 a **durable but uncommitted** record, F7–F9 a
committed one. Every point recovers to exactly one record, a verifying chain and
`ANCHORED` against that record. **No point produced a FALSE ANCHORED.** F5/F6 share
a locus and are modelled by the filesystem state a crash there leaves, rather than
by adding a test seam to a kernel primitive the worker plane also uses — stated
plainly rather than overclaimed.

**Guarantee scope, stated honestly.** Process crash and service crash
**GUARANTEED**; power loss and storage failure **BEST EFFORT, EXPLICITLY BOUNDED**.
Data is fsynced (FlushFileBuffers) before each commit step and the watermark is
replaced atomically, but Windows exposes no directory fsync and a journalled rename
is not a proof. Nothing here is power-loss proof and nothing claims to be. The
machine was never powered off, and no simulation is presented as equivalent.
`FileLock` is trusted-writer coordination, **not** a security boundary against a
worker; the ACL/SID boundary is Stage 6/8.

**Four mutants survived the first run and the tests changed because of them.**
Three were real coverage gaps — a retry answered from the ledger head (right only
by coincidence, because every retry test retried the most recent run), an
unrepaired tail never exercised because the default repairs, and a watermark flush
whose assertion was satisfied by the trusted state file's flush instead. The
fourth, the watermark-advance guard, is genuinely unreachable through the protocol;
rather than delete a defence-in-depth guard or invent a scenario nobody can build,
its contract is pinned by a direct test that says so in the test itself. After
repair: 21/21 caught, 0 survivors.

**Reused rather than invented**, after inspecting what exists: `atomic_io`,
`file_lock` and `hash_canonical`, plus `build_anchor_record` split out of
`publish_anchor` so the Stage-3 and Stage-4 protocols share ONE definition of what
an anchor record is. The single extension is `atomic_write_bytes`, because the
watermark and the ledger prefix are exact byte sequences a text-mode writer would
rewrite; `atomic_write_text`'s on-disk bytes are untouched and both share one
replace-retry helper.

**No production wiring.** No launcher, no worker account, no DPAPI, no service, no
named pipe, no ACL, no provisioning, no engine/runner change, no unknown-`.git`.
Nothing persistent was installed; every store is a temporary directory.

Directed 72 passed / 28 subtests; fresh checkout of `8b58509` 161 passed; Stage-4
mutation **21/21 CAUGHT (0 survived)**, Stage-3 re-run 17/17, authority 13/13;
**full suite 1290 passed / 101 subtests, GREEN**; mypy strict clean over 65 source
files; ruff clean on every new and changed file; negative control and secret scan
(0 findings) captured.

TCB: +1 allowlist entry (`gnosis.trust.publication`, 834 LOC) by explicit diff;
`kernel.atomic_io` 37 → 82 LOC inside its existing grant. `trust.deployment`
(1052 LOC) is **still not** in the publisher's closure. No third-party code, no
worker/engine module, no dynamic loading.

F-14 remains **CLOSED**; the historical flaky event stays an evidence note.
Stage 5 NOT started. F-17 stays **OPEN**. See `STAGE4-RESULTS.txt`.
