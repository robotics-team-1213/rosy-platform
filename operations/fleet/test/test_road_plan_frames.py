"""road-nav2 converts a site goal into the robot's own SLAM frame, or refuses (2026-11-13)."""
import asyncio
import math
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from fleet.server.ledger.task_dispatch_helpers import compute_road_plan


def plan(site_pose, robot_state):
    async def map_pose(_robot_id):
        return site_pose

    console = SimpleNamespace(snapshot=lambda: _snap(robot_state))
    app = SimpleNamespace(state=SimpleNamespace(site_maps=None, trip_runner=SimpleNamespace(map_pose=map_pose)))
    return asyncio.run(compute_road_plan(console, SimpleNamespace(app=app), "rosy_46", 0.0, 0.0, None, None, ""))


async def _snap(robot_state):
    return {"robots": [{"robot_id": "rosy_46", "state": robot_state}]}


def site(x, y, yaw, state="LOCALIZED"):
    return SimpleNamespace(x=x, y=y, yaw=yaw, state=state)


SLAM_ORIGIN = {"pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
               "localization": {"state": "LOCALIZED", "pose_frame": "map"}}


def test_a_site_goal_is_rotated_and_shifted_into_the_slam_frame():
    # Robot booted at site (-0.42, 0.38) facing -90 deg, so its SLAM origin is there.
    out = plan(site(-0.42, 0.38, -math.pi / 2), SLAM_ORIGIN)["target_nav2"]
    # Site goal (0, 0): 0.42 east and 0.38 south of the robot; in the robot frame that is +0.38 ahead, +0.42 left.
    assert (out["x"], out["y"]) == pytest.approx((0.38, 0.42), abs=1e-3)


@pytest.mark.parametrize("pose", [None, site(-0.42, 0.38, -math.pi / 2, state="UNKNOWN")])
def test_no_measured_site_pose_refuses_instead_of_assuming_identity(pose):
    with pytest.raises(HTTPException) as err:
        plan(pose, SLAM_ORIGIN)
    assert err.value.detail["code"] == "SITE_POSE_UNKNOWN"


@pytest.mark.parametrize("state", [
    {"pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "localization": {"state": "LOST", "pose_frame": "map"}},
    {"pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "localization": {"state": "LOCALIZED", "pose_frame": "odom"}},
    {"localization": {"state": "LOCALIZED", "pose_frame": "map"}},
])
def test_no_localized_robot_map_pose_refuses(state):
    with pytest.raises(HTTPException) as err:
        plan(site(-0.42, 0.38, -math.pi / 2), state)
    assert err.value.detail["code"] == "ROBOT_POSE_UNTRUSTED"


def test_the_refusal_names_why_auto_locate_has_no_fit():
    # 2026-11-14 rosy_45: battery caution, so the robot refused the identify blink and no fit came.
    identity = SimpleNamespace(snapshot=lambda: {"robots": [
        {"robot_id": "rosy_46", "last": {"reason": "lamp_refused", "lamp_reason": "CAUTION_ACTIVE"}}]})
    auto = SimpleNamespace(tracking=SimpleNamespace(identity=identity), snapshot=lambda: {"robots": [
        {"robot_id": "rosy_46", "reason": "lamp_refused"}]})

    async def map_pose(_robot_id):
        return None

    console = SimpleNamespace(snapshot=lambda: _snap(SLAM_ORIGIN))
    app = SimpleNamespace(state=SimpleNamespace(site_maps=None, auto_locate=auto,
                                                trip_runner=SimpleNamespace(map_pose=map_pose)))
    with pytest.raises(HTTPException) as err:
        asyncio.run(compute_road_plan(console, SimpleNamespace(app=app), "rosy_46", 0.0, 0.0, None, None, ""))
    assert err.value.detail["auto_locate"] == "lamp_refused (CAUTION_ACTIVE)"
    assert "lamp_refused (CAUTION_ACTIVE)" in err.value.detail["message"]
