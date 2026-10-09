"""D-494 5: the server trip loop against a fake CORE junction (D-494 4 / D-495) and fake ports."""

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
from fleet.localization.map_pose import MapPose
from fleet.server.console_view import TripCaps
from fleet.server.trip_ports import HttpLaneJunction, TripConfig
from fleet.server import trip_runner
from core_features.line_follow.recovery.junction.gate import MANEUVER as CORE_MANEUVER
from fleet.server.trip_runner import TripError, TripRunner
from fleet.site_map import SiteMap, from_lane_graph
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient, RobotApiError

ROOT = Path(__file__).resolve().parents[3]
LANE_GRAPH = ROOT / "middleware" / "perception" / "map" / "map_v2_fleet" / "lane_graph.yaml"
OPERATOR = {"Authorization": "Bearer operator-token"}
VIEWER = {"Authorization": "Bearer viewer-token"}
# D-507 2 (2026-10-08): a turn goes only with a window, which only a junction_pivot robot takes.
LANE = TripCaps("pinky_pro", frozenset({"lane"}), 0.2, junction_turn=True, junction_pivot=True)
BOTH = TripCaps("pinky_pro", frozenset({"lane", "free"}), 0.2, junction_turn=True)
MANOEUVRE = CORE_MANEUVER  # the fake CORE is busy exactly when CORE is


