"""D-491 5: the server trip loop with fake ports (caps, map pose, junction, goals)."""

from __future__ import annotations

import asyncio
import math
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.trip_runner import MapPose, TripCaps, TripError, TripRunner, plan_body
from fleet.site_map import SiteMap, from_lane_graph
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError

ROOT = Path(__file__).resolve().parents[3]
LANE_GRAPH = ROOT / "middleware" / "perception" / "map" / "map_v2_fleet" / "lane_graph.yaml"
OPERATOR = {"Authorization": "Bearer operator-token"}
VIEWER = {"Authorization": "Bearer viewer-token"}
LANE = TripCaps("pinky_pro", frozenset({"lane"}), 0.2, junction_turn=True)
BOTH = TripCaps("pinky_pro", frozenset({"lane", "free"}), 0.2, junction_turn=True)


class Ports:
    def __init__(self, caps=LANE):
        self.caps = {"rosy_60": caps}
        self.pose = None
        self.sent: list[tuple] = []
        self.goals: list[tuple] = []
        self.canceled: list[str] = []
        self.junction_error = None
        self.junction = None  # CORE line_follow.junction
        self.turns: list = []
        self.blocked: frozenset = frozenset()
        self.now = 1000.0
        self.refreshes = 0
        self.held: list[str] = []
        self.mode = "CAMERA_LINE"

    def caps_for(self, robot_id):
        return self.caps.get(robot_id)

    async def arbitrated_pose(self, robot_id):  # async on purpose: the runner takes either
        return self.pose

    async def refresh(self, robot_id, force_rest=False):
        assert force_rest  # the trip loop reads past the 1 Hz hub cache
        self.refreshes += 1

    async def junction_state(self, robot_id):
        return self.junction

    async def hold(self, robot_id):
        self.held.append(robot_id)
        return {"mode": "OFF"}

    async def line_follow_mode(self, robot_id):
        return self.mode

    async def send_junction(self, robot_id, action, place_id, stop_after_m, expires_s, turn_deg=None,
                            advance_m=None):
        self.turns.append(turn_deg)
        if self.junction_error is not None:
            raise self.junction_error
        self.sent.append((action, place_id, stop_after_m))
        return {"accepted": True, "junction_seq": len(self.sent)}

    async def goal(self, robot_id, x, y, yaw):
        self.goals.append((round(x, 3), round(y, 3)))
        return {"accepted": True}

    async def cancel_goal(self, robot_id):
        self.canceled.append(robot_id)
        return {"canceled": True}

    def at(self, arc, s, state="LOCALIZED", dy=0.0, anchor_age_s=0.1):
        x, y, yaw = arc.point_at(s)
        self.pose = MapPose(x, y + dy, yaw, state, "sighting", 0.0, 0.1, anchor_age_s)


def _free_map(mode="free") -> SiteMap:
    return SiteMap.model_validate({
        "places": [{"id": "A", "name": "A", "x": 0, "y": 0, "kind": "junction"},
                   {"id": "B", "name": "B", "x": 1, "y": 0, "kind": "junction"},
                   {"id": "C", "name": "C", "x": 1, "y": 1, "kind": "park"}],
        "edges": [{"id": "ab", "from": "A", "to": "B", "polyline": [[0, 0], [1, 0]], "width_m": 0.2,
                   "speed_cap_mps": 0.2, "drive_mode": mode},
                  {"id": "bc", "from": "B", "to": "C", "polyline": [[1, 0], [1, 1]], "width_m": 0.2,
                   "speed_cap_mps": 0.2, "drive_mode": mode}]})


def _setup(site_map=None, caps=LANE, path=None):
    ports = Ports(caps)
    store = SiteMapStore(path, clock=lambda: ports.now)
    store.import_if_empty(site_map or from_lane_graph(LANE_GRAPH), source="test")
    runner = TripRunner(store=store, routing_config=store.routing_config, caps=ports, poses=ports,
                        junction=ports, goal=ports.goal, cancel_goal=ports.cancel_goal,
                        blocked=lambda: ports.blocked, clock=lambda: ports.now)
    return runner, store, ports


