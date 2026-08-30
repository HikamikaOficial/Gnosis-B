"""The production directory layout and the ACL matrix, as data (F-17 Stage 8).

This module is PURE: no filesystem, no `icacls`, no Git, no OS calls. It answers
two questions a reviewer must be able to check by reading, not by trusting:

    WHERE does every authority-bearing thing live?      -> DeploymentLayout
    WHO may do WHAT to each of them?                     -> the ACL matrix

The layout separates, deliberately:

    the trusted CODE base   (Program Files: admin-writable, Users read-only) —
        runtime, the publisher trust package, the worker bootstrap, and the
        deployment descriptors observation reads;
    the trusted STATE base  (ProgramData: protected, inheritance stripped) —
        anchors, run identities, the AUTHORITATIVE evidence bundles, the DPAPI
        credential blob, the service config, logs;
    the WORKER-PLANE base   (ProgramData\\...\\Work) — the per-run worktree the
        untrusted worker may write.

THE CANDIDATE / AUTHORITATIVE SPLIT (Stage 7 R5, closed here). The worker writes
its candidate output under the worker-plane `Work\\<run_id>` root, which it may
Modify. The AUTHORITATIVE evidence the Publisher's Stage-7 boundary gate reads
lives under the state base's `bundles` root, where the worker has NO ACE at all —
so a worker cannot write the SUMMARY whose verdict authorizes publication.

THE ACL MATRIX. Four principals, resolved to SIDs at provision time:

    MAINTENANCE  the trusted maintainer (Administrators) — installs/updates
    SYSTEM       NT AUTHORITY\\SYSTEM
    SERVICE      the Publisher's per-service RESTRICTED SID (S-1-5-80-...)
    WORKER       the dedicated non-admin worker account's SID

The invariant the whole stage exists to guarantee: the WORKER never holds WRITE,
MODIFY, DELETE, WRITE_DAC or WRITE_OWNER on any trusted code or state root. It
holds READ+EXECUTE on what it must run (runtime, bootstrap, toolchain), MODIFY on
its own `Work\\<run_id>` worktree, and NOTHING on the credential blob, the
anchors, the run identities, the authoritative bundles, the publisher code or the
service config. Absence of an ACE, on an inheritance-stripped root, is a hard
deny.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Principal(Enum):
    MAINTENANCE = "MAINTENANCE"
    SYSTEM = "SYSTEM"
    SERVICE = "SERVICE"
    WORKER = "WORKER"


class Access(Enum):
    """The access an ACE grants, in the vocabulary icacls understands.

    Deliberately small. NONE is not a value: a principal that should have no
    access simply has no ACE, which on an inheritance-stripped root is a full
    deny — expressed, not defaulted.
    """

    FULL = "(OI)(CI)F"           # create/read/write/delete/WDAC/WO — trusted only
    MODIFY = "(OI)(CI)M"         # create/read/write/delete, not WDAC/WO
    READ_EXECUTE = "(OI)(CI)(RX)"  # read + execute + traverse; NO write of any kind
    READ = "(OI)(CI)(R)"         # read only


@dataclass(frozen=True)
class RootSpec:
    """One authority-bearing directory: where it is, and its exact ACL.

    `break_inheritance` is True for every protected root: the parent
    (Program Files / ProgramData) grants BUILTIN\\Users read/execute (and, on
    ProgramData, create) by inheritance, and a worker is a Users member, so a
    child that did not strip inheritance would silently grant the worker RX.
    Stripping it makes the grant list below the WHOLE truth about the root.
    """

    key: str
    relative_to: str  # "code" | "state" | "work"
    subpath: str      # relative path under the base ("" = the base root itself)
    purpose: str
    break_inheritance: bool
    grants: tuple[tuple[Principal, Access], ...]

    def worker_access(self) -> Access | None:
        for principal, access in self.grants:
            if principal is Principal.WORKER:
                return access
        return None


# ---------------------------------------------------------------------------
# THE ACL MATRIX. This tuple IS the matrix; the provisioner renders it to
# icacls and the evidence prints it. Order is for a reader, not for precedence.
# ---------------------------------------------------------------------------
_M, _S, _SVC, _W = (Principal.MAINTENANCE, Principal.SYSTEM,
                    Principal.SERVICE, Principal.WORKER)
_F, _MOD, _RX, _R = Access.FULL, Access.MODIFY, Access.READ_EXECUTE, Access.READ

_ROOTS: tuple[RootSpec, ...] = (
    # -- trusted CODE base (Program Files) --
    RootSpec("code_root", "code", "", "the trusted code base",
             True, ((_M, _F), (_S, _F))),
    RootSpec("runtime", "code", "runtime",
             "the deployed Python interpreter tree (with python._pth)",
             True, ((_M, _F), (_S, _F), (_SVC, _RX), (_W, _RX))),
    RootSpec("publisher", "code", "publisher",
             "the publisher trust package (= the observed trust_root); the "
             "service reads+executes it, the worker has no access",
             True, ((_M, _F), (_S, _F), (_SVC, _RX))),
    RootSpec("bootstrap", "code", "bootstrap",
             "the worker bootstrap the launcher runs AS the worker; worker "
             "reads+executes, never writes",
             True, ((_M, _F), (_S, _F), (_W, _RX))),
    RootSpec("toolchain", "code", "toolchain",
             "the relocated worker toolchain (git, claude, node); worker "
             "reads+executes",
             True, ((_M, _F), (_S, _F), (_W, _RX))),
    # -- trusted STATE base (ProgramData) --
    RootSpec("state_root", "state", "",
             "the trusted state base; holds config.json, the service reads it",
             True, ((_M, _F), (_S, _F), (_SVC, _RX))),
    RootSpec("anchors", "state", "anchors",
             "the AnchorStore ledger + watermark; the service commits here",
             True, ((_M, _F), (_S, _F), (_SVC, _MOD))),
    RootSpec("runidentity", "state", "runidentity",
             "the trusted run-identity store; created by the Director, the "
             "ANCHORED transition written by the service",
             True, ((_M, _F), (_S, _F), (_SVC, _MOD))),
    RootSpec("bundles", "state", "bundles",
             "the AUTHORITATIVE evidence the Stage-7 gate reads; written by the "
             "trusted capture, read by the service, WORKER HAS NO ACE",
             True, ((_M, _F), (_S, _F), (_SVC, _R))),
    RootSpec("secrets", "state", "secrets",
             "the DPAPI worker-credential blob; the worker is DENIED (no ACE)",
             True, ((_M, _F), (_S, _F))),
    RootSpec("logs", "state", "logs",
             "operational service logs",
             True, ((_M, _F), (_S, _F), (_SVC, _MOD))),
    # -- WORKER-PLANE base (ProgramData\...\Work) --
    RootSpec("work", "work", "",
             "the per-run worktree where untrusted worker code runs; the only "
             "place the worker may write",
             True, ((_M, _F), (_S, _F), (_W, _MOD))),
)


@dataclass(frozen=True)
class DeploymentLayout:
    """Concrete paths for a deployment, production or disposable-equivalent.

    `code_base` lives under Program Files (admin-writable, Users read-only);
    `state_base` and `work_base` under ProgramData (protected, inheritance
    stripped). The disposable qualification uses the SAME ancestors with a
    disposable leaf name, so it is semantically equivalent to production.
    """

    code_base: str
    state_base: str
    work_base: str
    release_id: str = "current"

    @property
    def code_release_base(self) -> str:
        """The versioned code root for THIS release.

        Code is versioned so update stages a new release beside the old and
        rollback flips the service back to the prior one; the state base is
        stable across releases (anchors and run identities are durable). Both
        moves are maintenance-only — the worker has no write on either.
        """
        return f"{self.code_base}\\releases\\{self.release_id}"

    def base_for(self, relative_to: str) -> str:
        return {"code": self.code_release_base, "state": self.state_base,
                "work": self.work_base}[relative_to]

    def path(self, spec: RootSpec) -> str:
        base = self.base_for(spec.relative_to)
        return base if spec.subpath == "" else f"{base}\\{spec.subpath}"

    def roots(self) -> tuple[RootSpec, ...]:
        return _ROOTS

    # -- named paths the provisioner and observation need --
    @property
    def trust_root(self) -> str:
        """The observed trust package root (deployment.observe_trust_package)."""
        return f"{self.code_release_base}\\publisher"

    @property
    def runtime_root(self) -> str:
        return f"{self.code_release_base}\\runtime"

    @property
    def runtime_executable(self) -> str:
        return f"{self.code_release_base}\\runtime\\python.exe"

    @property
    def service_entry(self) -> str:
        return f"{self.code_release_base}\\publisher\\service_main.py"

    @property
    def anchors_root(self) -> str:
        return f"{self.state_base}\\anchors"

    @property
    def runidentity_root(self) -> str:
        return f"{self.state_base}\\runidentity"

    @property
    def bundles_root(self) -> str:
        return f"{self.state_base}\\bundles"

    @property
    def secrets_blob(self) -> str:
        return f"{self.state_base}\\secrets\\worker.dpapi"

    @property
    def config_path(self) -> str:
        return f"{self.state_base}\\config.json"

    @property
    def log_path(self) -> str:
        return f"{self.state_base}\\logs\\publisher.log"

    @property
    def package_json(self) -> str:
        return f"{self.code_release_base}\\publisher\\PACKAGE.json"

    @property
    def pipe_policy_json(self) -> str:
        return f"{self.code_release_base}\\publisher\\PIPE_POLICY.json"

    @property
    def deployment_json(self) -> str:
        return f"{self.code_release_base}\\publisher\\DEPLOYMENT.json"

    @property
    def pth_file(self) -> str:
        # CPython reads `python<major><minor>._pth` next to python.exe.
        return f"{self.code_release_base}\\runtime\\python._pth"


# ---------------------------------------------------------------------------
# The invariants the matrix must satisfy. Pure predicates over the matrix, so a
# test can assert them and a mutant that weakens the matrix is caught here
# before any OS state is created.
# ---------------------------------------------------------------------------
_WORKER_WRITABLE_KEYS = frozenset({"work"})  # the ONLY roots a worker may write
_WORKER_DENIED_KEYS = frozenset({  # roots the worker must have NO ACE on
    "publisher", "state_root", "anchors", "runidentity", "bundles", "secrets",
    "logs",
})


def worker_never_writes_a_trusted_root() -> list[str]:
    """Return the keys where the worker holds a writing access. Empty == good."""
    bad: list[str] = []
    for spec in _ROOTS:
        access = spec.worker_access()
        if access in (Access.FULL, Access.MODIFY) and spec.key not in _WORKER_WRITABLE_KEYS:
            bad.append(spec.key)
    return bad


def worker_denied_roots_grant_no_worker_ace() -> list[str]:
    """Return the must-be-denied keys that mistakenly grant the worker. Empty == good."""
    bad: list[str] = []
    by_key = {s.key: s for s in _ROOTS}
    for key in _WORKER_DENIED_KEYS:
        spec = by_key[key]
        if spec.worker_access() is not None:
            bad.append(key)
    return bad


def every_protected_root_breaks_inheritance() -> list[str]:
    """Return any root that does not strip inheritance. Empty == good."""
    return [s.key for s in _ROOTS if not s.break_inheritance]
