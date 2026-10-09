"""D-579: a learning capture goal is the existing map goal, or a refusal."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
from capture_goal import (
    CAMERA_OFFLINE,
    GOAL_POINT_MISSING,
    NOT_LOCALIZED,
    capture_goal,
)

CAMERA = {"available": True, "stale": False}
MAP = {"state": "LOCALIZED", "pose_frame": "map"}


def test_offline_or_stale_camera_makes_no_goal():
    for camera in ({"available": False, "stale": False}, {"available": True, "stale": True}, None):
        result = capture_goal(camera=camera, localization=MAP, x=0.2, y=-0.1, yaw=0.0)
        assert result == {"ok": False, "refusal": CAMERA_OFFLINE, "goal": None}


def test_missing_or_odom_localization_makes_no_goal():
    for localization in (None, {}, {"state": "LOCALIZED", "pose_frame": "odom"}):
        result = capture_goal(camera=CAMERA, localization=localization, x=0.2, y=-0.1)
        assert result["ok"] is False
        assert result["refusal"] == NOT_LOCALIZED
        assert result["goal"] is None


def test_localized_without_a_finite_point_makes_no_goal():
    result = capture_goal(camera=CAMERA, localization=MAP, x=None, y=0.0, yaw=0.0)
    assert result == {"ok": False, "refusal": GOAL_POINT_MISSING, "goal": None}
    infinite = capture_goal(camera=CAMERA, localization=MAP, x=float("nan"), y=0.0, yaw=0.0)
    assert infinite["refusal"] == GOAL_POINT_MISSING


def test_fresh_camera_and_map_pose_return_the_existing_goal_body():
    result = capture_goal(camera=CAMERA, localization=MAP, x=0.2, y=-0.1, yaw=1.5)
    assert result == {
        "ok": True,
        "refusal": None,
        "goal": {"x": 0.2, "y": -0.1, "yaw": 1.5},
    }
