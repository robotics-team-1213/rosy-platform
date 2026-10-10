"""D-601: a Fleet trip start turns CORE's camera line on itself (A), refuses a dead line camera at
plan time (B) and checks the robot's start pose against its first lane (D)."""

from __future__ import annotations

import dataclasses
import math

import pytest

from fleet.routing.snap import PlanError, snap_start
from fleet.server.trip_admission import start_check
from fleet.server.trip_ports import TripConfig, TripError
from fleet.swarm.transport import RobotApiError
from test_trip_runner import LANE, _arc, _code, _plan, _setup, _ticks, run


def _turned(ports, deg, dx=0.0, dy=0.0):
    pose = ports.pose
    ports.pose = dataclasses.replace(pose, x=pose.x + dx, y=pose.y + dy, yaw=pose.yaw + math.radians(deg))


def test_a_start_turns_an_off_robots_camera_line_on_last_and_every_end_turns_it_off():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    ports.core.mode = "OFF"
    view = run(runner.start("p1", "bob"))
    assert ports.line_starts == ["rosy_60"] and ports.core.mode == "CAMERA_LINE"
    assert view["state"] == "started" and view["detail"]["line_follow_started"] is True
    _ticks(runner, ports)
    run(runner.cancel("p1", "bob"))
    assert ports.held == ["rosy_60"] and ports.core.mode == "OFF"


def test_a_a_robot_already_on_camera_line_is_not_switched_and_is_still_turned_off_at_the_end():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    view = run(runner.start("p1", "bob"))
    assert ports.line_starts == [] and "line_follow_started" not in view["detail"]
    run(runner.cancel("p1", "bob"))
    assert ports.core.mode == "OFF"  # D-494 9: every end stops the robot, however it was on before


def test_a_nothing_is_turned_on_when_a_start_check_refuses():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    ports.core.mode = "OFF"
    ports.caps = {}
    assert _code(runner.start("p1", "bob")) == "TRIP_ROBOT_CAPS_UNKNOWN"
    ports.caps = {"rosy_60": LANE}
    _turned(ports, 180)
    assert _code(runner.start("p1", "bob")) == "TRIP_START_HEADING_MISMATCH"
    assert ports.line_starts == [] and ports.core.mode == "OFF" and runner.view("p1") is None


def test_a_a_refused_camera_line_ends_the_trip_failed_and_stops_the_robot():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    ports.core.mode = "OFF"
    ports.line_start_error = RobotApiError("rosy_60", 409, "MODE_CONFLICT", "manual control is held")
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.code == "TRIP_LINE_FOLLOW_START_FAILED" and err.value.detail["error"] == "MODE_CONFLICT"
    view = runner.view("p1")
    assert view["state"] == "failed" and view["reason"] == "TRIP_LINE_FOLLOW_START_FAILED"
    assert ports.held == ["rosy_60"] and not runner.robot_busy("rosy_60")


def test_a_a_cancel_landing_while_the_mode_is_sent_stops_the_robot_again():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    ports.core.mode = "OFF"
    real = ports.start_camera_line

    async def slow(robot_id):
        await runner.cancel("p1", "eve")  # the operator's stop lands before CORE's answer
        return await real(robot_id)

    ports.start_camera_line = slow
    view = run(runner.start("p1", "bob"))
    assert view["state"] == "canceled" and ports.held == ["rosy_60", "rosy_60"] and ports.core.mode == "OFF"


def test_a_a_lap_still_needs_the_camera_line_on():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    ports.core.mode = "OFF"
    segments = store.plan("p1")["result"]["plan"]["segments"]
    assert _code(runner._pose_checks("rosy_60", store.active()[2], segments)) == "TRIP_LINE_FOLLOW_NOT_ACTIVE"


