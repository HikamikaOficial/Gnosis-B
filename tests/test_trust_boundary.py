"""Trust-plane boundary tests (F-17 Stage 1 — trust-plane split).

These keep the Trust Plane minimal: they fail if `gnosis.trust` starts
importing anything outside its qualified TCB closure, if a second canonical-hash
implementation appears, if the compatibility facade stops pointing at the
authoritative implementation, or if probe code (ProbeAnchorStore) leaks into
`src/`. The load-time import closure is measured in a CLEAN subprocess so
pytest's own imports do not pollute it.

CLOSED-WORLD MODEL (Stage-1 independent-review hardening). The first version of
this file enforced a BLACKLIST of worker-plane name substrings (engine, planner,
scheduler, ...). That is too weak for a Trusted Computing Base: a NEW internal
dependency whose name nobody thought to blacklist would enter the TCB silently.
Of the 56 non-TCB internal `gnosis.*` modules that exist today, that blacklist
would have admitted 28 without a word — `kernel.credentials`, `kernel.ledger`,
`kernel.memory_router` and `transport.mcp_transport` among them.

The model is therefore INVERTED. For internal `gnosis.*` modules:

    DEFAULT = NOT ALLOWED

Only the modules in `TRUST_ALLOWLIST` may appear in the Trust Plane's loaded
closure, each for a stated architectural reason. The enforced property is

    loaded gnosis module ∉ TRUST_ALLOWLIST  ->  TEST FAIL

which does not depend on knowing a dangerous module's name in advance
(`test_an_arbitrary_unknown_internal_module_is_a_boundary_violation` and
`test_a_real_new_internal_module_in_the_closure_is_caught_end_to_end` prove
exactly that). stdlib is out of scope for this control; third-party code is not
— see `test_the_trust_plane_pulls_in_no_third_party_code`.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Iterable
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"

# ---------------------------------------------------------------------------
# The closed-world Trust Plane allowlist.
#
# An internal `gnosis.*` module belongs here ONLY if the Trust Plane cannot do
# its job without it. Adding an entry means deliberately enlarging the TCB:
# whatever is listed here is code whose compromise would defeat F-17.
# `gnosis.kernel.authority` is deliberately ABSENT — the Trust Plane must never
# depend back on its own compatibility facade.
# ---------------------------------------------------------------------------
TRUST_ALLOWLIST: dict[str, str] = {
    "gnosis": "distribution root package; its __init__ holds no logic",
    "gnosis.kernel": "empty package marker, traversed only to reach kernel.canonical",
    "gnosis.kernel.canonical": (
        "the ONE canonical-bytes hash primitive (ADR-0004). Re-implementing it "
        "inside the Trust Plane is the defect test_canonical_hash_is_not_duplicated "
        "forbids, so the dependency is the lesser evil and is deliberate."),
    "gnosis.trust": "the Trust Plane package itself",
    "gnosis.trust.anchor": "authoritative anchor slice (record, store, publication protocol)",
    "gnosis.trust.launch": "authoritative launch/identity slice (MIC primitives, publisher gate)",
    # Stage-2 addition, entering by explicit allowlist diff as required:
    "gnosis.trust.deployment": (
        "authoritative deployment-identity slice (F-17 Stage 2) — observes what "
        "is actually deployed and binds it into deployment_digest. Trusted "
        "because a compromise of it would let a different deployment claim the "
        "identity of the approved one."),
    # Stage-3 additions, each an explicit, reviewable enlargement of the TCB:
    "gnosis.trust.run_identity": (
        "authoritative trusted-run-identity slice (F-17 Stage 3) — the publication "
        "lifecycle and the publish-authorization gate. Trusted because a "
        "compromise of it would let a run be anchored that was never authorized."),
    "gnosis.kernel.atomic_io": (
        "the ONE corruption-resistant write primitive (write-tmp + os.replace, 37 "
        "lines, stdlib only). The trusted run store must not observe a torn "
        "record; re-implementing the write inside the Trust Plane would be a "
        "second implementation of an existing primitive."),
    "gnosis.kernel.file_lock": (
        "the kernel's ONE cross-process advisory lock (111 lines, stdlib only), "
        "already the established pattern for a read-modify-write of durable JSON "
        "state. Without it two trusted writers can silently drop a transition and "
        "a monotonic state could regress; with it the compare-and-set is real."),
    # Stage-4 addition, entering by explicit allowlist diff as required:
    "gnosis.trust.publication": (
        "authoritative durable-publication slice (F-17 Stage 4) — the committed "
        "watermark, the single commit point, and crash recovery. Trusted because "
        "a compromise of it would let an uncommitted anchor be declared "
        "committed, or committed history be discarded as a crashed attempt."),
    # Stage-5 additions, each an explicit, reviewable enlargement of the TCB:
    "gnosis.trust.launch_spec": (
        "the sealed LaunchSpec (F-17 Stage 5) — how a ~12 kB logical argv crosses "
        "a 1024-character transport. Trusted because a compromise of it would let "
        "the Worker choose the argv the Director's launch executes."),
    "gnosis.trust.bootstrap": (
        "the trusted bootstrap (F-17 Stage 5). Listed because its BYTES are "
        "TCB — the Worker may read and execute it but not write it — even though "
        "the process RUNS AS THE WORKER and is therefore never treated as a "
        "trusted decision-maker; it only refuses instructions that fail the seal."),
    "gnosis.trust.worker_launcher": (
        "the trusted dedicated-worker launcher (F-17 Stage 5) — DPAPI credential, "
        "CreateProcessWithLogonW, suspended-until-verified identity checks, job "
        "containment and the environment allowlist. Trusted because a compromise "
        "of it would let a run execute under an identity nobody authorized."),
    # Stage-6 addition. This one SHRINKS the TCB rather than enlarging it:
    "gnosis.trust.bundle_verify": (
        "the minimal bundle verifier (F-17 Stage 6) — manifest read, hash, "
        "compare, and nothing else. It exists so the publisher can answer a "
        "question about bytes WITHOUT the machinery that produced them: before "
        "it, the default verify path pulled evidence_capture, git_evidence, "
        "input_lock and write_observer into a running publication, and a "
        "publisher that can execute Git is a publisher that can be made to "
        "execute Git. `evidence_capture` now imports THIS, never the reverse."),
}

# Trust Plane entry points whose load-time closure is measured. A new trusted
# module is added HERE and to TRUST_ALLOWLIST in the same reviewable diff — the
# stale-entry test below refuses an allowlist grant that no entry point loads.
TRUST_ENTRY_POINTS = ("gnosis.trust.anchor", "gnosis.trust.launch",
                      "gnosis.trust.deployment", "gnosis.trust.run_identity",
                      "gnosis.trust.publication", "gnosis.trust.launch_spec",
                      "gnosis.trust.worker_launcher", "gnosis.trust.bootstrap")

# ---------------------------------------------------------------------------
# Internal modules the Trust Plane imports LAZILY, inside a function body.
#
# A lazy import is invisible to the load-time closure measured above, but it is
# a full TCB dependency the moment that function runs — so a closed-world model
# that only looked at load time could be bypassed by moving the import into a
# function. Everything listed here therefore counts as TCB, and the source scan
# below refuses any lazy internal import that is neither allowlisted nor
# declared here.
#
# THIS LIST IS NOW EMPTY, AND THAT IS THE STAGE-6 RESULT.
#
# It used to hold `gnosis.kernel.evidence_capture`: verify_bundle was imported
# lazily inside publish_anchor / verify_anchored_bundle, which meant the
# PUBLISH-time closure was far larger than the load-time one and dragged
# git_evidence, input_lock and write_observer into a running publication. The
# `verify=` seam let a deployed publisher pass something smaller, but the
# DEFAULT still reached for the big one, and a default is what runs.
#
# Stage 6 moved the verifier to `gnosis.trust.bundle_verify` and pointed the
# default at it, so there is no lazy internal import left to declare. Measured
# after a REAL publication: 14 modules -> 11, and all four forbidden modules
# gone. If an entry reappears here, the publisher grew a dependency at run time
# that its load-time closure does not show.
# ---------------------------------------------------------------------------
DEFERRED_TCB_EXPANSION: dict[str, str] = {}


def _is_internal(module: str) -> bool:
    """True for a `gnosis` internal module (not merely a `gnosis`-prefixed name)."""
    return module == "gnosis" or module.startswith("gnosis.")


def unqualified_internal_modules(closure: Iterable[str]) -> list[str]:
    """The closed-world violation set: loaded internal modules NOT qualified for
    the TCB. Deliberately name-agnostic — it flags a module it has never heard
    of, which is the whole point of inverting the blacklist."""
    return sorted(m for m in closure if _is_internal(m) and m not in TRUST_ALLOWLIST)


_PROBE = """
import json, sys
_std = set(sys.stdlib_module_names)
def _internal(m):
    return m == "gnosis" or m.startswith("gnosis.")
