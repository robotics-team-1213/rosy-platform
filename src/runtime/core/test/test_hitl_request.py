"""ROS-free validation of the robot HITL request envelope."""

import pytest

from core.bridge.hitl import HitlRequest, parse_hitl_request


def test_parse_hitl_request_accepts_a_bounded_confidence():
    parsed = parse_hitl_request(
        '{"requested":true,"module":"navigation","confidence":0.42}'
    )

    assert parsed == HitlRequest(requested=True, module="navigation", confidence=0.42)


@pytest.mark.parametrize("payload", [
    "not-json",
    "{}",
    '{"requested":"yes","module":"navigation","confidence":0.5}',
    '{"requested":true,"module":"","confidence":0.5}',
    '{"requested":true,"module":"navigation","confidence":-0.1}',
    '{"requested":true,"module":"navigation","confidence":1.1}',
])
def test_parse_hitl_request_rejects_ambiguous_or_unbounded_payloads(payload):
    with pytest.raises(ValueError):
        parse_hitl_request(payload)
