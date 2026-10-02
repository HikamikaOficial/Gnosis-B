"""Verify an already-produced evidence bundle. Nothing else.

WHY THIS IS ITS OWN MODULE, AND IN THE TRUST PLANE.

The publisher's whole job at verification time is to answer one question: are
these bytes exactly the bytes the trusted record names? Answering it needs a
manifest reader, a hash and a directory walk. It does NOT need the machinery
that PRODUCED the bundle.

Before this module, the default verifier reached into
`gnosis.kernel.evidence_capture`, and importing that pulled in git evidence
collection, the input lock and the write observer - roughly 3400 lines of code
that can run tools, take locks and watch the filesystem - into the closure of a
service whose entire remit is to compare hashes. A publisher that can execute
Git is a publisher that can be made to execute Git.

So the verification primitives live HERE, in the trust plane, and
`evidence_capture` imports them rather than the other way round. There is still
exactly ONE implementation - moving it, not copying it, is the point: two
verifiers that must agree are a defect waiting for the day they do not.

Dependencies, deliberately: json, dataclasses, pathlib, and the ONE canonical
hash primitive (ADR-0004). No I/O beyond reading the bundle it is asked about.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gnosis.kernel.canonical import hash_canonical, sha256_hex

BUNDLE_MANIFEST = "MANIFEST.sha256.json"


def write_bundle_manifest(staging: Path) -> Path:
    """Hash every file in the bundle, then hash that map into one digest.

    Written after everything else, so SUMMARY.json and every artifact are
    covered. It cannot hash itself, so it names itself as the one unlisted
    file and says so — the rule the review-package manifest already follows.
    `bundle_digest` is the root a reviewer records out of band or reads off
    the git commit that carries the bundle; editing any listed file changes
    it, and editing the manifest to match is what a signature would prevent,
    which is the declared limitation, not a hidden one.
    """
    files: dict[str, str] = {}
    for item in sorted(staging.rglob("*")):
        if item.is_file() and item.name != BUNDLE_MANIFEST:
            files[item.relative_to(staging).as_posix()] = sha256_hex(item.read_bytes())
    bundle_digest = hash_canonical(sorted(files.items()))
    path = staging / BUNDLE_MANIFEST
    path.write_text(json.dumps({
        "note": (
            "SHA-256 of every file in this bundle. bundle_digest is one hash "
            "over the whole map. Re-derive it with verify_bundle(): any file "
            "added, removed or changed after capture is detected. The manifest "
            "cannot hash itself, so it is the one file not listed; a "
            "cryptographic signature over bundle_digest — which would also stop "
            "an editor from recomputing this manifest — needs key management "
            "that is out of scope and is a declared limitation, not a claim."
        ),
        "unlisted": BUNDLE_MANIFEST,
        "bundle_digest": bundle_digest,
        "files": files,
    }, indent=2, sort_keys=True), encoding="utf-8")
    return path


@dataclass(frozen=True)
class BundleVerification:
    """Whether a bundle is byte-for-byte what its manifest recorded."""

    verified: bool
    bundle_digest: str | None
    problems: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "bundle_digest": self.bundle_digest,
            "problems": list(self.problems),
        }


def verify_bundle(bundle: Path,
                  expected_digest: str | None = None) -> BundleVerification:
    """Re-derive the manifest and report any file added, removed or changed.

    Fail-closed: a missing or unparseable manifest, a recomputed
    `bundle_digest` that disagrees with the recorded one, or any file that
    is present-but-unlisted, listed-but-absent, or hashed differently, all
    make `verified` false. Only an exact match verifies.

    `expected_digest` is the external root of trust (BLOCKER 2). The
    manifest's own `bundle_digest` lives inside the bundle it protects, so
    on its own it proves self-consistency, not tamper-evidence: an editor
    who rewrites a file can recompute the manifest to match. Passing a
    `bundle_digest` recorded OUTSIDE the bundle — the value committed in
    ADR-0027, or read off the git commit that carries the bundle — turns
    this into a tamper-evidence check: a recomputed manifest whose digest
    no longer equals the external anchor is caught here. Authenticity (who
    produced it, unforgeably) still needs a signature, which is out of
    scope; this raises self-consistency to tamper-evidence against an
    external anchor, no further.

    STAGE 6: the publisher NEVER passes a worker-supplied `expected_digest`.
    The value comes from the trusted record, or from nothing at all.
    """
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
        # The external anchor disagrees: the bundle is internally consistent
        # but is not the bundle the trusted record names.
        problems.append(
            f"bundle_digest {recomputed} does not match the expected "
            f"{expected_digest}")

    return BundleVerification(not problems, manifest.get("bundle_digest"),
                              tuple(problems))
