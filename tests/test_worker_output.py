import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from gnosis.trust.worker_output import read_worker_output


def test_exact_bounded_output(tmp_path: Path) -> None:
    output = tmp_path / "stdout.log"
    output.write_bytes(b"output\x00\xff")
    assert read_worker_output(output, limit=8) == b"output\x00\xff"
    with pytest.raises(OSError):
        read_worker_output(output, limit=7)


def test_hardlink_is_refused_without_reading(tmp_path: Path) -> None:
    secret = tmp_path / "protected.txt"
    secret.write_bytes(b"protected bytes")
    output = tmp_path / "stdout.log"
    os.link(secret, output)
    with pytest.raises(OSError, match="single-link"):
        read_worker_output(output, limit=100)


def test_ancestor_redirect_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "stdout.log").write_bytes(b"outside output")
    link = tmp_path / "redirect"
    if sys.platform == "win32":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(target, target_is_directory=True)
    try:
        with pytest.raises(OSError, match="redirected"):
            read_worker_output(link / "stdout.log", limit=100)
    finally:
        if sys.platform == "win32":
            link.rmdir()
        else:
            link.unlink()


def test_missing_output_is_not_empty_success(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        read_worker_output(tmp_path / "missing", limit=100)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing contract")
def test_reader_holds_file_against_concurrent_writer(tmp_path: Path) -> None:
    output = tmp_path / "stdout.log"
    output.write_bytes(b"original")
    real_fstat = os.fstat

    def inspect_while_locked(fd: int) -> os.stat_result:
        with pytest.raises(OSError), output.open("wb") as writer:
            writer.write(b"replaced")
        return real_fstat(fd)

    with mock.patch("gnosis.trust.worker_output.os.fstat", side_effect=inspect_while_locked):
        assert read_worker_output(output, limit=100) == b"original"
    assert output.read_bytes() == b"original"
