"""D-760 3-5 (stage 3): link_wait, the shrink sender, seq, the restart quarantine and the start order."""

from __future__ import annotations

import asyncio
import dataclasses
import math
from types import SimpleNamespace

import pytest

from fleet.routing.execute import plan_body
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.server.site_map_store import SiteMapStore
from fleet.server.trip_ports import TripConfig, TripError
from fleet.server.trip_runner import TripRunner
from fleet.traffic import trip_authority
from fleet.traffic.trip_authority import AuthoritySender
from test_lane_traffic import _arc, _trip
from test_routing import demo_site
from test_trip_authority import AUTH, AuthFleet
from test_trip_lease import LeaseCore
from test_trip_runner import _activate_again

#: a stage-2 CORE: shrink/seq, 5 s ttl, enforced under the lease
NEW = dataclasses.replace(AUTH, trip_lease=True, line_follow_authority_shrink=True,
                          line_follow_authority_under_lease=True)
STOOD = {"accepted": True, "authority": {"state": "HOLDING"}}


class LinkFleet(AuthFleet):
    """AuthFleet whose robots can drop off the network (``down``); every call is logged before it fails."""

    def __init__(self, ids, caps):
        super().__init__(ids, caps)
        self.lease = {robot_id: LeaseCore() for robot_id in ids}
        self.down: set[str] = set()
        self.lease_up: set[str] = set()  # robots whose lease renews while their other calls fail
        self.calls: list[tuple] = []  # (robot id, kind, authority body or None) tried
        self.line_gate: asyncio.Event | None = None

    def _call(self, robot_id, kind, body=None):
        self.calls.append((robot_id, kind, body))
        if robot_id in self.down:
            raise OSError("no route to host")

    async def refresh(self, robot_id, force_rest=False):
        self._call(robot_id, "state")

    async def junction_state(self, robot_id):
        self._call(robot_id, "state")
        return await super().junction_state(robot_id)

    async def send_junction(self, robot_id, *args, **kwargs):
        self._call(robot_id, "junction")
        return await super().send_junction(robot_id, *args, **kwargs)

    async def goal(self, robot_id, *args):
        self._call(robot_id, "goal")
        return await super().goal(robot_id, *args)

    async def line_follow_mode(self, robot_id):
        self._call(robot_id, "mode")
        return await super().line_follow_mode(robot_id)

    async def start_camera_line(self, robot_id):
        if self.line_gate is not None:
            await self.line_gate.wait()
        return await self.p[robot_id].start_camera_line(robot_id)

    async def send_authority(self, robot_id, body):
        self._call(robot_id, "authority", body)
        return await super().send_authority(robot_id, body)

    async def trip_lease(self, robot_id, body):
        self.lease[robot_id].down = robot_id in self.down - self.lease_up
        return self.lease[robot_id].put(body)

    async def trip_lease_release(self, robot_id, lease_id):
        return self.lease[robot_id].delete(lease_id)


def _setup(caps, lease=True, config=TripConfig()):
    fleet = LinkFleet(tuple(caps), caps)
    store = SiteMapStore(None, clock=lambda: fleet.now)
    store.import_if_empty(demo_site(), source="test")
    runner = TripRunner(store=store, routing_config=store.routing_config, caps=fleet.caps_for, poses=fleet,
                        junction=fleet, goal=fleet.goal, cancel_goal=fleet.cancel_goal,
                        blocked=lambda: fleet.blocked, clock=lambda: fleet.now, config=config,
                        authority=True, lease={"required": lease})
    runner.lease._clock = lambda: fleet.now
    runner.authority._clock, runner.authority.quiet_until = (lambda: fleet.now), -math.inf
    return runner, store, fleet


