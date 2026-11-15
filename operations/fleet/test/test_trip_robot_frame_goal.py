"""D-1003: a free trip's Nav2 goal is its segment end, in the robot's own map frame, not the site map frame."""

from __future__ import annotations

import math

from rosy.world.state.projections.map_pose import MapPose
from fleet.server.trip_geometry import robot_frame_goal
from fleet.swarm.transport import RobotApiError
from test_trip_runner import BOTH, _arc, _free_map, _plan, _setup, _ticks, run

#: The robot's SLAM map is the site map turned 90 degrees and moved by (2, 3).
TURN, SHIFT = math.pi / 2, (2.0, 3.0)


def _in_robot_map(x, y, yaw):
    c, s = math.cos(TURN), math.sin(TURN)
    return c * x - s * y + SHIFT[0], s * x + c * y + SHIFT[1], yaw + TURN


def _state(pose, state="LOCALIZED", frame="map", map_id=None):
    body = {"pose": dict(zip(("x", "y", "yaw"), pose)), "localization": {"state": state, "pose_frame": frame}}
    if map_id is not None:
        body["map_id"] = map_id
    return body


def test_the_goal_moves_with_the_frame_offset_and_equal_frames_keep_it():
    site = MapPose(0.1, 0.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, 0.1)
    x, y, yaw = robot_frame_goal((0.3, 0.0, 0.0), site, _state(_in_robot_map(0.1, 0.0, 0.0)))
    assert (round(x, 6), round(y, 6), round(yaw, 6)) == (2.0, 3.3, round(TURN, 6))
    same = robot_frame_goal((0.3, 0.2, 1.0), site, _state((0.1, 0.0, 0.0)))
    assert [round(v, 9) for v in same] == [0.3, 0.2, 1.0]


def test_no_localized_map_frame_pose_is_no_goal():
    site = MapPose(0.1, 0.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, 0.1)
    for state in (_state((0, 0, 0), frame="odom"), _state((0, 0, 0), state="SUSPECT"), {"pose": None},
                  {"localization": {"state": "LOCALIZED", "pose_frame": "map"}}, None,
                  _state((float("nan"), 0, 0))):
        assert robot_frame_goal((0.3, 0.0, 0.0), site, state) is None


def test_a_free_trip_sends_its_goals_in_the_robot_map_frame():
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    ports.map_id = "site"  # D-1010: the site side of the conversion is anchored on the active map
    robot = {"state": None}

    async def robot_state(robot_id):
        return robot["state"]

    runner._robot_state = robot_state
    _plan(store, ports, "ab:fwd", 0.1, "C")
    robot["state"] = _state(_in_robot_map(ports.pose.x, ports.pose.y, ports.pose.yaw))
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    assert ports.goals == [(2.0, 4.0)]  # the segment end, site (1, 0), seen from the robot's own map


def test_a_robot_without_a_map_frame_pose_gets_no_goal():
    """D-1010 review: no LOCALIZED map pose to pair with and no map id proof — the site goal no
    longer goes out raw (D-1003 3항's unconditional fallback is gone); the trip stops on map_frame."""
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    ports.map_id = "site"

    async def robot_state(robot_id):
        return _state((5.0, 5.0, 1.0), frame="odom")

    runner._robot_state = robot_state
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    row = runner.view("p1")
    assert ports.goals == [] and row["state"] == "stopped" and row["reason"] == "map_frame"


def test_free_trip_sends_each_segment_end_once_and_arrives():
    """D-1003 4 (replaces the D-463 rolling point): CORE takes no new goal while Nav2 runs one."""
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    assert ports.goals == [(1.0, 0.0)] and ports.sent == []
    ports.at(_arc(store, "ab:fwd"), 0.6)
    _ticks(runner, ports)
    assert len(ports.goals) == 1  # the same place is not sent again
    ports.at(_arc(store, "bc:fwd"), 0.05)
    ports.goal_error = RobotApiError("rosy_60", 409, "NAVIGATION_ACTIVE", "navigation in progress")
    _ticks(runner, ports)
    assert len(ports.goals) == 1 and runner.view("p1")["state"] == "running"  # B's goal still finishing
    ports.goal_error = None
    _ticks(runner, ports)
    assert ports.goals[-1] == (1.0, 1.0)
    ports.at(_arc(store, "bc:fwd"), 0.97)
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "arrived"
