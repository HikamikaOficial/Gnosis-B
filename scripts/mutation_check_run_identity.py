"""Prove the F-17 Stage-3 publish-authorization suite catches what it claims.

Each mutant restores a real way for `knowing a run_id` to become enough to
produce ANCHORED: a gate removed, an identity component dropped from the
comparison, a monotonic state allowed to regress, an immutable field made
writable, a V1 record admitted where a deployment binding is required, a run_id
allowed to be rebound, or the authorization taking its answer from the caller
instead of from the trusted store. The targeted suite must go red for each.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/mutation_check_run_identity.py [--out PATH]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNID = "src/gnosis/trust/run_identity.py"
ANCHOR = "src/gnosis/trust/anchor.py"
SUITE = ["tests/test_run_identity_authorization.py", "tests/test_authority_boundary.py",
         "tests/test_trust_boundary.py"]


@dataclass(frozen=True)
class Mutant:
    name: str
    description: str
    edits: list[tuple[str, str, str]] = field(default_factory=list)


# The multi-line targets live as named constants: a mutant's anchor text has to
# match the source EXACTLY, and naming them keeps that text readable instead of
# buried in a nested literal.
_SID_CHECK = (
    "        if not isinstance(self.owner_worker_sid, str) or not _SID_PATTERN.match(\n"
    "                self.owner_worker_sid):"
)
_ANCHOR_DIGEST_CHECK = (
    "            if not isinstance(self.anchor_record_digest, str) or not _DIGEST.match(\n"
    "                    self.anchor_record_digest):"
)
_SAFE_RUN_ID_CHECK = (
    "    return (isinstance(run_id, str) and bool(_SAFE_RUN_ID.match(run_id))\n"
    '            and ".." not in run_id)'
)
_HEAD_TREE_COMPARISON = (
    '        (request.expected_head_sha, identity.head_sha, "head_sha"),\n'
    '        (request.expected_tree_identity, identity.tree_identity, "tree_identity"),'
)
_OWNER_COMPARISON = (
    '        (request.expected_owner_worker_sid, identity.owner_worker_sid, "owner_worker_sid"),'
)
_DEPLOYMENT_COMPARISON = (
    '        (request.expected_deployment_digest, identity.deployment_digest, "deployment_digest"),'
)
# Stage 4 moved the single parse into `parse_record_line`, so this mutant now
# anchors on the LOOP that calls it. The mutation itself is unchanged in intent:
# an unreadable ledger line is skipped instead of failing closed.
_LEDGER_FAIL_CLOSED = (
    '            out.append(parse_record_line(line, where=f"anchor ledger line {number}"))'
)
_LEDGER_SKIPPED = (
    "            try:\n"
    '                out.append(parse_record_line(line, where=f"line {number}"))\n'
    "            except AuthorityUnavailable:\n"
    "                continue"
)
_V2_DEPLOYMENT_REQUIRED = (
    '            _require_digest(self.deployment_digest, "a V2 anchor\'s deployment_digest")'
)


MUTANTS: list[Mutant] = [
    Mutant("RM1", "the PUBLISHABLE gate is removed, so any known run may be anchored",
           [(RUNID, "    if record.publication_state is not PublicationState.PUBLISHABLE:",
             "    if False:")]),
    Mutant("RM2", "the owner_worker_sid check is dropped, so another worker's run publishes",
           [(RUNID, _OWNER_COMPARISON, "")]),
    Mutant("RM3", "the deployment check is dropped, so evidence from another trust plane publishes",
           [(RUNID, _DEPLOYMENT_COMPARISON, "")]),
    Mutant("RM4", "the epoch check is dropped, so an older generation's artifact publishes",
           [(RUNID, "    if request.expected_epoch != identity.epoch:", "    if False:")]),
    Mutant("RM5", "the head/tree binding is dropped from the authorization comparison",
           [(RUNID, _HEAD_TREE_COMPARISON, "")]),
    Mutant("RM6", "publication state may regress (ANCHORED back to PUBLISHABLE)",
           [(RUNID, "            if target not in allowed:", "            if False:")]),
    Mutant("RM7", "a transition stops requiring the expected identity, so a stale/ABA update lands",
           [(RUNID, "            if current.identity_digest != expected_identity_digest:",
             "            if False:")]),
    Mutant("RM8", "a run_id may be rebound to a different identity (delete-and-recreate)",
           [(RUNID, "                if existing.identity_digest != identity.digest():",
             "                if False:")]),
    Mutant("RM9", "ANCHORED no longer requires a confirmed AnchorRecord digest",
           [(RUNID, _ANCHOR_DIGEST_CHECK, "            if False:")]),
    Mutant("RM10", "an unsafe run_id is accepted as a trusted-store record name",
           [(RUNID, _SAFE_RUN_ID_CHECK,
             "    return isinstance(run_id, str) and bool(run_id)")]),
    Mutant("RM11", "a V2 anchor is accepted without a deployment binding",
           [(ANCHOR, _V2_DEPLOYMENT_REQUIRED, "            pass")]),
    Mutant("RM12", "a V1 record may carry V2 fields, so an unbound anchor masquerades as bound",
           [(ANCHOR,
             "        elif self.deployment_digest is not None or self.run_identity_digest is not None:",
             "        elif False:")]),
    Mutant("RM13", "a V1 record satisfies a deployment-bound verification",
           [(ANCHOR, "        if not record.is_deployment_bound:", "        if False:")]),
    Mutant("RM14", "the anchor stops binding the deployment recorded in the run identity",
           [(ANCHOR, "        deployment_digest=identity.deployment_digest,",
             '        deployment_digest="0" * 64,')]),
    Mutant("RM15", "publish adopts the bundle's tree identity again instead of the Director's",
           [(ANCHOR, "    if bundle_tree != identity.tree_identity:", "    if False:")]),
    Mutant("RM16", "owner_worker_sid accepts a username instead of a canonical SID",
           [(ANCHOR, _SID_CHECK, "        if False:")]),
    Mutant("RM17", "an unreadable anchor ledger line is skipped instead of failing closed",
           [(ANCHOR, _LEDGER_FAIL_CLOSED, _LEDGER_SKIPPED)]),
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

    say("MUTATION CHECK — F-17 Stage 3 trusted RunIdentity + publish authorization")
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
                (REPO / rel).write_text(src.replace(old, new, 1), encoding="utf-8", newline="")
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