class FakeCore:
    """CORE ``line_follow/junction.py`` as Fleet sees it (feat/d491-core-junction-action).

    One instruction; ``seq`` counts accepted ones. Only CAMERA_LINE takes one (IR_LINE 409
    JUNCTION_CAMERA_ONLY, M4), and only with manual control released (409 MODE_CONFLICT, L6).
    ``straight`` and a turn with ``turn_deg`` arm, ``stop`` executes at once and holds after
    ``stop_after_m`` of travel from receipt or at a sighted junction, whichever first (M7); a
    turn without ``turn_deg`` is ``unresolved``. During a manoeuvre the identical instruction is
    a no-op (M3) and a different one aborts it unaccepted. A place whose action ran (straight
    through, or a turn past its turning phase) refuses the same action again (409
    JUNCTION_ALREADY_DONE, R1). An armed instruction expires to idle. The test drives the robot
    side: ``see_junction``, ``phase``, ``done``.
    """

    def __init__(self, ports) -> None:
        self.ports = ports
        self.mode = "CAMERA_LINE"
        self.manual_released = True
        self.seq = 0
        self.j: dict | None = None
        self.done_place: tuple | None = None

    def _xy(self):
        pose = self.ports.pose
        return (pose.x, pose.y) if pose is not None else (0.0, 0.0)

    def send(self, action, place_id, stop_after_m, expires_s, turn_deg):
        if not self.manual_released:
            raise RobotApiError("rosy_60", 409, "MODE_CONFLICT", "manual control is held")
        if self.mode == "IR_LINE":
            raise RobotApiError("rosy_60", 409, "JUNCTION_CAMERA_ONLY", "IR has no junction detection")
        if self.mode != "CAMERA_LINE":
            raise RobotApiError("rosy_60", 409, "LINE_FOLLOW_NOT_ACTIVE", "line follow is off")
        if not 0 < expires_s <= 30 or (stop_after_m is not None and (action != "stop" or not 0 <= stop_after_m <= 2)) \
                or (turn_deg is not None and action != "bend" and (
                    action not in ("left", "right") or not 0 < abs(turn_deg) <= 150
                    or (turn_deg > 0) != (action == "left")))                 or (action == "bend" and (turn_deg is None or not 0 < abs(turn_deg) <= 90)):
            raise RobotApiError("rosy_60", 400, "VALIDATION_ERROR", "bad junction instruction")
        if self.done_place == (place_id, action):
            raise RobotApiError("rosy_60", 409, "JUNCTION_ALREADY_DONE", f"{action} at {place_id} already ran")
        j = self.j
        if j is not None and j["state"] in MANOEUVRE:
            if (j["action"], j["place_id"], j.get("turn_deg")) == (action, place_id, turn_deg):
                return {"accepted": True, "junction_seq": j["seq"], "state": j["state"]}  # M3 no-op
            self._mark_done()
            j.update(state="aborted", reason="new_instruction")
            return {"accepted": False, "junction_seq": j["seq"], "state": "aborted"}
        if self.done_place is not None and self.done_place[0] != place_id:
            self.done_place = None
        self.seq += 1
        state = ("armed" if action in ("straight", "bend") or turn_deg is not None
                 else "executing" if action == "stop" else "unresolved")
        self.j = {"action": action, "place_id": place_id, "seq": self.seq, "state": state, "reason": None,
                  "expires_at": self.ports.now + expires_s, "stop_after_m": stop_after_m or 0.0,
                  "from": self._xy(), "held": False, "turn_deg": turn_deg}
        return {"accepted": True, "junction_seq": self.seq, "state": state}

    def _mark_done(self):
        j = self.j
        if j is not None and j.get("place_id") is not None and (
                j["state"] in ("advancing", "reacquiring") or j["action"] == "straight"):
            self.done_place = (j["place_id"], j["action"])

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
        elif j["action"] == "stop":
            j["held"] = True  # M7: a stop also holds at the junction it sees

    def phase(self, state):
        self.j["state"] = state

    def done(self):
        self._mark_done()
        self.j = None

    def off(self):
        self.mode = "OFF"
        if self.j is not None and self.j["state"] in MANOEUVRE:
            self._mark_done()
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
        self.advances: list = []
        self.expects: list = []  # D-507 2 fields per send (None: not sent)
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
                            advance_m=None, expect=None):
        if self.junction_error is not None:
            raise self.junction_error
        reply = self.core.send(action, place_id, stop_after_m, expires_s, turn_deg)
        self.sent.append((action, place_id, None if stop_after_m is None else round(stop_after_m, 3)))
        self.turns.append(turn_deg)
        self.advances.append(advance_m)
        self.expects.append(expect)
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
    runner = TripRunner(store=store, routing_config=store.routing_config, caps=ports.caps_for, poses=ports,
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
    assert core.send("left", "B", None, 15, 90.0) == {"accepted": True, "junction_seq": 2, "state": "armed"}
    core.see_junction()
    assert core.status()["state"] == "turning"
    assert core.send("left", "B", None, 15, 90.0) == {"accepted": True, "junction_seq": 2, "state": "turning"}
    core.phase("advancing")
    assert core.send("straight", "C", None, 15, None) == {"accepted": False, "junction_seq": 2, "state": "aborted"}
    assert core.status()["state"] == "aborted"
    with pytest.raises(RobotApiError) as err:  # past its turn: the place's left already ran
        core.send("left", "B", None, 15, 90.0)
    assert err.value.code == "JUNCTION_ALREADY_DONE"
    assert core.send("left", "E", None, 15, None)["accepted"] and core.status()["state"] == "unresolved"
    assert core.send("straight", "B", None, 1, None)["accepted"]
    ports.now += 2
    assert core.status() == {"pending_action": None, "place_id": None, "state": "idle", "seq": 4, "reason": None}
    with pytest.raises(RobotApiError):
        core.send("right", "B", None, 15, 30.0)  # right takes a negative angle
    for mode, released, code in (("IR_LINE", True, "JUNCTION_CAMERA_ONLY"), ("OFF", True, "LINE_FOLLOW_NOT_ACTIVE"),
                                 ("CAMERA_LINE", False, "MODE_CONFLICT")):
        core.mode, core.manual_released = mode, released
        with pytest.raises(RobotApiError) as err:
            core.send("stop", "D", 0.0, 15, None)
        assert err.value.code == code
    core.mode, core.manual_released = "CAMERA_LINE", True
    ports.pose = dataclasses.replace(ports.pose, x=0.0)
    core.send("stop", "D", 1.0, 15, None)
    core.see_junction()
    assert core.j["held"]  # M7: at the junction before the distance


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
    ports.core.mode = "IR_LINE"  # no junction detection on IR (M4)
    assert _code(runner.start("p1", "bob")) == "TRIP_LINE_FOLLOW_NOT_ACTIVE"
    ports.core.mode = "CAMERA_LINE"
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
    assert _code(runner.start("p2", "bob")) == "TRIP_BUSY"  # this robot already has an open trip (D-517 1)



def test_d593_a_still_operator_pin_starts_up_to_its_anchor_age_limit():
    """D-593 7 (user 2026-10-10): a pin older than 2 s starts only while odom has not moved."""
    def pin(moved_m=0.0, turned_deg=0.0, anchor=8.0, source="operator_pin"):
        x, y, yaw = ring_s.point_at(0.1)
        ports.pose = MapPose(x, y, yaw, "LOCALIZED", source, moved_m, 0.1, anchor,
                             anchor_source=source, bridge_turn_deg=turned_deg)

    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    ports.core.mode = "CAMERA_LINE"
    ring_s = _arc(store, "ring_s:fwd")
    for kwargs in ({"moved_m": 0.03}, {"turned_deg": 2.5}, {"source": "sighting"}):
        pin(**kwargs)
        assert _code(runner.start("p1", "bob")) == "TRIP_POSE_UNTRUSTED"
    pin(moved_m=0.02, turned_deg=2.0)
    assert run(runner.start("p1", "bob"))["state"] == "started"


def test_d593_pin_still_thresholds_are_bounded():
    with pytest.raises(ValueError):
        TripConfig(pin_start_still_m=0.2)
    with pytest.raises(ValueError):
        TripConfig(pin_start_still_deg=15.0)

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
    # keep-mode evidence is needed for any lane plan, a stop-only one included (D-495)
    ("lane", "bc:fwd", 0.5, "C", TripCaps("pinky_pro", frozenset({"lane"}), 0.2), "JUNCTION_TURN_UNSUPPORTED"),
])
def test_plans_a_lane_robot_cannot_run_are_refused(site_map, arc, s, to, caps, reason):
    runner, store, ports = _setup(_free_map(site_map), caps=caps)
    _plan(store, ports, arc, s, to)
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.code == "TRIP_MODE_UNSUPPORTED" and err.value.detail["reason"] == reason


