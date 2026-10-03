"""ROS-free contracts for the post-mapping Nav2 probe."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "launch" / "pinky_acceptance_policy.py"
PROBE = ROOT / "scripts" / "pinky_nav2_probe.py"


def _policy():
    spec = importlib.util.spec_from_file_location("pinky_acceptance_policy", POLICY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_navigation_result_requires_success_and_bounded_pose_error():
    policy = _policy()

    assert policy.goal_position_error((0.0, 0.0), (0.03, 0.04)) == pytest.approx(0.05)
    assert policy.nav_result_passes("SUCCEEDED", 0.05, 0.08) is True
    assert policy.nav_result_passes("ABORTED", 0.01, 0.08) is False
    assert policy.nav_result_passes("SUCCEEDED", 0.081, 0.08) is False
    assert policy.nav_result_passes("SUCCEEDED", float("nan"), 0.08) is False


def test_navigation_result_rejects_invalid_error_limit():
    policy = _policy()

    with pytest.raises(ValueError):
        policy.nav_result_passes("SUCCEEDED", 0.01, 0.0)


def test_probe_uses_nav2_action_and_never_publishes_velocity():
    source = PROBE.read_text(encoding="utf-8")

    assert "NavigateToPose" in source
    assert 'ActionClient(self, NavigateToPose, "navigate_to_pose")' in source
    assert "create_publisher(" in source
    assert 'String, "navigation/probe_status", qos' in source
    assert "goal_position_error(" in source
    assert "nav_result_passes(" in source
    assert "create_publisher(Twist" not in source
    assert '"cmd_vel"' not in source


def test_probe_waits_for_bt_navigator_active_before_sending_goal():
    source = PROBE.read_text(encoding="utf-8")

    assert "lifecycle_msgs.srv import GetState" in source
    assert 'create_client(GetState, "bt_navigator/get_state")' in source
    assert "PRIMARY_STATE_ACTIVE" in source
    assert "wait_for_nav2_active" in source
    assert source.index("wait_for_nav2_active") < source.index("send_goal_async(goal)")
