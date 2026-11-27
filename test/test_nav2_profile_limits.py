"""Device profile and Nav2 motion-limit contracts."""

import sys
from pathlib import Path

import pytest
import yaml

from robot_contracts import ROOT
sys.path.insert(0, str(ROOT / "middleware" / "drive" / "planning" / "nav2"))

from navigation.profile_limits import (
    MotionLimits,
    derive_slow_speed_params,
    load_motion_limits,
    validate_nav2_parameters,
    validate_requested_limits,
)


PROFILE = ROOT / "deploy" / "robot" / "pinky_pro" / "config" / "profile.hardware.yaml"
NAV2 = ROOT / "middleware" / "drive" / "planning" / "nav2" / "params" / "nav2_params.yaml"


def test_costmaps_wait_for_amcl_before_activating():
    """RTF 0.3에서 기본 TF 대기는 AMCL 첫 스캔보다 짧다. costmap이 죽으면 목표가 REJECTED다."""
    data = yaml.safe_load(NAV2.read_text(encoding="utf-8"))
    for costmap in ("local_costmap", "global_costmap"):
        timeout = data[costmap][costmap]["ros__parameters"]["initial_transform_timeout"]
        assert timeout >= 30.0, f"{costmap} initial_transform_timeout={timeout}"


def test_local_costmap_resolution_matches_map_and_window_stays_small():
    """0.05 m quantised the lane wall into a lethal band 0.09 m from the robot (rosy_45, 11-27)."""
    p = yaml.safe_load(NAV2.read_text(encoding="utf-8"))["local_costmap"]["local_costmap"]["ros__parameters"]
    assert p["resolution"] == 0.025
    assert round(p["width"] / p["resolution"]) * round(p["height"] / p["resolution"]) <= 6400  # Pi-class CPU budget (2x2 m window)


def test_nav2_default_inflation_is_the_hardware_value():
    """현장 기본은 0.08 m. 시뮬 월드는 worlds.yaml이 덮어쓴다."""
    data = yaml.safe_load(NAV2.read_text(encoding="utf-8"))
    for costmap in ("local_costmap", "global_costmap"):
        layer = data[costmap][costmap]["ros__parameters"]["inflation_layer"]
        radius = layer["inflation_radius"]
        assert radius == 0.08, f"{costmap} inflation_radius={radius}"
        assert layer["cost_scaling_factor"] == 8.0, f"{costmap} cost_scaling_factor={layer['cost_scaling_factor']}"
    assert data["global_costmap"]["global_costmap"]["ros__parameters"]["footprint_padding"] == 0.005


def test_factory_sim_inflation_is_wider_than_hardware_default():
    catalog = ROOT / "integrations" / "simulation" / "gazebo" / "config" / "worlds.yaml"
    worlds = yaml.safe_load(catalog.read_text(encoding="utf-8"))["worlds"]
    factory = float(worlds["rosy_factory.world"]["inflation_radius"])
    assert factory > 0.08


def test_goal_ball_is_shorter_than_the_lane_step_and_the_lookahead():
    """A carrot inside xy_goal_tolerance makes RPP rotate in place and never drive."""
    data = yaml.safe_load(NAV2.read_text(encoding="utf-8"))
    controller = data["controller_server"]["ros__parameters"]
    tolerance = controller["general_goal_checker"]["xy_goal_tolerance"]
    rpp = controller["FollowPath"]
    lookahead = rpp["min_lookahead_dist"]
    assert tolerance == 0.08
    assert tolerance < lookahead  # a carrot inside the goal ball makes RPP rotate without driving
    # 11-27 tight U-turn (R~0.135 m): lookahead 0.09 cuts the arc by L^2/(8R) ~ 0.8 cm.
    assert (rpp["lookahead_dist"], lookahead, rpp["max_lookahead_dist"]) == (0.09, 0.09, 0.10)
    assert (rpp["curvature_lookahead_dist"], rpp["lookahead_time"]) == (0.09, 0.6)
    assert rpp["use_regulated_linear_velocity_scaling"] is True


def test_global_planner_is_smac_and_rejects_unknown():
    """긴 통로에서 NavFn 역추적이 실패한다. 미지 공간은 지름길이 아니다."""
    data = yaml.safe_load(NAV2.read_text(encoding="utf-8"))
    grid = data["planner_server"]["ros__parameters"]["GridBased"]
    assert grid["plugin"] == "nav2_smac_planner::SmacPlanner2D"
    assert grid["allow_unknown"] is False


def test_deployed_motor_defaults_match_the_hardware_profile():
    """compose/.env/install-pi 기본값은 profile.hardware.yaml 숫자다."""
    limits = load_motion_limits(PROFILE)
    linear = f"{limits.max_linear_mps:.2f}"
    angular = f"{limits.max_angular_rps:.2f}"
    compose = (ROOT / "deploy" / "robot" / "pinky_pro" / "compose.yaml").read_text(encoding="utf-8")
    env = (ROOT / "deploy" / "robot" / "pinky_pro" / ".env.example").read_text(encoding="utf-8")
    installer = (ROOT / "deploy" / "robot" / "pinky_pro" / "install-pi.sh").read_text(encoding="utf-8")
    assert f"ROSY_MAX_LINEAR_MPS:-{linear}" in compose
    assert f"ROSY_MAX_ANGULAR_RPS:-{angular}" in compose
    assert f"ROSY_MAX_LINEAR_MPS={linear}" in env
    assert f"ROSY_MAX_ANGULAR_RPS={angular}" in env
    assert f"ROSY_MAX_LINEAR_MPS {linear}" in installer
    assert f"ROSY_MAX_ANGULAR_RPS {angular}" in installer


