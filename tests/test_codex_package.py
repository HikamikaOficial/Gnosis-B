import json
from pathlib import Path

import pytest

from gnosis.provision.codex_package import CodexPackageError, codex_package_entrypoint


@pytest.fixture
def package(tmp_path):
    return make_package(tmp_path)


def make_package(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    descriptor = {
        "layoutVersion": 1, "version": "0.148.0",
        "target": "x86_64-pc-windows-msvc", "variant": "codex",
        "entrypoint": "bin/codex.exe", "resourcesDir": "codex-resources",
        "pathDir": "codex-path",
    }
    (tmp_path / "codex-package.json").write_text(json.dumps(descriptor))
    for name in ("bin/codex.exe", "bin/codex-code-mode-host.exe", "codex-path/rg.exe",
                 "codex-resources/codex-command-runner.exe",
                 "codex-resources/codex-windows-sandbox-setup.exe"):
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"test-native-file")
    return tmp_path


def test_resolves_vendor_entrypoint(package):
    assert codex_package_entrypoint(package) == package / "bin" / "codex.exe"


@pytest.mark.parametrize("field,value", [
    ("entrypoint", "../outside.exe"), ("entrypoint", "C:/outside.exe"),
    ("resourcesDir", "../resources"), ("layoutVersion", True),
    ("layoutVersion", 2), ("target", "x86_64-unknown-linux-gnu"),
    ("variant", "untrusted"), ("pathDir", "elsewhere"), ("version", None),
])
def test_rejects_unsupported_or_escaping_descriptor(package, field, value):
    path = package / "codex-package.json"
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(CodexPackageError):
        codex_package_entrypoint(package)


@pytest.mark.parametrize("relative", ["bin/codex.exe", "bin/codex-code-mode-host.exe",
    "codex-path/rg.exe", "codex-resources/codex-command-runner.exe",
    "codex-resources/codex-windows-sandbox-setup.exe"])
def test_rejects_incomplete_package(package, relative):
    (package / relative).write_bytes(b"")
    with pytest.raises(CodexPackageError):
        codex_package_entrypoint(package)


@pytest.mark.parametrize("raw", [b"{", b"x" * 4097,
    b'{"layoutVersion":1,"layoutVersion":1}', b"[]"])
def test_rejects_malformed_descriptor(package, raw):
    (package / "codex-package.json").write_bytes(raw)
    with pytest.raises(CodexPackageError):
        codex_package_entrypoint(package)


def test_rejects_linked_package_content(package, monkeypatch):
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda p: p.name == "codex-path" or original(p))
    with pytest.raises(CodexPackageError, match="linked path"):
        codex_package_entrypoint(package)
