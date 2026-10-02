"""The P2 publication protocol.

Reuses the REVIEWED primitives verbatim: gnosis.kernel.authority.publish_anchor
/ AnchorRecord / RunIdentity, and gnosis.kernel.canonical. The only adaptations
the P2 design calls for:
  - AnchorStore is subclassed to SKIP the MIC High relabel at runtime: under P2
    the boundary is the NTFS DACL by the service SID (set at provisioning), and a
    Medium/virtual-account service cannot relabel to High anyway. Every reviewed
    method (records/verify_chain/append/lookup/next_seq_and_prev) is inherited
    unchanged.
  - verify is injected from trust.bundle_verify (no capture machinery).
  - owner authorization: RunIdentity on disk carries owner_worker_sid; the
    publisher requires it to equal the endpoint's configured authorized worker SID.
  - a two-phase committed-watermark makes crash recovery a trusted action, not a
    magic append-only property.
The worker sends only `PUBLISH <run_id>`. Every other fact comes from the trusted
RunIdentity store; the worker never supplies path/digest/HEAD/tree/repo/owner.
"""
from __future__ import annotations

import json
import re
import os
from pathlib import Path

from gnosis.kernel.authority import AnchorStore, RunIdentity, publish_anchor
from trust.bundle_verify import verify_bundle

RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
WATERMARK = "committed.seq"


class ProbeAnchorStore(AnchorStore):
    """AnchorStore whose boundary is the NTFS DACL (provisioned), not runtime MIC."""

    def __init__(self, root: Path) -> None:  # noqa: D401 - see module docstring
        self.root = root
        self.ledger = root / self.LEDGER
        root.mkdir(parents=True, exist_ok=True)


def _watermark_path(store_root: Path) -> Path:
    return store_root / WATERMARK


def read_watermark(store_root: Path) -> int:
    try:
        return int(_watermark_path(store_root).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return -1


def write_watermark(store_root: Path, seq: int) -> None:
    tmp = _watermark_path(store_root).with_suffix(".seq.tmp")
    tmp.write_text(str(seq), encoding="utf-8")
    os.replace(tmp, _watermark_path(store_root))


def recover(store_root: Path, log) -> dict:
    """TRUSTED recovery, run at startup. Truncate any ledger record beyond the
    committed watermark (an append that crashed before confirmation was never
    anchored), then verify the chain. This is an explicit trusted action, NOT an
    inherent property of append-only."""
    store = ProbeAnchorStore(store_root)
    committed = read_watermark(store_root)
    if not store.ledger.exists():
        return {"recovered": False, "committed": committed, "records": 0, "chain_ok": True}
    lines = [ln for ln in store.ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]
    keep = committed + 1
    truncated = 0
    if len(lines) > keep:
        truncated = len(lines) - keep
        store.ledger.write_text(("\n".join(lines[:keep]) + ("\n" if keep else "")),
                                encoding="utf-8")
        log(f"recovery truncated {truncated} unconfirmed record(s) beyond watermark {committed}")
    chain_ok = store.verify_chain()
    return {"recovered": truncated > 0, "committed": committed,
            "records": len(store.records()), "chain_ok": chain_ok}


class Publisher:
    def __init__(self, cfg: dict, log):
        self.state_root = Path(cfg["trust_state_root"])
        self.anchors_root = self.state_root / "anchors"
        self.runid_root = self.state_root / "runidentity"
        self.authorized_worker_sid = cfg["authorized_worker_sid"]
        self.log = log

    def _load_runidentity(self, run_id: str) -> dict | None:
        p = self.runid_root / f"{run_id}.json"
        try:
            return json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None

    def handle(self, request: str, client_pid: int) -> str:
        parts = request.split()
        if len(parts) != 2 or parts[0] != "PUBLISH":
            return "REJECTED:bad-verb"
        run_id = parts[1]
        if not RUN_ID_RE.match(run_id):
            return "REJECTED:bad-run-id"

        rid = self._load_runidentity(run_id)
        if rid is None:
            return "REJECTED:unknown-run"          # fail closed
        # authorization: trusted owner must be the endpoint's authorized worker SID
        if rid.get("owner_worker_sid") != self.authorized_worker_sid:
            self.log(f"owner mismatch run={run_id} owner={rid.get('owner_worker_sid')} "
                     f"authorized={self.authorized_worker_sid}")
            return "REJECTED:owner-mismatch"        # fail closed (cross-run / other worker)

        store = ProbeAnchorStore(self.anchors_root)
        if store.lookup(run_id) is not None:
            return "ALREADY_ANCHORED"               # idempotent, no second append

        # everything below comes from the TRUSTED RunIdentity, never the worker
        identity = RunIdentity(
            task_id=rid["task_id"], run_id=rid["run_id"],
            repository_id=rid["repository_id"], head_sha=rid["head_sha"],
            bundle_path=rid["bundle_path"])
        bundle_dir = Path(rid["bundle_path"])
        try:
            record = publish_anchor(store, identity, bundle_dir, verify=verify_bundle)
        except Exception as exc:
            self.log(f"publish refused run={run_id}: {exc}")
            return f"REJECTED:{type(exc).__name__}"
        # two-phase commit: record is appended + re-read inside publish_anchor;
        # only now mark it committed so a crash before this point is recoverable.
        write_watermark(self.anchors_root, record.seq)
        return f"ANCHORED:{record.bundle_digest[:12]}:seq={record.seq}"
