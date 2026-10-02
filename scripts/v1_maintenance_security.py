"""Read-only checks for the private maintenance journal directory."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from gnosis.trust.deployment import (
    SecurityDescriptorIdentity,
    canonical_security_descriptor,
    read_path_security_descriptor,
)

_MAINTENANCE = frozenset({"S-1-5-32-544", "S-1-5-18"})
_FULL_CONTROL = 0x1F01FF
_TRUSTED_INSTALLER = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
_ANCESTOR_OWNERS = _MAINTENANCE | {_TRUSTED_INSTALLER}
# Rights capable of changing/replacing an existing protected descendant or its
# ancestor. Directory creation alone does not replace an already-existing child.
_ANCESTOR_MUTATION = 0x10000000 | 0x40000000 | 0xD0000 | 0x40 | 0x2 | 0x10 | 0x100


class MaintenanceSecurityError(ValueError):
    pass


class MaintenanceOperations(Protocol):
    def is_elevated(self) -> bool: ...
    def run(self, argv: list[str]) -> tuple[int, str]: ...


def create_maintenance_directory(path: Path, ops: MaintenanceOperations) -> None:
    """Create a fresh maintenance directory and verify its explicit ACL.

    Never adopt or rewrite an existing path. Any failed creation/protection is
    left visible for maintenance inspection; no recursive cleanup is attempted.
    """
    path = Path(path)
    if not ops.is_elevated():
        raise MaintenanceSecurityError("maintenance setup requires elevation")
    if not path.is_absolute() or path.exists() or path.is_symlink() or path.is_junction():
        raise MaintenanceSecurityError("maintenance setup requires a fresh absolute path")
    verify_maintenance_ancestors(path.parent)
    path.mkdir(exist_ok=False)
    commands = (
        ["icacls", str(path), "/inheritance:r", "/grant:r",
         "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
        ["icacls", str(path), "/setowner", "*S-1-5-32-544"],
    )
    for command in commands:
        code, _output = ops.run(command)
        if code != 0:
            raise MaintenanceSecurityError("maintenance directory protection failed")
    verify_maintenance_directory(path)


def require_private_maintenance_acl(descriptor: SecurityDescriptorIdentity) -> None:
    """Require an explicit Admins/SYSTEM-only directory, not effective-access guesses.

    The directory is created for maintenance, so broader/custom ACLs are refused
    rather than normalized or weakened. This check never changes permissions.
    """
    if (descriptor.owner_sid not in _MAINTENANCE or not descriptor.dacl_present
            or not descriptor.control & 0x1000):
        raise MaintenanceSecurityError("maintenance directory owner/DACL is not protected")
    allowed = set()
    for ace in descriptor.aces:
        if (ace.ace_type != 0 or ace.sid not in _MAINTENANCE
                or ace.access_mask != _FULL_CONTROL
                or ace.ace_flags != 0x03):
            raise MaintenanceSecurityError("maintenance directory has an unexpected permission")
        allowed.add(ace.sid)
    if allowed != _MAINTENANCE:
        raise MaintenanceSecurityError("maintenance directory lacks required administrative access")


def verify_maintenance_directory(path: Path) -> None:
    path = Path(path)
    if not path.is_absolute() or not path.is_dir() or path.is_symlink() or path.is_junction():
        raise MaintenanceSecurityError("maintenance path must be an existing ordinary absolute directory")
    require_private_maintenance_acl(canonical_security_descriptor(read_path_security_descriptor(path)))
    verify_maintenance_ancestors(path.parent)


def require_safe_ancestor_acl(descriptor: SecurityDescriptorIdentity) -> None:
    """Conservatively reject untrusted mutation rights on an ancestor itself."""
    if descriptor.owner_sid not in _ANCESTOR_OWNERS or not descriptor.dacl_present:
        raise MaintenanceSecurityError("maintenance ancestor has an untrusted owner or DACL")
    for ace in descriptor.aces:
        if ace.ace_flags & 0x08:  # INHERIT_ONLY has no effect on this directory
            continue
        if ace.ace_type not in (0, 1):
            raise MaintenanceSecurityError("maintenance ancestor has unsupported permissions")
        if ace.ace_type == 0 and ace.sid not in _ANCESTOR_OWNERS and ace.access_mask & _ANCESTOR_MUTATION:
            raise MaintenanceSecurityError("maintenance ancestor permits untrusted modification")


def verify_maintenance_ancestors(parent: Path) -> None:
    parent = Path(parent)
    if not parent.is_absolute():
        raise MaintenanceSecurityError("maintenance ancestor must be absolute")
    for item in (parent, *parent.parents):
        if not item.is_dir() or item.is_symlink() or item.is_junction():
            raise MaintenanceSecurityError("maintenance ancestor is missing or linked")
        require_safe_ancestor_acl(canonical_security_descriptor(read_path_security_descriptor(item)))
