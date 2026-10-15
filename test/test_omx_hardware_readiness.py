"""Software inventory must not turn a camera graph into hardware admission."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "omx_hardware_readiness", ROOT / "deploy/robot/omx/hardware_readiness.py")
assert SPEC and SPEC.loader
readiness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(readiness)


def test_current_camera_only_host_reports_each_missing_control_boundary():
    report = readiness.evaluate_runtime(
        ros_distro="lyrical", expected_ros_distro="jazzy",
        packages={"controller_manager"}, actions={},
        joint_state_publishers={"/joint_state_publisher"})
    assert report["software_path_available"] is False
    assert report["motion_admitted"] is False
    assert "ros_distribution_mismatch" in report["blockers"]
    assert "trajectory_action_missing" in report["blockers"]
    assert "hardware_joint_state_source_missing" in report["blockers"]
    assert "synthetic_joint_state_publisher_present" in report["blockers"]
    assert "omx_adapter" in report["missing_packages"]
    assert "dynamixel_hardware_interface" in report["missing_packages"]


def test_complete_software_graph_still_does_not_admit_motion():
    report = readiness.evaluate_runtime(
        ros_distro="jazzy", expected_ros_distro="jazzy",
        packages=readiness.REQUIRED_PACKAGES, namespace="/cell",
        actions={"/cell/arm_controller/follow_joint_trajectory": ["control_msgs/action/FollowJointTrajectory"]},
        joint_state_publishers={"/cell/controller_manager"})
    assert report["software_path_available"] is True
    assert report["blockers"] == []
    assert report["motion_admitted"] is False
    assert report["unverified"] == ["physical_identity", "measured_profile", "physical_feedback",
                                    "independent_stop", "calibration", "payload", "recovery"]


@pytest.mark.parametrize("publisher", ["joint_state_publisher", "joint_state_publisher_gui", "unknown"])
def test_joint_topic_presence_and_matching_action_name_are_insufficient(publisher):
    report = readiness.evaluate_runtime(
        ros_distro="jazzy", expected_ros_distro="jazzy", packages=readiness.REQUIRED_PACKAGES,
        actions={"/arm_controller/follow_joint_trajectory": ["example_interfaces/action/Fibonacci"]},
        joint_state_publishers={"/" + publisher})
    assert "trajectory_action_missing" in report["blockers"]
    assert "hardware_joint_state_source_missing" in report["blockers"]


def test_missing_distribution_is_unknown_not_a_match():
    report = readiness.evaluate_runtime(
        ros_distro="", expected_ros_distro="jazzy", packages=set(), actions={}, joint_state_publishers=set())
    assert "ros_distribution_mismatch" in report["blockers"]


def test_ros_initialization_failure_is_a_closed_json_report(monkeypatch, capsys):
    def refuse_init(**kwargs):
        raise RuntimeError("DDS initialization refused")
    fake_ros = SimpleNamespace(init=refuse_init)
    fake_index = SimpleNamespace(get_package_prefix=lambda package: "/test/prefix",
                                 PackageNotFoundError=LookupError)
    monkeypatch.setitem(sys.modules, "rclpy", fake_ros)
    monkeypatch.setitem(sys.modules, "ament_index_python.packages", fake_index)
    assert readiness.main(["--domain-id", "13", "--namespace", "/"]) == 2
    import json
    report = json.loads(capsys.readouterr().out)
    assert report["motion_admitted"] is False
    assert report["blockers"] == ["runtime_discovery_failed"]


def test_other_cell_action_cannot_supply_this_cell_software_path():
    report = readiness.evaluate_runtime(
        ros_distro="jazzy", expected_ros_distro="jazzy", packages=readiness.REQUIRED_PACKAGES,
        namespace="/cell_a", joint_state_publishers={"/cell_b/controller_manager"},
        actions={"/cell_b/arm_controller/follow_joint_trajectory": ["control_msgs/action/FollowJointTrajectory"]})
    assert "trajectory_action_missing" in report["blockers"]
    assert "hardware_joint_state_source_missing" in report["blockers"]


def test_missing_lock_reports_failure_before_ros_initialization(monkeypatch, capsys):
    def missing(*args, **kwargs):
        raise FileNotFoundError("lock unavailable")
    monkeypatch.setattr(readiness.Path, "read_text", missing)
    assert readiness.main(["--domain-id", "13", "--namespace", "/"]) == 2
    import json
    assert json.loads(capsys.readouterr().out)["blockers"] == ["runtime_discovery_failed"]
