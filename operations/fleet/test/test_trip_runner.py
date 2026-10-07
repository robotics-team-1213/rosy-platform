"""D-491 5: the server trip loop against a fake CORE junction (D-491 4 / D-492) and fake ports."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import math
import time
from hashlib import sha256
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.hub.hub import HubError
from fleet.routing.execute import plan_body
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.server.trip_ports import HttpLaneJunction, MapPose, TripCaps, TripConfig
from fleet.server.trip_runner import TripError, TripRunner
from fleet.site_map import SiteMap, from_lane_graph
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient, RobotApiError

ROOT = Path(__file__).resolve().parents[3]
LANE_GRAPH = ROOT / "middleware" / "perception" / "map" / "map_v2_fleet" / "lane_graph.yaml"
OPERATOR = {"Authorization": "Bearer operator-token"}
VIEWER = {"Authorization": "Bearer viewer-token"}
LANE = TripCaps("pinky_pro", frozenset({"lane"}), 0.2, junction_turn=True)
BOTH = TripCaps("pinky_pro", frozenset({"lane", "free"}), 0.2, junction_turn=True)
MANOEUVRE = ("turning", "advancing", "reacquiring")


class FakeCore:
    """CORE ``line_follow/junction.py`` as Fleet sees it (feat/d491-core-junction-action).

    One instruction; ``seq`` counts accepted ones. ``straight`` and a turn with ``turn_deg``
    arm, ``stop`` executes at once and holds after ``stop_after_m`` of travel from receipt (not
    at a junction), a turn without ``turn_deg`` is ``unresolved``. A new instruction during a
    manoeuvre aborts it and is not accepted. An armed instruction expires to idle. The test
    drives the robot side: ``see_junction``, ``phase``, ``done``.
    """

    def __init__(self, ports) -> None:
        self.ports = ports
        self.mode = "CAMERA_LINE"
        self.seq = 0
        self.j: dict | None = None

    def _xy(self):
        pose = self.ports.pose
        return (pose.x, pose.y) if pose is not None else (0.0, 0.0)

    def send(self, action, place_id, stop_after_m, expires_s, turn_deg):
        if self.mode not in ("CAMERA_LINE", "IR_LINE"):
            raise RobotApiError("rosy_60", 409, "LINE_FOLLOW_NOT_ACTIVE", "line follow is off")
        if not 0 < expires_s <= 30 or (stop_after_m is not None and (action != "stop" or not 0 <= stop_after_m <= 2)) \
                or (turn_deg is not None and (action not in ("left", "right") or not 0 < abs(turn_deg) <= 150
                                              or (turn_deg > 0) != (action == "left"))):
            raise RobotApiError("rosy_60", 400, "VALIDATION_ERROR", "bad junction instruction")
        if self.j is not None and self.j["state"] in MANOEUVRE:
            self.j.update(state="aborted", reason="new_instruction")
            return {"accepted": False, "junction_seq": self.j["seq"]}
        self.seq += 1
        state = ("armed" if action == "straight" or turn_deg is not None
                 else "executing" if action == "stop" else "unresolved")
        self.j = {"action": action, "place_id": place_id, "seq": self.seq, "state": state, "reason": None,
                  "expires_at": self.ports.now + expires_s, "stop_after_m": stop_after_m or 0.0,
                  "from": self._xy(), "held": False}
        return {"accepted": True, "junction_seq": self.seq}

    def status(self):
        j = self.j
        if j is not None and j["state"] == "armed" and self.ports.now > j["expires_at"]:
            self.j = j = None
        if j is not None and j["action"] == "stop" and j["state"] == "executing":
            j["held"] = j["held"] or math.dist(j["from"], self._xy()) >= j["stop_after_m"]
        if j is None:
            return {"pending_action": None, "place_id": None, "state": "idle", "seq": self.seq, "reason": None}
        return {"pending_action": j["action"], "place_id": j["place_id"], "state": j["state"], "seq": self.seq,
                "reason": j["reason"]}

    def see_junction(self):
        j = self.j
        if j is None or j["state"] == "waiting":
            self.j = {"action": None, "place_id": None, "seq": self.seq, "state": "waiting", "reason": None}
        elif j["state"] == "armed":
            j["state"] = "executing" if j["action"] == "straight" else "turning"

    def phase(self, state):
        self.j["state"] = state

    def done(self):
        self.j = None

    def off(self):
        self.mode = "OFF"
        if self.j is not None and self.j["state"] in MANOEUVRE:
            self.j.update(state="aborted", reason="mode_change")
        else:
            self.j = None


class Ports:
    def __init__(self, caps=LANE):
        self.caps = {"rosy_60": caps}
        self.pose = None
        self.core = FakeCore(self)
        self.sent: list[tuple] = []
        self.turns: list = []
        self.goals: list[tuple] = []
        self.canceled: list[str] = []
        self.held: list[str] = []
        self.junction_error = None
        self.goal_error = None
        self.state_none = False  # an old CORE without line_follow.junction
        self.blocked: frozenset = frozenset()
        self.now = 1000.0
        self.refreshes = 0

    def caps_for(self, robot_id):
        return self.caps.get(robot_id)

    async def arbitrated_pose(self, robot_id):  # async on purpose: the runner takes either
        return self.pose

    async def refresh(self, robot_id, force_rest=False):
        assert force_rest  # the trip loop reads past the 1 Hz hub cache
        self.refreshes += 1

    async def junction_state(self, robot_id):
        return None if self.state_none else self.core.status()

    async def hold(self, robot_id):
        self.held.append(robot_id)
        self.core.off()
        return {"mode": "OFF"}

    async def line_follow_mode(self, robot_id):
        return self.core.mode

    async def send_junction(self, robot_id, action, place_id, stop_after_m, expires_s, turn_deg=None,
                            advance_m=None):
        if self.junction_error is not None:
            raise self.junction_error
        reply = self.core.send(action, place_id, stop_after_m, expires_s, turn_deg)
        self.sent.append((action, place_id, None if stop_after_m is None else round(stop_after_m, 3)))
        self.turns.append(turn_deg)
        return reply

    async def goal(self, robot_id, x, y, yaw):
        if self.goal_error is not None:
            raise self.goal_error
        self.goals.append((round(x, 3), round(y, 3)))
        return {"accepted": True}

    async def cancel_goal(self, robot_id):
        self.canceled.append(robot_id)
        return {"canceled": True}

    def at(self, arc, s, state="LOCALIZED", dy=0.0, anchor_age_s=0.1):
        x, y, yaw = arc.point_at(s)
        self.pose = MapPose(x, y + dy, yaw, state, "sighting", 0.0, 0.1, anchor_age_s)


def _map(*places, edges) -> SiteMap:
    return SiteMap.model_validate({
        "places": [{"id": p, "name": p, "x": x, "y": y, "kind": "junction"} for p, x, y in places],
        "edges": [{"id": e, "from": a, "to": b, "polyline": line, "width_m": 0.2, "speed_cap_mps": 0.2,
                   "drive_mode": mode} for e, a, b, line, mode in edges]})


def _free_map(mode="free") -> SiteMap:
    """A -> B -> C with a 90 degree left turn at B."""
    return _map(("A", 0, 0), ("B", 1, 0), ("C", 1, 1),
                edges=[("ab", "A", "B", [[0, 0], [1, 0]], mode), ("bc", "B", "C", [[1, 0], [1, 1]], mode)])


def _sharp_map() -> SiteMap:
    """A -> B -> D with a 129.8 degree left turn at B (over 90, under the 150 bound)."""
    return _map(("A", 0, 0), ("B", 1, 0), ("D", 0.5, 0.6),
                edges=[("ab", "A", "B", [[0, 0], [1, 0]], "lane"), ("bd", "B", "D", [[1, 0], [0.5, 0.6]], "lane")])


def _setup(site_map=None, caps=LANE, path=None, **config):
    ports = Ports(caps)
    store = SiteMapStore(path, clock=lambda: ports.now)
    store.import_if_empty(site_map or from_lane_graph(LANE_GRAPH), source="test")
    runner = TripRunner(store=store, routing_config=store.routing_config, caps=ports, poses=ports,
                        junction=ports, goal=ports.goal, cancel_goal=ports.cancel_goal,
                        blocked=lambda: ports.blocked, clock=lambda: ports.now, config=TripConfig(**config))
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


def _arc(store, arc_id):
    return store.active()[2].arcs[arc_id]


def run(coro):
    return asyncio.run(coro)


def _code(coro) -> str:
    with pytest.raises(TripError) as err:
        run(coro)
    return err.value.code


def _ticks(runner, ports, n=1, dt=0.5):
    for _ in range(n):
        ports.now += dt
        run(runner.tick())


# ---- the fake is CORE ----------------------------------------------------------------------

def test_the_fake_core_follows_the_junction_contract():
    ports = Ports()
    core = ports.core
    ports.pose = MapPose(0.0, 0.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, 0.1)
    assert core.send("stop", "B", 0.3, 15, None)["accepted"] and core.status()["state"] == "executing"
    ports.pose = dataclasses.replace(ports.pose, x=0.31)
    assert core.j["held"] is False and core.status()["state"] == "executing" and core.j["held"]
    assert core.send("left", "B", None, 15, 90.0) == {"accepted": True, "junction_seq": 2}
    core.see_junction()
    assert core.status()["state"] == "turning"
    assert core.send("straight", "C", None, 15, None) == {"accepted": False, "junction_seq": 2}
    assert core.status()["state"] == "aborted"
    assert core.send("left", "B", None, 15, None)["accepted"] and core.status()["state"] == "unresolved"
    assert core.send("straight", "B", None, 1, None)["accepted"]
    ports.now += 2
    assert core.status() == {"pending_action": None, "place_id": None, "state": "idle", "seq": 4, "reason": None}
    with pytest.raises(RobotApiError):
        core.send("right", "B", None, 15, 30.0)  # right takes a negative angle


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
    ports.caps = {"rosy_60": TripCaps("pinky_pro", frozenset({"free"}), 0.2, junction_turn=True)}
    assert _code(runner.start("p1", "bob")) == "TRIP_MODE_UNSUPPORTED"
    ports.caps = {"rosy_60": LANE}
    ports.core.mode = "OFF"
    assert _code(runner.start("p1", "bob")) == "TRIP_LINE_FOLLOW_NOT_ACTIVE"
    ports.core.mode = "IR_LINE"
    ring_s = _arc(store, "ring_s:fwd")
    for state, anchor in (("DEGRADED", 0.1), ("LOCALIZED", 2.5), ("LOCALIZED", None)):
        ports.at(ring_s, 0.1, state=state, anchor_age_s=anchor)
        with pytest.raises(TripError) as err:
            run(runner.start("p1", "bob"))
        assert err.value.code == "TRIP_POSE_UNTRUSTED" and err.value.detail["anchor_age_s"] == anchor
    ports.pose = None
    assert _code(runner.start("p1", "bob")) == "TRIP_POSE_UNTRUSTED"
    ports.at(ring_s, 0.1, anchor_age_s=1.9)
    assert run(runner.start("p1", "bob"))["state"] == "started"
    assert _code(runner.start("p1", "bob")) == "TRIP_ALREADY_STARTED"
    _plan(store, ports, "ring_s:fwd", 0.1, "NE", plan_id="p2")
    assert _code(runner.start("p2", "bob")) == "TRIP_BUSY"  # one trip on the whole site


def _activate_again(store):
    draft = store.save_draft(SiteMap.model_validate(store.active_view()["map"]), expected_revision=None,
                             principal_id="bob")
    store.activate(expected_revision=draft["revision"], principal_id="bob", route_active=False)


def test_start_refuses_a_plan_made_on_another_map_version():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    _activate_again(store)
    assert _code(runner.start("p1", "bob")) == "TRIP_MAP_CHANGED"


def test_start_checks_the_map_version_again_after_its_robot_calls():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    pose = ports.pose

    async def activating(robot_id):  # a map activation lands while the start reads the pose
        _activate_again(store)
        return pose

    ports.arbitrated_pose = activating
    assert _code(runner.start("p1", "bob")) == "TRIP_MAP_CHANGED"
    assert runner.running() is None


@pytest.mark.parametrize(("site_map", "arc", "s", "to", "caps", "reason"), [
    ("lane", "ab:fwd", 0.1, (1.0, 0.5, None), LANE, "LANE_END_NOT_A_PLACE"),
    ("lane", "ab:fwd", 0.5, "C", TripCaps("pinky_pro", frozenset({"lane"}), 0.2), "JUNCTION_TURN_UNSUPPORTED"),
    # keep-mode evidence is needed for any lane plan, a stop-only one included (D-492)
    ("lane", "bc:fwd", 0.5, "C", TripCaps("pinky_pro", frozenset({"lane"}), 0.2), "JUNCTION_TURN_UNSUPPORTED"),
])
def test_plans_a_lane_robot_cannot_run_are_refused(site_map, arc, s, to, caps, reason):
    runner, store, ports = _setup(_free_map(site_map), caps=caps)
    _plan(store, ports, arc, s, to)
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.code == "TRIP_MODE_UNSUPPORTED" and err.value.detail["reason"] == reason


def test_a_turn_sharper_than_the_bound_is_refused_for_lane_robots():
    runner, store, ports = _setup(_free_map("lane"), max_turn_deg=80.0)  # 150 by default (D-492)
    _plan(store, ports, "ab:fwd", 0.5, "C")
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.detail == {"edge_id": "ab", "reason": "LANE_TURN_TOO_SHARP", "turn_deg": 90.0}


# ---- lane: stops ----------------------------------------------------------------------------

def test_the_last_stop_carries_the_distance_left_and_is_never_sent_again():
    runner, store, ports = _setup()
    arc = _arc(store, "east:fwd")
    plan = _plan(store, ports, "east:fwd", 0.5, "SE")
    assert [s[0] for s in plan.segments] == ["east"]
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    assert runner.running()["state"] == "running" and ports.sent == []
    ports.at(arc, arc.length_m - 0.61)
    _ticks(runner, ports)
    assert ports.sent == []
    ports.at(arc, arc.length_m - 0.55)
    _ticks(runner, ports)
    assert ports.sent == [("stop", "SE", 0.55)]  # CORE counts it in odom from receipt
    ports.at(arc, arc.length_m - 0.3)
    _ticks(runner, ports, 40)  # executing, then held: never again, past any expiry
    assert len(ports.sent) == 1 and runner.running() is not None
    ports.at(arc, arc.length_m - 0.05)
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "arrived"


def test_a_stop_further_than_two_metres_is_clamped():
    runner, store, ports = _setup(arm_distance_m=3.0)
    arc = _arc(store, "east:fwd")
    _plan(store, ports, "east:fwd", 0.5, "SE")
    run(runner.start("p1", "bob"))
    ports.at(arc, arc.length_m - 2.9)
    _ticks(runner, ports)
    assert ports.sent == [("stop", "SE", 2.0)]


# ---- lane: straight, turns, advance -----------------------------------------------------------

def test_straight_is_refreshed_only_while_core_shows_it_armed_and_never_while_executing():
    runner, store, ports = _setup()
    ring_s = _arc(store, "ring_s:fwd")
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)  # ring_s is shorter than the arm distance: armed at once
    assert ports.sent == [("straight", "SE", None)]
    _ticks(runner, ports, 1, dt=8.0)  # armed, same seq, half the 15 s expiry gone
    assert ports.sent[-1] == ("straight", "SE", None) and len(ports.sent) == 2
    ports.core.see_junction()
    _ticks(runner, ports, 1, dt=8.0)
    assert len(ports.sent) == 2  # executing: nothing new
    ports.at(ring_s, ring_s.length_m - 0.02)
    ports.core.done()  # through the junction: idle, near the place
    _ticks(runner, ports)
    assert runner.running()["segment_index"] == 1 and ports.sent[-1] == ("straight", "NE", None)


def test_an_expired_instruction_before_the_place_is_sent_again():
    runner, store, ports = _setup(junction_expires_s=2.0)
    arc = _arc(store, "east:fwd")
    _plan(store, ports, "east:fwd", arc.length_m - 0.5, "NW")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    first = len(ports.sent)
    _ticks(runner, ports, 1, dt=3.0)  # CORE dropped it to idle; the robot is still 0.5 m away
    assert len(ports.sent) == first + 1 and runner.running()["segment_index"] == 0


def test_a_90_degree_turn_waits_out_the_manoeuvre_then_moves_on():
    runner, store, ports = _setup(_free_map("lane"))
    ab, bc = _arc(store, "ab:fwd"), _arc(store, "bc:fwd")
    _plan(store, ports, "ab:fwd", 0.5, "C")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    assert ports.sent == [("left", "B", None)] and ports.turns == [pytest.approx(90.0, abs=0.1)]
    ports.at(ab, ab.length_m - 0.05)
    ports.core.see_junction()
    for state in MANOEUVRE:
        ports.core.phase(state)
        _ticks(runner, ports, 30, dt=1.0)  # 90 s in all: no stall, no send, no advance
    assert len(ports.sent) == 1 and runner.running()["segment_index"] == 0
    ports.core.done()
    _ticks(runner, ports)
    assert runner.running()["segment_index"] == 1
    ports.at(bc, 0.5)
    _ticks(runner, ports)
    assert ports.sent[-1] == ("stop", "C", 0.5)


def test_a_turn_over_90_degrees_moves_on_by_core_or_by_the_pose():
    for core_reports in (True, False):
        runner, store, ports = _setup(_sharp_map())
        bd = _arc(store, "bd:fwd")
        _plan(store, ports, "ab:fwd", 0.6, "D")
        run(runner.start("p1", "bob"))
        _ticks(runner, ports)
        assert ports.sent[0][0] == "left" and ports.turns[0] == pytest.approx(129.8, abs=0.1)
        ports.at(bd, 0.0)  # turned in place at B: on the corner of both lanes
        ports.core.see_junction()
        _ticks(runner, ports)
        assert runner.running()["segment_index"] == 0
        if core_reports:
            ports.core.done()
        else:
            ports.state_none = True  # no junction state: only the pose can move it on
            ports.at(bd, 0.05)
        _ticks(runner, ports)
        assert runner.running()["segment_index"] == 1, core_reports


def test_a_short_ring_lane_moves_on_by_the_pose_and_waits_for_core_to_finish():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    ports.core.see_junction()  # straight through SE
    ports.at(_arc(store, "ring_e:fwd"), 0.05)  # already on the 0.46 m ring_e
    _ticks(runner, ports)
    assert runner.running()["segment_index"] == 1 and len(ports.sent) == 1  # SE still executing
    ports.core.done()
    _ticks(runner, ports)
    assert ports.sent[-1] == ("straight", "NE", None)


def test_an_old_core_without_the_junction_api_fails_the_trip_and_stops_the_robot():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    ports.junction_error = RobotApiError("rosy_60", 404, "HTTP_404", "not found")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    view = runner.view("p1")
    assert (view["state"], view["reason"]) == ("failed", "TRIP_ROBOT_JUNCTION_UNSUPPORTED")
    assert ports.held == ["rosy_60"] and view["detail"]["stop_sent"] is True


@pytest.mark.parametrize("state", ["aborted", "unresolved"])
def test_core_abort_or_unresolved_stops_the_trip_and_turns_line_follow_off(state):
    runner, store, ports = _setup(_free_map("lane"))
    _plan(store, ports, "ab:fwd", 0.5, "C")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    ports.core.see_junction()
    ports.core.j.update(state=state, reason="near_stop")
    _ticks(runner, ports)
    view = runner.view("p1")
    assert (view["state"], view["reason"], view["detail"]["junction_state"]) == ("stopped", "junction", state)
    assert view["detail"]["junction_reason"] == "near_stop" and ports.held == ["rosy_60"]


def test_an_abort_left_from_before_the_trip_is_not_the_trips():
    runner, store, ports = _setup()
    ports.core.seq = 7
    ports.core.j = {"action": "left", "place_id": "X", "seq": 7, "state": "aborted", "reason": "mode_change"}
    _plan(store, ports, "east:fwd", 0.5, "SE")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports, 3)
    assert runner.running() is not None


def test_core_waiting_at_a_junction_stops_the_trip_after_the_timeout():
    runner, store, ports = _setup()
    _plan(store, ports, "east:fwd", 0.5, "SE")
    run(runner.start("p1", "bob"))
    ports.core.see_junction()  # a junction the plan does not expect, far from SE
    _ticks(runner, ports)
    _ticks(runner, ports, 1, dt=9.4)
    assert runner.running() is not None
    _ticks(runner, ports, 1, dt=0.7)
    assert runner.view("p1")["reason"] == "junction" and ports.held == ["rosy_60"]


# ---- free -----------------------------------------------------------------------------------

def test_free_trip_sends_d463_points_ahead_across_the_place_and_arrives():
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    assert ports.goals == [(0.3, 0.0)] and ports.sent == []
    _ticks(runner, ports)
    assert len(ports.goals) == 1  # the same point is not sent again
    ports.at(_arc(store, "ab:fwd"), 0.9)
    _ticks(runner, ports)
    assert ports.goals[-1] == (1.0, 0.1)  # 0.2 m ahead runs on into bc
    ports.at(_arc(store, "bc:fwd"), 0.97)
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "arrived"


def test_a_free_robot_error_fails_the_trip_and_cancels_the_goal():
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    ports.goal_error = RobotApiError("rosy_60", 409, "NAVIGATION_BUSY", "busy")
    _ticks(runner, ports)
    view = runner.view("p1")
    assert (view["state"], view["reason"]) == ("failed", "NAVIGATION_BUSY") and ports.canceled == ["rosy_60"]


# ---- pose, stall, restart, loop --------------------------------------------------------------

@pytest.mark.parametrize("state", ["DEGRADED", "UNKNOWN", None])
def test_free_pose_loss_stops_the_trip_and_leaves_the_robot_to_its_deadman(state):
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    if state is None:
        ports.pose = None
    else:
        ports.at(_arc(store, "ab:fwd"), 0.3, state=state)
    _ticks(runner, ports, 2)
    view = runner.view("p1")
    assert (view["state"], view["reason"], view["detail"]["pose_state"]) == ("stopped", "pose", state)
    assert {"sightings_filtered_map_id", "odom_refused"} <= set(view["detail"])
    assert len(ports.goals) == 1 and ports.canceled == []


def test_lane_pose_loss_turns_line_follow_off_at_once():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    ports.pose = None
    _ticks(runner, ports)
    view = runner.view("p1")
    assert view["reason"] == "pose" and ports.held == ["rosy_60"] and view["detail"]["stop_sent"]


def test_a_pose_stop_surfaces_the_provider_diagnostics():
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    ports.at(_arc(store, "ab:fwd"), 0.3, state="DEGRADED")
    ports.pose = dataclasses.replace(ports.pose, sightings_filtered_map_id=2, odom_refused={"reason": "gap"})
    _ticks(runner, ports)
    detail = runner.view("p1")["detail"]
    assert detail["sightings_filtered_map_id"] == 2 and detail["odom_refused"] == {"reason": "gap"}


def test_off_lane_beyond_half_the_width_stops_the_trip():
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    ports.at(_arc(store, "ab:fwd"), 0.4, dy=0.09)
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "running"
    ports.at(_arc(store, "ab:fwd"), 0.4, dy=0.11)
    _ticks(runner, ports)
    view = runner.view("p1")
    assert view["state"] == "stopped" and view["detail"]["off_lane_m"] == pytest.approx(0.11)


def test_no_progress_for_stall_s_stops_and_holds_the_robot():
    runner, store, ports = _setup()
    arc = _arc(store, "east:fwd")
    _plan(store, ports, "east:fwd", 0.5, "SE")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    ports.at(arc, 0.56)  # +0.06 m resets the timer
    _ticks(runner, ports, 1, dt=15)
    ports.at(arc, 0.58)  # +0.02 m is not progress
    _ticks(runner, ports, 1, dt=19.9)
    assert runner.running() is not None
    _ticks(runner, ports, 1, dt=0.2)
    view = runner.view("p1")
    assert (view["state"], view["reason"]) == ("stopped", "stall") and ports.held == ["rosy_60"]


def test_a_replan_hold_is_not_a_stall_and_free_stall_cancels_the_goal():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    ports.blocked = frozenset({"ring_e"})
    _ticks(runner, ports, 3, dt=15)
    assert runner.running()["hold"] is not None
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    _ticks(runner, ports, 1, dt=20)
    assert runner.view("p1")["reason"] == "stall" and ports.canceled == ["rosy_60"] and ports.held == []


def test_a_restart_marks_open_trips_stopped_and_stops_their_robots_once(tmp_path):
    runner, store, ports = _setup(path=tmp_path / "fleet.sqlite3")
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    store.close()
    again, store, ports = _setup(path=tmp_path / "fleet.sqlite3", period_s=0.01)
    assert again.running() is None and again.view("p1")["reason"] == "restart"

    async def briefly():
        task = asyncio.create_task(again.run())
        await asyncio.sleep(0.05)
        task.cancel()

    run(briefly())
    view = again.view("p1")
    assert ports.sent == [("stop", "SE", 0.0)] and ports.held == ["rosy_60"] and view["detail"]["stop_sent"]


def test_a_restart_halt_without_a_place_only_turns_line_follow_off(tmp_path):
    store = SiteMapStore(tmp_path / "fleet.sqlite3")
    store.put_trip({"trip_id": "t", "robot_id": "rosy_60", "state": "running", "drive_mode": "lane",
                    "next_place": None, "detail": {}})
    store.close()
    runner, store, ports = _setup(path=tmp_path / "fleet.sqlite3")
    run(runner._halt_restarted())
    assert ports.sent == [] and ports.held == ["rosy_60"]


def test_the_loop_survives_a_failing_store_and_keeps_running():
    runner, store, ports = _setup(period_s=0.01)
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))

    def broken(_trip):
        raise RuntimeError("disk full")

    store.put_trip = broken

    async def briefly():
        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.1)
        alive = not task.done()
        task.cancel()
        return alive

    assert run(briefly())
    view = runner.view("p1")
    assert (view["state"], view["reason"]) == ("failed", "TRIP_LOOP_ERROR") and ports.held == ["rosy_60"]


def test_refresh_failures_warn_at_most_every_30_seconds(caplog):
    runner, store, ports = _setup()
    _plan(store, ports, "east:fwd", 0.5, "SE")
    run(runner.start("p1", "bob"))

    async def failing(robot_id, force_rest=False):
        raise OSError("robot unreachable")

    ports.refresh = failing
    with caplog.at_level(logging.WARNING):
        _ticks(runner, ports, 5)
        _ticks(runner, ports, 1, dt=30)
    assert sum("state refresh" in r.message for r in caplog.records) == 2


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


# ---- cancel ---------------------------------------------------------------------------------

def test_lane_cancel_sends_a_stop_and_turns_line_follow_off():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    view = run(runner.cancel("p1", "bob"))
    assert view["state"] == "canceled" and view["detail"]["canceled_by"] == "bob"
    assert ports.sent[-1] == ("stop", "SE", 0.0) and ports.held == ["rosy_60"] and view["detail"]["stop_sent"]
    assert _code(runner.cancel("p1", "bob")) == "TRIP_NOT_RUNNING"
    assert _code(runner.cancel("zz", "bob")) == "TRIP_UNKNOWN"


def test_free_cancel_cancels_the_goal():
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    run(runner.cancel("p1", "bob"))
    assert ports.canceled == ["rosy_60"] and ports.held == []


def test_cancel_does_not_wait_for_a_tick_in_flight_and_that_tick_sends_nothing():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    pose = ports.pose

    async def scenario():
        gate = asyncio.Event()

        async def slow_pose(robot_id):
            await gate.wait()
            return pose

        ports.arbitrated_pose = slow_pose
        tick = asyncio.create_task(runner.tick())
        await asyncio.sleep(0)
        view = await asyncio.wait_for(runner.cancel("p1", "bob"), 1.0)  # the tick holds the lock
        gate.set()
        await tick
        return view

    view = run(scenario())
    assert view["state"] == "canceled" and ports.held == ["rosy_60"]
    assert [s for s in ports.sent if s[0] != "stop"] == []


def test_a_send_in_flight_when_cancel_lands_is_stopped_again():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    send = ports.send_junction

    async def scenario():
        gate = asyncio.Event()

        async def slow_send(*args, **kwargs):
            if args[1] != "stop":
                await gate.wait()
            return await send(*args, **kwargs)

        ports.send_junction = slow_send
        tick = asyncio.create_task(runner.tick())
        await asyncio.sleep(0.01)
        await asyncio.wait_for(runner.cancel("p1", "bob"), 1.0)
        gate.set()
        await tick

    run(scenario())
    assert runner.view("p1")["state"] == "canceled"  # the refused late send does not rewrite it
    assert ports.sent[-1] == ("stop", "SE", 0.0) and "rosy_60" in ports.held


def test_every_halt_step_is_tried_whatever_the_robot_raises():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))

    async def refuse(robot_id):
        raise KeyError("odd client")

    ports.hold = refuse
    ports.junction_error = RobotApiError("rosy_60", 409, "DOCKING_ACTIVE", "busy")
    view = run(runner.cancel("p1", "bob"))
    assert view["state"] == "canceled" and view["detail"]["stop_sent"] is False
    assert view["detail"]["error"] == "KeyError"


def test_robot_calls_are_bounded():
    runner, store, ports = _setup(port_timeout_s=0.05)
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))

    async def stuck(robot_id):
        await asyncio.sleep(5)

    ports.junction_state = stuck
    started = time.monotonic()
    _ticks(runner, ports)
    assert time.monotonic() - started < 2.0 and runner.view("p1")["reason"] == "TRIP_ROBOT_UNREACHABLE"


# ---- replan ---------------------------------------------------------------------------------

def test_a_blocked_lane_replans_at_the_next_place_holds_with_a_measured_stop_then_resumes():
    runner, store, ports = _setup()
    ring_s = _arc(store, "ring_s:fwd")
    plan = _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    assert [s[0] for s in plan.segments] == ["ring_s", "ring_e", "ring_n"]
    run(runner.start("p1", "bob"))
    assert _code(runner.confirm_replan("p1", "bob")) == "TRIP_NO_REPLAN"
    ports.blocked = frozenset({"ring_e"})
    _ticks(runner, ports)
    view = runner.running()
    assert view["hold"]["reason"] == "replan" and [s["edge_id"] for s in view["hold"]["plan"]["segments"]][1] == "east"
    assert ports.sent == [("stop", "SE", round(ring_s.length_m - 0.1, 3))]
    ports.at(ring_s, ring_s.length_m - 0.05)
    _ticks(runner, ports, 4)
    assert len(ports.sent) == 1  # held by CORE: no new stop
    view = run(runner.confirm_replan("p1", "bob"))
    assert view["hold"] is None and [s["edge_id"] for s in view["plan"]["segments"]][:2] == ["ring_s", "east"]
    _ticks(runner, ports)
    assert ports.sent[-1][1] == "SE" and ports.sent[-1][0] != "stop"  # our held stop is replaced


def test_a_replan_with_the_same_route_does_not_hold():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    ports.blocked = frozenset({"west"})
    _ticks(runner, ports)
    assert runner.running()["hold"] is None and ports.sent[0][0] == "straight"


def test_confirm_after_the_map_changed_plans_again_at_the_place():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    ports.blocked = frozenset({"ring_e"})
    _ticks(runner, ports)
    assert runner.running()["hold"]["map_version"] == 1
    _activate_again(store)
    assert _code(runner.confirm_replan("p1", "bob")) == "TRIP_MAP_CHANGED"
    _ticks(runner, ports)
    assert runner.running()["hold"]["map_version"] == 2
    assert run(runner.confirm_replan("p1", "bob"))["map_version"] == 2


# ---- config, ports ----------------------------------------------------------------------------

def test_trip_config_reads_fleet_trip_and_refuses_bad_values(tmp_path):
    from fleet import cli

    config = tmp_path / "site.yaml"
    config.write_text("fleet:\n  trip:\n    stall_s: 35\n", encoding="utf-8")
    assert cli._trip_config(cli.parse_args(["console", "--site-config", str(config)])).stall_s == 35
    assert TripConfig.from_mapping(None).stall_s == 20.0
    for bad in ({"stall_s": 0}, {"stall_s": True}, {"nope": 1}):
        with pytest.raises(ValueError):
            TripConfig.from_mapping(bad)


def test_the_http_junction_port_uses_the_robot_client():
    class Client:
        modes: list = []

        async def line_follow_junction(self, action, place_id, *, stop_after_m, expires_s, turn_deg, advance_m):
            return {"args": (action, place_id, stop_after_m, expires_s, turn_deg)}

        async def state(self):
            return {"line_follow": {"junction": {"state": "turning", "seq": 3}}}

        async def line_follow(self):
            return {"mode": "CAMERA_LINE"}

        async def line_follow_mode(self, mode):
            self.modes.append(mode)
            return {"mode": mode}

    client = Client()
    port = HttpLaneJunction(lambda: {"r": client})
    assert run(port.send_junction("r", "left", "NE", None, 15.0, turn_deg=88.0)) == {
        "args": ("left", "NE", None, 15.0, 88.0)}
    assert run(port.junction_state("r"))["state"] == "turning"
    assert run(port.line_follow_mode("r")) == "CAMERA_LINE"
    run(port.hold("r"))
    assert client.modes == ["OFF"]
    with pytest.raises(HubError) as err:
        run(port.send_junction("x", "left", "NE", None, 15.0))
    assert err.value.code == "UNKNOWN_ROBOT"


def test_http_robot_client_line_follow_junction_hits_the_core_path():
    seen = {}

    def handler(request):
        seen["path"], seen["body"] = request.url.path, json.loads(request.content)
        return httpx.Response(404, json={"error": {"code": "HTTP_404", "message": "nope"}})

    async def go():
        async with httpx.AsyncClient(base_url="http://robot", transport=httpx.MockTransport(handler)) as http:
            client = HttpRobotClient(RobotEndpoint("one", "http://robot", "t"), http=http)
            await client.line_follow_junction("right", "SE", stop_after_m=None, expires_s=15.0, turn_deg=-91.5)

    with pytest.raises(RobotApiError) as err:
        run(go())
    assert err.value.status == 404 and seen["path"] == "/api/v1/line-follow/junction"
    assert seen["body"] == {"action": "right", "place_id": "SE", "expires_s": 15.0, "turn_deg": -91.5}


# ---- API --------------------------------------------------------------------------------------

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
    return TestClient(app), tasks, store, robot, console


def test_trip_api_start_status_cancel_need_a_named_operator_and_are_audited(tmp_path):
    ports = Ports()
    client, tasks, store, _robot, _console = _app(tmp_path, ports)
    ports.now = time.time()
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


def test_a_robot_on_a_trip_refuses_other_fleet_motion(tmp_path):
    ports = Ports()
    client, tasks, store, robot, console = _app(tmp_path, ports)
    ports.now = time.time()
    plan = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()
    assert client.post(f"/api/fleet/trips/{plan['plan_id']}/start", headers=OPERATOR).status_code == 200
    busy = {**OPERATOR, "Idempotency-Key": "k1"}
    for path, body in (("/api/fleet/robots/rosy_60/goal", {"x": 0.1, "y": 0.0, "yaw": 0.0}),
                       ("/api/fleet/robots/rosy_60/route", {"edges": ["ring_s"]})):
        response = client.post(path, json=body, headers=busy)
        assert response.status_code == 409 and response.json()["detail"]["code"] == "TRIP_ROBOT_BUSY", path
    assert not tasks.store.queued_task_ids()
    with pytest.raises(HubError) as err:  # task dispatch goes through the same goal path
        run(console.goal("rosy_60", 0.1, 0.0, 0.0))
    assert err.value.code == "TRIP_ROBOT_BUSY"
    with pytest.raises(HubError) as err:
        run(console.formation_start("rosy_60", members=["rosy_60", "rosy_60x"]))
    assert err.value.code in ("TRIP_ROBOT_BUSY", "UNKNOWN_ROBOT")
    assert not [c for c in robot.calls if c[0] == "navigation_goal"]
    client.post(f"/api/fleet/trips/{plan['plan_id']}/cancel", headers=OPERATOR)
    assert client.post("/api/fleet/robots/rosy_60/goal", json={"x": 0.1, "y": 0.0, "yaw": 0.0},
                       headers={**OPERATOR, "Idempotency-Key": "k2"}).status_code == 200


def test_formation_refuses_a_robot_on_a_trip():
    robots = [FakeRobot("a"), FakeRobot("b")]
    console = FleetConsole([RobotEndpoint(r.robot_id, "http://x", "t") for r in robots], robots)
    console.trip_busy = lambda robot_id: robot_id == "b"
    with pytest.raises(HubError) as err:
        run(console.formation_start("a"))
    assert err.value.code == "TRIP_ROBOT_BUSY"


def test_default_wiring_refuses_start_until_the_providers_land(tmp_path):
    from test_site_map_trip import _app as plain_app, _on_ring_s

    client, _tasks, store, robot = plain_app(tmp_path)
    robot._state = _on_ring_s(store)
    plan = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()
    refused = client.post(f"/api/fleet/trips/{plan['plan_id']}/start", headers=OPERATOR)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "TRIP_ROBOT_CAPS_UNKNOWN"
