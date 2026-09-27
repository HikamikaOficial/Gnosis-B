import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest
from v1_maintenance_security import (
    MaintenanceSecurityError,
    create_maintenance_directory,
    require_private_maintenance_acl,
    require_safe_ancestor_acl,
)

from gnosis.trust.deployment import AceIdentity, SecurityDescriptorIdentity


def secured():
    return SecurityDescriptorIdentity("S-1-5-32-544", "S-1-5-18", 0x1004, True,
        (AceIdentity(0, 3, 0x1F01FF, "S-1-5-32-544"),
         AceIdentity(0, 3, 0x1F01FF, "S-1-5-18")), None)


def test_private_maintenance_acl_is_accepted():
    require_private_maintenance_acl(secured())


@pytest.mark.parametrize("failure", ["none", "elevation", "collision", "command", "observation"])
def test_directory_creation_requires_fresh_path_and_verified_protection(tmp_path, failure):
    destination = tmp_path / "maintenance"
    if failure == "collision":
        destination.mkdir()
        (destination / "existing").write_text("preserve")
    ops = Mock()
    ops.is_elevated.return_value = failure != "elevation"
    ops.run.return_value = (1 if failure == "command" else 0, "")
    with (patch("v1_maintenance_security.verify_maintenance_ancestors") as ancestors,
          patch("v1_maintenance_security.verify_maintenance_directory") as verify):
        if failure == "observation":
            verify.side_effect = MaintenanceSecurityError("observed ACL refused")
        if failure == "none":
            create_maintenance_directory(destination, ops)
            ancestors.assert_called_once_with(tmp_path)
            verify.assert_called_once_with(destination)
            assert ops.run.call_count == 2
        else:
            with pytest.raises(MaintenanceSecurityError):
                create_maintenance_directory(destination, ops)
            if failure in ("elevation", "collision"):
                ops.run.assert_not_called()
                verify.assert_not_called()
    if failure == "collision":
        assert (destination / "existing").read_text() == "preserve"
    elif failure == "elevation":
        assert not destination.exists()
    else:
        assert destination.is_dir()


@pytest.mark.parametrize("mask", [0x40, 0x10000, 0x40000, 0x80000, 0x10000000, 0x40000000, 0x2])
def test_ancestor_rejects_untrusted_replacement_rights(mask):
    descriptor = secured()
    descriptor = replace(descriptor, aces=(*descriptor.aces, AceIdentity(0, 0, mask, "S-1-5-32-545")))
    with pytest.raises(MaintenanceSecurityError):
        require_safe_ancestor_acl(descriptor)


def test_ancestor_allows_read_and_ignores_inherit_only_permissions():
    descriptor = secured()
    descriptor = replace(descriptor, aces=(*descriptor.aces,
        AceIdentity(0, 0, 0x1200A9, "S-1-5-32-545"),
        AceIdentity(0, 0x0B, 0x10000000, "S-1-3-0")))
    require_safe_ancestor_acl(descriptor)


@pytest.mark.parametrize("change", ["owner", "null", "inheritance", "users", "inherit_only", "missing"])
def test_maintenance_acl_refuses_unqualified_access(change):
    descriptor = secured()
    if change == "owner":
        descriptor = replace(descriptor, owner_sid="S-1-5-21-worker")
    elif change == "null":
        descriptor = replace(descriptor, dacl_present=False)
    elif change == "inheritance":
        descriptor = replace(descriptor, control=4)
    elif change == "users":
        descriptor = replace(descriptor, aces=(*descriptor.aces, AceIdentity(0, 3, 0x1F01FF, "S-1-5-32-545")))
    elif change == "inherit_only":
        descriptor = replace(descriptor, aces=(replace(descriptor.aces[0], ace_flags=11), descriptor.aces[1]))
    else:
        descriptor = replace(descriptor, aces=descriptor.aces[:1])
    with pytest.raises(MaintenanceSecurityError):
        require_private_maintenance_acl(descriptor)
