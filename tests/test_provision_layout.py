"""F-17 Stage 8 — the production layout and ACL matrix, checked as data.

These pin the security shape of the deployment before any OS state exists: the
worker never holds write on a trusted root, the credential blob and the
authoritative evidence deny the worker entirely, every protected root strips
inheritance, and the candidate worktree is the only place the worker may write.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gnosis.provision.layout import (
    Access,
    DeploymentLayout,
    Principal,
    every_protected_root_breaks_inheritance,
    worker_denied_roots_grant_no_worker_ace,
    worker_never_writes_a_trusted_root,
)

LAY = DeploymentLayout(
    r"C:\Program Files\GnosisStage8Probe\Trust",
    r"C:\ProgramData\GnosisStage8Probe\Trust",
    r"C:\ProgramData\GnosisStage8Probe\Work",
    release_id="R1")


def _spec(key: str):  # type: ignore[no-untyped-def]
    return next(s for s in LAY.roots() if s.key == key)


class TestTheMatrixInvariants(unittest.TestCase):
    def test_worker_never_writes_a_trusted_root(self):
        self.assertEqual(worker_never_writes_a_trusted_root(), [])

    def test_worker_denied_roots_grant_no_worker_ace(self):
        self.assertEqual(worker_denied_roots_grant_no_worker_ace(), [])

    def test_every_protected_root_breaks_inheritance(self):
        self.assertEqual(every_protected_root_breaks_inheritance(), [])


class TestPerRootAccess(unittest.TestCase):
    def test_worker_has_no_ace_on_the_credential_blob_dir(self):
        self.assertIsNone(_spec("secrets").worker_access())

    def test_worker_has_no_ace_on_authoritative_bundles(self):
        # Stage 7 R5 closed: the worker cannot write the SUMMARY the gate reads.
        self.assertIsNone(_spec("bundles").worker_access())

    def test_worker_has_no_ace_on_anchors_runidentity_publisher(self):
        for key in ("anchors", "runidentity", "publisher"):
            self.assertIsNone(_spec(key).worker_access(), key)

    def test_worker_reads_and_executes_runtime_bootstrap_toolchain(self):
        for key in ("runtime", "bootstrap", "toolchain"):
            self.assertIs(_spec(key).worker_access(), Access.READ_EXECUTE, key)

    def test_worker_modifies_only_the_work_root(self):
        self.assertIs(_spec("work").worker_access(), Access.MODIFY)
        writable = [s.key for s in LAY.roots()
                    if s.worker_access() in (Access.FULL, Access.MODIFY)]
        self.assertEqual(writable, ["work"])

    def test_service_appends_to_anchors_and_runidentity(self):
        self.assertIs(_spec("anchors").worker_access(), None)
        # the service (not the worker) writes anchors/runidentity
        for key in ("anchors", "runidentity"):
            grants = dict(_spec(key).grants)
            self.assertIs(grants[Principal.SERVICE], Access.MODIFY, key)

    def test_service_reads_bundles_but_does_not_write_them(self):
        grants = dict(_spec("bundles").grants)
        self.assertIs(grants[Principal.SERVICE], Access.READ)

    def test_service_reads_and_executes_publisher_code(self):
        grants = dict(_spec("publisher").grants)
        self.assertIs(grants[Principal.SERVICE], Access.READ_EXECUTE)


class TestLayoutPaths(unittest.TestCase):
    def test_code_is_versioned_state_is_stable(self):
        self.assertIn(r"\releases\R1", LAY.trust_root)
        self.assertNotIn("releases", LAY.config_path)
        self.assertNotIn("releases", LAY.bundles_root)

    def test_all_paths_are_absolute(self):
        for p in (LAY.trust_root, LAY.runtime_executable, LAY.config_path,
                  LAY.bundles_root, LAY.secrets_blob, LAY.pth_file):
            self.assertTrue(Path(p).is_absolute(), p)

    def test_the_authoritative_bundles_are_not_the_worker_work_root(self):
        self.assertNotEqual(LAY.bundles_root, LAY.work_base)
        self.assertNotIn(LAY.work_base, LAY.bundles_root)


if __name__ == "__main__":
    unittest.main()
