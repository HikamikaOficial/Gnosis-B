r"""F-33 Stage 2C-B1-R3E.1 — canonical production operator-config writer.

R3E's fix was reader-side + a harness-only writer. R3E.1 promotes the operator-config
construction into the canonical production surface
(`gnosis.director.composition.build_operator_config`), makes the B1 OS-real driver
delegate to it, and proves — with the REAL writer (not a manual dict) — that
`deployment.release_id == layout.release_id`, plus a writer->reader roundtrip.

Filesystem/mock only; no OS provisioning, no provider calls.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO / "scripts", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from gnosis.director import cli
from gnosis.director.cli import build_operator_composition
from gnosis.director.composition import (
    OPERATOR_CONFIG_SECTIONS,
    OperatorConfigInputs,
    build_operator_config,
)
from gnosis.provision.layout import DeploymentLayout


def _inputs(root: Path, release_id: str) -> OperatorConfigInputs:
    lay = DeploymentLayout(code_base=str(root / "code"), state_base=str(root / "state"),
                           work_base=str(root / "work"), release_id=release_id)
    return OperatorConfigInputs(
        layout=lay, worker_username="GnosisWkr", trust_root=lay.trust_root,
        reviewer_binary=sys.executable, reviewer_id="claude-code-cli",
        policy_actor="gnosis-director", director_root=lay.state_base,
        repo_path=str(root), trust_state_root=lay.state_base,
        evidence_root=lay.bundles_root, repository_id="gnosis",
        service_name="GnosisPub", pipe_name=r"\\.\pipe\g",
        verifier_name="gnosis-verify",
        verifier_command=(sys.executable, "-I", "-B", "-c", "raise SystemExit(0)"))


class _Captured(Exception):
    def __init__(self, config: object) -> None:
        self.config = config


class TestCanonicalWriter(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_release_id_from_layout_B1(self) -> None:
        cfg = build_operator_config(_inputs(self.root, "B1"))
        self.assertEqual(cfg["deployment"]["release_id"], "B1")

    def test_release_id_from_layout_R42(self) -> None:
        cfg = build_operator_config(_inputs(self.root, "R42"))
        self.assertEqual(cfg["deployment"]["release_id"], "R42")

    def test_emits_all_required_sections_and_contract_matches_reader(self) -> None:
        cfg = build_operator_config(_inputs(self.root, "B1"))
        for section in OPERATOR_CONFIG_SECTIONS:
            self.assertIn(section, cfg)
        # writer/reader contract agreement (anti-drift)
        self.assertEqual(set(OPERATOR_CONFIG_SECTIONS), set(cli._REQUIRED_CONFIG))
        # mandatory deployment sub-fields the reader consumes
        for k in ("code_base", "state_base", "work_base", "release_id",
                  "worker_username", "trust_root"):
            self.assertIn(k, cfg["deployment"])

    def test_writer_ignores_environment(self) -> None:
        with mock.patch.dict("os.environ", {"release_id": "EVIL"}):
            cfg = build_operator_config(_inputs(self.root, "R42"))
        self.assertEqual(cfg["deployment"]["release_id"], "R42")


class TestWriterReaderRoundtrip(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _roundtrip_runtime_root(self, release_id: str) -> str:
        cfg = build_operator_config(_inputs(self.root, release_id))   # REAL writer
        cp = self.root / "operator_config.json"
        cp.write_text(json.dumps(cfg), encoding="utf-8")

        def _capture(config: object) -> object:
            raise _Captured(config)
        with mock.patch("gnosis.trust.deployment.observe_deployment", _capture), \
                mock.patch("gnosis.director.composition.trusted_deployment_from_layout",
                           lambda *a, **k: object()), \
                self.assertRaises(_Captured) as cm:
            build_operator_composition(cp)          # REAL reader
        return str(cm.exception.config.runtime_root).replace("/", "\\")  # type: ignore[attr-defined]

    def test_roundtrip_B1(self) -> None:
        self.assertTrue(self._roundtrip_runtime_root("B1").endswith(r"releases\B1\runtime"))

    def test_roundtrip_R42(self) -> None:
        rr = self._roundtrip_runtime_root("R42")
        self.assertTrue(rr.endswith(r"releases\R42\runtime"), rr)
        self.assertNotIn(r"releases\current", rr)


class TestDriverDelegates(unittest.TestCase):
    def test_driver_delegates_to_canonical_writer(self) -> None:
        # the B1 driver must produce EXACTLY the canonical writer's output (no
        # independent schema) and must carry the authoritative release_id.
        import run_f33_stage2c_b1_osreal as drv
        with tempfile.TemporaryDirectory() as d:
            dcfg = drv.default_driver_config(Path(d) / "gnosis-2cb-b1-run-b1-1")
            driver_cfg = drv.build_operator_config(dcfg.stage, dcfg.reviewer_binary)
        self.assertEqual(driver_cfg["deployment"]["release_id"],
                         dcfg.stage.layout.release_id)
        # source-level: the driver imports and calls the canonical writer, defining
        # no operator-config schema of its own.
        src = (Path(drv.__file__)).read_text(encoding="utf-8")
        self.assertIn("from gnosis.director.composition import", src)
        self.assertIn("build_operator_config as _canonical_build_operator_config", src)


if __name__ == "__main__":
    unittest.main()
