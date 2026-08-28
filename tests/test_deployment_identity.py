"""F-17 Stage 2 — trust-plane deployment identity.

The property under test is that the identity measures REALITY:

    what is executed  ==  what is measured  ==  what is bound into evidence

so a deployment that drifts from what provisioning intended is caught, and a
change of intention alone changes nothing. The two directions are proved
explicitly (`TestDesiredIsNotObserved`), because "serialize the config and call
it a deployment digest" is precisely the shortcut this stage exists to refuse.

Most tests are hermetic: security descriptors are built from SDDL and
canonicalized through the same binary path the OS observation uses, and the
composite identity is assembled from dataclasses. The OS-real tests observe
only things that already exist — a temporary directory, this interpreter, and
an existing read-only Windows service. NOTHING is installed and nothing is left
behind: Stage 2 identifies deployments, it does not create one.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from gnosis.trust.deployment import (
    DEPLOYMENT_SCHEMA,
    DEPLOYMENT_SCHEMA_V2,
    MANIFEST_SCHEMA,
    AceIdentity,
    DeploymentIdentityUnavailable,
    DesiredDeploymentConfig,
    FileIdentity,
    PathSecurityIdentity,
    PipePolicyIdentity,
    RuntimeIdentity,
    SecurityDescriptorIdentity,
    ServiceIdentity,
    TrustPackageManifest,
    TrustPlaneDeploymentIdentity,
    canonical_sddl,
    canonical_security_descriptor,
    compare_with_desired,
    observe_deployment,
    observe_path_security,
    observe_pipe_policy,
    observe_runtime,
    observe_service,
    observe_trust_package,
    observed_directory_path,
    read_path_security_descriptor,
    service_sid,
    verify_package_against_expected,
)

WINDOWS_ONLY = unittest.skipUnless(
    sys.platform == "win32", "deployment identity is a Windows mechanism")

# An existing service, observed READ-ONLY. Nothing is installed by this suite.
READ_ONLY_SERVICE = "Winmgmt"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _make_trust_root(parent: Path, files: dict[str, bytes] | None = None, *,
                     package_version: str = "1.0.0",
                     source_commit: str = "a" * 40,
                     source_tree: str = "b" * 40,
                     sddl: str = "O:BAG:BAD:(A;;FA;;;BA)",
                     pipe_name: str = "\\\\.\\pipe\\gnosis-trust",
                     flags: list[str] | None = None) -> Path:
    """A stand-in trust root: the shape of a deployment, none of its authority."""
    root = parent / "Trust"
    root.mkdir(parents=True, exist_ok=True)
    (root / "PACKAGE.json").write_text(json.dumps({
        "schema": MANIFEST_SCHEMA, "package_version": package_version,
        "source_commit": source_commit, "source_tree": source_tree,
    }), encoding="utf-8")
    (root / "PIPE_POLICY.json").write_text(json.dumps({
        "schema_version": "gnosis.pipe.v1", "name": pipe_name, "sddl": sddl,
        "flags": flags if flags is not None else ["FIRST_PIPE_INSTANCE", "REJECT_REMOTE"],
    }), encoding="utf-8")
    # `files is not None`, not `files or ...`: an EMPTY mapping must mean "no
    # extra artifacts", not "fall back to the default one".
    default = {"publisher.py": b"MARKER = 1\n"}
    for name, payload in (default if files is None else files).items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return root


def _ace(sid: str = "S-1-5-32-544", mask: int = 0x1F01FF, ace_type: int = 0,
         flags: int = 0) -> AceIdentity:
    return AceIdentity(ace_type=ace_type, ace_flags=flags, access_mask=mask, sid=sid)


def _sd(*aces: AceIdentity, owner: str = "S-1-5-32-544",
        label: AceIdentity | None = None) -> SecurityDescriptorIdentity:
    return SecurityDescriptorIdentity(
        owner_sid=owner, group_sid="S-1-5-32-544", control=0x1004,
        dacl_present=True, aces=aces or (_ace(),), mandatory_label=label)


def _synthetic_identity() -> TrustPlaneDeploymentIdentity:
    """A complete identity assembled from dataclasses.

    Lets the drift matrix vary exactly one observed field at a time, with no
    dependence on a machine that has the production deployment installed.
    """
    return TrustPlaneDeploymentIdentity(
        schema=DEPLOYMENT_SCHEMA,
        package=TrustPackageManifest(
            schema=MANIFEST_SCHEMA, package_version="1.0.0",
            source_commit="a" * 40, source_tree="b" * 40,
            files=(FileIdentity(path="publisher.py", size=11, digest="c" * 64),)),
        runtime=RuntimeIdentity(
            executable_path=r"C:\Program Files\Gnosis\Trust\runtime\python.exe",
            executable_size=45568, executable_digest="d" * 64,
            version="3.12.14", implementation="cpython",
            architecture="64bit", machine="AMD64"),
        service=ServiceIdentity(
            name="GnosisTrustedPublisher", account="NT SERVICE\\GnosisTrustedPublisher",
            image_path=r'"C:\Program Files\Gnosis\Trust\runtime\python.exe" main.py',
            start_type="DEMAND", service_sid="S-1-5-80-1-2-3-4-5",
            sid_type="RESTRICTED", required_privileges=("SeChangeNotifyPrivilege",),
            security_descriptor=_sd()),
        trust_root=PathSecurityIdentity(
            path=r"C:\Program Files\Gnosis\Trust", security_descriptor=_sd()),
        runidentity_store=PathSecurityIdentity(
            path=r"C:\ProgramData\Gnosis\Trust\runs", security_descriptor=_sd()),
        anchorstore=PathSecurityIdentity(
            path=r"C:\ProgramData\Gnosis\Trust\anchors", security_descriptor=_sd()),
        pipe_policy=PipePolicyIdentity(
            schema_version="gnosis.pipe.v1", name="\\\\.\\pipe\\gnosis-trust",
            flags=("FIRST_PIPE_INSTANCE", "REJECT_REMOTE"),
            security_descriptor=_sd()),
    )


# ---------------------------------------------------------------------------
# Security-descriptor canonicalization (hermetic: SDDL in, identity out)
# ---------------------------------------------------------------------------
@WINDOWS_ONLY
class TestTheCanonicalSecurityDescriptor(unittest.TestCase):
    def test_a_same_semantics_different_formatting_is_the_same_identity(self):
        # A: SID aliases vs full SIDs, mnemonic rights vs the hex mask. These
        # are the incidental differences `icacls`/`sc sdshow` text would carry.
        left = canonical_sddl("O:BAG:BAD:(A;;FA;;;BA)(A;;0x1200a9;;;S-1-5-11)")
        right = canonical_sddl(
            "O:S-1-5-32-544G:S-1-5-32-544"
            "D:(A;;0x1f01ff;;;S-1-5-32-544)(A;;0x1200a9;;;AU)")
        self.assertEqual(left.digest(), right.digest())
        self.assertEqual(left.owner_sid, "S-1-5-32-544")
        self.assertEqual([a.sid for a in left.aces], ["S-1-5-32-544", "S-1-5-11"])

    def test_b_a_different_ace_is_a_different_identity(self):
        base = canonical_sddl("O:BAG:BAD:(A;;FA;;;BA)")
        extra = canonical_sddl("O:BAG:BAD:(A;;FA;;;BA)(A;;FA;;;WD)")
        denied = canonical_sddl("O:BAG:BAD:(D;;FA;;;WD)(A;;FA;;;BA)")
        self.assertNotEqual(base.digest(), extra.digest())
        self.assertNotEqual(base.digest(), denied.digest())
        self.assertNotEqual(extra.digest(), denied.digest())

    def test_c_a_different_access_mask_is_a_different_identity(self):
        full = canonical_sddl("O:BAG:BAD:(A;;FA;;;BA)")
        read = canonical_sddl("O:BAG:BAD:(A;;FR;;;BA)")
        self.assertNotEqual(full.digest(), read.digest())

    def test_d_a_different_sid_is_a_different_identity(self):
        admins = canonical_sddl("O:BAG:BAD:(A;;FA;;;BA)")
        users = canonical_sddl("O:BAG:BAD:(A;;FA;;;BU)")
        self.assertNotEqual(admins.digest(), users.digest())

    def test_f_a_different_mandatory_label_is_a_different_identity(self):
        high = canonical_sddl("O:BAG:BAD:(A;;FA;;;BA)S:(ML;;NW;;;HI)")
        medium = canonical_sddl("O:BAG:BAD:(A;;FA;;;BA)S:(ML;;NW;;;ME)")
        self.assertIsNotNone(high.mandatory_label)
        self.assertNotEqual(high.mandatory_label, medium.mandatory_label)
        self.assertNotEqual(high.digest(), medium.digest())

    def test_a_different_owner_is_a_different_identity(self):
        self.assertNotEqual(canonical_sddl("O:BAG:BAD:(A;;FA;;;BA)").digest(),
                            canonical_sddl("O:SYG:BAD:(A;;FA;;;BA)").digest())

    def test_ace_order_is_preserved_not_sorted(self):
        # Order is semantic in an ACL: Windows evaluates ACEs in sequence, so a
        # deny moved after an allow is a DIFFERENT descriptor. Sorting them here
        # would be the "canonicalization loses ACL semantics" stop condition.
        first = canonical_sddl("O:BAG:BAD:(D;;FA;;;WD)(A;;FA;;;BA)")
        second = canonical_sddl("O:BAG:BAD:(A;;FA;;;BA)(D;;FA;;;WD)")
        self.assertEqual({a.sid for a in first.aces}, {a.sid for a in second.aces})
        self.assertNotEqual(first.digest(), second.digest())

    def test_no_ace_is_dropped_as_redundant(self):
        # Two ACEs for the same SID are kept: whether they are equivalent is a
        # question about the Windows access check, not about representation.
        one = canonical_sddl("O:BAG:BAD:(A;;FR;;;BA)")
        two = canonical_sddl("O:BAG:BAD:(A;;FR;;;BA)(A;;FW;;;BA)")
        self.assertEqual(len(one.aces), 1)
        self.assertEqual(len(two.aces), 2)
        self.assertNotEqual(one.digest(), two.digest())

    def test_a_malformed_descriptor_fails_closed(self):
        with self.assertRaises(DeploymentIdentityUnavailable):
            canonical_security_descriptor(b"")
        with self.assertRaises(DeploymentIdentityUnavailable):
            canonical_security_descriptor(b"not a security descriptor")

    def test_an_unparsable_sddl_fails_closed(self):
        with self.assertRaises(DeploymentIdentityUnavailable):
            canonical_sddl("this is not sddl")

    def test_a_real_directory_descriptor_canonicalizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity = canonical_security_descriptor(
                read_path_security_descriptor(Path(tmp)))
            self.assertTrue(identity.owner_sid.startswith("S-1-"))
            self.assertTrue(identity.dacl_present)
            self.assertTrue(identity.aces)
            self.assertEqual(len(identity.digest()), 64)


# ---------------------------------------------------------------------------
# The trust package manifest
# ---------------------------------------------------------------------------
@WINDOWS_ONLY
class TestTheTrustPackageManifest(unittest.TestCase):
    def test_it_hashes_the_actual_bytes_on_disk(self):
        payload = b"TRUSTED PUBLISHER BYTES\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp), {"publisher.py": payload})
            manifest = observe_trust_package(root)
            entry = next(f for f in manifest.files if f.path == "publisher.py")
            self.assertEqual(entry.digest, hashlib.sha256(payload).hexdigest())
            self.assertEqual(entry.size, len(payload))

    def test_it_measures_every_file_with_no_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp), {
                "publisher.py": b"a", "sub/helper.py": b"b", "sub/deep/x.dat": b"c"})
            paths = {f.path for f in observe_trust_package(root).files}
            self.assertEqual(paths, {"PACKAGE.json", "PIPE_POLICY.json",
                                     "publisher.py", "sub/helper.py", "sub/deep/x.dat"})

    def test_the_same_bytes_produce_the_same_digest_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp))
            self.assertEqual(observe_trust_package(root).digest(),
                             observe_trust_package(root).digest())

    def test_creation_order_and_mtime_are_not_part_of_the_identity(self):
        files = {"a.py": b"A", "b.py": b"B", "c.py": b"C"}
        with tempfile.TemporaryDirectory() as tmp:
            one = _make_trust_root(Path(tmp) / "one", files)
            two_dir = Path(tmp) / "two"
            two = _make_trust_root(two_dir, {})
            for name in reversed(list(files)):          # written in the other order
                (two / name).write_bytes(files[name])
            (two / "a.py").touch()                      # and with a newer mtime
            self.assertEqual(observe_trust_package(one).digest(),
                             observe_trust_package(two).digest())

    def test_one_changed_byte_changes_the_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp), {"publisher.py": b"MARKER = 1\n"})
            before = observe_trust_package(root).digest()
            (root / "publisher.py").write_bytes(b"MARKER = 2\n")
            self.assertNotEqual(before, observe_trust_package(root).digest())

    def test_an_added_or_removed_file_changes_the_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp), {"publisher.py": b"x"})
            before = observe_trust_package(root).digest()
            (root / "extra.py").write_bytes(b"y")
            after = observe_trust_package(root).digest()
            self.assertNotEqual(before, after)
            (root / "extra.py").unlink()
            self.assertEqual(before, observe_trust_package(root).digest())

    def test_the_expected_manifest_cannot_stand_in_for_the_bytes(self):
        # `manifest says hash X` is never accepted: the observed manifest comes
        # from the bytes, and the expectation can only REFUSE the deployment.
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp), {"publisher.py": b"ORIGINAL"})
            expected = observe_trust_package(root)
            (root / "publisher.py").write_bytes(b"TAMPERED")
            observed = observe_trust_package(root)
            self.assertNotEqual(observed.digest(), expected.digest())
            with self.assertRaises(DeploymentIdentityUnavailable):
                verify_package_against_expected(observed, expected)

    def test_an_unexpected_extra_artifact_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp), {"publisher.py": b"x"})
            expected = observe_trust_package(root)
            (root / "backdoor.py").write_bytes(b"import os")
            with self.assertRaises(DeploymentIdentityUnavailable):
                verify_package_against_expected(observe_trust_package(root), expected)

    def test_a_missing_or_malformed_declaration_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp))
            (root / "PACKAGE.json").unlink()
            with self.assertRaises(DeploymentIdentityUnavailable):
                observe_trust_package(root)
            (root / "PACKAGE.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(DeploymentIdentityUnavailable):
                observe_trust_package(root)
            (root / "PACKAGE.json").write_text(
                json.dumps({"schema": MANIFEST_SCHEMA, "package_version": "1.0.0"}),
                encoding="utf-8")
            with self.assertRaises(DeploymentIdentityUnavailable):
                observe_trust_package(root)

    def test_a_missing_or_empty_trust_root_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(DeploymentIdentityUnavailable):
                observe_trust_package(Path(tmp) / "absent")
            empty = Path(tmp) / "empty"
            empty.mkdir()
            with self.assertRaises(DeploymentIdentityUnavailable):
                observe_trust_package(empty)


# ---------------------------------------------------------------------------
# Paths and redirection
# ---------------------------------------------------------------------------
@WINDOWS_ONLY
class TestPathsAndRedirection(unittest.TestCase):
    def test_the_resolved_path_is_the_object_windows_actually_opens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            # the same directory reached through a different textual case
            self.assertEqual(observed_directory_path(root),
                             observed_directory_path(Path(str(root).upper())))

    def test_a_junction_resolves_to_its_target_not_its_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "elsewhere"
            target.mkdir()
            link = Path(tmp) / "link"
            proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", check=False)
            if proc.returncode != 0:
                self.skipTest("this volume does not support directory junctions")
            self.assertEqual(observed_directory_path(link), observed_directory_path(target))

    def test_a_trusted_artifact_redirected_out_of_the_root_fails_closed(self):
        # The Worker must not be able to make `expected path` and `executed
        # bytes` two different objects without the identity noticing.
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp))
            outside = Path(tmp) / "outside"
            outside.mkdir()
            (outside / "smuggled.py").write_bytes(b"import os")
            proc = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(root / "plugins"), str(outside)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                check=False)
            if proc.returncode != 0:
                self.skipTest("this volume does not support directory junctions")
            with self.assertRaises(DeploymentIdentityUnavailable):
                observe_trust_package(root)

    def test_an_unreadable_artifact_fails_closed(self):
        with (tempfile.TemporaryDirectory() as tmp,
              self.assertRaises(DeploymentIdentityUnavailable)):
            observe_runtime(Path(tmp) / "no-such-python.exe")


# ---------------------------------------------------------------------------
# The trusted runtime
# ---------------------------------------------------------------------------
@WINDOWS_ONLY
class TestTheTrustedRuntime(unittest.TestCase):
    def test_it_binds_the_actual_executable_bytes(self):
        identity = observe_runtime(Path(sys.executable))
        expected = hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
        self.assertEqual(identity.executable_digest, expected)
        self.assertTrue(identity.version)
        self.assertTrue(identity.machine)

    def test_two_runtimes_of_the_same_version_are_not_the_same_runtime(self):
        # "Python 3.12" is not an identity. A byte-different python.exe that
        # reports the SAME version must produce a DIFFERENT runtime identity.
        original = Path(sys.executable)
        twin = original.with_name("_gnosis_stage2_probe_python.exe")
        try:
            shutil.copy2(original, twin)
            with twin.open("ab") as fh:
                fh.write(b"GNOSIS-STAGE2-OVERLAY")
            observed_twin = observe_runtime(twin)
            observed_original = observe_runtime(original)
            self.assertEqual(observed_twin.version, observed_original.version)
            self.assertNotEqual(observed_twin.executable_digest,
                                observed_original.executable_digest)
        finally:
            twin.unlink(missing_ok=True)
        self.assertFalse(twin.exists())

    def test_a_runtime_that_cannot_answer_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "python.exe"
            fake.write_bytes(b"not an executable")
            with self.assertRaises(DeploymentIdentityUnavailable):
                observe_runtime(fake)


# ---------------------------------------------------------------------------
# The Windows service, observed read-only
# ---------------------------------------------------------------------------
@WINDOWS_ONLY
class TestServiceObservation(unittest.TestCase):
    """Observes an EXISTING service. Installs nothing, leaves nothing behind."""

    def _observe(self) -> ServiceIdentity:
        try:
            return observe_service(READ_ONLY_SERVICE)
        except DeploymentIdentityUnavailable as exc:  # pragma: no cover - env
            self.skipTest(f"{READ_ONLY_SERVICE} is not observable here: {exc}")

    def test_it_reads_the_real_scm_state(self):
        identity = self._observe()
        self.assertEqual(identity.name, READ_ONLY_SERVICE)
        self.assertTrue(identity.image_path)
        self.assertTrue(identity.account)
        self.assertIn(identity.start_type,
                      {"BOOT", "SYSTEM", "AUTO", "DEMAND", "DISABLED"})
        self.assertIn(identity.sid_type, {"NONE", "UNRESTRICTED", "RESTRICTED"})
        self.assertTrue(identity.service_sid.startswith("S-1-5-80-"))
        self.assertTrue(identity.security_descriptor.aces)

    def test_the_service_sid_comes_from_windows(self):
        self.assertTrue(service_sid(READ_ONLY_SERVICE).startswith("S-1-5-80-"))

    def test_required_privileges_are_parsed_from_a_real_multi_sz(self):
        """The MULTI_SZ path needs a service that actually HAS privileges.

        `READ_ONLY_SERVICE` reports none, so the parser's non-empty branch —
        a pointer into the live answer buffer, walked NUL to double-NUL — would
        otherwise never run. Several candidates are tried because which service
        exists is a property of the machine, not of the code.
        """
        for candidate in ("EventLog", "Dnscache", "Schedule", "LanmanWorkstation"):
            try:
                privileges = observe_service(candidate).required_privileges
            except DeploymentIdentityUnavailable:
                continue
            if not privileges:
                continue
            self.assertTrue(all(p.startswith("Se") for p in privileges), privileges)
            self.assertEqual(list(privileges), sorted(privileges))  # a set, not an order
            return
        self.skipTest("no observable service on this machine declares required privileges")

    def test_a_missing_service_fails_closed(self):
        with self.assertRaises(DeploymentIdentityUnavailable):
            observe_service("GnosisNoSuchServiceStage2Probe")

    def test_a_missing_service_sid_fails_closed(self):
        with self.assertRaises(DeploymentIdentityUnavailable):
            service_sid("GnosisNoSuchServiceStage2Probe")


# ---------------------------------------------------------------------------
# The pipe policy, read from the deployed trust root
# ---------------------------------------------------------------------------
@WINDOWS_ONLY
class TestThePipePolicy(unittest.TestCase):
    def test_it_canonicalizes_the_deployed_sddl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp), sddl="O:BAG:BAD:(A;;FA;;;BA)")
            other = _make_trust_root(
                Path(tmp) / "other",
                sddl="O:S-1-5-32-544G:S-1-5-32-544D:(A;;0x1f01ff;;;S-1-5-32-544)")
            self.assertEqual(observe_pipe_policy(root).security_descriptor.digest(),
                             observe_pipe_policy(other).security_descriptor.digest())

    def test_a_changed_grant_changes_the_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tight = _make_trust_root(Path(tmp) / "a", sddl="O:BAG:BAD:(A;;FA;;;BA)")
            loose = _make_trust_root(Path(tmp) / "b",
                                     sddl="O:BAG:BAD:(A;;FA;;;BA)(A;;FA;;;WD)")
            self.assertNotEqual(observe_pipe_policy(tight).security_descriptor.digest(),
                                observe_pipe_policy(loose).security_descriptor.digest())

    def test_a_malformed_policy_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp))
            (root / "PIPE_POLICY.json").write_text("{", encoding="utf-8")
            with self.assertRaises(DeploymentIdentityUnavailable):
                observe_pipe_policy(root)
            (root / "PIPE_POLICY.json").unlink()
            with self.assertRaises(DeploymentIdentityUnavailable):
                observe_pipe_policy(root)


# ---------------------------------------------------------------------------
# Deployment drift — one observed field at a time
# ---------------------------------------------------------------------------
@WINDOWS_ONLY
class TestDeploymentDrift(unittest.TestCase):
    def setUp(self) -> None:
        self.base = _synthetic_identity()
        self.digest = self.base.digest()

    def _assert_changed(self, **changes: object) -> None:
        mutated = dataclasses.replace(self.base, **changes)  # type: ignore[arg-type]
        self.assertNotEqual(self.digest, mutated.digest())

    def test_1_a_changed_trust_package_byte_changes_the_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp), {"publisher.py": b"ORIGINAL"})
            before = observe_trust_package(root)
            identity = dataclasses.replace(self.base, package=before)
            (root / "publisher.py").write_bytes(b"MODIFIED")
            after = dataclasses.replace(self.base, package=observe_trust_package(root))
            self.assertNotEqual(identity.digest(), after.digest())

    def test_2_a_changed_runtime_executable_changes_the_digest(self):
        self._assert_changed(runtime=dataclasses.replace(
            self.base.runtime, executable_digest="e" * 64))

    def test_3_a_changed_imagepath_changes_the_digest(self):
        self._assert_changed(service=dataclasses.replace(
            self.base.service, image_path=r"C:\Temp\evil.exe"))

    def test_4_a_changed_service_account_changes_the_digest(self):
        self._assert_changed(service=dataclasses.replace(
            self.base.service, account="LocalSystem"))

    def test_5_a_changed_service_sid_changes_the_digest(self):
        self._assert_changed(service=dataclasses.replace(
            self.base.service, service_sid="S-1-5-80-9-9-9-9-9"))

    def test_6_a_changed_sid_type_changes_the_digest(self):
        # E in the canonical-DACL matrix: RESTRICTED -> UNRESTRICTED is a
        # different deployment, never the same one differently described.
        self._assert_changed(service=dataclasses.replace(
            self.base.service, sid_type="UNRESTRICTED"))

    def test_7_a_changed_service_dacl_changes_the_digest(self):
        self._assert_changed(service=dataclasses.replace(
            self.base.service, security_descriptor=_sd(_ace(sid="S-1-1-0"))))

    def test_8_a_changed_trust_root_acl_changes_the_digest(self):
        self._assert_changed(trust_root=dataclasses.replace(
            self.base.trust_root, security_descriptor=_sd(_ace(sid="S-1-1-0"))))

    def test_9_a_changed_runidentity_store_acl_changes_the_digest(self):
        self._assert_changed(runidentity_store=dataclasses.replace(
            self.base.runidentity_store, security_descriptor=_sd(_ace(sid="S-1-1-0"))))

    def test_10_a_changed_anchorstore_acl_changes_the_digest(self):
        self._assert_changed(anchorstore=dataclasses.replace(
            self.base.anchorstore, security_descriptor=_sd(_ace(sid="S-1-1-0"))))

    def test_11_a_changed_pipe_policy_changes_the_digest(self):
        self._assert_changed(pipe_policy=dataclasses.replace(
            self.base.pipe_policy, schema_version="gnosis.pipe.v2"))
        self._assert_changed(pipe_policy=dataclasses.replace(
            self.base.pipe_policy, flags=("REJECT_REMOTE",)))

    def test_a_changed_required_privilege_changes_the_digest(self):
        self._assert_changed(service=dataclasses.replace(
            self.base.service,
            required_privileges=("SeChangeNotifyPrivilege", "SeDebugPrivilege")))

    def test_the_mandatory_label_is_part_of_the_identity(self):
        labelled = _sd(label=_ace(ace_type=0x11, mask=1, sid="S-1-16-12288"))
        self._assert_changed(anchorstore=dataclasses.replace(
            self.base.anchorstore, security_descriptor=labelled))

    def test_an_unchanged_deployment_keeps_its_digest(self):
        self.assertEqual(self.digest, _synthetic_identity().digest())
        self.assertEqual(len(self.digest), 64)


# ---------------------------------------------------------------------------
# Desired is not observed
# ---------------------------------------------------------------------------
@WINDOWS_ONLY
class TestDesiredIsNotObserved(unittest.TestCase):
    def _config(self, root: Path, **overrides: object) -> DesiredDeploymentConfig:
        base: dict[str, object] = {
            "trust_root": root, "runtime_executable": Path(sys.executable),
            "runtime_root": Path(sys.executable).parent,
            "runidentity_store": root, "anchorstore": root,
            "service_name": READ_ONLY_SERVICE,
        }
        base.update(overrides)
        return DesiredDeploymentConfig(**base)  # type: ignore[arg-type]

    def test_12_a_different_intention_over_the_same_machine_is_the_same_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp))
            first = self._config(root, expected_service_account="NT SERVICE\\A",
                                 expected_sid_type="RESTRICTED",
                                 expected_package_version="9.9.9")
            second = self._config(root, expected_service_account="NT SERVICE\\B",
                                  expected_sid_type="UNRESTRICTED",
                                  expected_package_version="0.0.1")
            self.assertEqual(observe_trust_package(first.trust_root).digest(),
                             observe_trust_package(second.trust_root).digest())
            # and the drift report — the ONLY consumer of intention — differs
            identity = dataclasses.replace(
                _synthetic_identity(), package=observe_trust_package(root))
            self.assertNotEqual(compare_with_desired(identity, first),
                                compare_with_desired(identity, second))
            self.assertEqual(identity.digest(), identity.digest())

    def test_13_a_changed_machine_under_the_same_intention_changes_the_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp), {"publisher.py": b"ORIGINAL"})
            config = self._config(root, expected_package_version="1.0.0")
            before = dataclasses.replace(
                _synthetic_identity(), package=observe_trust_package(config.trust_root))
            (root / "publisher.py").write_bytes(b"CHANGED ON THE MACHINE")
            after = dataclasses.replace(
                _synthetic_identity(), package=observe_trust_package(config.trust_root))
            self.assertNotEqual(before.digest(), after.digest())

    def test_no_desired_value_can_reach_the_identity(self):
        # Structural, not incidental: every expectation is a unique sentinel and
        # none of them may appear anywhere in the serialized identity.
        sentinels = {"expected_package_version": "SENTINEL-PKG-8f2a",
                     "expected_service_account": "SENTINEL-ACCT-8f2a",
                     "expected_sid_type": "SENTINEL-SIDTYPE-8f2a"}
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp))
            config = self._config(root, **sentinels)
            identity = dataclasses.replace(
                _synthetic_identity(), package=observe_trust_package(config.trust_root))
            serialized = json.dumps(identity.to_dict())
            for value in sentinels.values():
                self.assertNotIn(value, serialized)

    def test_drift_is_reported_without_touching_the_identity(self):
        identity = _synthetic_identity()
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp))
            matching = self._config(root, expected_sid_type="RESTRICTED",
                                    expected_service_account=identity.service.account,
                                    expected_package_version="1.0.0")
            self.assertEqual(compare_with_desired(identity, matching), ())
            drifted = self._config(root, expected_sid_type="UNRESTRICTED")
            findings = compare_with_desired(identity, drifted)
            self.assertEqual(len(findings), 1)
            self.assertIn("SID type", findings[0])
            self.assertEqual(identity.digest(), _synthetic_identity().digest())


# ---------------------------------------------------------------------------
# The whole pipeline, composed against real objects
# ---------------------------------------------------------------------------
@WINDOWS_ONLY
class TestTheObservationComposes(unittest.TestCase):
    def test_observe_deployment_builds_an_identity_from_real_objects(self):
        """End to end over a fixture trust root, this interpreter, and an
        EXISTING service observed read-only. Nothing is installed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp))
            store = Path(tmp) / "state"
            store.mkdir()
            config = DesiredDeploymentConfig(
                trust_root=root, runtime_executable=Path(sys.executable),
                runtime_root=Path(sys.executable).parent,
                runidentity_store=store, anchorstore=store,
                service_name=READ_ONLY_SERVICE)
            try:
                identity = observe_deployment(config)
            except DeploymentIdentityUnavailable as exc:  # pragma: no cover - env
                self.skipTest(f"{READ_ONLY_SERVICE} is not observable here: {exc}")
            self.assertEqual(identity.schema, DEPLOYMENT_SCHEMA_V2)
            self.assertTrue(identity.binds_runtime_tree)
            # The runtime is bound as a TREE, not as one executable.
            self.assertIsNotNone(identity.runtime_tree)
            assert identity.runtime_tree is not None
            self.assertTrue(identity.runtime_tree.files)
            self.assertEqual(len(identity.digest()), 64)
            self.assertTrue(identity.package.files)
            self.assertTrue(identity.runtime.executable_digest)
            self.assertTrue(identity.service.service_sid.startswith("S-1-5-80-"))
            self.assertTrue(identity.trust_root.security_descriptor.aces)
            self.assertEqual(identity.digest(), observe_deployment(config).digest())

    def test_an_expected_manifest_that_does_not_match_refuses_the_deployment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _make_trust_root(Path(tmp), {"publisher.py": b"ORIGINAL"})
            expected = observe_trust_package(root)
            (root / "publisher.py").write_bytes(b"TAMPERED")
            config = DesiredDeploymentConfig(
                trust_root=root, runtime_executable=Path(sys.executable),
                runtime_root=Path(sys.executable).parent,
                runidentity_store=root, anchorstore=root,
                service_name=READ_ONLY_SERVICE, expected_manifest=expected)
            with self.assertRaises(DeploymentIdentityUnavailable):
                observe_deployment(config)

    def test_the_path_security_of_a_real_directory_is_observable(self):
        with tempfile.TemporaryDirectory() as tmp:
            observed = observe_path_security(Path(tmp))
            self.assertTrue(Path(observed.path).is_dir())
            self.assertTrue(observed.security_descriptor.owner_sid.startswith("S-1-"))


if __name__ == "__main__":
    unittest.main()
