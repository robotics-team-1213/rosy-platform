"""Decision results stay inside the allowed set and never become a velocity."""

from pathlib import Path

from core_features.decision import (
    ActionOption,
    DecisionRequest,
    DecisionStatus,
    route,
)

ROOT = Path(__file__).resolve().parents[4]
DECISION = Path(__file__).resolve().parents[1] / "core_features" / "decision"
LANE = (
    ActionOption("FOLLOW", motion=True),
    ActionOption("SLOW", motion=True),
    ActionOption("STOP", motion=False),
    ActionOption("ABSTAIN", motion=False),
)


def _request(**overrides) -> DecisionRequest:
    base = dict(
        decision_id="dec-1",
        decision_type="lane_recovery",
        allowed_actions=LANE,
        snapshot_age_ms=10,
        max_age_ms=120,
        deadline_ms=100,
        elapsed_ms=10,
        mode="NAVIGATION",
        safety_state="NORMAL",
        context={},
        fallback_action="STOP",
    )
    base.update(overrides)
    return DecisionRequest(**base)


def _pick(action_id):
    def rule(_request, _allowed):
        return action_id

    return rule


def test_a_legal_rule_is_decided():
    result = route(_request(), _pick("SLOW"))
    assert result.status is DecisionStatus.DECIDED
    assert result.selected_action == "SLOW"
    assert result.fallback_action is None


def test_an_action_outside_the_set_is_invalid_and_not_rewritten():
    result = route(_request(), _pick("TURN_180_AND_ACCELERATE"))
    assert result.status is DecisionStatus.INVALID
    assert result.selected_action is None
    assert result.fallback_action == "STOP"
    assert result.reason_code == "OUTSIDE_ALLOWED_SET"


def test_safe_stop_drops_motion_before_the_rule():
    result = route(_request(safety_state="SAFE_STOP"), _pick("FOLLOW"))
    assert result.status is DecisionStatus.INVALID
    assert result.selected_action is None


def test_manual_drops_autonomous_motion():
    result = route(_request(mode="MANUAL"), _pick("FOLLOW"))
    assert result.status is DecisionStatus.INVALID
    assert result.selected_action is None


def test_unresolved_rule_abstains_without_pretending_to_stop():
    result = route(_request(), lambda _request, _allowed: None)
    assert result.status is DecisionStatus.ABSTAINED
    assert result.selected_action is None
    assert result.fallback_action == "STOP"


def test_a_rule_error_stays_an_error():
    def boom(_request, _allowed):
        raise RuntimeError("provider down")

    result = route(_request(), boom)
    assert result.status is DecisionStatus.ERROR
    assert result.selected_action is None
    assert result.reason_code == "RULE_ERROR"


def test_stale_input_and_deadline_select_nothing():
    stale = route(_request(snapshot_age_ms=500), _pick("FOLLOW"))
    late = route(_request(elapsed_ms=500), _pick("FOLLOW"))
    assert stale.status is DecisionStatus.STALE_INPUT
    assert late.status is DecisionStatus.TIMEOUT
    assert stale.selected_action is None
    assert late.selected_action is None


def test_missing_rule_is_no_provider():
    result = route(_request(), None)
    assert result.status is DecisionStatus.NO_PROVIDER
    assert result.selected_action is None


def test_decision_has_no_actuator_and_no_ros_import():
    result = route(_request(), _pick("STOP"))
    assert not hasattr(result, "linear")
    assert not hasattr(result, "angular")
    source = "\n".join(path.read_text(encoding="utf-8") for path in DECISION.glob("*.py"))
    assert "cmd_vel" not in source
    assert "rclpy" not in source
    assert "import control" not in source


def test_decision_lives_in_core_features_not_a_runtime_rename():
    assert (ROOT / "src" / "runtime" / "features" / "core_features" / "decision").is_dir()
    for banned in (
        ROOT / "src" / "site" / "rosy_ai_worker",
        ROOT / "src" / "runtime" / "rosy_pinky_pro",
        ROOT / "src" / "rosy_pinky_pro",
    ):
        assert not banned.exists()


def test_fallback_that_was_filtered_out_is_not_invented():
    result = route(
        _request(safety_state="SAFE_STOP", fallback_action="SLOW"),
        _pick("FOLLOW"),
    )
    assert result.status is DecisionStatus.INVALID
    assert result.fallback_action is None
    assert result.selected_action is None
