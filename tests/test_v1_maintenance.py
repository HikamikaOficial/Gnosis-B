import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v1_maintenance as maintenance

from tests.test_stage2cb_backend import _config


def config_bytes(tmp_path: Path) -> bytes:
    config = replace(_config(tmp_path), source_commit="a" * 40, source_tree="b" * 40,
                     runtime_src=str(tmp_path / "runtime"),
                     reviewer_binary=str(tmp_path / "review.exe"),
                     residue_root=str(tmp_path / "maintenance"),
                     codex_runtime_src=str(tmp_path / "codex"),
                     git_runtime_src=str(tmp_path / "git"))
    return json.dumps(asdict(config)).encode()


def test_config_roundtrip(tmp_path: Path) -> None:
    raw = config_bytes(tmp_path)
    assert asdict(maintenance.decode_config(raw)) == json.loads(raw)


def test_entry_imports_its_own_checkout_without_site_or_working_directory(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "v1_maintenance.py"
    result = subprocess.run([sys.executable, "-I", "-S", "-B", str(script), "--help"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    assert "initialize,install,verify" in result.stdout


@pytest.mark.parametrize("key,value", [("source_commit", "HEAD"), ("runtime_src", "relative"),
                                       ("run_id", "../escape"), ("worker_username", True),
                                       ("codex_runtime_src", None)])
def test_bad_installation_input_refused(tmp_path: Path, key: str, value: object) -> None:
    record = json.loads(config_bytes(tmp_path))
    record[key] = value
    with pytest.raises(ValueError):
        maintenance.decode_config(json.dumps(record).encode())


def test_duplicate_fields_refused(tmp_path: Path) -> None:
    raw = config_bytes(tmp_path)
    with pytest.raises(ValueError, match="duplicate"):
        maintenance.decode_config(raw[:-1] + b', "run_id":"other"}')


def test_no_explicit_execution_does_not_construct_backend(tmp_path: Path) -> None:
    with mock.patch.object(maintenance, "WindowsRealOperations") as backend:
        with pytest.raises(SystemExit):
            maintenance.main(["install", str(tmp_path / "config.json")])
        backend.assert_not_called()


def test_non_elevated_install_does_not_read_config_or_install(tmp_path: Path) -> None:
    with (mock.patch.object(maintenance, "WindowsRealOperations") as backend,
          mock.patch.object(maintenance, "load_config") as load,
          mock.patch.object(maintenance, "install_pinned") as install):
        backend.return_value.is_elevated.return_value = False
        with pytest.raises(SystemExit):
            maintenance.main(["install", str(tmp_path / "config.json"), "--execute"])
        load.assert_not_called()
        install.assert_not_called()
