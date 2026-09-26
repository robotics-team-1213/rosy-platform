"""Measured mobile-manipulation footprint contracts."""

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "runtime" / "navigation"))

from navigation.footprint_profile import (  # noqa: E402
    FootprintProfile,
    load_footprint_profile,
)
from navigation.params_rewrite import write_prefixed_nav2_params  # noqa: E402


MOTION_PROFILES = ROOT / "deploy" / "robot" / "config" / "motion_profiles.yaml"
NAV2 = ROOT / "src" / "runtime" / "navigation" / "params" / "nav2_params.yaml"


def measured_mapping():
    return {
        "measured": True,
        "footprint": [[-0.20, -0.15], [0.20, -0.15], [0.20, 0.15], [-0.20, 0.15]],
        "clearance_m": 0.03,
        "payload": {"mass_kg": 1.5, "center_of_gravity_m": [0.0, 0.0, 0.25]},
        "max_linear_mps": 0.12,
        "max_angular_rps": 0.40,
        "moveit_scene_revision": "scene-2026-09-13-a",
    }


def test_default_device_motion_profiles_are_explicitly_unmeasured():
    profile = load_footprint_profile(MOTION_PROFILES, "carrying_box")

    assert profile.measured is False
    assert profile.operational is False
    assert profile.footprint == ()


def test_measured_profile_requires_payload_and_moveit_scene_contract():
    values = measured_mapping()
    values["payload"]["center_of_gravity_m"] = [-0.04, 0.02, 0.25]
    profile = FootprintProfile.from_mapping("carrying_box", values)

    assert profile.operational is True
    assert profile.payload_mass_kg == pytest.approx(1.5)
    assert profile.payload_cog_m == (-0.04, 0.02, 0.25)
    assert profile.max_angular_rps == pytest.approx(0.40)

    incomplete = measured_mapping()
    incomplete.pop("moveit_scene_revision")
    with pytest.raises(ValueError, match="moveit_scene_revision"):
        FootprintProfile.from_mapping("carrying_box", incomplete)


def test_measured_state_requires_a_polygon():
    incomplete = measured_mapping()
    incomplete["footprint"] = []
    with pytest.raises(ValueError, match="measured footprint"):
        FootprintProfile.from_mapping("stowed_arm", incomplete)


def test_prefixed_nav2_params_can_receive_the_measured_polygon(tmp_path):
    profile = FootprintProfile.from_mapping("base", measured_mapping())
    output = Path(
        write_prefixed_nav2_params(
            NAV2,
            "rosy_01",
            directory=tmp_path,
            footprint_points=profile.footprint,
        )
    )
    data = yaml.safe_load(output.read_text(encoding="utf-8"))

    local = data["local_costmap"]["local_costmap"]["ros__parameters"]
    global_map = data["global_costmap"]["global_costmap"]["ros__parameters"]
    assert local["footprint"] == "[[-0.2,-0.15],[0.2,-0.15],[0.2,0.15],[-0.2,0.15]]"
    assert global_map["footprint"] == local["footprint"]
    assert local["robot_base_frame"] == "rosy_01/base_footprint"
