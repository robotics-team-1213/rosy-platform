"""Tests for productized continuous road-following Nav2 repeat trips (POST /navigation/route)."""

from __future__ import annotations

import asyncio
import math
import time
from hashlib import sha256
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fakes import FakeClock, FakeRobot, fresh_power_health, run
from fleet.hub.hub import HubError
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.trip_guard import install_trip_guard
from fleet.server.trip_nav2_route import sample_nav2_route
from fleet.server.trip_ports import TripConfig
from fleet.server.trip_runner import TripError, TripRunner
from fleet.site_map import SiteMap
from fleet.swarm.navigation_transport import NavigationTransport
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError
from rosy.world.state.projections.map_pose import MapPose
from test_trip_runner import BOTH, LANE, OPERATOR, _setup, _ticks, fresh_battery


class RouteFakeRobot(FakeRobot):
    def __init__(self, robot_id: str, *, modes=("lane", "free"), lease: bool = True) -> None:
        super().__init__(robot_id)
        self.modes = list(modes)
        self.lease = lease
        self.routes: list[tuple] = []
        self.route_grids: list[str | None] = []
        self.bound_route_supported = False
        self.renewals: list[tuple] = []
        self.active_cid: str | None = None
        self._state = {
            **self._state,
            "navigation": "ARRIVED",
            "capabilities": {"navigation": {"goal_navigation": True}},
        }

    async def capabilities(self) -> dict:
        return {
            "navigation": {"goal_navigation": True, "bound_route": self.bound_route_supported},
            "controls": {
                "schema": "rosy.controls/1",
                "items": [{
                    "id": "base", "kind": "base_velocity", "robot_kind": "pinky_pro",
                    "drive_modes": self.modes, "trip_max_linear": 0.12,
                    "goal_lease": self.lease, "trip_lease": True,
                }],
            },
        }

    async def navigation_route(self, points, *, correlation_id=None, lease_ttl_s=None, **kwargs) -> dict:
        self._record("navigation_route", points, correlation_id, lease_ttl_s)
        self.routes.append((points, correlation_id, lease_ttl_s))
        self.route_grids.append(kwargs.get("expected_map_grid_id"))
        self.active_cid = correlation_id
        self._state["navigation"] = "NAVIGATING"
        return {"accepted": True}

    async def navigation_goal_lease(self, correlation_id, ttl_s) -> dict:
        self.renewals.append((correlation_id, ttl_s))
        if correlation_id != self.active_cid:
            raise RobotApiError(self.robot_id, 409, "GOAL_LEASE_NOT_ACTIVE", "not active")
        return {"renewed": True}

    async def navigation_cancel(self) -> dict:
        self._state["navigation"] = "CANCELED"
        return await super().navigation_cancel()


class DummyTransport(NavigationTransport):
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict | None]] = []

    async def _post(self, path: str, body: dict | None = None) -> dict:
        self.posts.append((path, body))
        return {"accepted": True}


def _south_loop_map() -> SiteMap:
    """Closed one-way lane loop mirroring world_261026 (S3/S4/S5 kind='stop' + J_in/J_out U-turns)."""
    return SiteMap.model_validate({
        "map_id": "site-loop",
        "places": [
            {"id": "S3", "name": "S3", "x": 0.75, "y": -0.21, "kind": "stop", "yaw": math.pi},
            {"id": "J_in", "name": "J_in", "x": 0.32, "y": -0.25, "kind": "junction"},
            {"id": "J_out", "name": "J_out", "x": -0.68, "y": -0.25, "kind": "junction"},
            {"id": "S4", "name": "S4", "x": 0.17, "y": -0.48, "kind": "stop", "yaw": 0.0},
            {"id": "S5", "name": "S5", "x": 0.91, "y": -0.48, "kind": "stop", "yaw": 0.0},
        ],
        "edges": [
            {"id": "upper_east", "from": "S3", "to": "J_in", "direction": "one_way",
             "drive_mode": "lane", "width_m": 0.2, "speed_cap_mps": 0.15,
             "polyline": [[0.75, -0.21], [0.53, -0.23], [0.32, -0.25]]},
            {"id": "upper_west", "from": "J_in", "to": "J_out", "direction": "one_way",
             "drive_mode": "lane", "width_m": 0.2, "speed_cap_mps": 0.15,
             "polyline": [[0.32, -0.25], [-0.18, -0.25], [-0.68, -0.25]]},
            {"id": "loop_left", "from": "J_out", "to": "S4", "direction": "one_way",
             "drive_mode": "lane", "width_m": 0.2, "speed_cap_mps": 0.15,
             "polyline": [[-0.68, -0.25], [-0.82, -0.36], [-0.68, -0.48], [0.17, -0.48]]},
            {"id": "lower_east", "from": "S4", "to": "S5", "direction": "one_way",
             "drive_mode": "lane", "width_m": 0.2, "speed_cap_mps": 0.15,
             "polyline": [[0.17, -0.48], [0.54, -0.48], [0.91, -0.48]]},
            {"id": "loop_right", "from": "S5", "to": "S3", "direction": "one_way",
             "drive_mode": "lane", "width_m": 0.2, "speed_cap_mps": 0.15,
             "polyline": [[0.91, -0.48], [1.05, -0.35], [0.91, -0.21], [0.75, -0.21]]},
        ],
    })


