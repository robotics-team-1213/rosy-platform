"""End-to-end tests for Nav2 Fleet guidance, traffic holds, pause/resume, and multi-robot claims."""

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone
from hashlib import sha256
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fakes import FakeClock, FakeRobot, fresh_power_health, run
from fleet.routing.execute import plan_body
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.trip_guard import install_trip_guard
from fleet.server.trip_nav2_route import NAV2_RETRIES, NAV2_RETRY_S, NAV2_TRANSIENT_RETRY_S
from fleet.server.trip_ports import TripConfig
from fleet.server.trip_runner import TripRunner
from fleet.site_map import SiteMap
from fleet.swarm.robots import RobotEndpoint
from rosy.world.state.projections.map_pose import MapPose
from test_trip_nav2_route import RouteFakeRobot, _console_runner, _south_loop_map
from test_trip_runner import BOTH, _setup, _ticks, fresh_battery


def _branch_map() -> SiteMap:
    """Diamond branching map: short upper branch A->B->D vs alternate lower branch A->C->D."""
    return SiteMap.model_validate({
        "map_id": "site-branch",
        "places": [
            {"id": "H", "name": "H", "x": -0.8, "y": 0.0, "kind": "stop", "yaw": 0.0},
            {"id": "A", "name": "A", "x": 0.0, "y": 0.0, "kind": "junction"},
            {"id": "B", "name": "B", "x": 1.0, "y": 0.05, "kind": "junction"},
            {"id": "C", "name": "C", "x": 1.0, "y": -0.9, "kind": "junction"},
            {"id": "D", "name": "D", "x": 2.0, "y": 0.0, "kind": "stop", "yaw": 0.0},
        ],
        "edges": [
            {"id": "ha", "from": "H", "to": "A", "direction": "one_way", "drive_mode": "lane",
             "width_m": 0.25, "speed_cap_mps": 0.15, "polyline": [[-0.8, 0.0], [0.0, 0.0]]},
            {"id": "ab", "from": "A", "to": "B", "direction": "one_way", "drive_mode": "lane",
             "width_m": 0.25, "speed_cap_mps": 0.15, "polyline": [[0.0, 0.0], [1.0, 0.05]]},
            {"id": "bd", "from": "B", "to": "D", "direction": "one_way", "drive_mode": "lane",
             "width_m": 0.25, "speed_cap_mps": 0.15, "polyline": [[1.0, 0.05], [2.0, 0.0]]},
            {"id": "ac", "from": "A", "to": "C", "direction": "one_way", "drive_mode": "lane",
             "width_m": 0.25, "speed_cap_mps": 0.15, "polyline": [[0.0, 0.0], [1.0, -0.9]]},
            {"id": "cd", "from": "C", "to": "D", "direction": "one_way", "drive_mode": "lane",
             "width_m": 0.25, "speed_cap_mps": 0.15, "polyline": [[1.0, -0.9], [2.0, 0.0]]},
        ],
    })


def _corridor_map() -> SiteMap:
    return SiteMap.model_validate({
        "map_id": "site-line",
        "places": [
            {"id": "P0", "name": "P0", "x": 0.0, "y": 0.0, "kind": "stop", "yaw": 0.0},
            {"id": "P1", "name": "P1", "x": 1.0, "y": 0.0, "kind": "junction"},
            {"id": "P2", "name": "P2", "x": 2.0, "y": 0.0, "kind": "junction"},
            {"id": "P3", "name": "P3", "x": 3.0, "y": 0.0, "kind": "stop", "yaw": 0.0},
        ],
        "edges": [
            {"id": eid, "from": u, "to": v, "direction": "one_way", "drive_mode": "lane",
             "width_m": 0.25, "speed_cap_mps": 0.15, "polyline": [[float(i), 0.0], [float(i + 1), 0.0]]}
            for i, (eid, u, v) in enumerate([("e01", "P0", "P1"), ("e12", "P1", "P2"), ("e23", "P2", "P3")])
        ],
    })


