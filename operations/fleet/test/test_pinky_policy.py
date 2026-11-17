import math
from unittest.mock import patch

from fleet.pipeline.pinky_policy import (
    PINKY_PROFILE,
    RobotKindProfile,
    compute_pinky_road_command,
    evaluate_pinky_dock_step,
    get_robot_profile,
)


def test_profile_defaults_and_robot_lookup():
    profile = RobotKindProfile()
    assert profile.kind == "pinky"
    assert profile.rear_x_m > 0
    assert profile.to_dict()["road_step_m"] == 0.12
    assert get_robot_profile() is PINKY_PROFILE
    assert get_robot_profile("rosy_07") is PINKY_PROFILE
    assert get_robot_profile("pinky_pro") is PINKY_PROFILE
    assert get_robot_profile("omx").kind == "omx"


@patch("fleet.pipeline.pinky_policy.evaluate_bay_dock")
def test_dock_fuses_onboard_offsets(mock_eval):
    mock_eval.return_value = {"verdict": "BACKING_DRIFT", "offset_m": 0.02, "yaw_err_deg": 10.0}
    result = evaluate_pinky_dock_step(0, 0, 0, None, onboard_lat_m=0.04,
                                      onboard_head_rad=math.radians(20))
    assert result["fused_offset_m"] == 0.027
    assert result["fused_yaw_err_deg"] == 13.5
    assert result["v_cmd_mps"] == -0.05
    mock_eval.assert_called_once_with(0, 0, 0, None, None)


@patch("fleet.pipeline.pinky_policy.evaluate_bay_dock", return_value={"verdict": "CONTACT_STOP"})
def test_dock_contact_stop(mock_eval):
    result = evaluate_pinky_dock_step(0, 0, None, None)
    assert (result["v_cmd_mps"], result["omega_cmd_rad_s"]) == (0.0, 0.0)


def test_road_command_advances_and_caps_speed():
    points = [{"x": 0.0, "y": 0.0}, {"x": 0.2, "y": 0.0},
              {"x": 0.5, "y": 0.0, "speed_cap_mps": 0.08}]
    result = compute_pinky_road_command((0.01, 0.0, 0.0), points)
    assert result["wp_index"] == 1
    assert result["next_goal"] == {"x": 0.5, "y": 0.0, "yaw": None}
    assert result["v_cmd_mps"] == 0.08
    assert result["omega_cmd_rad_s"] == 0.0


def test_road_turns_in_place_and_finishes():
    turn = compute_pinky_road_command((0, 0, 0), [{"x": -1, "y": 0}])
    assert turn["v_cmd_mps"] == 0.0
    assert turn["omega_cmd_rad_s"] == -1.6
    done = compute_pinky_road_command((0, 0, 0), [{"x": 0, "y": 0}])
    assert done["done"] is True
    assert done["v_cmd_mps"] == 0.0