def _external(mods):
    return sorted(m for m in mods if m.split(".")[0] not in _std and not _internal(m))
_before = set(sys.modules)
{body}
_after = set(sys.modules)
print(json.dumps({{
    "internal": sorted(m for m in _after if _internal(m)),
    "external": _external(_after - _before),
}}))
"""


def _closure(body: str) -> dict[str, list[str]]:
    """Run `body` in a CLEAN interpreter and report what it loaded.

    A fresh subprocess is required: pytest's own imports would otherwise
    pollute the measurement. `external` is a DELTA against interpreter start,
    so site-injected shims (virtualenv / editable-install finders) are not
    mistaken for Trust Plane dependencies.
    """
    out = subprocess.run([sys.executable, "-c", _PROBE.format(body=body)],
                         capture_output=True, text=True, check=True, cwd=str(REPO))
    result: dict[str, list[str]] = json.loads(out.stdout)
    return result


def _load_closure(module: str) -> set[str]:
    """gnosis.* modules loaded by importing `module` in a fresh interpreter."""
    return set(_closure(f"import {module}")["internal"])


# ---------------------------------------------------------------------------
# Closed-world enforcement
# ---------------------------------------------------------------------------
def test_trust_anchor_load_closure_is_closed_world() -> None:
    violations = unqualified_internal_modules(_load_closure("gnosis.trust.anchor"))
    assert not violations, (
        "trust.anchor loaded internal modules that are NOT qualified for the "
        f"Trust Plane TCB: {violations}. Either remove the dependency or add it "
        "to TRUST_ALLOWLIST with an architectural reason — enlarging the TCB is "
        "a deliberate act, never a side effect.")


def test_trust_launch_load_closure_is_closed_world() -> None:
    violations = unqualified_internal_modules(_load_closure("gnosis.trust.launch"))
    assert not violations, (
        f"trust.launch loaded unqualified internal modules: {violations}")


def test_every_trust_entry_point_load_closure_is_closed_world() -> None:
    """The closed-world rule applies to EVERY Trust Plane entry point, so a new
    trusted module cannot arrive with an unreviewed dependency graph behind it."""
    for entry in TRUST_ENTRY_POINTS:
        violations = unqualified_internal_modules(_load_closure(entry))
        assert not violations, (
            f"{entry} loaded unqualified internal modules: {violations}")


def test_the_allowlist_grants_nothing_it_does_not_need() -> None:
    """An allowlist that outgrows the real closure is a standing permission for
    a future dependency nobody reviewed. Every entry must be genuinely loaded."""
    reachable: set[str] = set()
    for entry in TRUST_ENTRY_POINTS:
        reachable |= _load_closure(entry)
    stale = sorted(set(TRUST_ALLOWLIST) - reachable)
    assert not stale, f"TRUST_ALLOWLIST grants modules the Trust Plane never loads: {stale}"


def test_an_arbitrary_unknown_internal_module_is_a_boundary_violation() -> None:
    """The property must not depend on knowing the dangerous name in advance.

    Every name below is one the previous worker-plane BLACKLIST would have
    missed (it contains none of engine/planner/scheduler/policy/runner/adapter/
    claude/codex/plugin/director/evidence_capture/integration/convergence/
    worktree), including one generated fresh at run time.
    """
    unknown = [
        "gnosis.kernel.credentials",          # exists today; blacklist missed it
        "gnosis.kernel.ledger",               # exists today; blacklist missed it
        "gnosis.transport.mcp_transport",     # exists today; blacklist missed it
        "gnosis.some_future_module",          # does not exist yet
        f"gnosis.{uuid.uuid4().hex}",         # a name nothing in this repo knows
    ]
    for name in unknown:
        closure = set(TRUST_ALLOWLIST) | {name}
        assert unqualified_internal_modules(closure) == [name], (
            f"the closed-world check failed to flag {name}")


def test_a_real_new_internal_module_in_the_closure_is_caught_end_to_end() -> None:
    """A REAL new `gnosis.*` module, created and imported for real, is caught.

    The predicate test above proves the check is name-agnostic; this proves the
    whole measured path is — a module that exists nowhere in the repo, written
    to disk and genuinely imported into the Trust Plane's process, lands in the
    measured closure and is reported as a violation. No source is mutated:
    AM12 in scripts/mutation_check_authority.py covers the "trust.anchor itself
    imports it" variant.
    """
    name = f"zz_future_dependency_{uuid.uuid4().hex[:8]}"
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / f"{name}.py").write_text("VALUE = 1\n", encoding="utf-8")
        body = (
            "import gnosis, gnosis.trust.anchor, importlib\n"
            f"gnosis.__path__.append({tmp!r})\n"
            "importlib.invalidate_caches()\n"
            f"import gnosis.{name}\n"
        )
        closure = _closure(body)["internal"]
    assert f"gnosis.{name}" in closure, "the probe did not actually import the new module"
    assert unqualified_internal_modules(closure) == [f"gnosis.{name}"]


def _is_module(dotted: str) -> bool:
    """True if `dotted` names a real module/package under src/."""
    path = SRC.joinpath(*dotted.split("."))
    return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()


def _internal_imports(path: Path) -> set[str]:
    """Every internal `gnosis.*` module imported by `path` at ANY nesting level
    — module scope, function bodies, `try:` blocks alike."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = ".".join(path.relative_to(SRC).with_suffix("").parts[:-1])
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            root = node.module or ""
            if node.level:  # relative import -> resolve against the package
                base = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                root = ".".join([*base, root] if root else base)
            if root:
                found.add(root)
                # `from gnosis.kernel import canonical` also imports a module
                found.update(f"{root}.{a.name}" for a in node.names
                             if _is_module(f"{root}.{a.name}"))
    return {m for m in found if _is_internal(m)}