def _plan(store, ports, arc_id, s, to, plan_id="p1", **request):
    graph = store.active()[2]
    arc = graph.arcs[arc_id]
    ports.at(arc, s)
    x, y, yaw = arc.point_at(s)
    plan = plan_trip(graph, PlanRequest(map_version=store.active()[0], start_pose=(x, y, yaw), goal=to, **request),
                     store.routing_config)
    store.record_plan(plan_id=plan_id, robot_id="rosy_60", principal_id="bob", map_version=plan.map_version,
                      request={"to": to, "via": [], **request}, result={"plan": plan_body(plan)})
    return plan


def run(coro):
    return asyncio.run(coro)


def _code(coro) -> str:
    with pytest.raises(TripError) as err:
        run(coro)
    return err.value.code


# ---- start checks ---------------------------------------------------------------------

def test_start_refuses_with_every_d491_code_in_order():
    runner, store, ports = _setup()
    assert _code(runner.start("nope", "bob")) == "TRIP_PLAN_UNKNOWN"
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    ports.now += 31
    assert _code(runner.start("p1", "bob")) == "TRIP_PLAN_EXPIRED"
    ports.now -= 31
    ports.caps = {}
    assert _code(runner.start("p1", "bob")) == "TRIP_ROBOT_CAPS_UNKNOWN"
    ports.caps = {"rosy_60": TripCaps("pinky_pro", frozenset({"free"}), 0.2)}
    assert _code(runner.start("p1", "bob")) == "TRIP_MODE_UNSUPPORTED"
    ports.caps = {"rosy_60": LANE}
    ports.at(store.active()[2].arcs["ring_s:fwd"], 0.1, state="DEGRADED")
    assert _code(runner.start("p1", "bob")) == "TRIP_POSE_UNTRUSTED"
    ports.pose = None
    assert _code(runner.start("p1", "bob")) == "TRIP_POSE_UNTRUSTED"
    ports.at(store.active()[2].arcs["ring_s:fwd"], 0.1)
    assert run(runner.start("p1", "bob"))["state"] == "started"
    assert _code(runner.start("p1", "bob")) == "TRIP_ALREADY_STARTED"
    _plan(store, ports, "ring_s:fwd", 0.1, "NE", plan_id="p2")
    assert _code(runner.start("p2", "bob")) == "TRIP_BUSY"  # one trip on the whole site


def test_start_refuses_a_plan_made_on_another_map_version():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    draft = store.save_draft(SiteMap.model_validate(store.active_view()["map"]), expected_revision=None,
                             principal_id="bob")
    store.activate(expected_revision=draft["revision"], principal_id="bob", route_active=False)
    assert _code(runner.start("p1", "bob")) == "TRIP_MAP_CHANGED"


def test_lane_trip_that_ends_mid_lane_is_not_executable():
    runner, store, ports = _setup(_free_map("lane"))
    _plan(store, ports, "ab:fwd", 0.1, (1.0, 0.5, None))
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.code == "TRIP_MODE_UNSUPPORTED" and err.value.detail["reason"] == "LANE_END_NOT_A_PLACE"


# ---- lane ------------------------------------------------------------------------------

def test_lane_trip_arms_each_place_within_the_arm_distance_and_stops_at_the_last():
    runner, store, ports = _setup()
    graph = store.active()[2]
    plan = _plan(store, ports, "east:fwd", 0.5, "SE")
    assert [s[0] for s in plan.segments] == ["east"]
    run(runner.start("p1", "bob"))
    run(runner.tick())
    assert runner.running()["state"] == "running" and ports.sent == []
    arc = graph.arcs["east:fwd"]
    ports.at(arc, arc.length_m - 0.61)
    run(runner.tick())
    assert ports.sent == []
    ports.at(arc, arc.length_m - 0.59)
    run(runner.tick())
    assert ports.sent == [("stop", "SE", 0.0)]
    run(runner.tick())
    assert len(ports.sent) == 1  # armed once; re-sent only after half the expiry
    ports.at(arc, arc.length_m - 0.1)
    run(runner.tick())
    assert runner.running() is None and runner.view("p1")["state"] == "arrived"