def test_nav2_traffic_hold_stops_before_refused_block_and_auto_resumes():
    robot = RouteFakeRobot("rosy_42")
    clock, _console, store, graph, pose, _canceled, runner = _console_runner(robot, _corridor_map())
    pose["v"] = MapPose(0.05, 0.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-line")
    ver = store.active()[0]
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=ver, start_pose=(0.05, 0.0, 0.0), goal="P3", stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-tr", robot_id="rosy_42", principal_id="bob", map_version=ver,
                      request={"to": "P3", "drive_mode": "nav2"}, result={"plan": plan})

    # Pre-pin rosy_99 standing on e23 so Fleet's TrafficService refuses e23 from tick 1.
    pinned_pose = MapPose(2.6, 0.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-line")
    runner.traffic._last_pose["rosy_99"] = (2.6, 0.0, 0.0)
    layout = runner.traffic._layout_for(store.active())
    runner.traffic._state.pinned["rosy_99"] = runner.traffic._under(layout, graph, (2.6, 0.0, 0.0))

    run(runner.start("p-tr", "bob"))
    live = runner._live["rosy_42"]
    live.traffic = {"waiting_for": ["rosy_99"], "refused_at_m": 2.0}
    run(runner.tick())

    # Route dispatched stops at P2 (end_index <= 1), well short of refused e23.
    assert len(robot.routes) == 1
    assert live.active_route["end_index"] < 2

    # Advance robot to the end of its allowed span; while refused_at_m holds, it pauses without stalling.
    end_idx = live.active_route["end_index"]
    end_arc = graph.arcs[f"{live.segments[end_idx]['edge_id']}:fwd"]
    ex, ey, eyaw = end_arc.point_at(end_arc.length_m - 0.02)
    pose["v"] = MapPose(ex, ey, eyaw, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-line")
    robot._state["navigation"] = "ARRIVED"
    runner.traffic._last_pose["rosy_99"] = (10.0, 10.0, 0.0)  # Off graph so traffic table clears if stepped
    # While block remains held in traffic table, robot stays running > stall_s without dispatching e23.
    for _ in range(5):
        clock.advance(5.0)
        pose["v"] = MapPose(ex, ey, eyaw, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-line")
        runner.traffic._state.pinned["rosy_99"] = runner.traffic._under(layout, graph, (2.6, 0.0, 0.0))
        live.traffic = {"waiting_for": ["rosy_99"], "refused_at_m": float(end_idx + 1)}
        run(runner._step(live))
        assert live.view["state"] == "running" and len(robot.routes) == 1

    # Once peer clears the block on the next period, onward e23 route is dispatched automatically.
    live.traffic = {"waiting_for": [], "refused_at_m": None}
    run(runner._step(live))
    assert len(robot.routes) == 2 and live.active_route["end_index"] == 2
    assert pinned_pose.state == "LOCALIZED"


def test_nav2_failed_reroutes_autonomously_around_blocked_edge_and_resets_after_progress():
    smap = _branch_map()
    runner, store, ports = _setup(smap, caps=BOTH)
    ports.map_id = "site-branch"
    runner.autonomous_robots = frozenset({"rosy_60"})
    graph = store.active()[2]
    sent_routes: list[list[dict]] = []
    robot_nav = {"navigation": "IDLE"}

    async def robot_state(_rid):
        return {
            "navigation": robot_nav["navigation"],
            "localization": {"state": "LOCALIZED", "pose_frame": "map"},
            "pose": {"x": ports.pose.x, "y": ports.pose.y, "yaw": ports.pose.yaw},
        }

    async def send_route(_rid, points):
        sent_routes.append(points)
        robot_nav["navigation"] = "NAVIGATING"
        return {"accepted": True}

    runner._robot_state = robot_state
    runner._route = send_route

    ports.at(graph.arcs["ha:fwd"], 0.1)
    ver = store.active()[0]
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=ver, start_pose=(ports.pose.x, ports.pose.y, ports.pose.yaw), goal="D", stop_offset=False,
    ), store.routing_config))
    assert [s["edge_id"] for s in plan["segments"]] == ["ha", "ab", "bd"]
    store.record_plan(plan_id="p-detour", robot_id="rosy_60", principal_id="bob", map_version=ver,
                      request={"to": "D", "drive_mode": "nav2"}, result={"plan": plan})

    run(runner.start("p-detour", "bob"))
    _ticks(runner, ports, n=1)
    assert len(sent_routes) == 1

    # Robot moves near end of ha -> Nav2 reports FAILED entering ab -> Fleet auto-reroutes via ac -> cd.
    ports.at(graph.arcs["ha:fwd"], 0.65)
    robot_nav["navigation"] = "FAILED"
    _ticks(runner, ports, n=1)
    view = runner.view("p-detour")
    assert view["state"] == "running" and view["hold"] is None
    assert [s["edge_id"] for s in view["plan"]["segments"]] == ["ha", "ac", "cd"]
    assert view["detail"]["nav2_problem"]["state"] == "rerouted"
    assert view["detail"]["nav2_problem"]["blocked_edges"] == ["ab"]

    # Next tick dispatches guided detour route; before moving stall_m, recovery memory is preserved.
    robot_nav["navigation"] = "IDLE"
    _ticks(runner, ports, n=1)
    assert len(sent_routes) == 2 and runner._live["rosy_60"].nav2_replans == 1

    # Once robot actually progresses >= stall_m (0.05 m) along the new route, recovery state clears.
    ports.at(graph.arcs["ac:fwd"], 0.15)
    _ticks(runner, ports, n=1)
    assert runner.view("p-detour")["detail"].get("nav2_problem") is None
    assert runner._live["rosy_60"].nav2_replans == 0