def test_the_trust_plane_declares_every_internal_import_including_lazy_ones() -> None:
    """Closed-world for DEFERRED imports too.

    The load-time closure tests cannot see an import written inside a function
    body — which would otherwise be a trivial way to grow the TCB without
    tripping any check. This reads the Trust Plane's own source instead, so an
    unqualified internal dependency is refused wherever it is written. AM13 in
    scripts/mutation_check_authority.py is the mutant for exactly that bypass.
    """
    qualified = set(TRUST_ALLOWLIST) | set(DEFERRED_TCB_EXPANSION)
    offenders: dict[str, list[str]] = {}
    for source in sorted((SRC / "gnosis" / "trust").rglob("*.py")):
        bad = sorted(_internal_imports(source) - qualified)
        if bad:
            offenders[source.name] = bad
    assert not offenders, (
        f"the Trust Plane imports unqualified internal modules: {offenders}. A "
        "lazy (function-body) import is still a TCB dependency: allowlist it, "
        "declare it in DEFERRED_TCB_EXPANSION, or do not depend on it.")


_FORBIDDEN_DYNAMIC_NAMES: frozenset[str] = frozenset({
    "exec", "eval", "compile", "__import__",
})
_FORBIDDEN_DYNAMIC_ATTRS: frozenset[str] = frozenset({
    "import_module", "spec_from_file_location", "module_from_spec",
    "exec_module", "load_module", "SourceFileLoader", "ExtensionFileLoader",
})


