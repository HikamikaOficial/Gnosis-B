r"""F-33 Stage 2C-B1-R3D — effective composed deployment identity.

The R3A/R3C-proven identity-scope collision (the composed application tree lives
under the F-17 `trust_root`, so the whole-root F-17 re-observation at launch never
matched the pre-application base digest) is reconciled by an explicit EFFECTIVE
whole-root identity measured AFTER the application tree is deployed, bound with the
immutable base provenance and the closed-world application identity.

Filesystem only; no OS provisioning, no provider calls. A real F-17 base fixture +
real `deploy_operator_stack` are used; the whole-root observer is injected.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "scripts", REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from gnosis.provision.gnosis_deployment import (
    BaseDeployment,
    GnosisDeploymentError,
    GnosisDeploymentProvisioner,
    composed_deployment_digest,
    f17_publisher_files,
    read_composed_record,
)
from gnosis.provision.layout import DeploymentLayout
from gnosis.provision.operator_stack import canonical_package_root

SRC = REPO / "src"
F17_BASE = "f" * 64        # base F-17 provenance (pre-application)
EFFECTIVE = "e" * 64       # effective whole-root identity (post-application)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.layout = DeploymentLayout(
            code_base=str(self.root / "code"), state_base=str(self.root / "state"),
            work_base=str(self.root / "work"), release_id="R3D")
        self.pkg = canonical_package_root(self.layout)
        self.pkg.mkdir(parents=True)
        Path(self.layout.state_base).mkdir(parents=True, exist_ok=True)
        for src, rel in f17_publisher_files(SRC):
            dest = self.pkg / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        self.rollbacks = 0

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _base(self) -> BaseDeployment:
        def _rb() -> None:
            self.rollbacks += 1
        return BaseDeployment(layout=self.layout, deployment_digest=F17_BASE, rollback=_rb)

    def _prov(self, effective: str = EFFECTIVE) -> GnosisDeploymentProvisioner:
        return GnosisDeploymentProvisioner(
            SRC, base_provision=self._base, observe_effective=lambda: effective)

    def _obs(self, digest: str = EFFECTIVE):
        return lambda: digest

    def _regen_manifest(self) -> None:
        # Recompute a coherent APPLICATION.json over the CURRENT (tampered) bytes so
        # the LOCAL manifest is self-consistent — only the trusted RECORD catches it.
        import hashlib
        data = json.loads((self.pkg / "APPLICATION.json").read_text(encoding="utf-8"))
        files = []
        for ent in data["files"]:
            rel = ent["relpath"]
            files.append([rel, hashlib.sha256((self.pkg / rel).read_bytes()).hexdigest()])
        files.sort(key=lambda x: x[0])
        tree = hashlib.sha256(
            json.dumps(files, separators=(",", ":")).encode("utf-8")).hexdigest()
        out = {"schema": "gnosis.application_manifest.v1", "tree_digest": tree,
               "files": [{"relpath": r, "digest": d} for r, d in files]}
        (self.pkg / "APPLICATION.json").write_text(json.dumps(out, indent=2),
                                                   encoding="utf-8")


class TestEffectiveIdentity(_Base):
    def test_binding_uses_all_three_identities(self) -> None:
        # changing ANY operand changes the composed digest.
        base = composed_deployment_digest(F17_BASE, "a" * 64, EFFECTIVE)
        self.assertNotEqual(base, composed_deployment_digest("d" * 64, "a" * 64, EFFECTIVE))
        self.assertNotEqual(base, composed_deployment_digest(F17_BASE, "b" * 64, EFFECTIVE))
        self.assertNotEqual(base, composed_deployment_digest(F17_BASE, "a" * 64, "c" * 64))

    def test_record_carries_distinct_base_and_effective(self) -> None:
        comp = self._prov().provision()
        rec = read_composed_record(comp.composed_record_path)
        self.assertEqual(rec.f17_deployment_digest, F17_BASE)         # base provenance
        self.assertEqual(rec.effective_deployment_digest, EFFECTIVE)  # effective, distinct
        self.assertNotEqual(rec.f17_deployment_digest, rec.effective_deployment_digest)
        self.assertEqual(rec.composed_deployment_digest,
                         composed_deployment_digest(F17_BASE, rec.application_tree_digest,
                                                    EFFECTIVE))

    def test_effective_measured_after_app_deploy(self) -> None:
        # The provisioner must call observe_effective AFTER the app tree exists.
        seen = {}

        def _obs_eff() -> str:
            seen["entry_present"] = (self.pkg / "operator_entry.py").is_file()
            seen["app_present"] = (self.pkg / "gnosis" / "director" / "cli.py").is_file()
            return EFFECTIVE
        prov = GnosisDeploymentProvisioner(SRC, base_provision=self._base,
                                           observe_effective=_obs_eff)
        prov.provision()
        self.assertTrue(seen["entry_present"])   # measured post-deploy
        self.assertTrue(seen["app_present"])


class TestCanonicalLaunchEffective(_Base):
    def test_valid_effective_launch_passes(self) -> None:
        comp = self._prov().provision()
        argv = GnosisDeploymentProvisioner.canonical_launch(comp, reobserve_f17=self._obs())
        self.assertIn("-I", argv)
        self.assertTrue(argv[-1].endswith("operator_entry.py"))

    def test_whole_root_change_refused(self) -> None:
        # any whole-root mutation (substrate replacement / extra importable file /
        # injected overlay) -> the fresh effective observation differs -> refuse.
        # The specific message proves the EFFECTIVE check (not only the composed
        # backstop) fired — so skipping that check is independently detectable.
        comp = self._prov().provision()
        with self.assertRaises(GnosisDeploymentError) as cm:
            GnosisDeploymentProvisioner.canonical_launch(
                comp, reobserve_f17=self._obs("d" * 64))
        self.assertIn("effective deployment identity", str(cm.exception))

    def test_launch_not_held_to_pre_app_base(self) -> None:
        # the reconciliation itself: an observer returning the pre-app BASE digest
        # (the old collision operand) must NOT be accepted — the launch operand is
        # the EFFECTIVE identity, not the base provenance.
        comp = self._prov().provision()
        with self.assertRaises(GnosisDeploymentError):
            GnosisDeploymentProvisioner.canonical_launch(
                comp, reobserve_f17=self._obs(F17_BASE))

    def test_application_tamper_still_refused(self) -> None:
        # application-manifest closed-world check remains complementary to the
        # effective identity; its specific message proves it fired independently.
        comp = self._prov().provision()
        target = self.pkg / "gnosis" / "director" / "cli.py"
        target.write_bytes(target.read_bytes() + b"\n# tamper\n")
        with self.assertRaises(GnosisDeploymentError) as cm:
            GnosisDeploymentProvisioner.canonical_launch(comp, reobserve_f17=self._obs())
        self.assertIn("application tree", str(cm.exception))

    def test_coherent_app_tamper_caught_by_record(self) -> None:
        # local manifest self-consistent -> only the trusted RECORD's application
        # digest catches it (isolates the record-level app check from measure()).
        comp = self._prov().provision()
        target = self.pkg / "gnosis" / "director" / "cli.py"
        target.write_bytes(target.read_bytes() + b"\n# coherent tamper\n")
        self._regen_manifest()
        with self.assertRaises(GnosisDeploymentError) as cm:
            GnosisDeploymentProvisioner.canonical_launch(comp, reobserve_f17=self._obs())
        self.assertIn("application tree digest", str(cm.exception))

    def test_wrong_schema_right_keys_rejected(self) -> None:
        # a record with all v2 keys but an old/unknown schema tag must fail closed
        # (guards against silently accepting a mislabeled record).
        comp = self._prov().provision()
        rp = comp.composed_record_path
        data = json.loads(rp.read_text(encoding="utf-8"))
        data["schema"] = "gnosis.composed_record.v1"
        rp.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(GnosisDeploymentError):
            GnosisDeploymentProvisioner.canonical_launch(comp, reobserve_f17=self._obs())


class TestRecordSchema(_Base):
    def _provision_and_read(self) -> tuple[Path, dict]:
        comp = self._prov().provision()   # provision ONCE per test
        rp = comp.composed_record_path
        return rp, json.loads(rp.read_text(encoding="utf-8"))

    def test_v2_roundtrip(self) -> None:
        rp, _ = self._provision_and_read()
        self.assertEqual(read_composed_record(rp).schema, "gnosis.composed_record.v2")

    def test_legacy_v1_record_fails_closed(self) -> None:
        # a v1 record (no effective field) is unsupported under the new path.
        rp, good = self._provision_and_read()
        legacy = {k: v for k, v in good.items() if k != "effective_deployment_digest"}
        legacy["schema"] = "gnosis.composed_record.v1"
        rp.write_text(json.dumps(legacy), encoding="utf-8")
        with self.assertRaises(GnosisDeploymentError):
            read_composed_record(rp)

    def test_missing_effective_rejected(self) -> None:
        rp, good = self._provision_and_read()
        bad = {k: v for k, v in good.items() if k != "effective_deployment_digest"}
        rp.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(GnosisDeploymentError):
            read_composed_record(rp)

    def test_effective_substitution_inconsistent(self) -> None:
        # mutate ONLY effective without recomputing the composed binding -> reject.
        rp, good = self._provision_and_read()
        good["effective_deployment_digest"] = "a" * 64
        rp.write_text(json.dumps(good), encoding="utf-8")
        with self.assertRaises(GnosisDeploymentError):
            read_composed_record(rp)

    def test_mix_and_match_operands_rejected(self) -> None:
        # base from A, app from B, effective from C with a stale composed -> reject.
        rp, good = self._provision_and_read()
        good["f17_deployment_digest"] = "1" * 64
        good["application_tree_digest"] = "2" * 64
        good["effective_deployment_digest"] = "3" * 64
        rp.write_text(json.dumps(good), encoding="utf-8")   # composed left stale
        with self.assertRaises(GnosisDeploymentError):
            read_composed_record(rp)


if __name__ == "__main__":
    unittest.main()