def test_lane_trip_sends_the_turn_and_waits_until_the_place_is_passed():
    runner, store, ports = _setup()
    graph = store.active()[2]
    plan = _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    first = plan.actions[0]
    run(runner.start("p1", "bob"))
    run(runner.tick())  # ring_s is shorter than the arm distance: armed at once
    assert ports.sent == [(first[1], "SE", None)]
    ports.at(graph.arcs["ring_s:fwd"], graph.arcs["ring_s:fwd"].length_m - 0.02)
    run(runner.tick())
    assert len(ports.sent) == 1 and runner.running()["segment_index"] == 0  # not yet through SE
    ports.at(graph.arcs["ring_e:fwd"], 0.05)
    run(runner.tick())
    assert runner.running()["segment_index"] == 1 and ports.sent[-1][1] == "NE"
    ports.now += 8  # half of the 15 s expiry: the same instruction again
    run(runner.tick())
    assert ports.sent[-1] == ports.sent[-2]


def test_an_old_core_without_the_junction_api_fails_the_trip():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    ports.junction_error = RobotApiError("rosy_60", 404, "HTTP_404", "not found")
    run(runner.start("p1", "bob"))
    run(runner.tick())
    view = runner.view("p1")
    assert view["state"] == "failed" and view["reason"] == "TRIP_ROBOT_JUNCTION_UNSUPPORTED"


# ---- free ------------------------------------------------------------------------------

def test_free_trip_sends_d463_points_ahead_across_the_place_and_arrives():
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    graph = store.active()[2]
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    run(runner.tick())
    assert ports.goals == [(0.3, 0.0)] and ports.sent == []
    run(runner.tick())
    assert len(ports.goals) == 1  # the same point is not sent again
    ports.at(graph.arcs["ab:fwd"], 0.9)
    run(runner.tick())
    assert ports.goals[-1] == (1.0, 0.1)  # 0.2 m ahead runs on into bc
    ports.at(graph.arcs["bc:fwd"], 0.97)
    run(runner.tick())
    assert runner.view("p1")["state"] == "arrived"


# ---- stops, restart, cancel ---------------------------------------------------------------

@pytest.mark.parametrize("state", ["DEGRADED", "UNKNOWN", None])
def test_pose_loss_stops_the_trip_and_sends_nothing_more(state):
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    run(runner.tick())
    if state is None:
        ports.pose = None
    else:
        ports.at(store.active()[2].arcs["ab:fwd"], 0.3, state=state)
    run(runner.tick())
    run(runner.tick())
    view = runner.view("p1")
    assert (view["state"], view["reason"], view["detail"]["pose_state"]) == ("stopped", "pose", state)
    assert {"sightings_filtered_map_id", "odom_refused"} <= set(view["detail"])
    assert len(ports.goals) == 1 and ports.canceled == []  # left to the robot's deadman


def test_off_lane_beyond_half_the_width_stops_the_trip():
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    ports.at(store.active()[2].arcs["ab:fwd"], 0.4, dy=0.09)
    run(runner.tick())
    assert runner.view("p1")["state"] == "running"
    ports.at(store.active()[2].arcs["ab:fwd"], 0.4, dy=0.11)
    run(runner.tick())
    view = runner.view("p1")
    assert view["state"] == "stopped" and view["detail"]["off_lane_m"] == pytest.approx(0.11)


def test_a_restart_marks_the_open_trip_stopped_and_never_resumes(tmp_path):
    runner, store, ports = _setup(path=tmp_path / "fleet.sqlite3")
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    run(runner.tick())
    store.close()
    again, store, ports = _setup(path=tmp_path / "fleet.sqlite3")
    assert again.running() is None
    view = again.view("p1")
    assert (view["state"], view["reason"]) == ("stopped", "restart")
    run(again.tick())
    assert ports.sent == []


@pytest.mark.parametrize(("site_map", "arc", "to", "caps"), [
    (None, "ring_s:fwd", "NW", LANE), ("free", "ab:fwd", "C", BOTH)])
def test_cancel_sends_a_lane_stop_or_a_goal_cancel(site_map, arc, to, caps):
    runner, store, ports = _setup(_free_map() if site_map else None, caps=caps)
    _plan(store, ports, arc, 0.1, to)
    run(runner.start("p1", "bob"))
    run(runner.tick())
    view = run(runner.cancel("p1", "bob"))
    assert view["state"] == "canceled" and view["detail"]["canceled_by"] == "bob"
    if site_map:
        assert ports.canceled == ["rosy_60"]
    else:
        assert ports.sent[-1] == ("stop", "SE", 0.0)
    assert _code(runner.cancel("p1", "bob")) == "TRIP_NOT_RUNNING"
    assert _code(runner.cancel("zz", "bob")) == "TRIP_UNKNOWN"