def test_pinky_profile_files_share_the_hardware_motion_ceilings():
    limits = load_motion_limits(PROFILE)
    paths = (
        ROOT / "middleware" / "devices" / "pinky" / "profile" / "config" / "profile.yaml",
        ROOT / "deploy" / "robot" / "pinky_pro" / "config" / "profile.core.yaml",
        ROOT / "deploy" / "robot" / "pinky_pro" / "config" / "profile.motor.yaml",
        ROOT / "contracts" / "foundation" / "config" / "rosy_default.yaml",
    )
    for path in paths:
        if path.name == "rosy_default.yaml":
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            nav = data["navigation"]
            assert float(nav["max_linear_velocity"]) == limits.max_linear_mps, path
            assert float(nav["max_angular_velocity"]) == limits.max_angular_rps, path
            continue
        other = load_motion_limits(path)
        assert other == limits, path


def test_hardware_profile_is_the_source_of_motion_ceilings():
    limits = load_motion_limits(PROFILE)

    assert limits == MotionLimits(max_linear_mps=0.20, max_angular_rps=0.80)
    validate_requested_limits(
        limits,
        max_linear_mps="0.20",
        max_angular_rps="0.80",
    )
    validate_nav2_parameters(NAV2, limits)


@pytest.mark.parametrize(
    ("name", "value"),
    [("max_linear_mps", 0.21), ("max_angular_rps", 0.81)],
)
def test_launch_override_above_profile_fails_closed(name, value):
    limits = load_motion_limits(PROFILE)
    requested = {"max_linear_mps": 0.20, "max_angular_rps": 0.80}
    requested[name] = value

    with pytest.raises(ValueError, match="exceeds Device profile ceiling"):
        validate_requested_limits(limits, **requested)


def test_nav2_velocity_override_above_profile_fails_closed(tmp_path):
    data = yaml.safe_load(NAV2.read_text(encoding="utf-8"))
    data["velocity_smoother"]["ros__parameters"]["max_velocity"][2] = 0.81
    path = tmp_path / "nav2.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ValueError, match="velocity_smoother.max_velocity"):
        validate_nav2_parameters(path, load_motion_limits(PROFILE))


def test_profile_with_missing_or_invalid_limits_fails_closed(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("profile:\n  max_linear_velocity: 0.2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="max_angular_velocity"):
        load_motion_limits(path)


def _nav2():
    return yaml.safe_load(NAV2.read_text(encoding="utf-8"))


def test_slow_speed_derivation_at_the_approved_speed():
    p = derive_slow_speed_params(_nav2(), 0.023, 0.093)
    c = p["controller_server"]["ros__parameters"]
    assert c["FollowPath"]["desired_linear_vel"] == 0.023
    assert c["FollowPath"]["rotate_to_heading_angular_vel"] == 0.093
    assert c["FollowPath"]["min_approach_linear_velocity"] == pytest.approx(0.0115)
    assert c["FollowPath"]["regulated_linear_scaling_min_speed"] == pytest.approx(0.0115)
    checker = c["progress_checker"]
    assert checker["movement_time_allowance"] == pytest.approx(1.25 * 3.141592653589793 / 0.093)
    assert checker["required_movement_radius"] == pytest.approx(0.25 * 0.023 * checker["movement_time_allowance"])
    assert p["velocity_smoother"]["ros__parameters"]["max_velocity"] == [0.023, 0.0, 0.093]
    assert p["behavior_server"]["ros__parameters"]["max_rotational_vel"] == 0.093
    # the derived file still passes the Device ceiling check
    limits = load_motion_limits(PROFILE)
    from navigation.params_rewrite import write_prefixed_nav2_params
    out = write_prefixed_nav2_params(NAV2, "", directory=Path(__import__("tempfile").mkdtemp()), speed=(0.023, 0.093))
    validate_nav2_parameters(out, limits)


def test_cost_scaling_matches_local_inflation_and_lookahead():
    data = _nav2()
    controller = data["controller_server"]["ros__parameters"]
    rpp = controller["FollowPath"]
    inflation = data["local_costmap"]["local_costmap"]["ros__parameters"]["inflation_layer"]["inflation_radius"]
    assert rpp["cost_scaling_dist"] <= inflation + 0.05
    assert rpp["min_lookahead_dist"] > controller["general_goal_checker"]["xy_goal_tolerance"]


def test_slow_speed_derivation_leaves_stock_speed_unchanged():
    assert derive_slow_speed_params(_nav2(), 0.20, 0.80) == _nav2()


def test_bt_server_timeout_survives_a_slow_controller_loop():
    bt = _nav2()["bt_navigator"]["ros__parameters"]
    assert bt["default_server_timeout"] == 500


def test_nav2_rpp_drives_forward_only_and_amcl_tracks_turns_tightly():
    """RPP allow_reversing+use_rotate_to_heading conflicts and locks reversed paths on wrong-way starts."""
    data = _nav2()
    rpp = data["controller_server"]["ros__parameters"]["FollowPath"]
    amcl = data["amcl"]["ros__parameters"]
    assert rpp["allow_reversing"] is False
    assert rpp["use_rotate_to_heading"] is True
    assert 0.65 <= rpp["rotate_to_heading_min_angle"] <= 1.0
    assert rpp["approach_velocity_scaling_dist"] <= 0.12
    assert rpp["max_allowed_time_to_collision_up_to_carrot"] <= 0.5
    assert amcl["update_min_d"] <= 0.05
    assert amcl["update_min_a"] <= 0.05
