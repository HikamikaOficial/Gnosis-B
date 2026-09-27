"""Explicit Windows maintenance entry for persistent installation and verification.

No provider call, login or implicit elevation is performed here. Configuration
must already reside in the protected maintenance directory.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any

# Bind maintenance imports to this exact checkout, including under Python -I.
# Never depend on an editable install pointing at a different source snapshot.
_REPOSITORY = Path(__file__).resolve().parents[1]
for _entry in (_REPOSITORY / "src", _REPOSITORY / "scripts"):
    sys.path.insert(0, str(_entry))

from stage2cb import Stage2CBConfig
from stage2cb_ops import WindowsRealOperations
from v1_installation import install_pinned, verify_persistent
from v1_maintenance_security import (
    create_maintenance_directory,
    require_safe_ancestor_acl,
    verify_maintenance_directory,
)

from gnosis.provision.layout import DeploymentLayout
from gnosis.trust.deployment import (
    DesiredDeploymentConfig,
    canonical_security_descriptor,
    observe_deployment,
    read_path_security_descriptor,
)
from gnosis.trust.worker_output import read_worker_output


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate installation configuration key")
        result[key] = value
    return result


def decode_config(raw: bytes) -> Stage2CBConfig:
    if len(raw) > 65536:
        raise ValueError("installation configuration exceeds its byte bound")
    value = json.loads(raw, object_pairs_hook=_unique)
    names = {field.name for field in fields(Stage2CBConfig)}
    if not isinstance(value, dict) or set(value) != names:
        raise ValueError("installation configuration must contain exactly the supported fields")
    layout = value.pop("layout")
    if (not isinstance(layout, dict)
            or set(layout) != {field.name for field in fields(DeploymentLayout)}
            or not all(isinstance(v, str) and v for v in layout.values())
            or not all(isinstance(v, str) and v for v in value.values())):
        raise ValueError("installation fields must be nonempty strings")
    for key in ("source_commit", "source_tree"):
        if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value[key]) is None:
            raise ValueError("installation source identity must be a full Git object ID")
    for path in (layout["code_base"], layout["state_base"], layout["work_base"],
                 value["residue_root"], value["runtime_src"], value["codex_runtime_src"],
                 value["reviewer_binary"], value["git_runtime_src"]):
        if not Path(path).is_absolute():
            raise ValueError("installation paths must be absolute")
    for key, text in (("release_id", layout["release_id"]),
                      ("run_id", value["run_id"]), ("worker_username", value["worker_username"]),
                      ("service_name", value["service_name"])):
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", text) is None:
            raise ValueError(f"invalid installation identifier: {key}")
    config = Stage2CBConfig(layout=DeploymentLayout(**layout), **value)
    config.residue_record_dir()  # Reject a journal beneath an owned deployment root.
    return config


def load_config(path: Path) -> Stage2CBConfig:
    verify_maintenance_directory(path.parent)
    require_safe_ancestor_acl(canonical_security_descriptor(read_path_security_descriptor(path)))
    config = decode_config(read_worker_output(path, limit=65536))
    if Path(config.residue_record_dir()).absolute() != path.parent.absolute():
        raise ValueError("configuration and ownership journal must share the protected directory")
    return config


def observe_installed(config: Stage2CBConfig) -> str:
    layout = config.layout
    return observe_deployment(DesiredDeploymentConfig(
        trust_root=Path(layout.trust_root), runtime_executable=Path(layout.runtime_executable),
        runtime_root=Path(layout.runtime_root), runidentity_store=Path(layout.runidentity_root),
        anchorstore=Path(layout.anchors_root), service_name=config.service_name)).digest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("initialize", "install", "verify"))
    parser.add_argument("path", type=Path, help="maintenance directory (initialize) or config JSON")
    parser.add_argument("--execute", action="store_true", help="explicitly perform maintenance")
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error("maintenance requires --execute")
    ops = WindowsRealOperations(authorized=True)
    if not ops.is_elevated():
        parser.error("maintenance requires an elevated Windows process")
    if args.action == "initialize":
        create_maintenance_directory(args.path, ops)
        print("Protected maintenance directory created.")
        return 0
    config = load_config(args.path)
    if args.action == "install":
        installed = install_pinned(config, ops, observe_effective=lambda: observe_installed(config))
    else:
        installed = verify_persistent(config, observe_effective=lambda: observe_installed(config))
    print(json.dumps({"action": args.action, "operator_entry": str(installed.operator_entry),
                      "status": "deployment verified; provider qualification still required"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
