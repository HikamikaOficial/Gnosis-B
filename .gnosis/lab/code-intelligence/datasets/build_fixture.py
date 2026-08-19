"""Builds the deterministic code-intelligence benchmark fixture: a tiny
git repo with known ground truth (symbols, calls, an indirect chain, a
rename, a deletion, a new file, a circular import, overloaded names, dead
code, and a blast-radius-relevant change), plus ground_truth.json.

Run once: `python build_fixture.py`. Idempotent (wipes and rebuilds
fixture-repo/ each time). Never touches the external reference corpus.
"""
from __future__ import annotations

import json
import shutil
import stat
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE / "fixture-repo"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True)


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.strip()


def _force_remove_readonly(func, path, exc_info) -> None:
    # Git marks object files read-only on Windows; shutil.rmtree needs a
    # hand clearing that bit before it can unlink them.
    import os as _os
    _os.chmod(path, stat.S_IWRITE)
    func(path)


def build() -> dict:
    if REPO.exists():
        shutil.rmtree(REPO, onerror=_force_remove_readonly)
    REPO.mkdir(parents=True)
    _git("init")
    _git("config", "user.email", "lab@gnosis.local")
    _git("config", "user.name", "Gnosis Lab")

    commits: dict[str, str] = {}

    _write(REPO / "pkg" / "__init__.py", "")
    _write(REPO / "pkg" / "deep.py", (
        "def compute_d(x):\n"
        "    \"\"\"Bottom of the indirect chain: entrypoint -> compute_b/c -> compute_d.\"\"\"\n"
        "    return x * 2\n"
        "\n"
        "\n"
        "def legacy_function():\n"
        "    \"\"\"Unused; deleted in a later commit (deletion-detection fixture).\"\"\"\n"
        "    return \"legacy\"\n"
    ))
    _write(REPO / "pkg" / "helpers.py", (
        "from .deep import compute_d\n"
        "\n"
        "\n"
        "def compute_b(x):\n"
        "    return compute_d(x) + 1\n"
        "\n"
        "\n"
        "def compute_c(x):\n"
        "    return compute_d(x) + 2\n"
    ))
    _write(REPO / "pkg" / "core.py", (
        "from .helpers import compute_b, compute_c\n"
        "\n"
        "\n"
        "def entrypoint(x):\n"
        "    \"\"\"Direct calls to compute_b/compute_c; indirect chain to compute_d.\"\"\"\n"
        "    return compute_b(x) + compute_c(x)\n"
    ))
    _write(REPO / "pkg" / "circular_x.py", (
        "from . import circular_y\n"
        "\n"
        "\n"
        "def x_func():\n"
        "    return circular_y.y_func() + 1\n"
    ))
    _write(REPO / "pkg" / "circular_y.py", (
        "from . import circular_x\n"
        "\n"
        "\n"
        "def y_func():\n"
        "    return 1\n"
    ))
    _write(REPO / "pkg" / "overload_ns1.py", (
        "def process(item):\n"
        "    \"\"\"Same name as overload_ns2.process; different module\n"
        "    (overloaded/similarly-named-symbol disambiguation fixture).\"\"\"\n"
        "    return f\"ns1:{item}\"\n"
    ))
    _write(REPO / "pkg" / "overload_ns2.py", (
        "def process(item):\n"
        "    return f\"ns2:{item}\"\n"
    ))
    _write(REPO / "pkg" / "dead_code.py", (
        "def unused_function():\n"
        "    \"\"\"Defined but never called anywhere in this fixture (dead-code fixture).\"\"\"\n"
        "    return \"dead\"\n"
    ))
    _write(REPO / "tests" / "__init__.py", "")
    _write(REPO / "tests" / "test_core.py", (
        "from pkg.core import entrypoint\n"
        "\n"
        "\n"
        "def test_entrypoint():\n"
        "    assert entrypoint(3) == 15\n"
    ))
    _write(REPO / "README.md", "Gnosis M2.1 code-intelligence benchmark fixture. Synthetic, no real logic.\n")
    _git("add", "-A")
    _git("commit", "-m", "c1: initial state")
    commits["c1_initial"] = _head()

    _write(REPO / "pkg" / "helpers.py", (
        "from .deep import compute_d\n"
        "\n"
        "\n"
        "def compute_b_renamed(x):\n"
        "    return compute_d(x) + 1\n"
        "\n"
        "\n"
        "def compute_c(x):\n"
        "    return compute_d(x) + 2\n"
    ))
    _write(REPO / "pkg" / "core.py", (
        "from .helpers import compute_b_renamed, compute_c\n"
        "\n"
        "\n"
        "def entrypoint(x):\n"
        "    \"\"\"Direct calls to compute_b_renamed/compute_c; indirect chain to compute_d.\"\"\"\n"
        "    return compute_b_renamed(x) + compute_c(x)\n"
    ))
    _git("add", "-A")
    _git("commit", "-m", "c2: rename compute_b to compute_b_renamed")
    commits["c2_rename"] = _head()

    _write(REPO / "pkg" / "deep.py", (
        "def compute_d(x):\n"
        "    \"\"\"Bottom of the indirect chain: entrypoint -> compute_b/c -> compute_d.\"\"\"\n"
        "    return x * 2\n"
    ))
    _git("add", "-A")
    _git("commit", "-m", "c3: delete unused legacy_function")
    commits["c3_delete"] = _head()

    _write(REPO / "pkg" / "new_module.py", (
        "from .helpers import compute_b_renamed\n"
        "\n"
        "\n"
        "def new_feature(x):\n"
        "    return compute_b_renamed(x) * 10\n"
    ))
    _git("add", "-A")
    _git("commit", "-m", "c4: add new_module (incremental indexing fixture)")
    commits["c4_new_file"] = _head()

    _write(REPO / "pkg" / "helpers.py", (
        "from .deep import compute_d\n"
        "\n"
        "\n"
        "def compute_b_renamed(x):\n"
        "    return compute_d(x) + 1\n"
        "\n"
        "\n"
        "def compute_c(x):\n"
        "    # Behavior changed here: known callers are entrypoint (direct) and\n"
        "    # test_entrypoint (transitive, via entrypoint).\n"
        "    return compute_d(x) + 2 + 100\n"
    ))
    _write(REPO / "tests" / "test_core.py", (
        "from pkg.core import entrypoint\n"
        "\n"
        "\n"
        "def test_entrypoint():\n"
        "    assert entrypoint(3) == 115\n"
    ))
    _git("add", "-A")
    _git("commit", "-m", "c5: change compute_c body (blast-radius fixture)")
    commits["c5_blast_radius_change"] = _head()

    return commits


