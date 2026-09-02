r"""F-33 Stage 2C-B1-R3E — canonical release-id plumbing.

The R3D OS-real run launched the operator, which then failed inside
`cli.build_operator_composition`: it rebuilt `DeploymentLayout` WITHOUT the actual
`release_id`, defaulting to "current", so it observed `...\releases\current\runtime`
while the qualified release was `B1` (`CreateFileW winerr 3`). R3E carries the actual
release identity from the trusted config into the operator's layout reconstruction —
no "current" fallback, no hardcoding, arbitrary valid release IDs, fail-closed on
missing/invalid, and the value is validated as a safe path segment.

Filesystem/mock only; no OS provisioning, no provider calls. `observe_deployment` is
captured so the reconstructed runtime root is inspected without a real deployment.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gnosis.director import cli
from gnosis.director.cli import EXIT_USAGE, OperatorError, build_operator_composition


def _config(root: Path, *, release_id: str | None = "B1") -> Path:
    rid = release_id if release_id is not None else "B1"
    dep = {
        "code_base": str(root / "code"), "state_base": str(root / "state"),
        "work_base": str(root / "work"), "worker_username": "GnosisWkr",
        "trust_root": str(root / "code" / "releases" / rid / "publisher"),
    }
    if release_id is not None:
        dep["release_id"] = release_id           # omit entirely when release_id=None
    body = {
        "deployment": dep,
        "attribution": {"reviewer_id": "r@team", "policy_actor": "agent://dir"},
        "operator": {"director_root": str(root / "state"), "repo_path": str(root)},
        "publication": {"trust_state_root": str(root / "state"),
                        "evidence_root": str(root / "ev"), "repository_id": "gnosis",
                        "service_name": "GnosisPub", "pipe_name": r"\\.\pipe\g"},
        "verifier": {"name": "v", "command": [sys.executable, "-c", "raise SystemExit(0)"]},
        "reviewer": {"binary": sys.executable},   # a real absolute file -> build_reviewer OK
    }
    p = root / "operator_config.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


class _Captured(Exception):
    def __init__(self, config: object) -> None:
        self.config = config


def _capture_observe(config: object) -> object:
    raise _Captured(config)


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _runtime_root_for(self, release_id: str) -> str:
        cp = _config(self.root, release_id=release_id)
        with mock.patch("gnosis.trust.deployment.observe_deployment", _capture_observe), \
                mock.patch("gnosis.director.composition.trusted_deployment_from_layout",
                           lambda *a, **k: object()), self.assertRaises(_Captured) as cm:
            build_operator_composition(cp)
        return str(cm.exception.config.runtime_root).replace("/", "\\")  # type: ignore[attr-defined]


class TestReleaseIdReachesLayout(_Base):
    def test_actual_release_B1_reconstructed(self) -> None:
        rr = self._runtime_root_for("B1")
        self.assertTrue(rr.endswith(r"releases\B1\runtime"), rr)
        self.assertNotIn(r"releases\current", rr)   # the historical wrong default

    def test_arbitrary_release_generalises(self) -> None:
        for rid in ("R42", "current", "v2-3_x"):
            rr = self._runtime_root_for(rid)
            self.assertTrue(rr.endswith(rf"releases\{rid}\runtime"), rr)


class TestFailClosed(_Base):
    def test_missing_release_id_fails_closed_not_current(self) -> None:
        cp = _config(self.root, release_id=None)   # no release_id key at all
        with mock.patch("gnosis.trust.deployment.observe_deployment",
                        _capture_observe), self.assertRaises(OperatorError) as cm:
            build_operator_composition(cp)
        self.assertEqual(cm.exception.code, EXIT_USAGE)
        # via cli.main -> usage exit, never silently resolves a "current" runtime
        code = cli.main(["run", "--config", str(cp),
                         "--brief", str(self._min_brief())])
        self.assertEqual(code, EXIT_USAGE)

    def test_invalid_release_ids_rejected(self) -> None:
        for bad in ("", "..", "a/b", r"a\b", "C:x", "a b", ".", "-lead", "a.b",
                    "x" * 65):
            cp = _config(self.root, release_id=bad)
            with self.assertRaises(OperatorError) as cm:
                build_operator_composition(cp)
            self.assertEqual(cm.exception.code, EXIT_USAGE, f"release_id={bad!r}")

    def _min_brief(self) -> Path:
        b = {"brief_id": "b1", "title": "t", "mission": "m", "source": "manual",
             "non_negotiables": [], "constraints": [], "acceptance_criteria": [],
             "raw_text": "", "metadata": {}}
        p = self.root / "brief.json"
        p.write_text(json.dumps(b), encoding="utf-8")
        return p


class TestNoUntrustedReleaseSource(_Base):
    def test_release_id_comes_from_trusted_config_only(self) -> None:
        # the value used is exactly the trusted config's deployment.release_id; an
        # environment variable of the same name must NOT influence it.
        with mock.patch.dict("os.environ", {"GNOSIS_RELEASE_ID": "EVIL",
                                            "release_id": "EVIL"}):
            rr = self._runtime_root_for("B1")
        self.assertTrue(rr.endswith(r"releases\B1\runtime"))
        self.assertNotIn("EVIL", rr)


if __name__ == "__main__":
    unittest.main()