def test_a_turn_sharper_than_the_bound_is_refused_for_lane_robots():
    runner, store, ports = _setup(_free_map("lane"), max_turn_deg=80.0)  # 150 by default (D-495)
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
    runner, store, ports = _setup(_free_map("lane"), junction_expires_s=2.0)
    _plan(store, ports, "ab:fwd", 0.5, "C")
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
    assert ports.advances == [0.10]  # D-507 4: the advance turn_deg was aimed for, sent explicitly
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


def test_fleet_counts_every_core_manoeuvre_state_as_busy():
    """Lap SIM B (3/20): Fleet's list lacked CORE's D-507 4 ``approaching``; one list, checked."""
    assert set(trip_runner.MANOEUVRE) == set(CORE_MANEUVER)


def test_no_instruction_goes_out_while_core_approaches_the_pivot_past_the_place():
    """Lap SIM B: mid-approach the map pose is already on the next lane; the next place's
    instruction would abort the turn (CORE answers ``aborted``, Fleet stops the trip)."""
    runner, store, ports = _setup(_map(("A", 0, 0), ("B", 1, 0), ("C", 1, 0.5), edges=[
        ("ab", "A", "B", [[0, 0], [1, 0]], "lane"), ("bc", "B", "C", [[1, 0], [1, 0.5]], "lane")]))
    ab, bc = _arc(store, "ab:fwd"), _arc(store, "bc:fwd")
    _plan(store, ports, "ab:fwd", 0.5, "C")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    assert ports.sent == [("left", "B", None)]
    ports.at(ab, ab.length_m - 0.05)
    ports.core.see_junction()
    ports.core.phase("approaching")
    _ticks(runner, ports)
    ports.at(bc, 0.05)  # the approach drives past the place point onto the next lane
    _ticks(runner, ports, 10)
    assert ports.sent == [("left", "B", None)] and runner.running()["state"] == "running"
    ports.core.done()  # the turn ends: the next place's instruction goes out
    _ticks(runner, ports)
    assert ports.sent[-1] == ("stop", "C", pytest.approx(0.45, abs=0.01))


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
    """Within ``arm_distance_m`` of the place (D-507 3: beyond it ``waiting`` ends the trip at once)."""
    runner, store, ports = _setup()
    _plan(store, ports, "east:fwd", 0.5, "SE")
    run(runner.start("p1", "bob"))
    east = _arc(store, "east:fwd")
    ports.at(east, east.length_m - 0.5)
    _ticks(runner, ports)
    assert ports.sent[-1][0] == "stop"  # sent once, never again
    ports.core.j = None
    ports.core.see_junction()  # CORE waits at a junction 0.5 m before SE
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


