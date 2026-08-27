"""Prove the F-17 Stage-4 durable-publication suite catches what it claims.

Each mutant restores a real way for the crash window to reopen: an ANCHORED
answer that outruns its commit, a commit point that stops binding the record it
commits, a recovery that promotes a crashed attempt to committed history or
discards committed history as a crashed attempt, a malformed commit statement
read as "nothing is committed", a retry that anchors twice, a binding dropped
from recovery, a durable flush removed, the publication lock removed. The
targeted suite must go red for each.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/mutation_check_publication.py [--out PATH]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PUB = "src/gnosis/trust/publication.py"
ANCHOR = "src/gnosis/trust/anchor.py"
ATOMIC = "src/gnosis/kernel/atomic_io.py"
SUITE = ["tests/test_durable_publication.py", "tests/test_authority_boundary.py",
         "tests/test_run_identity_authorization.py", "tests/test_trust_boundary.py",
         "tests/test_atomic_io.py"]


@dataclass(frozen=True)
class Mutant:
    name: str
    description: str
    edits: list[tuple[str, str, str]] = field(default_factory=list)


# Multi-line targets live as named constants: a mutant's anchor text has to
# match the source EXACTLY, and naming them keeps that text readable.
_LEDGER_FLUSH = (
    "            fh.flush()\n"
    "            os.fsync(fh.fileno())"
)
_WATERMARK_FLUSH = (
    "        fh.write(data)\n"
    "        fh.flush()\n"
    "        os.fsync(fh.fileno())"
)
_GENESIS_CONSISTENCY = (
    "        if (self.committed_seq < 0) != (digest == GENESIS_HASH):"
)
_WATERMARK_BINDS_THE_RECORD = (
    "    head_digest = committed[-1].digest()\n"
    "    if head_digest != watermark.committed_record_digest:"
)
_CASE_C = (
    "        elif state is PublicationState.PUBLISHABLE:\n"
    "            # CASE C. The commit happened; only the consequence is missing.\n"
    "            run_store.mark_anchored(record.run_id, identity.digest(), record.digest())\n"
    "            after = run_store.read(record.run_id)\n"
    "            if (after.publication_state is not PublicationState.ANCHORED\n"
    "                    or after.anchor_record_digest != record.digest()):\n"
    "                raise PublicationCorrupt(\n"
    '                    f"the reconciled ANCHORED state for run {record.run_id} did not "\n'
    '                    "read back as written")\n'
    "            reconciled.append(record.run_id)"
)
_ALREADY_ANCHORED_RESOLUTION = (
    "        for record in split.committed:\n"
    "            if record.digest() == trusted.anchor_record_digest:\n"
    "                return PublicationResult(PublishOutcome.ALREADY_ANCHORED, record,\n"
    "                                         watermark, report)"
)
_TAKE_THE_LOCK = (
    "    with FileLock(lock_path_for(store.ledger)):\n"
    "        return _publish_locked(store, run_store, request, bundle_dir,\n"
    "                               verify=verify,\n"
    "                               repair_uncommitted_tail=repair_uncommitted_tail)"
)
_NO_LOCK = (
    "    return _publish_locked(store, run_store, request, bundle_dir,\n"
    "                           verify=verify,\n"
    "                           repair_uncommitted_tail=repair_uncommitted_tail)"
)
_MALFORMED_WATERMARK_FAILS_CLOSED = (
    "    except (UnicodeDecodeError, json.JSONDecodeError) as exc:\n"
    "        raise PublicationCorrupt("
)
_MARK_ANCHORED_EARLY = (
    "    _assert_watermark_advances(watermark, new_watermark)"
)


MUTANTS: list[Mutant] = [
    Mutant("SM1", "the protocol answers ANCHORED before the watermark is committed",
           [(PUB, '    _fault("F5", root=store.root, watermark=new_watermark)',
             ("    return PublicationResult(PublishOutcome.ANCHORED, record, "
              "new_watermark, report)"))]),
    Mutant("SM2", "RunIdentity is marked ANCHORED before the durable watermark commit",
           [(PUB, _MARK_ANCHORED_EARLY,
             "    run_store.mark_anchored(identity.run_id, identity.digest(), "
             "record.digest())\n" + _MARK_ANCHORED_EARLY)]),
    Mutant("SM3", "the ledger append is not flushed to the storage stack",
           [(ANCHOR, _LEDGER_FLUSH, "            pass")]),
    Mutant("SM4", "the ledger is not re-verified from disk before the watermark advances",
           [(PUB, "    prospective = split_ledger(store.ledger, new_watermark)",
             "    prospective = LedgerSplit((), 0, 0, 0, b'')")]),
    Mutant("SM5", "the watermark binds only the sequence, not the record it commits",
           [(PUB, _WATERMARK_BINDS_THE_RECORD,
             "    head_digest = committed[-1].digest()\n    if False:")]),
    Mutant("SM6", "recovery treats any tail beyond the watermark as committed history",
           [(PUB, "    if watermark.commits_nothing:",
             "    if False:")]),
    Mutant("SM7", "recovery may cut the ledger inside the committed prefix",
           [(PUB, "        atomic_write_bytes(store.ledger, split.raw[: split.committed_end_offset])",
             "        atomic_write_bytes(store.ledger, b'')")]),
    Mutant("SM8", "a malformed watermark is read as 'nothing is committed'",
           [(PUB, _MALFORMED_WATERMARK_FAILS_CLOSED,
             ("    except (UnicodeDecodeError, json.JSONDecodeError) as exc:\n"
              "        return GENESIS_WATERMARK\n"
              "        raise PublicationCorrupt("))]),
    Mutant("SM9", "a retry appends a second anchor instead of answering ALREADY_ANCHORED",
           [(PUB, "    if decision.verdict is PublicationVerdict.ALREADY_ANCHORED:",
             "    if False:")]),
    Mutant("SM10", "recovery ignores which deployment a committed anchor is bound to",
           [(PUB, "        if identity.deployment_digest != expected_deployment_digest:",
             "        if False:")]),
    Mutant("SM11", "recovery stops checking the record against the run identity",
           [(PUB, "        _assert_record_matches_identity(record, identity)", "        pass")]),
    Mutant("SM12", "the trusted publication lock is dropped",
           [(PUB, _TAKE_THE_LOCK, _NO_LOCK)]),
    Mutant("SM13", "an ANCHORED state is trusted without a confirming watermark",
           [(PUB, "        if trusted.anchor_record_digest not in committed_digests:",
             "        if False:")]),
    Mutant("SM14", "the watermark may jump instead of advancing by exactly one record",
           [(PUB, "    if new.committed_seq != expected:", "    if False:")]),
    Mutant("SM15", "several uncommitted records are discarded on a guess",
           [(PUB, "    if split.tail_complete_records > 1:", "    if False:")]),
    Mutant("SM16", "a ledger that already holds records is given a genesis watermark",
           [(PUB, "    if raw.strip():", "    if False:")]),
    Mutant("SM17", "recovery skips case C, so a committed run is published a second time",
           [(PUB, _CASE_C,
             ("        elif state is PublicationState.PUBLISHABLE:\n"
              "            reconciled.append(record.run_id)"))]),
    Mutant("SM18", "the watermark's temp file is not flushed to the storage stack",
           [(ATOMIC, _WATERMARK_FLUSH, "        fh.write(data)")]),
    Mutant("SM19", "a watermark may commit nothing and name a record at the same time",
           [(PUB, _GENESIS_CONSISTENCY, "        if False:")]),
    Mutant("SM20", "ALREADY_ANCHORED is answered without resolving the committed record",
           [(PUB, _ALREADY_ANCHORED_RESOLUTION,
             ("        return PublicationResult(PublishOutcome.ALREADY_ANCHORED,\n"
              "                                 split.committed[-1], watermark, "
              "report)"))]),
    Mutant("SM21", "an uncommitted tail is appended onto instead of failing closed",
           [(PUB, "    if report.has_uncommitted_tail and not report.tail_discarded:",
             "    if False:")]),
]


def _pytest() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, "-m", "pytest", *SUITE, "-q", "-x"],
                          cwd=REPO, capture_output=True, text=True, check=False)
    tail = (proc.stdout.strip().splitlines() or [""])[-1][:200]
    return proc.returncode, tail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    lines: list[str] = []

    def say(t: str = "") -> None:
        print(t, flush=True)
        lines.append(t)

    say("MUTATION CHECK — F-17 Stage 4 durable publication + crash recovery")
    say("=" * 74)
    say(f"targeted suite: {' '.join(SUITE)}")
    say("")
    originals = {rel: (REPO / rel).read_text(encoding="utf-8")
                 for rel in {e[0] for m in MUTANTS for e in m.edits}}
    code, tail = _pytest()
    say(f"BASELINE (repair in place): exit={code}  {tail}")
    if code != 0:
        say("ABORTED: baseline not green.")
        if args.out:
            args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1
    say("")
    survived: list[str] = []
    try:
        for m in MUTANTS:
            applied = True
            for rel, old, new in m.edits:
                src = (REPO / rel).read_text(encoding="utf-8")
                if old not in src:
                    applied = False
                    break
                (REPO / rel).write_text(src.replace(old, new, 1), encoding="utf-8",
                                        newline="")
            if not applied:
                survived.append(f"{m.name} (NOT APPLIED)")
                say(f"{m.name}: {m.description}\n  verdict: NOT APPLIED")
            else:
                code, tail = _pytest()
                say(f"{m.name}: {m.description}")
                say(f"  result: exit={code}  {tail}")
                say(f"  verdict: {'CAUGHT' if code != 0 else 'SURVIVED'}")
                if code == 0:
                    survived.append(m.name)
            for rel, text in originals.items():
                (REPO / rel).write_text(text, encoding="utf-8", newline="")
            say("")
    finally:
        for rel, text in originals.items():
            (REPO / rel).write_text(text, encoding="utf-8", newline="")
    code, tail = _pytest()
    say(f"RESTORED: exit={code}  {tail}")
    say(f"mutants: {len(MUTANTS)}  survived/aborted: {len(survived)}"
        + (f"  -> {survived}" if survived else ""))
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if survived or code != 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
