"""OMX adapter profile contracts."""

import pytest

from omx_adapter.cli import main
from omx_adapter.profile import OmxAdapterProfile


def test_unselected_omx_is_valid_but_not_capable():
    profile = OmxAdapterProfile.from_mapping({"enabled": False})

    assert profile.model == ""
    assert profile.capability_enabled is False
    assert profile.ros2_control_contract() == {}


def test_enabled_profile_emits_standard_joint_trajectory_contract():
    profile = OmxAdapterProfile.from_mapping(
        {
            "enabled": True,
            "model": "omx-f",
            "driver_package": "omx_f_driver",
            "hardware_plugin": "omx_f_driver/OmxFSystem",
            "joint_names": ["joint1", "joint2", "joint3", "joint4", "joint5", "joint6"],
            "base_frame": "base_link",
            "arm_base_frame": "omx_base_link",
            "update_rate_hz": 100,
        }
    )

    contract = profile.ros2_control_contract()
    assert profile.capability_enabled is True
    assert contract["joint_state_broadcaster"]["type"] == (
        "joint_state_broadcaster/JointStateBroadcaster"
    )
    assert contract["arm_controller"]["type"] == (
        "joint_trajectory_controller/JointTrajectoryController"
    )
    assert contract["arm_controller"]["joints"] == list(profile.joint_names)
    assert contract["hardware_plugin"] == "omx_f_driver/OmxFSystem"
    assert contract["moveit"]["trajectory_action"] == (
        "arm_controller/follow_joint_trajectory"
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"enabled": True},
        {"enabled": True, "model": "unknown"},
        {"enabled": True, "model": "omx-f", "driver_package": "pkg"},
        {
            "enabled": True,
            "model": "omx-f",
            "driver_package": "pkg",
            "hardware_plugin": "plugin",
            "joint_names": ["joint1", "joint1"],
        },
    ],
)
def test_enabled_profile_fails_closed_until_model_driver_and_joints_are_known(patch):
    with pytest.raises(ValueError):
        OmxAdapterProfile.from_mapping(patch)


def test_model_aliases_are_normalized():
    profile = OmxAdapterProfile.from_mapping(
        {
            "enabled": False,
            "model": "OpenMANIPULATOR-X",
        }
    )

    assert profile.model == "openmanipulator_x"


def test_numeric_and_frame_parameters_fail_closed():
    with pytest.raises(ValueError):
        OmxAdapterProfile.from_mapping({"update_rate_hz": True})
    with pytest.raises(ValueError):
        OmxAdapterProfile.from_mapping({"base_frame": ""})
    with pytest.raises(ValueError):
        OmxAdapterProfile.from_mapping({"arm_base_frame": " omx_base_link"})


def test_cli_prints_disabled_contract(tmp_path, capsys):
    profile = tmp_path / "omx.yaml"
    profile.write_text("omx:\n  enabled: false\n", encoding="utf-8")

    assert main([str(profile)]) == 0
    assert capsys.readouterr().out.strip() == "{}"
