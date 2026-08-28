"""Prove the F-17 Stage-5 launcher suite catches what it claims.

Each mutant restores a real way for the Worker boundary to become decorative: a
same-user fallback, a seal that is not checked, a payload that may sit outside
the trusted root, an identity check skipped, Worker code resumed before it is
verified, a job that does not contain, a Director environment handed over, a
shell or a PATH search in the bootstrap, a transport budget that is not enforced.

SCOPE, STATED HONESTLY. This runs the FAST suite: the directed tests plus the
structural assertions that pin the creation sequence and the job flags. The
end-to-end behaviour those mutants would break — the child really is the Worker
SID, really is Medium, really is contained — is demonstrated separately by
`scripts/probe_stage5_worker_launcher.py`, which creates a real account and a
real job. Mutants marked STRUCTURAL below die on the source-order assertions
rather than on observed behaviour, and that difference is reported rather than
blurred.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/mutation_check_worker_launcher.py [--out PATH]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAUNCHER = "src/gnosis/trust/worker_launcher.py"
SPEC = "src/gnosis/trust/launch_spec.py"
BOOT = "src/gnosis/trust/bootstrap.py"
RUNNER = "src/gnosis/runner/claude_cli_runner.py"
SUITE = ["tests/test_worker_launcher.py", "tests/test_trust_boundary.py",
         "tests/test_cli_runner.py"]


@dataclass(frozen=True)
class Mutant:
    name: str
    description: str
    edits: list[tuple[str, str, str]] = field(default_factory=list)
    structural: bool = False


_NO_FALLBACK = (
    "    if launcher is None:\n"
    "        raise WorkerLaunchFailed(\n"
    '            "no trusted worker launcher is configured; the run fails rather "\n'
    '            "than launching as the Director")'
)
_SEAL_CHECK = (
    "    if actual != expected_digest:\n"
    "        raise LaunchSpecUnsealed("
)
_CANONICAL_CHECK = "    if spec.canonical_bytes() != payload:"
# The token verdict lives in the extracted, unit-testable `verify_worker_token`,
# so these four are BEHAVIOURAL now, not structural: each deletion is caught by
# a test that exercises the decision rather than by reading the source order.
_SID_CHECK = "    if observed.sid != account.expected_sid:"
_INTEGRITY_CHECK = "    if observed.integrity != account.expected_integrity:"
_ADMIN_CHECK = "    if BUILTIN_ADMINISTRATORS_SID in observed.group_sids:"
_DANGEROUS_CHECK = "    if dangerous:"
_JOB_CONTAINED = "        if not contained.value:"
_RESUME_AFTER_CHECKS = (
    "        handles.job = _create_job()\n"
    "        if not _k32.AssignProcessToJobObject(handles.job, handles.process):"
)
_KILL_ON_CLOSE = (
    "    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE"
)
_JOB_TERMINATION = (
    "            _k32.TerminateJobObject(self.job, 1)\n"
    "            _k32.WaitForSingleObject(self.process, 5000)"
)
_BUDGET = "        if len(command) > TRANSPORT_COMMAND_BUDGET:"
# D3 changed the SHAPE of this leak. The launcher no longer builds the whole
# environment, so "the Director's environment becomes the base" is now "the
# allowlist is ignored and every Director variable crosses".
_ENV_BASE = "    for name in sorted(allowlist):"
_ISOLATED = '        [str(runtime), "-I", str(bootstrap_script_path()), str(spec_path), digest])'
_BOOT_EXEC = (
    "                list(spec.argv), executable=str(executable), cwd=str(cwd),\n"
    "                env=child_environment(spec, dict(os.environ)),\n"
    "                stdin=subprocess.DEVNULL, stdout=out, stderr=err,\n"
    "                shell=False, check=False)"
)
_SPEC_PATH_GUARD = (
    "    if not is_storable_launch_id(launch_id):\n"
    "        raise LaunchSpecInvalid("
)
_ABS_PATH_GUARD = "            if not _is_absolute_windows_path(value):"
_DIGEST_SURFACED = "        launch_spec_digest=digest,"
_RUNNER_GUARD = (
    "            from gnosis.trust.worker_launcher import assert_no_same_user_fallback\n"
    "            assert_no_same_user_fallback(launcher)"
)


MUTANTS: list[Mutant] = [
    Mutant("WM1", "an absent launcher silently becomes a same-user launch",
           [(LAUNCHER, _NO_FALLBACK, "    if False:\n        pass")]),
    Mutant("WM2", "the production profile accepts an explicit test fake",
           [(LAUNCHER, '    if getattr(launcher, "is_test_fake", False):', "    if False:")]),
    Mutant("WM3", "the runner stops enforcing the trusted-launch requirement",
           [(RUNNER, _RUNNER_GUARD, "            pass")]),
    Mutant("WM4", "the bootstrap ignores the launch-spec digest",
           [(SPEC, _SEAL_CHECK, "    if False:\n        raise LaunchSpecUnsealed(")]),
    Mutant("WM5", "a re-serialised (non-canonical) payload is accepted",
           [(SPEC, _CANONICAL_CHECK, "    if False:")]),
    Mutant("WM6", "a launch_id may climb out of the trusted launch root",
           [(SPEC, _SPEC_PATH_GUARD,
             "    if False:\n        raise LaunchSpecInvalid(")]),
    Mutant("WM7", "a relative or UNC executable/cwd is accepted",
           [(SPEC, _ABS_PATH_GUARD, "            if False:")]),
    Mutant("WM8", "a NUL in an argument is accepted and silently truncated by the OS",
           [(SPEC, '            if "\\x00" in item:', "            if False:")]),
    Mutant("WM9", "the child's TokenUser SID is not checked",
           [(LAUNCHER, _SID_CHECK, "    if False:")]),
    Mutant("WM10", "an integrity mismatch is ignored",
           [(LAUNCHER, _INTEGRITY_CHECK, "    if False:")]),
    Mutant("WM11", "an administrator worker token is accepted",
           [(LAUNCHER, _ADMIN_CHECK, "    if False:")]),
    Mutant("WM12", "a dangerous privilege in the worker token is accepted",
           [(LAUNCHER, _DANGEROUS_CHECK, "    if False:")]),
    Mutant("WM13", "worker code is resumed BEFORE job containment is established",
           [(LAUNCHER, _RESUME_AFTER_CHECKS,
             ("        _k32.ResumeThread(handles.thread)\n"
              "        handles.job = _create_job()\n"
              "        if not _k32.AssignProcessToJobObject(handles.job, "
              "handles.process):"))], structural=True),
    Mutant("WM14", "a child that is not in the job is resumed anyway",
           [(LAUNCHER, _JOB_CONTAINED, "        if False:")], structural=True),
    Mutant("WM15", "KILL_ON_JOB_CLOSE is removed, so the tree outlives the run",
           [(LAUNCHER, _KILL_ON_CLOSE,
             "    info.BasicLimitInformation.LimitFlags = 0")], structural=True),
    Mutant("WM16", "breakaway is permitted, so a child can leave the job",
           [(LAUNCHER, _KILL_ON_CLOSE,
             ("    info.BasicLimitInformation.LimitFlags = "
              "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | 0x00000800  "
              "# JOB_OBJECT_LIMIT_BREAKAWAY_OK"))], structural=True),
    Mutant("WM17", "timeout kills only the root PID, not the job",
           [(LAUNCHER, _JOB_TERMINATION,
             ("            _k32.TerminateProcess(self.process, 1)\n"
              "            _k32.WaitForSingleObject(self.process, 5000)"))],
           structural=True),
    Mutant("WM18", "the Director's environment becomes the worker's base",
           [(LAUNCHER, _ENV_BASE, "    for name in sorted(director_env):")]),
    Mutant("WM19", "the transport budget is not enforced",
           [(LAUNCHER, _BUDGET, "        if False:")]),
    Mutant("WM20", "the bootstrap interpreter stops being isolated (-I dropped)",
           [(LAUNCHER, _ISOLATED,
             '        [str(runtime), str(bootstrap_script_path()), str(spec_path), digest])')]),
    Mutant("WM21", "the bootstrap PATH-searches argv[0] instead of the sealed image",
           [(BOOT, _BOOT_EXEC,
             ("                list(spec.argv), cwd=str(cwd),\n"
              "                env=child_environment(spec, dict(os.environ)),\n"
              "                stdin=subprocess.DEVNULL, stdout=out, stderr=err,\n"
              "                shell=False, check=False)"))]),
    Mutant("WM22", "the bootstrap runs the logical command through a shell",
           [(BOOT, _BOOT_EXEC,
             ("                list(spec.argv), executable=str(executable), "
              "cwd=str(cwd),\n"
              "                env=child_environment(spec, dict(os.environ)),\n"
              "                stdin=subprocess.DEVNULL, stdout=out, stderr=err,\n"
              "                shell=True, check=False)"))]),
    Mutant("WM23", "the bootstrap inherits the Director's stdin instead of DEVNULL",
           [(BOOT, "                stdin=subprocess.DEVNULL, stdout=out, stderr=err,",
             "                stdout=out, stderr=err,")]),
    Mutant("WM24", "launch_spec_digest is not surfaced for Stage 6 binding",
           [(LAUNCHER, _DIGEST_SURFACED, '        launch_spec_digest="",')]),
    # D3 hardening. These reintroduce the privilege dependency the review
    # rejected: a launcher that calls LoadUserProfileW needs SeBackup+SeRestore,
    # and one that calls CreateProcessWithTokenW needs SeImpersonate. Both are
    # REACHABLE on this machine, which is exactly why neither may be an
    # AUTHORIZED DEPENDENCY.
    Mutant("WM26", "the launcher reintroduces the LoadUserProfileW profile path",
           [(LAUNCHER, "def _winfail(call: str) -> None:",
             ("def _load_user_profile(token: object) -> None:\n"
              "    _userenv.LoadUserProfileW(token, None)\n"
              "\n"
              "\ndef _winfail(call: str) -> None:"))]),
    Mutant("WM27", "the launcher reintroduces LogonUserW",
           [(LAUNCHER, "def _winfail(call: str) -> None:",
             ("def _logon(user: str) -> None:\n"
              "    _a32.LogonUserW(user, None, None, 2, 0, None)\n"
              "\n"
              "\ndef _winfail(call: str) -> None:"))]),
    Mutant("WM28", "the launcher passes an explicit environment block again",
           [(LAUNCHER,
             ("                CREATE_SUSPENDED | CREATE_NO_WINDOW,\n"
              "                None, str(Path(spec.cwd)), ctypes.byref(startup),"),
             ("                CREATE_SUSPENDED | CREATE_NO_WINDOW "
              "| CREATE_UNICODE_ENVIRONMENT,\n"
              "                None, str(Path(spec.cwd)), ctypes.byref(startup),"))]),
    Mutant("WM29", "the sealed overlay is applied AFTER the seal, so it is unsigned",
           [(LAUNCHER,
             ("        spec = replace(spec, environment=tuple(\n"
              "            sorted(build_worker_environment(\n"
              "                self._director_env, self.environment_allowlist).items())))\n"
              "        digest = seal_launch_spec(self.launch_root, spec)"),
             ("        digest = seal_launch_spec(self.launch_root, spec)\n"
              "        spec = replace(spec, environment=tuple(\n"
              "            sorted(build_worker_environment(\n"
              "                self._director_env, "
              "self.environment_allowlist).items())))"))]),
    Mutant("WM30", "a credential-shaped name may ride in the Worker-readable spec",
           [(SPEC, "            if _CREDENTIAL_SHAPED.search(name):", "            if False:")]),
    Mutant("WM31", "LOGON_NETCREDENTIALS_ONLY replaces LOGON_WITH_PROFILE",
           [(LAUNCHER, "                LOGON_WITH_PROFILE, str(self.runtime), buffer,",
             ("                LOGON_NETCREDENTIALS_ONLY, str(self.runtime), "
              "buffer,"))], structural=True),
]


def _pytest() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, "-m", "pytest", *SUITE, "-q", "-x"],
                          cwd=REPO, capture_output=True, text=True, check=False)
    tail = (proc.stdout.strip().splitlines() or [""])[-1][:200]
    return proc.returncode, tail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    lines: list[str] = []

    def say(t: str = "") -> None:
        print(t, flush=True)
        lines.append(t)

    say("MUTATION CHECK — F-17 Stage 5 trusted dedicated-worker launcher")
    say("=" * 74)
    say(f"targeted suite: {' '.join(SUITE)}")
    say("STRUCTURAL mutants die on source-order/flag assertions; the observed")
    say("behaviour they would break is proved by the OS-real probe separately.")
    say("")
    originals = {rel: (REPO / rel).read_text(encoding="utf-8")
                 for rel in {e[0] for m in MUTANTS for e in m.edits}}
    code, tail = _pytest()
    say(f"BASELINE (repair in place): exit={code}  {tail}")
    if code != 0:
        say("ABORTED: baseline not green.")
        if args.out:
            args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1
    say("")
    survived: list[str] = []
    try:
        for m in MUTANTS:
            applied = True
            for rel, old, new in m.edits:
                src = (REPO / rel).read_text(encoding="utf-8")
                if old not in src:
                    applied = False
                    break
                (REPO / rel).write_text(src.replace(old, new, 1), encoding="utf-8",
                                        newline="")
            kind = " [STRUCTURAL]" if m.structural else ""
            if not applied:
                survived.append(f"{m.name} (NOT APPLIED)")
                say(f"{m.name}{kind}: {m.description}\n  verdict: NOT APPLIED")
            else:
                code, tail = _pytest()
                say(f"{m.name}{kind}: {m.description}")
                say(f"  result: exit={code}  {tail}")
                say(f"  verdict: {'CAUGHT' if code != 0 else 'SURVIVED'}")
                if code == 0:
                    survived.append(m.name)
            for rel, text in originals.items():
                (REPO / rel).write_text(text, encoding="utf-8", newline="")
            say("")
    finally:
        for rel, text in originals.items():
            (REPO / rel).write_text(text, encoding="utf-8", newline="")
    code, tail = _pytest()
    say(f"RESTORED: exit={code}  {tail}")
    say(f"mutants: {len(MUTANTS)}  survived/aborted: {len(survived)}"
        + (f"  -> {survived}" if survived else ""))
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if survived or code != 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