# ---- replan --------------------------------------------------------------------------------

def test_a_blocked_lane_replans_only_at_the_next_place_and_holds_for_the_operator():
    runner, store, ports = _setup()
    graph = store.active()[2]
    plan = _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    assert [s[0] for s in plan.segments] == ["ring_s", "ring_e", "ring_n"]
    run(runner.start("p1", "bob"))
    assert _code(runner.confirm_replan("p1", "bob")) == "TRIP_NO_REPLAN"
    ports.blocked = frozenset({"ring_e"})
    run(runner.tick())
    view = runner.running()
    assert view["hold"]["reason"] == "replan" and ports.sent == [("stop", "SE", 0.0)]
    assert [s["edge_id"] for s in view["hold"]["plan"]["segments"]][1] == "east"
    ports.at(graph.arcs["ring_s:fwd"], graph.arcs["ring_s:fwd"].length_m - 0.05)
    run(runner.tick())
    assert runner.running()["hold"] is not None and len(ports.sent) == 1  # holding, nothing new
    view = run(runner.confirm_replan("p1", "bob"))
    assert view["hold"] is None and [s["edge_id"] for s in view["plan"]["segments"]][:2] == ["ring_s", "east"]
    run(runner.tick())
    assert ports.sent[-1][1] == "SE" and ports.sent[-1][0] != "stop"


def test_a_replan_with_the_same_route_does_not_hold():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    ports.blocked = frozenset({"west"})  # not on the route: no replan at all
    run(runner.tick())
    assert runner.running()["hold"] is None and ports.sent[0][0] != "stop"


# ---- API -----------------------------------------------------------------------------------

def _app(tmp_path, ports):
    robot = FakeRobot("rosy_60")
    console = FleetConsole([RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")], [robot])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"})
    store = SiteMapStore(tmp_path / "tasks.sqlite")
    store.import_if_empty(from_lane_graph(LANE_GRAPH), source="lane_graph.yaml")
    users = {sha256(b"operator-token").hexdigest(): {"principal_id": "bob", "role": "operator"},
             sha256(b"viewer-token").hexdigest(): {"principal_id": "vic", "role": "viewer"}}
    app = create_app(console, task_service=tasks, site_users=users, site_maps=store,
                     trip_caps=ports, map_pose=ports, lane_junction=ports)
    x, y, yaw = store.active()[2].arcs["ring_s:fwd"].point_at(0.1)
    robot._state = {"robot_id": "rosy_60", "pose": {"x": x, "y": y, "yaw": yaw},
                    "localization": {"state": "LOCALIZED", "pose_frame": "map"}}
    ports.at(store.active()[2].arcs["ring_s:fwd"], 0.1)
    return TestClient(app), tasks, store


def test_trip_api_start_status_cancel_need_a_named_operator_and_are_audited(tmp_path):
    ports = Ports()
    client, tasks, store = _app(tmp_path, ports)
    ports.now = __import__("time").time()
    plan = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()
    assert store.plan(plan["plan_id"])["result"]["plan"]["segments"] == plan["segments"]
    start = f"/api/fleet/trips/{plan['plan_id']}/start"
    assert client.post(start, headers=VIEWER).status_code == 403
    started = client.post(start, headers=OPERATOR)
    assert started.status_code == 200 and started.json()["state"] == "started", started.text
    again = client.post(start, headers=OPERATOR)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "TRIP_ALREADY_STARTED"
    run(client.app.state.trip_runner.tick())
    listing = client.get("/api/fleet/trips", headers=VIEWER).json()
    assert listing["running"]["trip_id"] == plan["plan_id"] and listing["running"]["pose"]["source"] == "sighting"
    assert client.get(f"/api/fleet/trips/{plan['plan_id']}", headers=VIEWER).json()["state"] == "running"
    assert client.get("/api/fleet/trips/nope", headers=VIEWER).json()["detail"]["code"] == "TRIP_UNKNOWN"

    # D-491 5: the activation guard is "a running trip exists"
    saved = client.put("/api/fleet/site-map/draft", json={"map": store.active_view()["map"]}, headers=OPERATOR).json()
    refused = client.post("/api/fleet/site-map/activate", json={"expected_revision": saved["revision"]},
                          headers=OPERATOR)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "SITE_MAP_ROUTE_ACTIVE"
    assert client.post(f"/api/fleet/trips/{plan['plan_id']}/cancel", headers=VIEWER).status_code == 403
    canceled = client.post(f"/api/fleet/trips/{plan['plan_id']}/cancel", headers=OPERATOR)
    assert canceled.status_code == 200 and canceled.json()["state"] == "canceled"
    assert client.post("/api/fleet/site-map/activate", json={"expected_revision": saved["revision"]},
                       headers=OPERATOR).status_code == 200
    audit = [(r["path"], r["event_type"], r["status_code"]) for r in tasks.store.api_audit()]
    assert (start, "RESULT", 200) in audit
    assert (f"/api/fleet/trips/{plan['plan_id']}/cancel", "RESULT", 200) in audit


