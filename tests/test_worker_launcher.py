"""F-17 Stage 5 — the sealed LaunchSpec, the short transport, and argv fidelity.

The property under test:

    A ~12 kB LOGICAL command crosses a 1024-character transport WITHOUT being
    truncated, split, re-parsed or re-punctuated — and the Worker cannot change
    what that command is.

Everything here runs as the current user. The IDENTITY property (the child's
TokenUser SID is the Worker's) cannot be tested without creating a real Windows
account, so it is deliberately NOT faked here: it is proved by the OS-real probe
`scripts/probe_stage5_worker_launcher.py`, and this file proves the properties
that are independent of identity. Splitting them that way keeps each test honest
about what it actually demonstrates.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from gnosis.trust.launch import AuthorityUnavailable
from gnosis.trust.launch_spec import (
    MAX_LAUNCH_SPEC_BYTES,
    OVERLAY_ALLOWED_NAMES,
    LaunchSpec,
    LaunchSpecInvalid,
    LaunchSpecUnsealed,
    child_environment,
    credential_shaped,
    launch_spec_path,
    read_sealed_launch_spec,
    seal_launch_spec,
)
from gnosis.trust.worker_launcher import (
    DANGEROUS_PRIVILEGES,
    DEFAULT_ENVIRONMENT_ALLOWLIST,
    LOGON_COMMAND_LINE_LIMIT,
    TRANSPORT_COMMAND_BUDGET,
    LaunchedWorkerIdentity,
    ObservedToken,
    WorkerAccount,
    WorkerIdentityMismatch,
    WorkerLaunchFailed,
    assert_no_same_user_fallback,
    bootstrap_script_path,
    build_transport_command,
    build_worker_environment,
    summarise_launch,
    verify_worker_token,
)

# The measured worst case from Stage 5's Gate 1: the engine's default path is a
# 12000-character code-intelligence context block prepended to the task prompt.
ENGINE_DEFAULT_PROMPT = "X" * 12000 + "\n\n---\n\nimplement the thing"

ARGV_EDGE_CASES = [
    "plain",
    "with space",
    'has "quotes"',
    "back\\slash",
    "trailing\\\\",
    "",                                   # an empty argument
    "unicode-\u00e1\u00e9\u4e2d\u6587\u00f1",
    "tab\there",
    "semi;colon&amp|pipe>redirect<",      # shell metacharacters
    "%NOT_EXPANDED%",                     # cmd would expand this
    "$notexpanded",                       # a shell would expand this
    "trailing space ",
    'mixed"\\quote\\\\',
    ENGINE_DEFAULT_PROMPT,                # the real 12 kB payload
]


def _spec(tmp: Path, **overrides: object) -> LaunchSpec:
    base: dict[str, object] = {
        "launch_id": "probe-0001",
        "executable": sys.executable,
        "argv": (sys.executable, "-c", "pass"),
        "cwd": str(tmp),
        "stdout_path": str(tmp / "out.txt"),
        "stderr_path": str(tmp / "err.txt"),
        "run_id": None,
    }
    base.update(overrides)
    return LaunchSpec(**base)  # type: ignore[arg-type]


class _TmpCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "launch"
        self.root.mkdir()


# ---------------------------------------------------------------------------
class TestTheLaunchSpecContract(_TmpCase):
    def test_a_spec_round_trips_through_its_dict(self):
        spec = _spec(self.tmp, argv=tuple(ARGV_EDGE_CASES))
        self.assertEqual(LaunchSpec.from_dict(spec.to_dict()), spec)

    def test_the_launch_id_must_be_a_storable_name(self):
        for bad in ("", "..", "../escape", "a/b", "a\\b", "C:evil", ".hidden",
                    "x" * 65, "has space"):
            with self.assertRaises(LaunchSpecInvalid, msg=bad):
                _spec(self.tmp, launch_id=bad)

    def test_paths_must_be_absolute_and_drive_qualified(self):
        for field in ("executable", "cwd", "stdout_path", "stderr_path"):
            for bad in ("relative\\path", "\\rooted-but-driveless", "",
                        "\\\\server\\share\\file"):
                with self.assertRaises(LaunchSpecInvalid, msg=f"{field}={bad}"):
                    _spec(self.tmp, **{field: bad})

    def test_a_unc_path_is_refused_because_it_resolves_off_this_machine(self):
        with self.assertRaises(LaunchSpecInvalid):
            _spec(self.tmp, executable="\\\\attacker\\share\\evil.exe")

    def test_argv_must_be_a_non_empty_vector_of_strings(self):
        for bad in ((), ("ok", 5), ("ok", None)):
            with self.assertRaises(LaunchSpecInvalid, msg=repr(bad)):
                _spec(self.tmp, argv=bad)

    def test_a_nul_in_an_argument_is_refused_rather_than_truncated(self):
        """A NUL terminates a Windows command line, so an argument carrying one
        would be SILENTLY TRUNCATED by the OS — the exact thing this stage
        refuses to do."""
        with self.assertRaises(LaunchSpecInvalid):
            _spec(self.tmp, argv=(sys.executable, "-c", "pass\x00hidden"))

    def test_unknown_and_missing_fields_are_refused(self):
        good = _spec(self.tmp).to_dict()
        with self.assertRaises(LaunchSpecInvalid):
            LaunchSpec.from_dict({**good, "extra": 1})
        for drop in ("schema", "launch_id", "executable", "argv", "cwd",
                     "stdout_path", "stderr_path"):
            data = dict(good)
            del data[drop]
            with self.assertRaises(LaunchSpecInvalid, msg=drop):
                LaunchSpec.from_dict(data)

    def test_an_unknown_schema_is_refused(self):
        with self.assertRaises(LaunchSpecInvalid):
            _spec(self.tmp, schema="gnosis.trust.launch_spec.v99")

    def test_the_logical_command_digest_depends_only_on_argv(self):
        """It is what provenance and replay bind to, so it must be unchanged by
        the transport that carried the command."""
        first = _spec(self.tmp, launch_id="a", run_id=None)
        second = _spec(self.tmp, launch_id="b", run_id="RUN-1")
        self.assertNotEqual(first.digest(), second.digest())
        self.assertEqual(first.logical_command_digest, second.logical_command_digest)
        third = _spec(self.tmp, argv=(sys.executable, "-c", "other"))
        self.assertNotEqual(first.logical_command_digest, third.logical_command_digest)


class TestTheSeal(_TmpCase):
    def test_sealing_returns_the_digest_of_what_is_on_disk(self):
        spec = _spec(self.tmp, argv=tuple(ARGV_EDGE_CASES))
        digest = seal_launch_spec(self.root, spec)
        self.assertEqual(digest, spec.digest())
        back = read_sealed_launch_spec(launch_spec_path(self.root, spec.launch_id),
                                       expected_digest=digest)
        self.assertEqual(back, spec)
        self.assertEqual(list(back.argv), ARGV_EDGE_CASES)

    def test_a_tampered_payload_is_refused(self):
        """THE attack the seal exists for: something rewrites the argv between
        the Director sealing it and the bootstrap reading it."""
        spec = _spec(self.tmp)
        digest = seal_launch_spec(self.root, spec)
        path = launch_spec_path(self.root, spec.launch_id)
        evil = json.loads(path.read_text(encoding="utf-8"))
        evil["argv"] = [sys.executable, "-c", "print('pwned')"]
        path.write_bytes(json.dumps(evil).encode("utf-8"))
        with self.assertRaises(LaunchSpecUnsealed):
            read_sealed_launch_spec(path, expected_digest=digest)

    def test_a_wrong_expected_digest_is_refused(self):
        spec = _spec(self.tmp)
        seal_launch_spec(self.root, spec)
        with self.assertRaises(LaunchSpecUnsealed):
            read_sealed_launch_spec(launch_spec_path(self.root, spec.launch_id),
                                    expected_digest="f" * 64)

    def test_a_malformed_expected_digest_is_refused_before_any_read(self):
        for bad in ("", "nope", "A" * 64, "a" * 63, None, 5):
            with self.assertRaises(LaunchSpecInvalid, msg=repr(bad)):
                read_sealed_launch_spec(self.root / "absent.json",
                                        expected_digest=bad)  # type: ignore[arg-type]

    def test_a_re_serialised_payload_is_refused_even_when_it_means_the_same(self):
        """The digest matches but the bytes are not canonical: something
        rewrote the file after it was sealed, and that is not a launch this
        process was told to perform."""
        spec = _spec(self.tmp)
        digest = seal_launch_spec(self.root, spec)
        path = launch_spec_path(self.root, spec.launch_id)
        path.write_bytes(json.dumps(spec.to_dict(), indent=2).encode("utf-8"))
        with self.assertRaises(LaunchSpecUnsealed):
            read_sealed_launch_spec(path, expected_digest=digest)

    def test_a_missing_payload_fails_closed(self):
        with self.assertRaises(LaunchSpecUnsealed):
            read_sealed_launch_spec(self.root / "absent.json",
                                    expected_digest="a" * 64)

    def test_an_oversize_payload_is_refused_by_the_bound(self):
        spec = _spec(self.tmp)
        digest = seal_launch_spec(self.root, spec)
        path = launch_spec_path(self.root, spec.launch_id)
        path.write_bytes(b"x" * (MAX_LAUNCH_SPEC_BYTES + 1))
        with self.assertRaises(LaunchSpecInvalid):
            read_sealed_launch_spec(path, expected_digest=digest)

    def test_a_launch_id_cannot_climb_out_of_the_launch_root(self):
        for bad in ("../../evil", "..\\evil", "C:\\evil"):
            with self.assertRaises(LaunchSpecInvalid, msg=bad):
                launch_spec_path(self.root, bad)


class TestTheTransportIsShort(_TmpCase):
    def test_the_real_worst_case_logical_argv_fits_in_a_short_transport(self):
        """Gate 1's blocker, resolved and measured rather than asserted."""
        argv = (sys.executable, "-p", ENGINE_DEFAULT_PROMPT, "--output-format", "json")
        spec = _spec(self.tmp, argv=argv)
        digest = seal_launch_spec(self.root, spec)
        logical = len(subprocess.list2cmdline(list(argv)))
        transport = build_transport_command(
            Path(sys.executable), launch_spec_path(self.root, spec.launch_id), digest)
        self.assertGreater(logical, LOGON_COMMAND_LINE_LIMIT * 10)
        self.assertLessEqual(len(transport), TRANSPORT_COMMAND_BUDGET)
        self.assertLess(len(transport), LOGON_COMMAND_LINE_LIMIT)

    def test_the_budget_leaves_real_headroom_under_the_hard_cap(self):
        """A design that fits in 1023 characters fails the first time a path
        gets longer. The budget is half the cap, on purpose."""
        self.assertLessEqual(TRANSPORT_COMMAND_BUDGET, LOGON_COMMAND_LINE_LIMIT // 2)

    def test_the_transport_never_carries_the_payload(self):
        argv = (sys.executable, "-p", ENGINE_DEFAULT_PROMPT)
        spec = _spec(self.tmp, argv=argv)
        digest = seal_launch_spec(self.root, spec)
        transport = build_transport_command(
            Path(sys.executable), launch_spec_path(self.root, spec.launch_id), digest)
        self.assertNotIn("X" * 100, transport)
        self.assertIn("-I", transport)          # the interpreter is isolated
        self.assertIn(digest, transport)        # the seal travels on the command line


class TestArgvFidelityThroughTheBootstrap(_TmpCase):
    """The bootstrap is executed for real. Identity is a separate property and
    is not claimed here: this proves the argv vector survives the transport."""

    def _echo(self) -> Path:
        echo = self.tmp / "argv_echo.py"
        echo.write_text(
            "import json, sys\n"
            "with open(sys.argv[1], 'w', encoding='utf-8') as fh:\n"
            "    json.dump(sys.argv[2:], fh)\n", encoding="utf-8")
        return echo

    def test_every_argv_edge_case_round_trips_exactly(self):
        dump = self.tmp / "argv.json"
        argv = (sys.executable, str(self._echo()), str(dump), *ARGV_EDGE_CASES)
        spec = _spec(self.tmp, argv=argv)
        digest = seal_launch_spec(self.root, spec)
        proc = subprocess.run(
            [sys.executable, "-I", str(bootstrap_script_path()),
             str(launch_spec_path(self.root, spec.launch_id)), digest],
            capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(dump.read_text(encoding="utf-8")),
                         ARGV_EDGE_CASES)

    def test_the_bootstrap_refuses_a_tampered_spec_with_a_distinct_exit_code(self):
        spec = _spec(self.tmp)
        digest = seal_launch_spec(self.root, spec)
        path = launch_spec_path(self.root, spec.launch_id)
        evil = json.loads(path.read_text(encoding="utf-8"))
        evil["argv"] = [sys.executable, "-c", "print('pwned')"]
        path.write_bytes(json.dumps(evil).encode("utf-8"))
        proc = subprocess.run(
            [sys.executable, "-I", str(bootstrap_script_path()), str(path), digest],
            capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 121)   # EXIT_SEAL_FAILED
        self.assertIn("refusing to launch", proc.stderr)

    def test_the_bootstrap_writes_the_named_output_files(self):
        script = self.tmp / "noisy.py"
        script.write_text("import sys\nprint('to-out')\nprint('to-err', "
                          "file=sys.stderr)\nsys.exit(7)\n", encoding="utf-8")
        spec = _spec(self.tmp, argv=(sys.executable, str(script)))
        digest = seal_launch_spec(self.root, spec)
        proc = subprocess.run(
            [sys.executable, "-I", str(bootstrap_script_path()),
             str(launch_spec_path(self.root, spec.launch_id)), digest],
            capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 7, "the exit code must be propagated")
        self.assertIn("to-out", (self.tmp / "out.txt").read_text(encoding="utf-8"))
        self.assertIn("to-err", (self.tmp / "err.txt").read_text(encoding="utf-8"))

    def test_the_logical_command_never_inherits_the_callers_stdin(self):
        """WM23's target, finding H1's repair, tested for real: data written to
        the bootstrap's own stdin must NOT reach the logical command."""
        script = self.tmp / "read_stdin.py"
        script.write_text(
            "import sys\n"
            "with open(sys.argv[1], 'w', encoding='utf-8') as fh:\n"
            "    fh.write(repr(sys.stdin.read()))\n", encoding="utf-8")
        seen = self.tmp / "seen.txt"
        spec = _spec(self.tmp, argv=(sys.executable, str(script), str(seen)))
        digest = seal_launch_spec(self.root, spec)
        proc = subprocess.run(
            [sys.executable, "-I", str(bootstrap_script_path()),
             str(launch_spec_path(self.root, spec.launch_id)), digest],
            input=b"SECRET-FROM-THE-DIRECTOR-STDIN", capture_output=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(seen.read_text(encoding="utf-8"), "''",
                         "the logical command read the caller's stdin")

    def test_the_bootstrap_does_not_expand_shell_syntax(self):
        """No shell anywhere: `%VAR%` and `$VAR` must arrive as literals."""
        dump = self.tmp / "argv.json"
        cases = ["%USERNAME%", "$USERNAME", "`whoami`", "$(whoami)", "a&b", "a|b"]
        argv = (sys.executable, str(self._echo()), str(dump), *cases)
        spec = _spec(self.tmp, argv=argv)
        digest = seal_launch_spec(self.root, spec)
        subprocess.run(
            [sys.executable, "-I", str(bootstrap_script_path()),
             str(launch_spec_path(self.root, spec.launch_id)), digest],
            capture_output=True, text=True, check=False)
        self.assertEqual(json.loads(dump.read_text(encoding="utf-8")), cases)


class TestTheEnvironmentAllowlist(unittest.TestCase):
    def test_the_director_environment_never_crosses_wholesale(self):
        """Finding E1, repaired. The Director contributes ONLY named variables.
        The Worker's real environment is built by Windows from the Worker's own
        profile and never passes through here at all (D3 hardening)."""
        director = {"CLAUDE_CODE_MESSAGING_TOKEN": "secret",
                    "ANTHROPIC_API_KEY": "secret", "GNOSIS_SENTINEL": "secret",
                    "PYTHONUTF8": "1", "USERPROFILE": r"C:\Users\Director"}
        env = build_worker_environment(director)
        self.assertEqual(env, {"PYTHONUTF8": "1"})
        for leaked in ("CLAUDE_CODE_MESSAGING_TOKEN", "ANTHROPIC_API_KEY",
                       "GNOSIS_SENTINEL", "USERPROFILE"):
            self.assertNotIn(leaked, env)

    def test_only_names_in_the_closed_overlay_set_can_cross(self):
        """Even a caller that widens its OWN allowlist cannot smuggle a name
        past the spec's closed overlay set."""
        env = build_worker_environment({"A": "1", "PYTHONUTF8": "2"},
                                       allowlist=frozenset({"A", "PYTHONUTF8"}))
        self.assertEqual(env, {"PYTHONUTF8": "2"})

    def test_an_empty_director_value_does_not_cross(self):
        """An empty variable is unset for every consumer, so carrying one over
        would be the ambient fallback wearing an allowlist's clothes."""
        env = build_worker_environment({"PYTHONUTF8": ""})
        self.assertNotIn("PYTHONUTF8", env)

    def test_the_sealed_overlay_refuses_a_credential_shaped_name(self):
        """The LaunchSpec is Worker-READABLE, so a credential in it is a
        credential handed to the Worker. Refused by construction."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            for bad in ("ANTHROPIC_API_KEY", "CLAUDE_TOKEN", "MY_SECRET",
                        "DB_PASSWORD", "OAUTH_BEARER", "SESSION_ID",
                        "PRIVATE_THING", "SOME_CREDENTIAL"):
                with self.assertRaises(LaunchSpecInvalid, msg=bad):
                    _spec(Path(tmp), environment=((bad, "x"),))

    def test_the_sealed_overlay_is_bounded_and_well_formed(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            _spec(root, environment=(("PYTHONUTF8", "1"),))      # must not raise
            for bad in (
                tuple((f"VAR{i}", "1") for i in range(17)),       # over the bound
                (("bad name", "1"),),                            # unsafe name
                (("VAR", "with\x00nul"),),                       # NUL in a value
                (("VAR", "x" * 1025),),                          # over-long value
                (("VAR", "1"), ("VAR", "2")),                    # duplicate name
            ):
                with self.assertRaises(LaunchSpecInvalid, msg=repr(bad)[:40]):
                    _spec(root, environment=bad)

    def test_the_sealed_overlay_may_not_reintroduce_a_dangerous_variable(self):
        """The closed set is the security model. A name the base policy drops
        cannot come back in through the overlay."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            for bad in ("NODE_OPTIONS", "NODE_PATH", "PYTHONPATH", "PYTHONHOME",
                        "PYTHONSTARTUP", "GIT_CONFIG_GLOBAL", "GIT_TEMPLATE_DIR",
                        "SSL_CERT_FILE", "SSLKEYLOGFILE", "HTTPS_PROXY",
                        "NO_PROXY", "USERPROFILE", "ANYTHING_ELSE"):
                with self.assertRaises(LaunchSpecInvalid, msg=bad):
                    _spec(Path(tmp), environment=((bad, "x"),))

    def test_a_sealed_path_entry_must_be_absolute(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            _spec(Path(tmp), environment=(("PATH", r"C:\tools;C:\more"),))
            for bad in (r"C:\ok;relative\bad", r"\\server\share", "notapath"):
                with self.assertRaises(LaunchSpecInvalid, msg=bad):
                    _spec(Path(tmp), environment=(("PATH", bad),))


class TestTheClosedChildEnvironmentPolicy(unittest.TestCase):
    """The FINAL blocking finding, repaired.

    The bootstrap's own environment no longer comes from the Director — but it
    comes from the WORKER'S PROFILE, and under T2 the Worker is compromised. A
    previous run can persist variables into `HKCU\\Environment` that Windows
    faithfully rebuilds for the next run. Forwarding `os.environ` would carry
    all of it into the logical command.

    The rule is UNKNOWN VARIABLE == DENIED.
    """

    ROOT = r"C:\Users\Worker"
    SYS = r"C:\Windows"

    POISON: ClassVar[dict[str, str]] = {
        "NODE_OPTIONS": "--require C:/worker/evil.js",
        "NODE_PATH": r"C:\worker\modules",
        "PYTHONPATH": r"C:\worker\py",
        "PYTHONHOME": r"C:\worker\py",
        "PYTHONSTARTUP": r"C:\worker\startup.py",
        "GIT_CONFIG": r"C:\worker\gitconfig",
        "GIT_CONFIG_GLOBAL": r"C:\worker\gitconfig",
        "GIT_CONFIG_SYSTEM": r"C:\worker\gitconfig",
        "GIT_TEMPLATE_DIR": r"C:\worker\templates",
        "SSL_CERT_FILE": r"C:\worker\ca.pem",
        "SSL_CERT_DIR": r"C:\worker\ca",
        "SSLKEYLOGFILE": r"C:\worker\keys.log",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "ALL_PROXY": "http://127.0.0.1:9",
        "NO_PROXY": "",
        "CLAUDE_CODE_MESSAGING_TOKEN": "stolen",
        "CLAUDE_CODE_SESSION_ID": "stolen",
        "ANTHROPIC_API_KEY": "stolen",
        "OPENAI_API_KEY": "stolen",
        "CODEX_HOME": r"C:\worker\codex",
        "GNOSIS_ARBITRARY_SENTINEL": "planted-by-a-previous-run",
    }

    def _build(self, **extra: str) -> dict[str, str]:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            spec = _spec(Path(tmp), environment=(("PYTHONUTF8", "1"),))
        own = {
            "USERPROFILE": self.ROOT,
            "APPDATA": self.ROOT + r"\AppData\Roaming",
            "LOCALAPPDATA": self.ROOT + r"\AppData\Local",
            "TEMP": self.ROOT + r"\AppData\Local\Temp",
            "TMP": self.ROOT + r"\AppData\Local\Temp",
            "USERNAME": "Worker",
            "NUMBER_OF_PROCESSORS": "8",
            "PATH": r"C:\worker\bin;C:\Windows\system32",
            **self.POISON, **extra,
        }
        return child_environment(spec, own, profile_root=self.ROOT,
                                 system_root=self.SYS)

    def test_every_poisoned_variable_is_absent(self):
        env = self._build()
        for name in self.POISON:
            self.assertNotIn(name, env, f"{name} survived the allowlist")

    def test_the_result_is_exactly_the_policy(self):
        env = self._build()
        self.assertEqual(sorted(env), sorted([
            "APPDATA", "COMSPEC", "LOCALAPPDATA", "NUMBER_OF_PROCESSORS", "PATH",
            "PATHEXT", "PYTHONUTF8", "SystemDrive", "SystemRoot", "TEMP", "TMP",
            "USERNAME", "USERPROFILE", "windir"]))

    def test_path_is_built_not_inherited(self):
        env = self._build()
        self.assertNotIn(r"C:\worker\bin", env["PATH"])
        self.assertIn(r"C:\Windows\system32", env["PATH"])

    def test_a_sealed_path_is_prepended_to_the_system_path(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            spec = _spec(Path(tmp), environment=(("PATH", r"C:\trusted\tools"),))
        env = child_environment(spec, {"PATH": r"C:\worker\bin"},
                                profile_root=self.ROOT, system_root=self.SYS)
        self.assertTrue(env["PATH"].startswith(r"C:\trusted\tools;"))
        self.assertNotIn(r"C:\worker\bin", env["PATH"])

    def test_os_facts_are_never_taken_from_the_environment(self):
        env = self._build(SystemRoot=r"C:\worker\fakewindows",
                          windir=r"C:\worker\fakewindows",
                          COMSPEC=r"C:\worker\evil.exe",
                          PATHEXT=".EVIL")
        self.assertEqual(env["SystemRoot"], self.SYS)
        self.assertEqual(env["windir"], self.SYS)
        self.assertEqual(env["COMSPEC"], self.SYS + r"\system32\cmd.exe")
        self.assertNotIn(".EVIL", env["PATHEXT"])

    def test_a_profile_path_pointing_outside_the_profile_is_dropped(self):
        """Redirection, not correction: a USERPROFILE the Worker moved is not
        silently repaired into something plausible, it is simply not passed."""
        for redirected in (r"C:\worker\elsewhere", r"C:\Users\Worker2",
                           r"C:\Users", r"\\server\share", "relative"):
            env = self._build(USERPROFILE=redirected)
            self.assertNotIn("USERPROFILE", env, redirected)

    def test_a_sibling_prefix_is_not_inside_the_profile(self):
        """`C:\\Users\\Worker2` starts with `C:\\Users\\Worker` as a STRING and
        is a different profile, so the comparison is component-wise."""
        env = self._build(APPDATA=r"C:\Users\Worker2\AppData\Roaming")
        self.assertNotIn("APPDATA", env)

    def test_a_genuine_profile_path_survives(self):
        env = self._build()
        self.assertEqual(env["USERPROFILE"], self.ROOT)
        self.assertEqual(env["APPDATA"], self.ROOT + r"\AppData\Roaming")

    def test_case_and_separator_differences_do_not_defeat_the_check(self):
        env = self._build(USERPROFILE=r"c:/users/worker/")
        self.assertIn("USERPROFILE", env)

    def test_the_sealed_overlay_still_applies_last(self):
        env = self._build()
        self.assertEqual(env["PYTHONUTF8"], "1")

    def test_the_default_allowlist_carries_no_credential_shaped_name(self):
        for name in DEFAULT_ENVIRONMENT_ALLOWLIST:
            self.assertNotRegex(name, r"(?i)(KEY|TOKEN|SECRET|PASS|CRED|AUTH|SESSION)")

    def test_the_overlay_policy_itself_carries_no_credential_shaped_name(self):
        """DEFENCE IN DEPTH THAT GUARDS THE POLICY, NOT EACH VALUE.

        A per-value credential check would be unreachable — the closed set
        rejects every unlisted name before any value is examined — and an
        unreachable check is the RM13 defect this project has already paid for
        once. A mutation run proved it: with the closed set in place, deleting
        the per-value check changed nothing. So the guard was moved onto the SET,
        where it is live: it fires the moment someone widens the policy.
        """
        self.assertEqual(credential_shaped(OVERLAY_ALLOWED_NAMES), [])
        self.assertEqual(
            credential_shaped(frozenset({"PYTHONUTF8", "CLAUDE_SESSION_TOKEN"})),
            ["CLAUDE_SESSION_TOKEN"])


class TestTheLauncherDependsOnNoExtraPrivilege(unittest.TestCase):
    """D3, the blocking finding, ENFORCED rather than promised.

    REACHABLE != AUTHORIZED DEPENDENCY. The launcher must not call the APIs that
    would make `SeBackupPrivilege` / `SeRestorePrivilege` (`LoadUserProfileW`) or
    `SeImpersonatePrivilege` (`CreateProcessWithTokenW`) a requirement — even
    though an elevated Director happens to hold all three. A future edit that
    reintroduces one has to delete this test to do it.
    """

    SOURCES = (REPO / "src" / "gnosis" / "trust" / "worker_launcher.py",
               REPO / "src" / "gnosis" / "trust" / "bootstrap.py",
               REPO / "src" / "gnosis" / "trust" / "launch_spec.py")

    FORBIDDEN = ("LoadUserProfileW", "UnloadUserProfile", "LogonUserW",
                 "CreateEnvironmentBlock", "CreateProcessWithTokenW",
                 "CreateProcessAsUserW", "AdjustTokenPrivileges")

    def test_no_privilege_requiring_api_is_called(self):
        for source in self.SOURCES:
            tree = ast.parse(source.read_text(encoding="utf-8"))
            used = {node.attr for node in ast.walk(tree)
                    if isinstance(node, ast.Attribute)}
            used |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            used |= {node.value for node in ast.walk(tree)
                     if isinstance(node, ast.Constant) and isinstance(node.value, str)}
            for name in self.FORBIDDEN:
                self.assertNotIn(name, used,
                                 f"{source.name} calls {name}, reintroducing a "
                                 "privilege dependency this stage removed")

    def test_the_userenv_library_is_not_loaded_at_all(self):
        tree = ast.parse(self.SOURCES[0].read_text(encoding="utf-8"))
        loaded = {node.value for node in ast.walk(tree)
                  if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        self.assertNotIn("userenv", loaded,
                         "userenv.dll is only needed for the profile APIs removed here")

    def test_the_process_environment_is_passed_as_null(self):
        """The measurement that removed the dependency: LOGON_WITH_PROFILE with
        a NULL lpEnvironment already yields the WORKER's profile environment."""
        text = self.SOURCES[0].read_text(encoding="utf-8")
        self.assertIn("CREATE_SUSPENDED | CREATE_NO_WINDOW,", text)
        self.assertNotIn("CREATE_UNICODE_ENVIRONMENT", text,
                         "a unicode environment flag implies an environment block")

    def test_the_sealed_overlay_is_applied_before_the_seal(self):
        """If the overlay were added after sealing, the digest would not cover
        it and the Worker could edit the one part of its environment the
        Director insisted on."""
        tree = ast.parse(self.SOURCES[0].read_text(encoding="utf-8"))
        body = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "launch":
                body = ast.unparse(node)
        self.assertIn("build_worker_environment", body)
        self.assertLess(body.index("build_worker_environment"),
                        body.index("seal_launch_spec"))


class TestNoSameUserFallback(unittest.TestCase):
    def test_an_absent_launcher_fails_the_run(self):
        with self.assertRaises(WorkerLaunchFailed):
            assert_no_same_user_fallback(None)

    def test_a_test_fake_may_never_be_selected_in_production(self):
        class _Fake:
            is_test_fake = True

        with self.assertRaises(WorkerLaunchFailed):
            assert_no_same_user_fallback(_Fake())

    def test_a_real_launcher_is_accepted(self):
        class _Real:
            pass

        assert_no_same_user_fallback(_Real())   # must not raise

    def test_no_module_in_the_launch_path_falls_back_to_popen(self):
        """A structural check, because this is the one failure mode that would
        look like success: a launcher that catches its own failure and runs the
        command as the Director has crossed no boundary at all."""
        for name in ("worker_launcher.py", "launch_spec.py"):
            source = (REPO / "src" / "gnosis" / "trust" / name).read_text(
                encoding="utf-8")
            tree = ast.parse(source)
            calls = [node for node in ast.walk(tree)
                     if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Attribute)
                     and node.func.attr in {"Popen", "run", "call", "check_output"}
                     and isinstance(node.func.value, ast.Name)
                     and node.func.value.id == "subprocess"]
            self.assertEqual(calls, [], f"{name} shells out on the launch path")


class TestTheBootstrapIsMinimalAndStatic(unittest.TestCase):
    SOURCE = REPO / "src" / "gnosis" / "trust" / "bootstrap.py"

    def test_it_uses_no_shell_and_no_path_search(self):
        source = self.SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"run", "Popen", "call"}):
                    kwargs = {kw.arg for kw in node.keywords}
                    self.assertIn("executable", kwargs,
                                  "the image must be explicit, never a PATH search")
                    shell = [kw for kw in node.keywords if kw.arg == "shell"]
                    self.assertTrue(shell and shell[0].value.value is False,
                                    "shell=False must be explicit")
        # Scan the CODE's string literals, not the prose. The docstring above
        # names `powershell` precisely in order to forbid it, and a scan that
        # cannot tell a prohibition from a use is a check that fails on its own
        # documentation.
        docstrings = {ast.get_docstring(node, clean=False)
                      for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.FunctionDef,
                                           ast.AsyncFunctionDef, ast.ClassDef))}
        literals = [node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value not in docstrings]
        for text in literals:
            for forbidden in ("cmd.exe", "cmd /c", "powershell", "os.system", "/bin/sh"):
                self.assertNotIn(forbidden, text.lower(),
                                 f"bootstrap code literal reaches for {forbidden}")

    def test_it_reads_no_configuration_from_the_environment(self):
        """FORWARDING the environment is not READING configuration from it.

        The bootstrap passes `dict(os.environ)` — its own Worker-profile
        environment — through to the logical command, which is the whole point
        of the D3 design. What it must never do is take a DECISION from a
        variable: no `os.environ[...]`, no `.get(...)`, no `getenv`. An earlier
        version of this test forbade the name `environ` outright and failed the
        moment the forwarding was added, which would have been the wrong lesson.
        """
        tree = ast.parse(self.SOURCE.read_text(encoding="utf-8"))
        names = {node.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Attribute)}
        names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        for forbidden in ("getenv", "eval", "exec", "compile", "import_module",
                          "__import__"):
            self.assertNotIn(forbidden, names, f"bootstrap reaches for {forbidden}")

        def _is_environ(node: ast.AST) -> bool:
            return isinstance(node, ast.Attribute) and node.attr == "environ"

        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and _is_environ(node.value):
                self.fail("bootstrap indexes os.environ for configuration")
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"get", "setdefault", "pop"}
                    and _is_environ(node.func.value)):
                self.fail(f"bootstrap reads os.environ.{node.func.attr} "
                          "for configuration")

    def test_its_module_closure_stays_small(self):
        """The bootstrap's TCB is its runtime plus its imports. It must not
        acquire the engine, the runner, or anything that drags them in."""
        probe = (
            "import json, sys\n"
            f"sys.path.insert(0, r'{REPO / 'src'}')\n"
            "import gnosis.trust.bootstrap\n"
            "print(json.dumps(sorted(m for m in sys.modules "
            "if m == 'gnosis' or m.startswith('gnosis.'))))\n")
        out = subprocess.run([sys.executable, "-I", "-c", probe],
                             capture_output=True, text=True, check=True, cwd=str(REPO))
        closure = json.loads(out.stdout)
        self.assertEqual(closure, [
            "gnosis", "gnosis.kernel", "gnosis.kernel.atomic_io",
            "gnosis.kernel.canonical", "gnosis.trust", "gnosis.trust.bootstrap",
            "gnosis.trust.launch", "gnosis.trust.launch_spec"])


