"""D-398: one validation rule for enforce and shadow (check_decision)."""

from dataclasses import replace

import pytest

from core_features.safety.manager import SafetyDecision, SafetyRequest, check_decision

REQUEST = SafetyRequest(command_id=7, source="navigation", calibration_revision="rev",
                        now=10.0, linear=0.1, angular=0.2)
GOOD = SafetyDecision(7, "navigation", "rev", observed_at=9.9, expires_at=10.3,
                      linear_limit=0.05, angular_limit=0.5, disposition="limit", reason="motion_limited")


def test_valid_decision_has_no_reason():
    assert check_decision(GOOD, REQUEST, elapsed=0.001) == ""


@pytest.mark.parametrize("decision, elapsed", [
    ("not a decision", 0.001),
    (replace(GOOD, command_id=8), 0.001),
    (replace(GOOD, source="docking"), 0.001),
    (replace(GOOD, calibration_revision="other"), 0.001),
    (replace(GOOD, observed_at=10.1), 0.001),          # observed after now
    (replace(GOOD, expires_at=9.95), 0.001),           # already expired
    (replace(GOOD, expires_at=10.5), 0.001),           # lease longer than 0.5 s
    (replace(GOOD, linear_limit=-0.1), 0.001),
    (replace(GOOD, disposition="maybe"), 0.001),
    (replace(GOOD, reason="x" * 129), 0.001),
    (GOOD, 0.011),                                     # over the 10 ms budget
    (GOOD, float("nan")),
])
def test_invalid_decisions_are_policy_invalid(decision, elapsed):
    assert check_decision(decision, REQUEST, elapsed=elapsed) == "policy_invalid"


def test_stop_disposition_reports_its_reason():
    stop = replace(GOOD, disposition="stop", reason="pickup")
    assert check_decision(stop, REQUEST, elapsed=0.001) == "pickup"
    assert check_decision(replace(stop, reason=""), REQUEST, elapsed=0.001) == "policy_stop"
