"""Device profile and Nav2 motion-limit contracts."""

import sys
from pathlib import Path

import pytest
import yaml

from robot_contracts import ROOT
sys.path.insert(0, str(ROOT / "src" / "runtime" / "navigation"))

from navigation.profile_limits import (
    MotionLimits,
    load_motion_limits,
    validate_nav2_parameters,
    validate_requested_limits,
)


PROFILE = ROOT / "deploy" / "robot" / "config" / "profile.hardware.yaml"
NAV2 = ROOT / "src" / "runtime" / "navigation" / "params" / "nav2_params.yaml"


def test_costmaps_wait_for_amcl_before_activating():
    """RTF 0.3에서 기본 TF 대기는 AMCL 첫 스캔보다 짧다. costmap이 죽으면 목표가 REJECTED다."""
    data = yaml.safe_load(NAV2.read_text(encoding="utf-8"))
    for costmap in ("local_costmap", "global_costmap"):
        timeout = data[costmap][costmap]["ros__parameters"]["initial_transform_timeout"]
        assert timeout >= 30.0, f"{costmap} initial_transform_timeout={timeout}"


def test_nav2_default_inflation_is_the_hardware_value():
    """현장 기본은 0.15 m. 시뮬 월드는 worlds.yaml이 덮어쓴다."""
    data = yaml.safe_load(NAV2.read_text(encoding="utf-8"))
    for costmap in ("local_costmap", "global_costmap"):
        radius = data[costmap][costmap]["ros__parameters"]["inflation_layer"][
            "inflation_radius"
        ]
        assert radius == 0.15, f"{costmap} inflation_radius={radius}"


def test_factory_sim_inflation_is_wider_than_hardware_default():
    catalog = ROOT / "src" / "sim" / "gz_sim" / "config" / "worlds.yaml"
    worlds = yaml.safe_load(catalog.read_text(encoding="utf-8"))["worlds"]
    factory = float(worlds["rosy_factory.world"]["inflation_radius"])
    assert factory > 0.15


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
    compose = (ROOT / "deploy" / "robot" / "compose.yaml").read_text(encoding="utf-8")
    env = (ROOT / "deploy" / "robot" / ".env.example").read_text(encoding="utf-8")
    installer = (ROOT / "deploy" / "robot" / "install-pi.sh").read_text(encoding="utf-8")
    assert f"ROSY_MAX_LINEAR_MPS:-{linear}" in compose
    assert f"ROSY_MAX_ANGULAR_RPS:-{angular}" in compose
    assert f"ROSY_MAX_LINEAR_MPS={linear}" in env
    assert f"ROSY_MAX_ANGULAR_RPS={angular}" in env
    assert f"ROSY_MAX_LINEAR_MPS {linear}" in installer
    assert f"ROSY_MAX_ANGULAR_RPS {angular}" in installer


def test_pinky_profile_files_share_the_hardware_motion_ceilings():
    limits = load_motion_limits(PROFILE)
    paths = (
        ROOT / "src" / "products" / "pinky_pro" / "config" / "profile.yaml",
        ROOT / "deploy" / "robot" / "config" / "profile.core.yaml",
        ROOT / "deploy" / "robot" / "config" / "profile.motor.yaml",
        ROOT / "src" / "runtime" / "gateway" / "config" / "rosy_default.yaml",
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