def test_default_wiring_refuses_start_until_the_providers_land(tmp_path):
    from test_site_map_trip import _app as plain_app, _on_ring_s

    client, _tasks, store, robot = plain_app(tmp_path)
    robot._state = _on_ring_s(store)
    plan = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()
    refused = client.post(f"/api/fleet/trips/{plan['plan_id']}/start", headers=OPERATOR)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "TRIP_ROBOT_CAPS_UNKNOWN"


def test_the_http_junction_port_posts_the_d491_body():
    from fleet.server.trip_runner import HttpLaneJunction

    class Client:
        async def line_follow_junction(self, action, place_id, *, stop_after_m, expires_s, turn_deg, advance_m):
            return {"args": (action, place_id, stop_after_m, expires_s, turn_deg)}

        async def state(self):
            return {"line_follow": {"junction": {"state": "turning", "seq": 3}}}

    port = HttpLaneJunction(lambda: {"r": Client()})
    assert run(port.send_junction("r", "left", "NE", None, 15.0, turn_deg=88.0)) == {
        "args": ("left", "NE", None, 15.0, 88.0)}
    assert run(port.junction_state("r"))["state"] == "turning"
    from fleet.hub.hub import HubError

    with pytest.raises(HubError) as err:
        run(port.send_junction("x", "left", "NE", None, 15.0))
    assert err.value.code == "UNKNOWN_ROBOT"


def test_http_robot_client_line_follow_junction_hits_the_core_path():
    import httpx

    from fleet.swarm.transport import HttpRobotClient

    seen = {}

    def handler(request):
        seen["path"], seen["body"] = request.url.path, __import__("json").loads(request.content)
        return httpx.Response(404, json={"error": {"code": "HTTP_404", "message": "nope"}})

    async def go():
        async with httpx.AsyncClient(base_url="http://robot", transport=httpx.MockTransport(handler)) as http:
            client = HttpRobotClient(RobotEndpoint("one", "http://robot", "t"), http=http)
            await client.line_follow_junction("left", "SE", stop_after_m=None, expires_s=15.0, turn_deg=-91.5)

    with pytest.raises(RobotApiError) as err:
        run(go())
    assert err.value.status == 404 and seen["path"] == "/api/v1/line-follow/junction"
    assert seen["body"] == {"action": "left", "place_id": "SE", "expires_s": 15.0, "turn_deg": -91.5}


def test_the_loop_steps_on_its_period():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))

    async def briefly():
        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.05)
        task.cancel()

    run(briefly())
    assert runner.running()["state"] == "running" and math.isclose(runner.config.period_s, 0.5)


def test_confirm_after_the_map_changed_plans_again_at_the_place():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    ports.blocked = frozenset({"ring_e"})
    run(runner.tick())
    assert runner.running()["hold"]["map_version"] == 1
    draft = store.save_draft(SiteMap.model_validate(store.active_view()["map"]), expected_revision=None,
                             principal_id="bob")
    store.activate(expected_revision=draft["revision"], principal_id="bob", route_active=False)
    assert _code(runner.confirm_replan("p1", "bob")) == "TRIP_MAP_CHANGED"
    run(runner.tick())
    hold = runner.running()["hold"]
    assert hold["map_version"] == 2 and ports.sent[-1][0] == "stop"
    assert run(runner.confirm_replan("p1", "bob"))["map_version"] == 2