def test_each_trip_step_renews_the_goal_lease_and_a_failed_renewal_keeps_the_trip():
    """D-550 10: the trip loop is the renewer of trip goals; a renewal error is left to CORE."""
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    renewed = []

    async def renew(robot_id):
        renewed.append(robot_id)
        if len(renewed) == 2:
            raise ConnectionError("no route")

    runner._renew_lease = renew
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports, n=3)
    assert renewed == ["rosy_60"] * 3 and runner.view("p1")["state"] == "running"


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
    run(runner.halts.halt_restarted())
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

        async def line_follow_junction(self, action, place_id, *, stop_after_m, expires_s, turn_deg, advance_m,
                                       expect=None):
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
                     trip_caps_port=ports.caps_for, map_pose_port=ports, lane_junction=ports)
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

    # D-494 5: the activation guard is "a running trip exists"
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


class _TripOf:
    """A runner stand-in for the guard: ``robot`` is on a trip."""

    def __init__(self, robot):
        self.robot, self.canceled = robot, []

    def robot_busy(self, robot_id):
        return robot_id == self.robot

    def open_trips(self):
        return [{"robot_id": self.robot}] if self.robot else []

    async def cancel_robot(self, robot_id, reason):
        self.canceled.append((robot_id, reason))


def _guarded(*ids, trip="b"):
    from fleet.server.trip_guard import install_trip_guard

    robots = [FakeRobot(robot_id) for robot_id in ids]
    console = FleetConsole([RobotEndpoint(r.robot_id, "http://x", "t") for r in robots], robots)
    runner = _TripOf(trip)
    install_trip_guard(console, runner)
    return console, runner, robots


def test_formation_refuses_a_robot_on_a_trip():
    console, _runner, _robots = _guarded("a", "b")
    with pytest.raises(HubError) as err:
        run(console.formation_start("a"))
    assert err.value.code == "TRIP_ROBOT_BUSY"


def test_a_trip_robot_never_yields_and_is_not_a_reassignment_candidate(monkeypatch):
    import fleet.server.console as console_module

    console, _runner, robots = _guarded("a", "b", "c")
    monkeypatch.setattr(console_module.bays, "best_bay", lambda *args, **kwargs: (2.0, 2.0))

    async def no_map():
        return {}

    console.map = no_map
    console._pose_of = lambda robot_id: (0.5, 0.0)
    result = run(console._make_room("a", 1.0, 0.0, 0.0, [(0.0, 0.0), (1.0, 0.0)], ["b", "c"]))
    assert result["no_space"] == ["b"] and result["yielding"] == ["c"]
    assert not [c for c in robots[1].calls if c[0] == "navigation_goal"]
    rows = [{"robot_id": rid, "online": True, "state": {"capabilities_degraded": rid == "a"}} for rid in "abc"]
    console._goals["a"] = {"x": 1.0, "y": 0.0, "yaw": 0.0}
    console._queued.pop("c", None)
    console._goals.pop("c", None)
    console._yielding.clear()
    run(console._run_traffic(rows))
    assert "b" not in console._queued and "b" not in console._goals
    assert (console._queued.get("c") or console._goals.get("c"))["x"] == 1.0  # c took the mission


def test_line_follow_off_stops_and_cancels_the_trip_other_modes_are_refused():
    console, runner, robots = _guarded("a", "b")
    with pytest.raises(HubError) as err:
        run(console.line_follow_mode("b", "IR_LINE"))
    assert err.value.code == "TRIP_ROBOT_BUSY"
    run(console.line_follow_mode("b", "OFF"))
    assert ("line_follow_mode", "OFF") in robots[1].calls and runner.canceled == [("b", "operator_line_follow_off")]
    run(console.line_follow_mode("a", "IR_LINE"))  # another robot is not affected
    assert runner.canceled == [("b", "operator_line_follow_off")]


def test_cancel_robot_ends_the_trip_with_the_reason():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    run(runner.cancel_robot("rosy_60", "operator_line_follow_off"))
    view = runner.view("p1")
    assert (view["state"], view["reason"], view["detail"]["canceled_by"]) == (
        "canceled", "operator_line_follow_off", None)


def test_default_wiring_refuses_start_until_the_providers_land(tmp_path):
    from test_site_map_trip import _app as plain_app, _on_ring_s

    client, _tasks, store, robot = plain_app(tmp_path)
    robot._state = _on_ring_s(store)
    plan = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()
    refused = client.post(f"/api/fleet/trips/{plan['plan_id']}/start", headers=OPERATOR)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "TRIP_ROBOT_CAPS_UNKNOWN"


# ---- re-review R1-R8 ----------------------------------------------------------------------

@pytest.mark.parametrize("reply", [{"accepted": False, "queued": True, "reason": "ROUTE_CONFLICT"},
                                   {"accepted": False, "queued": False, "reason": "YIELDED"}])
