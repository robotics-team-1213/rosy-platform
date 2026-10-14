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
from fleet.swarm.transport import RobotApiError
from fleet.traffic.config import _trip_lease
from fleet.traffic.trip_authority import AuthoritySender
from test_lane_traffic import _arc, _trip
from test_routing import demo_site
from test_trip_authority import AUTH, AuthFleet
from test_trip_lease import LeaseCore
from test_trip_runner import _activate_again, run

#: a stage-2 CORE: shrink/seq, 5 s ttl, enforced under the lease
NEW = dataclasses.replace(AUTH, trip_lease=True, line_follow_authority_shrink=True,
                          line_follow_authority_under_lease=True)
STOOD = {"accepted": True, "authority": {"state": "HOLDING"}}
#: CORE refused the request (409): it dropped its held end, but Fleet does not count that as a confirmed shrink
REFUSED = RobotApiError("a", 409, "AUTHORITY_ODOM_STALE", "no fresh odom to measure travel")


class LinkFleet(AuthFleet):
    """AuthFleet whose robots can drop off the network (``down``); every call is logged before it fails."""

    def __init__(self, ids, caps):
        super().__init__(ids, caps)
        self.lease = {robot_id: LeaseCore() for robot_id in ids}
        self.down: set[str] = set()
        self.lease_up: set[str] = set()  # robots whose lease renews while their other calls fail
        self.lease_down: set[str] = set()  # robots whose lease renew fails while their other calls answer
        self.fail: dict[str, Exception] = {}  # call kind -> what it raises for every robot
        self.calls: list[tuple] = []  # (robot id, kind, authority body or None) tried
        self.line_gate: asyncio.Event | None = None
        self.line_waiting = False

    def _call(self, robot_id, kind, body=None):
        self.calls.append((robot_id, kind, body))
        if robot_id in self.down:
            raise OSError("no route to host")
        if kind in self.fail:
            raise self.fail[kind]

    async def refresh(self, robot_id, force_rest=False):
        self._call(robot_id, "state")

    async def junction_state(self, robot_id):
        self._call(robot_id, "state")
        return await super().junction_state(robot_id)

    async def send_junction(self, robot_id, *args, **kwargs):
        self._call(robot_id, "junction")
        return await super().send_junction(robot_id, *args, **kwargs)

    async def hold(self, robot_id):
        self._call(robot_id, "hold")
        return await super().hold(robot_id)

    async def goal(self, robot_id, *args):
        self._call(robot_id, "goal")
        return await super().goal(robot_id, *args)

    async def line_follow_mode(self, robot_id):
        self._call(robot_id, "mode")
        return await super().line_follow_mode(robot_id)

    async def start_camera_line(self, robot_id):
        if self.line_gate is not None:
            self.line_waiting = True
            await self.line_gate.wait()
        return await self.p[robot_id].start_camera_line(robot_id)

    async def send_authority(self, robot_id, body):
        self._call(robot_id, "authority", body)
        if isinstance(self.answer, Exception):  # a CORE 409 refusal
            raise self.answer
        return await super().send_authority(robot_id, body)

    async def trip_lease(self, robot_id, body):
        self.lease[robot_id].down = robot_id in (self.down - self.lease_up) | self.lease_down
        return self.lease[robot_id].put(body)

    async def trip_lease_release(self, robot_id, lease_id):
        return self.lease[robot_id].delete(lease_id)


def _setup(caps, lease=True, config=TripConfig(), renew_lease=None):
    fleet = LinkFleet(tuple(caps), caps)
    store = SiteMapStore(None, clock=lambda: fleet.now)
    store.import_if_empty(demo_site(), source="test")
    runner = TripRunner(store=store, routing_config=store.routing_config, caps=fleet.caps_for, poses=fleet,
                        junction=fleet, goal=fleet.goal, cancel_goal=fleet.cancel_goal,
                        blocked=lambda: fleet.blocked, clock=lambda: fleet.now, config=config,
                        authority=True, lease={"required": lease}, renew_lease=renew_lease)
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
    def grants(robot_id):
        return {unit for unit, _forward in state.held[robot_id].values()}
    held_a, held_b = grants("a"), grants("b")
    fleet.down.add("a")
    _ticks(runner, fleet, 6)
    assert runner.view("a")["state"] == "link_wait"
    assert held_a <= grants("a") and grants("b") <= held_b  # a keeps its blocks; b is granted none of them
    assert runner._live["b"].traffic["waiting_for"] == ["a"]