def test_d_the_start_refuses_a_robot_facing_away_from_or_off_its_first_lane():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    base = ports.pose
    _turned(ports, 178)
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.code == "TRIP_START_HEADING_MISMATCH" and abs(err.value.detail["heading_err_deg"]) == 178.0
    ports.pose = base
    _turned(ports, 25)
    assert _code(runner.start("p1", "bob")) == "TRIP_START_HEADING_MISMATCH"
    width = _arc(store, "ring_s:fwd").width_m
    ports.pose = base
    tangent = base.yaw
    _turned(ports, 0, dx=-math.sin(tangent) * (width / 2 + 0.05), dy=math.cos(tangent) * (width / 2 + 0.05))
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.code == "TRIP_START_OFF_LANE" and err.value.detail["off_lane_m"] == pytest.approx(0.05, abs=0.01)
    ports.pose = base
    _turned(ports, 15)
    assert run(runner.start("p1", "bob"))["state"] == "started"


def test_d_start_check_is_pure():
    _runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    graph = store.active()[2]
    segments = store.plan("p1")["result"]["plan"]["segments"]
    x, y, yaw = _arc(store, "ring_s:fwd").point_at(0.1)
    assert start_check(graph, segments, x, y, yaw, 20.0)["code"] is None
    row = start_check(graph, segments, x, y, yaw + math.pi, 20.0)
    assert row["code"] == "TRIP_START_HEADING_MISMATCH" and abs(row["heading_err_deg"]) == 180.0
    assert start_check(graph, segments, x, y, None, 20.0)["code"] == "TRIP_START_HEADING_MISMATCH"
    assert start_check(graph, [], x, y, yaw, 20.0) == {"code": None}
    with pytest.raises(ValueError):
        TripConfig(start_heading_tol_deg=120.0)


def test_d_the_planner_refusal_carries_the_heading_error_and_the_distance_off():
    _runner, store, ports = _setup()
    graph = store.active()[2]
    x, y, yaw = _arc(store, "ring_s:fwd").point_at(0.1)
    with pytest.raises(PlanError) as err:
        snap_start(graph, x, y, yaw + math.pi, store.routing_config)
    assert err.value.code == "TRIP_HEADING_CONFLICT" and abs(err.value.detail["heading_err_deg"]) > store.routing_config.heading_tol_deg
    with pytest.raises(PlanError) as err:
        snap_start(graph, 50.0, 50.0, yaw, store.routing_config)
    assert err.value.code == "TRIP_START_OFF_MAP" and err.value.detail["off_lane_m"] > 10


def test_b_camera_check_refuses_a_dead_or_unreadable_line_camera():
    runner, _store, ports = _setup()
    run(runner.camera_check("rosy_60"))
    ports.camera = {"available": False, "stale": True, "age_ms": 9000}
    with pytest.raises(TripError) as err:
        run(runner.camera_check("rosy_60"))
    assert err.value.code == "TRIP_LANE_CAMERA_UNAVAILABLE" and err.value.detail == {"stale": True, "age_ms": 9000}

    async def down(robot_id):
        raise RobotApiError("rosy_60", 404, "NOT_FOUND", "no vision route")

    ports.front_camera = down
    assert _code(runner.camera_check("rosy_60")) == "TRIP_LANE_CAMERA_UNAVAILABLE"


def test_b_d_the_plan_route_refuses_a_dead_line_camera_and_shows_the_start_check(tmp_path):
    from test_site_map_trip import OPERATOR, _app, _on_ring_s

    client, _tasks, store, robot = _app(tmp_path)
    robot._state = _on_ring_s(store)
    plan = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR)
    assert plan.status_code == 200 and plan.json()["start_check"]["code"] is None
    robot._state["pose"]["yaw"] += math.radians(35)  # inside the planner's 60 deg, outside the start's 20
    check = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()["start_check"]
    assert check["code"] == "TRIP_START_HEADING_MISMATCH" and check["heading_err_deg"] == pytest.approx(35, abs=0.5)
    robot._state["pose"]["yaw"] += math.radians(145)
    wrong = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()["detail"]
    assert wrong["code"] == "TRIP_HEADING_CONFLICT" and abs(wrong["detail"]["heading_err_deg"]) > 60
    robot._state = _on_ring_s(store)
    robot.front_status_value = {"available": False, "stale": True, "age_ms": 12000}
    dead = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR)
    assert dead.status_code == 422 and dead.json()["detail"]["code"] == "TRIP_LANE_CAMERA_UNAVAILABLE"
    assert store.plans()[0]["result"]["error"] == "TRIP_LANE_CAMERA_UNAVAILABLE"


