"""Step 3 of the stop alignment: a place with a yaw is not ARRIVED until a fresh marker sighting shows the heading
within 3 deg; CORE turns the robot (tol 2 deg, 3 turns at most); STATION_ALIGN_FAILED / _BLOCKED end the trip."""

from __future__ import annotations

import dataclasses
import math

import asyncio

from fleet.server.trip_station_align import station_align_gate
from test_trip_align_d603 import Core as _Core
from test_trip_runner import _arc, _plan, _setup, run


class Core(_Core):
    async def rotate_to(self, robot_id, delta_deg, operator_name, tol_deg=None):
        self.tols = [*getattr(self, "tols", []), tol_deg]
        return await super().rotate_to(robot_id, delta_deg, operator_name)


def _at_the_stop(yaw_off_deg, place_yaw=True, gate=None, **config):
    runner, store, ports = _setup(period_s=0.01, **config)
    arc = _arc(store, "east:fwd")
    _plan(store, ports, "east:fwd", 0.5, "SE")
    graph = store.active()[2]
    want = arc.point_at(arc.length_m)[2]
    if place_yaw:
        object.__setattr__(graph.places["SE"], "yaw", want)
    if gate is not None:
        runner._align_gate = gate
    run(runner.start("p1", "bob"))
    ports.at(arc, arc.length_m - 0.55)
    _ticks(runner, ports)
    ports.at(arc, arc.length_m - 0.05)
    ports.pose = dataclasses.replace(ports.pose, yaw=want + math.radians(yaw_off_deg))
    return runner, ports, want


def _ticks(runner, ports, n=1):
    """One event loop for all ticks: a step that outlasts a period (the turn) keeps running between them."""
    async def go():
        for _ in range(n):
            ports.now += 0.5
            await runner.tick()
            await asyncio.sleep(0.05)
    run(go())


def test_15_deg_off_turns_once_then_a_fresh_sighting_arrives():
    runner, ports, want = _at_the_stop(15)
    core = Core(ports)
    _ticks(runner, ports)
    assert [d for d, _ in core.asked] == [-15.0] and core.tols == [2.0] and runner.view("p1")["state"] == "arrived"


def test_an_odom_only_pose_is_never_judged_and_never_arrives():
    runner, ports, want = _at_the_stop(15)
    core = Core(ports)
    ports.pose = dataclasses.replace(ports.pose, source="bridged")
    _ticks(runner, ports)
    assert core.asked == [] and runner.view("p1")["state"] == "running"
    ports.pose = dataclasses.replace(ports.pose, source="sighting", anchor_age_s=20.0)  # a stale sighting too
    _ticks(runner, ports)
    assert core.asked == [] and runner.view("p1")["state"] == "running"
    _ticks(runner, ports, 8)  # 3 s without a fresh sighting
    view = runner.view("p1")
    assert view["state"] == "failed" and view["reason"] == "STATION_ALIGN_FAILED" and core.asked == []


def test_three_turns_still_off_stops_with_station_align_failed_and_no_fourth_turn():
    runner, ports, want = _at_the_stop(15)
    core = Core(ports, real=0.1)  # the robot hardly turns
    _ticks(runner, ports)
    view = runner.view("p1")
    assert len(core.asked) == 3, (view["state"], view.get("reason"), view["detail"])
    assert view["state"] == "failed" and view["reason"] == "STATION_ALIGN_FAILED"
    _ticks(runner, ports, 3)
    assert len(core.asked) == 3


def test_a_cell_arm_not_folded_blocks_the_turn():
    state = type("S", (), {"omx_cell_states": {}, "arm_holds": {}, "arm_live_states": {
        "arm_s": {"folded": False, "updated_at": 1000.0}}})()
    gate = station_align_gate(state, {"EXP_S3_BELT": {"place_id": "SE", "cell_id": "cell_s", "arm_id": "arm_s"}},
                              clock=lambda: 1000.0)
    runner, ports, want = _at_the_stop(15, gate=gate)
    core = Core(ports)
    _ticks(runner, ports)
    view = runner.view("p1")
    assert core.asked == [] and view["reason"] == "STATION_ALIGN_BLOCKED" and view["detail"]["reason"] == "arm_not_folded"


def test_gate_reasons_human_hold_stale_and_folded():
    zones = {"z": {"place_id": "S3", "cell_id": "cell_s", "arm_id": "arm_s"}}
    state = type("S", (), {"omx_cell_states": {"cell_s": {"phase": "HUMAN_HOLD"}}, "arm_holds": {},
                           "arm_live_states": {"arm_s": {"folded": True, "updated_at": 990.0}}})()
    gate = station_align_gate(state, zones, clock=lambda: 1000.0)
    assert gate("S3") == "human_hold" and gate("S9") is None
    state.omx_cell_states = {}
    assert gate("S3") is None
    state.arm_live_states["arm_s"]["updated_at"] = 900.0
    assert gate("S3") == "arm_not_folded"
    state.arm_live_states["arm_s"]["updated_at"] = 990.0
    state.arm_holds = {"arm_s": {"held": True}}
    assert gate("S3") == "arm_held"


def test_a_human_hold_gate_means_no_turn():
    runner, ports, want = _at_the_stop(15, gate=lambda place: "human_hold")
    core = Core(ports)
    _ticks(runner, ports)
    assert core.asked == [] and runner.view("p1")["detail"]["reason"] == "human_hold"


def test_a_place_without_yaw_arrives_by_distance_as_before():
    runner, ports, want = _at_the_stop(15, place_yaw=False)
    core = Core(ports)
    _ticks(runner, ports)
    assert core.asked == [] and runner.view("p1")["state"] == "arrived"
