import tempfile
import unittest
from pathlib import Path

from gnosis.kernel.ledger import RunLedger
from gnosis.kernel.replay import (
    CallSpec,
    IntentJournal,
    IntentStatus,
    InteractionStore,
    ReplayError,
    ReplayMiss,
    ReplayMode,
    SideEffect,
    golden_fixture,
)


class _LiveCounter:
    """Stands in for a model/tool: counts real invocations so a test can
    prove replay never reached it."""

    def __init__(self, responses=None):
        self.calls = 0
        self._responses = list(responses or [])

    def __call__(self):
        self.calls += 1
        if self._responses:
            return self._responses[min(self.calls, len(self._responses)) - 1]
        return f"live-response-{self.calls}"


def _spec(prompt: str = "hello", model: str = "fable-5", **extra) -> CallSpec:
    params = {"model": model, "prompt": prompt, "temperature": 0.0}
    params.update(extra)
    return CallSpec(tool="llm.complete", params=params)


class TestCallSpecKeying(unittest.TestCase):
    def test_key_is_stable_and_order_independent(self):
        a = CallSpec(tool="t", params={"b": 1, "a": {"d": 2, "c": 3}})
        b = CallSpec(tool="t", params={"a": {"c": 3, "d": 2}, "b": 1})
        self.assertEqual(a.key(), b.key())

    def test_response_determining_params_change_the_key(self):
        base = _spec()
        for changed in (_spec(prompt="other"), _spec(model="opus-5"),
                        _spec(max_tokens=100)):
            self.assertNotEqual(base.key(), changed.key())

    def test_metadata_is_recorded_but_never_keyed(self):
        # Folding a timestamp into the key would make every replay a miss.
        a = CallSpec(tool="t", params={"p": 1}, metadata={"ts": "2026-01-01"})
        b = CallSpec(tool="t", params={"p": 1}, metadata={"ts": "2026-12-31"})
        self.assertEqual(a.key(), b.key())

    def test_tool_name_is_part_of_the_key(self):
        self.assertNotEqual(
            CallSpec(tool="a", params={"p": 1}).key(),
            CallSpec(tool="b", params={"p": 1}).key(),
        )


class TestInteractionStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "cassette.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _store(self, mode=ReplayMode.RECORD) -> InteractionStore:
        return InteractionStore(self.path, mode=mode)

    def test_record_then_replay_returns_recorded_response_without_live_call(self):
        live = _LiveCounter()
        recorded = self._store().call(_spec(), live)
        self.assertEqual(live.calls, 1)

        replay_live = _LiveCounter()
        replayed = self._store(ReplayMode.REPLAY).call(_spec(), replay_live)
        self.assertEqual(replayed, recorded)
        self.assertEqual(replay_live.calls, 0)  # never reached the model

    def test_replay_is_occurrence_aware_preserving_order_and_multiplicity(self):
        record_store = self._store()
        live = _LiveCounter()
        first = record_store.call(_spec(), live)
        second = record_store.call(_spec(), live)
        third = record_store.call(_spec(), live)
        self.assertEqual(len({first, second, third}), 3)  # distinct responses

        replay = self._store(ReplayMode.REPLAY)
        dead = _LiveCounter()
        self.assertEqual(replay.call(_spec(), dead), first)
        self.assertEqual(replay.call(_spec(), dead), second)
        self.assertEqual(replay.call(_spec(), dead), third)
        self.assertEqual(dead.calls, 0)

    def test_strict_replay_miss_aborts_and_never_calls_live(self):
        self._store().call(_spec(), _LiveCounter())
        replay = self._store(ReplayMode.REPLAY)
        dead = _LiveCounter()
        replay.call(_spec(), dead)  # occurrence 0 hits
        with self.assertRaises(ReplayMiss) as ctx:
            replay.call(_spec(), dead)  # occurrence 1 was never recorded
        self.assertEqual(dead.calls, 0)
        self.assertEqual(ctx.exception.occurrence, 1)
        self.assertEqual(ctx.exception.recorded, 1)

    def test_strict_replay_miss_on_unknown_key_aborts(self):
        self._store().call(_spec(prompt="known"), _LiveCounter())
        replay = self._store(ReplayMode.REPLAY)
        dead = _LiveCounter()
        with self.assertRaises(ReplayMiss):
            replay.call(_spec(prompt="unknown"), dead)
        self.assertEqual(dead.calls, 0)

    def test_fall_through_is_an_explicit_opt_in(self):
        self._store().call(_spec(prompt="known"), _LiveCounter())
        hybrid = self._store(ReplayMode.REPLAY_OR_RECORD)
        live = _LiveCounter()
        hybrid.call(_spec(prompt="known"), live)
        self.assertEqual(live.calls, 0)  # replayed
        hybrid.call(_spec(prompt="new"), live)
        self.assertEqual(live.calls, 1)  # fell through and recorded
        # ...and the new interaction is now part of the cassette.
        self.assertEqual(len(self._store(ReplayMode.REPLAY).records()), 2)

    def test_different_keys_have_independent_cursors(self):
        record = self._store()
        live = _LiveCounter()
        a1 = record.call(_spec(prompt="a"), live)
        b1 = record.call(_spec(prompt="b"), live)
        a2 = record.call(_spec(prompt="a"), live)

        replay = self._store(ReplayMode.REPLAY)
        dead = _LiveCounter()
        self.assertEqual(replay.call(_spec(prompt="a"), dead), a1)
        self.assertEqual(replay.call(_spec(prompt="b"), dead), b1)
        self.assertEqual(replay.call(_spec(prompt="a"), dead), a2)

    def test_fresh_instance_replays_from_the_beginning(self):
        # Replay is a property of the run, not of the process.
        self._store().call(_spec(), _LiveCounter())
        first = self._store(ReplayMode.REPLAY).call(_spec(), _LiveCounter())
        second = self._store(ReplayMode.REPLAY).call(_spec(), _LiveCounter())
        self.assertEqual(first, second)

    def test_unused_records_expose_fixture_drift(self):
        record = self._store()
        live = _LiveCounter()
        record.call(_spec(prompt="a"), live)
        record.call(_spec(prompt="b"), live)

        replay = self._store(ReplayMode.REPLAY)
        replay.call(_spec(prompt="a"), _LiveCounter())
        unused = replay.unused()
        self.assertEqual([r.params["prompt"] for r in unused], ["b"])

    def test_record_and_replay_observe_identical_values(self):
        # Determinism means the RECORDING run and the REPLAYING run see the
        # same value. Returning the live object would hand the recorder a
        # tuple where the replayer later gets a list.
        recorded = self._store().call(_spec(), lambda: ("a", "b"))
        replayed = self._store(ReplayMode.REPLAY).call(_spec(), _LiveCounter())
        self.assertEqual(recorded, replayed)
        self.assertIs(type(recorded), type(replayed))

    def test_nested_structures_round_trip_identically(self):
        payload = {"choices": [{"text": "hi", "score": 0.5}], "usage": {"in": 1}}
        recorded = self._store().call(_spec(), lambda: payload)
        replayed = self._store(ReplayMode.REPLAY).call(_spec(), _LiveCounter())
        self.assertEqual(recorded, replayed)
        self.assertEqual(replayed, payload)

    def test_unrecordable_response_fails_loudly(self):
        # A response that cannot be recorded cannot be replayed; recording
        # nothing would silently mis-align every later occurrence.
        store = self._store()
        with self.assertRaises(ReplayError):
            store.call(_spec(), lambda: object())
        with self.assertRaises(ReplayError):
            store.call(_spec(), lambda: float("nan"))

    def test_unrecordable_call_is_still_recorded_and_fails_closed_on_replay(self):
        # The live call HAPPENED: dropping its row would shift every later
        # occurrence and hide it from the audit trail (Codex review).
        store = self._store()
        with self.assertRaises(ReplayError):
            store.call(_spec(), lambda: object())
        rows = self._store(ReplayMode.REPLAY).records()
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0].unrecordable)
        # Replaying it fails closed rather than returning an invented value.
        with self.assertRaises(ReplayError):
            self._store(ReplayMode.REPLAY).call(_spec(), _LiveCounter())

    def test_concurrent_recorders_do_not_collide_on_occurrences(self):
        # Occurrence allocation happens under the file lock, from what is
        # on disk — two recorders sharing a cassette otherwise both write
        # occurrence 0 and corrupt every later replay (Codex review).
        import threading

        errors: list[Exception] = []

        def record(n: int) -> None:
            try:
                InteractionStore(self.path, ReplayMode.RECORD).call(
                    _spec(), lambda: f"resp-{n}",
                )
            except Exception as exc:  # noqa: BLE001 - surfaced below
                errors.append(exc)  # pragma: no cover

        threads = [threading.Thread(target=record, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(errors, [])
        occurrences = sorted(r.occurrence for r in self._store(ReplayMode.REPLAY).records())
        self.assertEqual(occurrences, list(range(8)))  # no duplicates, no gaps

    def test_interior_corruption_costs_only_the_damaged_row(self):
        # Contract corrected (independent review): raising here bricked
        # the WHOLE cassette — every intact, fsync'd row lost — and a torn
        # tail does not stay the last line for long, so one more append
        # turned a survivable crash into a total loss. Skipping the row
        # opens no permissive path: the call it recorded now MISSES, which
        # strict replay already treats as an abort, so garbage is still
        # never replayed.
        store = self._store()
        store.call(_spec(prompt="a"), _LiveCounter())
        second = store.call(_spec(prompt="b"), _LiveCounter())
        lines = self.path.read_text(encoding="utf-8").splitlines()
        lines[0] = "{not json"
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        recovered = self._store(ReplayMode.REPLAY)
        self.assertEqual([line for line, _ in recovered.damaged], [1])
        # The intact row still replays...
        self.assertEqual(recovered.call(_spec(prompt="b"), _LiveCounter()), second)
        # ...and the damaged one aborts rather than returning anything.
        with self.assertRaises(ReplayMiss):
            recovered.call(_spec(prompt="a"), _LiveCounter())

    def test_a_row_lost_from_the_middle_of_a_key_is_still_fatal(self):
        # Contiguity is what keeps the lenient load honest: losing one
        # occurrence of a repeated call would otherwise silently shift
        # every later one.
        store = self._store()
        store.call(_spec(prompt="a"), _LiveCounter())
        store.call(_spec(prompt="a"), _LiveCounter())
        store.call(_spec(prompt="a"), _LiveCounter())
        lines = self.path.read_text(encoding="utf-8").splitlines()
        lines[1] = "{not json"
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(ReplayError):
            self._store(ReplayMode.REPLAY)

    def test_torn_final_line_does_not_brick_the_cassette(self):
        # A process killed mid-append must not cost the whole recorded run
        # (RunLedger tolerates its own torn tail; so does the cassette).
        store = self._store()
        first = store.call(_spec(prompt="a"), _LiveCounter())
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write('{"key": "abc", "tool": "t", "occ')  # cut off
        recovered = self._store(ReplayMode.REPLAY)
        self.assertEqual(len(recovered.records()), 1)
        self.assertEqual(recovered.call(_spec(prompt="a"), _LiveCounter()), first)

    def test_gapped_or_duplicated_occurrences_are_refused(self):
        # Serving records positionally over gapped labels would replay a
        # DIFFERENT call's response instead of aborting.
        import json as _json
        spec = _spec()
        rows = [
            {"key": spec.key(), "tool": "t", "occurrence": 0,
             "params": spec.params, "response": "ZERO", "metadata": {}},
            {"key": spec.key(), "tool": "t", "occurrence": 5,
             "params": spec.params, "response": "FIVE", "metadata": {}},
        ]
        self.path.write_text(
            "\n".join(_json.dumps(r) for r in rows) + "\n", encoding="utf-8",
        )
        with self.assertRaises(ReplayError):
            self._store(ReplayMode.REPLAY)

    def test_string_mode_cannot_downgrade_strict_replay_to_a_live_call(self):
        # ReplayMode subclasses str: an `in` test matched a bare "REPLAY"
        # while the `is` abort guard did not, so a miss fell through to the
        # model. The mode is coerced at construction now.
        self._store().call(_spec(), _LiveCounter())
        store = InteractionStore(self.path, "REPLAY")  # plain string
        self.assertIs(store.mode, ReplayMode.REPLAY)
        live = _LiveCounter()
        store.call(_spec(), live)  # occurrence 0 hits
        with self.assertRaises(ReplayMiss):
            store.call(_spec(), live)  # occurrence 1 must ABORT
        self.assertEqual(live.calls, 0)

    def test_unencodable_metadata_never_costs_the_row(self):
        import datetime
        spec = CallSpec(tool="llm.complete", params={"p": 1},
                        metadata={"ts": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)})
        self._store().call(spec, lambda: "happened")
        rows = self._store(ReplayMode.REPLAY).records()
        self.assertEqual(len(rows), 1)  # the call that happened is recorded
        self.assertIn("_unencodable_metadata", rows[0].metadata)
        # ...and it still replays its response.
        self.assertEqual(
            self._store(ReplayMode.REPLAY).call(spec, _LiveCounter()), "happened",
        )

    def test_metadata_is_actually_recorded(self):
        spec = CallSpec(tool="llm.complete", params={"p": 1},
                        metadata={"request_id": "req-7"})
        self._store().call(spec, lambda: "ok")
        rows = self._store(ReplayMode.REPLAY).records()
        self.assertEqual(rows[0].metadata, {"request_id": "req-7"})

    def test_records_are_in_true_call_order(self):
        store = self._store()
        live = _LiveCounter()
        for prompt in ("z", "a", "z", "m"):
            store.call(_spec(prompt=prompt), live)
        self.assertEqual([r.params["prompt"] for r in store.records()],
                         ["z", "a", "z", "m"])

    def test_golden_fixture_round_trips_through_a_real_replay(self):
        # "Golden runs become regression fixtures" needs an IMPORT path,
        # not just an exporter.
        from gnosis.kernel.replay import load_golden_fixture, write_golden_fixture

        record = self._store()
        live = _LiveCounter()
        first = record.call(_spec(prompt="a"), live)
        second = record.call(_spec(prompt="b"), live)

        fixture_path = self.path.parent / "golden.jsonl"
        write_golden_fixture(record, fixture_path)

        replay = load_golden_fixture(fixture_path)
        self.assertIs(replay.mode, ReplayMode.REPLAY)
        dead = _LiveCounter()
        self.assertEqual(replay.call(_spec(prompt="a"), dead), first)
        self.assertEqual(replay.call(_spec(prompt="b"), dead), second)
        self.assertEqual(dead.calls, 0)
        # Drift from the golden run aborts instead of going live.
        with self.assertRaises(ReplayMiss):
            replay.call(_spec(prompt="c"), dead)

    def test_golden_fixture_export_preserves_occurrences(self):
        record = self._store()
        live = _LiveCounter()
        record.call(_spec(prompt="a"), live)
        record.call(_spec(prompt="a"), live)
        rows = list(golden_fixture(record))
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["occurrence"] for r in rows], [0, 1])
        self.assertIn("response", rows[0])


