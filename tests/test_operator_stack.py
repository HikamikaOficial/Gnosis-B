"""F-33 Stage-2C-PACK — canonical operator-stack deployment (PK1-PK15).

Filesystem only; no OS provisioning, no provider calls. Deploys the production
import closure into a temp application root and proves completeness, integrity,
isolation and fail-closed behaviour.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gnosis.provision.operator_stack import (
    OperatorStackError,
    _assert_inside,
    application_root_for,
    build_application_manifest,
    deploy_operator_stack,
    operator_entry_content,
    production_closure,
    verify_application_tree,
)

SRC = Path(__file__).resolve().parents[1] / "src"


class _Deployed(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app_root = self.root / "code" / "releases" / "R1" / "app"
        self.app_root.parent.mkdir(parents=True)
        self.dep = deploy_operator_stack(SRC, self.app_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()


class TestClosureAndManifest(unittest.TestCase):
    def test_pk1_full_closure_deployed(self) -> None:
        closure = production_closure(SRC)
        for required in ("gnosis.director.cli", "gnosis.director.composition",
                         "gnosis.director.publication", "gnosis.director.publisher_client",
                         "gnosis.director.deterministic_worker",
                         "gnosis.adapters.cli_review", "gnosis.kernel.engine"):
            self.assertIn(required, closure)

    def test_pk6_no_dev_or_test_surfaces(self) -> None:
        m = build_application_manifest(SRC)
        for f in m.files:
            self.assertFalse(f.relpath.startswith(("tests/", "docs/", "scripts/")))
            self.assertNotIn(".venv", f.relpath)

    def test_pk15_replay_route_unreachable(self) -> None:
        m = build_application_manifest(SRC)
        for f in m.files:
            self.assertNotIn("replay", f.relpath)
            self.assertNotIn("orchestrator", f.relpath)

    def test_pk14_manifest_deterministic(self) -> None:
        self.assertEqual(build_application_manifest(SRC).tree_digest,
                         build_application_manifest(SRC).tree_digest)

    def test_pk13_traversal_rejected(self) -> None:
        with self.assertRaises(OperatorStackError):
            _assert_inside(self.root_app(), self.root_app().parent / "escape.py")

    def root_app(self) -> Path:
        return Path(tempfile.gettempdir()) / "gnosis-app-root"


class TestDeployedTree(_Deployed):
    def test_pk4_source_equals_deployed(self) -> None:
        ok, problems = verify_application_tree(self.app_root, self.dep.manifest)
        self.assertTrue(ok, problems)

    def test_pk5_one_byte_tamper_detected(self) -> None:
        target = self.app_root / "gnosis" / "director" / "cli.py"
        target.write_text(target.read_text(encoding="utf-8") + "# x\n", encoding="utf-8")
        ok, problems = verify_application_tree(self.app_root, self.dep.manifest)
        self.assertFalse(ok)
        self.assertTrue(any("tampered" in p for p in problems))

    def test_pk2_missing_file_detected(self) -> None:
        (self.app_root / "gnosis" / "director" / "cli.py").unlink()
        ok, problems = verify_application_tree(self.app_root, self.dep.manifest)
        self.assertFalse(ok)
        self.assertTrue(any("missing" in p for p in problems))

    def test_pk3_unexpected_file_detected(self) -> None:
        (self.app_root / "gnosis" / "director" / "sneaky.py").write_text("x=1\n",
                                                                        encoding="utf-8")
        ok, problems = verify_application_tree(self.app_root, self.dep.manifest)
        self.assertFalse(ok)
        self.assertTrue(any("unexpected" in p for p in problems))

    def test_pk9_worker_image_at_expected_location(self) -> None:
        self.assertTrue(
            (self.app_root / "gnosis" / "director" / "deterministic_worker.py").is_file())

    def test_pk10_entry_delegates_to_canonical_main(self) -> None:
        content = self.dep.entry_path.read_text(encoding="utf-8")
        self.assertIn("from gnosis.director.cli import main", content)
        self.assertIn(str(self.app_root), content)
        self.assertTrue(self.dep.entry_path.is_file())

    def test_pk11_app_tree_does_not_touch_trust_tree(self) -> None:
        # Deployment writes only under app_root (+ the sibling entry); a separate
        # trust tree is never modified.
        trust_tree = self.root / "code" / "releases" / "R1" / "publisher"
        self.assertFalse(trust_tree.exists())


class TestIsolation(_Deployed):
    def _smoke(self, cwd: Path) -> subprocess.CompletedProcess[str]:
        code = (
            f"import sys; sys.path.insert(0, r'{self.app_root}'); "
            "import gnosis.director.composition, gnosis.director.cli, "
            "gnosis.director.deterministic_worker; print('IMPORT_OK')")
        return subprocess.run([sys.executable, "-I", "-B", "-c", code],
                              cwd=str(cwd), capture_output=True, text=True,
                              check=False)

    def test_pk7_imports_without_source_checkout(self) -> None:
        neutral = self.root / "neutral"
        neutral.mkdir()
        proc = self._smoke(neutral)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("IMPORT_OK", proc.stdout)

    def test_pk8_cwd_shadow_does_not_win(self) -> None:
        # A malicious same-name package in CWD must not shadow the deployed one.
        shadow = self.root / "shadow"
        (shadow / "gnosis").mkdir(parents=True)
        (shadow / "gnosis" / "__init__.py").write_text(
            "raise RuntimeError('SHADOW WON')\n", encoding="utf-8")
        proc = self._smoke(shadow)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("SHADOW WON", proc.stderr)


class TestFailClosed(unittest.TestCase):
    def test_pk12_empty_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            empty = Path(d) / "empty_src"
            empty.mkdir()
            app_root = Path(d) / "app"
            with self.assertRaises(OperatorStackError):
                deploy_operator_stack(empty, app_root)
            self.assertFalse(app_root.exists())  # no valid deployment left


class TestLayout(unittest.TestCase):
    def test_application_root_under_code_release_base(self) -> None:
        from gnosis.provision.layout import DeploymentLayout
        layout = DeploymentLayout(code_base=r"C:\Code", state_base=r"C:\State",
                                  work_base=r"C:\Work", release_id="R1")
        app = application_root_for(layout)
        self.assertEqual(app.name, "app")
        self.assertIn("releases", str(app))

    def test_entry_content_is_isolated(self) -> None:
        content = operator_entry_content(Path(r"C:\Deploy\app"))
        self.assertIn("sys.path.insert(0", content)
        self.assertIn("from gnosis.director.cli import main", content)


if __name__ == "__main__":
    unittest.main()
