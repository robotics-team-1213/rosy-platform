import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest

from fleet.server.held_lidar_observation import inspect_held_route
from fleet.swarm.transport import RobotApiError


@pytest.mark.parametrize("case,expected", [
    ("clear", "observed_clear"), ("reverse", "observed_clear"), ("blocked", "blocked"), ("partial", "unknown"),
    ("other_robot", "unknown"), ("stale", "unknown"), ("sideways", "unknown"), ("zero", "unknown"),
    ("moving", "unknown"), ("legacy", "unknown"), ("wrong_frame", "unknown"), ("revoked", None)])
def test_held_route_reads_only_the_stopped_movers_axis_aligned_scan(case, expected):
    now = 1000.
    pose = {"x": 2., "y": 3., "yaw": 0.}
    state = {"pose_frame": "map", "pose": pose, "navigation": "IDLE", "map_id": "native",
             "odom_pose": {**pose, "stamp": now}, "velocity": {"linear": .01 if case == "moving" else 0., "angular": 0.},
             "evidence": {"pose": {"evidence": "fresh", "received_at": datetime.fromtimestamp(now, timezone.utc).isoformat()},
                          "velocity": {"evidence": "fresh"}}}
    live = NS(open=True, route_rev=1, view={"trip_id":"t", "robot_id":"42", "map_version":394, "detail":{"peer_wait":{"since":999.}}})
    delta = -.02 if case == "reverse" else 0 if case == "zero" else .1
    route = [{"x": 2. + delta, "y": 3.01 if case == "sideways" else 3.}]
    calls = []
    async def read(robot, query):
        calls.append((robot, query))
        if case == "legacy":
            raise RobotApiError(robot, 404, "NOT_FOUND", "older CORE")
        if case == "revoked":
            live.route_rev += 1
        return {"kind":"native_lidar_straight_corridor_v1", "robot_id":"46" if case == "other_robot" else robot, **query,
                "status":"blocked" if case == "blocked" else "observed_clear",
                "reason":"obstacle_in_corridor" if case == "blocked" else "required_sector_observed",
                "frame_id":"camera" if case == "wrong_frame" else "42/rplidar_link", "source_stamp_ns":123456,
                "checked_at":now, "received_at":now-1 if case == "stale" else now-.01,
                "required_beams":11, "observed_beams":9 if case == "partial" else 11}
    runner = NS(_clock=lambda:now, read_held_lidar=read)
    asyncio.run(inspect_held_route(runner, live, state, route))
    detail = live.view["detail"]
    if expected is None:
        assert "held_lidar_observation" not in detail
        return
    assert detail["held_lidar_observation"]["status"] == expected
    assert detail["peer_wait"] == {"since":999.}
    asyncio.run(inspect_held_route(runner, live, state, route))
    if case in {"sideways", "zero", "moving"}:
        assert not calls
    else:
        assert calls == [("42", {"direction":"reverse" if case == "reverse" else "forward",
                                 "distance_m":.02 if case == "reverse" else .03})]