def test_navigation_transport_posts_and_validates_route():
    t = DummyTransport()
    pts = [{"x": 0.1, "y": 0.2, "kind": "pass"}, {"x": 0.5, "y": 0.2, "kind": "stop", "yaw": 0.0}]
    reply = run(t.navigation_route(pts, correlation_id="cid-1", lease_ttl_s=4.0))
    assert reply == {"accepted": True}
    assert t.posts == [("/api/v1/navigation/route", {"points": pts, "correlation_id": "cid-1", "lease_ttl_s": 4.0})]
    run(t.navigation_route(pts, expected_map_grid_id="occupancy:abcd"))
    assert t.posts[-1] == ("/api/v1/navigation/bound-route", {"points": pts, "expected_map_grid_id": "occupancy:abcd"})
    with pytest.raises(ValueError, match="ROUTE_POINTS_REQUIRED"):
        run(t.navigation_route([]))
    with pytest.raises(ValueError, match="NATIVE_OWNER_EPOCH_PAIR_REQUIRED"):
        run(t.navigation_route(pts, expected_boot_id="boot-1"))


def test_console_route_goal_lease_and_trip_guard():
    robot = RouteFakeRobot("rosy_42")
    clock = FakeClock()
    endpoints = [RobotEndpoint(robot_id="rosy_42", base_url="http://127.0.0.1:8080", token="t")]
    console = FleetConsole(endpoints, [robot], clock=clock, goal_lease_ttl_s=4.0)
    store = SiteMapStore(clock=clock)
    store.import_if_empty(_south_loop_map(), source="test")

    ports = SimpleNamespace(
        caps_for=lambda _id: asyncio.sleep(0, result=BOTH),
        arbitrated_pose=lambda _id: MapPose(0.5, -0.23, math.pi, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-loop"),
        state=lambda _id: robot.state(),
        junction_state=lambda _id: asyncio.sleep(0, result={}),
        hold=lambda _id: asyncio.sleep(0, result={"mode": "OFF"}),
        line_follow_mode=lambda _id: asyncio.sleep(0, result="OFF"),
        trip_lease=lambda *a, **kw: asyncio.sleep(0, result={"renewed": True}),
    )
    runner = TripRunner(
        store=store, routing_config=store.routing_config, caps=ports.caps_for, battery=fresh_power_health,
        poses=ports, junction=ports, goal=lambda *a, **kw: console.goal(*a, trip=True, **kw),
        route=lambda *a, **kw: console.route(*a, trip=True, **kw), cancel_goal=console.cancel, clock=clock,
    )
    install_trip_guard(console, runner, clock=clock)

    pts = [{"x": 0.4, "y": -0.24, "kind": "pass"}, {"x": 0.32, "y": -0.25, "kind": "stop", "yaw": math.pi}]
    reply = run(console.route("rosy_42", pts, trip=True))
    assert reply == {"accepted": True}
    assert len(robot.routes) == 1 and robot.routes[0][0] == pts
    assert robot.routes[0][2] == 4.0 and console.goal_leases["rosy_42"]["source"] == "trip"
    run(console.goal_leases.renew("trip", "rosy_42"))
    assert len(robot.renewals) == 1

    # Running trip blocks non-trip console route calls with TRIP_ROBOT_BUSY.
    runner._live["rosy_42"] = SimpleNamespace(open=True, view={"trip_id": "t1"})
    with pytest.raises(HubError) as err:
        run(console.route("rosy_42", pts))
    assert err.value.code == "TRIP_ROBOT_BUSY"
    run(console.cancel("rosy_42"))
    assert robot._state["navigation"] == "CANCELED"


def test_console_route_waits_for_untrusted_peer_before_motor_dispatch():
    r42 = RouteFakeRobot("rosy_42")
    r45 = RouteFakeRobot("rosy_45")
    r45._state["localization"] = {"state": "UNKNOWN", "pose_frame": "odom"}
    clock = FakeClock()
    console = FleetConsole([
        RobotEndpoint(robot_id="rosy_42", base_url="http://127.0.0.1:8080", token="t"),
        RobotEndpoint(robot_id="rosy_45", base_url="http://127.0.0.1:8081", token="t"),
    ], [r42, r45], clock=clock)
    pts = [{"x": 0.4, "y": -0.24, "kind": "pass"}, {"x": 0.32, "y": -0.25, "kind": "stop", "yaw": math.pi}]
    reply = run(console.route("rosy_42", pts))
    assert reply["accepted"] is False
    assert reply["queued"] is False
    assert reply["reason"] == "LOCALIZATION_UNTRUSTED"
    assert reply["command_robot_id"] == "rosy_42" and reply["waiting_on"] == ["rosy_45"]
    assert reply["cancel_confirmed"] is False and reply["dispatch_attempted"] is False
    assert r42.routes == []
    assert console._queued == {}


def test_sample_nav2_route_splits_closed_loop_and_keeps_open_path_single_stop():
    store = SiteMapStore()
    store.import_if_empty(_south_loop_map(), source="test")
    graph = store.active()[2]
    segs = [
        {"edge_id": "upper_east", "forward": True, "s_from": 0.0, "s_to": graph.arcs["upper_east:fwd"].length_m},
        {"edge_id": "upper_west", "forward": True, "s_from": 0.0, "s_to": graph.arcs["upper_west:fwd"].length_m},
        {"edge_id": "loop_left", "forward": True, "s_from": 0.0, "s_to": graph.arcs["loop_left:fwd"].length_m},
        {"edge_id": "lower_east", "forward": True, "s_from": 0.0, "s_to": graph.arcs["lower_east:fwd"].length_m},
        {"edge_id": "loop_right", "forward": True, "s_from": 0.0, "s_to": graph.arcs["loop_right:fwd"].length_m},
    ]
    closed = sample_nav2_route(graph, segs, 0, 0.0, 4)
    assert 10 <= len(closed) <= 64
    stops = [i for i, p in enumerate(closed) if p[3] == "stop"]
    assert len(stops) == 2 and stops[-1] == len(closed) - 1 and 0 < stops[0] < len(closed) - 1
    assert math.dist(closed[-1][:2], (0.75, -0.21)) < 1e-6

    open_path = sample_nav2_route(graph, segs, 0, 0.0, 1)
    assert all(p[3] == "pass" for p in open_path[:-1]) and open_path[-1][3] == "stop"
    assert math.dist(open_path[-1][:2], (-0.68, -0.25)) < 1e-6


@pytest.mark.parametrize(("binding_required", "loc_state", "refusal"), [
    (False, "LOCALIZED", None),
    (True, "LOCALIZED", "MAP_BINDING_REQUIRED"),
    (False, "CANDIDATES", "ROBOT_POSE_UNTRUSTED"),
])
def test_http_plan_nav2_allows_lane_loop_refuses_motor_and_convoy(tmp_path, binding_required, loc_state, refusal):
    clock = FakeClock()
    store = SiteMapStore(tmp_path / "site.sqlite", clock=clock)
    store.import_if_empty(_south_loop_map(), source="test")
    robot = RouteFakeRobot("rosy_42", modes=("lane", "free"))
    motor = RouteFakeRobot("rosy_45", modes=("lane",))
    for r in (robot, motor):
        r.power_health_value = fresh_power_health()
        r._state["odom_pose"] = {"x": 0.0, "y": 0.0, "yaw": 0.0, "stamp": time.time()}
    robot._state["localization"] = {"state": loc_state, "pose_frame": "map"}
    console = FleetConsole(
        [RobotEndpoint("rosy_42", "http://127.0.0.1:8081", "t"),
         RobotEndpoint("rosy_45", "http://127.0.0.1:8082", "t")],
        [robot, motor], clock=clock,
    )
    users = {sha256(b"op-tok").hexdigest(): {"principal_id": "bob", "role": "operator"}}
    app = create_app(
        console, task_service=FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids=["rosy_42", "rosy_45"]),
        site_maps=store, site_users=users, trip_config=TripConfig(map_binding_required=binding_required),
    )
    with TestClient(app) as client:
        # Anchor both robots on the south loop (rosy_42 33 deg off loop_left: past lane 20 deg tol, under 90 deg conflict).
        assert client.post("/api/fleet/robots/rosy_42/map-pin", json={"x": -0.68, "y": -0.25, "yaw": -1.9},
                           headers={"Authorization": "Bearer op-tok"}).status_code == 200
        assert client.post("/api/fleet/robots/rosy_45/map-pin", json={"x": 0.17, "y": -0.48, "yaw": 0.0},
                           headers={"Authorization": "Bearer op-tok"}).status_code == 200
        # Camera offline on free robot, yet nav2 plan succeeds and ignores start heading mismatch.
        robot.front_status_value = {"available": False, "stale": True, "age_ms": 9999}
        res = client.post("/api/fleet/robots/rosy_42/trip",
                          json={"to": "S3", "via": ["S4", "S5"], "repeat": True, "drive_mode": "nav2"},
                          headers={"Authorization": "Bearer op-tok"})
        if binding_required:
            assert res.status_code == 409, res.text
            assert res.json()["detail"] == {
                "code": "TRIP_POSE_UNTRUSTED", "detail": {"reason": "APPROVED_SLAM_POSE_REQUIRED"},
            }
            assert not robot.routes
            return
        assert res.status_code == 200, res.text
        plan = res.json()
        assert plan["start_check"]["code"] is None
        assert plan["nav2_preflight"] == {"code": refusal, "binding_required": binding_required,
                                             "binding_status": "MAP_BINDING_REQUIRED"}
        assert not robot.routes
        assert plan["segments"][-1]["s_to"] == pytest.approx(store.active()[2].arcs["loop_right:fwd"].length_m, abs=1e-4)

        # Motor-only robot (no "free" mode) cannot plan a nav2 trip.
        refused = client.post("/api/fleet/robots/rosy_45/trip",
                              json={"to": "S3", "via": ["S4", "S5"], "repeat": True, "drive_mode": "nav2"},
                              headers={"Authorization": "Bearer op-tok"})
        assert refused.status_code == 422 and refused.json()["detail"]["code"] == "TRIP_MODE_UNSUPPORTED"

        # Convoy is lane-only.
        bad = client.post("/api/fleet/robots/rosy_42/trip",
                          json={"to": "S3", "via": ["S4", "S5"], "repeat": True, "drive_mode": "nav2",
                                "convoy": {"leader": "rosy_45"}},
                          headers={"Authorization": "Bearer op-tok"})
        assert bad.status_code == 422


