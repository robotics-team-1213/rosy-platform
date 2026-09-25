"""lane_recovery returns FOLLOW or STOP and never a velocity."""

from core_features.decision import DecisionRequest, DecisionStatus, route
from core_features.decision.lane import FOLLOW, LANE_ACTIONS, STOP, lane_recovery_rule


def _request(*, safety_state: str = "NORMAL", mode: str = "NAVIGATION", **context) -> DecisionRequest:
    base = dict(
        visible=True,
        confidence=0.9,
        min_confidence=0.35,
        age_s=0.1,
        stale_after_s=0.3,
        source_matches=True,
    )
    base.update(context)
    return DecisionRequest(
        decision_id="lane-1",
        decision_type="lane_recovery",
        allowed_actions=LANE_ACTIONS,
        snapshot_age_ms=10,
        max_age_ms=300,
        deadline_ms=100,
        elapsed_ms=10,
        mode=mode,
        safety_state=safety_state,
        context=base,
        fallback_action=STOP,
    )


def test_a_fresh_visible_line_follows():
    result = route(_request(), lane_recovery_rule)
    assert result.status is DecisionStatus.DECIDED
    assert result.selected_action == FOLLOW
    assert not hasattr(result, "linear")


def test_low_confidence_stops_instead_of_slowing():
    result = route(_request(confidence=0.1), lane_recovery_rule)
    assert result.status is DecisionStatus.DECIDED
    assert result.selected_action == STOP


def test_stale_hidden_or_mismatched_source_stops():
    assert route(_request(age_s=1.0), lane_recovery_rule).selected_action == STOP
    assert route(_request(visible=False), lane_recovery_rule).selected_action == STOP
    assert route(_request(source_matches=False), lane_recovery_rule).selected_action == STOP
    assert route(_request(age_s=None), lane_recovery_rule).selected_action == STOP


def test_safe_stop_rejects_follow_without_rewriting_it():
    result = route(_request(safety_state="SAFE_STOP"), lane_recovery_rule)
    assert result.status is DecisionStatus.INVALID
    assert result.selected_action is None
    assert result.fallback_action == STOP
    assert result.reason_code == "OUTSIDE_ALLOWED_SET"
