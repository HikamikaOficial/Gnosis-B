"""Recover forensic check output; never reconstruct a passing check verdict."""
from __future__ import annotations

import json
import math
import re
import stat
from pathlib import Path
from typing import Any

from gnosis.kernel.check_execution import CheckExecutionUnavailable
from gnosis.kernel.file_lock import FileLock, LockTimeoutError
from gnosis.trust.launch_spec import LaunchSpec
from gnosis.trust.worker_output import read_worker_output, retain_worker_output

ATTEMPT_SCHEMA = "gnosis.verification-attempt.v1"
_RUN_ID = re.compile(r"check-[0-9a-f]{32}\Z")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate verification intent field")
        result[key] = value
    return result


def _ordinary_directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise CheckExecutionUnavailable("verification evidence directory is redirected")


def recover_check_outputs(*, evidence_root: Path, output_root: Path,
                          runtime: Path) -> tuple[str, ...]:
    """Retain missing output for unlocked attempts named by protected intents.

The executor holds attempt.lock from before intent creation through final
retention. A live attempt is skipped, even from another Director process.
Recovered bytes are diagnostics only: there is no recovered exit code or PASS.
"""
    if not evidence_root.exists():
        return ()
    _ordinary_directory(evidence_root)
    recovered: list[str] = []
    for index, retained in enumerate(evidence_root.iterdir()):
        if index >= 10000:
            raise CheckExecutionUnavailable("verification recovery inventory exceeds its bound")
        if not _RUN_ID.fullmatch(retained.name):
            raise CheckExecutionUnavailable("unrecognized verification evidence entry")
        _ordinary_directory(retained)
        try:
            with FileLock(retained / "attempt.lock", timeout_s=0):
                intent = retained / "intent.json"
                if not intent.exists():
                    continue  # interrupted before an execution intent was written
                try:
                    record = json.loads(read_worker_output(intent, limit=1024**2),
                                        object_pairs_hook=_unique_object)
                    if (not isinstance(record, dict)
                            or set(record) != {"schema", "spec", "timeout_s"}
                            or record["schema"] != ATTEMPT_SCHEMA):
                        raise ValueError("invalid verification intent")
                    spec = LaunchSpec.from_dict(record["spec"])
                    timeout = record["timeout_s"]
                    if (type(timeout) not in (float, int) or not math.isfinite(timeout)
                            or timeout <= 0):
                        raise ValueError("invalid verification deadline")
                    stage = output_root / retained.name
                    if (spec.run_id != retained.name or spec.launch_id != retained.name
                            or Path(spec.executable) != runtime
                            or Path(spec.stdout_path) != stage / "stdout"
                            or Path(spec.stderr_path) != stage / "stderr"):
                        raise ValueError("verification intent escapes its assigned namespace")
                except (OSError, ValueError, RuntimeError, TypeError, KeyError, OverflowError) as exc:
                    raise CheckExecutionUnavailable("verification intent could not be recovered") from exc
                changed = False
                for name in ("stdout", "stderr"):
                    destination = retained / name
                    if destination.exists():
                        continue  # protected evidence is never replaced
                    try:
                        (stage / name).lstat()
                    except FileNotFoundError:
                        continue  # a Worker may never have opened this stream
                    try:
                        data = read_worker_output(stage / name, limit=16 * 1024**2)
                    except FileNotFoundError:
                        continue  # a Worker may never have opened this stream
                    except OSError as exc:
                        raise CheckExecutionUnavailable("verification output recovery refused") from exc
                    retain_worker_output(destination, data)
                    changed = True
                if changed:
                    recovered.append(retained.name)
        except LockTimeoutError:
            continue
    return tuple(recovered)