def test_a_goal_the_console_did_not_send_fails_the_trip_and_clears_its_queue(reply):
    released = []
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    runner._release_queue = released.append
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))

    async def refused(robot_id, x, y, yaw):
        return reply

    ports.goal = refused
    runner._goal = refused
    _ticks(runner, ports)
    view = runner.view("p1")
    assert (view["state"], view["reason"], view["detail"]["goal_reason"]) == (
        "failed", "TRIP_GOAL_REFUSED", reply["reason"])
    assert ports.canceled == ["rosy_60"] and released == ["rosy_60"]


def test_a_free_arrival_clears_the_robots_console_queue():
    released = []
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    runner._release_queue = released.append
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    ports.at(_arc(store, "bc:fwd"), 0.97)
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "arrived" and released == ["rosy_60"]


def test_start_refuses_a_robot_that_already_moves_for_the_console():
    runner, store, ports = _setup()
    runner._engaged = lambda robot_id: "yielding"
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert (err.value.status, err.value.code, err.value.detail) == (409, "TRIP_ROBOT_BUSY", {"reason": "yielding"})


def test_engaged_reads_queue_goal_yield_and_formation():
    from fleet.server.trip_guard import engaged

    console, _runner, _robots = _guarded("a", "b")
    assert engaged(console, "a") is None
    console._goals["a"] = {"x": 0, "y": 0, "yaw": 0}
    assert engaged(console, "a") is None  # a finished goal is still shown; it does not count
    console._seen["a"] = {"navigation": "NAVIGATING"}
    assert engaged(console, "a") == "goal"
    console._goals.clear()
    console._queued["a"] = {"x": 0}
    assert engaged(console, "a") == "queued"
    console._queued.clear()
    console._yielding["a"] = {"for": "b"}
    assert engaged(console, "a") == "yielding"


def test_a_carried_out_instruction_is_never_sent_again():
    runner, store, ports = _setup(junction_expires_s=2.0)
    ring_s = _arc(store, "ring_s:fwd")
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    ports.core.see_junction()  # CORE executes our straight through SE
    _ticks(runner, ports)
    assert runner._live["rosy_60"].sent["carried"]
    ports.core.j = None  # CORE went idle without our seeing it finish; SE is 0.32 m ahead
    ports.at(ring_s, 0.05)
    _ticks(runner, ports, 3, dt=3.0)
    assert len(ports.sent) == 1


def test_a_carried_out_place_short_of_the_next_lane_keeps_the_pose_on_this_lane():
    """lap SIM 2 lap_12: CORE went idle on our straight while the robot backed off 0.26 m before
    SE; the pose is judged against ring_s, not ring_e (0.276 m away), so no false 'pose' stop."""
    runner, store, ports = _setup()
    ring_s = _arc(store, "ring_s:fwd")
    _plan(store, ports, "ring_s:fwd", 0.05, "NW")
    run(runner.start("p1", "bob"))
    ports.at(ring_s, ring_s.length_m - 0.2)
    _ticks(runner, ports)
    ports.core.see_junction()  # CORE executes our straight through SE
    _ticks(runner, ports)
    assert runner._live["rosy_60"].sent["carried"]
    ports.core.j = None  # CORE closed it (the keeper lost the junction while backing off)
    ports.at(ring_s, ring_s.length_m - 0.26)
    sent = len(ports.sent)
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "running" and runner.view("p1")["segment_index"] == 0
    assert len(ports.sent) == sent                         # the carried-out straight is not sent again
    ports.at(_arc(store, "ring_e:fwd"), 0.03)               # on the next lane: it moves on
    _ticks(runner, ports)
    assert runner.view("p1")["segment_index"] == 1


def test_already_done_from_core_counts_as_carried_out():
    runner, store, ports = _setup()
    ring_s = _arc(store, "ring_s:fwd")
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    ports.core.done_place = ("SE", "straight")  # it ran between two ticks
    ports.at(ring_s, ring_s.length_m - 0.02)
    _ticks(runner, ports)
    assert runner.running() is not None and runner._live["rosy_60"].sent["done"]
    _ticks(runner, ports)
    assert runner.running()["segment_index"] == 1 and ports.sent[-1] == ("straight", "NE", None)