@pytest.mark.parametrize("case", ["accepted", "older_core", "changed_grid"])
def test_named_nav2_opt_in_uses_bound_slam_for_plan_start_progress_and_route(tmp_path, case):
    from datetime import datetime, timezone
    from fleet.localization.map_binding import Fit

    store = SiteMapStore(tmp_path / "site.sqlite")
    store.import_if_empty(_south_loop_map(), source="test")
    robot = RouteFakeRobot("rosy_42")
    robot.power_health_value = fresh_power_health()
    robot.bound_route_supported = case != "older_core"
    fit = Fit(math.pi / 2, .31, -.22, ())
    native_x, native_y = fit.inverse((.17, -.48))

    def read_core():
        stamp = time.time() - .02
        robot._state.update(
            map_id="native-slam", map_grid_id="occupancy:0123456789ab", pose_frame="map",
            localization={"state": "LOCALIZED", "pose_frame": "map"},
            pose={"x": native_x, "y": native_y, "yaw": -fit.yaw},
            odom_pose={"x": native_x, "y": native_y, "yaw": -fit.yaw, "stamp": stamp},
            evidence={"pose": {"evidence": "fresh", "received_at": datetime.fromtimestamp(stamp, timezone.utc).isoformat()}},
        )

    read_core()
    site = (store.active()[1].map_id, store.active()[0])
    pairs = [{"site": list(p), "robot": list(fit.inverse(p))} for p in [(-1., -.5), (1., -.5), (.9, .45)]]
    holdout = [{"site": [0., 0.], "robot": list(fit.inverse((0., 0.)))}]
    binding = store.map_bindings.approve("rosy_42", robot._state, site, pairs, holdout, "bob")
    console = FleetConsole([RobotEndpoint("rosy_42", "http://127.0.0.1:8081", "t")], [robot])
    users = {sha256(b"op-tok").hexdigest(): {"principal_id": "bob", "role": "operator"}}
    tasks = FleetTaskStore(tmp_path / "tasks.sqlite")
    app = create_app(console, site_maps=store, site_users=users,
                     task_service=FleetTaskService(tasks, robot_ids=["rosy_42"]))
    runner = app.state.trip_runner
    read_legacy_pose = []

    async def wrong_camera_pose(_robot_id):
        read_legacy_pose.append(True)
        return MapPose(.75, -.21, math.pi, "LOCALIZED", "sighting", 0., 0., anchor_age_s=0., map_id=site[0])

    runner.map_pose = wrong_camera_pose
    headers = {"Authorization": "Bearer op-tok"}
    body = {"to": "S4", "start_at": "S4", "via": ["S5", "S3"], "drive_mode": "nav2", "approved_slam_required": True}
    with TestClient(app) as client:
        tasks.rearm_dispatch(expected_generation=tasks.dispatch_control()["generation"], actor_id="bob")
        assert not runner.human_hold_fn()
        assert not runner.config.map_binding_required
        plan = client.post("/api/fleet/robots/rosy_42/trip", json=body, headers=headers)
        if case == "older_core":
            assert plan.status_code == 409 and plan.json()["detail"]["code"] == "NAV2_BOUND_ROUTE_UNSUPPORTED"
            assert not robot.routes and not read_legacy_pose
            return
        assert plan.status_code == 200, plan.text
        assert plan.json()["nav2_binding_id"] == binding["binding_id"]
        plan_id = plan.json()["plan_id"]
        read_core()
        started = client.post(f"/api/fleet/trips/{plan_id}/start", headers=headers)
        assert started.status_code == 200, started.text
        live = runner._live["rosy_42"]
        pose = client.portal.call(runner._progress_pose, live, "rosy_42")
        assert pose.source == "approved_slam" and (pose.x, pose.y) == pytest.approx((.17, -.48))
        if case == "changed_grid":
            prepare = console.goal_leases.prepare_send

            async def change_grid(*args):
                guard = await prepare(*args)
                robot._state["map_grid_id"] = "occupancy:0fedcba98765"
                return guard

            console.goal_leases.prepare_send = change_grid
        client.portal.call(runner.tick)
        if case == "changed_grid":
            stopped = runner.view(plan_id)
            assert stopped["state"] in {"failed", "stopped"}
            assert not robot.routes and not read_legacy_pose
            return
        assert robot.routes and robot.route_grids == ["occupancy:0123456789ab"]
        assert console._site_claims["rosy_42"][0] == site[0]
        first = robot.routes[0][0][0]
        assert fit.apply((first["x"], first["y"])) == pytest.approx((.17, -.48), abs=.15)
        assert not read_legacy_pose

        store.map_bindings.revoke("rosy_42", "bob")
        client.portal.call(runner.tick)
        assert runner.view(plan_id)["state"] == "stopped"
        assert any(call[0] == "navigation_cancel" for call in robot.calls)
        assert len(robot.routes) == 1 and not read_legacy_pose