# ---- the shrink (D-760 3, Context 5) ---------------------------------------------------------

def _shrinks_until_confirmed(runner, fleet, robot_id="a"):
    """The next period sends ``shrink`` + 0 and repeats it while CORE does not accept it; once accepted (or
    the case cleared) no shrink follows. Returns what was sent in the two periods after."""
    fleet.answer = REFUSED
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
    fleet.answer = REFUSED
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


def test_a_robot_mid_step_gets_neither_an_extend_nor_a_shrink():
    """Safety-Review MEDIUM-3: Fleet's own slowness does not stop a robot; it rolls on its held ttl."""
    runner, store, fleet = _running(*_setup({"a": NEW}, config=TripConfig(period_s=0.05)))
    gate, inner = asyncio.Event(), fleet.junction_state

    async def slow(robot_id):
        await gate.wait()
        return await inner(robot_id)

    async def go():
        fleet.junction_state = slow
        since = len(fleet.calls)
        for _ in range(3):
            fleet.advance(0.5)
            await runner.tick()
            await _settle(runner)
        bodies = _bodies(fleet, "a", since)
        gate.set()
        await asyncio.gather(*runner._inflight.values())
        return bodies
    assert asyncio.run(go()) == []


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
        for _ in range(1000):  # the start's own checks run up to CORE's line PUT
            if fleet.line_waiting:
                break
            await asyncio.sleep(0)
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


# ---- Safety-Review CONDITIONS (2026-10-14) ----------------------------------------------------

def _near_place(caps=NEW, **setup):
    """A trip whose robot is within arm distance of its next place: each step sends a junction instruction."""
    runner, store, fleet = _setup({"a": caps}, **setup)
    east = _arc(store, "east:fwd")
    _trip(runner, store, fleet, "a", "east:fwd", east.length_m - 0.3)
    return runner, store, fleet


def test_a_non_transport_error_after_the_link_returned_ends_the_trip():
    """HIGH-1 (a): only no answer is link loss; a ValueError ends the trip failed as before."""
    runner, store, fleet = _near_place(config=TripConfig(stall_s=2.0))
    fleet.down.add("a")
    _ticks(runner, fleet, 2)
    assert runner.view("a")["state"] == "link_wait"
    fleet.down.discard("a")
    fleet.fail["junction"] = ValueError("bad body")
    _ticks(runner, fleet, 2)
    view = runner.view("a")
    assert (view["state"], view["reason"], view["detail"]["kind"]) == ("failed", "TRIP_ROBOT_UNREACHABLE", "ValueError")


def test_a_link_fault_after_every_return_keeps_the_first_since_so_the_stall_rule_ends_it():
    """HIGH-1 (b): _link_back passes, a later call of the same step gets no answer, every period."""
    runner, store, fleet = _near_place(config=TripConfig(stall_s=2.0))
    fleet.fail["junction"] = OSError("no route to host")
    _ticks(runner, fleet)
    since = runner.view("a")["wait"]["since"]
    for _ in range(20):  # 10 s: lease ttl 8 + stall_s 2
        _ticks(runner, fleet)
        if runner.view("a")["state"] != "link_wait":
            break
        assert runner.view("a")["wait"]["since"] == since
    assert (runner.view("a")["state"], runner.view("a")["reason"]) == ("stopped", "stall")
    assert fleet.now - since <= runner.lease.ttl_s + 2.0 + 0.5


