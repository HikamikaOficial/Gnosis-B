"""Claude review transport using the authenticated, contained Worker account.

The pipeline still checks subject fingerprints before accepting a review. This
transport permits only plan mode, never inherits Director credentials and moves
bounded output to protected evidence after the job has been closed.
"""
from __future__ import annotations

import json
import math
import uuid
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from gnosis.kernel.file_lock import FileLock
from gnosis.runner.capture import ExecutionResult
from gnosis.runner.claude_cli_runner import ClaudeCodeCLIRunner, CLIRunner
from gnosis.trust.worker_launcher import WorkerLauncher, assert_no_same_user_fallback
from gnosis.trust.worker_output import read_worker_output, retain_worker_output


class WorkerClaudeReviewer:
    def __init__(self, *, binary: Path, launcher: WorkerLauncher,
                 output_root: Path, guard: Callable[[], None]):
        if not binary.is_absolute() or not output_root.is_absolute():
            raise ValueError("review binary and output root must be absolute")
        self.binary = str(binary)
        self.launcher = launcher
        self.output_root = output_root
        self.guard = guard

    def run(self, prompt: str, cwd: Path, stdout_path: Path, stderr_path: Path,
            timeout_s: float = 900, permission_mode: str = "plan",
            cancellation_token: Any = None, heartbeat_fn: Any = None,
            model: str | None = None, **options: Any) -> ExecutionResult:
        if permission_mode != "plan" or any(v is not None for v in options.values()):
            raise ValueError("Worker reviewer permits plan mode without launch/environment overrides")
        if (isinstance(timeout_s, bool) or not math.isfinite(timeout_s) or timeout_s <= 0
                or not all(p.is_absolute() for p in (cwd, stdout_path, stderr_path))):
            raise ValueError("review requires absolute paths and a finite positive deadline")
        assert_no_same_user_fallback(self.launcher)
        self.guard()
        identifier = "review-" + uuid.uuid4().hex
        stage = self.output_root / identifier
        stage.mkdir(parents=True, exist_ok=False)
        argv = ClaudeCodeCLIRunner(self.binary).build_argv(prompt, permission_mode="plan", model=model)
        # Protected intent survives interruption; no incomplete output implies PASS.
        with FileLock(stdout_path.with_suffix(stdout_path.suffix + ".lock")):
            retain_worker_output(stdout_path.with_suffix(stdout_path.suffix + ".intent.json"),
                json.dumps({"schema": "gnosis.worker-review.v1", "run_id": identifier,
                            "stage": str(stage), "cwd": str(cwd),
                            "timeout_s": timeout_s}).encode("utf-8"))
            try:
                result = CLIRunner().run(argv, cwd, stage / "stdout", stage / "stderr", timeout_s,
                    cancellation_token=cancellation_token, heartbeat_fn=heartbeat_fn,
                    launcher=self.launcher, require_trusted_launch=True,
                    launch_id=identifier, run_id=identifier)
            except BaseException:
                for origin, target in ((stage / "stdout", stdout_path), (stage / "stderr", stderr_path)):
                    try:
                        retain_worker_output(target, read_worker_output(origin, limit=16 * 1024**2))
                    except OSError:
                        pass  # Keep the original failure; staged data remains for inspection.
                raise
            stdout = read_worker_output(stage / "stdout", limit=16 * 1024**2)
            stderr = read_worker_output(stage / "stderr", limit=16 * 1024**2)
            retain_worker_output(stdout_path, stdout)
            retain_worker_output(stderr_path, stderr)
            self.guard()
            payload = None
            if len(stdout) <= 1024 * 1024:
                try:
                    candidate = json.loads(stdout)
                    if isinstance(candidate, dict):
                        payload = candidate
                except (ValueError, UnicodeError):
                    pass
            return replace(result, stdout_path=str(stdout_path), stderr_path=str(stderr_path),
                           parsed_json=payload)
