"""D-463: a lane route is the graph polyline, and one goal is the next short point."""

from __future__ import annotations

import math
from hashlib import sha256
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.lane_route import STEP_M, LaneRouteError, next_step, route_lines
from site_map_fixture import painted_track
from fleet.server.app import GoalRequest, create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapStore
from fleet.site_map import from_lane_graph
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.usefixtures("unnamed_operator_drives")
RING = ("ring_s", "ring_e", "ring_n", "ring_w")
LANE_GRAPH = ROOT / "middleware" / "perception" / "map" / "map_v2_fleet" / "lane_graph.yaml"


def _site_maps() -> SiteMapStore:
    """D-488: /route reads the active site map, imported from the configured lane graph."""
    store = SiteMapStore()
    store.import_if_empty(from_lane_graph(LANE_GRAPH), source="lane_graph.yaml")
    return store


def _localized(x: float, y: float, frame: str = "map") -> dict:
    return {
        "robot_id": "rosy_60",
        "pose": {"x": x, "y": y, "yaw": 0.0},
        "localization": {"state": "LOCALIZED", "pose_frame": frame},
    }


@pytest.fixture
def unnamed_operator_drives(monkeypatch):
    """These tests cover lane geometry on the direct (no task store) path. D-540 9 names the
    operator on /route; test_named_operator_motion_routes.py covers that refusal."""
    import fleet.server.app as app_module
    real = app_module.build_role_guards

    def guards(*args, **kwargs):
        viewer, operator, _named, proposer = real(*args, **kwargs)
        return viewer, operator, operator, proposer
    monkeypatch.setattr(app_module, "build_role_guards", guards)