def test_a_cancel_during_link_wait_keeps_the_pin_until_the_last_extend_expired():
    """MEDIUM-2: the halt got no answer, so the robot may still drive its last extend for up to its ttl."""
    runner, store, fleet = _running(*_setup({"a": NEW}))
    fleet.down.add("a")
    _ticks(runner, fleet, 2)
    reach = runner.authority.reach("a")
    assert reach > 0
    run(runner.cancel("a", "bob"))
    assert runner.view("a")["detail"]["stop_sent"] is False and runner.authority.reach("a") == reach
    sent_at = runner.authority._held["a"]["sent_at"]
    fleet.advance(sent_at + 5.0 + 1.5 - fleet.now - 0.1)
    assert runner.authority.reach("a") == reach
    fleet.advance(0.2)
    assert runner.authority.reach("a") == 0.0


def test_a_confirmed_halt_drops_the_pin_at_once():
    """MEDIUM-2 / mutation: the trip end's forget runs; the line is OFF, so no authority is left."""
    runner, store, fleet = _running(*_setup({"a": NEW}))
    assert runner.authority.reach("a") > 0
    run(runner.cancel("a", "bob"))
    assert runner.view("a")["detail"]["stop_sent"] is True and runner.authority.reach("a") == 0.0


def test_shrink_none_held_counts_as_confirmed():
    runner, store, fleet = _running(*_setup({"a": NEW}))

    def broken(*_args, **_kwargs):
        raise RuntimeError("table")
    runner.traffic.step = broken
    fleet.answer = {"accepted": False, "reason": "shrink_none_held", "authority": {"state": "NONE"}}
    since = len(fleet.calls)
    _ticks(runner, fleet, 3)
    bodies = _bodies(fleet, "a", since)
    assert len(bodies) == 1 and bodies[0]["shrink"] is True and runner.authority.reach("a") == 0.0


def test_a_confirmation_for_another_leg_does_not_confirm_the_held_one():
    """Mutation: ``held["leg"] == body["leg_id"]`` in ``_send``."""
    class Port:
        async def send_authority(self, robot_id, body):
            return {"accepted": True}
    sender = AuthoritySender(Port(), True, clock=lambda: 100.0)
    sender._held["a"] = {"leg": "t:1:e", "stamp": 5.0, "until_m": 1.0, "shrunk": False, "sent_at": 100.0}
    live = SimpleNamespace(view={"robot_id": "a"}, authority=None)
    asyncio.run(sender._send(live, {"leg_id": "t:0:e", "shrink": True, "until_m": 0.0}))
    assert sender.reach("a") == 1.0


def test_the_lease_ttl_must_outlast_the_authority(tmp_path):
    path = tmp_path / "site.yaml"
    path.write_text("fleet:\n  trip_lease_required: true\n  trip_lease_ttl_s: 5\n  traffic:\n    authority: true\n",
                    encoding="utf-8")
    with pytest.raises(SystemExit):
        _trip_lease(SimpleNamespace(site_config=path))
    path.write_text("fleet:\n  trip_lease_required: true\n  trip_lease_ttl_s: 5\n", encoding="utf-8")
    assert _trip_lease(SimpleNamespace(site_config=path))["ttl_s"] == 5.0  # no authority: no order to keep
    path.write_text("fleet:\n  trip_lease_required: true\n  trip_lease_ttl_s: 6\n  traffic:\n    authority: true\n",
                    encoding="utf-8")
    assert _trip_lease(SimpleNamespace(site_config=path))["ttl_s"] == 6.0


def test_the_link_returns_only_after_a_lease_renew_since_the_loss():
    runner, store, fleet = _running(*_setup({"a": NEW}))
    fleet.down.add("a")
    _ticks(runner, fleet, 3)
    fleet.down.discard("a")
    fleet.lease_down.add("a")  # the robot answers, its lease renew not yet
    _ticks(runner, fleet, 2)
    assert runner.view("a")["state"] == "link_wait"
    fleet.lease_down.discard("a")
    _ticks(runner, fleet, 2)
    assert runner.view("a")["state"] == "running"


def test_no_goal_lease_renewal_during_link_wait():
    renewed = []

    async def renew(robot_id):
        renewed.append(robot_id)
    runner, store, fleet = _running(*_setup({"a": NEW}, renew_lease=renew))
    assert renewed
    fleet.down.add("a")
    _ticks(runner, fleet)
    count = len(renewed)
    _ticks(runner, fleet, 4)
    assert runner.view("a")["state"] == "link_wait" and len(renewed) == count