def test_a_a_free_first_segment_is_never_switched_to_camera_line():
    """Review HIGH 1: only a trip that starts on a lane turns the camera line on."""
    from test_trip_runner import BOTH, _map
    site = _map(("A", 0, 0), ("B", 1, 0), ("C", 2, 0),
                edges=[("ab", "A", "B", [[0, 0], [1, 0]], "free"), ("bc", "B", "C", [[1, 0], [2, 0]], "lane")])
    runner, store, ports = _setup(site, caps=BOTH)
    _plan(store, ports, "ab:fwd", 0.2, "C")
    ports.core.mode = "OFF"
    assert _code(runner.start("p1", "bob")) == "TRIP_LINE_FOLLOW_NOT_ACTIVE" and ports.line_starts == []


def test_a_a_timed_out_mode_put_is_stopped_twice():
    """Review M: CORE may still turn the line on after Fleet gave up and sent OFF."""
    runner, store, ports = _setup(port_timeout_s=0.01)
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    ports.core.mode = "OFF"
    ports.line_start_error = TimeoutError()
    assert _code(runner.start("p1", "bob")) == "TRIP_LINE_FOLLOW_START_FAILED"
    assert ports.held == ["rosy_60", "rosy_60"] and runner.view("p1")["state"] == "failed"


def test_b_the_camera_check_can_be_turned_off_for_sim():
    runner, _store, ports = _setup(lane_camera_check=False)
    ports.camera = {"available": False}
    run(runner.camera_check("rosy_60"))
    with pytest.raises(ValueError):
        TripConfig(lane_camera_check=1)


def test_d604_the_capability_line_camera_answers_the_check_without_a_call():
    from fleet.server.console_view import TripCaps
    runner, _store, ports = _setup()
    calls = []

    async def counted(robot_id):
        calls.append(robot_id)
        return {"available": True}

    ports.front_camera = counted
    live = TripCaps("pinky_pro", frozenset({"lane"}), 0.1,
                    line_camera={"available": True, "age_ms": 40, "source": "DEVICE"})
    run(runner.camera_check("rosy_60", live))
    for camera, stale in (({"available": False, "age_ms": 9000, "source": "DEVICE"}, True),
                          ({"available": False, "age_ms": None, "source": "NONE"}, False)):
        with pytest.raises(TripError) as err:
            run(runner.camera_check("rosy_60", dataclasses.replace(live, line_camera=camera)))
        assert err.value.code == "TRIP_LANE_CAMERA_UNAVAILABLE"
        assert err.value.detail == {"stale": stale, "age_ms": camera["age_ms"], "source": camera["source"]}
    assert calls == []                                   # no robot call while the caps carry it
    run(runner.camera_check("rosy_60", dataclasses.replace(live, line_camera=None)))  # older CORE
    run(runner.camera_check("rosy_60"))
    assert calls == ["rosy_60", "rosy_60"]               # falls back to front/status


def test_d604_the_plan_route_reads_the_line_camera_from_capabilities(tmp_path):
    from test_site_map_trip import OPERATOR, _app, _on_ring_s
    from test_trip_caps import _caps, _robot_caps
    from fleet.server.console_view import trip_caps

    caps = _caps(junction_turn=True)
    caps["line_follow"] = {"camera": {"available": False, "age_ms": None, "source": "NONE"}}
    assert trip_caps(caps).line_camera == caps["line_follow"]["camera"]
    assert trip_caps(_caps()).line_camera is None and trip_caps({**_caps(), "line_follow": 1}).line_camera is None
    client, _tasks, store, robot = _app(tmp_path)
    robot._state = _on_ring_s(store)
    robot.front_status_value = {"available": True}   # front/status says live, capabilities say dead
    _robot_caps(robot, caps)
    dead = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR)
    assert dead.status_code == 422 and dead.json()["detail"]["code"] == "TRIP_LANE_CAMERA_UNAVAILABLE"
    assert dead.json()["detail"]["detail"]["source"] == "NONE"