# ---- D-492 bounded junction turn ------------------------------------------------------

def test_lane_left_right_send_the_map_angle_and_need_the_junction_turn_capability():
    runner, store, ports = _setup(_free_map("lane"))
    plan = _plan(store, ports, "ab:fwd", 0.5, "C")
    assert plan.actions[0][:2] == ("B", "left")
    ports.caps = {"rosy_60": TripCaps("pinky_pro", frozenset({"lane"}), 0.2)}  # junction_turn False
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.code == "TRIP_MODE_UNSUPPORTED" and err.value.detail["reason"] == "JUNCTION_TURN_UNSUPPORTED"
    ports.caps = {"rosy_60": LANE}
    run(runner.start("p1", "bob"))
    run(runner.tick())
    assert ports.sent[-1] == ("left", "B", None) and ports.turns[-1] == pytest.approx(90.0, abs=0.1)
    ports.at(store.active()[2].arcs["bc:fwd"], 0.5)
    run(runner.tick())
    assert ports.sent[-1] == ("stop", "C", 0.0) and ports.turns[-1] is None
    straight = _setup()  # a stop-only lane plan needs no turn capability
    _plan(straight[1], straight[2], "east:fwd", 3.6, "SE")
    straight[2].caps = {"rosy_60": TripCaps("pinky_pro", frozenset({"lane"}), 0.2)}
    run(straight[0].start("p1", "bob"))


def test_a_turn_sharper_than_the_bound_is_refused_for_lane_robots():
    import dataclasses

    runner, store, ports = _setup(_free_map("lane"))
    _plan(store, ports, "ab:fwd", 0.5, "C")
    runner.config = dataclasses.replace(runner.config, max_turn_deg=80.0)  # 150 by default (D-492)
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.detail == {"edge_id": "ab", "reason": "LANE_TURN_TOO_SHARP", "turn_deg": 90.0}


@pytest.mark.parametrize("state", ["aborted", "unresolved"])
def test_core_junction_abort_or_unresolved_stops_the_trip(state):
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    ports.junction = {"state": "turning", "place_id": "SE"}
    run(runner.tick())
    assert runner.running() is not None
    ports.junction = {"state": state, "place_id": "SE"}
    run(runner.tick())
    view = runner.view("p1")
    assert (view["state"], view["reason"], view["detail"]["junction_state"]) == ("stopped", "junction", state)


def test_core_waiting_at_a_junction_stops_the_trip_after_the_timeout():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    ports.junction = {"state": "waiting", "place_id": "SE"}
    run(runner.tick())
    ports.now += 9.9
    run(runner.tick())
    assert runner.running() is not None
    ports.now += 0.2
    run(runner.tick())
    assert runner.view("p1")["reason"] == "junction"


def test_start_needs_a_fresh_anchor_and_each_tick_refreshes_the_robot_state():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    ports.at(store.active()[2].arcs["ring_s:fwd"], 0.1, anchor_age_s=2.5)
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.code == "TRIP_POSE_UNTRUSTED" and err.value.detail["anchor_age_s"] == 2.5
    ports.at(store.active()[2].arcs["ring_s:fwd"], 0.1, anchor_age_s=1.9)
    run(runner.start("p1", "bob"))
    before = ports.refreshes
    run(runner.tick())
    run(runner.tick())
    assert ports.refreshes == before + 2
    ports.at(store.active()[2].arcs["ring_s:fwd"], 0.1, anchor_age_s=8.0)  # bridged: still running
    run(runner.tick())
    assert runner.running()["pose"]["anchor_age_s"] == 8.0


def test_a_pose_stop_surfaces_the_provider_diagnostics():
    import dataclasses

    runner, store, ports = _setup(_free_map(), caps=BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    ports.at(store.active()[2].arcs["ab:fwd"], 0.3, state="DEGRADED")
    ports.pose = dataclasses.replace(ports.pose, sightings_filtered_map_id=2, odom_refused={"reason": "gap"})
    run(runner.tick())
    detail = runner.view("p1")["detail"]
    assert detail["sightings_filtered_map_id"] == 2 and detail["odom_refused"] == {"reason": "gap"}


# ---- review changes A–C (2026-10-07) ---------------------------------------------------------

def test_lane_cancel_stops_now_with_a_junction_stop_and_a_hold():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    view = run(runner.cancel("p1", "bob"))
    assert ports.sent[-1] == ("stop", "SE", 0.0) and ports.held == ["rosy_60"] and view["detail"]["stop_sent"]


def test_a_hold_the_robot_refuses_is_reported_not_hidden():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))

    async def refuse(robot_id):
        raise RobotApiError(robot_id, 409, "DOCKING_ACTIVE", "busy")

    ports.hold = refuse
    view = run(runner.cancel("p1", "bob"))
    assert view["state"] == "canceled" and view["detail"]["stop_sent"] is False
    assert view["detail"]["error"] == "DOCKING_ACTIVE"


