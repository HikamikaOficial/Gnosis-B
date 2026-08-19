import unittest

from gnosis.kernel.memory import (
    IllegalMemoryTransitionError,
    MemoryEvidence,
    MemoryQuery,
    MemoryStatus,
    MemoryUnavailable,
    NullMemoryProvider,
    validate_memory_transition,
)
import time

from gnosis.kernel.memory_reference import InMemoryMemoryProvider
from gnosis.kernel.memory_router import MemoryRouter


def _ev(source_kind="human", **kw):
    return MemoryEvidence(source_kind=source_kind, **kw)


class TestMemoryStatusTransitions(unittest.TestCase):
    def test_legal_lifecycle_path(self):
        self.assertEqual(
            validate_memory_transition(MemoryStatus.OBSERVED, MemoryStatus.CANDIDATE),
            MemoryStatus.CANDIDATE,
        )
        validate_memory_transition(MemoryStatus.CANDIDATE, MemoryStatus.QUARANTINED)
        validate_memory_transition(MemoryStatus.QUARANTINED, MemoryStatus.ACTIVE)
        validate_memory_transition(MemoryStatus.ACTIVE, MemoryStatus.SUPERSEDED)

    def test_trusted_source_can_skip_quarantine(self):
        validate_memory_transition(MemoryStatus.CANDIDATE, MemoryStatus.ACTIVE)

    def test_illegal_transition_raises(self):
        with self.assertRaises(IllegalMemoryTransitionError):
            validate_memory_transition(MemoryStatus.OBSERVED, MemoryStatus.ACTIVE)
        with self.assertRaises(IllegalMemoryTransitionError):
            validate_memory_transition(MemoryStatus.REVOKED, MemoryStatus.ACTIVE)

    def test_terminal_states_have_no_exits(self):
        for terminal in (MemoryStatus.SUPERSEDED, MemoryStatus.REVOKED):
            with self.assertRaises(IllegalMemoryTransitionError):
                validate_memory_transition(terminal, MemoryStatus.ACTIVE)


class TestNullMemoryProvider(unittest.TestCase):
    def test_every_operation_raises_unavailable(self):
        provider = NullMemoryProvider()
        ev = _ev()
        with self.assertRaises(MemoryUnavailable):
            provider.remember("x", "fact", ev)
        with self.assertRaises(MemoryUnavailable):
            provider.query(MemoryQuery(text="x"))
        with self.assertRaises(MemoryUnavailable):
            provider.why("act-1")


class TestTemporalTruth(unittest.TestCase):
    """Director scenario: T1 'Storage backend is SQLite', T2 'migrated to
    PostgreSQL'. Query at T1 must return SQLite; current query must
    return PostgreSQL; the old fact must not simply disappear."""

    def test_query_at_t1_vs_current_after_supersession(self):
        provider = InMemoryMemoryProvider()
        t1 = provider.remember("Storage backend is SQLite.", "fact", _ev(), labels=("storage-backend",))
        t1_timestamp = t1.updated_at
        time.sleep(0.01)
        t2 = provider.supersede(t1.memory_id, "Storage backend migrated to PostgreSQL.", _ev())

        current = provider.query(MemoryQuery(text="storage backend"))
        self.assertEqual(len(current.records), 1)
        self.assertEqual(current.records[0].memory_id, t2.memory_id)
        self.assertIn("PostgreSQL", current.records[0].content)

        past = provider.query(MemoryQuery(text="storage backend", as_of=t1_timestamp))
        self.assertEqual(len(past.records), 1)
        self.assertEqual(past.records[0].memory_id, t1.memory_id)
        self.assertIn("SQLite", past.records[0].content)

    def test_old_fact_not_deleted_still_reachable_with_include_superseded(self):
        provider = InMemoryMemoryProvider()
        t1 = provider.remember("Storage backend is SQLite.", "fact", _ev(), labels=("storage-backend",))
        provider.supersede(t1.memory_id, "Storage backend migrated to PostgreSQL.", _ev())

        with_history = provider.query(MemoryQuery(text="storage backend", include_superseded=True))
        ids = {r.memory_id for r in with_history.records}
        self.assertIn(t1.memory_id, ids)
        stored_t1 = next(r for r in with_history.records if r.memory_id == t1.memory_id)
        self.assertEqual(stored_t1.status, MemoryStatus.SUPERSEDED)


