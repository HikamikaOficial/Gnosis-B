"""Validate the supported native Windows Codex distribution before deployment."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CodexPackageError(ValueError):
    """The provider distribution is incomplete or unsupported."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CodexPackageError("duplicate provider package field")
        result[key] = value
    return result


def codex_package_entrypoint(root: Path) -> Path:
    """Return the executable in a complete layout-v1 x64 Windows package.

    Preserve the vendor directory structure, including sandbox and search
    helpers. The returned path alone is not deployment identity evidence;
    callers must still measure and bind the complete protected runtime tree.
    """
    root = Path(root)
    if not root.is_dir() or root.is_symlink() or root.is_junction():
        raise CodexPackageError("provider package must be an ordinary directory")
    for item in root.rglob("*"):
        if item.is_symlink() or item.is_junction():
            raise CodexPackageError("provider package contains a linked path")
    descriptor = root / "codex-package.json"
    try:
        with descriptor.open("rb") as stream:
            raw = stream.read(4097)
        if len(raw) > 4096:
            raise CodexPackageError("provider package descriptor exceeds bound")
        data = json.loads(raw, object_pairs_hook=_unique_object)
    except (OSError, ValueError, UnicodeError) as exc:
        raise CodexPackageError("invalid provider package descriptor") from exc
    expected = {
        "layoutVersion": 1, "target": "x86_64-pc-windows-msvc",
        "variant": "codex", "entrypoint": "bin/codex.exe",
        "resourcesDir": "codex-resources", "pathDir": "codex-path",
    }
    if (not isinstance(data, dict) or set(data) != {*expected, "version"}
            or type(data.get("layoutVersion")) is not int
            or any(data.get(key) != value for key, value in expected.items())
            or not isinstance(data.get("version"), str) or not data["version"]):
        raise CodexPackageError("unsupported provider package layout")
    for relative in (
        "bin/codex.exe", "bin/codex-code-mode-host.exe", "codex-path/rg.exe",
        "codex-resources/codex-command-runner.exe",
        "codex-resources/codex-windows-sandbox-setup.exe",
    ):
        path = root / relative
        if not path.is_file() or path.stat().st_size == 0:
            raise CodexPackageError(f"provider package lacks required file: {relative}")
    return root / "bin" / "codex.exe"