class TestIntentJournal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = RunLedger(Path(self.tmp.name) / "ledger.jsonl")
        self.journal = IntentJournal(self.ledger, run_id="RUN-1")

    def tearDown(self):
        self.tmp.cleanup()

    def test_intent_is_durable_before_the_side_effect_runs(self):
        observed: list[str] = []

        def side_effect() -> None:
            # At this point the declaration must already be on disk.
            events = [e.event_type for e in self.ledger.read_all()]
            observed.append(events[-1])

        with self.journal.intent("git.push", SideEffect(side_effect=True)) as handle:
            side_effect()
            handle.complete({"pushed": True})

        self.assertEqual(observed, ["intent.declared"])
        record = self.journal.records()[0]
        self.assertEqual(record.status, IntentStatus.COMPLETED)
        self.assertEqual(record.outcome, {"pushed": True})

    def test_exception_marks_failed_and_propagates(self):
        with (
            self.assertRaises(RuntimeError),
            self.journal.intent("api.charge", SideEffect(side_effect=True)),
        ):
            raise RuntimeError("boom")
        record = self.journal.records()[0]
        self.assertEqual(record.status, IntentStatus.FAILED)
        self.assertIn("boom", record.outcome["error"])

    def test_crash_between_intent_and_outcome_stays_unresolved(self):
        # Simulate a process death: the handle is never resolved and the
        # context manager never exits.
        self.journal.intent("git.push", SideEffect(side_effect=True))
        fresh = IntentJournal(self.ledger, run_id="RUN-1")
        unresolved = fresh.unresolved()
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0].status, IntentStatus.DECLARED)
        self.assertTrue(unresolved[0].unresolved)

    def test_body_that_never_claims_an_outcome_is_not_invented_as_success(self):
        with self.journal.intent("git.push", SideEffect(side_effect=True)):
            pass  # forgot to call complete()
        record = self.journal.records()[0]
        self.assertEqual(record.status, IntentStatus.DECLARED)
        self.assertEqual(len(self.journal.unresolved()), 1)

    def test_rewind_safety_is_a_query_not_a_guess(self):
        with self.journal.intent("fs.write", SideEffect(side_effect=True, idempotent=True)) as h:
            h.complete()
        with self.journal.intent("git.commit", SideEffect(side_effect=True, has_revert=True)) as h:
            h.complete()
        with self.journal.intent("cache.read", SideEffect(side_effect=False)) as h:
            h.complete()
        self.assertTrue(self.journal.can_rewind())

        with self.journal.intent("email.send", SideEffect(side_effect=True)) as h:
            h.complete({"sent": True})
        self.assertFalse(self.journal.can_rewind())
        blockers = self.journal.rewind_blockers()
        self.assertEqual([b.tool for b in blockers], ["email.send"])

    def test_unresolved_intent_blocks_rewind_even_if_flagged_safe(self):
        # An unknown outcome cannot be declared safe.
        self.journal.intent("fs.write", SideEffect(side_effect=True, idempotent=True))
        self.assertFalse(self.journal.can_rewind())
        self.assertEqual(len(self.journal.rewind_blockers()), 1)

    def test_idempotency_key_round_trips(self):
        effect = SideEffect(side_effect=True, idempotent=True, idempotency_key="ORDER-42")
        with self.journal.intent("api.charge", effect, {"amount": 10}) as h:
            h.complete()
        record = self.journal.records()[0]
        self.assertEqual(record.effect.idempotency_key, "ORDER-42")
        self.assertEqual(record.params, {"amount": 10})

    def test_double_resolution_is_refused(self):
        with self.journal.intent("git.push", SideEffect(side_effect=True)) as handle:
            handle.complete()
            with self.assertRaises(ReplayError):
                handle.complete()
            with self.assertRaises(ReplayError):
                handle.fail()

    def test_journal_is_hash_chained_and_tamper_evident(self):
        with self.journal.intent("git.push", SideEffect(side_effect=True)) as h:
            h.complete()
        self.ledger.verify_chain()  # intact

        lines = self.ledger.path.read_text(encoding="utf-8").splitlines()
        lines[0] = lines[0].replace('"git.push"', '"git.push-tampered"')
        self.ledger.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        from gnosis.kernel.ledger import LedgerCorruptionError
        with self.assertRaises(LedgerCorruptionError):
            self.ledger.verify_chain()

    def test_resumed_journal_never_reuses_intent_ids(self):
        # The crash-resume case: a second journal over the SAME ledger used
        # to mint the same id, letting its completion mark the earlier,
        # still-unresolved DANGEROUS intent as done (Codex review, critical).
        self.journal.intent("email.send", SideEffect(side_effect=True))  # crashed
        resumed = IntentJournal(self.ledger, run_id="RUN-1")
        with resumed.intent("email.send", SideEffect(side_effect=True)) as h:
            h.complete({"sent": True})

        records = resumed.records()
        self.assertEqual(len(records), 2)
        self.assertEqual(len({r.intent_id for r in records}), 2)  # distinct ids
        statuses = sorted(r.status.value for r in records)
        self.assertEqual(statuses, ["COMPLETED", "DECLARED"])
        # The dangerous unresolved intent was NOT erased by the resume.
        self.assertEqual(len(resumed.unresolved()), 1)
        self.assertFalse(resumed.can_rewind())

    def test_records_are_scoped_to_this_run(self):
        # One ledger can carry several runs' events; a sibling run's
        # intents must not appear in this run's safety answer.
        other = IntentJournal(self.ledger, run_id="RUN-2")
        other.intent("email.send", SideEffect(side_effect=True))  # unresolved
        with self.journal.intent("fs.write", SideEffect(side_effect=False)) as h:
            h.complete()
        self.assertEqual([r.tool for r in self.journal.records()], ["fs.write"])
        self.assertTrue(self.journal.can_rewind())
        self.assertFalse(other.can_rewind())

    def test_safety_queries_refuse_a_tampered_journal(self):
        # A rewind-safety answer read from an unverified chain is worthless
        # (Codex review): destroying work on it would be unforgivable.
        from gnosis.kernel.ledger import LedgerCorruptionError
        with self.journal.intent("email.send", SideEffect(side_effect=True)) as h:
            h.complete()
        lines = self.ledger.path.read_text(encoding="utf-8").splitlines()
        lines[0] = lines[0].replace('"side_effect": true', '"side_effect": false')
        self.ledger.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(LedgerCorruptionError):
            self.journal.can_rewind()
        with self.assertRaises(LedgerCorruptionError):
            self.journal.rewind_blockers()

    def test_records_preserve_declaration_order(self):
        for i in range(3):
            with self.journal.intent(f"tool.{i}", SideEffect(side_effect=False)) as h:
                h.complete()
        self.assertEqual([r.tool for r in self.journal.records()],
                         ["tool.0", "tool.1", "tool.2"])


if __name__ == "__main__":
    unittest.main()
