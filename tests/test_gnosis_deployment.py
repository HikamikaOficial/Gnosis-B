"""F-33 Stage-2C-PACK-R2 — mandatory composed-identity enforcement.

Filesystem only; no OS provisioning, no provider calls. An F-17 base fixture
pre-populates the canonical package root with the trust-plane closure (as the real
F-17 Provisioner would), then the composed provisioner adds the operator stack,
writes the TRUSTED composed record into the (F-17) state base and enforces the
composed identity at provision time, pre-launch and startup.

Enforcement matrix:
  E1-E4    provision-time gate            (TestProvisionGate)
  E2/E4    provision-gate DIRECT assurance(TestProvisionGateAssurance)  [R2.1]
  E5-E10   pre-launch gate                (TestPreLaunchGate)
  E11-E13  coherent code+manifest tamper  (TestCoherentTamper)  [MANDATORY]
  E14-E18  startup self-verification      (TestStartupSelfVerify)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gnosis.provision.gnosis_deployment import (
    BaseDeployment,
    ComposedDeployment,
    GnosisDeploymentError,
    GnosisDeploymentProvisioner,
    composed_deployment_digest,
    composed_record_path,
    f17_publisher_files,
    read_composed_record,
)
from gnosis.provision.layout import DeploymentLayout
from gnosis.provision.operator_stack import (
    canonical_package_root,
)

SRC = Path(__file__).resolve().parents[1] / "src"
F17_DIGEST = "f" * 64        # base F-17 provenance (pre-application)
EFFECTIVE = "e" * 64         # R3D effective whole-root identity (post-application)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.layout = DeploymentLayout(
            code_base=str(self.root / "code"), state_base=str(self.root / "state"),
            work_base=str(self.root / "work"), release_id="R2")
        self.pkg = canonical_package_root(self.layout)
        self.pkg.mkdir(parents=True)
        Path(self.layout.state_base).mkdir(parents=True, exist_ok=True)
        for src, rel in f17_publisher_files(SRC):  # simulate the F-17 base
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
        return BaseDeployment(layout=self.layout, deployment_digest=F17_DIGEST,
                              rollback=_rb)

    def _prov(self) -> GnosisDeploymentProvisioner:
        return GnosisDeploymentProvisioner(
            SRC, base_provision=self._base_provision,
            observe_effective=self._observer(EFFECTIVE))

    def _observer(self, digest: str = EFFECTIVE):
        # the injected whole-root observer; defaults to the effective identity so
        # canonical_launch's fresh effective check passes on an unchanged tree.
        return lambda: digest


class TestProvisionGate(_Base):
    def test_e4_provision_returns_verified_and_writes_trusted_record(self) -> None:
        comp = self._prov().provision()
        self.assertIsInstance(comp, ComposedDeployment)
        self.assertEqual(self.base_calls, 1)
        # trusted record lives OUTSIDE the application tree (in the state base)
        self.assertEqual(comp.composed_record_path, composed_record_path(self.layout))
        self.assertTrue(comp.composed_record_path.is_file())
        # the trusted record is NOT inside the application package tree it authenticates
        self.assertFalse(str(comp.composed_record_path).startswith(str(self.pkg)))
        rec = read_composed_record(comp.composed_record_path)
        self.assertEqual(rec.application_tree_digest, comp.application.manifest.tree_digest)
        self.assertEqual(rec.f17_deployment_digest, F17_DIGEST)
        self.assertEqual(rec.effective_deployment_digest, EFFECTIVE)
        GnosisDeploymentProvisioner.verify(comp, expect_f17_digest=F17_DIGEST,
                                           expect_effective=EFFECTIVE)

    def test_only_one_trust_copy(self) -> None:
        comp = self._prov().provision()
        self.assertFalse(any(f.relpath.startswith("gnosis/trust/")
                             for f in comp.application.manifest.files))
        self.assertEqual(len(list((self.pkg).rglob("gnosis/trust/__init__.py"))), 1)

    def test_e1_application_failure_rolls_back_base(self) -> None:
        victim = self.pkg / "gnosis" / "director" / "cli.py"
        victim.parent.mkdir(parents=True, exist_ok=True)
        victim.write_bytes(b"F17\n")
        with self.assertRaises(GnosisDeploymentError):
            self._prov().provision()
        self.assertEqual(self.rollback_calls, 1)
        # no valid record left behind
        self.assertFalse(composed_record_path(self.layout).is_file())

    def test_e3_record_write_failure_rolls_back_base(self) -> None:
        # Make the record's parent a FILE so the atomic write cannot create it.
        rp = composed_record_path(self.layout)
        shutil.rmtree(rp.parent)
        rp.parent.write_bytes(b"not a dir")
        with self.assertRaises(GnosisDeploymentError):
            self._prov().provision()
        self.assertEqual(self.rollback_calls, 1)

    def test_e3b_rollback_failure_reports_unknown_state(self) -> None:
        victim = self.pkg / "gnosis" / "director" / "cli.py"
        victim.parent.mkdir(parents=True, exist_ok=True)
        victim.write_bytes(b"F17\n")

        def _base_bad_rollback() -> BaseDeployment:
            def _rb() -> None:
                raise RuntimeError("rollback boom")
            return BaseDeployment(layout=self.layout, deployment_digest=F17_DIGEST,
                                  rollback=_rb)
        prov = GnosisDeploymentProvisioner(SRC, base_provision=_base_bad_rollback,
                                          observe_effective=self._observer(EFFECTIVE))
        with self.assertRaises(GnosisDeploymentError) as cm:
            prov.provision()
        self.assertIn("unknown state", str(cm.exception))


class TestProvisionGateAssurance(_Base):
    """DIRECT assurance that the PROVISION-TIME composed-identity gate is invoked
    before provision() returns and that its failure fails closed. These observe the
    provision gate SPECIFICALLY (patching the provisioner's own verify), NOT a
    downstream canonical_launch / startup refusal. They are the assertions R2's
    E1-E4 lacked, and they are what makes mutants E-M1/E-M2 catchable."""

    def test_e4_final_verify_invoked_before_return_and_failure_blocks(self) -> None:
        # Force the FINAL provision-time verify to fail (a sentinel that only the
        # provision gate would observe). base + application deployment succeed;
        # the gate must run, provision() must NOT return, and rollback must fire.
        with mock.patch.object(
                GnosisDeploymentProvisioner, "verify",
                side_effect=GnosisDeploymentError("SENTINEL provision-verify")) as mv, \
                self.assertRaises(GnosisDeploymentError) as cm:
            self._prov().provision()
        self.assertEqual(mv.call_count, 1)              # the gate WAS invoked
        self.assertEqual(self.base_calls, 1)            # we entered the composed flow
        self.assertIn("SENTINEL provision-verify", str(cm.exception))  # propagated
        self.assertEqual(self.rollback_calls, 1)        # fail-closed rollback
        # the gate is on the ONLY return path: with it failing, no composed
        # deployment object is obtainable (the assertRaises above proves no return).

    def test_e2_composed_verify_failure_at_provision_fails_closed(self) -> None:
        # E2: a composed-identity verification failure at provision time (the final
        # verify is exactly the composed-identity check) prevents a valid result.
        with mock.patch.object(
                GnosisDeploymentProvisioner, "verify",
                side_effect=GnosisDeploymentError("composed deployment identity mismatch")):
            returned = None
            with self.assertRaises(GnosisDeploymentError):
                returned = self._prov().provision()
        self.assertIsNone(returned)
        self.assertEqual(self.rollback_calls, 1)

    def test_final_verify_failure_with_failing_rollback_is_unknown_state(self) -> None:
        # §8: final verify fails AND base rollback also fails -> fail closed as
        # "unknown state"; still no valid composed result.
        def _rb_boom() -> None:
            raise RuntimeError("rollback boom")

        def _base_bad_rollback() -> BaseDeployment:
            return BaseDeployment(layout=self.layout, deployment_digest=F17_DIGEST,
                                  rollback=_rb_boom)
        prov = GnosisDeploymentProvisioner(SRC, base_provision=_base_bad_rollback,
                                          observe_effective=self._observer(EFFECTIVE))
        with mock.patch.object(
                GnosisDeploymentProvisioner, "verify",
                side_effect=GnosisDeploymentError("SENTINEL")), \
                self.assertRaises(GnosisDeploymentError) as cm:
            prov.provision()
        self.assertIn("unknown state", str(cm.exception))


class TestComposedIdentity(_Base):
    def test_definition_deterministic_and_reverifies(self) -> None:
        comp = self._prov().provision()
        self.assertEqual(
            comp.composed_deployment_digest,
            composed_deployment_digest(F17_DIGEST, comp.application.manifest.tree_digest,
                                       EFFECTIVE))

    def test_changes_if_application_changes(self) -> None:
        self.assertNotEqual(composed_deployment_digest(F17_DIGEST, "a" * 64, EFFECTIVE),
                            composed_deployment_digest(F17_DIGEST, "b" * 64, EFFECTIVE))

    def test_changes_if_f17_digest_changes(self) -> None:
        self.assertNotEqual(composed_deployment_digest("d" * 64, "x" * 64, EFFECTIVE),
                            composed_deployment_digest("a" * 64, "x" * 64, EFFECTIVE))

    def test_record_reader_rejects_malformed(self) -> None:
        comp = self._prov().provision()
        rp = comp.composed_record_path
        good = json.loads(rp.read_text(encoding="utf-8"))
        # wrong schema
        bad = dict(good); bad["schema"] = "evil.v1"
        rp.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(GnosisDeploymentError):
            read_composed_record(rp)
        # truncated json
        rp.write_text('{"schema":', encoding="utf-8")
        with self.assertRaises(GnosisDeploymentError):
            read_composed_record(rp)
        # inconsistent composed digest
        bad2 = dict(good); bad2["composed_deployment_digest"] = "c" * 64
        rp.write_text(json.dumps(bad2), encoding="utf-8")
        with self.assertRaises(GnosisDeploymentError):
            read_composed_record(rp)


class TestPreLaunchGate(_Base):
    def _comp(self) -> ComposedDeployment:
        return self._prov().provision()

    def test_e5_valid_launch_returns_isolated_argv(self) -> None:
        comp = self._comp()
        argv = GnosisDeploymentProvisioner.canonical_launch(
            comp, reobserve_f17=self._observer())
        self.assertIn("-I", argv)
        self.assertIn("-B", argv)
        self.assertEqual(argv[0], str(Path(self.layout.runtime_executable)))
        self.assertTrue(argv[-1].endswith("operator_entry.py"))

    def test_e6_application_tamper_refused(self) -> None:
        comp = self._comp()
        target = self.pkg / "gnosis" / "director" / "composition.py"
        target.write_bytes(target.read_bytes() + b"# x\n")
        with self.assertRaises(GnosisDeploymentError):
            GnosisDeploymentProvisioner.canonical_launch(
                comp, reobserve_f17=self._observer())

    def test_e7_entry_tamper_refused(self) -> None:
        comp = self._comp()
        comp.operator_entry.write_bytes(comp.operator_entry.read_bytes() + b"#x")
        with self.assertRaises(GnosisDeploymentError):
            GnosisDeploymentProvisioner.canonical_launch(
                comp, reobserve_f17=self._observer())

    def test_e8_f17_digest_change_refused(self) -> None:
        comp = self._comp()
        with self.assertRaises(GnosisDeploymentError):
            GnosisDeploymentProvisioner.canonical_launch(
                comp, reobserve_f17=self._observer("d" * 64))

    def test_e9_application_digest_change_refused(self) -> None:
        comp = self._comp()
        target = self.pkg / "gnosis" / "director" / "cli.py"
        target.write_bytes(target.read_bytes() + b"\n# tamper\n")
        with self.assertRaises(GnosisDeploymentError):
            GnosisDeploymentProvisioner.canonical_launch(
                comp, reobserve_f17=self._observer())

    def test_e10_trusted_record_mismatch_refused(self) -> None:
        comp = self._comp()
        # write a self-consistent record whose application digest differs from
        # what is actually deployed.
        other_app = "a" * 64
        rec = {
            "schema": "gnosis.composed_record.v2",
            "f17_deployment_digest": F17_DIGEST,
            "application_tree_digest": other_app,
            "effective_deployment_digest": EFFECTIVE,
            "composed_deployment_digest": composed_deployment_digest(
                F17_DIGEST, other_app, EFFECTIVE),
            "package_root": str(self.pkg),
            "operator_entry_relpath": "operator_entry.py",
            "worker_image_relpath": "gnosis/director/deterministic_worker.py",
        }
        comp.composed_record_path.write_text(json.dumps(rec), encoding="utf-8")
        with self.assertRaises(GnosisDeploymentError):
            GnosisDeploymentProvisioner.canonical_launch(
                comp, reobserve_f17=self._observer())

    def test_launch_cannot_override_entry_or_disable_verification(self) -> None:
        # The API takes no entry/package-root/skip-verify parameter; the entry is
        # derived from the trusted record only.
        import inspect
        params = set(inspect.signature(
            GnosisDeploymentProvisioner.canonical_launch).parameters)
        self.assertEqual(params, {"comp", "reobserve_f17", "spawn", "operator_args"})


class TestCoherentTamper(_Base):
    """MANDATORY: internal self-consistency must not authorise a tampered tree."""

    def test_e11_app_plus_manifest_coherent_tamper_refused(self) -> None:
        comp = self._prov().provision()
        # tamper an application module AND regenerate APPLICATION.json to match it,
        # leaving the trusted record unchanged.
        target = self.pkg / "gnosis" / "director" / "composition.py"
        target.write_bytes(target.read_bytes() + b"\n# coherent tamper\n")
        self._regen_manifest()
        with self.assertRaises(GnosisDeploymentError):
            GnosisDeploymentProvisioner.canonical_launch(
                comp, reobserve_f17=self._observer())

    def test_e12_entry_plus_manifest_coherent_tamper_refused(self) -> None:
        comp = self._prov().provision()
        comp.operator_entry.write_bytes(comp.operator_entry.read_bytes() + b"#x")
        self._regen_manifest()
        with self.assertRaises(GnosisDeploymentError):
            GnosisDeploymentProvisioner.canonical_launch(
                comp, reobserve_f17=self._observer())

    def test_e13_internally_consistent_release_swap_refused(self) -> None:
        comp = self._prov().provision()
        # simulate swapping the whole release for another internally consistent one
        for mod in ("cli.py", "execution.py", "pipeline.py"):
            p = self.pkg / "gnosis" / "director" / mod
            if p.is_file():
                p.write_bytes(p.read_bytes() + b"\n# swapped release\n")
        self._regen_manifest()
        with self.assertRaises(GnosisDeploymentError):
            GnosisDeploymentProvisioner.canonical_launch(
                comp, reobserve_f17=self._observer())

    def _regen_manifest(self) -> None:
        # Recompute a fully coherent APPLICATION.json over the CURRENT (tampered)
        # deployed bytes, reusing the deployed relpath set so it stays canonical.
        import hashlib
        data = json.loads((self.pkg / "APPLICATION.json").read_text(encoding="utf-8"))
        files = []
        for ent in data["files"]:
            rel = ent["relpath"]
            digest = hashlib.sha256((self.pkg / rel).read_bytes()).hexdigest()
            files.append([rel, digest])
        files.sort(key=lambda x: x[0])
        tree = hashlib.sha256(
            json.dumps(files, separators=(",", ":")).encode("utf-8")).hexdigest()
        out = {"schema": "gnosis.application_manifest.v1", "tree_digest": tree,
               "files": [{"relpath": r, "digest": d} for r, d in files]}
        (self.pkg / "APPLICATION.json").write_text(json.dumps(out, indent=2),
                                                   encoding="utf-8")


class TestStartupSelfVerify(_Base):
    """Run the deployed measured entry with a real interpreter (as canonical_launch
    would), exercising the inline stdlib-only startup verifier."""

    def _run_entry(self, cwd: Path) -> subprocess.CompletedProcess[str]:
        comp = self._prov().provision()
        return subprocess.run(
            [sys.executable, "-I", "-B", str(comp.operator_entry)],
            cwd=str(cwd), capture_output=True, text=True, check=False)

    def _provisioned(self) -> ComposedDeployment:
        return self._prov().provision()

    def test_e14_valid_startup_reaches_cli_main(self) -> None:
        neutral = self.root / "neutral"; neutral.mkdir()
        r = self._run_entry(neutral)
        # verification must have PASSED (no fail-closed exit 70, no verifier error);
        # cli.main then runs on empty argv and returns its own usage code.
        self.assertNotEqual(r.returncode, 70, r.stderr[-400:])
        self.assertNotIn("startup composed-identity", r.stderr)

    def test_e15_local_manifest_ok_but_record_mismatch_aborts(self) -> None:
        comp = self._provisioned()
        other = "a" * 64
        rec = {
            "schema": "gnosis.composed_record.v2",
            "f17_deployment_digest": F17_DIGEST,
            "application_tree_digest": other,
            "effective_deployment_digest": EFFECTIVE,
            "composed_deployment_digest": composed_deployment_digest(
                F17_DIGEST, other, EFFECTIVE),
            "package_root": str(self.pkg),
            "operator_entry_relpath": "operator_entry.py",
            "worker_image_relpath": "gnosis/director/deterministic_worker.py",
        }
        comp.composed_record_path.write_text(json.dumps(rec), encoding="utf-8")
        neutral = self.root / "neutral"; neutral.mkdir()
        r = subprocess.run([sys.executable, "-I", "-B", str(comp.operator_entry)],
                           cwd=str(neutral), capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 70, r.stdout[-300:] + r.stderr[-300:])
        self.assertIn("TRUSTED composed record", r.stderr)

    def test_e16_malformed_manifest_aborts(self) -> None:
        comp = self._provisioned()
        (comp.package_root / "APPLICATION.json").write_text("{ this is not json",
                                                            encoding="utf-8")
        neutral = self.root / "neutral"; neutral.mkdir()
        r = subprocess.run([sys.executable, "-I", "-B", str(comp.operator_entry)],
                           cwd=str(neutral), capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 70, r.stderr[-300:])

    def test_e17_malformed_trusted_record_aborts(self) -> None:
        comp = self._provisioned()
        comp.composed_record_path.write_text('{"schema": "x"', encoding="utf-8")
        neutral = self.root / "neutral"; neutral.mkdir()
        r = subprocess.run([sys.executable, "-I", "-B", str(comp.operator_entry)],
                           cwd=str(neutral), capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 70, r.stderr[-300:])

    def test_startup_byte_tamper_without_manifest_regen_aborts(self) -> None:
        # A raw byte tamper (manifest NOT regenerated) must be caught by the
        # entry's per-file re-measurement before any application import.
        comp = self._provisioned()
        t = self.pkg / "gnosis" / "director" / "cli.py"
        t.write_bytes(t.read_bytes() + b"\n# raw tamper\n")
        neutral = self.root / "neutralbt"; neutral.mkdir()
        r = subprocess.run([sys.executable, "-I", "-B", str(comp.operator_entry)],
                           cwd=str(neutral), capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 70, r.stderr[-300:])

    def test_e18_cwd_shadow_does_not_win_after_self_check(self) -> None:
        comp = self._provisioned()
        shadow = self.root / "shadow"
        (shadow / "gnosis").mkdir(parents=True)
        (shadow / "gnosis" / "__init__.py").write_text(
            "raise RuntimeError('SHADOW-WINS')\n", encoding="utf-8")
        r = subprocess.run([sys.executable, "-I", "-B", str(comp.operator_entry)],
                           cwd=str(shadow), capture_output=True, text=True, check=False)
        self.assertNotIn("SHADOW-WINS", r.stderr)
        self.assertNotEqual(r.returncode, 70, r.stderr[-300:])


class TestProvenanceOneTree(_Base):
    def test_one_tree_no_checkout(self) -> None:
        comp = self._prov().provision()
        neutral = self.root / "neutral2"; neutral.mkdir()
        code = (
            f"import sys; sys.path.insert(0, r'{self.pkg}');"
            "import gnosis.director.cli as a, gnosis.trust.run_identity as c,"
            " gnosis.trust.orchestration as d, gnosis.director.deterministic_worker as e;"
            "print(a.__file__); print(c.__file__); print(d.__file__); print(e.__file__)")
        r = subprocess.run([sys.executable, "-I", "-B", "-c", code], cwd=str(neutral),
                           capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stderr[-300:])
        for line in r.stdout.splitlines():
            self.assertTrue(line.startswith(str(self.pkg)), line)
        _ = comp


if __name__ == "__main__":
    unittest.main()
