"""Minimal bundle verification for the P2 trusted publisher TCB.

Extracted VERBATIM (logic-identical) from
`gnosis.kernel.evidence_capture` lines 1225-1330 so the publisher can
re-derive a bundle manifest digest WITHOUT importing the 3444-line capture
machinery (evidence_capture + git_evidence + input_lock + write_observer).
Depends only on hashlib (via canonical) + json + dataclasses + pathlib.
This is the ~40-line TCB slice the P2 design specifies; it is injected into
`publish_anchor(..., verify=verify_bundle)` through the existing seam.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gnosis.kernel.canonical import hash_canonical, sha256_hex

BUNDLE_MANIFEST = "MANIFEST.sha256.json"


def write_bundle_manifest(staging: Path) -> Path:
    files: dict[str, str] = {}
    for item in sorted(staging.rglob("*")):
        if item.is_file() and item.name != BUNDLE_MANIFEST:
            files[item.relative_to(staging).as_posix()] = sha256_hex(item.read_bytes())
    bundle_digest = hash_canonical(sorted(files.items()))
    path = staging / BUNDLE_MANIFEST
    path.write_text(json.dumps({
        "unlisted": BUNDLE_MANIFEST,
        "bundle_digest": bundle_digest,
        "files": files,
    }, indent=2, sort_keys=True), encoding="utf-8")
    return path


@dataclass(frozen=True)
class BundleVerification:
    verified: bool
    bundle_digest: str | None
    problems: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"verified": self.verified, "bundle_digest": self.bundle_digest,
                "problems": list(self.problems)}


def verify_bundle(bundle: Path, expected_digest: str | None = None) -> BundleVerification:
    manifest_path = bundle / BUNDLE_MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return BundleVerification(False, None, (f"manifest unreadable: {exc}",))
    recorded = manifest.get("files")
    if not isinstance(recorded, dict):
        return BundleVerification(False, None, ("manifest has no files map",))

    problems: list[str] = []
    on_disk = {
        item.relative_to(bundle).as_posix()
        for item in bundle.rglob("*")
        if item.is_file() and item.name != BUNDLE_MANIFEST
    }
    for rel in sorted(on_disk - set(recorded)):
        problems.append(f"present but unlisted: {rel}")
    for rel in sorted(set(recorded) - on_disk):
        problems.append(f"listed but absent: {rel}")
    for rel in sorted(on_disk & set(recorded)):
        actual = sha256_hex((bundle / rel).read_bytes())
        if actual != recorded[rel]:
            problems.append(f"changed: {rel}")

    recomputed = hash_canonical(sorted(recorded.items()))
    if recomputed != manifest.get("bundle_digest"):
        problems.append("bundle_digest does not match the files map")
    if expected_digest is not None and recomputed != expected_digest:
        problems.append(f"bundle_digest {recomputed} does not match the expected {expected_digest}")

    return BundleVerification(not problems, manifest.get("bundle_digest"), tuple(problems))