def test_nav2_failed_no_detour_retries_then_holds_until_resume():
    smap = _south_loop_map()
    runner, store, ports = _setup(smap, caps=BOTH)
    ports.map_id = "site-loop"
    runner.autonomous_robots = frozenset({"rosy_60"})
    graph = store.active()[2]
    sent_routes: list[list[dict]] = []
    robot_nav = {"navigation": "IDLE"}

    async def robot_state(_rid):
        return {
            "navigation": robot_nav["navigation"],
            "localization": {"state": "LOCALIZED", "pose_frame": "map"},
            "pose": {"x": ports.pose.x, "y": ports.pose.y, "yaw": ports.pose.yaw},
        }

    async def send_route(_rid, points):
        sent_routes.append(points)
        robot_nav["navigation"] = "NAVIGATING"
        return {"accepted": True}

    runner._robot_state = robot_state
    runner._route = send_route

    ports.at(graph.arcs["upper_east:fwd"], 0.05)
    ver = store.active()[0]
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=ver, start_pose=(ports.pose.x, ports.pose.y, ports.pose.yaw), goal="J_in", stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-nd", robot_id="rosy_60", principal_id="bob", map_version=ver,
                      request={"to": "J_in", "drive_mode": "nav2"}, result={"plan": plan})
    run(runner.start("p-nd", "bob"))
    _ticks(runner, ports, n=1)
    assert len(sent_routes) == 1

    # Bounded cooldown retries when no alternate path exists on single loop.
    for attempt in range(1, NAV2_RETRIES + 1):
        robot_nav["navigation"] = "FAILED"
        _ticks(runner, ports, n=1)
        view = runner.view("p-nd")
        assert view["detail"]["nav2_problem"]["state"] == "retry_wait"
        assert view["detail"]["nav2_problem"]["attempt"] == attempt
        ports.now += NAV2_RETRY_S - 1.0
        _ticks(runner, ports, n=1)
        assert len(sent_routes) == attempt  # still cooling down
        ports.now += 1.5
        _ticks(runner, ports, n=1)
        assert len(sent_routes) == attempt + 1  # retried cleanly

    # Exhausting retries enters nav2_problem hold (does NOT discard trip or stall across >20s).
    robot_nav["navigation"] = "FAILED"
    _ticks(runner, ports, n=1)
    view = runner.view("p-nd")
    assert view["state"] == "running" and view["hold"]["reason"] == "nav2_problem"
    assert view["detail"]["nav2_problem"]["state"] == "held"
    ports.now += 35.0
    _ticks(runner, ports, n=1)
    assert runner.view("p-nd")["state"] == "running" and len(sent_routes) == NAV2_RETRIES + 1

    # Operator/Fleet resume clears hold and dispatches again.
    resumed = run(runner.resume("p-nd", "bob"))
    assert resumed["hold"] is None and resumed["detail"].get("nav2_problem") is None
    robot_nav["navigation"] = "IDLE"
    _ticks(runner, ports, n=1)
    assert len(sent_routes) == NAV2_RETRIES + 2


@pytest.mark.parametrize("lost", [False, True])
def test_http_pause_and_resume_with_guided_blocked_edges(tmp_path, lost):
    clock = FakeClock()
    clock.now = time.time()
    store = SiteMapStore(tmp_path / "site.sqlite", clock=clock)
    store.import_if_empty(_branch_map(), source="test")
    robot = RouteFakeRobot("rosy_42", modes=("lane", "free"))
    robot.power_health_value = fresh_power_health()
    robot._state["map_id"] = "site-branch"
    robot._state["pose"] = {"x": -0.7, "y": 0.0, "yaw": 0.0}
    robot._state["odom_pose"] = {"x": -0.7, "y": 0.0, "yaw": 0.0, "stamp": clock.now}
    console = FleetConsole([RobotEndpoint("rosy_42", "http://127.0.0.1:8081", "t")], [robot], clock=clock)
    users = {
        sha256(b"op-tok").hexdigest(): {"principal_id": "bob", "role": "operator"},
        sha256(b"vw-tok").hexdigest(): {"principal_id": "carol", "role": "viewer"},
    }
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids=["rosy_42"])
    tasks.store.rearm_dispatch(expected_generation=tasks.store.dispatch_control()["generation"], actor_id="bob")
    app = create_app(
        console,
        task_service=tasks,
        site_maps=store, site_users=users,
    )
    app.state.trip_runner._clock = clock
    op = {"Authorization": "Bearer op-tok"}
    vw = {"Authorization": "Bearer vw-tok"}
    with TestClient(app) as client:
        pin = client.post("/api/fleet/robots/rosy_42/map-pin", json={"x": -0.7, "y": 0.0, "yaw": 0.0}, headers=op)
        assert pin.status_code == 200, pin.text
        plan_res = client.post("/api/fleet/robots/rosy_42/trip", json={"to": "D", "drive_mode": "nav2"}, headers=op)
        assert plan_res.status_code == 200, plan_res.text
        tid = plan_res.json()["plan_id"]
        start_res = client.post(f"/api/fleet/trips/{tid}/start", headers=op)
        assert start_res.status_code == 200, start_res.text

        assert client.post(f"/api/fleet/trips/{tid}/pause", headers=vw).status_code == 403
        assert client.post(f"/api/fleet/trips/{tid}/resume", headers=op).status_code == 409

        runner = app.state.trip_runner
        client.portal.call(runner.tick)
        assert len(robot.routes) == 1

        runner.halts._clock = clock
        cancel = runner._cancel_goal
        attempts = []

        async def controlled_cancel(rid):
            attempts.append(rid)
            if lost and len(attempts) == 1:
                raise OSError("lost cancel")
            return await cancel(rid)

        runner._cancel_goal = controlled_cancel
        camera_holds = []
        if lost:
            runner._live["rosy_42"].view["detail"]["camera_lane_fallback"] = {"phase": "starting", "index": 0}
            async def hold_camera(rid):
                camera_holds.append(rid)
                return {"mode": "OFF"}
            runner._junction.hold = hold_camera
        robot._state.update(mode="IDLE", goal=None, velocity={"linear": 0., "angular": 0.}, line_follow={"mode": "OFF"})

        def sample():
            stamp = datetime.fromtimestamp(clock.now - .01, timezone.utc).isoformat()
            robot._state["evidence"] = {"velocity": {"sampled_at": stamp, "evidence": "fresh"}}

        sample()
        paused = client.post(f"/api/fleet/trips/{tid}/pause", json={"reason": "blocked_ahead"}, headers=op)
        assert paused.status_code == 200, paused.text
        held = paused.json()["hold"]
        assert held["reason"] == "fleet_hold" and held["stop"]["confirmed"] is False
        assert runner._live["rosy_42"].active_route is not None
        assert store.trip(tid)["hold"]["stop"] == held["stop"]
        assert client.post(f"/api/fleet/trips/{tid}/pause", headers=op).json()["hold"]["at"] == held["at"]
        assert len(attempts) == 1
        assert camera_holds == (["rosy_42"] if lost else [])
        for payload in ({}, {"blocked_edges": ["ab"]}):
            refusal = client.post(f"/api/fleet/trips/{tid}/resume", headers=op, json=payload)
            assert refusal.status_code == 409 and "TRIP_PAUSE_STOP_UNCONFIRMED" in refusal.text

        clock.advance(25.)
        client.portal.call(runner.tick)
        assert len(robot.routes) == 1 and robot._state["navigation"] == "CANCELED"
        clock.advance(.1)
        sample()
        robot._state["velocity"]["linear"] = .05
        assert client.post(f"/api/fleet/trips/{tid}/resume", headers=op).status_code == 409
        robot._state["velocity"]["linear"] = 0.
        robot._state["goal"] = {"x": 1., "y": 2.}
        assert client.post(f"/api/fleet/trips/{tid}/resume", headers=op).status_code == 409
        clock.advance(.1)
        sample()
        robot._state["goal"] = None
        client.portal.call(runner.tick)
        assert runner.view(tid)["hold"]["stop"]["confirmed"] is True
        assert runner._live["rosy_42"].active_route is None

        resumed = client.post(f"/api/fleet/trips/{tid}/resume", json={"blocked_edges": ["ab"]}, headers=op)
        assert resumed.status_code == 200, resumed.text
        data = resumed.json()
        assert data["hold"] is None and [s["edge_id"] for s in data["plan"]["segments"]] == ["ha", "ac", "cd"]
        assert data["detail"]["guided_blocked_edges"] == ["ab"]
        assert "camera_lane_fallback" not in data["detail"]

        robot._state["navigation"] = "IDLE"
        client.portal.call(runner.tick)
        assert len(robot.routes) == 2


