"""D-535: connection failure reasons follow the shared vector exactly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from core_common.protocol import connect_reason

VECTOR = json.loads((Path(__file__).resolve().parents[3] / "test/fixtures/protocol/connect-reasons.v1.json")
                    .read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", VECTOR["cases"], ids=lambda case: case["id"])
def test_classify_matches_vector(case):
    assert connect_reason.classify(**case["input"]) == case["expect"]


def test_tables_are_the_vector_tables():
    assert [row["code"] for row in VECTOR["reasons"]] == list(connect_reason.REASONS)
    for row in VECTOR["reasons"]:
        assert connect_reason.REASONS[row["code"]] == (row["retry"], row["message"], row["action"])
    assert VECTOR["transport"] == connect_reason.TRANSPORT
    assert VECTOR["robot_codes"] == connect_reason.ROBOT_CODES
    assert VECTOR["http_status"] == {str(k): v for k, v in connect_reason.HTTP_STATUS.items()}
    assert VECTOR["request_states"] == connect_reason.REQUEST_STATES
    assert (VECTOR["http_5xx_fallback"], VECTOR["http_fallback"]) == (
        connect_reason.HTTP_5XX_FALLBACK, connect_reason.HTTP_FALLBACK)


def test_every_mapping_lands_on_a_reason():
    targets = {*connect_reason.TRANSPORT.values(), *connect_reason.ROBOT_CODES.values(),
               *connect_reason.HTTP_STATUS.values(), *connect_reason.REQUEST_STATES.values(),
               connect_reason.HTTP_5XX_FALLBACK, connect_reason.HTTP_FALLBACK}
    assert targets <= set(connect_reason.REASONS)
    assert all(row["retry"] in ("auto", "person") and row["message"] and row["action"] for row in VECTOR["reasons"])


@pytest.mark.parametrize("kwargs", [{}, {"transport": "carrier_pigeon"}, {"request_state": "maybe"}])
def test_classify_rejects_unknown_or_missing_input(kwargs):
    with pytest.raises(ValueError):
        connect_reason.classify(**kwargs)


def test_body_carries_message_action_and_retry():
    error = connect_reason.body("RATE_LIMITED", {"retry_after_s": 3})["error"]
    assert error["code"] == "RATE_LIMITED" and error["message"]
    assert error["detail"] == {"retry_after_s": 3, "action": connect_reason.REASONS["RATE_LIMITED"][2], "retry": "auto"}
