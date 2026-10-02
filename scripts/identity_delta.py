r"""F-33 Stage 2C-B1-R3B — harness-only deployment-identity delta diagnostics.

The OS-real B1 run fails closed at the canonical-launch F-17 re-observation gate
because the freshly re-observed F-17 deployment digest differs from the trusted
recorded digest. R3A proved the two digests come from the SAME observer over the
SAME layout, so the delta is a real change in the observed identity — but the exact
component is unknown because only the mismatch *error string* was captured.

This module records the two AUTHORITATIVE observations (the very objects whose
digests feed the trust gate) and, on a digest mismatch, reports WHICH component(s)
changed and — for trees — the exact added/removed/changed manifest entries, and —
for security descriptors — a safe fingerprint delta.

GATE-PRESERVING AND SIDE-EFFECT-FREE BY CONSTRUCTION:
  * it only reads `identity.to_dict()` / `identity.digest()` (pure serialisation of
    an already-observed identity) — it performs NO filesystem or OS write, so it can
    never itself create the digest delta;
  * it never updates the trusted digest, never moves/relaxes the gate, never decides
    whether to launch;
  * every capture is best-effort: a diagnostic failure is recorded and swallowed so
    it can never prevent the authoritative digest from reaching the gate.

No secrets are present in a deployment identity: it carries paths, sizes, content
SHA-256 digests, canonical security descriptors (SIDs/ACEs), and service config —
never file contents, credentials, tokens, or DPAPI plaintext.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# Every top-level component of TrustPlaneDeploymentIdentity.to_dict(), mapped to the
# classification a change in it implies. Trees ("files") and security descriptors are
# refined at diff time.
_CONTENT_CLASS = {
    "package": "PACKAGE_CONTENT_CHANGED",
    "runtime": "RUNTIME_CONTENT_CHANGED",
    "runtime_tree": "RUNTIME_CONTENT_CHANGED",
    "pipe_policy": "PIPE_POLICY_CHANGED",
}
_STORE_KEYS = ("trust_root", "runidentity_store", "anchorstore")


def _stable_digest(obj: Any) -> str:
    """A diagnostic-only stable digest of a JSON-able component. NEVER a substitute
    for the authoritative F-17 deployment digest."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _sddl_fingerprint(sd: Any) -> dict[str, Any] | None:
    """A safe, per-subcomponent fingerprint of a security descriptor (owner/group/
    DACL/mandatory-label), so a SECURITY-DESCRIPTOR mutation is distinguishable from
    a CONTENT mutation without dumping anything sensitive (there is nothing sensitive
    to dump — SIDs and ACEs only)."""
    if not isinstance(sd, dict):
        return None
    return {
        "owner_sid": sd.get("owner_sid"),
        "group_sid": sd.get("group_sid"),
        "control": sd.get("control"),
        "dacl_present": sd.get("dacl_present"),
        "dacl_fingerprint": _stable_digest(sd.get("aces")),
        "mandatory_label_fingerprint": _stable_digest(sd.get("mandatory_label")),
    }


def _manifest_delta(prov: dict[str, Any], launch: dict[str, Any]) -> dict[str, list[str]]:
    """Added/removed/changed canonical relative paths between two file manifests."""
    p = {f.get("path"): f for f in prov.get("files", [])}
    lch = {f.get("path"): f for f in launch.get("files", [])}
    added = sorted(k for k in lch.keys() - p.keys() if k is not None)
    removed = sorted(k for k in p.keys() - lch.keys() if k is not None)
    changed = sorted(k for k in p.keys() & lch.keys()
                     if k is not None and p[k] != lch[k])
    return {"added": added, "removed": removed, "changed": changed}