@pytest.mark.parametrize("reason", ["ROUTE_CONFLICT", "YIELDING", "LOCALIZATION_UNTRUSTED"])
def test_nav2_autonomous_backs_off_on_transient_refusal_and_fails_closed_on_untrusted(reason):
    robot = RouteFakeRobot("rosy_42")
    clock, _console, store, graph, pose, _canceled, runner = _console_runner(robot, _south_loop_map())
    runner.autonomous_robots = frozenset() if reason == "LOCALIZATION_UNTRUSTED" else frozenset({"rosy_42"})
    pose["v"] = MapPose(0.5, -0.23, math.pi, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-loop")
    ver = store.active()[0]
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=ver, start_pose=(0.5, -0.23, math.pi), goal="J_in", stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-cf", robot_id="rosy_42", principal_id="bob", map_version=ver,
                      request={"to": "J_in", "drive_mode": "nav2"}, result={"plan": plan})

    orig_route = runner._route
    attempts = []

    async def route_fn(_rid, pts):
        attempts.append(pts)
        return {"accepted": False, "queued": False, "reason": reason, "blocked_by": "rosy_45",
                "waiting_on": ["rosy_45"], "dispatch_attempted": False}

    runner._route = route_fn
    run(runner.start("p-cf", "bob"))
    run(runner.tick())
    view = runner.view("p-cf")
    assert view["state"] == "running" and view["detail"]["goal_wait"] == reason
    live = runner._live["rosy_42"]
    assert live.active_route is None
    assert live.nav2_retry_at == clock() + NAV2_TRANSIENT_RETRY_S
    assert view["detail"]["peer_wait"]["waiting_on"] == ["rosy_45"]

    clock.advance(0.5)
    run(runner.tick())
    assert len(attempts) == 1

    # Once the cooldown expires, the cleared route can be dispatched.
    clock.advance(runner.config.stall_s + NAV2_TRANSIENT_RETRY_S)
    live.progress_at = clock() - runner.config.stall_s - 1
    runner._route = orig_route
    run(runner.tick())
    view = runner.view("p-cf")
    assert view["state"] == "running" and runner._live["rosy_42"].active_route is not None
    assert "goal_wait" not in view["detail"]
    assert "peer_wait" not in view["detail"]
    assert view["detail"]["last_peer_wait"]["cleared_at"] >= view["detail"]["last_peer_wait"]["since"]
    assert live.nav2_retry_at == -math.inf

    # Non-transient LOCALIZATION_UNTRUSTED still fails closed as TRIP_GOAL_REFUSED.
    runner._live["rosy_42"].active_route = None
    runner._route = lambda _rid, _pts: asyncio.sleep(0, result={"accepted": False, "reason": "LOCALIZATION_UNTRUSTED"})
    run(runner.tick())
    fail_view = runner.view("p-cf")
    assert fail_view["state"] == "failed" and fail_view["reason"] == "TRIP_GOAL_REFUSED"