def test_nav2_repeat_trip_rolls_across_multiple_laps_and_reanchors_robot_frame():
    """Lap 1 partial mid-loop -> Lap 2 -> Lap 3 seamless rollover without hold, transformed into SLAM frame."""
    smap = _south_loop_map()
    runner, store, ports = _setup(smap, caps=BOTH)
    ports.map_id = "site-loop"
    sent_routes: list[list[dict]] = []
    robot_nav = {"navigation": "IDLE"}
    turn, shift = math.pi / 2, (2.0, 3.0)
    c, s = math.cos(turn), math.sin(turn)

    def to_robot(x, y, yaw):
        return c * x - s * y + shift[0], s * x + c * y + shift[1], yaw + turn

    async def robot_state(_rid):
        rx, ry, ryaw = to_robot(ports.pose.x, ports.pose.y, ports.pose.yaw)
        return {
            "navigation": robot_nav["navigation"],
            "map_id": "occupancy:slam",
            "localization": {"state": "LOCALIZED", "pose_frame": "map"},
            "pose": {"x": rx, "y": ry, "yaw": ryaw},
        }

    async def send_route(robot_id, points):
        if robot_nav["navigation"] == "NAVIGATING":
            raise RobotApiError(robot_id, 409, "NAVIGATION_ACTIVE", "busy")
        sent_routes.append(points)
        robot_nav["navigation"] = "NAVIGATING"
        return {"accepted": True}

    runner._robot_state = robot_state
    runner._route = send_route

    # Plan starting mid-loop on loop_left just before S4 -> Lap 1 is [loop_left, lower_east, loop_right].
    graph = store.active()[2]
    left_arc = graph.arcs["loop_left:fwd"]
    ports.at(left_arc, left_arc.length_m - 0.15)
    body_req = {"to": "S3", "via": ["S4", "S5"], "repeat": True, "drive_mode": "nav2"}
    from fleet.routing.execute import plan_body
    from fleet.routing.trip import PlanRequest, plan_trip
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=store.active()[0], start_pose=(ports.pose.x, ports.pose.y, ports.pose.yaw),
        goal="S3", via=("S4", "S5"), stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-nav2", robot_id="rosy_60", principal_id="bob",
                      map_version=plan["map_version"], request=body_req, result={"plan": plan})

    # line_follow is OFF, camera is unavailable — Nav2 still starts and reports leg_mode == "free".
    ports.core.mode = "OFF"
    ports.camera = {"available": False}
    started = run(runner.start("p-nav2", "bob"))
    assert started["drive_mode"] == "free" and runner.leg_mode("rosy_60") == "free"
    assert ports.line_starts == []

    # Tick 1: dispatches Lap 1 route in robot SLAM frame with multiple pass points + 1 stop.
    _ticks(runner, ports, n=1)
    assert len(sent_routes) == 1
    assert all(p["kind"] == "pass" for p in sent_routes[0][:-1]) and sent_routes[0][-1]["kind"] == "stop"
    exp_s3 = to_robot(0.75, -0.21, math.pi)
    assert math.hypot(sent_routes[0][-1]["x"] - exp_s3[0], sent_routes[0][-1]["y"] - exp_s3[1]) < 1e-3

    # Robot approaches end of loop_right -> lap 2 planned seamlessly while route is still NAVIGATING!
    loop_right = graph.arcs["loop_right:fwd"]
    ports.at(loop_right, loop_right.length_m - 0.3)
    _ticks(runner, ports, n=1)
    view = runner.view("p-nav2")
    assert view["lap"] == 2 and view["hold"] is None and view["state"] == "running"
    assert len(sent_routes) == 1  # Not interrupted while NAVIGATING

    # First tick sees 409 NAVIGATION_ACTIVE -> retries cleanly on next tick once ARRIVED.
    ports.at(graph.arcs["upper_east:fwd"], 0.03)
    _ticks(runner, ports, n=1)
    assert len(sent_routes) == 1
    robot_nav["navigation"] = "ARRIVED"
    _ticks(runner, ports, n=1)
    assert len(sent_routes) == 2
    assert len(sent_routes[1]) >= 25  # full 5-edge canonical loop
    # Closed-loop route splits near midpoint with a stop+yaw so Nav2 cannot short-circuit on start==end.
    stops_lap2 = [p for p in sent_routes[1] if p["kind"] == "stop"]
    assert len(stops_lap2) == 2 and all(math.isfinite(p["yaw"]) for p in stops_lap2)

    # Advance through Lap 2 end -> Lap 3 wraps & trims earlier segments consistently!
    robot_nav["navigation"] = "NAVIGATING"
    for seg_name in ("upper_west:fwd", "loop_left:fwd", "lower_east:fwd"):
        arc = graph.arcs[seg_name]
        ports.at(arc, arc.length_m * 0.5)
        _ticks(runner, ports, n=1)
    ports.at(loop_right, loop_right.length_m - 0.25)
    _ticks(runner, ports, n=1)
    view = runner.view("p-nav2")
    assert view["lap"] == 3 and view["hold"] is None and len(sent_routes) == 2

    robot_nav["navigation"] = "ARRIVED"
    ports.at(graph.arcs["upper_east:fwd"], 0.03)
    _ticks(runner, ports, n=1)
    assert len(sent_routes) == 3
    assert sum(p["kind"] == "stop" for p in sent_routes[2]) == 2

    # Cancel ends cleanly via cancel_goal, never line_follow_mode OFF.
    canceled = run(runner.cancel("p-nav2", "bob"))
    assert canceled["state"] == "canceled" and ports.canceled == ["rosy_60"] and ports.held == []