class TestContradictions(unittest.TestCase):
    """Director scenario: conflicting claims from different sources must
    not be silently collapsed into a fabricated single truth."""

    def test_two_active_contradictory_memories_both_surface_not_merged(self):
        provider = InMemoryMemoryProvider()
        provider.remember("The build system is Bazel.", "fact", _ev(source_kind="tool", source_uri="ci-log-1"))
        provider.remember("The build system is Make.", "fact", _ev(source_kind="tool", source_uri="ci-log-2"))

        result = provider.query(MemoryQuery(text="build system"))
        contents = {r.content for r in result.records}
        # Both surface, unresolved -- the system does not invent a merged
        # "the build system is Bazel and Make" answer, nor silently pick one.
        self.assertEqual(contents, {"The build system is Bazel.", "The build system is Make."})

    def test_proposed_contradictions_stay_quarantined_not_treated_as_truth(self):
        provider = InMemoryMemoryProvider()
        record = provider.propose("Unverified: the build system is Bazel.", "fact", _ev(source_kind="agent"))
        self.assertEqual(record.status, MemoryStatus.QUARANTINED)
        result = provider.query(MemoryQuery(text="build system"))
        self.assertEqual(result.records, ())  # quarantined content never presented as active truth


class TestSupersessionHistory(unittest.TestCase):
    def test_history_preserves_both_transitions_current_state_unambiguous(self):
        provider = InMemoryMemoryProvider()
        t1 = provider.remember("Decision: use REST.", "decision", _ev())
        t2 = provider.supersede(t1.memory_id, "Decision: use gRPC.", _ev())

        t1_history = provider.history(t1.memory_id)
        self.assertEqual([h.new_status for h in t1_history], [
            MemoryStatus.CANDIDATE, MemoryStatus.ACTIVE, MemoryStatus.SUPERSEDED,
        ])
        current = provider.query(MemoryQuery(text="use"))
        self.assertEqual(len(current.records), 1)
        self.assertEqual(current.records[0].memory_id, t2.memory_id)


class TestProvenance(unittest.TestCase):
    def test_every_memory_traceable_to_its_source(self):
        provider = InMemoryMemoryProvider()
        record = provider.remember(
            "ADR-004: switch to event sourcing.", "decision",
            _ev(source_kind="document", source_uri="docs/adr/ADR-004.md", actor_uri="director://chatgpt"),
        )
        self.assertEqual(record.evidence.source_kind, "document")
        self.assertEqual(record.evidence.source_uri, "docs/adr/ADR-004.md")
        self.assertEqual(record.evidence.actor_uri, "director://chatgpt")


class TestRevocation(unittest.TestCase):
    """Director scenario: inject a false memory, let it influence a
    controlled action, revoke it, determine whether downstream influence
    can be identified."""

    def test_revoked_memory_excluded_from_future_influence_but_traceable_in_past(self):
        provider = InMemoryMemoryProvider()
        false_memory = provider.remember("The API rate limit is 1000 req/s.", "fact", _ev(source_kind="tool"))

        influence_before = provider.inject("act-1", "What is the API rate limit?", agent="test-agent")
        self.assertIn(false_memory.memory_id, influence_before.memory_ids)

        provider.revoke(false_memory.memory_id, "Number was fabricated by a misconfigured tool.")

        influence_after = provider.inject("act-2", "What is the API rate limit?", agent="test-agent")
        self.assertNotIn(false_memory.memory_id, influence_after.memory_ids)

        # Downstream influence on the ORIGINAL action remains identifiable.
        past_influence = provider.why("act-1")
        self.assertIn(false_memory.memory_id, past_influence.memory_ids)
        current_status = provider.history(false_memory.memory_id)[-1].new_status
        self.assertEqual(current_status, MemoryStatus.REVOKED)


