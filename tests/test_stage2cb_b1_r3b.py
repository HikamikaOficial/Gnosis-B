r"""F-33 Stage 2C-B1-R3B — deployment-identity delta instrumentation.

Harness-only, gate-preserving diagnostics that name WHICH F-17 identity component
changed between the trusted provision-time observation and the fresh canonical-launch
re-observation. Pure/OS-free: synthetic identity dicts exercise the diff; a small
fake exercises the recorder.
"""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "scripts", REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import identity_delta as idd
import run_f33_stage2c_b1_osreal as drv


def _sd(owner="O", aces=(("ace", 1),)):
    return {"owner_sid": owner, "group_sid": "G", "control": 1,
            "dacl_present": True, "aces": [dict([a]) for a in aces],
            "mandatory_label": None}


def _ident(**over):
    base = {
        "schema": "gnosis.deployment.v2",
        "package": {"schema": "pkg", "package_version": "1", "source_commit": "c",
                    "source_tree": "t",
                    "files": [{"path": "a.py", "size": 1, "digest": "d1"},
                              {"path": "b.py", "size": 2, "digest": "d2"}]},
        "runtime": {"executable_path": "py.exe", "executable_size": 10,
                    "executable_digest": "rd", "version": "3.12"},
        "runtime_tree": {"schema": "tree", "label": "runtime",
                         "files": [{"path": "lib/x.py", "size": 3, "digest": "t1"}]},
        "service": {"name": "S", "account": r"NT SERVICE\S", "image_path": "img",
                    "start_type": "demand", "service_sid": "S-1-5-80-1",
                    "sid_type": "unrestricted", "required_privileges": [],
                    "security_descriptor": _sd()},
        "trust_root": {"path": r"C:\dep\trust", "security_descriptor": _sd()},
        "runidentity_store": {"path": r"C:\dep\state\run", "security_descriptor": _sd()},
        "anchorstore": {"path": r"C:\dep\state\anchors", "security_descriptor": _sd()},
        "pipe_policy": {"schema": "pipe", "sddl": "D:(A;;;;;WD)"},
    }
    base.update(over)
    return base