def test_nav2_trip_stops_on_aborted_navigation_or_off_lane():
    smap = _south_loop_map()
    runner, store, ports = _setup(smap, caps=BOTH)
    ports.map_id = "site-loop"
    graph = store.active()[2]
    robot_nav = {"navigation": "IDLE"}

    async def robot_state(_rid):
        return {
            "navigation": robot_nav["navigation"],
            "localization": {"state": "LOCALIZED", "pose_frame": "map"},
            "pose": {"x": ports.pose.x, "y": ports.pose.y, "yaw": ports.pose.yaw},
        }

    runner._robot_state = robot_state
    runner._route = lambda _rid, _pts: asyncio.sleep(0, result={"accepted": True})
    ports.at(graph.arcs["upper_east:fwd"], 0.05)
    from fleet.routing.execute import plan_body
    from fleet.routing.trip import PlanRequest, plan_trip
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=store.active()[0], start_pose=(ports.pose.x, ports.pose.y, ports.pose.yaw),
        goal="J_in", stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-abort", robot_id="rosy_60", principal_id="bob",
                      map_version=plan["map_version"], request={"to": "J_in", "drive_mode": "nav2"},
                      result={"plan": plan})
    run(runner.start("p-abort", "bob"))
    _ticks(runner, ports, n=1)
    assert runner.view("p-abort")["state"] == "running"
    robot_nav["navigation"] = "FAILED"
    _ticks(runner, ports, n=1)
    row = runner.view("p-abort")
    assert row["state"] == "stopped" and row["reason"] == "navigation"

    # Moving > half_width off the painted road stops Nav2 trip with off_lane_m and cancels Nav2.
    robot_nav["navigation"] = "IDLE"
    ports.canceled.clear()
    ports.at(graph.arcs["upper_east:fwd"], 0.05)
    store.record_plan(plan_id="p-offlane", robot_id="rosy_60", principal_id="bob",
                      map_version=plan["map_version"], request={"to": "J_in", "drive_mode": "nav2"},
                      result={"plan": plan})
    run(runner.start("p-offlane", "bob"))
    _ticks(runner, ports, n=1)
    assert runner.view("p-offlane")["state"] == "running"
    ports.at(graph.arcs["upper_east:fwd"], 0.15, dy=0.35)
    _ticks(runner, ports, n=1)
    off_row = runner.view("p-offlane")
    assert off_row["state"] == "stopped" and off_row["reason"] == "pose"
    assert "off_lane_m" in off_row["detail"] and ports.canceled == ["rosy_60"]


