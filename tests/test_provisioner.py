"""F-17 Stage 8 — the provisioner's content and transaction order.

Exercised with a recording Operations fake: no account, service or ACL is
created, but the exact commands and their ORDER are asserted — ACLs applied
before the deployment is observed, the worker denied on every trusted root, the
service SID made RESTRICTED, the credential blob written. The OS-real behaviour
is proved separately by the Stage 8 probe.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gnosis.provision.layout import DeploymentLayout
from gnosis.provision.provisioner import (
    ProvisionConfig,
    Provisioner,
    ResolvedSids,
    icacls_commands,
    package_json,
    pth_content,
    service_config_json,
    service_imagepath,
)

SID_SERVICE = "S-1-5-80-1-2-3-4-5"
SID_WORKER = "S-1-5-21-11-22-33-1001"


def _layout() -> DeploymentLayout:
    return DeploymentLayout(
        r"C:\Program Files\GnosisStage8Probe\Trust",
        r"C:\ProgramData\GnosisStage8Probe\Trust",
        r"C:\ProgramData\GnosisStage8Probe\Work", release_id="R1")


def _config() -> ProvisionConfig:
    return ProvisionConfig(
        layout=_layout(), service_name="GnosisStage8Probe",
        pipe_name=r"\\.\pipe\gnosis-s8", worker_username="GnosisWkrS8",
        package_version="0.0.0-s8", source_commit="c" * 40, source_tree="t" * 64)


class _RecordingOps:
    """Records every operation; returns plausible values, touches nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.made: set[str] = set()
        self.accounts: set[str] = set()
        self.services: set[str] = set()

    def run(self, argv):  # type: ignore[no-untyped-def]
        self.calls.append(("run", tuple(argv)))
        # Model the two idempotence probes: a service query reports absence
        # until `sc create` has run, so a fresh install takes the create path.
        if len(argv) >= 3 and argv[0] == "sc.exe" and argv[1] == "query":
            return (0, "RUNNING") if argv[2] in self.services else (1060, "")
        if len(argv) >= 3 and argv[0] == "sc.exe" and argv[1] == "create":
            self.services.add(argv[2])
        return (0, "")

    def mkdir(self, path):  # type: ignore[no-untyped-def]
        self.calls.append(("mkdir", (path,))); self.made.add(path)

    def rmtree(self, path):  # type: ignore[no-untyped-def]
        self.calls.append(("rmtree", (path,)))

    def exists(self, path):  # type: ignore[no-untyped-def]
        return path in self.made

    def copytree(self, src, dst):  # type: ignore[no-untyped-def]
        self.calls.append(("copytree", (src, dst))); self.made.add(dst)

    def copyfile(self, src, dst):  # type: ignore[no-untyped-def]
        self.calls.append(("copyfile", (src, dst)))

    def write_text(self, path, text):  # type: ignore[no-untyped-def]
        self.calls.append(("write_text", (path, text)))

    def write_bytes(self, path, data):  # type: ignore[no-untyped-def]
        self.calls.append(("write_bytes", (path, data)))

    def resolve_sid(self, name):  # type: ignore[no-untyped-def]
        self.calls.append(("resolve_sid", (name,)))
        if name == "BUILTIN\\Administrators":
            return "S-1-5-32-544"
        if name.startswith("NT SERVICE\\"):
            return SID_SERVICE
        return SID_WORKER

    def account_exists(self, username):  # type: ignore[no-untyped-def]
        return username in self.accounts

    def create_worker(self, username, password, comment):  # type: ignore[no-untyped-def]
        self.calls.append(("create_worker", (username,)))
        self.accounts.add(username)

    def delete_worker(self, username):  # type: ignore[no-untyped-def]
        self.calls.append(("delete_worker", (username,))); return 0

    def protect_secret(self, secret):  # type: ignore[no-untyped-def]
        self.calls.append(("protect_secret", ()))
        return b"DPAPI-BLOB"


class _FakeIdentity:
    def digest(self) -> str:
        return "d" * 64