class TestTheTokenVerdict(unittest.TestCase):
    """Every refusal that decides whether Worker code may run, as a unit test.

    Extracted from the ctypes flow on purpose: a check that can only be reached
    by creating a real Windows account is a check no fast test can defend, and
    a mutation removing it would survive everything but an OS-real probe run.
    The probe still proves the OBSERVED values are real; this proves the
    DECISION over them is right.
    """

    ACCOUNT = WorkerAccount(username="W", domain=".",
                            expected_sid="S-1-5-21-1-2-3-1001",
                            expected_integrity="Medium")

    def _token(self, **overrides: object) -> ObservedToken:
        base: dict[str, object] = {"sid": "S-1-5-21-1-2-3-1001", "integrity": "Medium",
                                   "group_sids": ("S-1-5-32-545",), "privileges":
                                   ("SeChangeNotifyPrivilege",)}
        base.update(overrides)
        return ObservedToken(**base)  # type: ignore[arg-type]

    def test_the_authorized_worker_is_accepted(self):
        self.assertEqual(verify_worker_token(self._token(), self.ACCOUNT), ())

    def test_a_different_sid_is_refused(self):
        with self.assertRaises(WorkerIdentityMismatch):
            verify_worker_token(self._token(sid="S-1-5-21-9-9-9-9999"), self.ACCOUNT)

    def test_a_wrong_integrity_is_refused(self):
        for bad in ("High", "Low", "System"):
            with self.assertRaises(WorkerIdentityMismatch, msg=bad):
                verify_worker_token(self._token(integrity=bad), self.ACCOUNT)

    def test_an_administrator_token_is_refused(self):
        with self.assertRaises(WorkerIdentityMismatch) as ctx:
            verify_worker_token(
                self._token(group_sids=("S-1-5-32-545", "S-1-5-32-544")), self.ACCOUNT)
        self.assertIn("Administrators", str(ctx.exception))

    def test_every_dangerous_privilege_is_refused_one_at_a_time(self):
        """A non-admin account is not enough: privileges are granted
        independently of group membership."""
        for privilege in sorted(DANGEROUS_PRIVILEGES):
            with self.assertRaises(WorkerIdentityMismatch, msg=privilege):
                verify_worker_token(
                    self._token(privileges=("SeChangeNotifyPrivilege", privilege)),
                    self.ACCOUNT)

    def test_a_harmless_privilege_is_allowed(self):
        verify_worker_token(
            self._token(privileges=("SeChangeNotifyPrivilege",
                                    "SeIncreaseWorkingSetPrivilege")), self.ACCOUNT)