def ground_truth(commits: dict) -> dict:
    return {
        "fixture_commits": commits,
        "final_state": {
            "symbols_present": [
                {"qualified_name": "pkg.deep.compute_d", "file": "pkg/deep.py", "kind": "function"},
                {"qualified_name": "pkg.helpers.compute_b_renamed", "file": "pkg/helpers.py", "kind": "function"},
                {"qualified_name": "pkg.helpers.compute_c", "file": "pkg/helpers.py", "kind": "function"},
                {"qualified_name": "pkg.core.entrypoint", "file": "pkg/core.py", "kind": "function"},
                {"qualified_name": "pkg.circular_x.x_func", "file": "pkg/circular_x.py", "kind": "function"},
                {"qualified_name": "pkg.circular_y.y_func", "file": "pkg/circular_y.py", "kind": "function"},
                {"qualified_name": "pkg.overload_ns1.process", "file": "pkg/overload_ns1.py", "kind": "function"},
                {"qualified_name": "pkg.overload_ns2.process", "file": "pkg/overload_ns2.py", "kind": "function"},
                {"qualified_name": "pkg.dead_code.unused_function", "file": "pkg/dead_code.py", "kind": "function"},
                {"qualified_name": "pkg.new_module.new_feature", "file": "pkg/new_module.py", "kind": "function"},
                {"qualified_name": "tests.test_core.test_entrypoint", "file": "tests/test_core.py", "kind": "function"},
            ],
            "symbols_absent": [
                {"qualified_name": "pkg.helpers.compute_b", "reason": "renamed to compute_b_renamed in c2"},
                {"qualified_name": "pkg.deep.legacy_function", "reason": "deleted in c3"},
            ],
            "direct_calls": [
                {"caller": "pkg.core.entrypoint", "callee": "pkg.helpers.compute_b_renamed"},
                {"caller": "pkg.core.entrypoint", "callee": "pkg.helpers.compute_c"},
                {"caller": "pkg.helpers.compute_b_renamed", "callee": "pkg.deep.compute_d"},
                {"caller": "pkg.helpers.compute_c", "callee": "pkg.deep.compute_d"},
                {"caller": "pkg.new_module.new_feature", "callee": "pkg.helpers.compute_b_renamed"},
                {"caller": "tests.test_core.test_entrypoint", "callee": "pkg.core.entrypoint"},
            ],
            "indirect_chain": {
                "path": ["pkg.core.entrypoint", "pkg.helpers.compute_c", "pkg.deep.compute_d"],
                "description": "entrypoint -> compute_c -> compute_d transitive chain",
            },
            "circular_dependency": {
                "modules": ["pkg.circular_x", "pkg.circular_y"],
                "description": "pkg.circular_x imports pkg.circular_y and pkg.circular_y imports pkg.circular_x",
            },
            "overloaded_names": {
                "name": "process",
                "distinct_qualified_names": ["pkg.overload_ns1.process", "pkg.overload_ns2.process"],
            },
            "cross_module_call": {
                "caller": "tests.test_core.test_entrypoint",
                "callee": "pkg.core.entrypoint",
                "description": "test module calling production module across a package boundary",
            },
            "dead_code": {
                "qualified_name": "pkg.dead_code.unused_function",
                "expected_callers": [],
            },
            "blast_radius_of_compute_c_change": {
                "changed_symbol": "pkg.helpers.compute_c",
                "changed_in_commit": "c5_blast_radius_change",
                "expected_impacted_set": [
                    "pkg.helpers.compute_c",
                    "pkg.core.entrypoint",
                    "tests.test_core.test_entrypoint",
                ],
            },
        },
    }


if __name__ == "__main__":
    commit_shas = build()
    truth = ground_truth(commit_shas)
    (HERE / "ground_truth.json").write_text(json.dumps(truth, indent=2, sort_keys=True), encoding="utf-8")
    print("Fixture repo built at:", REPO)
    print("Commits:", json.dumps(commit_shas, indent=2))