def test_multi_robot_nav2_claims_compare_in_site_frame_without_false_mismatch():
    r1 = RouteFakeRobot("rosy_42")
    r2 = RouteFakeRobot("rosy_46")
    r1._state = {**r1._state, "map_id": "occupancy:42", "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
                 "localization": {"state": "LOCALIZED", "pose_frame": "map"}}
    r2._state = {**r2._state, "map_id": "occupancy:46", "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
                 "localization": {"state": "LOCALIZED", "pose_frame": "map"}}
    console = FleetConsole([
        RobotEndpoint("rosy_42", "http://127.0.0.1:8081", "t"),
        RobotEndpoint("rosy_46", "http://127.0.0.1:8082", "t"),
    ], [r1, r2], clock=FakeClock())
    console.set_site_pose_providers(
        mover=lambda rid: ("world_261026", 0.0, 0.0, 0.0) if rid == "rosy_42" else ("world_261026", 0.0, 2.0, 0.0),
    )

    pts_far = [{"x": 0.0, "y": 0.0, "kind": "pass"}, {"x": 1.0, "y": 0.0, "kind": "stop", "yaw": 0.0}]
    assert run(console.route("rosy_42", pts_far))["accepted"] is True
    assert run(console.route("rosy_46", pts_far))["accepted"] is True  # y=0 vs y=2 in site frame

    # Crossing path in site frame triggers ROUTE_CONFLICT instead of false MAP_FRAME_MISMATCH.
    r2._state["navigation"] = "IDLE"
    pts_cross = [{"x": 0.0, "y": 0.0, "kind": "pass"}, {"x": 0.5, "y": -1.9, "kind": "stop", "yaw": 0.0}]
    conflict = run(console.route("rosy_46", pts_cross))
    assert conflict["accepted"] is False and conflict["reason"] == "ROUTE_CONFLICT"

    # Without site-frame pose proof, distinct frames still fail closed as MAP_FRAME_MISMATCH.
    console.set_site_pose_providers(mover=lambda rid: ("world_261026", 0.0, 0.0, 0.0) if rid == "rosy_42" else None)
    mismatch = run(console.route("rosy_46", pts_far))
    assert mismatch["accepted"] is False and mismatch["reason"] == "MAP_FRAME_MISMATCH"


def test_nav2_unconfirmed_problem_replan_holds_across_ticks():
    smap = _branch_map()
    runner, store, ports = _setup(smap, caps=BOTH)
    ports.map_id = "site-branch"
    runner.autonomous_robots = frozenset({"rosy_60"})
    graph = store.active()[2]
    sent_routes: list[list[dict]] = []
    robot_nav = {"navigation": "IDLE"}

    async def robot_state(_rid):
        return {"navigation": robot_nav["navigation"], "localization": {"state": "LOCALIZED", "pose_frame": "map"},
                "pose": {"x": ports.pose.x, "y": ports.pose.y, "yaw": ports.pose.yaw}}

    async def send_route(_rid, points):
        sent_routes.append(points)
        robot_nav["navigation"] = "NAVIGATING"
        return {"accepted": True}

    runner._robot_state, runner._route = robot_state, send_route
    ports.at(graph.arcs["ha:fwd"], 0.1)
    ver = store.active()[0]
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=ver, start_pose=(ports.pose.x, ports.pose.y, ports.pose.yaw), goal="D", stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-unconf", robot_id="rosy_60", principal_id="bob", map_version=ver,
                      request={"to": "D", "drive_mode": "nav2"}, result={"plan": plan})
    run(runner.start("p-unconf", "bob"))
    _ticks(runner, ports, n=1)
    assert len(sent_routes) == 1

    # Detour plan succeeds, but _ai_confirm refuses because robot capabilities became unavailable.
    runner._caps = lambda _rid: asyncio.sleep(0, result=None)
    ports.at(graph.arcs["ha:fwd"], 0.65)
    robot_nav["navigation"] = "FAILED"
    _ticks(runner, ports, n=1)
    view = runner.view("p-unconf")
    assert view["hold"]["reason"] == "replan" and view["hold"]["source"] == "nav2_problem"
    assert view["detail"]["nav2_problem"]["state"] == "held"

    robot_nav["navigation"] = "IDLE"
    ports.now += 35.0
    _ticks(runner, ports, n=3)
    held_view = runner.view("p-unconf")
    assert held_view["state"] == "running" and held_view["hold"]["source"] == "nav2_problem"
    assert len(sent_routes) == 1  # Wait held cleanly without re-sending the failed route.