def test_the_trust_plane_loads_no_code_dynamically() -> None:
    """FROZEN ARCHITECTURAL RULE (Stage-2 review).

    The closed-world import model is a STATIC control: it reasons about import
    statements. Dynamic loading — `importlib.import_module` with a computed
    name, `__import__`, `exec`/`eval`/`compile`, a loader pointed at a path,
    plugin discovery — would let code enter the Trust Plane without any import
    statement to check, silently enlarging the TCB. It was the standing
    residual risk of Stage 1; here it becomes an enforced property.

    Introducing any of these needs an explicit review decision, which means
    changing this test on purpose — not slipping past it.
    """
    offenders: dict[str, list[str]] = {}
    for source in sorted((SRC / "gnosis" / "trust").rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        found: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in _FORBIDDEN_DYNAMIC_NAMES:
                found.append(f"{node.id} (line {node.lineno})")
            elif isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_DYNAMIC_ATTRS:
                found.append(f".{node.attr} (line {node.lineno})")
            elif isinstance(node, ast.Import):
                found += [f"import {a.name} (line {node.lineno})" for a in node.names
                          if a.name == "importlib" or a.name.startswith("importlib.")]
            elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                    "importlib"):
                found.append(f"from {node.module} (line {node.lineno})")
        if found:
            offenders[source.name] = sorted(found)
    assert not offenders, (
        "the Trust Plane reaches for dynamic code loading: "
        f"{offenders}. Code that arrives without an import statement cannot be "
        "checked by the closed-world model; enlarging the TCB that way is "
        "forbidden without an explicit review decision.")


def test_the_deferred_expansion_list_is_not_stale() -> None:
    """A declared lazy dependency that no longer exists in the source would be a
    standing, unreviewed permission — the same defect as a stale allowlist."""
    imported: set[str] = set()
    for source in sorted((SRC / "gnosis" / "trust").rglob("*.py")):
        imported |= _internal_imports(source)
    stale = sorted(set(DEFERRED_TCB_EXPANSION) - imported)
    assert not stale, f"DEFERRED_TCB_EXPANSION declares dependencies nobody imports: {stale}"


