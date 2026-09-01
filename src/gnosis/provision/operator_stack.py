"""Canonical operator-stack deployment (F-33 Stage 2C-PACK).

The F-17 `Provisioner` deploys the trusted runtime + trust-plane package. It does
NOT deploy the Gnosis-B operator/application stack that `gnosis.director.cli:main`
and the deterministic Worker image require. This module adds that layer WITHOUT
touching the historical F-17 provisioner: it deploys the exact production import
closure of the operator stack into the existing `DeploymentLayout`
(`code_release_base/app`), so a deployed `gnosis run` resolves all production
`gnosis.*` modules from its own measured tree — never the developer checkout.

Properties:
- The deployed set is the DETERMINISTIC production import closure starting at
  `gnosis.director.cli` and `gnosis.director.deterministic_worker` — production
  modules only. Tests, docs, `.git`, `.venv`, scripts, the replay runner and other
  non-production surfaces are excluded by construction (they are not imported).
- Every file is measured (sha256) and the tree gets one canonical digest;
  source==deployed is verifiable and a one-byte tamper is detectable.
- Deployment is atomic (stage → measure → activate); a missing module, a traversal
  attempt, or a partial copy fails closed and leaves no valid `app` root.
- No OS provisioning here; pure filesystem. `src/gnosis/trust/*` untouched.
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from gnosis.provision.layout import DeploymentLayout

# The production entry closure is rooted here; nothing else seeds the manifest.
_CLOSURE_ROOTS = ("gnosis.director.cli", "gnosis.director.deterministic_worker")
_APP_SUBDIR = "app"
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
    """All `gnosis.*` modules imported by `module`, resolving RELATIVE imports
    (`from ..kernel.x import y`) to their absolute names — most of the code base
    imports this way, so missing them would deploy an incomplete closure."""
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


def production_closure(source_root: Path) -> dict[str, Path]:
    """The deterministic set of production `gnosis.*` modules to deploy, mapped to
    their source files. Includes every transitive import plus each module's parent
    package `__init__`. Production modules only — nothing test/dev is reached."""
    seen: set[str] = set()
    files: dict[str, Path] = {}
    stack = list(_CLOSURE_ROOTS)
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class ApplicationFile:
    relpath: str          # POSIX-style, relative to the source root
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
                           separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_application_manifest(source_root: Path) -> ApplicationManifest:
    """The authoritative, deterministic operator-application manifest."""
    closure = production_closure(source_root)
    entries: list[ApplicationFile] = []
    for src in closure.values():
        rel = src.relative_to(source_root).as_posix()
        entries.append(ApplicationFile(relpath=rel, digest=_sha256(src)))
    entries.sort(key=lambda f: f.relpath)
    files = tuple(entries)
    return ApplicationManifest(files=files, tree_digest=_tree_digest(files))


def application_root_for(layout: DeploymentLayout) -> Path:
    """The deployed operator/application code root inside the existing layout."""
    return Path(layout.code_release_base) / _APP_SUBDIR


def operator_entry_content(app_root: Path) -> str:
    """An isolated entry that delegates EXACTLY to gnosis.director.cli:main,
    importing only from the deployed application root (never CWD/PYTHONPATH/site).
    Run it with `<runtime> -I -B <entry> ...`."""
    return (
        "import sys\n"
        "from pathlib import Path\n"
        f"_APP_ROOT = r\"{app_root}\"\n"
        "sys.path.insert(0, _APP_ROOT)\n"
        "from gnosis.director.cli import main\n"
        "raise SystemExit(main(sys.argv[1:]))\n")


@dataclass(frozen=True)
class DeployedApplication:
    app_root: Path
    entry_path: Path
    manifest: ApplicationManifest


def _assert_inside(root: Path, target: Path) -> None:
    root_r = root.resolve()
    target_r = target.resolve()
    if root_r != target_r and root_r not in target_r.parents:
        raise OperatorStackError(
            f"deployment target {target} escapes the application root {root}")


def deploy_operator_stack(source_root: Path, app_root: Path) -> DeployedApplication:
    """Deploy the operator stack atomically into `app_root`.

    Stages the measured closure beside `app_root`, verifies source==staged, writes
    the entry + manifest, then activates by replacing `app_root`. A missing module,
    a traversal, or any copy failure fails closed and leaves no valid `app_root`.
    """
    manifest = build_application_manifest(source_root)
    if not manifest.files:
        raise OperatorStackError("empty operator manifest; refusing to deploy")
    app_root = Path(app_root)
    staging = app_root.parent / (app_root.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    try:
        for f in manifest.files:
            src = source_root / f.relpath
            if not src.is_file():
                raise OperatorStackError(f"required module missing at source: {f.relpath}")
            dest = staging / f.relpath
            _assert_inside(staging, dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            if _sha256(dest) != f.digest:
                raise OperatorStackError(f"deployed byte mismatch for {f.relpath}")
        (staging / "APPLICATION.json").write_text(
            json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
        (staging / "__gnosis_app_marker__").write_text("gnosis-operator-app\n",
                                                       encoding="utf-8")
        # activate atomically
        if app_root.exists():
            shutil.rmtree(app_root)
        staging.replace(app_root)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    entry_path = app_root.parent / _ENTRY_NAME
    entry_path.write_text(operator_entry_content(app_root), encoding="utf-8")
    return DeployedApplication(app_root=app_root, entry_path=entry_path,
                               manifest=manifest)


def verify_application_tree(app_root: Path,
                            manifest: ApplicationManifest) -> tuple[bool, list[str]]:
    """Re-measure the deployed tree against the manifest. Detects tamper, missing
    files and unexpected extra files."""
    problems: list[str] = []
    expected = {f.relpath: f.digest for f in manifest.files}
    for rel, digest in expected.items():
        dest = app_root / rel
        if not dest.is_file():
            problems.append(f"missing: {rel}")
        elif _sha256(dest) != digest:
            problems.append(f"tampered: {rel}")
    # unexpected .py files (ignore the manifest/marker sidecars)
    allowed = set(expected) | {"APPLICATION.json", "__gnosis_app_marker__"}
    for path in app_root.rglob("*.py"):
        rel = path.relative_to(app_root).as_posix()
        if rel not in allowed:
            problems.append(f"unexpected: {rel}")
    return (not problems), problems