def test_lane_arrival_needs_our_accepted_stop_and_accepts_core_holding_it():
    runner, store, ports = _setup()
    arc = _arc(store, "east:fwd")
    _plan(store, ports, "east:fwd", 0.5, "SE")
    run(runner.start("p1", "bob"))
    ports.core.manual_released = False  # the stop is refused: no arrival on distance alone
    ports.at(arc, arc.length_m - 0.05)
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "failed" and runner.view("p1")["reason"] == "MODE_CONFLICT"
    runner, store, ports = _setup()
    _plan(store, ports, "east:fwd", 0.5, "SE")
    run(runner.start("p1", "bob"))
    ports.at(arc, arc.length_m - 0.25)
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "running"  # stop sent this tick
    ports.core.see_junction()  # CORE holds our stop at the junction it sighted (M7)
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "arrived"


def test_confirm_replan_forgets_the_last_instruction():
    runner, store, ports = _setup()
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    ports.blocked = frozenset({"ring_e"})
    _ticks(runner, ports)
    held = runner._live["rosy_60"].sent["seq"]
    run(runner.confirm_replan("p1", "bob"))
    assert runner._live["rosy_60"].sent is None and runner._live["rosy_60"].replaceable == held


def test_the_restart_halt_is_retried_until_it_takes_or_the_robot_leaves(tmp_path):
    store = SiteMapStore(tmp_path / "fleet.sqlite3")
    for trip_id, robot_id in (("t1", "rosy_60"), ("t2", "gone")):
        store.put_trip({"trip_id": trip_id, "robot_id": robot_id, "state": "running", "drive_mode": "lane",
                        "next_place": None, "detail": {}})
    store.close()
    runner, store, ports = _setup(path=tmp_path / "fleet.sqlite3")
    runner.halts.roster = lambda: ["rosy_60"]
    hold = ports.hold
    calls = []

    async def flaky(robot_id):
        calls.append(robot_id)
        if len(calls) == 1:
            raise OSError("robot unreachable")
        return await hold(robot_id)

    ports.hold = flaky
    run(runner.halts.halt_restarted())
    assert [t["robot_id"] for t in runner.halts.restarted] == ["rosy_60"]  # "gone" left the roster
    run(runner.halts.halt_restarted())
    assert runner.halts.restarted == [] and calls == ["rosy_60", "rosy_60"]
    assert store.trip("t1")["detail"]["stop_sent"] is True


def test_robot_routes_refuse_a_trip_robot(tmp_path):
    ports = Ports()
    client, _tasks, _store, robot, _console = _app(tmp_path, ports)
    ports.now = time.time()
    plan = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()
    assert client.post(f"/api/fleet/trips/{plan['plan_id']}/start", headers=OPERATOR).status_code == 200
    stuck = client.post("/api/fleet/robots/rosy_60/line-stuck/decision",
                        json={"stuck_id": "s1", "decision": "RESUME"}, headers=OPERATOR)
    assert stuck.status_code == 409 and stuck.json()["detail"]["code"] == "TRIP_ROBOT_BUSY"
    ir = client.post("/api/fleet/robots/rosy_60/line-follow", json={"mode": "IR_LINE"}, headers=OPERATOR)
    assert ir.status_code == 409 and ir.json()["detail"]["code"] == "TRIP_ROBOT_BUSY"
    off = client.post("/api/fleet/robots/rosy_60/line-follow", json={"mode": "OFF"}, headers=OPERATOR)
    assert off.status_code == 200 and ("line_follow_mode", "OFF") in robot.calls
    view = client.get(f"/api/fleet/trips/{plan['plan_id']}", headers=VIEWER).json()
    assert (view["state"], view["reason"]) == ("canceled", "operator_line_follow_off")


def test_start_through_the_api_refuses_a_robot_with_a_queued_console_mission(tmp_path):
    ports = Ports()
    client, _tasks, _store, _robot, console = _app(tmp_path, ports)
    ports.now = time.time()
    plan = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()
    console._queued["rosy_60"] = {"x": 0.0, "y": 0.0, "yaw": 0.0, "reason": "ROUTE_CONFLICT"}
    refused = client.post(f"/api/fleet/trips/{plan['plan_id']}/start", headers=OPERATOR)
    assert refused.status_code == 409 and refused.json()["detail"] == {
        "code": "TRIP_ROBOT_BUSY", "detail": {"reason": "queued"}}