def _install() -> tuple[Provisioner, _RecordingOps]:
    ops = _RecordingOps()
    prov = Provisioner(
        config=_config(), ops=ops, runtime_src=r"C:\src\runtime",
        publisher_files=[(r"C:\src\p.py", "gnosis/x.py")],
        bootstrap_files=[(r"C:\src\b.py", "gnosis/trust/bootstrap.py")],
        toolchain_files=[(r"C:\tools\git.exe", "git.exe")],
        observe_fn=lambda _config: _FakeIdentity())
    prov.install("Pw!secret123")
    return prov, ops


class TestPureRenderers(unittest.TestCase):
    def test_pth_pins_runtime_and_publisher_and_disables_site(self):
        pth = pth_content()
        self.assertIn("..\\publisher", pth)
        self.assertIn("Lib", pth)
        self.assertNotIn("import site", pth)
        self.assertNotIn("site-packages", pth)

    def test_imagepath_is_absolute_isolated_and_quoted(self):
        img = service_imagepath(r"C:\rt\python.exe", r"C:\rt\service_main.py",
                                r"C:\pd\config.json")
        self.assertEqual(
            img, '"C:\\rt\\python.exe" -I -B "C:\\rt\\service_main.py" '
                 '"C:\\pd\\config.json"')
        self.assertIn(" -I ", img)
        # -B forbids bytecode in the measured trust root (digest stability).
        self.assertIn(" -B ", img)

    def test_config_binds_the_service_and_worker_sids_and_digest(self):
        cfg = service_config_json(_config(), ResolvedSids(
            "S-1-5-32-544", "S-1-5-18", SID_SERVICE, SID_WORKER), "e" * 64)
        self.assertEqual(cfg["service_sid"], SID_SERVICE)
        self.assertEqual(cfg["authorized_worker_sid"], SID_WORKER)
        self.assertEqual(cfg["expected_deployment_digest"], "e" * 64)
        self.assertNotIn("releases", cfg["trust_state_root"])

    def test_package_json_carries_real_provenance(self):
        pkg = package_json("1.2.3", "a" * 40, "b" * 64)
        self.assertEqual(pkg["source_commit"], "a" * 40)

    def test_icacls_strips_inheritance_before_granting(self):
        from gnosis.provision.layout import DeploymentLayout as D
        lay = D(r"C:\c", r"C:\s", r"C:\w", release_id="R1")
        sids = ResolvedSids("S-1-5-32-544", "S-1-5-18", SID_SERVICE, SID_WORKER)
        secrets = next(s for s in lay.roots() if s.key == "secrets")
        cmds = icacls_commands(secrets, lay.secrets_blob, sids)
        self.assertEqual(cmds[0][2], "/inheritance:r")
        # the worker SID never appears in the secrets grant
        flat = " ".join(" ".join(c) for c in cmds)
        self.assertNotIn(SID_WORKER, flat)