def _client(state: dict):
    robot = FakeRobot("rosy_60", state=state)
    console = FleetConsole(
        [RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")], [robot])
    return TestClient(create_app(console, site_maps=_site_maps())), robot


def _goals(robot: FakeRobot) -> list[tuple]:
    return [call for call in robot.calls if call[0] == "navigation_goal"]


def test_ring_order_is_continuous_and_the_reverse_join_is_not():
    assert route_lines(RING, painted_track())
    with pytest.raises(LaneRouteError, match="ROUTE_DISCONTINUOUS"):
        route_lines(("ring_s", "ring_w"), painted_track())
    with pytest.raises(LaneRouteError, match="ROUTE_UNKNOWN_EDGE"):
        route_lines(("not-an-edge",), painted_track())


def test_next_point_stays_on_ring_s_and_is_not_the_far_junction():
    line = painted_track().line("ring_s")
    start = line.point_at(0.0)
    step = next_step(route_lines(("ring_s", "ring_e", "ring_n"), painted_track()), start[0], start[1])
    expect = line.point_at(0.20)
    end = line.point_at(line.length_m)

    assert step is not None
    assert math.dist((step.x, step.y), (expect[0], expect[1])) < 1e-6
    assert math.dist((step.x, step.y), (end[0], end[1])) > 0.10
    assert abs(step.yaw - expect[2]) < 1e-6


def test_a_step_near_the_end_of_ring_s_continues_on_ring_e():
    south = painted_track().line("ring_s")
    east = painted_track().line("ring_e")
    pose = south.point_at(0.30)
    step = next_step(route_lines(("ring_s", "ring_e"), painted_track()), pose[0], pose[1])
    onto = 0.30 + 0.20 - south.length_m
    expect = east.point_at(onto)
    far = east.point_at(east.length_m)

    assert step is not None
    assert math.dist((step.x, step.y), (expect[0], expect[1])) < 1e-4
    assert math.dist((step.x, step.y), (far[0], far[1])) > 0.15


def test_a_finished_lap_is_the_end_and_a_fresh_lap_is_the_start():
    close = painted_track().line("ring_w").point_at(painted_track().line("ring_w").length_m)
    lines = route_lines(RING, painted_track())
    started = next_step(lines, close[0], close[1], along_m=0.0)
    finished = next_step(lines, close[0], close[1], along_m=1.5)

    assert started is not None and started.s_m == pytest.approx(STEP_M)
    assert finished is None


def test_the_lane_step_sits_outside_the_device_goal_ball():
    """RPP does not drive to a point it already counts as arrived."""
    params = ROOT / "middleware/core/navigation/params/nav2_params.yaml"
    data = yaml.safe_load(params.read_text(encoding="utf-8"))
    tolerance = data["controller_server"]["ros__parameters"]["general_goal_checker"][
        "xy_goal_tolerance"]
    assert STEP_M > tolerance


def test_the_ring_centre_and_the_route_end_do_not_dispatch():
    centre = (-0.3357, 0.0011)
    with pytest.raises(LaneRouteError, match="ROUTE_OFF_LANE"):
        next_step(route_lines(RING, painted_track()), centre[0], centre[1])
    end = painted_track().line("ring_s").point_at(painted_track().line("ring_s").length_m)
    assert next_step(route_lines(("ring_s",), painted_track()), end[0], end[1]) is None


def test_a_localized_map_pose_sends_only_the_short_point():
    line = painted_track().line("ring_s")
    start = line.point_at(0.0)
    client, robot = _client(_localized(start[0], start[1]))

    response = client.post("/api/fleet/robots/rosy_60/route", json={"edges": ["ring_s", "ring_e"]})

    assert response.status_code == 200, response.text
    goals = _goals(robot)
    assert len(goals) == 1
    expect = line.point_at(0.20)
    assert math.dist((goals[0][1], goals[0][2]), (expect[0], expect[1])) < 1e-6
    assert math.dist((response.json()["goal"]["x"], response.json()["goal"]["y"]),
                     (expect[0], expect[1])) < 1e-6
    assert set(GoalRequest.model_fields) == {"x", "y", "yaw"}


@pytest.mark.parametrize("state", [
    {"robot_id": "rosy_60", "pose": {"x": -0.5216, "y": -0.1682, "yaw": 0.0}},
    _localized(-0.5216, -0.1682, frame="odom"),
])
def test_legacy_and_odom_poses_do_not_call_core(state):
    client, robot = _client(state)

    response = client.post("/api/fleet/robots/rosy_60/route", json={"edges": list(RING)})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ROUTE_POSE_UNTRUSTED"
    assert _goals(robot) == []


def test_following_the_ring_to_its_close_does_not_start_another_lap():
    west = painted_track().line("ring_w")
    before = west.point_at(west.length_m - 0.15)
    close = west.point_at(west.length_m)
    client, robot = _client(_localized(before[0], before[1]))

    moving = client.post("/api/fleet/robots/rosy_60/route", json={"edges": list(RING)})
    robot._state["pose"]["x"] = close[0]
    robot._state["pose"]["y"] = close[1]
    done = client.post("/api/fleet/robots/rosy_60/route", json={"edges": list(RING)})

    assert moving.status_code == 200, moving.text
    assert moving.json()["goal"] is not None
    assert done.status_code == 200, done.text
    assert done.json()["reason"] == "ROUTE_COMPLETE"
    assert done.json()["goal"] is None
    assert len(_goals(robot)) == 1


def test_off_lane_and_finished_routes_do_not_call_core():
    client, robot = _client(_localized(-0.3357, 0.0011))
    off = client.post("/api/fleet/robots/rosy_60/route", json={"edges": list(RING)})
    end = painted_track().line("ring_s").point_at(painted_track().line("ring_s").length_m)
    done_client, done_robot = _client(_localized(end[0], end[1]))
    done = done_client.post("/api/fleet/robots/rosy_60/route", json={"edges": ["ring_s"]})

    assert off.status_code == 409
    assert off.json()["detail"]["code"] == "ROUTE_OFF_LANE"
    assert done.status_code == 200
    assert done.json()["reason"] == "ROUTE_COMPLETE"
    assert done.json()["goal"] is None
    assert _goals(robot) == []
    assert _goals(done_robot) == []


def test_a_broken_route_is_rejected_before_a_goal():
    line = painted_track().line("ring_s")
    start = line.point_at(0.0)
    client, robot = _client(_localized(start[0], start[1]))

    unknown = client.post("/api/fleet/robots/rosy_60/route", json={"edges": ["nope"]})
    broken = client.post("/api/fleet/robots/rosy_60/route",
                         json={"edges": ["ring_s", "ring_w"]})
    extra = client.post("/api/fleet/robots/rosy_60/route",
                        json={"edges": ["ring_s"], "x": 1})

    assert unknown.status_code == 400
    assert unknown.json()["detail"]["code"] == "ROUTE_UNKNOWN_EDGE"
    assert broken.status_code == 400
    assert broken.json()["detail"]["code"] == "ROUTE_DISCONTINUOUS"
    assert extra.status_code == 422
    assert _goals(robot) == []


def test_durable_task_records_the_short_point(tmp_path):
    line = painted_track().line("ring_s")
    start = line.point_at(0.0)
    robot = FakeRobot("rosy_60", state=_localized(start[0], start[1]))
    console = FleetConsole(
        [RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")], [robot])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"})
    client = TestClient(create_app(
        console, task_service=tasks, site_maps=_site_maps(),
        site_users={sha256(b"operator-token").hexdigest():
                    {"principal_id": "bob", "role": "operator"}},
    ))
    headers = {"Authorization": "Bearer operator-token"}

    missing = client.post("/api/fleet/robots/rosy_60/route",
                          json={"edges": ["ring_s"]}, headers=headers)
    sent = client.post("/api/fleet/robots/rosy_60/route", json={"edges": ["ring_s"]},
                       headers={**headers, "Idempotency-Key": "ring-1"})

    expect = line.point_at(0.20)
    assert missing.status_code == 400
    assert missing.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert sent.status_code == 200, sent.text
    stored = sent.json()["task"]["request"]["goal"]
    assert math.dist((stored["x"], stored["y"]), (expect[0], expect[1])) < 1e-6
    assert _goals(robot) == [] or math.dist(
        (_goals(robot)[0][1], _goals(robot)[0][2]), (expect[0], expect[1])) < 1e-6


def test_route_contract_is_in_the_api_reference_and_goal_stays_a_point():
    reference = (ROOT / "docs/reference/ROSY API & Protocol Reference.md").read_text(encoding="utf-8")
    assert "**Version:** v1.197" in reference
    assert "`/api/fleet/robots/{robot_id}/route`" in reference
    assert "ROUTE_POSE_UNTRUSTED" in reference
    assert "D-463" in reference
