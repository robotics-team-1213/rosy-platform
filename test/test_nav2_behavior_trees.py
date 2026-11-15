"""D-1009: the behavior trees bt_navigator loads, and that every Nav2 launch path points at them."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NAV2 = ROOT / "middleware" / "drive" / "planning" / "nav2"
TREES = NAV2 / "behavior_trees"
sys.path.insert(0, str(NAV2))

from navigation.params_rewrite import write_prefixed_nav2_params  # noqa: E402

THROUGH, TO_POSE = TREES / "rosy_navigate_through_poses.xml", TREES / "rosy_navigate_to_pose.xml"


def _nodes(path):
    return list(ET.parse(path).getroot().iter())


def _attr(path, tag, key):
    return [n.get(key) for n in _nodes(path) if n.tag == tag]


def test_trees_replan_fast_and_keep_closely_spaced_pass_points():
    assert _attr(THROUGH, "RateController", "hz") == ["2.0"] and _attr(TO_POSE, "RateController", "hz") == ["2.0"]
    assert _attr(THROUGH, "RemovePassedGoals", "radius") == ["0.15"]   # stock 0.7 swallows 0.2 m spacing
    assert _attr(THROUGH, "ComputePathThroughPoses", "goals") == ["{goals}"]
    assert _attr(TO_POSE, "ComputePathToPose", "goal") == ["{goal}"]


def test_every_failure_is_retried_and_recoveries_are_short_and_in_place():
    for tree in (THROUGH, TO_POSE):
        tags = {n.tag for n in _nodes(tree)}
        assert not tags & {"WouldAPlannerRecoveryHelp", "WouldAControllerRecoveryHelp"}   # gate that ended a run at once
        assert not tags & {"Spin", "BackUp"}   # a wall may be 0.15 m away
        assert _attr(tree, "Wait", "wait_duration") == ["1.0"]
        assert _attr(tree, "RecoveryNode", "number_of_retries")[0] == "20"
        assert {"ClearEntireCostmap", "FollowPath"} <= tags


def test_launch_params_point_bt_navigator_at_the_trees(tmp_path):
    out = Path(write_prefixed_nav2_params(NAV2 / "params" / "nav2_params.yaml", "rosy_01", directory=tmp_path))
    bt = yaml.safe_load(out.read_text(encoding="utf-8"))["/rosy_01/bt_navigator"]["ros__parameters"]
    assert Path(bt["default_nav_to_pose_bt_xml"]) == (TREES / "rosy_navigate_to_pose.xml").resolve()
    assert Path(bt["default_nav_through_poses_bt_xml"]) == (TREES / "rosy_navigate_through_poses.xml").resolve()
    assert bt["navigators"] == ["navigate_to_pose", "navigate_through_poses"]


def test_trees_are_installed_with_the_package_and_the_sim_launch_uses_them():
    assert "behavior_trees" in (NAV2 / "CMakeLists.txt").read_text(encoding="utf-8")
    sim = (ROOT / "integrations/simulation/gazebo/launch/gz_multi.launch.py").read_text(encoding="utf-8")
    assert "rosy_navigate_through_poses.xml" in sim and "rosy_navigate_to_pose.xml" in sim