def test_planned_stop_goal_clears_stale_site_claims(monkeypatch):
    from fleet.server import console_helpers
    from fleet.server.map_binding_store import MapBindingStore

    robot_id = "rosy_46"
    boot_id = "1ad31f2d-f4ac-41aa-9bc1-37cb77a16664"
    plan_id = "acc31f2d-f4ac-41aa-9bc1-37cb77a16664"
    operation = {"boot_id": boot_id, "run_id": "c17ca896-9ae1-495c-a936-b7c7db3953fc", "kind": "navigate",
                 "phase": "RUNNING", "correlation_id": "attempt"}
    approval = {"binding_id": "fit-1", "site_map_id": "cell", "site_map_version": 261,
                "robot_grid_id": "grid-A", "fit": {"yaw": 0, "tx": 0, "ty": 0, "residual_max_m": 0}}
    bindings = SimpleNamespace(active=lambda _rid: approval)
    bindings.matching_fit = lambda *args: MapBindingStore.matching_fit(bindings, *args)
    maps = SimpleNamespace(
        active=lambda: (261, SimpleNamespace(map_id="cell", edges=[SimpleNamespace(drive_mode="free", direction="two_way")],
                                             turn_bans=[], crosswalks=[]), SimpleNamespace(arcs={})),
        map_bindings=bindings,
    )

    async def state():
        return {"localization": {"state": "LOCALIZED", "pose_frame": "map"}, "map_id": "same-name",
                "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "map_grid_id": "grid-A", "trip_lease": None,
                "velocity": {"linear": 0.0, "angular": 0.0},
                "evidence": {"pose": {"evidence": "fresh"}, "velocity": {"evidence": "fresh"}}}

    async def get(path):
        return {"owner": {"boot_id": boot_id, "owner_generation": 9}} if path == "/api/v1/navigation/state" else {}

    async def navigation_plan(*_, **__kwargs):
        return {"plan_id": plan_id, "map_grid_id": "grid-A", "frame": "map", "points": [[0, 0], [0.5, 0.0]]}

    async def send(*_, **__options):
        return {"accepted": True, "operation": operation}

    monkeypatch.setattr(console_helpers, "require_capability", lambda *_: asyncio.sleep(0, result={}))
    client = SimpleNamespace(state=state, _get=get, navigation_plan=navigation_plan)
    console = SimpleNamespace(
        _named_stop_site_maps=maps, _client=lambda _: client, _clients={robot_id: client},
        clients=lambda: {robot_id: client}, robot_ids=[robot_id], _traffic_lock=asyncio.Lock(),
        _goal_busy=set(), _clearance_m=0.2, _clock=time.monotonic,
        _named_stop_traffic=SimpleNamespace(has_configured_controls=lambda: False),
        goal_leases=SimpleNamespace(stop_token=lambda _: 0, send=send, check_stop=lambda *_: None,
                                    pending={}, motion_epoch=0),
        _formation_members=lambda: (), _yielding={}, _seen={}, _goals={}, _queued={}, _claims={},
        _site_claims={robot_id: ("cell", [(0.0, 0.0), (1.0, 0.0)])},
        _goal_admission=SimpleNamespace(yield_hold=lambda _: None),
        _remember=lambda _: None, _verdict=lambda _: "TRUSTED", trip_refusal=lambda _: None,
    )
    reply = run(console_helpers._goal(console, robot_id, 0.5, 0.0, 0.0, task_id="t1", attempt_id="attempt",
                                      attempt_seq=1, lease_source=None,
                                      stop_binding={"site_map_id": "cell", "site_map_version": 261,
                                                    "binding_id": "fit-1", "map_grid_id": "grid-A"}))
    assert reply["accepted"] is True and robot_id not in console._site_claims
    assert console._claims[robot_id] == [(0, 0), (0.5, 0.0)]


@pytest.mark.parametrize("case", ["vacant", "old_core", "post_dispatch", "previous_route", "wrong_robot",
                                  "moving", "active_goal", "cancel_vacant", "cancel_moving", "old_twist", "skew", "new_owner", "new_wire", "wire_pending", "restart"])
def test_idle_peer_wait_pause_requires_post_cancel_standstill_and_same_owner(case):
    robot = RouteFakeRobot("rosy_42")
    clock, console, store, graph, pose, _canceled, runner = _console_runner(robot, _corridor_map())
    clock.now = time.time()
    rid, tid = "rosy_42", "peer-paused"
    pose["v"] = MapPose(.1, 0., 0., "LOCALIZED", "sighting", 0., .1, .1, "site-line")
    ver = store.active()[0]
    plan = plan_body(plan_trip(graph, PlanRequest(map_version=ver, start_pose=(.1, 0., 0.), goal="P3"), store.routing_config))
    store.record_plan(plan_id=tid, robot_id=rid, principal_id="bob", map_version=ver,
                      request={"to": "P3", "drive_mode": "nav2"}, result={"plan": plan})
    async def refuse(_rid, _points):
        return {"accepted": False, "queued": False, "reason": "LOCALIZATION_UNTRUSTED", "blocked_by": "peer",
                "waiting_on": ["peer"], "dispatch_attempted": case == "post_dispatch",
                "stage": "post_dispatch_peer_check" if case == "post_dispatch" else "pre_dispatch_peer_check",
                "cancel_confirmed": case == "post_dispatch", "command_robot_id": "other" if case == "wrong_robot" else rid}
    runner._route = refuse
    run(runner.start(tid, "bob"))
    run(runner.tick())
    live = runner._live[rid]
    assert live.view["detail"]["peer_wait"] and not robot.routes
    if case == "previous_route":
        live.view["detail"]["nav2_route"] = {"points": 3}
    leases = console.goal_leases
    if case == "wire_pending":
        leases.pending[rid] = 1
    owner = {"owner_run_id": None, "boot_id": "a2154d53-b016-4f96-ada0-22b191c9fb13",
             "owner_generation": 4, "transport_generation": 3, "mode_epoch": 1, "dock_owner_generation": 0}
    async def cancel(_rid):
        stamp = datetime.fromtimestamp(clock() + (1. if case == "skew" else 0), timezone.utc).isoformat()
        return {"navigation": "IDLE", "operation": None, "idle_observed_at": stamp,
                **({} if case == "old_core" else {"idle_owner": owner})}
    async def state(_rid):
        clock.advance(.1)
        stamp = datetime.fromtimestamp(clock.now - (1 if case == "old_twist" else .02), timezone.utc).isoformat()
        return {"robot_id": rid, "mode": "IDLE", "navigation": "IDLE", "line_follow": {"mode": "OFF"},
                **({"goal": {"x": 1.0}} if case == "active_goal" else {}),
                "velocity": {"linear": .1 if case in ("moving", "cancel_moving") else 0., "angular": 0.},
                "evidence": {"velocity": {"evidence": "fresh", "sampled_at": stamp}}}
    async def navigation(_rid):
        if case == "new_wire":
            with leases.motion_wire(rid, "POST", "/api/v1/navigation/goal", {}):
                pass
        return {"navigation": "IDLE", "idle_owner": owner | ({"owner_generation": 5} if case == "new_owner" else {})}
    runner._cancel_goal = runner.halts._cancel_goal = cancel
    runner.halts.read_stop_state = state
    runner.halts.read_navigation = navigation
    runner.halts.wire_epoch = leases.idle_wire_epoch
    if case in ("cancel_vacant", "cancel_moving"):  # a cancel with no dispatched goal needs the same idle proof
        canceled = run(runner.cancel(tid, "bob"))["detail"]
        assert canceled["stop_sent"] is (case == "cancel_vacant") and ("error" in canceled) is (case == "cancel_moving")
        if case == "cancel_vacant":
            assert canceled["pause_proof"]["basis"] == "pre_dispatch_idle"
        return
    paused = run(runner.pause(tid, "bob"))
    stop = paused["hold"]["stop"]
    assert not stop["cancel_ack"]
    if case == "restart":
        from fleet.server.trip_halts import pause_proof_args
        halted = run(runner.halts.halt_robot(rid, False, None, **pause_proof_args(paused)))
        assert halted["stop_sent"] and halted["pause_proof"]["basis"] == "pre_dispatch_idle"
    elif case == "vacant":
        assert stop["proof"]["basis"] == "pre_dispatch_idle"
        assert run(runner.resume(tid, "bob"))["hold"] is None
        clock.advance(NAV2_TRANSIENT_RETRY_S + .1)
        run(runner.tick())
        assert live.view["detail"]["peer_wait"] and not robot.routes
    else:
        from fleet.server.trip_runner import TripError
        with pytest.raises(TripError) as exc:
            run(runner.resume(tid, "bob"))
        assert exc.value.code == "TRIP_PAUSE_STOP_UNCONFIRMED"
        assert stop["confirmed"] is False and not robot.routes