class TestTheRunnerRefusesToDegrade(unittest.TestCase):
    def test_requiring_a_trusted_launch_without_one_fails_the_run(self):
        """WM3's target. The runner must refuse BEFORE anything is spawned,
        not catch a failure and continue as the Director."""
        from gnosis.runner.claude_cli_runner import CLIRunner

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            with self.assertRaises(WorkerLaunchFailed):
                CLIRunner().run(
                    [sys.executable, "-c", "open('leaked.txt','w').write('x')"],
                    cwd=root, stdout_path=root / "o.txt", stderr_path=root / "e.txt",
                    timeout_s=30.0, require_trusted_launch=True, launcher=None)
            self.assertFalse((root / "leaked.txt").exists(),
                             "the command must not have run at all")

    def test_a_test_fake_is_refused_in_the_required_profile(self):
        from gnosis.runner.claude_cli_runner import CLIRunner

        class _Fake:
            is_test_fake = True

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            with self.assertRaises(WorkerLaunchFailed):
                CLIRunner().run([sys.executable, "-c", "pass"], cwd=root,
                                stdout_path=root / "o.txt", stderr_path=root / "e.txt",
                                timeout_s=30.0, require_trusted_launch=True,
                                launcher=_Fake())

    def test_the_logical_command_is_what_execution_records(self):
        """Provenance: `command` keeps its historical meaning, and the transport
        is recorded separately rather than merged into it."""
        identity = LaunchedWorkerIdentity(
            pid=1, observed_sid="S-1-5-21-1-2-3-1001", integrity="Medium",
            is_administrator=False, dangerous_privileges=(),
            launch_spec_digest="a" * 64, logical_command_digest="b" * 64,
            transport_command_length=264, contained_in_job=True)
        summary = summarise_launch(identity)
        self.assertEqual(summary["launch_spec_digest"], "a" * 64)
        self.assertEqual(summary["logical_command_digest"], "b" * 64)
        self.assertEqual(summary["observed_worker_sid"], "S-1-5-21-1-2-3-1001")
        self.assertTrue(summary["contained_in_job"])
        # the transport argv itself is NEVER part of the provenance record
        self.assertNotIn("transport_command", summary)