def test_nav2_mid_route_hold_cancels_long_route_and_dispatches_short_hold():
    smap = _south_loop_map()
    runner, store, ports = _setup(smap, caps=BOTH)
    ports.map_id = "site-loop"
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
    from fleet.routing.execute import plan_body
    from fleet.routing.trip import PlanRequest, plan_trip
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=store.active()[0], start_pose=(ports.pose.x, ports.pose.y, ports.pose.yaw),
        goal="S4", stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-hold", robot_id="rosy_60", principal_id="bob",
                      map_version=plan["map_version"], request={"to": "S4", "drive_mode": "nav2"},
                      result={"plan": plan})
    run(runner.start("p-hold", "bob"))
    _ticks(runner, ports, n=1)
    assert len(sent_routes) == 1 and runner._live["rosy_60"].active_route["end_index"] == 2
    runner._live["rosy_60"].view["hold"] = {"reason": "replan"}
    robot_nav["navigation"] = "NAVIGATING"
    _ticks(runner, ports, n=1)
    assert ports.canceled == ["rosy_60"] and len(sent_routes) == 2
    assert runner._live["rosy_60"].active_route["end_index"] == 0


def test_stop_points_one_way_nav2_moves_out_of_zone():
    from fleet.server.trip_laps import stop_points
    from fleet.traffic.lane_traffic import TrafficService

    smap = _south_loop_map()
    store = SiteMapStore()
    store.import_if_empty(smap, source="test")
    active = store.active()
    graph = active[2]
    # Put upper_west inside a site zone so one-way Nav2 trip to J_out advances onward to S4.
    traffic = TrafficService(store, TripConfig(), zones={"z1": (("upper_west",), 1)})
    from fleet.routing.execute import plan_body
    from fleet.routing.trip import PlanRequest, plan_trip
    x, y, yaw = graph.arcs["upper_east:fwd"].point_at(0.05)
    raw = plan_body(plan_trip(graph, PlanRequest(
        map_version=active[0], start_pose=(x, y, yaw), goal="J_out", stop_offset=True,
    ), store.routing_config))
    moved_plan, moved_req, _route, _arcs, stop_moved = stop_points(
        active, raw, {"to": "J_out", "drive_mode": "nav2"},
        {"kind": "pinky_pro", "modes": ["free"], "junction_turn": False},
        frozenset(), store.routing_config, 150.0, traffic,
    )
    assert moved_req["to"] == "S5" and stop_moved == {"from": "J_out", "to": "S5"}
    assert moved_plan["segments"][-1]["edge_id"] == "lower_east"


