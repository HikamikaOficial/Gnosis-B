import subprocess
import sys
from pathlib import Path

import pytest

from gnosis.provision.git_package import REQUIRED_FILES, GitPackageError, git_package_entrypoint


def package(root: Path) -> Path:
    for relative in REQUIRED_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture bytes; never executed")
    return root


def test_supported_package(tmp_path: Path) -> None:
    root = package(tmp_path / "git")
    assert git_package_entrypoint(root) == root / "cmd/git.exe"


@pytest.mark.parametrize("relative", REQUIRED_FILES)
def test_missing_required_file(tmp_path: Path, relative: str) -> None:
    root = package(tmp_path / "git")
    (root / relative).unlink()
    with pytest.raises(GitPackageError):
        git_package_entrypoint(root)


def test_empty_executable(tmp_path: Path) -> None:
    root = package(tmp_path / "git")
    (root / "cmd/git.exe").write_bytes(b"")
    with pytest.raises(GitPackageError):
        git_package_entrypoint(root)


def test_redirected_extra_directory(tmp_path: Path) -> None:
    root = package(tmp_path / "git")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "extra"
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                       capture_output=True, check=True)
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(GitPackageError, match="redirected"):
            git_package_entrypoint(root)
    finally:
        if sys.platform == "win32":
            link.rmdir()
        else:
            link.unlink()
