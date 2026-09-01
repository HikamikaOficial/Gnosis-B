"""F-33 Stage-2C-PACK-R1/R2 — operator-stack primitives (trust/app split, manifest,
self-verifying entry, fail-closed manifest loader).

Filesystem only; no OS provisioning, no provider calls.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gnosis.provision.layout import DeploymentLayout
from gnosis.provision.operator_stack import (
    OperatorStackError,
    _assert_inside,
    _relpath_is_canonical,
    application_modules,
    build_application_manifest,
    canonical_package_root,
    deploy_operator_stack,
    f17_provided_closure,
    load_application_manifest,
    measure_application_tree,
    operator_entry_content,
    production_closure,
    verify_application_tree,
)

SRC = Path(__file__).resolve().parents[1] / "src"
REC = Path(r"C:\D\state\GNOSIS_COMPOSED.json")


class TestClosureSplit(unittest.TestCase):
    def test_production_closure_complete(self) -> None:
        prod = production_closure(SRC)
        for m in ("gnosis.director.cli", "gnosis.director.composition",
                  "gnosis.director.deterministic_worker", "gnosis.adapters.cli_review"):
            self.assertIn(m, prod)

    def test_f17_provided_includes_all_director_trust(self) -> None:
        f17 = f17_provided_closure(SRC)
        for m in ("orchestration", "deployment", "worker_launcher", "launch_spec",
                  "run_identity", "publisher_service"):
            self.assertIn(f"gnosis.trust.{m}", f17)

    def test_application_owns_no_trust(self) -> None:
        app = application_modules(SRC)
        self.assertFalse(any(m.startswith("gnosis.trust.") for m in app))
        self.assertIn("gnosis.director.cli", app)

    def test_manifest_has_no_trust_path_and_measures_entry(self) -> None:
        m = build_application_manifest(SRC, Path(r"C:\D\publisher"), REC)
        self.assertFalse(any(f.relpath.startswith("gnosis/trust/") for f in m.files))
        self.assertTrue(any(f.relpath == "operator_entry.py" for f in m.files))

    def test_manifest_deterministic(self) -> None:
        pr = Path(r"C:\D\publisher")
        self.assertEqual(build_application_manifest(SRC, pr, REC).tree_digest,
                         build_application_manifest(SRC, pr, REC).tree_digest)

    def test_canonical_root_is_publisher(self) -> None:
        layout = DeploymentLayout(code_base=r"C:\C", state_base=r"C:\S",
                                  work_base=r"C:\W", release_id="R1")
        self.assertEqual(canonical_package_root(layout), Path(layout.trust_root))

    def test_entry_is_self_verifying_and_delegates(self) -> None:
        c = operator_entry_content(Path(r"C:\pkg"), REC)
        self.assertIn("sys.path.insert(0, _ROOT)", c)
        self.assertIn("from gnosis.director.cli import main", c)
        # self-verification runs BEFORE the application import.
        self.assertLess(c.index("_verify()"), c.index("from gnosis.director.cli"))
        self.assertIn(str(REC), c)  # trusted record path is baked (and measured)

    def test_assert_inside_rejects_escape(self) -> None:
        root = Path(tempfile.gettempdir()) / "gnosis-r2-root"
        with self.assertRaises(OperatorStackError):
            _assert_inside(root, root.parent / "escape.py")

    def test_relpath_canonical_rejects_traversal_and_absolute(self) -> None:
        self.assertTrue(_relpath_is_canonical("gnosis/director/cli.py"))
        for bad in ("../x.py", "/abs.py", "C:\\x.py", "a\\b.py", "a//b.py",
                    "./a.py", "", "trailing/"):
            self.assertFalse(_relpath_is_canonical(bad), bad)


class TestDeployIntoCanonicalRoot(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.pkg = Path(self.tmp.name) / "publisher"
        self.pkg.mkdir()
        self.rec = Path(self.tmp.name) / "state" / "GNOSIS_COMPOSED.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_deploys_app_modules_and_entry(self) -> None:
        dep = deploy_operator_stack(SRC, self.pkg, self.rec)
        self.assertTrue((self.pkg / "gnosis" / "director" / "cli.py").is_file())
        self.assertTrue(dep.entry_path.is_file())
        self.assertTrue(dep.worker_image.is_file())
        ok, problems = verify_application_tree(self.pkg, dep.manifest)
        self.assertTrue(ok, problems)
        # re-measure equals the manifest digest
        self.assertEqual(measure_application_tree(self.pkg, dep.manifest),
                         dep.manifest.tree_digest)

    def test_never_deploys_trust(self) -> None:
        deploy_operator_stack(SRC, self.pkg, self.rec)
        self.assertFalse((self.pkg / "gnosis" / "trust" / "orchestration.py").exists())

    def test_refuses_to_overwrite_existing_f17_file(self) -> None:
        victim = self.pkg / "gnosis" / "director" / "cli.py"
        victim.parent.mkdir(parents=True)
        victim.write_text("F17-OWNED\n", encoding="utf-8")
        with self.assertRaises(OperatorStackError):
            deploy_operator_stack(SRC, self.pkg, self.rec)

    def test_entry_tamper_detected(self) -> None:
        dep = deploy_operator_stack(SRC, self.pkg, self.rec)
        dep.entry_path.write_text(dep.entry_path.read_text(encoding="utf-8") + "#x\n",
                                  encoding="utf-8")
        ok, problems = verify_application_tree(self.pkg, dep.manifest)
        self.assertFalse(ok)
        self.assertTrue(any("operator_entry.py" in p for p in problems))

    def test_application_json_has_schema(self) -> None:
        deploy_operator_stack(SRC, self.pkg, self.rec)
        data = json.loads((self.pkg / "APPLICATION.json").read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], "gnosis.application_manifest.v1")


class TestManifestLoaderFailClosed(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.pkg = Path(self.tmp.name) / "publisher"
        self.pkg.mkdir()
        self.rec = Path(self.tmp.name) / "state" / "GNOSIS_COMPOSED.json"
        deploy_operator_stack(SRC, self.pkg, self.rec)
        self.manifest_path = self.pkg / "APPLICATION.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_valid_manifest_loads(self) -> None:
        m = load_application_manifest(self.pkg)
        self.assertTrue(any(f.relpath == "operator_entry.py" for f in m.files))

    def test_wrong_schema_rejected(self) -> None:
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        data["schema"] = "evil.v9"
        self.manifest_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(OperatorStackError):
            load_application_manifest(self.pkg)

    def test_duplicate_keys_rejected(self) -> None:
        self.manifest_path.write_text(
            '{"schema":"gnosis.application_manifest.v1","tree_digest":"%s",'
            '"files":[],"files":[]}' % ("a" * 64), encoding="utf-8")
        with self.assertRaises(OperatorStackError):
            load_application_manifest(self.pkg)

    def test_traversal_relpath_rejected(self) -> None:
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        data["files"][0]["relpath"] = "../escape.py"
        self.manifest_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(OperatorStackError):
            load_application_manifest(self.pkg)

    def test_tree_digest_inconsistent_rejected(self) -> None:
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        data["tree_digest"] = "b" * 64
        self.manifest_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(OperatorStackError):
            load_application_manifest(self.pkg)


if __name__ == "__main__":
    unittest.main()
