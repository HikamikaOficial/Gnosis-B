"""Reject malformed worker envelopes before they enter the governed pipeline."""

import json
from pathlib import Path

import pytest

from gnosis.director import deterministic_worker as worker
from gnosis.director.execution import TrustedExecutionPort, WorkerResultInvalid


def valid_result() -> dict[str, object]:
    return {
        "schema": worker.RESULT_SCHEMA,
        "ok": True,
        "cassette_sha256": "a" * 64,
        "turn_count": 1,
        "final_message": "done",
        "provider_calls": 0,
    }


def read_result(tmp_path: Path, payload: dict[str, object]) -> dict[str, object]:
    path = tmp_path / "result.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return TrustedExecutionPort._read_deterministic_result(path, expected_digest="a" * 64)


@pytest.mark.parametrize("field", tuple(valid_result()))
def test_every_result_field_is_required(tmp_path: Path, field: str) -> None:
    payload = valid_result()
    del payload[field]
    with pytest.raises(WorkerResultInvalid):
        read_result(tmp_path, payload)


@pytest.mark.parametrize("value", [False, True, 0, -1, 1.0, "1", None, worker.MAX_TURNS + 1])
def test_turn_count_is_a_bounded_integer(tmp_path: Path, value: object) -> None:
    payload = valid_result()
    payload["turn_count"] = value
    with pytest.raises(WorkerResultInvalid):
        read_result(tmp_path, payload)


@pytest.mark.parametrize("value", [False, True, 1, -1, 0.0, "0", None])
def test_deterministic_execution_must_report_zero_provider_calls(
    tmp_path: Path, value: object,
) -> None:
    payload = valid_result()
    payload["provider_calls"] = value
    with pytest.raises(WorkerResultInvalid):
        read_result(tmp_path, payload)


@pytest.mark.parametrize("value", [None, [], {}, 123, "\ud800"])
def test_final_message_must_be_utf8_text(tmp_path: Path, value: object) -> None:
    payload = valid_result()
    payload["final_message"] = value
    with pytest.raises(WorkerResultInvalid):
        read_result(tmp_path, payload)


def test_empty_final_message_is_permitted_by_the_cassette_contract(tmp_path: Path) -> None:
    payload = valid_result()
    payload["final_message"] = ""
    assert read_result(tmp_path, payload) == payload


def test_valid_result_is_preserved(tmp_path: Path) -> None:
    payload = valid_result()
    assert read_result(tmp_path, payload) == payload