async def _settle(runner):
    for _ in range(5):
        pending = [t for t in (*runner.authority._inflight.values(), *runner.lease._inflight.values(),
                               *runner.lease._releasing.values()) if not t.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


def _ticks(runner, fleet, n=1, dt=0.5):
    async def go():
        for _ in range(n):
            fleet.advance(dt)
            await runner.tick()
            await _settle(runner)
    asyncio.run(go())


def _bodies(fleet, robot_id, since=0):
    return [body for r, kind, body in fleet.calls[since:] if r == robot_id and kind == "authority"]


def _running(runner, store, fleet):
    _trip(runner, store, fleet, "a", "east:fwd", 0.3)
    _ticks(runner, fleet, 2)
    assert runner.view("a")["state"] == "running" and _bodies(fleet, "a")
    return runner, store, fleet


# ---- link_wait (D-760 4) ---------------------------------------------------------------------

@pytest.mark.parametrize("down_s", [3.0, 4.5, 5.5])
def test_a_link_loss_under_the_lease_ttl_keeps_the_trip_open_and_it_carries_on(down_s):
    runner, store, fleet = _running(*_setup({"a": NEW}))
    fleet.down.add("a")
    since = len(fleet.calls)
    _ticks(runner, fleet, int(down_s / 0.5))
    view = runner.view("a")
    assert view["state"] == "link_wait" and view["wait"]["reason"] == "link_wait" and runner.robot_busy("a")
    tried = {kind for r, kind, _body in fleet.calls[since:] if r == "a"}
    assert tried <= {"state", "authority"}  # no junction instruction, goal or mode change
    assert all(body.get("shrink") is True and body["until_m"] == 0.0 for body in _bodies(fleet, "a", since))
    fleet.down.discard("a")
    _ticks(runner, fleet)
    view = runner.view("a")
    assert view["state"] == "running" and "wait" not in view and view["lease"]["state"] == "held"
    _ticks(runner, fleet)
    assert _bodies(fleet, "a")[-1].get("shrink") is None  # extends again


def test_a_link_loss_past_the_lease_ttl_ends_the_trip_lease_lost():
    runner, store, fleet = _running(*_setup({"a": NEW}))
    fleet.down.add("a")
    _ticks(runner, fleet, 15)
    assert runner.view("a")["state"] == "link_wait"
    _ticks(runner, fleet, 3)  # 9 s
    view = runner.view("a")
    assert (view["state"], view["reason"], view["detail"]["lease_reason"]) == ("stopped", "lease_lost", "renew_timeout")


def test_the_check_on_return_ends_a_trip_whose_line_was_turned_off():
    runner, store, fleet = _running(*_setup({"a": NEW}))
    fleet.down.add("a")
    _ticks(runner, fleet, 4)
    fleet.p["a"].core.mode = "OFF"  # someone stopped line following meanwhile
    fleet.down.discard("a")
    _ticks(runner, fleet)
    view = runner.view("a")
    assert (view["state"], view["reason"], view["detail"]["mode"]) == ("failed", "TRIP_LINE_FOLLOW_NOT_ACTIVE", "OFF")


def test_the_check_on_return_ends_a_trip_on_another_map_version():
    runner, store, fleet = _running(*_setup({"a": NEW}))
    fleet.down.add("a")
    _ticks(runner, fleet, 4)
    _activate_again(store)
    fleet.down.discard("a")
    _ticks(runner, fleet)
    assert (runner.view("a")["state"], runner.view("a")["reason"]) == ("failed", "TRIP_MAP_CHANGED")


def test_a_trip_without_a_lease_ends_on_the_first_failure_as_before():
    runner, store, fleet = _running(*_setup({"a": AUTH}, lease=False))
    fleet.down.add("a")
    _ticks(runner, fleet)
    view = runner.view("a")
    assert (view["state"], view["reason"]) == ("failed", "TRIP_ROBOT_UNREACHABLE")


def test_link_wait_is_no_stall_while_the_lease_lives_then_the_stall_rule_applies():
    runner, store, fleet = _running(*_setup({"a": NEW}, config=TripConfig(stall_s=2.0)))
    fleet.down.add("a")
    fleet.lease_up.add("a")  # only the robot's state and line calls fail: the lease keeps renewing
    _ticks(runner, fleet, 14)  # 7 s, stall_s is 2 s
    assert runner.view("a")["state"] == "link_wait"
    _ticks(runner, fleet, 4 + 4)  # past the 8 s bound, then stall_s
    assert runner.view("a")["reason"] == "stall"


def test_a_link_wait_robot_keeps_its_blocks_and_the_robot_behind_stops_before_them():
    runner, store, fleet = _setup({"a": NEW, "b": NEW})
    middle = _arc(store, "east:fwd").length_m / 2
    _trip(runner, store, fleet, "a", "east:fwd", middle + 0.15)
    _trip(runner, store, fleet, "b", "east:fwd", middle - 0.05)
    _ticks(runner, fleet)
    state = runner.traffic._state
    held = {unit for unit, _f in state.held["a"].values()} | set(state.last_occupied["a"])
    fleet.down.add("a")
    _ticks(runner, fleet, 6)
    assert runner.view("a")["state"] == "link_wait"
    assert held <= {unit for unit, _f in state.held["a"].values()} | set(state.last_occupied["a"])
    assert not held & {unit for unit, _f in state.held["b"].values()}
    assert runner._live["b"].traffic["waiting_for"] == ["a"]


# ---- the shrink (D-760 3, Context 5) ---------------------------------------------------------

def _shrinks_until_confirmed(runner, fleet, robot_id="a"):
    """The next period sends ``shrink`` + 0 and repeats it while CORE does not accept it; once accepted (or
    the case cleared) no shrink follows. Returns what was sent in the two periods after."""
    fleet.answer = {"accepted": False, "reason": "shrink_none_held", "authority": None}
    since = len(fleet.calls)
    _ticks(runner, fleet, 2)
    bodies = _bodies(fleet, robot_id, since)
    assert len(bodies) == 2 and all(b["shrink"] is True and b["until_m"] == 0.0 for b in bodies)
    fleet.answer = STOOD
    _ticks(runner, fleet)
    since = len(fleet.calls)
    _ticks(runner, fleet, 2)
    after = _bodies(fleet, robot_id, since)
    assert not any(b.get("shrink") for b in after)
    return after


def test_a_map_pose_jump_shrinks():
    runner, store, fleet = _running(*_setup({"a": NEW}))
    fleet.at("a", _arc(store, "east:fwd"), 1.6)  # 1.3 m in one period
    _shrinks_until_confirmed(runner, fleet)  # JUMP_SETTLE_PERIODS later the jump is taken: extends again


def test_a_failing_block_table_shrinks():
    runner, store, fleet = _running(*_setup({"a": NEW}))

    def broken(*_args, **_kwargs):
        raise RuntimeError("table")
    runner.traffic.step = broken
    assert _shrinks_until_confirmed(runner, fleet) == []


def test_another_map_version_shrinks_and_keeps_the_end_pinned_until_confirmed():
    runner, store, fleet = _running(*_setup({"a": NEW}))
    assert runner.authority.reach("a") > 0
    runner.authority._held["a"]["until_m"] = reach = 2.0  # as if a 2 m authority were out
    _activate_again(store)
    fleet.answer = {"accepted": False, "reason": "shrink_none_held", "authority": None}
    _ticks(runner, fleet)
    assert _bodies(fleet, "a")[-1]["shrink"] is True
    layout, graph = runner.traffic._layout, store.active()[2]
    pose = runner.traffic._last_pose["a"]
    body_only, with_end = runner.traffic._under(layout, graph, pose), runner.traffic._under(layout, graph, pose, reach)
    assert set(with_end) > set(body_only)  # the unconfirmed end reaches past the body
    assert set(with_end) <= set(runner.traffic._state.pinned["a"])  # no other robot is granted them
    fleet.answer = STOOD
    _ticks(runner, fleet)
    assert runner.authority.reach("a") == 0.0


def test_a_convoy_follower_whose_grant_goes_back_shrinks():
    runner, store, fleet = _setup({"a": NEW, "b": NEW})
    from test_convoy_trips import _trip as _convoy_trip
    _convoy_trip(runner, store, fleet, "a", "east:fwd", 1.5)
    _ticks(runner, fleet)
    _convoy_trip(runner, store, fleet, "b", "east:fwd", 0.2, leader="a")
    _ticks(runner, fleet, 2)
    assert _bodies(fleet, "b")
    runner.traffic._state.authority["b"] = 99.0  # an earlier, larger end: this period's is smaller (D-517 4)
    _ticks(runner, fleet)
    assert runner._live["b"].traffic["authority_end_m"] is None
    assert _bodies(fleet, "b")[-1]["shrink"] is True


def test_a_robot_mid_step_gets_a_shrink_not_an_extend():
    runner, store, fleet = _running(*_setup({"a": NEW}, config=TripConfig(period_s=0.05)))
    gate, inner = asyncio.Event(), fleet.junction_state

    async def slow(robot_id):
        await gate.wait()
        return await inner(robot_id)

    async def go():
        fleet.junction_state = slow
        since = len(fleet.calls)
        fleet.advance(0.5)
        await runner.tick()
        await _settle(runner)
        body = _bodies(fleet, "a", since)[-1]
        gate.set()
        await asyncio.gather(*runner._inflight.values())
        return body
    body = asyncio.run(go())
    assert body["shrink"] is True and body["until_m"] == 0.0


def test_a_robot_without_the_shrink_flag_gets_ttl_2_and_never_a_shrink():
    runner, store, fleet = _running(*_setup({"a": AUTH}, lease=False))
    assert {b["ttl_s"] for b in _bodies(fleet, "a")} == {2.0} and all("shrink" not in b for b in _bodies(fleet, "a"))
    since = len(fleet.calls)

    def broken(*_args, **_kwargs):
        raise RuntimeError("table")
    runner.traffic.step = broken
    _ticks(runner, fleet, 2)
    assert _bodies(fleet, "a", since) == []  # today: nothing goes out, its 2 s expiry stops it


def test_a_shrink_capable_robot_gets_ttl_5():
    runner, store, fleet = _running(*_setup({"a": NEW}))
    assert {b["ttl_s"] for b in _bodies(fleet, "a")} == {5.0}


# ---- seq, restart, start order (D-760 2/3/5) -------------------------------------------------

def test_seq_rises_per_leg_and_a_restarted_fleet_uses_a_new_leg(monkeypatch):
    runner, store, fleet = _running(*_setup({"a": NEW}))
    fleet.at("a", _arc(store, "east:fwd"), 1.6)  # a jump: shrinks on the same leg
    _ticks(runner, fleet, 2)
    bodies = _bodies(fleet, "a")
    legs = {b["leg_id"] for b in bodies}
    assert len(legs) == 1 and [b["seq"] for b in bodies] == list(range(len(bodies)))
    core_seq = {next(iter(legs)): bodies[-1]["seq"]}  # what CORE remembers (D-760 rev 2 item 2)
    monkeypatch.setattr(trip_authority, "FLEET_EPOCH", "restarted0000000")  # a new process
    sender = AuthoritySender(fleet, True)
    live = runner._live["a"]
    live.traffic = {**(live.traffic or {}), "authority_end_m": 1.5, "front_d_m": 0.5, "pose_stamp": 1.0}
    body = sender.body(live)
    assert body["leg_id"] not in core_seq and body["seq"] == 0  # never stale_seq on a remembered leg


def test_no_extended_authority_for_5_s_after_fleet_starts():
    runner, store, fleet = _setup({"a": NEW})
    runner.authority.quiet_until = fleet.now + trip_authority.QUARANTINE_S  # the process started now
    _trip(runner, store, fleet, "a", "east:fwd", 0.3)
    _ticks(runner, fleet, 9)  # 4.5 s
    assert _bodies(fleet, "a") == []
    _ticks(runner, fleet, 2)
    assert _bodies(fleet, "a") and _bodies(fleet, "a")[0].get("shrink") is None


def test_no_authority_before_the_line_is_on():
    runner, store, fleet = _setup({"a": NEW}, config=TripConfig(period_s=0.05))
    fleet.p["a"].core.mode = "OFF"  # D-601 A: the trip turns the camera line on itself
    graph = store.active()[2]
    arc = graph.arcs["east:fwd"]
    fleet.at("a", arc, 0.3)
    plan = plan_trip(graph, PlanRequest(store.active()[0], arc.point_at(0.3), "start_n", via=("start_s",)),
                     store.routing_config)
    store.record_plan(plan_id="a", robot_id="a", principal_id="bob", map_version=plan.map_version,
                      request={"to": "start_n", "via": ["start_s"], "repeat": True}, result={"plan": plan_body(plan)})

    async def go():
        fleet.line_gate = asyncio.Event()
        start = asyncio.ensure_future(runner.start("a", "bob"))
        for _ in range(4):  # the lease is open, the line not yet on
            fleet.advance(0.5)
            await runner.tick()
            await _settle(runner)
        assert runner.view("a")["lease"]["state"] == "held" and _bodies(fleet, "a") == []
        fleet.line_gate.set()
        await start
        for _ in range(2):
            fleet.advance(0.5)
            await runner.tick()
            await _settle(runner)
    asyncio.run(go())
    assert fleet.p["a"].core.mode == "CAMERA_LINE" and _bodies(fleet, "a")


def test_the_sender_holds_an_extend_while_the_line_is_not_on():
    live = SimpleNamespace(traffic={"authority_end_m": 2.0, "front_d_m": 0.5, "pose_stamp": 5.0}, route_rev=0,
                           trim_m=0.0, open=True, authority=None, at_stamp=None,
                           view={"robot_id": "a", "trip_id": "t", "traffic_authority": "core", "state": "started",
                                 "detail": {"line_follow_started": False}, "caps": {}})
    sender = AuthoritySender(SimpleNamespace(), True, clock=lambda: 100.0)
    sender.quiet_until = -math.inf
    sender.period([live])
    assert sender._inflight == {}


def test_under_lease_robots_start_only_with_the_lease_required():
    loose = dataclasses.replace(NEW, line_follow_authority_required=False)
    runner, store, fleet = _setup({"a": loose})
    assert _trip(runner, store, fleet, "a", "east:fwd", 0.3)["traffic_authority"] == "core"
    runner, store, fleet = _setup({"a": loose}, lease=False)  # no lease: nothing enforces it before the first
    with pytest.raises(TripError) as err:
        _trip(runner, store, fleet, "a", "east:fwd", 0.3)
    assert err.value.code == "TRIP_AUTHORITY_NOT_REQUIRED"
