"""D-523: AI PC replies parse to facts or allowlisted candidates, never commands."""

from datetime import datetime, timedelta, timezone

import pytest

from fleet.ai.decision_pipeline import (
    COMMAND_WORDS,
    ChoiceCandidate,
    IdentityFact,
    parse_choice,
    parse_identity,
)

OPENED = datetime(2026, 10, 8, 1, 0, tzinfo=timezone.utc)
NOW = OPENED + timedelta(seconds=2)
CAPTURED = OPENED + timedelta(seconds=1)


def _identity(**overrides):
    fields = {
        "cause": "obstacle_ahead",
        "front_clearance_m": 0.24,
        "opened_at": OPENED,
        "captured_at": CAPTURED,
        "profile_id": "identity-a",
        "expected_profile_id": "identity-a",
        "payload": {"thing": "person", "confidence": 0.91},
        "now": NOW,
    }
    fields.update(overrides)
    return parse_identity(**fields)


def _choice(**overrides):
    fields = {
        "profile_id": "choice-a",
        "expected_profile_id": "choice-a",
        "generation": "stuck-9",
        "expected_generation": "stuck-9",
        "criteria": {"hold_west": "wait in the west spur", "ask_human": "ask a person"},
        "response": {"answers": {"decision": {"choice": "hold_west"}}},
        "elapsed_s": 0.4,
    }
    fields.update(overrides)
    return parse_choice(**fields)


@pytest.mark.parametrize("thing", ["wall", "object", "robot", "person"])
def test_identity_accepts_each_fixed_thing(thing):
    fact = _identity(payload={"thing": thing, "confidence": 0.7})

    assert fact == IdentityFact(
        thing=thing, confidence=0.7, observed_at=CAPTURED, age_s=1.0,
        state="OK", profile_id="identity-a", source="vlm",
    )


def test_explicit_unknown_keeps_the_reading_but_not_an_ok_state():
    fact = _identity(payload={"thing": "unknown", "confidence": 0.95})

    assert fact.thing == "unknown"
    assert fact.state == "UNKNOWN"
    assert fact.confidence == 0.95
    assert fact.observed_at == CAPTURED


def test_low_confidence_does_not_keep_the_named_thing():
    fact = _identity(payload={"thing": "person", "confidence": 0.69})

    assert fact.thing == "unknown"
    assert fact.state == "UNKNOWN"
    assert fact.confidence == 0.69
    assert fact.observed_at == CAPTURED


@pytest.mark.parametrize("payload", [
    {"thing": "person", "confidence": 0.91, "decision": "WAIT"},
    {"thing": "WAIT", "confidence": 0.99},
    {"thing": "person"},
    {"confidence": 0.99},
    ["person", 0.99],
])
def test_bad_identity_payload_is_unknown(payload):
    fact = _identity(payload=payload)

    assert fact.state == "UNKNOWN"
    assert fact.thing == "unknown"
    assert fact.confidence is None
    assert not hasattr(fact, "decision")


@pytest.mark.parametrize("overrides", [
    {"captured_at": None},
    {"captured_at": OPENED - timedelta(seconds=1)},
    {"captured_at": NOW - timedelta(seconds=9)},
    {"opened_at": None},
    {"now": datetime(2026, 10, 8, 1, 0, 2)},
    {"front_clearance_m": None},
    {"front_clearance_m": -0.1},
    {"profile_id": "other"},
    {"payload": None},
])
def test_stale_or_missing_identity_context_is_unknown(overrides):
    fact = _identity(**overrides)

    assert fact == IdentityFact(
        thing="unknown", confidence=None, observed_at=None, age_s=None,
        state="UNKNOWN", profile_id="identity-a", source="vlm",
    )


def test_lane_lost_is_not_an_identity_ask():
    with pytest.raises(ValueError, match="obstacle_ahead"):
        _identity(cause="lane_lost")


def test_identity_fact_is_frozen():
    fact = _identity()
    with pytest.raises(AttributeError):
        fact.thing = "wall"


def test_choice_inside_the_allowlist_is_kept():
    candidate = _choice()

    assert candidate == ChoiceCandidate(
        choice="hold_west", profile_id="choice-a", generation="stuck-9",
    )


@pytest.mark.parametrize("overrides", [
    {"response": {"answers": {"decision": {"choice": "go_faster"}}}},
    {"response": {"answers": {"decision": {"choice": "WAIT"}}}},
    {"response": None},
    {"criteria": {}},
    {"criteria": {"only": "one choice"}},
    {"criteria": {"WAIT": "wait", "YIELD": "yield"}},
    {"profile_id": "other"},
    {"generation": "stuck-8"},
    {"elapsed_s": 8.1},
    {"elapsed_s": None},
])
def test_choice_outside_the_contract_abstains(overrides):
    candidate = _choice(**overrides)

    assert candidate.choice is None
    assert candidate.profile_id == "choice-a"
    assert not hasattr(candidate, "decision")
    assert candidate.choice not in COMMAND_WORDS


def test_choice_candidate_is_frozen_and_not_a_command_type():
    candidate = _choice()
    with pytest.raises(AttributeError):
        candidate.choice = "ask_human"
    assert type(candidate).__name__ == "ChoiceCandidate"
