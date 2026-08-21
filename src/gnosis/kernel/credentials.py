"""Credential identity, and the boundary rotation may not cross by itself.

ADR-0016 left the hold plane keyed on ONE `credential` string fixed when
the scheduler is built, so "the account is held" and "this key is held"
were the same statement and there was nothing to rotate to.

The reason this module is not just a list of strings is that a credential
set is a **privilege boundary, not a pool**. Two rules of the
constitution live exactly here:

- rule 25: subscription credentials are not an improvised API;
- rule 26: no silent fallback to paid APIs.

Both are about CROSSING a boundary, so the boundary has to exist as data
the kernel can check. A rotation that quietly moves a queued brief from a
seat to a metered key is not a retry — it is a billing decision nobody
made, arriving as an availability optimisation.

**Secrets never enter this module.** A credential names the environment
variables its value lives in; the kernel holds the reference, the parent
process holds the value, and nothing here can be written to a ledger, a
run record or an evidence file and leak one.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CredentialKind(str, Enum):
    """What using this credential COSTS, which is what makes it a boundary."""

    # A seat or plan. Rule 25: not to be driven as an API.
    SUBSCRIPTION = "SUBSCRIPTION"
    # Billed per call. Rule 26: never fallen back to silently.
    METERED = "METERED"
    # A local model or an offline stub: no external billing, no seat.
    LOCAL = "LOCAL"


class CredentialUnavailable(RuntimeError):
    """The named credential cannot be bound to a launch.

    Raised rather than falling back to the ambient environment. Inheriting
    the parent's variables would launch as whatever credential happens to
    be configured — which is precisely the silent fallback rule 26
    forbids, and it would look like a successful rotation.
    """


@dataclass(frozen=True)
class Credential:
    """One identity a launch can run as.

    `env_from` maps the variable the CHILD needs to the variable in the
    parent environment that holds its value: `{"ANTHROPIC_API_KEY":
    "GNOSIS_KEY_B"}`. The indirection is the point — the kernel can name,
    order, hold and audit a credential without ever touching its secret.
    """

    credential_id: str
    kind: CredentialKind
    env_from: Mapping[str, str] = field(default_factory=dict)
    # Variables to REMOVE from the child environment. A stale
    # `ANTHROPIC_API_KEY` left in place while a subscription credential is
    # selected is the same silent fallback in the other direction.
    env_clear: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.credential_id:
            raise ValueError("a credential must have an id")
        if not isinstance(self.kind, CredentialKind):
            raise TypeError(f"kind must be a CredentialKind, got {self.kind!r}")
        for child_var, parent_var in self.env_from.items():
            if not child_var or not parent_var:
                raise ValueError(
                    f"{self.credential_id}: empty variable name in env_from")

    def environment(self, base: Mapping[str, str]) -> dict[str, str]:
        """The child's environment, or raise.

        A missing source variable is fatal here. Returning `base`
        unchanged would hand the launch whatever credential the ambient
        environment carries, report success, and bill somebody nobody
        chose — an availability optimisation that crossed a boundary.
        """
        missing = [parent for parent in self.env_from.values() if parent not in base]
        if missing:
            raise CredentialUnavailable(
                f"{self.credential_id}: source variable(s) not set: "
                f"{', '.join(sorted(missing))}"
            )
        env = dict(base)
        for name in self.env_clear:
            env.pop(name, None)
        for child_var, parent_var in self.env_from.items():
            env[child_var] = base[parent_var]
        return env

    def to_dict(self) -> dict[str, Any]:
        """Provenance, never secrets: ids and variable NAMES only."""
        return {
            "credential_id": self.credential_id,
            "kind": self.kind.value,
            "env_from": {child: parent for child, parent in sorted(self.env_from.items())},
            "env_clear": list(self.env_clear),
        }


@dataclass(frozen=True)
class Rotation:
    """Which credential a launch may use, and why that one."""

    credential: Credential
    # Credentials passed over, with the reason. An operator asking "why is
    # this running on the metered key" must not have to reconstruct it.
    skipped: tuple[tuple[str, str], ...] = ()


class CredentialPool:
    """An ORDERED set of credentials, and the rule for choosing among them.

    Order is declared, not discovered: rotation must land in the same
    place on every process that reads the same configuration, or two
    workers rotate differently and the audit trail stops meaning
    anything.
    """

    def __init__(self, credentials: Sequence[Credential]) -> None:
        if not credentials:
            raise ValueError("a credential pool needs at least one credential")
        seen: set[str] = set()
        for credential in credentials:
            if credential.credential_id in seen:
                raise ValueError(f"duplicate credential id: {credential.credential_id}")
            seen.add(credential.credential_id)
        self.credentials = tuple(credentials)

    @property
    def primary(self) -> Credential:
        """The first declared. Its KIND is the one rotation stays inside."""
        return self.credentials[0]

    def ids(self) -> tuple[str, ...]:
        return tuple(c.credential_id for c in self.credentials)

    def get(self, credential_id: str) -> Credential | None:
        for credential in self.credentials:
            if credential.credential_id == credential_id:
                return credential
        return None

    def source_variables(self) -> frozenset[str]:
        """Every parent variable any credential in this pool reads."""
        return frozenset(
            parent for credential in self.credentials
            for parent in credential.env_from.values()
        )

    def launch_environment(self, credential: Credential,
                           base: Mapping[str, str]) -> dict[str, str]:
        """The child's environment for `credential`, and NOTHING else's.

        `Credential.environment` alone leaves every other credential's
        source variable in place, so a child launched on a subscription
        seat could still read the metered key out of its own environment
        and spend it. The boundary would then be enforced against the
        kernel and not against the agent — which is the only party the
        rule is about. Least privilege (rule 13) means the child sees the
        identity it was given and no other.

        The selected credential's own source variables go too: the child
        needs the value under the name it expects, not the name the
        kernel stores it under.
        """
        stripped = {name: value for name, value in base.items()
                    if name not in self.source_variables()}
        # Bind from the FULL base — the source variables were only removed
        # from what the child sees, not from what the kernel may read.
        bound = credential.environment(base)
        for child_var in credential.env_from:
            stripped[child_var] = bound[child_var]
        for name in credential.env_clear:
            stripped.pop(name, None)
        return stripped

    def select(
        self,
        admits: Callable[[str], bool],
        *,
        authorised_kinds: frozenset[CredentialKind] | None = None,
    ) -> Rotation | None:
        """The first declared credential that may run now, or None.

        Rotation stays inside the primary's KIND unless another kind is
        EXPLICITLY authorised. Deny-by-default (rule 13) applies to
        spending as much as to filesystem access: an exhausted seat is a
        reason to wait, not a reason to start billing.

        None means park — every credential is either held or behind a
        boundary this caller has no authority to cross. A park is not a
        failure (rule 6) and nobody is charged for it (rule 7).
        """
        allowed = {self.primary.kind}
        if authorised_kinds:
            allowed |= set(authorised_kinds)
        skipped: list[tuple[str, str]] = []
        for credential in self.credentials:
            if credential.kind not in allowed:
                reason = (f"kind {credential.kind.value} not authorised "
                          f"(primary is {self.primary.kind.value})")
                skipped.append((credential.credential_id, reason))
                continue
            if not admits(credential.credential_id):
                skipped.append((credential.credential_id, "held"))
                continue
            return Rotation(credential=credential, skipped=tuple(skipped))
        return None
