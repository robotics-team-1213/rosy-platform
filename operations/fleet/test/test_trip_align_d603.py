"""D-603: with ``fleet.trip.auto_align`` a trip start whose robot faces away from its first lane asks CORE
``rotate_to`` (delta = lane heading - map yaw), waits for it and a fresh sighting, checks again (one more
small turn for odom over-rotation) and only then starts; any refusal or abort refuses the start."""

from __future__ import annotations

import dataclasses
import math

import pytest

from fleet.server import trip_admission
from fleet.server.trip_ports import TripConfig, TripError
from fleet.swarm.transport import RobotApiError
from test_trip_runner import _code, _plan, _setup, run


class Core:
    """CORE's rotate_to on the fake robot: turns the Fleet pose by ``delta * real`` (odom over-rotation)."""

    def __init__(self, ports, real=1.0, refuse=None, end=("done", "done")):
        self.ports, self.real, self.refuse, self.end = ports, real, refuse, end
        self.asked: list = []
        self.stops = 0
        ports.rotate_to, ports.rotate_status, ports.rotate_stop = self.rotate_to, self.status, self.stop
        ports.refresh = self.refresh

    async def rotate_to(self, robot_id, delta_deg, operator_name):
        if self.refuse is not None:
            raise self.refuse
        self.asked.append((delta_deg, operator_name))
        pose = self.ports.pose
        self.ports.pose = dataclasses.replace(pose, yaw=pose.yaw + math.radians(delta_deg * self.real))
        return {"kind": "rotate_to", "state": "running"}

    async def status(self, robot_id):
        state, reason = self.end
        return {"kind": "rotate_to", "state": state, "reason": reason, "final_err_deg": 1.0}

    async def stop(self, robot_id):
        self.stops += 1
        return {"state": "aborted"}

    async def refresh(self, robot_id, force_rest=False):
        self.ports.now += 0.5  # a camera that keeps sighting: the anchor stays 0.1 s old


def _turned(ports, deg):
    ports.pose = dataclasses.replace(ports.pose, yaw=ports.pose.yaw + math.radians(deg))


def _aligned_setup(**config):
    runner, store, ports = _setup(auto_align=True, period_s=0.01, **config)
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    return runner, store, ports


def test_off_by_default_the_start_is_refused_and_nothing_turns():
    runner, store, ports = _setup(period_s=0.01)
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    core = Core(ports)
    _turned(ports, 178)
    assert _code(runner.start("p1", "bob")) == "TRIP_START_HEADING_MISMATCH" and core.asked == []
    assert TripConfig().auto_align is False
    with pytest.raises(ValueError):
        TripConfig(auto_align="yes")


def test_a_reversed_robot_is_turned_then_started():
    runner, _store, ports = _aligned_setup()
    core = Core(ports)
    _turned(ports, 178)
    view = run(runner.start("p1", "bob"))
    assert core.asked == [(-178.0, "bob")] and view["state"] == "started"
    assert view["detail"]["aligned"] == [{"delta_deg": -178.0, "final_err_deg": 1.0}]


def test_wrong_one_lap_start_refuses_before_any_alignment_turn():
    runner, store, ports = _aligned_setup()
    row = store.plan("p1")
    store.record_plan(plan_id="lap", robot_id=row["robot_id"], principal_id="bob",
                      map_version=row["map_version"], request={**row["request"], "start_at": "NW"},
                      result=row["result"])
    core = Core(ports)
    _turned(ports, 178)
    assert _code(runner.start("lap", "bob")) == "TRIP_START_PLACE_MISMATCH"
    assert core.asked == [] and runner.running() is None


def test_odom_over_rotation_gets_one_small_second_turn():
    runner, _store, ports = _aligned_setup()
    core = Core(ports, real=1.15)  # the wheels turn 15 % more than CORE's odom says
    _turned(ports, 170)
    view = run(runner.start("p1", "bob"))
    assert core.asked[0][0] == -170.0 and core.asked[1][0] == pytest.approx(25.5, abs=0.2)
    assert view["state"] == "started"


def test_still_off_after_two_turns_is_refused():
    runner, _store, ports = _aligned_setup()
    core = Core(ports, real=0.5)
    _turned(ports, 170)
    assert _code(runner.start("p1", "bob")) == "TRIP_START_HEADING_MISMATCH" and len(core.asked) == 2
    assert runner.view("p1") is None


def test_a_core_refusal_refuses_the_start_with_its_reason():
    runner, _store, ports = _aligned_setup()
    Core(ports, refuse=RobotApiError("rosy_60", 409, "ROTATE_CLEARANCE", "a return 0.08 m from the base",
                                     {"nearest_m": 0.08, "need_m": 0.113}))
    _turned(ports, 90)
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.code == "TRIP_ALIGN_REFUSED" and err.value.detail["error"] == "ROTATE_CLEARANCE"
    assert err.value.detail["core"] == {"nearest_m": 0.08, "need_m": 0.113} and runner.view("p1") is None
    assert ports.line_starts == []


def test_an_aborted_or_endless_turn_refuses_the_start(monkeypatch):
    monkeypatch.setattr(trip_admission, "ALIGN_WAIT_S", 0.1)
    runner, _store, ports = _aligned_setup()
    Core(ports, end=("aborted", "obstacle"))
    _turned(ports, 90)
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.code == "TRIP_ALIGN_ABORTED" and err.value.detail["reason"] == "obstacle"
    runner, _store, ports = _aligned_setup()
    core = Core(ports, end=("running", None))
    _turned(ports, 90)
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.detail["reason"] == "fleet_timeout" and core.stops == 1


def test_no_fresh_sighting_after_the_turn_refuses_the_start(monkeypatch):
    monkeypatch.setattr(trip_admission, "ALIGN_SIGHTING_S", 0.1)
    runner, _store, ports = _aligned_setup()
    core = Core(ports)

    async def frozen(robot_id, force_rest=False):
        return None  # the clock does not move: no sighting is newer than the turn

    ports.refresh = frozen
    _turned(ports, 90)
    with pytest.raises(TripError) as err:
        run(runner.start("p1", "bob"))
    assert err.value.code == "TRIP_POSE_UNTRUSTED" and err.value.detail["after_align"] is True
    assert len(core.asked) == 1


def test_off_lane_is_never_turned():
    runner, store, ports = _aligned_setup()
    core = Core(ports)
    width = store.active()[2].arcs["ring_s:fwd"].width_m
    pose = ports.pose
    ports.pose = dataclasses.replace(pose, x=pose.x - math.sin(pose.yaw) * width,
                                     y=pose.y + math.cos(pose.yaw) * width, yaw=pose.yaw + math.pi)
    assert _code(runner.start("p1", "bob")) == "TRIP_START_OFF_LANE" and core.asked == []


def test_the_plan_marks_a_heading_mismatch_the_start_will_turn(tmp_path):
    from test_site_map_trip import OPERATOR, _app, _on_ring_s

    client, _tasks, store, robot = _app(tmp_path)
    robot._state = _on_ring_s(store)
    robot._state["pose"]["yaw"] += math.radians(35)
    check = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()["start_check"]
    assert check["code"] == "TRIP_START_HEADING_MISMATCH" and "auto_align" not in check
    client.app.state.trip_runner.config = TripConfig(auto_align=True)
    check = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "NW"}, headers=OPERATOR).json()["start_check"]
    assert check["code"] == "TRIP_START_HEADING_MISMATCH" and check["auto_align"] is True
