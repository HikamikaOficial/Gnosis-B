r"""F-33 Stage 2C-B1-R2B — access-diagnostic truthfulness remediation.

R2A acceptance FAILED with the sole blocker ACCESS DIAGNOSTIC = OVERCLAIM: the
`_access_contract` producer emitted authoritative PASS/FAIL from weak leaf-object
`icacls` substring evidence. R2B makes the producer conservative:

  * no authoritative PASS from a generic `NT SERVICE` substring;
  * no authoritative FAIL from friendly-name absence;
  * no full ancestor-access PASS from leaf-only evidence;
  * FAIL only on a proven DENY ACE for the *intended* service principal;
  * everything else -> UNKNOWN (honest uncertainty, not false certainty).

Filesystem/mock only; no OS provisioning, no provider calls, no behavior change.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "scripts", REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import stage2cb as s
import stage2cb_ops as sops

SVC = "GnosisPubS2CBProbe"


class _FakeF17:
    """Scripted, read-only stand-in for the F-17 RealOperations: returns canned
    `icacls` output and an optional resolved SID. No side effects."""

    def __init__(self, icacls: str | dict[str, str], sid: str | None = None) -> None:
        self._icacls = icacls
        self._sid = sid

    def run(self, argv: list[str]) -> tuple[int, str]:
        if argv and argv[0] == "icacls":
            out = self._icacls
            if isinstance(out, dict):
                return 0, out.get(argv[1], "")
            return 0, out
        if argv and argv[0] == "sc.exe":
            return 0, ("        STATE              : 1  STOPPED\n"
                       "        WIN32_EXIT_CODE    : 0  (0x0)")
        return 0, ""

    def resolve_sid(self, name: str) -> str:
        if self._sid is None:
            raise RuntimeError("account not resolvable")
        return self._sid


class _Layout:
    def __init__(self, root: Path) -> None:
        self.code_base = str(root)
        self.runtime_executable = str(root / "py.exe")
        self.service_entry = str(root / "svc.py")
        self.config_path = str(root / "config.json")


class _Config:
    def __init__(self, root: Path, name: str = SVC) -> None:
        self.layout = _Layout(root)
        self.service_name = name


class _AccessBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for leaf in ("py.exe", "svc.py", "config.json"):
            (self.root / leaf).write_text("x", encoding="utf-8")
        self.cfg = _Config(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _contract(self, icacls: str | dict[str, str], sid: str | None = None):
        ops = sops.WindowsRealOperations(authorized=True)
        ops._f17 = _FakeF17(icacls, sid=sid)          # inject scripted backend
        return ops._access_contract(self.cfg)


class TestProducerTruthfulness(_AccessBase):
    def test_trustedinstaller_no_false_pass(self) -> None:
        # §10 / ADM1: a generic NT SERVICE principal (TrustedInstaller) present,
        # the intended Publisher principal absent -> MUST NOT be authoritative PASS.
        acl = r"C:\x NT SERVICE\TrustedInstaller:(F)" + "\n" \
              r"        BUILTIN\Administrators:(F)"
        access, detail = self._contract(acl)
        self.assertNotEqual(access, "PASS")
        self.assertEqual(access, "UNKNOWN")
        self.assertFalse(detail["intended_principal_rendered"])
        self.assertFalse(detail["deny_semantics_proven"])

    def test_friendly_name_absence_no_false_fail(self) -> None:
        # §11 / ADM2: intended principal not rendered, no deny -> UNKNOWN, NOT FAIL.
        acl = r"C:\x BUILTIN\Administrators:(F)"
        access, _ = self._contract(acl)
        self.assertNotEqual(access, "FAIL")
        self.assertEqual(access, "UNKNOWN")

    def test_leaf_grant_is_not_ancestor_pass(self) -> None:
        # §12 / ADM3: intended principal present WITH a grant on every leaf still
        # cannot prove ancestor traversal -> NOT PASS; ancestors untested.
        acl = rf"C:\x NT SERVICE\{SVC}:(RX)" + "\n" \
              r"        BUILTIN\Administrators:(F)"
        access, detail = self._contract(acl)
        self.assertNotEqual(access, "PASS")
        self.assertEqual(access, "UNKNOWN")
        self.assertTrue(detail["intended_principal_rendered"])
        self.assertFalse(detail["ancestors_tested"])
        self.assertFalse(detail["grant_semantics_proven"])

    def test_authoritative_deny_is_fail(self) -> None:
        # §13 / ADM5: an explicit DENY ACE for the intended principal -> the only
        # path to an authoritative FAIL.
        acl = rf"C:\x NT SERVICE\{SVC}:(DENY)(R)" + "\n" \
              r"        BUILTIN\Administrators:(F)"
        access, detail = self._contract(acl)
        self.assertEqual(access, "FAIL")
        self.assertEqual(detail["verdict"], "DIRECTLY-DENIED")
        self.assertTrue(detail["deny_semantics_proven"])

    def test_deny_detected_via_resolved_sid(self) -> None:
        # ADM5 (SID form): friendly name absent, but the resolved SID carries a
        # DENY ACE -> authoritative FAIL (SID-based identity match).
        sid = "S-1-5-80-1111111111-2222222222"
        acl = rf"C:\x {sid}:(DENY)(R)"
        access, detail = self._contract(acl, sid=sid)
        self.assertEqual(access, "FAIL")
        self.assertTrue(detail["deny_semantics_proven"])

    def test_temp_path_alone_is_not_fail(self) -> None:
        # §18 / ADM6: temp deployment paths with no deny ACE -> UNKNOWN, never FAIL.
        acl = rf"C:\x NT SERVICE\{SVC}:(RX)"
        access, _ = self._contract(acl)
        self.assertNotEqual(access, "FAIL")

    def test_icacls_error_is_unknown_not_fail(self) -> None:
        class _Err(_FakeF17):
            def run(self, argv):
                if argv and argv[0] == "icacls":
                    return 1, "error"
                return 0, ""
        ops = sops.WindowsRealOperations(authorized=True)
        ops._f17 = _Err("")
        access, detail = ops._access_contract(self.cfg)
        self.assertEqual(access, "UNKNOWN")
        self.assertFalse(detail["deny_semantics_proven"])


class TestClassifierAccessContract(unittest.TestCase):
    def _pm(self, **over):
        base = {"service_running_observed": False, "runtime_exe_exists": True,
                "service_entry_exists": True, "config_path_exists": True,
                "service_exit_code": None, "access_contract": "UNKNOWN"}
        base.update(over)
        return base

    def test_unknown_access_is_not_access_failure(self) -> None:
        # §14 / ADM4: UNKNOWN access + no other authoritative discriminator ->
        # AMBIGUOUS, never DEPLOYMENT/ANCESTOR ACCESS FAILURE.
        cls = s.classify_publisher_failure(
            {"terminal_reason": "service-died"}, self._pm())
        self.assertNotEqual(cls, "DEPLOYMENT/ANCESTOR ACCESS FAILURE")
        self.assertEqual(cls, "AMBIGUOUS")

    def test_unknown_access_with_temp_path_not_access_failure(self) -> None:
        cls = s.classify_publisher_failure(
            {"terminal_reason": "service-died"},
            self._pm(deployment_root=r"C:\Users\x\AppData\Local\Temp\g"))
        self.assertNotEqual(cls, "DEPLOYMENT/ANCESTOR ACCESS FAILURE")

    def test_weak_fail_without_proof_is_gated(self) -> None:
        # a producer that emitted FAIL but attached a non-authoritative detail
        # (no deny proof) must NOT drive an access-failure classification.
        cls = s.classify_publisher_failure(
            {"terminal_reason": "service-died"},
            self._pm(access_contract="FAIL",
                     access_detail={"verdict": "UNKNOWN",
                                    "deny_semantics_proven": False}))
        self.assertNotEqual(cls, "DEPLOYMENT/ANCESTOR ACCESS FAILURE")

    def test_authoritative_deny_drives_access_failure(self) -> None:
        cls = s.classify_publisher_failure(
            {"terminal_reason": "service-died"},
            self._pm(service_exit_code=0, access_contract="FAIL",
                     access_detail={"verdict": "DIRECTLY-DENIED",
                                    "deny_semantics_proven": True}))
        self.assertEqual(cls, "DEPLOYMENT/ANCESTOR ACCESS FAILURE")


if __name__ == "__main__":
    unittest.main()
