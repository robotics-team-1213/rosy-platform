"""End-to-end tests for Nav2 Fleet guidance, traffic holds, pause/resume, and multi-robot claims."""

from __future__ import annotations

import asyncio
import math
import time
from hashlib import sha256
from types import SimpleNamespace

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
from fleet.server.trip_nav2_route import NAV2_RETRIES, NAV2_RETRY_S
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


def test_http_pause_and_resume_with_guided_blocked_edges(tmp_path):
    clock = FakeClock()
    store = SiteMapStore(tmp_path / "site.sqlite", clock=clock)
    store.import_if_empty(_branch_map(), source="test")
    robot = RouteFakeRobot("rosy_42", modes=("lane", "free"))
    robot.power_health_value = fresh_power_health()
    robot._state["map_id"] = "site-branch"
    robot._state["pose"] = {"x": -0.7, "y": 0.0, "yaw": 0.0}
    robot._state["odom_pose"] = {"x": -0.7, "y": 0.0, "yaw": 0.0, "stamp": time.time()}
    console = FleetConsole([RobotEndpoint("rosy_42", "http://127.0.0.1:8081", "t")], [robot], clock=clock)
    users = {
        sha256(b"op-tok").hexdigest(): {"principal_id": "bob", "role": "operator"},
        sha256(b"vw-tok").hexdigest(): {"principal_id": "carol", "role": "viewer"},
    }
    app = create_app(
        console,
        task_service=FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids=["rosy_42"]),
        site_maps=store, site_users=users,
    )
    op = {"Authorization": "Bearer op-tok"}
    vw = {"Authorization": "Bearer vw-tok"}
    with TestClient(app) as client:
        assert client.post("/api/fleet/robots/rosy_42/map-pin", json={"x": -0.7, "y": 0.0, "yaw": 0.0},
                           headers=op).status_code == 200
        plan = client.post("/api/fleet/robots/rosy_42/trip",
                           json={"to": "D", "drive_mode": "nav2"}, headers=op).json()
        tid = plan["plan_id"]
        assert client.post(f"/api/fleet/trips/{tid}/start", headers=op).status_code == 200

        assert client.post(f"/api/fleet/trips/{tid}/pause", headers=vw).status_code == 403
        assert client.post(f"/api/fleet/trips/{tid}/resume", headers=op).status_code == 409

        runner = app.state.trip_runner
        run(runner.tick())
        assert len(robot.routes) == 1

        paused = client.post(f"/api/fleet/trips/{tid}/pause", json={"reason": "blocked_ahead"}, headers=op)
        assert paused.status_code == 200
        assert paused.json()["hold"]["reason"] == "fleet_hold" and robot._state["navigation"] == "CANCELED"

        # Holding across > stall_s keeps trip open without dispatching any route.
        clock.advance(25.0)
        run(runner.tick())
        assert runner.view(tid)["state"] == "running" and len(robot.routes) == 1

        # Refresh map pin so resume guided replan sees a fresh localized pose.
        robot._state["pose"] = {"x": -0.5, "y": 0.0, "yaw": 0.0}
        resumed = client.post(f"/api/fleet/trips/{tid}/resume", json={"blocked_edges": ["ab"]}, headers=op)
        assert resumed.status_code == 200, resumed.text
        data = resumed.json()
        assert data["hold"] is None and [s["edge_id"] for s in data["plan"]["segments"]] == ["ha", "ac", "cd"]
        assert data["detail"]["guided_blocked_edges"] == ["ab"]

        run(runner.tick())
        assert len(robot.routes) == 2


def test_nav2_autonomous_waits_on_transient_conflict_and_fails_closed_on_untrusted():
    robot = RouteFakeRobot("rosy_42")
    _clock, _console, store, graph, pose, _canceled, runner = _console_runner(robot, _south_loop_map())
    runner.autonomous_robots = frozenset({"rosy_42"})
    pose["v"] = MapPose(0.5, -0.23, math.pi, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-loop")
    ver = store.active()[0]
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=ver, start_pose=(0.5, -0.23, math.pi), goal="J_in", stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-cf", robot_id="rosy_42", principal_id="bob", map_version=ver,
                      request={"to": "J_in", "drive_mode": "nav2"}, result={"plan": plan})

    orig_route = runner._route
    reply_box = [{"accepted": False, "queued": False, "reason": "ROUTE_CONFLICT"}]

    async def route_fn(_rid, _pts):
        return reply_box[0]

    runner._route = route_fn
    run(runner.start("p-cf", "bob"))
    run(runner.tick())
    view = runner.view("p-cf")
    assert view["state"] == "running" and view["detail"]["goal_wait"] == "ROUTE_CONFLICT"
    assert runner._live["rosy_42"].active_route is None

    # Transient conflict clears -> dispatches successfully.
    runner._route = orig_route
    run(runner.tick())
    view = runner.view("p-cf")
    assert view["state"] == "running" and runner._live["rosy_42"].active_route is not None
    assert "goal_wait" not in view["detail"]

    # Non-transient LOCALIZATION_UNTRUSTED still fails closed as TRIP_GOAL_REFUSED.
    runner._live["rosy_42"].active_route = None
    runner._route = lambda _rid, _pts: asyncio.sleep(0, result={"accepted": False, "reason": "LOCALIZATION_UNTRUSTED"})
    run(runner.tick())
    fail_view = runner.view("p-cf")
    assert fail_view["state"] == "failed" and fail_view["reason"] == "TRIP_GOAL_REFUSED"