def test_degraded_reroute_skips_trip_leased_goal():
    from fleet.server.degraded_reroute import reroute_degraded

    r42 = RouteFakeRobot("rosy_42")
    r45 = RouteFakeRobot("rosy_45")
    clock = FakeClock()
    console = FleetConsole([
        RobotEndpoint(robot_id="rosy_42", base_url="http://127.0.0.1:8080", token="t"),
        RobotEndpoint(robot_id="rosy_45", base_url="http://127.0.0.1:8081", token="t"),
    ], [r42, r45], clock=clock)
    console._goals["rosy_42"] = {"x": 0.75, "y": -0.21, "yaw": math.pi}
    console.goal_leases["rosy_42"] = {"state": "leased", "correlation_id": "c1", "ttl_s": 4.0, "source": "trip", "task_id": None}
    robots = [
        {"robot_id": "rosy_42", "online": True, "state": {"capabilities_degraded": True}},
        {"robot_id": "rosy_45", "online": True, "state": {"capabilities_degraded": False}},
    ]
    degraded = run(reroute_degraded(console, robots))
    assert degraded == {"rosy_42"} and console._queued == {}


def _console_runner(robot: RouteFakeRobot, smap: SiteMap, *, traffic_zones=None, peers=()):
    clock = FakeClock()
    robots = [robot, *peers]
    console = FleetConsole([RobotEndpoint(r.robot_id, "http://127.0.0.1:8080", "t") for r in robots],
                           robots, clock=clock, goal_lease_ttl_s=4.0)
    store = SiteMapStore(clock=clock)
    store.import_if_empty(smap, source="test")
    graph = store.active()[2]
    pose = {"v": MapPose(0.7, -0.215, math.pi, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-loop")}
    robot._state["pose"] = {"x": 0.7, "y": -0.215, "yaw": math.pi}
    robot._state["navigation"] = "IDLE"
    ports = SimpleNamespace(
        caps_for=lambda _id: asyncio.sleep(0, result=BOTH), arbitrated_pose=lambda _id: pose["v"],
        state=lambda _id: robot.state(), junction_state=lambda _id: asyncio.sleep(0, result={}),
        hold=lambda _id: asyncio.sleep(0, result={"mode": "OFF"}),
        line_follow_mode=lambda _id: asyncio.sleep(0, result="OFF"),
        trip_lease=lambda *a, **kw: asyncio.sleep(0, result={"renewed": True}),
    )
    canceled: list[str] = []
    raw_cancel = console.cancel

    async def cancel_goal(rid: str):
        canceled.append(rid)
        return await raw_cancel(rid)

    runner = TripRunner(
        store=store, routing_config=store.routing_config, caps=ports.caps_for, battery=fresh_battery,
        poses=ports, junction=ports, goal=lambda *a, **kw: console.goal(*a, trip=True, **kw),
        route=lambda *a, **kw: console.route(*a, trip=True, **kw), cancel_goal=cancel_goal,
        clock=clock, traffic_zones=traffic_zones,
    )
    install_trip_guard(console, runner, clock=clock)
    return clock, console, store, graph, pose, canceled, runner


def test_nav2_link_back_preserves_active_route_lease_and_detects_abort():
    from fleet.routing.execute import plan_body
    from fleet.routing.trip import PlanRequest, plan_trip

    robot = RouteFakeRobot("rosy_42")
    _clock, console, store, graph, pose, _canceled, runner = _console_runner(robot, _south_loop_map())
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=store.active()[0], start_pose=(pose["v"].x, pose["v"].y, pose["v"].yaw),
        goal="S4", stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-lb", robot_id="rosy_42", principal_id="bob",
                      map_version=plan["map_version"], request={"to": "S4", "drive_mode": "nav2"},
                      result={"plan": plan})
    run(runner.start("p-lb", "bob"))
    run(runner.tick())
    assert len(robot.routes) == 1 and "rosy_42" in console.goal_leases

    live = runner._live["rosy_42"]
    now = runner.lease.now()
    live.view.update(state="link_wait", lease={"lease_id": "l-lb", "state": "held", "renewed_at": now - 0.5},
                     wait={"reason": "link_wait", "kind": "timeout", "lease_at": now - 1.0})
    run(runner.tick())
    assert runner.view("p-lb")["state"] == "running"
    assert len(robot.routes) == 1 and "rosy_42" in console.goal_leases

    now = runner.lease.now()
    live.view.update(state="link_wait", lease={"lease_id": "l-lb", "state": "held", "renewed_at": now - 0.2},
                     wait={"reason": "link_wait", "kind": "timeout", "lease_at": now - 0.5})
    robot._state["navigation"] = "FAILED"
    run(runner.tick())
    assert runner.view("p-lb")["state"] == "stopped" and runner.view("p-lb")["reason"] == "navigation"


def test_nav2_replan_confirm_cancels_superseded_route_without_lease_loss():
    from fleet.routing.execute import plan_body
    from fleet.routing.trip import PlanRequest, plan_trip

    robot = RouteFakeRobot("rosy_42")
    _clock, console, store, graph, pose, canceled, runner = _console_runner(robot, _south_loop_map())
    ver = store.active()[0]
    long_plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=ver, start_pose=(pose["v"].x, pose["v"].y, pose["v"].yaw), goal="S3",
        via=("S4", "S5"), stop_offset=False,
    ), store.routing_config))
    short_plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=ver, start_pose=(pose["v"].x, pose["v"].y, pose["v"].yaw), goal="J_in", stop_offset=False,
    ), store.routing_config))
    store.record_plan(plan_id="p-rep", robot_id="rosy_42", principal_id="bob", map_version=ver,
                      request={"to": "S3", "via": ["S4", "S5"], "drive_mode": "nav2"}, result={"plan": long_plan})
    run(runner.start("p-rep", "bob"))
    run(runner.tick())
    live = runner._live["rosy_42"]
    assert live.active_route["end_index"] == 4 and len(robot.routes) == 1

    live.view["hold"] = {"reason": "replan", "map_version": ver, "plan": short_plan, "length_m": 0.43, "eta_s": 5.0}
    run(runner.confirm_replan("p-rep", "bob"))
    assert live.active_route["superseded"] is True and len(live.segments) == 1

    run(runner.tick())
    assert canceled == ["rosy_42"] and len(robot.routes) == 2
    assert "rosy_42" in console.goal_leases and live.active_route["end_index"] == 0


