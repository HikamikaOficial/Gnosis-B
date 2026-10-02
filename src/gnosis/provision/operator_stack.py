"""Canonical operator-stack deployment (F-33 Stage 2C-PACK-R1 / R2).

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
- APPLICATION-PROVIDED = production closure - F-17-provided. Deployed and measured
  here (`operator_entry.py` included), and it may NEVER include a `gnosis/trust/*`
  path (ownership guard).

R2 — MANDATORY COMPOSED-IDENTITY ENFORCEMENT. The measured `operator_entry.py` is
now SELF-VERIFYING: before it imports the (unverified) `gnosis` package it re-
measures the deployed application tree against the local `APPLICATION.json` AND
against the EXPECTED application digest carried by a trusted composed-deployment
record that lives OUTSIDE the application tree (see `gnosis_deployment`). The
manifest is parsed fail-closed (schema, no duplicate keys, canonical relpaths,
bounded size). The startup check uses ONLY the Python stdlib and the measured
entry bytes — it never imports the application package to verify that same
package. `APPLICATION.json` alone is NEVER authority: internal self-consistency
cannot be trusted, so the external trusted record's expected digest must agree.

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
_MANIFEST_NAME = "APPLICATION.json"
_MANIFEST_SCHEMA = "gnosis.application_manifest.v1"
# R3D: the trusted composed record is v2 (adds effective_deployment_digest). The
# baked startup verifier still only consumes application_tree_digest (present in
# both), but must accept the current record schema — v1 records fail closed.
_COMPOSED_RECORD_SCHEMA = "gnosis.composed_record.v2"

# Fail-closed parser bounds (defence in depth; a manifest/record far beyond the
# real closure is refused rather than measured).
_MAX_MANIFEST_BYTES = 1_048_576
_MAX_MANIFEST_FILES = 10_000


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


def worker_bootstrap_files(source_root: Path) -> tuple[tuple[str, str], ...]:
    """Minimal Worker-readable bootstrap, copied into the measured runtime."""
    return tuple((str(path), path.relative_to(source_root).as_posix())
                 for _, path in sorted(_closure(source_root, ("gnosis.trust.bootstrap",)).items()))


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
        return {"schema": _MANIFEST_SCHEMA, "tree_digest": self.tree_digest,
                "files": [{"relpath": f.relpath, "digest": f.digest} for f in self.files]}


def _tree_digest(files: tuple[ApplicationFile, ...]) -> str:
    # CANONICAL application tree digest. The self-verifying operator entry and
    # `canonical_launch` both recompute this EXACT construction (sorted pairs,
    # compact JSON), so any change here must be mirrored in the inline entry.
    canonical = json.dumps([[f.relpath, f.digest] for f in files],
                           separators=(",", ":"))
    return _sha256_bytes(canonical.encode("utf-8"))


def canonical_package_root(layout: DeploymentLayout) -> Path:
    """The ONE authoritative deployed package root (contains `gnosis/`); the same
    root the F-17 Provisioner deploys the trust plane + `python._pth` into."""
    return Path(layout.trust_root)


# ---------------------------------------------------------------------------
# Canonical relpath validation (shared by the manifest builder, the fail-closed
# loader used by canonical_launch, and mirrored inside the operator entry).
# ---------------------------------------------------------------------------
def _relpath_is_canonical(rel: str) -> bool:
    if not rel or rel != rel.strip():
        return False
    if "\\" in rel or rel.startswith("/") or rel.endswith("/"):
        return False
    if ":" in rel:  # no drive letters
        return False
    parts = rel.split("/")
    return not any(p in ("", ".", "..") for p in parts)


def operator_entry_content(package_root: Path, composed_record_path: Path) -> str:
    """The measured, SELF-VERIFYING operator entry (R2).

    Baked-in (and therefore measured): the package root, the local manifest path,
    and the absolute path of the trusted composed-deployment record that lives
    OUTSIDE this tree. Before importing the (still-unverified) application package
    the entry, using ONLY the stdlib and its own measured bytes:

      1. parses `APPLICATION.json` fail-closed (schema, no duplicate keys,
         canonical relpaths, bounded size/count);
      2. re-measures every listed file against the deployed bytes;
      3. recomputes the canonical tree digest and requires it to equal the
         manifest's `tree_digest`;
      4. reads the trusted composed record (fail-closed) and requires its
         `application_tree_digest` to equal the re-measured tree digest — so the
         local manifest ALONE can never authorise startup;
      5. requires its own relpath to be a measured manifest entry.

    Only then does it insert the package root and delegate to
    `gnosis.director.cli:main`. Launch remains `python -I -B <this file>`.
    """
    root = str(package_root)
    rec = str(composed_record_path)
    # NOTE: keep this body stdlib-only and self-contained; it is measured, and it
    # must never import the application package before verification succeeds.
    return f'''import sys, os, json, hashlib

_ROOT = r"{root}"
_RECORD = r"{rec}"
_MANIFEST = os.path.join(_ROOT, "{_MANIFEST_NAME}")
_ENTRY_REL = "{_ENTRY_NAME}"
_MANIFEST_SCHEMA = "{_MANIFEST_SCHEMA}"
_RECORD_SCHEMA = "{_COMPOSED_RECORD_SCHEMA}"
_MAX_BYTES = {_MAX_MANIFEST_BYTES}
_MAX_FILES = {_MAX_MANIFEST_FILES}


def _die(msg):
    sys.stderr.write("gnosis composed-identity startup verification FAILED: "
                     + msg + chr(10))
    raise SystemExit(70)


def _no_dupes(pairs):
    seen = {{}}
    for k, v in pairs:
        if k in seen:
            _die("duplicate JSON key: " + str(k))
        seen[k] = v
    return seen


def _load_json(path, schema):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        _die("cannot read " + path + ": " + str(exc))
    if len(raw) > _MAX_BYTES:
        _die("json too large: " + path)
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_dupes)
    except Exception as exc:  # noqa: BLE001
        _die("malformed json " + path + ": " + str(exc))
    if not isinstance(data, dict) or data.get("schema") != schema:
        _die("bad/absent schema in " + path)
    return data


def _canon_rel(rel):
    if not isinstance(rel, str) or not rel or rel != rel.strip():
        return False
    if "\\\\" in rel or rel.startswith("/") or rel.endswith("/") or ":" in rel:
        return False
    parts = rel.split("/")
    return not any(p in ("", ".", "..") for p in parts)


def _is_hex64(s):
    return isinstance(s, str) and len(s) == 64 and all(
        c in "0123456789abcdef" for c in s)


def _verify():
    man = _load_json(_MANIFEST, _MANIFEST_SCHEMA)
    if set(man.keys()) != {{"schema", "tree_digest", "files"}}:
        _die("unexpected manifest keys")
    if not _is_hex64(man["tree_digest"]):
        _die("bad manifest tree_digest")
    files = man["files"]
    if not isinstance(files, list) or len(files) > _MAX_FILES or not files:
        _die("bad manifest file list")
    pairs = []
    seen_rel = set()
    for ent in files:
        if not isinstance(ent, dict) or set(ent.keys()) != {{"relpath", "digest"}}:
            _die("bad manifest entry")
        rel, dig = ent["relpath"], ent["digest"]
        if not _canon_rel(rel):
            _die("non-canonical relpath: " + repr(rel))
        if rel in seen_rel:
            _die("duplicate relpath: " + rel)
        seen_rel.add(rel)
        if not _is_hex64(dig):
            _die("bad digest for " + rel)
        target = os.path.join(_ROOT, rel.replace("/", os.sep))
        try:
            with open(target, "rb") as fh:
                actual = hashlib.sha256(fh.read()).hexdigest()
        except OSError as exc:
            _die("missing measured file " + rel + ": " + str(exc))
        if actual != dig:
            _die("tampered file: " + rel)
        pairs.append([rel, dig])
    if _ENTRY_REL not in seen_rel:
        _die("operator entry is not a measured manifest file")
    pairs.sort(key=lambda p: p[0])
    recomputed = hashlib.sha256(
        json.dumps(pairs, separators=(",", ":")).encode("utf-8")).hexdigest()
    if recomputed != man["tree_digest"]:
        _die("recomputed application tree digest does not match manifest")
    rec = _load_json(_RECORD, _RECORD_SCHEMA)
    expected = rec.get("application_tree_digest")
    if not _is_hex64(expected):
        _die("trusted record has no valid application_tree_digest")
    # The external trusted record is the authority: the local manifest alone,
    # however internally consistent, cannot authorise startup.
    if expected != man["tree_digest"]:
        _die("application tree digest does not match the TRUSTED composed record")


_verify()
sys.path.insert(0, _ROOT)
from gnosis.director.cli import main  # noqa: E402
raise SystemExit(main(sys.argv[1:]))
'''


def build_application_manifest(source_root: Path, package_root: Path,
                               composed_record_path: Path) -> ApplicationManifest:
    """The deterministic APPLICATION manifest: the non-trust modules PLUS the
    measured self-verifying `operator_entry.py`. Contains no `gnosis/trust/*` path."""
    entries: list[ApplicationFile] = []
    for src in application_modules(source_root).values():
        rel = _rel(source_root, src)
        if rel.startswith(_TRUST_PREFIX):  # ownership guard, defence in depth
            raise OperatorStackError(f"application manifest must not own trust path {rel}")
        entries.append(ApplicationFile(relpath=rel, digest=_sha256(src)))
    entry_bytes = operator_entry_content(package_root, composed_record_path).encode("utf-8")
    entries.append(ApplicationFile(relpath=_ENTRY_NAME,
                                   digest=_sha256_bytes(entry_bytes)))
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


def deploy_operator_stack(source_root: Path, package_root: Path,
                          composed_record_path: Path) -> DeployedApplication:
    """Deploy the APPLICATION modules into the canonical package root (alongside
    the F-17-owned trust plane), then the measured self-verifying operator entry
    and the `APPLICATION.json` manifest.

    Fails closed on: a trust path (ownership guard), an escape, a copy-byte
    mismatch, or an attempt to overwrite an existing F-17-owned file. The trusted
    composed record itself is written by the composed provisioner AFTER this
    returns and AFTER verification (see `gnosis_deployment.provision`).
    """
    package_root = Path(package_root)
    manifest = build_application_manifest(source_root, package_root,
                                          composed_record_path)
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
    entry_path.write_bytes(
        operator_entry_content(package_root, composed_record_path).encode("utf-8"))
    if _sha256(entry_path) != next(
            f.digest for f in manifest.files if f.relpath == _ENTRY_NAME):
        raise OperatorStackError("deployed operator entry byte mismatch")
    (package_root / _MANIFEST_NAME).write_text(
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


def measure_application_tree(package_root: Path,
                             manifest: ApplicationManifest) -> str:
    """Re-measure the deployed application tree from CURRENT bytes and return the
    canonical tree digest (used by `canonical_launch` — it never trusts an
    in-memory digest from provisioning time)."""
    ok, problems = verify_application_tree(package_root, manifest)
    if not ok:
        raise OperatorStackError(f"application tree does not match manifest: {problems}")
    measured = tuple(
        ApplicationFile(relpath=f.relpath, digest=_sha256(package_root / f.relpath))
        for f in manifest.files)
    return _tree_digest(measured)


def load_application_manifest(package_root: Path) -> ApplicationManifest:
    """Fail-closed loader for the deployed `APPLICATION.json` (schema, no
    duplicate keys, canonical relpaths, bounded size/count, hex digests)."""
    path = package_root / _MANIFEST_NAME
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise OperatorStackError(f"cannot read {path}: {exc}") from exc
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise OperatorStackError(f"manifest too large: {path}")

    def _no_dupes(pairs: list[tuple[str, object]]) -> dict[str, object]:
        seen: dict[str, object] = {}
        for k, v in pairs:
            if k in seen:
                raise OperatorStackError(f"duplicate JSON key: {k}")
            seen[k] = v
        return seen

    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_dupes)
    except OperatorStackError:
        raise
    except Exception as exc:
        raise OperatorStackError(f"malformed manifest {path}: {exc}") from exc
    if not isinstance(data, dict) or set(data.keys()) != {"schema", "tree_digest", "files"}:
        raise OperatorStackError("unexpected manifest structure")
    if data["schema"] != _MANIFEST_SCHEMA:
        raise OperatorStackError(f"unexpected manifest schema {data['schema']!r}")
    td = data["tree_digest"]
    if not (isinstance(td, str) and len(td) == 64):
        raise OperatorStackError("bad manifest tree_digest")
    files_raw = data["files"]
    if not isinstance(files_raw, list) or not files_raw or len(files_raw) > _MAX_MANIFEST_FILES:
        raise OperatorStackError("bad manifest file list")
    seen_rel: set[str] = set()
    entries: list[ApplicationFile] = []
    for ent in files_raw:
        if not isinstance(ent, dict) or set(ent.keys()) != {"relpath", "digest"}:
            raise OperatorStackError("bad manifest entry")
        rel, dig = ent["relpath"], ent["digest"]
        if not _relpath_is_canonical(rel):
            raise OperatorStackError(f"non-canonical relpath: {rel!r}")
        if rel in seen_rel:
            raise OperatorStackError(f"duplicate relpath: {rel}")
        seen_rel.add(rel)
        if not (isinstance(dig, str) and len(dig) == 64):
            raise OperatorStackError(f"bad digest for {rel}")
        entries.append(ApplicationFile(relpath=rel, digest=dig))
    entries.sort(key=lambda f: f.relpath)
    files = tuple(entries)
    if _tree_digest(files) != td:
        raise OperatorStackError("manifest tree_digest does not match its own files")
    return ApplicationManifest(files=files, tree_digest=td)