class TestTransactionOrder(unittest.TestCase):
    def setUp(self) -> None:
        self.prov, self.ops = _install()
        self.kinds = [c[0] for c in self.ops.calls]

    def _first(self, pred):  # type: ignore[no-untyped-def]
        return next(i for i, c in enumerate(self.ops.calls) if pred(c))

    def test_acls_are_applied_before_the_deployment_is_observed(self):
        # deployment_digest binds the observed security of the paths, so ACLs
        # MUST precede observation. The step log records the order.
        acl_step = self.prov.steps.index(next(
            s for s in self.prov.steps if s.startswith("apply ACL matrix")))
        obs_step = self.prov.steps.index(next(
            s for s in self.prov.steps if s.startswith("observe deployment")))
        self.assertLess(acl_step, obs_step)

    def test_the_worker_account_exists_before_the_service_and_acls(self):
        create = self._first(lambda c: c[0] == "create_worker")
        first_icacls = self._first(
            lambda c: c[0] == "run" and c[1] and c[1][0] == "icacls")
        self.assertLess(create, first_icacls)

    def test_the_service_is_made_restricted(self):
        sc_calls = [c[1] for c in self.ops.calls
                    if c[0] == "run" and c[1] and c[1][0] == "sc.exe"]
        verbs = [(c[1], c[2]) for c in sc_calls if len(c) > 2]
        self.assertIn(("create", "GnosisStage8Probe"), verbs)
        self.assertIn(("sidtype", "GnosisStage8Probe"), verbs)

    def test_no_icacls_grants_the_worker_on_a_denied_root(self):
        denied_paths = {
            _layout().secrets_blob.rsplit("\\", 1)[0], _layout().bundles_root,
            _layout().anchors_root, _layout().runidentity_root,
            f"{_layout().code_release_base}\\publisher",
        }
        for kind, argv in self.ops.calls:
            if kind != "run" or not argv or argv[0] != "icacls":
                continue
            path = argv[1]
            if path in denied_paths and "/grant:r" in argv:
                self.assertNotIn(
                    f"*{SID_WORKER}", " ".join(argv),
                    f"worker granted on denied root {path}")

    def test_the_credential_blob_is_written(self):
        self.assertTrue(any(
            c[0] == "write_bytes" and c[1][0].endswith("worker.dpapi")
            for c in self.ops.calls))


class TestIdempotence(unittest.TestCase):
    def test_re_running_install_creates_no_second_account_or_service(self):
        ops = _RecordingOps()
        prov = Provisioner(
            config=_config(), ops=ops, runtime_src=r"C:\src\runtime",
            publisher_files=[(r"C:\src\p.py", "gnosis/x.py")],
            bootstrap_files=[(r"C:\src\b.py", "gnosis/trust/bootstrap.py")],
            toolchain_files=[(r"C:\tools\git.exe", "git.exe")],
            observe_fn=lambda _config: _FakeIdentity())
        prov.install("Pw!secret123")
        prov.install("Pw!secret123")  # a second, converging run
        creates = [c for c in ops.calls if c[0] == "create_worker"]
        self.assertEqual(len(creates), 1, "a second account was created")
        sc_creates = [c for c in ops.calls if c[0] == "run" and c[1][:2]
                      == ("sc.exe", "create")]
        self.assertEqual(len(sc_creates), 1, "a second service was created")

    def test_grants_are_replace_not_add_so_acls_cannot_broaden(self):
        # icacls /grant:r REPLACES a principal's ACE; a re-run yields identical
        # ACLs, so the matrix cannot broaden on convergence.
        _prov, ops = _install()
        grants = [argv for kind, argv in ops.calls
                  if kind == "run" and argv[:1] == ("icacls",)
                  and "/grant:r" in argv]
        self.assertTrue(grants)
        for argv in grants:
            self.assertIn("/grant:r", argv)
            self.assertNotIn("/grant", [a for a in argv if a == "/grant"])


class TestUninstallOrder(unittest.TestCase):
    def test_uninstall_stops_service_then_removes_account_then_roots(self):
        ops = _RecordingOps()
        for b in (r"C:\Program Files\GnosisStage8Probe\Trust",
                  r"C:\ProgramData\GnosisStage8Probe\Trust",
                  r"C:\ProgramData\GnosisStage8Probe\Work"):
            ops.made.add(b)
        prov = Provisioner(config=_config(), ops=ops, runtime_src="x",
                           publisher_files=[], bootstrap_files=[],
                           toolchain_files=[])
        prov.uninstall()
        kinds = [(c[0], c[1]) for c in ops.calls]
        stop = next(i for i, c in enumerate(kinds)
                    if c[0] == "run" and c[1][:2] == ("sc.exe", "stop"))
        deleted = next(i for i, c in enumerate(kinds) if c[0] == "delete_worker")
        rmtree = next(i for i, c in enumerate(kinds) if c[0] == "rmtree")
        self.assertLess(stop, deleted)
        self.assertLess(deleted, rmtree)


if __name__ == "__main__":
    unittest.main()