def classify_identity_delta(provision: dict[str, Any] | None,
                            launch: dict[str, Any] | None) -> dict[str, Any]:
    """Pure structural diff of two deployment-identity dicts. Surfaces EVERY changed
    top-level component (never stops at the first), the manifest delta for tree
    components, and the SDDL delta for security-descriptor components. Returns a
    classification set drawn from the fixed taxonomy."""
    if provision is None or launch is None:
        return {"status": "DIFF_UNAVAILABLE", "components": {},
                "manifest_delta": {}, "sddl_delta": {},
                "classifications": ["DIFF_UNAVAILABLE"]}

    components: dict[str, str] = {}
    manifest_delta: dict[str, Any] = {}
    sddl_delta: dict[str, Any] = {}
    classifications: set[str] = set()

    for key in sorted(set(provision) | set(launch)):
        pv, lv = provision.get(key), launch.get(key)
        if pv == lv:
            components[key] = "UNCHANGED"
            continue
        components[key] = "CHANGED"
        pv_d = pv if isinstance(pv, dict) else {}
        lv_d = lv if isinstance(lv, dict) else {}

        # (a) content manifest (tree) components
        if "files" in pv_d or "files" in lv_d:
            manifest_delta[key] = _manifest_delta(pv_d, lv_d)
            classifications.add(_CONTENT_CLASS.get(key, "PACKAGE_CONTENT_CHANGED"))

        # (b) path identity (observed absolute path) — stores and service image
        if pv_d.get("path") != lv_d.get("path") and ("path" in pv_d or "path" in lv_d):
            classifications.add("PATH_IDENTITY_CHANGED")

        # (c) security-descriptor components (stores, service)
        if (("security_descriptor" in pv_d or "security_descriptor" in lv_d)
                and pv_d.get("security_descriptor") != lv_d.get("security_descriptor")):
            sddl_delta[key] = {
                "provision": _sddl_fingerprint(pv_d.get("security_descriptor")),
                "launch": _sddl_fingerprint(lv_d.get("security_descriptor")),
                "changed": True}
            classifications.add("SERVICE_SECURITY_CHANGED" if key == "service"
                                else "STORE_SECURITY_CHANGED")

        # (d) remaining scalar/content components with a fixed classification
        if (key in _CONTENT_CLASS and "files" not in pv_d and "files" not in lv_d):
            classifications.add(_CONTENT_CLASS[key])

        # (e) a service change with an unchanged descriptor is a config/account/
        #     image change; the taxonomy's only service bucket is SERVICE_SECURITY_
        #     CHANGED, so a changed service component maps there (sddl_delta presence
        #     distinguishes a true descriptor change from a config change).
        if key == "service" and key not in sddl_delta:
            classifications.add("SERVICE_SECURITY_CHANGED")

    changed = [k for k, v in components.items() if v == "CHANGED"]
    if not changed:
        classifications.add("NO_STRUCTURAL_DELTA_FOUND")
    elif len(changed) > 1:
        classifications.add("MULTIPLE_COMPONENTS_CHANGED")

    return {"status": "OK", "components": components,
            "manifest_delta": manifest_delta, "sddl_delta": sddl_delta,
            "classifications": sorted(classifications)}


class IdentityDeltaRecorder:
    """Captures the two AUTHORITATIVE deployment-identity observations and computes
    their component-level delta. Pure/read-only: it serialises identities already
    observed by the gate path and holds the result in memory. Never writes to disk,
    never touches the trusted digest, never blocks the gate."""

    def __init__(self) -> None:
        self.provision: dict[str, Any] | None = None
        self.launch: dict[str, Any] | None = None
        self.notes: list[str] = []

    def _snap(self, obj: Any, which: str) -> dict[str, Any] | None:
        try:
            return {"digest": obj.digest(), "identity": obj.to_dict()}
        except Exception as exc:                     # noqa: BLE001  best-effort only
            self.notes.append(f"{which} snapshot failed: {exc!r}")
            return None

    def record_provision(self, observed: Any) -> None:
        """Snapshot the F-17 InstallResult.observed — the SAME object whose digest
        became the trusted record's f17_deployment_digest."""
        self.provision = self._snap(observed, "provision")

    def record_launch(self, identity: Any) -> None:
        """Snapshot the fresh canonical-launch observation — the SAME identity object
        whose .digest() is returned to the trust gate."""
        self.launch = self._snap(identity, "launch")

    def result(self) -> dict[str, Any]:
        prov_id = self.provision["identity"] if self.provision else None
        launch_id = self.launch["identity"] if self.launch else None
        prov_dig = self.provision["digest"] if self.provision else None
        launch_dig = self.launch["digest"] if self.launch else None
        return {
            "provision_digest": prov_dig,
            "launch_digest": launch_dig,
            "digests_match": bool(prov_dig is not None and prov_dig == launch_dig),
            "component_digests": {
                "provision": {k: _stable_digest(v) for k, v in (prov_id or {}).items()},
                "launch": {k: _stable_digest(v) for k, v in (launch_id or {}).items()},
            },
            "delta": classify_identity_delta(prov_id, launch_id),
            "notes": self.notes,
        }