def test_measured_stop_accepts_core_snapshot_without_goal_key_and_recovers_prior_stop(tmp_path):
    robot = RouteFakeRobot("rosy_42")
    clock, _console, store, graph, pose, _canceled, runner = _console_runner(robot, _south_loop_map())
    runner.halts.read_stop_state = lambda _rid: asyncio.sleep(0, result=robot._state)
    pose["v"] = MapPose(0.5, -0.23, math.pi, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-loop")
    ver = store.active()[0]
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=ver, start_pose=(0.5, -0.23, math.pi), goal="J_in", stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-goal-omit", robot_id="rosy_42", principal_id="bob", map_version=ver,
                      request={"to": "J_in", "drive_mode": "nav2"}, result={"plan": plan})
    run(runner.start("p-goal-omit", "bob"))
    run(runner.tick())
    robot._state.pop("goal", None)
    robot._state.update(mode="IDLE", navigation="IDLE", velocity={"linear": 0.005, "angular": -0.01},
                        line_follow={"mode": "OFF"})
    clock.advance(0.2)
    stamp = datetime.fromtimestamp(clock.now - 0.01, timezone.utc).isoformat()
    robot._state["evidence"] = {"velocity": {"sampled_at": stamp, "evidence": "fresh"}}
    paused = run(runner.pause("p-goal-omit", "bob"))
    assert paused["hold"]["stop"]["confirmed"] is False
    clock.advance(0.2)
    stamp = datetime.fromtimestamp(clock.now - 0.01, timezone.utc).isoformat()
    robot._state["evidence"] = {"velocity": {"sampled_at": stamp, "evidence": "fresh"}}
    run(runner.tick())
    paused = run(runner.pause("p-goal-omit", "bob"))
    assert paused["hold"]["stop"]["confirmed"] is True

    resumed = run(runner.resume("p-goal-omit", "bob"))
    assert resumed["hold"] is None

    # Closed trip with unconfirmed halt self-recovers on subsequent tick.
    live = runner._live["rosy_42"]
    live.view["state"] = "canceled"
    live.view["detail"]["stop_sent"] = False
    clock.advance(3.0)
    run(runner.tick())
    assert live.view["detail"]["stop_sent"] is True


