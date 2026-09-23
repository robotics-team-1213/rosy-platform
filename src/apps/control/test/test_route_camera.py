"""Prototype A: route-driven junction manoeuvres over centre-line following."""

import math

import lane_sim
import numpy as np
import pytest
from control.sensing.route_camera import MANOEUVRE_MAX_TRAVEL_M, RouteCameraFollower
from lane_scenarios import (
    GRAPH,
    SCENARIOS,
    WORLD,
    junction_score,
    run_scenario,
    summary,
)
from lane_sim import CAM_X


def follower(scenario):
    return RouteCameraFollower(GRAPH, [scenario["into"], scenario["out"]],
                               start_pose=scenario["start"], camera_x_offset_m=CAM_X)


directed_points = junction_score.directed_points


def _blank_world():
    """A copy of the STL paint raster to erase from."""
    world = lane_sim.World(WORLD.x0, WORLD.x0 + WORLD.paint.shape[1] / 1000.0,
                           WORLD.y1 - WORLD.paint.shape[0] / 1000.0, WORLD.y1)
    world.paint = WORLD.paint.copy()
    return world


def _world_without_paint_after_the_node(scenario, radius_m=0.35):
    """The STL paint with every painted cell within radius_m of the node erased."""
    blank = _blank_world()
    node = GRAPH["nodes"][scenario["node"]]
    col, row = blank.px([node])[0]
    rows, cols = np.mgrid[0:blank.paint.shape[0], 0:blank.paint.shape[1]]
    blank.paint[np.hypot(cols - col, rows - row) <= radius_m * 1000.0] = 0
    return blank


@pytest.mark.parametrize("index", range(12))
def test_every_junction_transition_is_driven(index):
    scenario = SCENARIOS[index]
    result = run_scenario(scenario, follower(scenario), steps=260)
    result["scenario"] = scenario
    assert result["reached_end"], summary([result])
    assert result["branch_ok"], summary([result])
    assert not result["wrong_way"], summary([result])
    assert result["ring_ccw_ok"], summary([result])
    assert result["max_centre_dev_m"] <= 0.040, summary([result])


class _OdomFrameAtOrigin:
    """Hands the follower odometry whose frame starts at (0, 0, 0) while the
    robot stands at the scenario start (a real /odom, unlike Gazebo's)."""

    def __init__(self, subject, start):
        self.subject = subject
        self._start = tuple(float(v) for v in start)

    @property
    def state(self):
        return self.subject.state

    def update(self, now_s, pose, bgr, ground, **kwargs):
        x0, y0, yaw0 = self._start
        c, s = math.cos(yaw0), math.sin(yaw0)
        dx, dy = pose[0] - x0, pose[1] - y0
        odom = (c * dx + s * dy, -s * dx + c * dy, pose[2] - yaw0)
        return self.subject.update(now_s, odom, bgr, ground, **kwargs)


@pytest.mark.parametrize("index", [0, 5, 7, 11])
def test_odometry_from_its_own_origin_is_placed_on_the_map(index):
    """HIGH-1: /odom starts at (0, 0, 0) wherever the robot is. The follower
    anchors T_map_odom = start_pose (-) first odometry pose, so the clean
    scenarios still pass (one per node: NE, NW, SE, SW)."""
    scenario = SCENARIOS[index]
    subject = follower(scenario)
    result = run_scenario(scenario, _OdomFrameAtOrigin(subject, scenario["start"]), steps=260)
    result["scenario"] = scenario
    assert result["pass"], summary([result])
    assert result["max_centre_dev_m"] <= 0.040, summary([result])
    assert math.dist(subject.map_pose[:2], result["last_true_pose"][:2]) < 1e-6


def test_a_manoeuvre_that_never_reacquires_stops():
    """Fail-closed: with the world blank after the node, the manoeuvre ends
    and the follower publishes nothing rather than driving blind."""
    scenario = SCENARIOS[5]
    blank = _world_without_paint_after_the_node(scenario)
    result = run_scenario(scenario, follower(scenario), steps=260, world=blank)
    assert not result["pass"]
    assert result["tiers"][-1] in ("STOP", "MANOEUVRE_ABORT")


def test_a_manoeuvre_into_unpainted_floor_aborts_within_its_travel():
    """The plan's blank disc also covers the start, so that run stops before
    moving. Here the approach keeps its paint and only the floor past the
    node is blank (a 0.30 m disc centred 0.30 m into `out`): the follower
    must commit the manoeuvre, then abort on MANOEUVRE_MAX_TRAVEL_M instead
    of driving the route blind to the end point."""
    scenario = SCENARIOS[5]
    out = directed_points(GRAPH, scenario["out"])
    world = _blank_world()
    col, row = world.px([out[30]])[0]
    rows, cols = np.mgrid[0:world.paint.shape[0], 0:world.paint.shape[1]]
    world.paint[np.hypot(cols - col, rows - row) <= 300.0] = 0
    subject = follower(scenario)
    result = run_scenario(scenario, subject, steps=260, world=world)
    assert "MANOEUVRE" in result["tiers"]
    assert result["tiers"][-1] == "MANOEUVRE_ABORT"
    assert not result["reached_end"]
    first = result["tiers"].index("MANOEUVRE")
    track = result["track"]
    driven = sum(math.dist(track[i], track[i + 1]) for i in range(first, len(track) - 1))
    assert driven <= MANOEUVRE_MAX_TRAVEL_M + 0.01


def test_camera_tiers_drive_between_junctions():
    """Prototype A stays a camera method: on the longest approach (west:f,
    scenario 05) most frames are camera tiers, not the route."""
    scenario = SCENARIOS[5]
    result = run_scenario(scenario, follower(scenario), steps=260)
    camera = sum(tier in ("BOTH", "ONE", "MEMORY") for tier in result["tiers"])
    assert camera >= 0.7 * len(result["tiers"])


def test_the_route_forbids_the_wrong_way_round_the_ring():
    with pytest.raises(ValueError, match="one-way"):
        RouteCameraFollower(GRAPH, ["west:f", "ring_n:r"], start_pose=(0, 0, 0))


def test_a_map_frame_pose_is_used_as_given():
    """route_hybrid feeds the paint-localised estimate, already in the map
    frame: with map_frame=True no T_map_odom anchor is applied, so a first
    pose off start_pose is not snapped onto it."""
    scenario = SCENARIOS[5]
    subject = RouteCameraFollower(GRAPH, [scenario["into"], scenario["out"]],
                                  start_pose=scenario["start"], camera_x_offset_m=CAM_X,
                                  map_frame=True)
    x, y, yaw = scenario["start"]
    pose = (x + 0.01, y - 0.02, yaw + 0.05)
    subject.update(0.0, pose, WORLD.render(scenario["start"]), lane_sim.GROUND, **lane_sim.KW)
    assert subject.map_pose == pytest.approx(pose)
    assert follower(scenario).map_pose == tuple(scenario["start"])