class TestProceduralMemory(unittest.TestCase):
    """Director scenario: repeated engineering runs with a common failure
    and eventual successful remediation should be retrievable in a later
    analogous task. The contract supports the 'procedure' memory_type
    generically; extraction-quality judgment is out of scope for a
    deterministic unit test (see M3 benchmark report)."""

    def test_procedure_memory_type_flows_through_normal_lifecycle(self):
        provider = InMemoryMemoryProvider()
        procedure = provider.remember(
            "When 'port already in use' occurs on :8080, run `lsof -ti:8080 | xargs kill` before retrying.",
            "procedure", _ev(source_kind="system", source_uri="run:RUN-042"),
        )
        self.assertEqual(procedure.status, MemoryStatus.ACTIVE)
        found = provider.query(MemoryQuery(text="port already in use"))
        self.assertEqual(len(found.records), 1)
        self.assertEqual(found.records[0].memory_type, "procedure")


class TestNoiseResistance(unittest.TestCase):
    def test_targeted_query_finds_signal_among_noise(self):
        provider = InMemoryMemoryProvider()
        for i in range(50):
            provider.remember(f"Irrelevant noise memory number {i}.", "fact", _ev())
        provider.remember("The deploy target is us-east-1.", "fact", _ev(), labels=("deploy-target",))

        result = provider.query(MemoryQuery(text="deploy target"))
        self.assertEqual(len(result.records), 1)
        self.assertIn("us-east-1", result.records[0].content)

    def test_limit_bounds_result_count_even_with_many_matches(self):
        provider = InMemoryMemoryProvider()
        for i in range(20):
            provider.remember(f"Fact about widgets number {i}.", "fact", _ev())
        result = provider.query(MemoryQuery(text="widgets", limit=5))
        self.assertEqual(len(result.records), 5)


class TestStaleKnowledge(unittest.TestCase):
    def test_newer_active_decision_outranks_old_superseded_one(self):
        provider = InMemoryMemoryProvider()
        old = provider.remember("Architecture: monolith.", "decision", _ev(), labels=("architecture",))
        new = provider.supersede(old.memory_id, "Architecture: microservices.", _ev())

        result = provider.query(MemoryQuery(text="architecture"))
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.records[0].memory_id, new.memory_id)
        self.assertNotIn("monolith", result.records[0].content)


class TestMemoryRouter(unittest.TestCase):
    def test_gathers_from_multiple_roles_bounded(self):
        factual = InMemoryMemoryProvider()
        factual.remember("Storage backend is PostgreSQL.", "fact", _ev())
        governance = InMemoryMemoryProvider()
        governance.remember("Policy: no direct prod writes.", "policy", _ev())

        router = MemoryRouter({"factual_temporal": factual, "governance": governance})
        result = router.gather_context("storage backend policy", roles=["factual_temporal", "governance"])

        self.assertIn("factual_temporal", result.results_by_role)
        self.assertIn("governance", result.results_by_role)
        self.assertEqual(result.failures_by_role, {})

    def test_unregistered_role_recorded_as_failure_not_a_crash(self):
        router = MemoryRouter({"governance": InMemoryMemoryProvider()})
        result = router.gather_context("anything", roles=["governance", "procedural"])
        self.assertIn("procedural", result.failures_by_role)
        self.assertNotIn("procedural", result.results_by_role)

    def test_provider_unavailable_does_not_block_other_roles(self):
        router = MemoryRouter({"governance": NullMemoryProvider(), "factual_temporal": InMemoryMemoryProvider()})
        InMemoryMemoryProvider_instance = router.providers["factual_temporal"]
        InMemoryMemoryProvider_instance.remember("A fact.", "fact", _ev())

        result = router.gather_context("fact", roles=["governance", "factual_temporal"])
        self.assertIn("governance", result.failures_by_role)
        self.assertIn("factual_temporal", result.results_by_role)

    def test_total_records_budget_caps_across_roles(self):
        a = InMemoryMemoryProvider()
        b = InMemoryMemoryProvider()
        for i in range(5):
            a.remember(f"Fact A{i} about topic.", "fact", _ev())
            b.remember(f"Fact B{i} about topic.", "fact", _ev())

        router = MemoryRouter({"a": a, "b": b})
        result = router.gather_context("topic", roles=["a", "b"], max_records_per_role=5, max_total_records=4)
        self.assertLessEqual(result.total_records_included, 4)


if __name__ == "__main__":
    unittest.main()
