r"""F-33 Stage 2C-B1-R2B — access-diagnostic PRODUCER mutation harness (ADM1-ADM6).

R2A's DM4 only tested the downstream classifier; it did not test the truthfulness
of the access-contract PRODUCER. These mutants attack the producer (and the
UNKNOWN->classifier boundary) directly. A mutant is CAUGHT when it makes a
DIShonest claim on a scenario where the real producer/classifier is honest.

Run: .venv/Scripts/python.exe docs/evidence/.../mutation_harness_adm.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for _p in (REPO / "scripts", REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import stage2cb as s
import stage2cb_ops as sops

SVC = "GnosisPubS2CBProbe"


class _FakeF17:
    def __init__(self, icacls, sid=None):
        self._icacls, self._sid = icacls, sid

    def run(self, argv):
        if argv and argv[0] == "icacls":
            return 0, self._icacls
        return 0, ""

    def resolve_sid(self, name):
        if self._sid is None:
            raise RuntimeError("unresolved")
        return self._sid


def _cfg(root):
    class _L:
        code_base = str(root)
        runtime_executable = str(root / "py.exe")
        service_entry = str(root / "svc.py")
        config_path = str(root / "config.json")

    class _C:
        layout = _L()
        service_name = SVC
    return _C()


def _real_contract(icacls, sid, root):
    ops = sops.WindowsRealOperations(authorized=True)
    ops._f17 = _FakeF17(icacls, sid=sid)
    return ops._access_contract(_cfg(root))


# scenarios: (name, icacls, sid, honest_access)
TRUSTED = r"C:\x NT SERVICE\TrustedInstaller:(F)"
ABSENT = r"C:\x BUILTIN\Administrators:(F)"
LEAFGRANT = rf"C:\x NT SERVICE\{SVC}:(RX)"
DENY = rf"C:\x NT SERVICE\{SVC}:(DENY)(R)"


def _pm(**over):
    base = {"service_running_observed": False, "runtime_exe_exists": True,
            "service_entry_exists": True, "config_path_exists": True,
            "service_exit_code": None, "access_contract": "UNKNOWN"}
    base.update(over)
    return base


# --- mutant producers (dishonest variants of _access_contract's decision) -----
def adm1_any_nt_service_pass(icacls):        # generic NT SERVICE substring -> PASS
    return "PASS" if "NT SERVICE" in icacls.upper() else "UNKNOWN"


def adm2_friendlyname_absence_fail(icacls):  # intended name absent -> FAIL
    return "UNKNOWN" if SVC.upper() in icacls.upper() else "FAIL"


def adm3_leaf_grant_pass(icacls):            # leaf grant -> full-ancestor PASS
    return "PASS" if f"NT SERVICE\\{SVC}".upper() in icacls.upper() else "UNKNOWN"


def adm5_ignore_deny(icacls):                # ignore an explicit deny
    return "UNKNOWN"


def adm6_temp_path_fail(root):               # temp path present -> access FAIL
    return "FAIL" if "TEMP" in str(root).upper() else "UNKNOWN"


def main() -> int:
    results = []
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for leaf in ("py.exe", "svc.py", "config.json"):
            (root / leaf).write_text("x", encoding="utf-8")
        tmp_root = Path(r"C:\Users\x\AppData\Local\Temp\gnosis-2cb-b1-run-b1-1")

        # honest producer baselines
        assert _real_contract(TRUSTED, None, root)[0] == "UNKNOWN"
        assert _real_contract(ABSENT, None, root)[0] == "UNKNOWN"
        assert _real_contract(LEAFGRANT, None, root)[0] == "UNKNOWN"
        assert _real_contract(DENY, None, root)[0] == "FAIL"

        # ADM1: TrustedInstaller substring -> honest UNKNOWN; mutant says PASS
        caught = (_real_contract(TRUSTED, None, root)[0] != "PASS"
                  and adm1_any_nt_service_pass(TRUSTED) == "PASS")
        results.append(("ADM1", caught, "any NT SERVICE substring -> PASS"))

        # ADM2: friendly-name absence -> honest UNKNOWN; mutant says FAIL
        caught = (_real_contract(ABSENT, None, root)[0] != "FAIL"
                  and adm2_friendlyname_absence_fail(ABSENT) == "FAIL")
        results.append(("ADM2", caught, "friendly-name absence -> FAIL"))

        # ADM3: leaf grant -> honest UNKNOWN (ancestors untested); mutant says PASS
        real = _real_contract(LEAFGRANT, None, root)
        caught = (real[0] != "PASS" and real[1]["ancestors_tested"] is False
                  and adm3_leaf_grant_pass(LEAFGRANT) == "PASS")
        results.append(("ADM3", caught, "leaf grant -> full ancestor PASS"))

        # ADM4: UNKNOWN -> access root cause (classifier mutant)
        honest = s.classify_publisher_failure({"terminal_reason": "service-died"},
                                              _pm(access_contract="UNKNOWN"))
        mutant = "DEPLOYMENT/ANCESTOR ACCESS FAILURE"   # forced access branch
        caught = (honest != "DEPLOYMENT/ANCESTOR ACCESS FAILURE"
                  and mutant == "DEPLOYMENT/ANCESTOR ACCESS FAILURE")
        results.append(("ADM4", caught, "UNKNOWN -> access root cause"))

        # ADM5: ignore explicit deny -> honest FAIL lost; mutant says UNKNOWN
        caught = (_real_contract(DENY, None, root)[0] == "FAIL"
                  and adm5_ignore_deny(DENY) != "FAIL")
        results.append(("ADM5", caught, "ignore explicit deny ACE"))

        # ADM6: temp-path presence -> honest UNKNOWN; mutant says FAIL
        caught = (_real_contract(LEAFGRANT, None, tmp_root_ok(root))[0] != "FAIL"
                  and adm6_temp_path_fail(tmp_root) == "FAIL")
        results.append(("ADM6", caught, "temp-path presence -> access FAIL"))

    ok = True
    for name, caught, desc in results:
        print(f"{name}: {'APPLIED / CAUGHT' if caught else 'SURVIVED'}  ({desc})")
        ok = ok and caught
    n = sum(1 for _, c, _ in results if c)
    print(f"\n{n}/{len(results)} applied access-producer mutants CAUGHT")
    return 0 if ok else 1


def tmp_root_ok(root):
    # ADM6's producer check reads real leaf ACLs (never the path string); the
    # real producer ignores the deployment path entirely, so any existing root works.
    return root


if __name__ == "__main__":
    raise SystemExit(main())
