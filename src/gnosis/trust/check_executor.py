"""Run verification commands through the contained Worker identity.

This executor never starts a local subprocess. Output is untrusted, bounded,
and copied into protected evidence only after the Worker's job is closed.
"""
from __future__ import annotations

import json
import math
import subprocess
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from gnosis.kernel.check_execution import CheckExecutionUnavailable
from gnosis.kernel.file_lock import FileLock
from gnosis.trust.check_recovery import ATTEMPT_SCHEMA, recover_check_outputs
from gnosis.trust.launch_spec import LaunchSpec
from gnosis.trust.worker_launcher import WorkerLauncher
from gnosis.trust.worker_output import read_worker_output, retain_worker_output

# This literal runs only after the identity transition, from the measured
# interpreter with -I. Candidate imports cannot replace the transport wrapper.
# Cache settings cross as explicit non-secret argv, never the Director's env.
_WRAPPER = (
    "import json,os,subprocess,sys; "
    "env=dict(os.environ); env.update(json.loads(sys.argv[1])); "
    "raise SystemExit(subprocess.run(sys.argv[2:],env=env,check=False).returncode)"
)


class WorkerCheckExecutor:
    def __init__(self, *, launcher: WorkerLauncher, runtime: Path,
                 output_root: Path, evidence_root: Path,
                 guard: Callable[[], None], is_cancelled: Callable[[], bool]):
        if not all(p.is_absolute() for p in (runtime, output_root, evidence_root)):
            raise ValueError("verification runtime and output roots must be absolute")
        self.launcher = launcher
        self.runtime = runtime
        self.output_root = output_root
        self.evidence_root = evidence_root
        self.guard = guard
        self.is_cancelled = is_cancelled

    def execute(self, argv: Sequence[str], *, cwd: Path,
                timeout_s: float | None,
                env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        if (isinstance(timeout_s, bool) or timeout_s is None
                or not math.isfinite(timeout_s) or timeout_s <= 0):
            raise CheckExecutionUnavailable("verification requires a finite positive deadline")
        if not argv or not Path(argv[0]).is_absolute() or not cwd.is_absolute():
            raise CheckExecutionUnavailable("verification requires an absolute executable and cwd")
        self.guard()
        run_id = f"check-{uuid.uuid4().hex}"
        with FileLock(self.evidence_root / run_id / "attempt.lock"):
            return self._execute_attempt(argv, cwd=cwd, timeout_s=timeout_s, run_id=run_id)

    def recover_outputs(self) -> tuple[str, ...]:
        self.guard()
        return recover_check_outputs(evidence_root=self.evidence_root,
                                     output_root=self.output_root, runtime=self.runtime)

    def _execute_attempt(self, argv: Sequence[str], *, cwd: Path,
                         timeout_s: float, run_id: str) -> subprocess.CompletedProcess[str]:
        stage = self.output_root / run_id
        stage.mkdir(parents=True, exist_ok=False)
        out, err = stage / "stdout", stage / "stderr"
        # Ignore the caller's ambient environment, including test plugin/options
        # overrides. All cache destinations belong to this specific Worker run.
        cache = {"PYTHONDONTWRITEBYTECODE": "1",
                 "PYTHONPYCACHEPREFIX": str(stage / "pycache"),
                 "MYPY_CACHE_DIR": str(stage / "mypy"),
                 "RUFF_CACHE_DIR": str(stage / "ruff"),
                 "PYTEST_ADDOPTS": "-p no:cacheprovider"}
        logical = (str(self.runtime), "-I", "-B", "-c", _WRAPPER,
                   json.dumps(cache, sort_keys=True), *argv)
        spec = LaunchSpec(run_id, str(self.runtime), logical, str(cwd),
                          str(out), str(err), run_id=run_id)
        retained = self.evidence_root / run_id
        retain_worker_output(retained / "intent.json", json.dumps({
            "schema": ATTEMPT_SCHEMA, "spec": spec.to_dict(),
            "timeout_s": timeout_s,
        }, sort_keys=True).encode("utf-8"))
        try:
            launched = self.launcher.launch(spec)
            try:
                code, timed_out, cancelled = launched.wait(timeout_s, is_cancelled=self.is_cancelled)
            finally:
                # Also kills surviving descendants, including on a wait exception.
                launched.close()
        except BaseException as exc:
            # Keep partial diagnostics and their protected attribution on failure.
            # A hard process kill leaves intent + staged bytes for recovery.
            self._retain_partial(retained, out, err)
            if isinstance(exc, Exception):
                raise CheckExecutionUnavailable("verification Worker launch/wait failed") from exc
            raise
        try:
            stdout = read_worker_output(out, limit=16 * 1024**2)
            stderr = read_worker_output(err, limit=16 * 1024**2)
            retain_worker_output(retained / "stdout", stdout)
            retain_worker_output(retained / "stderr", stderr)
        except OSError as exc:
            raise CheckExecutionUnavailable("verification output could not be retained") from exc
        self.guard()
        if cancelled:
            raise CheckExecutionUnavailable("verification was cancelled")
        if timed_out:
            raise subprocess.TimeoutExpired(list(argv), timeout_s, output=stdout, stderr=stderr)
        return subprocess.CompletedProcess(list(argv), code,
                                           stdout.decode("utf-8", "replace"),
                                           stderr.decode("utf-8", "replace"))

    @staticmethod
    def _retain_partial(retained: Path, out: Path, err: Path) -> None:
        failures = []
        for name, path in (("stdout", out), ("stderr", err)):
            try:
                retain_worker_output(retained / name, read_worker_output(path, limit=16 * 1024**2))
            except OSError as exc:
                failures.append({"stream": name, "error": type(exc).__name__})
        if failures:
            try:
                retain_worker_output(retained / "capture-errors.json",
                                     json.dumps(failures).encode("utf-8"))
            except OSError:
                # Preserve the original launch failure; staged files remain.
                pass
