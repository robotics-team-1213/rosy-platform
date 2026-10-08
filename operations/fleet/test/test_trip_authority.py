"""D-517 4 (M2): Fleet sends each trip robot its movement authority from the block table."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from types import SimpleNamespace

import pytest

from core_common.robot_body import PINKY_PRO
from fleet.server.console_view import TripCaps, trip_caps
from fleet.server.site_map_store import SiteMapStore
from fleet.server.trip_authority import AuthoritySender
from fleet.server.trip_ports import TripConfig, TripError
from fleet.server.trip_runner import TripRunner
from test_lane_traffic import Fleet, _arc, _trip
from test_routing import demo_site
from test_trip_runner import LANE

AUTH = dataclasses.replace(LANE, line_follow_authority=True, line_follow_authority_required=True)


class AuthFleet(Fleet):
    def __init__(self, ids, caps, answer=None):
        super().__init__(ids)
        self.caps, self.answer = caps, answer or {"accepted": True, "authority": {"state": "FREE"}}
        self.bodies: dict[str, list] = {robot_id: [] for robot_id in ids}

    def caps_for(self, robot_id):
        return self.caps[robot_id]

    def at(self, robot_id, arc, s, anchor_age_s=0.1):
        super().at(robot_id, arc, s, anchor_age_s)
        self.p[robot_id].pose = dataclasses.replace(self.p[robot_id].pose, odom_stamp=self.now - 0.2)

    async def send_authority(self, robot_id, body):
        self.bodies[robot_id].append(body)
        return self.answer


def _setup(caps, enabled=True, answer=None, config=TripConfig()):
    fleet = AuthFleet(tuple(caps), caps, answer)
    store = SiteMapStore(None, clock=lambda: fleet.now)
    store.import_if_empty(demo_site(), source="test")
    runner = TripRunner(store=store, routing_config=store.routing_config, caps=fleet.caps_for, poses=fleet,
                        junction=fleet, goal=fleet.goal, cancel_goal=fleet.cancel_goal,
                        blocked=lambda: fleet.blocked, clock=lambda: fleet.now, config=config,
                        authority=enabled)
    return runner, store, fleet


def _ticks(runner, fleet, n=1, dt=0.5):
    async def go():  # one loop, so the sends started by a tick complete
        for _ in range(n):
            fleet.advance(dt)
            await runner.tick()
            await asyncio.gather(*[f for f in runner.authority._inflight.values() if not f.done()])
    asyncio.run(go())


def test_the_capability_is_read_from_the_controls_descriptor():
    item = {"kind": "base_velocity", "robot_kind": "pinky_pro", "drive_modes": ["lane"], "trip_max_linear": 0.1}
    assert trip_caps({"controls": {"items": [item]}}).line_follow_authority is False
    item["line_follow_authority"] = True
    assert trip_caps({"controls": {"items": [item]}}).line_follow_authority is True
    assert trip_caps({"controls": {"items": [item]}}).line_follow_authority_required is False
    item["line_follow_authority_required"] = True
    assert trip_caps({"controls": {"items": [item]}}).line_follow_authority_required is True


def test_sent_only_with_the_flag_and_the_robot_capability():
    runner, store, fleet = _setup({"a": AUTH, "b": LANE})
    east = _arc(store, "east:fwd")
    _trip(runner, store, fleet, "a", "east:fwd", east.length_m / 2 + 0.15)
    _trip(runner, store, fleet, "b", "east:fwd", 0.3)
    assert (runner.view("a")["traffic_authority"], runner.view("b")["traffic_authority"]) == ("core", "hold_back")
    assert runner.view("a")["caps"]["line_follow_authority"] is True
    _ticks(runner, fleet, n=2)
    assert len(fleet.bodies["a"]) == 2 and fleet.bodies["b"] == []  # b keeps the M1 junction hold-back

    runner, store, fleet = _setup({"a": AUTH}, enabled=False)
    _trip(runner, store, fleet, "a", "east:fwd", 0.3)
    _ticks(runner, fleet, n=2)
    assert runner.view("a")["traffic_authority"] == "hold_back" and fleet.bodies["a"] == []


def test_the_payload_is_relative_to_the_pose_the_table_used():
    runner, store, fleet = _setup({"a": AUTH})
    _trip(runner, store, fleet, "a", "east:fwd", 0.3)
    _ticks(runner, fleet)
    (body,) = fleet.bodies["a"]
    live = runner._live["a"]
    base = live.segments[0]["s_from"] + live.progress(*live.at)
    # blocks.py: a robot's d is its FRONT; CORE measures base odom travel, so the front stays inside
    assert live.traffic["front_d_m"] == pytest.approx(base + PINKY_PRO.front_x_m)
    assert set(body) == {"authority_id", "leg_id", "pose_stamp", "until_m", "ttl_s"}
    assert body["leg_id"] == "a:0" and body["ttl_s"] == 2.0
    assert body["pose_stamp"] == pytest.approx(fleet.p["a"].pose.odom_stamp) == live.traffic["pose_stamp"]
    assert body["until_m"] == pytest.approx(live.traffic["authority_end_m"] - base - PINKY_PRO.front_x_m, abs=1e-3)
    assert body["until_m"] > 0
    assert live.authority == {"state": "FREE"}


def _live(end, s, route_rev=0, trim_m=0.0, stamp=5.0):
    segments = [{"s_from": 0.0, "s_to": 10.0}]
    return SimpleNamespace(
        traffic={"authority_end_m": end, "front_d_m": s, "pose_stamp": stamp}, route_rev=route_rev, trim_m=trim_m,
        segments=segments, progress=lambda index, s: s, open=True, authority=None,
        view={"robot_id": "a", "trip_id": "t", "traffic_authority": "core"})


def test_a_leg_is_never_sent_a_smaller_end():
    sender = AuthoritySender(None, True)
    assert sender.body(_live(2.0, 0.5))["until_m"] == 1.5
    assert sender.body(_live(1.6, 0.5))["until_m"] == 1.5  # the table's end went back: keep the sent one
    assert sender.body(_live(1.0, 0.0, trim_m=1.0))["until_m"] == 1.0  # a dropped lap moves route metres
    assert sender.body(_live(1.6, 0.5, route_rev=1))["until_m"] == 1.1  # a new leg starts over
    assert sender.body(_live(0.2, 0.5, route_rev=1))["until_m"] == 1.1
    assert sender.body(_live(None, 0.5)) is None and sender.body(_live(2.0, 0.5, stamp=None)) is None


def test_a_failed_send_is_not_retried_before_the_next_period(caplog):
    calls = []

    class Port:
        async def send_authority(self, robot_id, body):
            calls.append(body)
            raise OSError("unreachable")

    sender, live = AuthoritySender(Port(), True), _live(2.0, 0.5)

    async def go():
        for _ in range(3):
            sender.period([live])
            sender.period([live])  # the same period's second call: one send in flight
            await asyncio.gather(*[f for f in sender._inflight.values() if not f.done()])
    with caplog.at_level(logging.WARNING):
        asyncio.run(go())
    assert len(calls) == 3 and live.authority is None
    assert sum("not delivered" in r.message for r in caplog.records) == 1  # once per run of failures


@pytest.mark.parametrize("state, stalled", [("HOLDING", False), ("FREE", True)])
def test_standing_at_the_authority_end_is_not_a_stall(state, stalled):
    runner, store, fleet = _setup({"a": AUTH}, answer={"accepted": True, "authority": {"state": state}})
    _trip(runner, store, fleet, "a", "east:fwd", 0.3)
    _ticks(runner, fleet, n=42)  # 21 s without moving and nobody ahead
    assert (runner.view("a")["reason"] == "stall") is stalled


def test_trip_caps_default_has_no_authority():
    assert TripCaps("pinky_pro", frozenset({"lane"}), 0.2).line_follow_authority is False


def test_until_is_from_the_front_so_the_base_stops_front_x_earlier():
    runner, store, fleet = _setup({"a": AUTH})
    east = _arc(store, "east:fwd")
    _trip(runner, store, fleet, "a", "east:fwd", east.length_m / 2)
    _ticks(runner, fleet)
    live = runner._live["a"]
    end, front = live.traffic["authority_end_m"], live.traffic["front_d_m"]
    base = live.segments[0]["s_from"] + live.progress(*live.at)
    until = fleet.bodies["a"][-1]["until_m"]
    assert until == pytest.approx(end - base - PINKY_PRO.front_x_m, abs=1e-3) and front - base > 0.04
    # the sender reuses the table's d, never recomputes it: a front put on the end stands at once
    live.traffic = {**live.traffic, "front_d_m": end}
    assert AuthoritySender(None, True).body(live)["until_m"] == 0.0


def test_a_step_still_in_flight_sends_nothing_and_keeps_its_pose_pair():
    runner, store, fleet = _setup({"a": AUTH}, config=TripConfig(period_s=0.05))
    east = _arc(store, "east:fwd")
    _trip(runner, store, fleet, "a", "east:fwd", 0.3)
    _ticks(runner, fleet)
    live, sent = runner._live["a"], len(fleet.bodies["a"])
    pair = (live.at, live.at_stamp)
    gate, inner = asyncio.Event(), fleet.junction_state

    async def slow(robot_id):  # CORE answers the junction read late (up to port_timeout_s)
        await gate.wait()
        return await inner(robot_id)

    async def go():
        fleet.junction_state = slow
        fleet.at("a", east, 0.5)  # a new pose and stamp read before the late junction read
        fleet.advance(0.5)
        await runner.tick()  # the period runs while a's step waits
        await asyncio.gather(*[f for f in runner.authority._inflight.values() if not f.done()])
        assert (live.at, live.at_stamp) == pair  # the old pair, never a new stamp on an old position
        assert len(fleet.bodies["a"]) == sent
        gate.set()
        await asyncio.gather(*runner._inflight.values())
    asyncio.run(go())
    assert live.at_stamp == pytest.approx(fleet.p["a"].pose.odom_stamp) and live.at != pair[0]


def test_an_authority_robot_without_authority_required_is_refused():
    loose = dataclasses.replace(AUTH, line_follow_authority_required=False)
    runner, store, fleet = _setup({"a": loose})
    with pytest.raises(TripError) as err:
        _trip(runner, store, fleet, "a", "east:fwd", 0.3)
    assert err.value.code == "TRIP_AUTHORITY_NOT_REQUIRED"
    runner, store, fleet = _setup({"a": loose}, enabled=False)  # flag off: M1 as before
    assert _trip(runner, store, fleet, "a", "east:fwd", 0.3)["traffic_authority"] == "hold_back"
    runner, store, fleet = _setup({"a": LANE})  # no line_follow_authority: M1 hold-back as before
    assert _trip(runner, store, fleet, "a", "east:fwd", 0.3)["traffic_authority"] == "hold_back"