class TestClassify(unittest.TestCase):
    def test_package_content_changed(self) -> None:
        p = _ident()
        lch = copy.deepcopy(p)
        lch["package"]["files"][0]["digest"] = "CHANGED"
        d = idd.classify_identity_delta(p, lch)
        self.assertEqual(d["components"]["package"], "CHANGED")
        self.assertEqual(d["components"]["runtime"], "UNCHANGED")
        self.assertIn("PACKAGE_CONTENT_CHANGED", d["classifications"])
        self.assertEqual(d["manifest_delta"]["package"]["changed"], ["a.py"])

    def test_package_added_removed(self) -> None:
        p = _ident()
        lch = copy.deepcopy(p)
        lch["package"]["files"].append({"path": "c.py", "size": 9, "digest": "d3"})
        lch["package"]["files"] = [f for f in lch["package"]["files"]
                                   if f["path"] != "b.py"]
        d = idd.classify_identity_delta(p, lch)
        self.assertEqual(d["manifest_delta"]["package"]["added"], ["c.py"])
        self.assertEqual(d["manifest_delta"]["package"]["removed"], ["b.py"])

    def test_runtime_content_changed(self) -> None:
        p = _ident()
        lch = copy.deepcopy(p)
        lch["runtime_tree"]["files"][0]["digest"] = "T2"
        d = idd.classify_identity_delta(p, lch)
        self.assertIn("RUNTIME_CONTENT_CHANGED", d["classifications"])
        self.assertEqual(d["manifest_delta"]["runtime_tree"]["changed"], ["lib/x.py"])

    def test_service_security_changed(self) -> None:
        p = _ident()
        lch = copy.deepcopy(p)
        lch["service"]["security_descriptor"] = _sd(owner="OTHER")
        d = idd.classify_identity_delta(p, lch)
        self.assertIn("SERVICE_SECURITY_CHANGED", d["classifications"])
        self.assertTrue(d["sddl_delta"]["service"]["changed"])

    def test_store_security_changed(self) -> None:
        p = _ident()
        lch = copy.deepcopy(p)
        lch["trust_root"]["security_descriptor"] = _sd(aces=(("ace", 2),))
        d = idd.classify_identity_delta(p, lch)
        self.assertIn("STORE_SECURITY_CHANGED", d["classifications"])
        self.assertIn("trust_root", d["sddl_delta"])
        # a pure content component must NOT be flagged
        self.assertNotIn("PACKAGE_CONTENT_CHANGED", d["classifications"])

    def test_path_identity_changed(self) -> None:
        p = _ident()
        lch = copy.deepcopy(p)
        lch["anchorstore"]["path"] = r"C:\other\anchors"
        d = idd.classify_identity_delta(p, lch)
        self.assertIn("PATH_IDENTITY_CHANGED", d["classifications"])

    def test_multiple_components(self) -> None:
        p = _ident()
        lch = copy.deepcopy(p)
        lch["runtime_tree"]["files"][0]["digest"] = "T2"
        lch["anchorstore"]["security_descriptor"] = _sd(owner="Z")
        d = idd.classify_identity_delta(p, lch)
        # BOTH surfaced — never stop at the first delta
        self.assertIn("RUNTIME_CONTENT_CHANGED", d["classifications"])
        self.assertIn("STORE_SECURITY_CHANGED", d["classifications"])
        self.assertIn("MULTIPLE_COMPONENTS_CHANGED", d["classifications"])
        self.assertEqual(d["components"]["runtime_tree"], "CHANGED")
        self.assertEqual(d["components"]["anchorstore"], "CHANGED")

    def test_identical_no_delta(self) -> None:
        p = _ident()
        d = idd.classify_identity_delta(p, copy.deepcopy(p))
        self.assertIn("NO_STRUCTURAL_DELTA_FOUND", d["classifications"])
        self.assertNotIn("CHANGED", set(d["components"].values()))
        self.assertEqual(d["manifest_delta"], {})
        self.assertEqual(d["sddl_delta"], {})

    def test_diff_unavailable(self) -> None:
        self.assertEqual(
            idd.classify_identity_delta(None, _ident())["classifications"],
            ["DIFF_UNAVAILABLE"])
        self.assertEqual(
            idd.classify_identity_delta(_ident(), None)["classifications"],
            ["DIFF_UNAVAILABLE"])


class _FakeIdentity:
    def __init__(self, d: dict, digest: str) -> None:
        self._d, self._digest = d, digest

    def to_dict(self) -> dict:
        return self._d

    def digest(self) -> str:
        return self._digest


class _BoomIdentity:
    def to_dict(self) -> dict:
        raise RuntimeError("cannot serialise")

    def digest(self) -> str:
        raise RuntimeError("cannot digest")


class _Cfg:
    class layout:
        trust_root = "t"; runtime_executable = "e"; runtime_root = "r"
        runidentity_root = "ri"; anchors_root = "an"
    service_name = "S"