def test_nav2_off_lane_margin_and_two_tick_persistence():
    from fleet.routing.execute import plan_body
    from fleet.routing.trip import PlanRequest, plan_trip

    robot = RouteFakeRobot("rosy_42")
    _clock, _console, store, graph, pose, _canceled, runner = _console_runner(robot, _south_loop_map())
    plan = plan_body(plan_trip(graph, PlanRequest(
        map_version=store.active()[0], start_pose=(pose["v"].x, pose["v"].y, pose["v"].yaw),
        goal="S4", stop_offset=False, ignore_start_heading=True,
    ), store.routing_config))
    store.record_plan(plan_id="p-tol", robot_id="rosy_42", principal_id="bob",
                      map_version=plan["map_version"], request={"to": "S4", "drive_mode": "nav2"},
                      result={"plan": plan})
    store.record_plan(plan_id="p-lf-fail", robot_id="rosy_42", principal_id="bob",
                      map_version=plan["map_version"], request={"to": "S4", "drive_mode": "line_follow"},
                      result={"plan": plan})
    # Nav2 start admission accepts (width_m/2, width_m/2 + nav2_off_lane_margin_m]; line_follow rejects.
    pose["v"] = MapPose(0.50, -0.215 + 0.14, math.pi, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-loop")
    with pytest.raises(TripError) as lf_err:
        run(runner.start("p-lf-fail", "bob"))
    assert lf_err.value.code == "TRIP_START_OFF_LANE"
    run(runner.start("p-tol", "bob"))
    robot._state["navigation"] = "NAVIGATING"
    run(runner.tick())
    assert runner.view("p-tol")["state"] == "running"

    # Inside width_m/2 + nav2_off_lane_margin_m (0.10 + 0.06 = 0.16): 0.14 m drift stays running across ticks.
    run(runner.tick())
    run(runner.tick())
    assert runner.view("p-tol")["state"] == "running" and runner._live["rosy_42"].off_lane_ticks == 0

    # Transient single tick at 0.18 m (> 0.16, <= 0.22) sets off_lane_ticks=1 without stopping, then clears on return.
    pose["v"] = MapPose(0.50, -0.215 + 0.18, math.pi, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-loop")
    run(runner.tick())
    assert runner.view("p-tol")["state"] == "running" and runner._live["rosy_42"].off_lane_ticks == 1

    pose["v"] = MapPose(0.50, -0.215, math.pi, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-loop")
    run(runner.tick())
    assert runner.view("p-tol")["state"] == "running" and runner._live["rosy_42"].off_lane_ticks == 0

    # Two consecutive ticks at 0.18 m stop the trip with off_lane_m under reason=="pose".
    pose["v"] = MapPose(0.50, -0.215 + 0.18, math.pi, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-loop")
    run(runner.tick())
    assert runner.view("p-tol")["state"] == "running"
    run(runner.tick())
    stopped = runner.view("p-tol")
    assert stopped["state"] == "stopped" and stopped["reason"] == "pose" and "off_lane_m" in stopped["detail"]

    # Immediate severe deviation (> width_m/2 + 2*margin = 0.22 m) stops in 1 tick.
    pose["v"] = MapPose(0.70, -0.215, math.pi, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-loop")
    store.record_plan(plan_id="p-sev", robot_id="rosy_42", principal_id="bob",
                      map_version=plan["map_version"], request={"to": "S4", "drive_mode": "nav2"},
                      result={"plan": plan})
    run(runner.start("p-sev", "bob"))
    robot._state["navigation"] = "NAVIGATING"
    run(runner.tick())
    pose["v"] = MapPose(0.50, -0.215 + 0.25, math.pi, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site-loop")
    run(runner.tick())
    sev = runner.view("p-sev")
    assert sev["state"] == "stopped" and sev["reason"] == "pose" and "off_lane_m" in sev["detail"]


