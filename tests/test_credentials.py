"""Credential identity and the boundary rotation may not cross alone.

The tests that carry this file are the ones about CROSSING: rotation is
an availability mechanism, and the failure mode worth engineering against
is an availability mechanism quietly making a billing decision (rules 25
and 26). The rest — ordering, holds, provenance — is bookkeeping around
that.
"""
import unittest
from typing import ClassVar

from gnosis.kernel.credentials import (
    Credential,
    CredentialKind,
    CredentialPool,
    CredentialUnavailable,
)


def _seat(name="seat-a", **kwargs):
    return Credential(credential_id=name, kind=CredentialKind.SUBSCRIPTION, **kwargs)


def _metered(name="metered-a", **kwargs):
    return Credential(credential_id=name, kind=CredentialKind.METERED, **kwargs)


class TestTheBoundary(unittest.TestCase):
    def test_rotation_never_crosses_into_a_metered_key_by_itself(self):
        # An exhausted seat is a reason to wait, not a reason to start
        # billing. This is the whole reason a credential set is not a
        # pool of interchangeable strings.
        pool = CredentialPool([_seat(), _metered()])
        rotation = pool.select(admits=lambda cid: cid != "seat-a")
        self.assertIsNone(rotation, "rotation started billing on its own")

    def test_crossing_is_possible_but_only_when_authorised(self):
        pool = CredentialPool([_seat(), _metered()])
        rotation = pool.select(
            admits=lambda cid: cid != "seat-a",
            authorised_kinds=frozenset({CredentialKind.METERED}),
        )
        self.assertIsNotNone(rotation)
        self.assertEqual(rotation.credential.credential_id, "metered-a")
        # And it says what it passed over, so an operator asking "why is
        # this on the metered key" does not have to reconstruct it.
        self.assertEqual(rotation.skipped, (("seat-a", "held"),))

    def test_a_refusal_to_cross_is_recorded_as_a_refusal_not_as_absence(self):
        pool = CredentialPool([_seat(), _metered()])
        # Nothing is held; the metered key is simply out of bounds.
        rotation = pool.select(admits=lambda cid: cid != "seat-a")
        self.assertIsNone(rotation)
        # With the seat available it is chosen and the metered key is
        # never even consulted for holds.
        consulted = []

        def admits(cid):
            consulted.append(cid)
            return True

        chosen = pool.select(admits=admits)
        self.assertEqual(chosen.credential.credential_id, "seat-a")
        self.assertEqual(consulted, ["seat-a"])

    def test_rotation_within_one_kind_needs_no_authorisation(self):
        pool = CredentialPool([_seat("seat-a"), _seat("seat-b")])
        rotation = pool.select(admits=lambda cid: cid == "seat-b")
        self.assertEqual(rotation.credential.credential_id, "seat-b")
        self.assertEqual(rotation.skipped, (("seat-a", "held"),))

    def test_everything_held_is_a_park_not_an_error(self):
        pool = CredentialPool([_seat("seat-a"), _seat("seat-b")])
        self.assertIsNone(pool.select(admits=lambda cid: False))


class TestBindingIsRealOrItRaises(unittest.TestCase):
    def test_a_credential_binds_its_variable_from_the_parent(self):
        credential = _seat(env_from={"ANTHROPIC_API_KEY": "GNOSIS_KEY_B"})
        env = credential.environment({"GNOSIS_KEY_B": "s3cret", "PATH": "/usr/bin"})
        self.assertEqual(env["ANTHROPIC_API_KEY"], "s3cret")
        self.assertEqual(env["PATH"], "/usr/bin", "the rest of the environment was lost")

    def test_a_missing_source_variable_refuses_rather_than_inheriting(self):
        # Returning the ambient environment would launch as whatever
        # credential happens to be configured, report success, and bill
        # somebody nobody chose. That is the silent fallback rule 26 names.
        credential = _seat(env_from={"ANTHROPIC_API_KEY": "GNOSIS_KEY_MISSING"})
        with self.assertRaises(CredentialUnavailable) as caught:
            credential.environment({"PATH": "/usr/bin"})
        self.assertIn("GNOSIS_KEY_MISSING", str(caught.exception))

    def test_a_stale_variable_is_cleared_not_left_to_win(self):
        # A subscription launch with a leftover API key in the environment
        # is the same silent fallback in the other direction.
        credential = _seat(env_clear=("ANTHROPIC_API_KEY",))
        env = credential.environment({"ANTHROPIC_API_KEY": "left-over", "PATH": "/x"})
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_provenance_carries_names_and_never_values(self):
        credential = _seat(env_from={"ANTHROPIC_API_KEY": "GNOSIS_KEY_B"})
        payload = repr(credential.to_dict())
        self.assertIn("GNOSIS_KEY_B", payload)      # the NAME is provenance
        self.assertNotIn("s3cret", payload)         # the value is not in the object
        self.assertNotIn("ANTHROPIC_API_KEY=", payload)


class TestTheChildSeesOneIdentity(unittest.TestCase):
    """Binding the chosen credential is not enough: leaving the OTHER
    credentials' source variables in the child's environment enforces the
    boundary against the kernel and not against the agent, which is the
    only party the rule is about."""

    BASE: ClassVar[dict[str, str]] = {
        "PATH": "/usr/bin", "SEAT_A_TOKEN": "aaa", "METERED_TOKEN": "mmm"}

    def _pool(self):
        return CredentialPool([
            _seat("seat-a", env_from={"CLAUDE_TOKEN": "SEAT_A_TOKEN"}),
            _metered("metered", env_from={"ANTHROPIC_API_KEY": "METERED_TOKEN"}),
        ])

    def test_a_seat_launch_cannot_read_the_metered_key_from_its_environment(self):
        pool = self._pool()
        env = pool.launch_environment(pool.get("seat-a"), self.BASE)
        self.assertEqual(env["CLAUDE_TOKEN"], "aaa")
        self.assertNotIn("METERED_TOKEN", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_the_kernels_own_source_variable_is_not_handed_through_either(self):
        # The child needs the value under the name it expects, not the
        # name the kernel stores it under.
        pool = self._pool()
        env = pool.launch_environment(pool.get("seat-a"), self.BASE)
        self.assertNotIn("SEAT_A_TOKEN", env)

    def test_a_missing_source_still_refuses(self):
        pool = CredentialPool([_seat("x", env_from={"K": "ABSENT"})])
        with self.assertRaises(CredentialUnavailable):
            pool.launch_environment(pool.get("x"), self.BASE)


class TestAPoolIsDeclaredNotDiscovered(unittest.TestCase):
    def test_order_is_the_declared_order(self):
        pool = CredentialPool([_seat("b"), _seat("a"), _seat("c")])
        self.assertEqual(pool.ids(), ("b", "a", "c"))
        self.assertEqual(pool.primary.credential_id, "b")

    def test_duplicate_ids_are_refused(self):
        with self.assertRaises(ValueError):
            CredentialPool([_seat("a"), _seat("a")])

    def test_an_empty_pool_is_refused(self):
        with self.assertRaises(ValueError):
            CredentialPool([])

    def test_a_credential_must_declare_a_real_kind(self):
        with self.assertRaises(TypeError):
            Credential(credential_id="x", kind="SUBSCRIPTION")
        with self.assertRaises(ValueError):
            Credential(credential_id="", kind=CredentialKind.LOCAL)


if __name__ == "__main__":
    unittest.main()