def test_an_aborted_place_is_never_sent_again_even_back_in_camera_line():
    runner, store, ports = _setup(_free_map("lane"))
    _plan(store, ports, "ab:fwd", 0.5, "C")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    ports.core.see_junction()  # turning at B
    ports.core.off()  # e.g. the driver released: CORE aborts the turn
    ports.core.mode = "CAMERA_LINE"  # back in camera line follow, 'aborted' still shown
    _ticks(runner, ports, 3)
    view = runner.view("p1")
    assert (view["state"], view["reason"], view["detail"]["junction_state"]) == ("stopped", "junction", "aborted")
    assert ports.sent == [("left", "B", None), ("stop", "B", 0.0)]  # only the halt's stop after it


def test_an_instruction_that_aborts_a_manoeuvre_stops_the_trip():
    runner, store, ports = _setup(_free_map("lane"))
    _plan(store, ports, "ab:fwd", 0.5, "C")
    run(runner.start("p1", "bob"))
    ports.core.send("left", "Z", None, 15, 45.0)  # someone else's turn, already running
    ports.core.see_junction()
    ports.state_none = True  # Fleet cannot see it, sends ours, and CORE aborts its turn instead
    _ticks(runner, ports)
    view = runner.view("p1")
    assert (view["state"], view["reason"], view["detail"]["junction_state"]) == ("stopped", "junction", "aborted")


# ---- safety review H1, M1-M3, L1, N2-N4 ---------------------------------------------------

def _trip_app(tmp_path):
    ports = Ports()
    client, tasks, store, robot, console = _app(tmp_path, ports)
    ports.now = time.time()
    plan = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()
    assert client.post(f"/api/fleet/trips/{plan['plan_id']}/start", headers=OPERATOR).status_code == 200
    return client, robot, console, plan["plan_id"], ports


@pytest.mark.parametrize(("path", "call", "reason"), [
    ("/api/fleet/robots/rosy_60/cancel", "navigation_cancel", "operator_cancel"),
    ("/api/fleet/cancel-all", "navigation_cancel", "operator_cancel"),
    ("/api/fleet/estop", "estop", "operator_estop"),
])
def test_every_operator_stop_reaches_the_robot_and_ends_the_trip(tmp_path, path, call, reason):
    client, robot, _console, trip_id, ports = _trip_app(tmp_path)
    response = client.post(path, headers=OPERATOR)
    assert response.status_code == 200, response.text
    assert [c for c in robot.calls if c[0] == call]
    view = client.get(f"/api/fleet/trips/{trip_id}", headers=VIEWER).json()
    assert (view["state"], view["reason"]) == ("canceled", reason)
    assert ports.held == ["rosy_60"]  # the trip's own halt (lane) ran too
    run(client.app.state.trip_runner.tick())
    assert ports.sent == [("stop", "SE", 0.0)]  # nothing re-sent after the stop


def test_create_app_wraps_every_console_motion_and_stop_method(tmp_path):
    _client, _robot, console, _trip_id, _ports = _trip_app(tmp_path)
    for name in ("goal", "formation_start", "formation_reform", "formation_resume", "line_follow_mode",
                 "cancel", "estop_all"):
        assert getattr(console, name).__name__ == f"guarded_{name}", name


def test_line_follow_off_ends_the_trip_even_when_the_robot_call_fails():
    console, runner, robots = _guarded("a", "b")
    robots[1].line_follow_mode = None  # the robot call raises

    async def failing(mode):
        raise OSError("robot unreachable")

    robots[1].line_follow_mode = failing
    with pytest.raises(OSError):
        run(console.line_follow_mode("b", "OFF"))
    assert runner.canceled == [("b", "operator_line_follow_off")]


def test_formation_reform_and_resume_refuse_a_trip_robot():
    console, _runner, _robots = _guarded("a", "b")
    console._formation_leader = "b"
    console._formation_members = lambda: {"a"}
    for call in (console.formation_reform("LINE"), console.formation_resume()):
        with pytest.raises(HubError) as err:
            run(call)
        assert err.value.code == "TRIP_ROBOT_BUSY"


def test_the_fleet_stuck_resolver_marks_a_trip_robot():
    """D-517 5 (M4): no longer skipped; the resolver gives a marked trip robot stopping answers only."""
    from fleet.server.stuck_resolver_loop import StuckResolverLoop

    seen = []

    class Resolver:
        def step(self, now, rows):
            seen.extend((row["robot_id"], row.get("trip", False)) for row in rows)
            return []

    async def snapshot():
        return {"robots": [{"robot_id": "a"}, {"robot_id": "b"}]}

    loop = StuckResolverLoop(snapshot, board=None, resolver=Resolver(), clients=dict)
    loop.trip_busy = lambda robot_id: robot_id == "b"
    run(loop.run_once())
    assert seen == [("a", False), ("b", True)]


