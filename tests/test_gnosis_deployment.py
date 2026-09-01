"""F-33 Stage-2C-PACK-R1 — canonical composed deployment (RPK1-RPK20).

Filesystem only; no OS provisioning, no provider calls. An F-17 base fixture
pre-populates the canonical package root with the trust-plane closure (as the real
F-17 Provisioner would), then the composed provisioner adds the operator stack.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gnosis.provision.gnosis_deployment import (
    BaseDeployment,
    ComposedDeployment,
    GnosisDeploymentError,
    GnosisDeploymentProvisioner,
    composed_deployment_digest,
    f17_publisher_files,
)
from gnosis.provision.layout import DeploymentLayout
from gnosis.provision.operator_stack import (
    canonical_package_root,
)

SRC = Path(__file__).resolve().parents[1] / "src"


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.layout = DeploymentLayout(
            code_base=str(self.root / "code"), state_base=str(self.root / "state"),
            work_base=str(self.root / "work"), release_id="R1")
        self.pkg = canonical_package_root(self.layout)
        self.pkg.mkdir(parents=True)
        # Simulate the F-17 base: deploy the trust-plane closure into the pkg root.
        for src, rel in f17_publisher_files(SRC):
            dest = self.pkg / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        self.base_calls = 0
        self.rollback_calls = 0

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _base_provision(self) -> BaseDeployment:
        self.base_calls += 1
        def _rb() -> None:
            self.rollback_calls += 1
        return BaseDeployment(layout=self.layout, deployment_digest="d" * 64, rollback=_rb)

    def _prov(self) -> GnosisDeploymentProvisioner:
        return GnosisDeploymentProvisioner(SRC, base_provision=self._base_provision)


class TestComposedProvision(_Base):
    def test_rpk1_rpk2_rpk3_composed_api_consumes_base_no_glue(self) -> None:
        comp = self._prov().provision()
        self.assertIsInstance(comp, ComposedDeployment)
        self.assertEqual(self.base_calls, 1)                 # RPK2 consumed base
        # RPK3: one call → both F-17 trust AND application director present
        self.assertTrue((self.pkg / "gnosis" / "trust" / "orchestration.py").is_file())
        self.assertTrue((self.pkg / "gnosis" / "director" / "cli.py").is_file())

    def test_rpk4_only_one_trust_copy(self) -> None:
        comp = self._prov().provision()
        self.assertFalse(any(f.relpath.startswith("gnosis/trust/")
                             for f in comp.application.manifest.files))

    def test_rpk8_rpk10_entry_measured_and_verifies(self) -> None:
        comp = self._prov().provision()
        self.assertTrue(any(f.relpath == "operator_entry.py"
                            for f in comp.application.manifest.files))
        GnosisDeploymentProvisioner.verify(comp)  # no raise

    def test_rpk9_entry_tamper_fails_verify(self) -> None:
        comp = self._prov().provision()
        comp.operator_entry.write_bytes(comp.operator_entry.read_bytes() + b"#x")
        with self.assertRaises(GnosisDeploymentError):
            GnosisDeploymentProvisioner.verify(comp)

    def test_rpk15_worker_image_canonical_and_measured(self) -> None:
        comp = self._prov().provision()
        self.assertEqual(comp.worker_image,
                         self.pkg / "gnosis" / "director" / "deterministic_worker.py")
        self.assertTrue(comp.worker_image.is_file())
        self.assertTrue(any(f.relpath == "gnosis/director/deterministic_worker.py"
                            for f in comp.application.manifest.files))

    def test_rpk18_launch_is_isolated(self) -> None:
        comp = self._prov().provision()
        self.assertIn("-I", comp.launch_argv)
        # verify fails closed if -I is stripped
        broken = ComposedDeployment(
            layout=comp.layout, package_root=comp.package_root,
            operator_entry=comp.operator_entry, worker_image=comp.worker_image,
            application=comp.application, f17_deployment_digest=comp.f17_deployment_digest,
            composed_deployment_digest=comp.composed_deployment_digest,
            launch_argv=(comp.launch_argv[0], "-B", comp.launch_argv[-1]))
        with self.assertRaises(GnosisDeploymentError):
            GnosisDeploymentProvisioner.verify(broken)

    def test_rpk19_rpk20_app_failure_rolls_back_base(self) -> None:
        # Pre-create an application-path file → overwrite guard trips → composed
        # provisioning fails closed AND the F-17 base is rolled back.
        victim = self.pkg / "gnosis" / "director" / "cli.py"
        victim.parent.mkdir(parents=True, exist_ok=True)
        victim.write_bytes(b"F17\n")
        with self.assertRaises(GnosisDeploymentError):
            self._prov().provision()
        self.assertEqual(self.rollback_calls, 1)


class TestComposedIdentity(_Base):
    def test_rpk11_rpk12_deterministic_and_reverifies(self) -> None:
        comp = self._prov().provision()
        self.assertEqual(
            comp.composed_deployment_digest,
            composed_deployment_digest("d" * 64, comp.application.manifest.tree_digest))
        GnosisDeploymentProvisioner.verify(comp)

    def test_rpk13_changes_if_application_changes(self) -> None:
        a = composed_deployment_digest("d" * 64, "a" * 64)
        b = composed_deployment_digest("d" * 64, "b" * 64)
        self.assertNotEqual(a, b)

    def test_rpk14_changes_if_f17_digest_changes(self) -> None:
        a = composed_deployment_digest("d" * 64, "x" * 64)
        b = composed_deployment_digest("e" * 64, "x" * 64)
        self.assertNotEqual(a, b)


class TestProvenanceSmoke(_Base):
    def _resolve(self, cwd: Path) -> dict[str, str]:
        code = (
            f"import sys; sys.path.insert(0, r'{self.pkg}');"
            "import gnosis.director.cli as a, gnosis.director.composition as b,"
            " gnosis.trust.run_identity as c, gnosis.trust.orchestration as d,"
            " gnosis.director.deterministic_worker as e;"
            "print(a.__file__); print(b.__file__); print(c.__file__);"
            " print(d.__file__); print(e.__file__)")
        p = subprocess.run([sys.executable, "-I", "-B", "-c", code], cwd=str(cwd),
                           capture_output=True, text=True, check=False)
        return {"rc": p.returncode, "out": p.stdout, "err": p.stderr}

    def test_rpk5_rpk6_rpk16_one_tree_no_checkout(self) -> None:
        self._prov().provision()
        neutral = self.root / "neutral"
        neutral.mkdir()
        r = self._resolve(neutral)
        self.assertEqual(r["rc"], 0, r["err"][-300:])
        for path in r["out"].splitlines():
            self.assertTrue(path.startswith(str(self.pkg)),
                            f"{path} not under the one authoritative tree {self.pkg}")

    def test_rpk17_cwd_shadow_does_not_win(self) -> None:
        self._prov().provision()
        shadow = self.root / "shadow"
        (shadow / "gnosis").mkdir(parents=True)
        (shadow / "gnosis" / "__init__.py").write_text(
            "raise RuntimeError('SHADOW')\n", encoding="utf-8")
        r = self._resolve(shadow)
        self.assertEqual(r["rc"], 0, r["err"][-300:])
        self.assertNotIn("SHADOW", r["err"])


if __name__ == "__main__":
    unittest.main()