@pytest.mark.parametrize("case", ["idle", "moving", "new_owner"])
def test_cancel_after_a_sent_leg_accepts_measured_idle_standstill(case):
    """11-27 rosy_45: a wait-place leg was sent (nav2_route), the trip then waited on a parked peer and was
    cancelled; CORE answered IDLE without an ack and every later start was refused prior_stop_unconfirmed."""
    robot = RouteFakeRobot("rosy_42")
    clock, console, store, graph, pose, _canceled, runner = _console_runner(robot, _corridor_map())
    clock.now = time.time()
    rid, tid = "rosy_42", "peer-canceled"
    pose["v"] = MapPose(.1, 0., 0., "LOCALIZED", "sighting", 0., .1, .1, "site-line")
    ver = store.active()[0]
    plan = plan_body(plan_trip(graph, PlanRequest(map_version=ver, start_pose=(.1, 0., 0.), goal="P3"), store.routing_config))
    store.record_plan(plan_id=tid, robot_id=rid, principal_id="bob", map_version=ver,
                      request={"to": "P3", "drive_mode": "nav2"}, result={"plan": plan})
    async def refuse(_rid, _points):
        return {"accepted": False, "queued": False, "reason": "YIELDING", "blocked_by": "peer",
                "waiting_on": ["peer"], "dispatch_attempted": False, "stage": "pre_dispatch_peer_check",
                "cancel_confirmed": False, "command_robot_id": rid}
    runner._route = refuse
    run(runner.start(tid, "bob"))
    run(runner.tick())
    live = runner._live[rid]
    live.view["detail"]["nav2_route"] = {"points": 3, "end_index": 1, "lap": None}  # the earlier leg
    leases = console.goal_leases
    owner = {"owner_run_id": None, "boot_id": "a2154d53-b016-4f96-ada0-22b191c9fb13",
             "owner_generation": 4, "transport_generation": 3, "mode_epoch": 1, "dock_owner_generation": 0}
    async def cancel(_rid):
        stamp = datetime.fromtimestamp(clock(), timezone.utc).isoformat()
        return {"navigation": "IDLE", "operation": None, "idle_observed_at": stamp, "idle_owner": owner}
    async def state(_rid):
        clock.advance(.1)
        stamp = datetime.fromtimestamp(clock.now - .02, timezone.utc).isoformat()
        return {"robot_id": rid, "mode": "IDLE", "navigation": "IDLE", "line_follow": {"mode": "OFF"},
                "velocity": {"linear": .1 if case == "moving" else 0., "angular": 0.},
                "evidence": {"velocity": {"evidence": "fresh", "sampled_at": stamp}}}
    async def navigation(_rid):
        return {"navigation": "IDLE", "idle_owner": owner | ({"owner_generation": 5} if case == "new_owner" else {})}
    runner._cancel_goal = runner.halts._cancel_goal = cancel
    runner.halts.read_stop_state = state
    runner.halts.read_navigation = navigation
    runner.halts.wire_epoch = leases.idle_wire_epoch
    canceled = run(runner.cancel(tid, "bob"))
    from fleet.server.trip_halts import halt_unconfirmed
    if case == "idle":
        assert canceled["detail"]["stop_sent"] is True and "error" not in canceled["detail"]
        assert canceled["detail"]["pause_proof"]["basis"] == "pre_dispatch_idle"
        assert not halt_unconfirmed(canceled["detail"])
    else:  # a moving robot or a changed owner is never taken as stopped
        assert canceled["detail"]["stop_sent"] is False and halt_unconfirmed(canceled["detail"])


@pytest.mark.parametrize("case", ["ARRIVED", "CANCELED", "FAILED", "moving", "wire_moved", "state_differs"])
def test_cancel_of_a_closed_trip_accepts_measured_standstill_after_an_ended_goal(case):
    """11-27 rosy_45: Nav2 ARRIVED just before the stop; the cancel receipt names ARRIVED (not IDLE), had no ack, and
    every later start was refused prior_stop_unconfirmed. Same proof as IDLE: fresh zero velocity after the cancel."""
    robot = RouteFakeRobot("rosy_42")
    clock, console, store, graph, pose, _canceled, runner = _console_runner(robot, _corridor_map())
    clock.now = time.time()
    rid, tid = "rosy_42", "peer-canceled-ended"
    pose["v"] = MapPose(.1, 0., 0., "LOCALIZED", "sighting", 0., .1, .1, "site-line")
    ver = store.active()[0]
    plan = plan_body(plan_trip(graph, PlanRequest(map_version=ver, start_pose=(.1, 0., 0.), goal="P3"), store.routing_config))
    store.record_plan(plan_id=tid, robot_id=rid, principal_id="bob", map_version=ver,
                      request={"to": "P3", "drive_mode": "nav2"}, result={"plan": plan})
    async def refuse(_rid, _points):
        return {"accepted": False, "queued": False, "reason": "YIELDING", "blocked_by": "peer",
                "waiting_on": ["peer"], "dispatch_attempted": False, "stage": "pre_dispatch_peer_check",
                "cancel_confirmed": False, "command_robot_id": rid}
    runner._route = refuse
    run(runner.start(tid, "bob"))
    run(runner.tick())
    live = runner._live[rid]
    live.view["detail"]["nav2_route"] = {"points": 3, "end_index": 1, "lap": None}
    ended = "ARRIVED" if case in ("moving", "wire_moved", "state_differs") else case
    wire = [runner.halts.idle_wire(rid) or console.goal_leases.idle_wire_epoch(rid)]
    async def cancel(_rid):
        return {"navigation": ended, "operation": None}
    async def state(_rid):
        clock.advance(.1)
        if case == "wire_moved":
            wire[0] += 1
        stamp = datetime.fromtimestamp(clock.now - .02, timezone.utc).isoformat()
        return {"robot_id": rid, "mode": "NAVIGATION", "navigation": "IDLE" if case == "state_differs" else ended,
                "line_follow": {"mode": "OFF"}, "velocity": {"linear": .1 if case == "moving" else 0., "angular": 0.},
                "evidence": {"velocity": {"evidence": "fresh", "sampled_at": stamp}}}
    runner._cancel_goal = runner.halts._cancel_goal = cancel
    runner.halts.read_stop_state = state
    runner.halts.wire_epoch = lambda _r: wire[0]
    canceled = run(runner.cancel(tid, "bob"))
    from fleet.server.trip_halts import halt_unconfirmed
    if case in ("ARRIVED", "CANCELED", "FAILED"):
        assert canceled["detail"]["stop_sent"] is True and "error" not in canceled["detail"]
        if case != "CANCELED":  # CORE's own CANCELED receipt already counts as an ack
            assert canceled["detail"]["pause_proof"]["basis"] == "ended_goal_standstill"
        assert not halt_unconfirmed(canceled["detail"])
    else:  # moving, a changed wire or a different navigation state is never taken as stopped
        assert canceled["detail"]["stop_sent"] is False and halt_unconfirmed(canceled["detail"])