@pytest.mark.parametrize(("decision", "status", "ends"), [
    ("RESUME", 409, None), ("BACK_AND_RETRY", 409, None), ("WAIT", 200, None),
    ("ABORT", 200, "operator_stuck_abort"), ("MANUAL", 200, "operator_stuck_manual")])
def test_stuck_decisions_on_a_trip_robot(tmp_path, decision, status, ends):
    client, robot, _console, trip_id, _ports = _trip_app(tmp_path)
    response = client.post("/api/fleet/robots/rosy_60/line-stuck/decision",
                           json={"stuck_id": "s1", "decision": decision}, headers=OPERATOR)
    assert response.status_code == status, response.text
    forwarded = ("line_stuck_decision", "s1", decision) in robot.calls
    assert forwarded == (status == 200)
    view = client.get(f"/api/fleet/trips/{trip_id}", headers=VIEWER).json()
    assert (view["reason"] if ends else view["state"]) == (ends or "started")


def test_a_fresh_console_goal_counts_as_engaged():
    from fleet.server.trip_guard import engaged

    console, _runner, _robots = _guarded("a", "b")
    now = [100.0]
    console._goals["a"] = {"x": 0, "y": 0, "yaw": 0}
    console.trip_goal_sent_at["a"] = 99.0
    assert engaged(console, "a", clock=lambda: now[0]) == "goal"
    now[0] = 101.5
    assert engaged(console, "a", clock=lambda: now[0]) is None


def test_restart_halts_run_outside_the_tick_with_a_cap_and_yield_to_a_new_trip(tmp_path):
    store = SiteMapStore(tmp_path / "fleet.sqlite3")
    store.put_trip({"trip_id": "t1", "robot_id": "rosy_60", "state": "running", "drive_mode": "lane",
                    "next_place": None, "detail": {}})
    store.close()
    runner, store, ports = _setup(path=tmp_path / "fleet.sqlite3", restart_retry_s=0.001, restart_attempts=3)

    async def unreachable(robot_id):
        raise OSError("robot unreachable")

    ports.hold = unreachable
    run(runner.halts.run_restart())
    assert runner.halts.restarted == []  # gave up after 3 tries
    runner, store, ports = _setup(path=tmp_path / "fleet2.sqlite3")
    runner.halts.restarted = [{"trip_id": "old", "robot_id": "rosy_60", "drive_mode": "lane", "next_place": None}]
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    assert runner.halts.restarted == []  # the new trip owns the robot now


def test_a_trip_store_failure_never_replaces_the_stop_result(tmp_path, caplog):
    client, robot, _console, _trip_id, _ports = _trip_app(tmp_path)

    async def broken(robot_id, reason):
        raise RuntimeError("trip store unavailable")

    def store_down(_trip):
        raise RuntimeError("trip store unavailable")

    runner = client.app.state.trip_runner
    runner.cancel_robot = broken
    with caplog.at_level(logging.ERROR):
        cancel = client.post("/api/fleet/robots/rosy_60/cancel", headers=OPERATOR)
        off = client.post("/api/fleet/robots/rosy_60/line-follow", json={"mode": "OFF"}, headers=OPERATOR)
        runner._store.put_trip = store_down  # the E-stop closes the trip itself, then records it
        estop = client.post("/api/fleet/estop", headers=OPERATOR)
    assert estop.status_code == 200 and estop.json()["total"] == 1 and ("estop",) in robot.calls
    assert cancel.status_code == 200 and off.status_code == 200
    assert sum("could not end the trip" in r.message for r in caplog.records) == 2
    assert sum("could not record a trip ended by the E-stop" in r.message for r in caplog.records) == 1
    assert runner.open_trips() == []


def test_create_app_wires_the_real_trip_providers(tmp_path):
    from test_site_map_trip import _app as plain_app

    from fleet.server.map_pose_service import MapPoseService
    from fleet.server.trip_ports import HttpLaneJunction

    client, _tasks, _store, _robot = plain_app(tmp_path)
    runner = client.app.state.trip_runner
    assert runner._caps.__name__ == "_trip_caps"  # the planner's capability closure (install_trip_routes)
    assert isinstance(runner._poses, MapPoseService) and runner._poses is client.app.state.map_pose
    assert isinstance(runner._junction, HttpLaneJunction)
