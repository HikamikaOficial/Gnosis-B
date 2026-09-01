"""Canonical operator-stack deployment (F-33 Stage 2C-PACK-R1).

ONE authoritative deployed `gnosis` package. The F-17 `Provisioner` deploys the
runtime + the trust-plane closure into the canonical package root
(`code_release_base/publisher`, where `gnosis/__init__.py` + `gnosis/trust/` live
and the runtime `python._pth` points). This module deploys the remaining
NON-TRUST operator/application modules (director, the rest of kernel, runner,
adapters, contracts) into that SAME `gnosis/` package — never creating or
modifying anything under `gnosis/trust/`. So the Director, the Publisher service
and the Worker all import ONE authoritative trust tree.

Split (both computed deterministically from the production import closure):
- F-17-PROVIDED = the import closure of the `gnosis.trust.*` modules (trust +
  their non-application deps + package `__init__`s). Supplied to the unmodified
  F-17 `Provisioner` as `publisher_files`; measured by the F-17 deployment digest.
- APPLICATION-PROVIDED = production closure − F-17-provided. Deployed and measured
  here (`operator_entry.py` included), and it may NEVER include a `gnosis/trust/*`
  path (ownership guard).

No OS provisioning here; pure filesystem. `src/gnosis/trust/*` untouched.
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from gnosis.provision.layout import DeploymentLayout

_CLOSURE_ROOTS = ("gnosis.director.cli", "gnosis.director.deterministic_worker")
_TRUST_PREFIX = "gnosis/trust/"
_ENTRY_NAME = "operator_entry.py"


class OperatorStackError(Exception):
    """The operator-stack deployment/verification failed (fail closed)."""


def _module_path(source_root: Path, module: str) -> Path | None:
    p = source_root / (module.replace(".", "/") + ".py")
    if p.is_file():
        return p
    init = source_root / module.replace(".", "/") / "__init__.py"
    return init if init.is_file() else None


def _gnosis_imports(path: Path, module: str) -> set[str]:
    is_package = path.name == "__init__.py"
    package = module if is_package else (
        module.rsplit(".", 1)[0] if "." in module else module)
    out: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                parts = package.split(".")
                if node.level - 1 > 0:
                    parts = parts[: -(node.level - 1)]
                anchor = ".".join(parts)
                absmod = f"{anchor}.{node.module}" if node.module else anchor
                if absmod.startswith("gnosis"):
                    out.add(absmod)
            elif node.module and node.module.startswith("gnosis"):
                out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names if a.name.startswith("gnosis"))
    return out


def _parent_packages(module: str) -> list[str]:
    parts = module.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts))]


def _closure(source_root: Path, roots: tuple[str, ...]) -> dict[str, Path]:
    seen: set[str] = set()
    files: dict[str, Path] = {}
    stack = list(roots)
    while stack:
        module = stack.pop()
        if module in seen:
            continue
        seen.add(module)
        path = _module_path(source_root, module)
        if path is None:
            continue
        files[module] = path
        for parent in _parent_packages(module):
            if parent not in seen:
                stack.append(parent)
        for dep in _gnosis_imports(path, module):
            if dep not in seen:
                stack.append(dep)
    return files


def production_closure(source_root: Path) -> dict[str, Path]:
    """The full deterministic production `gnosis.*` import closure."""
    return _closure(source_root, _CLOSURE_ROOTS)


def f17_provided_closure(source_root: Path) -> dict[str, Path]:
    """The trust-plane sub-closure the F-17 Provisioner deploys (as publisher_files).

    Seeded from the `gnosis.trust.*` modules in the production closure, so it also
    pulls in the package `__init__`s and non-application kernel deps the trust
    package needs to import."""
    prod = production_closure(source_root)
    trust_roots = tuple(m for m in prod if m.startswith("gnosis.trust."))
    return _closure(source_root, trust_roots)


def _rel(source_root: Path, path: Path) -> str:
    return path.relative_to(source_root).as_posix()


def application_modules(source_root: Path) -> dict[str, Path]:
    """Production closure MINUS the F-17-provided trust-plane closure."""
    prod = production_closure(source_root)
    f17 = set(f17_provided_closure(source_root))
    return {m: p for m, p in prod.items() if m not in f17}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


@dataclass(frozen=True)
class ApplicationFile:
    relpath: str
    digest: str


@dataclass(frozen=True)
class ApplicationManifest:
    files: tuple[ApplicationFile, ...]
    tree_digest: str

    def to_dict(self) -> dict[str, object]:
        return {"tree_digest": self.tree_digest,
                "files": [{"relpath": f.relpath, "digest": f.digest} for f in self.files]}


def _tree_digest(files: tuple[ApplicationFile, ...]) -> str:
    canonical = json.dumps([[f.relpath, f.digest] for f in files],
                           separators=(",", ":"))
    return _sha256_bytes(canonical.encode("utf-8"))


def canonical_package_root(layout: DeploymentLayout) -> Path:
    """The ONE authoritative deployed package root (contains `gnosis/`); the same
    root the F-17 Provisioner deploys the trust plane + `python._pth` into."""
    return Path(layout.trust_root)


def operator_entry_content(package_root: Path) -> str:
    """Isolated entry delegating EXACTLY to gnosis.director.cli:main, importing
    only from the canonical package root. MUST be launched `<runtime> -I -B`."""
    return (
        "import sys\n"
        f"_ROOT = r\"{package_root}\"\n"
        "sys.path.insert(0, _ROOT)\n"
        "from gnosis.director.cli import main\n"
        "raise SystemExit(main(sys.argv[1:]))\n")


def build_application_manifest(source_root: Path, package_root: Path
                               ) -> ApplicationManifest:
    """The deterministic APPLICATION manifest: the non-trust modules PLUS the
    measured `operator_entry.py`. Contains no `gnosis/trust/*` path."""
    entries: list[ApplicationFile] = []
    for src in application_modules(source_root).values():
        rel = _rel(source_root, src)
        if rel.startswith(_TRUST_PREFIX):  # ownership guard, defence in depth
            raise OperatorStackError(f"application manifest must not own trust path {rel}")
        entries.append(ApplicationFile(relpath=rel, digest=_sha256(src)))
    entry_digest = _sha256_bytes(operator_entry_content(package_root).encode("utf-8"))
    entries.append(ApplicationFile(relpath=_ENTRY_NAME, digest=entry_digest))
    entries.sort(key=lambda f: f.relpath)
    files = tuple(entries)
    return ApplicationManifest(files=files, tree_digest=_tree_digest(files))


@dataclass(frozen=True)
class DeployedApplication:
    package_root: Path
    entry_path: Path
    worker_image: Path
    manifest: ApplicationManifest


def _assert_inside(root: Path, target: Path) -> None:
    root_r = root.resolve()
    target_r = target.resolve()
    if root_r != target_r and root_r not in target_r.parents:
        raise OperatorStackError(f"target {target} escapes {root}")


def deploy_operator_stack(source_root: Path, package_root: Path) -> DeployedApplication:
    """Deploy the APPLICATION modules into the canonical package root (alongside
    the F-17-owned trust plane), then the measured operator entry.

    Fails closed on: a trust path (ownership guard), an escape, a copy-byte
    mismatch, or an attempt to overwrite an existing F-17-owned file.
    """
    package_root = Path(package_root)
    manifest = build_application_manifest(source_root, package_root)
    for f in manifest.files:
        if f.relpath == _ENTRY_NAME:
            continue
        if f.relpath.startswith(_TRUST_PREFIX):
            raise OperatorStackError(
                f"refusing to deploy into F-17-owned trust path {f.relpath}")
        src = source_root / f.relpath
        if not src.is_file():
            raise OperatorStackError(f"required application module missing: {f.relpath}")
        dest = package_root / f.relpath
        _assert_inside(package_root, dest)
        if dest.exists():
            raise OperatorStackError(
                f"refusing to overwrite existing (F-17-owned) file {f.relpath}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        if _sha256(dest) != f.digest:
            raise OperatorStackError(f"deployed byte mismatch for {f.relpath}")
    entry_path = package_root / _ENTRY_NAME
    # write_bytes (not write_text): the manifest digest is computed over the exact
    # UTF-8 bytes; text-mode newline translation would break byte equality.
    entry_path.write_bytes(operator_entry_content(package_root).encode("utf-8"))
    (package_root / "APPLICATION.json").write_text(
        json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    worker_image = package_root / "gnosis" / "director" / "deterministic_worker.py"
    return DeployedApplication(package_root=package_root, entry_path=entry_path,
                               worker_image=worker_image, manifest=manifest)


def verify_application_tree(package_root: Path,
                            manifest: ApplicationManifest) -> tuple[bool, list[str]]:
    """Re-measure the application-provided files (incl. the entry) against the
    manifest. Trust-plane files are F-17-owned and out of scope here."""
    problems: list[str] = []
    for f in manifest.files:
        dest = package_root / f.relpath
        if not dest.is_file():
            problems.append(f"missing: {f.relpath}")
        elif _sha256(dest) != f.digest:
            problems.append(f"tampered: {f.relpath}")
    return (not problems), problems