def test_pose_loss_on_a_lane_holds_the_robot_at_once():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    ports.pose = None
    run(runner.tick())
    view = runner.view("p1")
    assert view["reason"] == "pose" and ports.held == ["rosy_60"] and view["detail"]["stop_sent"]


def test_no_progress_for_stall_s_stops_and_holds_the_robot():
    runner, store, ports = _setup()
    arc = store.active()[2].arcs["east:fwd"]
    _plan(store, ports, "east:fwd", 0.5, "SE")
    run(runner.start("p1", "bob"))
    run(runner.tick())
    ports.now += 15
    ports.at(arc, 0.56)  # +0.06 m resets the timer
    run(runner.tick())
    ports.now += 19.9
    ports.at(arc, 0.58)  # +0.02 m is not progress
    run(runner.tick())
    assert runner.running() is not None
    ports.now += 0.2
    run(runner.tick())
    view = runner.view("p1")
    assert (view["state"], view["reason"]) == ("stopped", "stall") and ports.held == ["rosy_60"]


@pytest.mark.parametrize("junction", ["turning", "advancing", "reacquiring"])
def test_a_junction_manoeuvre_is_not_a_stall(junction):
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    run(runner.tick())  # armed: the junction state is read
    ports.junction = {"state": junction, "place_id": "SE"}
    for _ in range(3):
        ports.now += 15
        run(runner.tick())
    assert runner.running() is not None


def test_a_replan_hold_is_not_a_stall():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    ports.blocked = frozenset({"ring_e"})
    run(runner.tick())
    for _ in range(3):
        ports.now += 15
        run(runner.tick())
    assert runner.running()["hold"] is not None


def test_free_stall_cancels_the_goal():
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    run(runner.tick())
    ports.now += 20
    run(runner.tick())
    assert runner.view("p1")["reason"] == "stall" and ports.canceled == ["rosy_60"] and ports.held == []


@pytest.mark.parametrize("mode", ["OFF", None])
def test_a_lane_plan_needs_line_follow_on(mode):
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    ports.mode = mode
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.code == "TRIP_LINE_FOLLOW_NOT_ACTIVE" and err.value.detail["mode"] == mode
    ports.mode = "IR_LINE"
    assert run(runner.start("p1", "bob"))["state"] == "started"


def test_a_free_plan_does_not_read_line_follow():
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    ports.mode = "OFF"
    assert run(runner.start("p1", "bob"))["state"] == "started"


def test_trip_config_reads_fleet_trip_and_refuses_bad_values(tmp_path):
    from fleet import cli
    from fleet.server.trip_runner import TripConfig

    config = tmp_path / "site.yaml"
    config.write_text("fleet:\n  trip:\n    stall_s: 35\n", encoding="utf-8")
    assert cli._trip_config(cli.parse_args(["console", "--site-config", str(config)])).stall_s == 35
    assert TripConfig.from_mapping(None).stall_s == 20.0
    for bad in ({"stall_s": 0}, {"stall_s": True}, {"nope": 1}):
        with pytest.raises(ValueError):
            TripConfig.from_mapping(bad)


def test_http_line_follow_port_reads_the_mode_and_holds_with_mode_off():
    from fleet.server.trip_runner import HttpLaneJunction

    class Client:
        modes: list = []

        async def line_follow(self):
            return {"mode": "CAMERA_LINE"}

        async def line_follow_mode(self, mode):
            self.modes.append(mode)
            return {"mode": mode}

    client = Client()
    port = HttpLaneJunction(lambda: {"r": client})
    assert run(port.line_follow_mode("r")) == "CAMERA_LINE"
    run(port.hold("r"))
    assert client.modes == ["OFF"]
