"""Prove the F-17 Stage-6 composition suite catches what it claims.

Each mutant restores a real way for the composed path to fail open: an
authority-bearing value taken from the run being published instead of from
provisioning, a binding dropped from a digest, a containment check removed, the
pipe granting the bit that lets the Worker become the server, the durable
protocol swapped for the old direct write, the big evidence machinery back in
the publisher's closure.

A mutant that SURVIVES is a claim the suite does not actually check.

    PYTHONUTF8=1 .venv/Scripts/python.exe scripts/mutation_check_stage6.py [--out PATH]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PUBLISHER = "src/gnosis/trust/publisher.py"
PIPE = "src/gnosis/trust/pipe_server.py"
HOST = "src/gnosis/trust/service_host.py"
SERVICE = "src/gnosis/trust/publisher_service.py"
ORCH = "src/gnosis/trust/orchestration.py"
ANCHOR = "src/gnosis/trust/anchor.py"
RUNID = "src/gnosis/trust/run_identity.py"
DEPLOY = "src/gnosis/trust/deployment.py"
VERIFY = "src/gnosis/trust/bundle_verify.py"

SUITE = [
    "tests/test_publisher_service.py",
    "tests/test_publisher_pipe.py",
    "tests/test_trusted_orchestration.py",
    "tests/test_run_identity_authorization.py",
    "tests/test_trust_boundary.py",
    "tests/test_durable_publication.py",
    "tests/test_authority_boundary.py",
    "tests/test_deployment_identity.py",
]


@dataclass(frozen=True)
class Mutant:
    name: str
    description: str
    edits: list[tuple[str, str, str]] = field(default_factory=list)


# Multi-line anchors live as named constants. A mutant's anchor text has to
# match the source EXACTLY, and naming them keeps that text readable — the same
# convention the Stage-4 mutation script established.
_INSIDE_COMPONENTWISE = (
    '    root_parts = _resolved(root).split("\\\\")\n'
    '    candidate_parts = _resolved(candidate).split("\\\\")\n'
    "    return candidate_parts[: len(root_parts)] == root_parts"
)
_INSIDE_PREFIX = "    return _resolved(candidate).startswith(_resolved(root))"

_IDENTITY_EMITS_LAUNCH = (
    "        if self.schema == RUN_IDENTITY_SCHEMA_V2:\n"
    '            out["launch_spec_digest"] = self.launch_spec_digest'
)
_IDENTITY_DROPS_LAUNCH = (
    "        if False:\n"
    '            out["launch_spec_digest"] = self.launch_spec_digest'
)

_DEPLOY_EMITS_TREE = (
    "        if self.schema == DEPLOYMENT_SCHEMA_V2:\n"
    "            assert self.runtime_tree is not None  # enforced in __post_init__\n"
    '            out["runtime_tree"] = self.runtime_tree.to_dict()'
)
_DEPLOY_DROPS_TREE = (
    "        if False:\n"
    "            assert self.runtime_tree is not None\n"
    '            out["runtime_tree"] = self.runtime_tree.to_dict()'
)

_DEPLOY_REQUIRES_TREE = (
    "            if self.runtime_tree is None:\n"
    "                raise DeploymentIdentityUnavailable("
)
_DEPLOY_TREE_OPTIONAL = (
    "            if False:\n"
    "                raise DeploymentIdentityUnavailable("
)

_OBSERVE_V2 = (
    "        schema=CURRENT_DEPLOYMENT_SCHEMA,\n"
    "        package=package,\n"
    "        runtime=observe_runtime(config.runtime_executable),\n"
    "        runtime_tree=observe_runtime_tree(config.runtime_root),"
)
_OBSERVE_V1 = (
    "        schema=DEPLOYMENT_SCHEMA,\n"
    "        package=package,\n"
    "        runtime=observe_runtime(config.runtime_executable),"
)

_GATE_VERIFIES = (
    "    result = verify_bundle(evidence.bundle_dir)\n"
    "    if not result.verified:"
)
_GATE_IGNORES = (
    "    result = verify_bundle(evidence.bundle_dir)\n"
    "    if False:"
)

_PIPE_LOCAL_ONLY = (
    "            (PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT\n"
    "             | PIPE_REJECT_REMOTE_CLIENTS),"
)
_PIPE_REMOTE_OK = "            (PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT),"

# THE OVERSIZE DECISION MOVED WHEN THE PIPE WAS REPAIRED, and the mutant moved
# with it. On a message-mode pipe ReadFile FAILS with ERROR_MORE_DATA rather
# than returning a truncated success, so the old `len(raw) >= MAX` test could
# never fire - which is exactly why the first version of this mutant survived.
# It now drops the refusal, so an oversized message falls through to the parser.
_PIPE_BOUNDS = (
    '            self._note(f"oversized request from pid={client_pid}, discarded")\n'
    '            return "REJECTED:oversized"'
)
_PIPE_UNBOUNDED = (
    '            self._note(f"oversized request from pid={client_pid}, discarded")'
)

MUTANTS: list[Mutant] = [
    # ---- the confused-deputy family: authority taken from the wrong place ----
    Mutant("S6M01",
           "the owner check reads the run being published, not the service's configuration",
           [(PUBLISHER,
             "        if identity.owner_worker_sid != self.config.authorized_worker_sid:",
             "        if identity.owner_worker_sid != identity.owner_worker_sid:")]),
    Mutant("S6M02",
           "the publisher stops comparing the deployment it runs under",
           [(PUBLISHER,
             "        if identity.deployment_digest != self.config.expected_deployment_digest:",
             "        if False:")]),
    Mutant("S6M03",
           "the request carries the run's own deployment instead of the service's",
           [(PUBLISHER,
             "            expected_deployment_digest=self.config.expected_deployment_digest,",
             "            expected_deployment_digest=identity.deployment_digest,")]),
    Mutant("S6M04",
           "the request carries the run's own owner instead of the service's",
           [(PUBLISHER,
             "            expected_owner_worker_sid=self.config.authorized_worker_sid,",
             "            expected_owner_worker_sid=identity.owner_worker_sid,")]),

    # ---- evidence path authority ----
    Mutant("S6M05",
           "an evidence directory outside the trusted root is opened anyway",
           [(PUBLISHER,
             "        if not _inside(self.config.evidence_root, bundle_dir):",
             "        if False:")]),
    Mutant("S6M06",
           "containment becomes a string prefix, so a sibling directory passes",
           [(PUBLISHER, _INSIDE_COMPONENTWISE, _INSIDE_PREFIX)]),
    Mutant("S6M07",
           "the bundle path is rebuilt from the run id instead of read from the record",
           [(PUBLISHER,
             "        bundle_dir = Path(identity.bundle_path)",
             "        bundle_dir = self.config.evidence_root / run_id")]),

    # ---- the request grammar ----
    Mutant("S6M08",
           "the run id may contain path separators",
           [(PUBLISHER,
             '_REQUEST = re.compile(r"^PUBLISH (?P<run_id>[A-Za-z0-9][A-Za-z0-9._-]{0,127})$")',
             '_REQUEST = re.compile(r"^PUBLISH (?P<run_id>.{1,128})$")')]),
    Mutant("S6M09",
           "an oversized request is parsed instead of refused",
           [(PUBLISHER,
             '        if len(request.encode("utf-8", errors="ignore")) > MAX_REQUEST_BYTES:',
             "        if False:")]),

    # ---- the publish gate ----
    Mutant("S6M10",
           "PUBLISHABLE stops being required",
           [(RUNID,
             "    if record.publication_state is not PublicationState.PUBLISHABLE:",
             "    if False:")]),
    Mutant("S6M11",
           "the sealed launch intent is no longer compared",
           [(RUNID,
             "        if request.expected_launch_spec_digest != identity.launch_spec_digest:",
             "        if False:")]),
    Mutant("S6M12",
           "a launch binding is satisfied by declining to check it",
           [(RUNID,
             "        if request.expected_launch_spec_digest is None:",
             "        if False:")]),
    Mutant("S6M13",
           "an artifact from an earlier generation may publish as a later one",
           [(RUNID,
             "    if request.expected_epoch != identity.epoch:",
             "    if False:")]),

    # ---- the bindings themselves ----
    Mutant("S6M14",
           "the launch intent is dropped from the immutable identity digest",
           [(ANCHOR, _IDENTITY_EMITS_LAUNCH, _IDENTITY_DROPS_LAUNCH)]),
    Mutant("S6M15",
           "a V2 identity no longer needs a launch binding",
           [(ANCHOR,
             '            _require_digest(self.launch_spec_digest, "a V2 RunIdentity\'s launch_spec_digest")',
             "            pass")]),
    Mutant("S6M16",
           "the runtime tree is dropped from the deployment digest",
           [(DEPLOY, _DEPLOY_EMITS_TREE, _DEPLOY_DROPS_TREE)]),
    Mutant("S6M17",
           "a V2 deployment identity no longer needs the runtime tree",
           [(DEPLOY, _DEPLOY_REQUIRES_TREE, _DEPLOY_TREE_OPTIONAL)]),
    Mutant("S6M18",
           "observation goes back to emitting an unbound V1 deployment",
           [(DEPLOY, _OBSERVE_V2, _OBSERVE_V1)]),
    Mutant("S6M19",
           "the measured runtime need not be the runtime that executes",
           [(DEPLOY, "    _assert_executable_inside_runtime_root(config)\n", "")]),

    # ---- the writer's seam ----
    Mutant("S6M20",
           "a run may be created under a deployment that never measured the runtime",
           [(ORCH, "    if not deployment.binds_runtime_tree:", "    if False:")]),
    Mutant("S6M21",
           "a seal for another run may be bound to this plan",
           [(ORCH, "    if spec.run_id != plan.run_id:", "    if False:")]),
    Mutant("S6M22",
           "PUBLISHABLE stops requiring a verifying bundle",
           [(ORCH, _GATE_VERIFIES, _GATE_IGNORES)]),
    Mutant("S6M23",
           "a failed run becomes publishable",
           [(ORCH, "    if evidence.exit_code != 0:", "    if False:")]),
    Mutant("S6M24",
           "a bundle somewhere other than the trusted identity's path is accepted",
           [(ORCH,
             "    if Path(identity.bundle_path) != evidence.bundle_dir:",
             "    if False:")]),

    # ---- the endpoint ----
    Mutant("S6M25",
           "the Worker is granted the pipe's append bit, which is CREATE_PIPE_INSTANCE",
           [(PIPE, "WORKER_PIPE_ACCESS = 0x00120083",
             "WORKER_PIPE_ACCESS = 0x00120087")]),
    Mutant("S6M26",
           "the server will attach to a pipe name somebody else already created",
           [(PIPE,
             "            PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,",
             "            PIPE_ACCESS_DUPLEX,")]),
    Mutant("S6M27",
           "remote clients are accepted",
           [(PIPE, _PIPE_LOCAL_ONLY, _PIPE_REMOTE_OK)]),
    Mutant("S6M28",
           "the pipe stops being single-instance",
           [(PIPE, "MAX_INSTANCES = 1", "MAX_INSTANCES = 8")]),
    Mutant("S6M29",
           "an oversized message is handed to the parser",
           [(PIPE, _PIPE_BOUNDS, _PIPE_UNBOUNDED)]),

    # ---- composition and fallback ----
    Mutant("S6M30",
           "the service starts even when the SCM never launched it",
           [(HOST,
             '            raise OSError(f"StartServiceCtrlDispatcher failed {error}{hint}")',
             "            return")]),
    Mutant("S6M31",
           "the service starts with an incomplete configuration",
           [(SERVICE, "        if missing:", "        if False:")]),
    Mutant("S6M32",
           "the endpoint opens before durable state has been reconciled",
           [(SERVICE, "    recover_at_startup(config, log)\n", "")]),
    Mutant("S6M33",
           "the big evidence machinery returns to the publisher's closure",
           [(ANCHOR,
             "from gnosis.trust.bundle_verify import verify_bundle",
             "from gnosis.kernel.evidence_capture import verify_bundle")]),
    Mutant("S6M34",
           "the external anchor stops being compared in verification",
           [(VERIFY,
             "    if expected_digest is not None and recomputed != expected_digest:",
             "    if False:")]),
]


def _pytest() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, "-m", "pytest", *SUITE, "-q", "-x"],
                          cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)
    tail = (proc.stdout.strip().splitlines() or [""])[-1][:200]
    return proc.returncode, tail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    lines: list[str] = []

    def say(message: str) -> None:
        print(message)
        lines.append(message)

    touched = sorted({rel for m in MUTANTS for rel, _, _ in m.edits})
    originals = {rel: (REPO / rel).read_text(encoding="utf-8") for rel in touched}

    say("F-17 STAGE 6 — MUTATION CHECK OVER THE COMPOSED TRUST PATH")
    say("=" * 74)
    code, tail = _pytest()
    say(f"BASELINE: exit={code}  {tail}")
    if code != 0:
        say("baseline is not green; refusing to attribute mutant verdicts")
        return 1
    say("")

    survived: list[str] = []
    try:
        for mutant in MUTANTS:
            applied = True
            for rel, old, new in mutant.edits:
                src = (REPO / rel).read_text(encoding="utf-8")
                if old not in src:
                    applied = False
                    break
                (REPO / rel).write_text(src.replace(old, new, 1),
                                        encoding="utf-8", newline="")
            if not applied:
                survived.append(f"{mutant.name} (NOT APPLIED)")
                say(f"{mutant.name}: {mutant.description}\n  verdict: NOT APPLIED")
            else:
                code, tail = _pytest()
                say(f"{mutant.name}: {mutant.description}")
                say(f"  result: exit={code}  {tail}")
                say(f"  verdict: {'CAUGHT' if code != 0 else 'SURVIVED'}")
                if code == 0:
                    survived.append(mutant.name)
            for rel, text in originals.items():
                (REPO / rel).write_text(text, encoding="utf-8", newline="")
            say("")
    finally:
        for rel, text in originals.items():
            (REPO / rel).write_text(text, encoding="utf-8", newline="")

    code, tail = _pytest()
    say(f"RESTORED: exit={code}  {tail}")
    say(f"mutants: {len(MUTANTS)}  survived/aborted: {len(survived)}"
        + (f"  -> {survived}" if survived else ""))
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if survived or code != 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