class TestRecorder(unittest.TestCase):
    def test_records_authoritative_objects(self) -> None:
        rec = idd.IdentityDeltaRecorder()
        pobj = _FakeIdentity(_ident(), "prov")
        lch = _ident()
        lch["package"]["files"][0]["digest"] = "X"
        lobj = _FakeIdentity(lch, "launch")
        rec.record_provision(pobj)
        rec.record_launch(lobj)
        r = rec.result()
        # the snapshot IS the authoritative object's own dict/digest
        self.assertEqual(rec.provision["identity"], pobj.to_dict())
        self.assertEqual(r["provision_digest"], "prov")
        self.assertEqual(r["launch_digest"], "launch")
        self.assertIn("PACKAGE_CONTENT_CHANGED", r["delta"]["classifications"])

    def test_digests_match_reflects_reality(self) -> None:
        rec = idd.IdentityDeltaRecorder()
        rec.record_provision(_FakeIdentity(_ident(), "same"))
        rec.record_launch(_FakeIdentity(_ident(), "same"))
        self.assertTrue(rec.result()["digests_match"])
        rec2 = idd.IdentityDeltaRecorder()
        rec2.record_provision(_FakeIdentity(_ident(), "a"))
        rec2.record_launch(_FakeIdentity(_ident(), "b"))
        self.assertFalse(rec2.result()["digests_match"])

    def test_snapshot_failure_is_swallowed(self) -> None:
        rec = idd.IdentityDeltaRecorder()
        rec.record_provision(_BoomIdentity())      # must NOT raise
        rec.record_launch(_FakeIdentity(_ident(), "l"))
        r = rec.result()
        self.assertIsNone(r["provision_digest"])
        self.assertEqual(r["delta"]["classifications"], ["DIFF_UNAVAILABLE"])
        self.assertTrue(any("provision snapshot failed" in n for n in r["notes"]))

    def test_recorder_does_no_filesystem_io(self) -> None:
        # DDM3 guard: the module must not write anything (so it can never create the
        # digest delta it is meant to observe).
        src = (REPO / "scripts" / "identity_delta.py").read_text(encoding="utf-8")
        for forbidden in ("open(", "write_text", "write_bytes", ".write(",
                          "mkdir", "Path("):
            self.assertNotIn(forbidden, src)


class TestGatePreservingReobserve(unittest.TestCase):
    def test_reobserve_returns_digest_even_if_record_raises(self) -> None:
        # The reobserve seam must return the authoritative digest to the gate even if
        # the recorder blows up — diagnostics can never bypass or break the gate.
        class _Recorder:
            def record_launch(self, identity):
                raise RuntimeError("diagnostic exploded")

        captured = {}

        # monkeypatch observe_deployment used inside make_real_reobserve
        import gnosis.trust.deployment as dep
        real = dep.observe_deployment

        def _fake_observe(cfg):
            captured["called"] = True
            return _FakeIdentity(_ident(), "AUTHORITATIVE-DIGEST")
        dep.observe_deployment = _fake_observe  # type: ignore[assignment]
        try:
            obs = drv.make_real_reobserve(_Cfg(), _Recorder())
            # record_launch raises inside; the seam swallows it and STILL returns the
            # authoritative digest to the gate. Diagnostics can never break the gate.
            self.assertEqual(obs(), "AUTHORITATIVE-DIGEST")
            self.assertTrue(captured["called"])
        finally:
            dep.observe_deployment = real  # type: ignore[assignment]

    def test_reobserve_records_the_gate_observation(self) -> None:
        # DDM8 guard: EXACTLY ONE observation must feed both the gate digest and the
        # recorder. A second re-observation (diffing the wrong object) is caught.
        rec = idd.IdentityDeltaRecorder()
        seq = {"n": 0}
        import gnosis.trust.deployment as dep
        real = dep.observe_deployment

        def _fake(cfg):
            seq["n"] += 1
            return _FakeIdentity(_ident(), f"DIGEST-{seq['n']}")
        dep.observe_deployment = _fake  # type: ignore[assignment]
        try:
            returned = drv.make_real_reobserve(_Cfg(), rec)()
        finally:
            dep.observe_deployment = real  # type: ignore[assignment]
        self.assertEqual(returned, "DIGEST-1")
        self.assertEqual(rec.result()["launch_digest"], "DIGEST-1")
        self.assertEqual(seq["n"], 1)   # observed exactly once


class TestDriverTraceCarriesDelta(unittest.TestCase):
    def test_dry_run_trace_has_identity_delta(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            dcfg = drv.default_driver_config(Path(d) / "gnosis-2cb-b1-run-b1-1",
                                             live_used=1)
            import stage2cb_ops as sops
            t = drv.run_driver(dcfg, execute_os_real=False, confirm="",
                               expected_head_sha=drv.expected_head(),
                               dry_ops=sops.DryOperations())
        self.assertIn("identity_delta", t)
        idl = t["identity_delta"]
        for k in ("provision_digest", "launch_digest", "digests_match", "delta"):
            self.assertIn(k, idl)


if __name__ == "__main__":
    unittest.main()
