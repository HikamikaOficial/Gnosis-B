"""The trusted bootstrap. THIS CODE RUNS UNDER THE WORKER SID.

That sentence is the whole threat model of this file, so it is at the top rather
than buried. Everything else in `gnosis.trust` runs as the Director; this does
not. It is "trusted" only in the narrow sense that its BYTES are protected — the
script and its runtime live in a root the Worker may read and execute but not
write — and it is deliberately written so that being compromised buys an
attacker nothing it did not already have:

  * it holds NO credential and never sees one;
  * it receives NO privileged handle;
  * it makes NO security decision — the Director already decided, and this only
    refuses to carry out an instruction that fails its seal;
  * the process it creates runs as the SAME Worker SID it is already running as,
    so it can grant no authority it does not already possess.

A Worker that subverted this bootstrap could run whatever it likes AS THE
WORKER — which it could do anyway. What it must NOT be able to do is make the
Director's launch execute a DIFFERENT logical command than the one the Director
sealed, and that is what the digest check below prevents.

WHAT IT DOES, AND NOTHING ELSE:

    1. read the sealed LaunchSpec named on its own command line
    2. recompute `launch_spec_digest` and require the expected value
    3. re-validate the executable and the working directory
    4. create the real process with the EXACT argv vector, under the same SID
    5. propagate its exit code

FORBIDDEN HERE, by construction and by test: no shell, no `cmd /c`, no
`powershell -Command`, no PATH search, no `eval`/`exec`, no dynamic import, no
environment-derived configuration. It is invoked with `-I`, so PYTHONPATH, the
user site directory and every other Python environment variable are ignored: a
Worker cannot inject a module into this process by setting a variable.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# `-I` isolates the interpreter, which also means the package root is not on
# sys.path. It is derived from THIS FILE's own location — inside the trusted,
# Worker-read-only tool root — and never from an environment variable, an
# argument or the working directory, all of which the Worker can influence.
_SRC_ROOT = str(Path(__file__).resolve().parents[2])
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from gnosis.trust.launch import AuthorityUnavailable
from gnosis.trust.launch_spec import read_sealed_launch_spec

# Distinct, documented exit codes. The launcher must be able to tell "the seal
# failed" from "the real command ran and exited 2", and a single generic
# failure code would collapse exactly the distinction that matters. Chosen high
# to stay clear of the exit codes a real CLI produces.
EXIT_BAD_INVOCATION = 120
EXIT_SEAL_FAILED = 121
EXIT_TARGET_INVALID = 122
EXIT_LAUNCH_FAILED = 123


def _fail(code: int, message: str) -> int:
    # stderr, not stdout: stdout is the logical command's captured output and
    # must not be polluted by transport-layer diagnostics.
    print(f"gnosis-bootstrap: {message}", file=sys.stderr, flush=True)
    return code


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        return _fail(EXIT_BAD_INVOCATION,
                     "usage: bootstrap.py <launch-spec-path> <expected-digest>")
    spec_path, expected_digest = argv[1], argv[2]
    try:
        spec = read_sealed_launch_spec(Path(spec_path),
                                       expected_digest=expected_digest)
    except AuthorityUnavailable as exc:
        return _fail(EXIT_SEAL_FAILED, f"refusing to launch: {exc}")

    # Re-validated HERE, in the process that will actually create the child.
    # The Director validated the same things when it built the spec; the gap
    # between the two is exactly the window this closes.
    executable = Path(spec.executable)
    cwd = Path(spec.cwd)
    if not executable.is_file():
        return _fail(EXIT_TARGET_INVALID,
                     f"executable {spec.executable!r} is not a file")
    if not cwd.is_dir():
        return _fail(EXIT_TARGET_INVALID,
                     f"working directory {spec.cwd!r} is not a directory")

    # THE I/O ENDPOINTS ARE OPENED HERE, BY THIS PROCESS, AS THE WORKER.
    #
    # stdin is DEVNULL, never the Director's console. The logical command is a
    # non-interactive `claude -p` turn that reads nothing from stdin, so an
    # inherited interactive handle would be a channel granted for no reason
    # (finding H1). If a future authorized path genuinely needs stdin, it gets a
    # dedicated per-run pipe — never inheritance.
    #
    # stdout/stderr are the exact files the sealed spec names, opened with the
    # same truncating binary mode the previous runner used, so the capture,
    # streaming and stderr-separation semantics are unchanged.
    try:
        with (open(spec.stdout_path, "wb") as out,
              open(spec.stderr_path, "wb") as err):
            # `executable=` is the explicit application path: the image is
            # decided by the sealed spec, NEVER by a PATH search over argv[0].
            # `shell=False` is the default and is passed explicitly so reading
            # this line settles the question.
            completed = subprocess.run(
                list(spec.argv), executable=str(executable), cwd=str(cwd),
                stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                shell=False, check=False)
    except OSError as exc:
        return _fail(EXIT_LAUNCH_FAILED, f"could not start the logical command: {exc}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
