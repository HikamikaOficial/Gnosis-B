r"""F-33 Stage 2C-B1-R2C — named-pipe OBSERVATION mutation set (NPM1-NPM8).

Each mutant injects an observation-truthfulness defect into the qualified pipe
observer (or the R1 bounded loop) and runs the NP test that must fail on it. A
mutant is CAUGHT when the guarding test fails; the source is always restored.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(r"C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi")
PY = REPO / ".venv" / "Scripts" / "python.exe"
OPS = "scripts/stage2cb_ops.py"
CB = "scripts/stage2cb.py"
T = "tests/test_stage2cb_b1_r2c.py"
R1 = "tests/test_stage2cb_b1_r1.py"

MUTANTS = [
    ("NPM1", "restore pathlib existence probe", OPS,
     "pipe_exists=observer.observe,",
     "pipe_exists=lambda: Path(pipe_name).exists(),  # NPM1",
     f"{R1}::TestCanonicalPipeName::test_real_pipe_ready_uses_exact_path_not_reprefixed"),
    ("NPM2", "treat any Win32 error as ordinary not-ready", OPS,
     'raise PipeObservationError(f"WaitNamedPipeW failed: {name} ({err})")',
     "return False  # NPM2",
     f"{T}::TestObserverSemantics::test_np5_access_denied_not_ready_explicit"),
    ("NPM3", "treat access denied as READY", OPS,
     '        if ok:\n            self.last.update(win32_error_code=0, win32_error_name="SUCCESS",',
     '        if err == _ERROR_ACCESS_DENIED:  # NPM3\n            return True\n        if ok:\n            self.last.update(win32_error_code=0, win32_error_name="SUCCESS",',
     f"{T}::TestObserverSemantics::test_np5_access_denied_not_ready_explicit"),
    ("NPM4", "invalid name treated as transient", OPS,
     "_TRANSIENT_NOT_READY = {_ERROR_FILE_NOT_FOUND, _ERROR_SEM_TIMEOUT, _ERROR_PIPE_BUSY}",
     "_TRANSIENT_NOT_READY = {_ERROR_FILE_NOT_FOUND, _ERROR_SEM_TIMEOUT, _ERROR_PIPE_BUSY, _ERROR_INVALID_NAME}  # NPM4",
     f"{T}::TestObserverSemantics::test_np6_invalid_name_is_observation_error"),
    ("NPM5", "reprefix / mangle the pipe name", OPS,
     "ok, err = self._wait_fn(self._pipe_name, self._probe_timeout_ms)",
     'ok, err = self._wait_fn(rf"\\\\.\\pipe\\{self._pipe_name}", self._probe_timeout_ms)  # NPM5',
     f"{T}::TestObserverSemantics::test_np8_canonical_pipe_passed_verbatim"),
    ("NPM6", "ignore service death", CB,
     "        if not service_alive():",
     "        if False:  # NPM6",
     f"{T}::TestObserverBoundedLoop::test_np9_service_dies_while_waiting"),
    ("NPM7", "unbounded wait (drop the deadline)", CB,
     "        if now() - start >= timeout_s:",
     "        if False:  # NPM7",
     f"{T}::TestObserverBoundedLoop::test_np2_not_created_times_out"),
    ("NPM8", "invert busy semantics (busy -> READY)", OPS,
     "            return False\n        # access-denied / invalid-name / unexpected -> fail closed (observation-error)",
     "            return True  # NPM8\n        # access-denied / invalid-name / unexpected -> fail closed (observation-error)",
     f"{T}::TestObserverSemantics::test_np3_busy_present_not_connectable"),
]


def run_test(node: str) -> bool:
    p = subprocess.run([str(PY), "-m", "pytest", node, "-q", "--no-header",
                        "-p", "no:cacheprovider"], cwd=REPO, capture_output=True, text=True)
    return p.returncode == 0


def main() -> int:
    caught = 0
    for mid, desc, rel, old, new, node in MUTANTS:
        path = REPO / rel
        original = path.read_text(encoding="utf-8")
        if old not in original:
            print(f"{mid}: NOT APPLIED (anchor) — {desc}")
            continue
        try:
            path.write_text(original.replace(old, new, 1), encoding="utf-8")
            passed = run_test(node)
        finally:
            path.write_text(original, encoding="utf-8")
        v = "CAUGHT" if not passed else "SURVIVED"
        caught += v == "CAUGHT"
        print(f"{mid}: APPLIED / {v}  ({desc})")
    print(f"\n{caught}/{len(MUTANTS)} applied observation mutants CAUGHT")
    return 0 if caught == len(MUTANTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
