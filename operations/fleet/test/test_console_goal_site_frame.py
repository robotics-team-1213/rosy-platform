"""D-1003 for console goals: a site-map click is converted into the robot's own map frame, or refused (2026-11-14)."""
from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from rosy.world.state.projections.map_pose import MapPose
from fleet.server.ledger.task_dispatch_routes import ConsoleGoalRequest
from fleet.server.trip_geometry import site_goal_in_robot_frame

LOCALIZED = {"localization": {"state": "LOCALIZED", "pose_frame": "map"}}


def _convert(state, site_pose, active_map="site", goal=(0.0, 0.0, 0.0)):
    async def gather(robot_id):
        return state, "ok"
    active = None if active_map is None else (3, SimpleNamespace(map_id=active_map))
    app = SimpleNamespace(state=SimpleNamespace(site_maps=SimpleNamespace(active=lambda: active),
                                                map_pose=SimpleNamespace(arbitrated_pose=lambda rid: site_pose)))
    return asyncio.run(site_goal_in_robot_frame(app, SimpleNamespace(_gather_state=gather), "rosy_46", goal))


def test_a_site_goal_is_rotated_and_shifted_into_the_robot_frame():
    # The robot booted at site (-0.42, 0.38) facing -90 deg, so its SLAM origin sits there.
    site = MapPose(-0.42, 0.38, -math.pi / 2, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site")
    state = {**LOCALIZED, "map_id": "slam", "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}}
    x, y, yaw = _convert(state, site)
    assert (x, y) == pytest.approx((0.38, 0.42), abs=1e-6)
    assert yaw == pytest.approx(math.pi / 2)   # site yaw 0 seen from a robot frame turned -90 deg


def test_a_robot_on_the_site_map_itself_gets_the_goal_unchanged():
    assert _convert({"map_id": "site"}, None, goal=(1.0, 2.0, 0.5)) == (1.0, 2.0, 0.5)


@pytest.mark.parametrize("state,site,active", [
    ({**LOCALIZED, "map_id": "slam", "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}}, None, "site"),   # no site pose
    ({"map_id": "slam", "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}}, None, "site"),                # not localized
    ({"map_id": "site"}, None, None),                                                             # no site map
])
def test_without_a_frame_proof_the_goal_is_refused_not_sent_raw(state, site, active):
    with pytest.raises(HTTPException) as err:
        _convert(state, site, active)
    assert err.value.status_code == 409


def test_the_frame_field_takes_only_site():
    assert ConsoleGoalRequest(x=0, y=0, frame="site").frame == "site"
    with pytest.raises(ValueError):
        ConsoleGoalRequest(x=0, y=0, frame="robot")