def test_the_trust_plane_pulls_in_no_third_party_code() -> None:
    """stdlib is out of scope for the closed-world control, but third-party code
    is not: a package pulled into the TCB is a supply-chain path into it."""
    external = _closure("import gnosis.trust.anchor")["external"]
    assert not external, f"trust.anchor pulled third-party modules into the TCB: {external}"


def test_evidence_capture_is_only_a_lazy_import() -> None:
    # importing the anchor module must NOT eagerly import the capture machinery
    closure = _load_closure("gnosis.trust.anchor")
    assert "gnosis.kernel.evidence_capture" not in closure


# ---------------------------------------------------------------------------
# Single-implementation / facade invariants
# ---------------------------------------------------------------------------
def test_facade_points_at_the_single_authoritative_implementation() -> None:
    import gnosis.kernel.authority as facade
    from gnosis.trust import anchor, launch

    assert facade.AnchorStore is anchor.AnchorStore
    assert facade.AnchorRecord is anchor.AnchorRecord
    assert facade.RunIdentity is anchor.RunIdentity
    assert facade.publish_anchor is anchor.publish_anchor
    assert facade.verify_anchored_bundle is anchor.verify_anchored_bundle
    assert facade.AuthorityUnavailable is launch.AuthorityUnavailable
    assert facade.process_integrity is launch.process_integrity
    assert facade.assert_integrity is launch.assert_integrity
    assert facade.label_high_no_write_up is launch.label_high_no_write_up
    assert facade.assert_publisher_identity is launch.assert_publisher_identity


def test_canonical_hash_is_not_duplicated() -> None:
    from gnosis.kernel import canonical
    from gnosis.trust import anchor

    # the anchor module uses the ONE canonical primitive, not a private copy
    assert anchor.hash_canonical is canonical.hash_canonical
    assert anchor.GENESIS_HASH is canonical.GENESIS_HASH


def test_no_probe_anchor_store_in_production_source() -> None:
    hits = [
        p for p in SRC.rglob("*.py")
        if "ProbeAnchorStore" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not hits, f"ProbeAnchorStore (probe code) leaked into src/: {hits}"


def test_publisher_identity_precondition_fails_closed_when_not_the_publisher() -> None:
    # The AnchorStore precondition locus (Stage 1 = the same-user-MIC HIGH
    # check; future = the RESTRICTED service-SID gate). It must fail closed when
    # the current identity is not the trusted publisher, and stay silent when it
    # is. Windows-only: the MIC gate is a Windows mechanism.
    if sys.platform != "win32":
        import pytest
        pytest.skip("publisher-identity precondition is a Windows mechanism")
    from gnosis.trust import launch

    original = launch.process_integrity
    try:
        launch.process_integrity = lambda: "Medium"
        raised = False
        try:
            launch.assert_publisher_identity(require_high=True)
        except launch.AuthorityUnavailable:
            raised = True
        assert raised, "precondition must fail closed for a non-publisher identity"

        launch.process_integrity = lambda: "High"
        launch.assert_publisher_identity(require_high=True)  # must not raise
    finally:
        launch.process_integrity = original


def test_authority_facade_re_exports_the_public_api() -> None:
    import gnosis.kernel.authority as facade

    for name in (
        "ANCHOR_SCHEMA", "AnchorRecord", "AnchorStore", "AuthorityUnavailable",
        "RunIdentity", "SID_HIGH", "SID_LOW", "SID_MEDIUM", "assert_integrity",
        "label_high_no_write_up", "lowered_primary_token", "process_integrity",
        "publish_anchor", "run_at_integrity", "verify_anchored_bundle",
    ):
        assert hasattr(facade, name), f"facade dropped {name}"


def test_the_facades_private_helper_re_exports_are_recorded_debt() -> None:
    """`_bundle_head_sha` / `_bundle_content_digest` are private helpers the
    facade still re-exports for compatibility with existing importers. That is
    accepted, TRACKED cleanup debt (docs/NEXT_ACTIONS.md), not an oversight —
    this test pins the set so it cannot grow quietly into a private-API surface.
    """
    import gnosis.kernel.authority as facade

    private = sorted(n for n in facade.__all__ if n.startswith("_"))
    assert private == ["_bundle_content_digest", "_bundle_head_sha"], (
        f"the facade's private re-export surface changed: {private}")