class TestTheCreationSequenceAndFlags(unittest.TestCase):
    """The ORDER and the FLAGS are the security property, so they are pinned
    here as well as demonstrated end-to-end by the OS-real probe.

    These are STRUCTURAL assertions and are labelled as such: they read the
    launcher's own source. That is weaker than observing the behaviour, and it
    is the right complement to the probe rather than a substitute — the probe
    proves the child really is the Worker, really is Medium, really is in the
    job; these prove the sequence cannot be quietly reordered between probe
    runs, which is exactly what a mutation would do.
    """

    SOURCE = REPO / "src" / "gnosis" / "trust" / "worker_launcher.py"

    def setUp(self) -> None:
        self.text = self.SOURCE.read_text(encoding="utf-8")

    def _verify_body(self) -> str:
        tree = ast.parse(self.text)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_verify_and_contain":
                return ast.unparse(node)
        self.fail("_verify_and_contain not found")

    def test_resume_happens_after_every_identity_and_containment_check(self):
        body = self._verify_body()
        resume = body.index("ResumeThread")
        # The identity verdict itself is unit-tested in TestTheTokenVerdict; what
        # is pinned here is that it is REACHED, and reached before anything runs.
        for earlier in ("verify_worker_token",
                        "AssignProcessToJobObject",
                        "IsProcessInJob"):
            self.assertIn(earlier, body, f"{earlier} is missing entirely")
            self.assertLess(body.index(earlier), resume,
                            f"{earlier} must run BEFORE ResumeThread")

    def test_the_child_is_created_suspended(self):
        self.assertIn("CREATE_SUSPENDED | CREATE_NO_WINDOW", self.text)

    def test_logon_netcredentials_only_appears_nowhere(self):
        """It keeps the CALLER's token locally and would destroy the very
        user boundary the launch exists to create."""
        for path in sorted((REPO / "src" / "gnosis" / "trust").rglob("*.py")):
            self.assertNotIn("NETCREDENTIALS", path.read_text(encoding="utf-8").upper(),
                             f"{path.name} reaches for LOGON_NETCREDENTIALS_ONLY")

    def test_the_job_kills_on_close_and_permits_no_breakaway(self):
        """LimitFlags must be EXACTLY the kill-on-close flag.

        An earlier version asserted the flag was *contained in* the assignment,
        which a mutant satisfied by ORing BREAKAWAY_OK onto it — the check
        passed while the containment was gone. The assignment's right-hand side
        is now required to be a single name.
        """
        tree = ast.parse(self.text)
        flags = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Attribute) and t.attr == "LimitFlags"
                         for t in node.targets)]
        self.assertEqual(len(flags), 1, "LimitFlags is assigned exactly once")
        value = flags[0].value
        self.assertIsInstance(value, ast.Name,
                              "LimitFlags must be one flag, not a combination")
        self.assertEqual(value.id, "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE")

    def test_a_child_outside_the_job_is_never_resumed(self):
        """WM14's target: the IsProcessInJob verdict must gate the resume."""
        body = self._verify_body()
        self.assertIn("if not contained.value", body)
        self.assertLess(body.index("if not contained.value"),
                        body.index("ResumeThread"))

    def test_the_launch_spec_digest_is_surfaced_for_stage_6(self):
        """WM24's target. Stage 6 binds RunIdentity to this value, so it must
        be the digest the launcher actually sealed with — not a placeholder."""
        self.assertIn("launch_spec_digest=digest,", self.text)

    def test_termination_goes_through_the_job_not_the_root_pid(self):
        """Finding D1's repair. Killing only the root is what let descendants
        outlive a run."""
        tree = ast.parse(self.text)
        wait_body = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "wait":
                wait_body = ast.unparse(node)
        self.assertIn("TerminateJobObject", wait_body)
        self.assertNotIn("TerminateProcess", wait_body)

    def test_the_application_path_is_explicit_never_a_path_search(self):
        self.assertIn("str(self.runtime), buffer,", self.text,
                      "lpApplicationName must be the explicit runtime path")

    def test_no_std_handle_crosses_the_identity_boundary(self):
        """The bootstrap opens the endpoints itself, so there is nothing to
        leak — a structural answer to the handle-audit question.

        Scanned through the AST, not the text: the comment at that call site
        names STARTF_USESTDHANDLES precisely in order to say it is NOT set, and
        a check that cannot tell an explanation from a use fails on its own
        documentation. (It did, the first time this test ran.)
        """
        tree = ast.parse(self.text)
        identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        identifiers |= {node.attr for node in ast.walk(tree)
                        if isinstance(node, ast.Attribute)}
        self.assertNotIn("STARTF_USESTDHANDLES", identifiers)
        # ...and the STARTUPINFO's own flag field is never assigned, which is
        # what would be required to hand handles over. (`dwFlags` alone is too
        # broad a name to forbid: PROFILEINFOW has one too, and it IS set.)
        assigned = [node for node in ast.walk(tree)
                    if isinstance(node, ast.Attribute) and node.attr == "dwFlags"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "startup"]
        self.assertEqual(assigned, [], "the STARTUPINFO flags are never set")
        for field in ("hStdInput", "hStdOutput", "hStdError"):
            self.assertEqual(
                [node for node in ast.walk(tree)
                 if isinstance(node, ast.Attribute) and node.attr == field
                 and isinstance(node.value, ast.Name) and node.value.id == "startup"],
                [], f"startup.{field} is never populated")

    def test_the_transport_budget_is_enforced_not_merely_documented(self):
        self.assertIn("if len(command) > TRANSPORT_COMMAND_BUDGET:", self.text)


class TestTheDangerousPrivilegeSet(unittest.TestCase):
    def test_it_names_every_privilege_the_review_enumerated(self):
        for name in ("SeDebugPrivilege", "SeImpersonatePrivilege",
                     "SeTakeOwnershipPrivilege", "SeBackupPrivilege",
                     "SeRestorePrivilege", "SeTcbPrivilege",
                     "SeAssignPrimaryTokenPrivilege", "SeCreateTokenPrivilege"):
            self.assertIn(name, DANGEROUS_PRIVILEGES)


class TestOffWindowsThereIsNoFallback(unittest.TestCase):
    @unittest.skipIf(sys.platform == "win32", "the refusal is the non-Windows path")
    def test_the_launcher_refuses_rather_than_degrading(self):
        from gnosis.trust.worker_launcher import _require_windows

        with self.assertRaises(AuthorityUnavailable):
            _require_windows()


if __name__ == "__main__":
    unittest.main()
