"""D-541 7: Fleet holds a CORE trip lease for each trip (site config ``fleet.trip_lease_required``)."""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace

import pytest

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.console_view import trip_caps
from fleet.server.site_map_store import SiteMapStore
from fleet.server.trip_ports import TripConfig, TripError
from fleet.server.trip_runner import TripRunner
from fleet.site_map import from_lane_graph
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError
from fleet.traffic.config import _trip_lease
from test_lane_traffic import START_N, Fleet, _s_of, _to_tail
from test_lane_traffic import _trip as _lap_trip
from test_trip_runner import BOTH, LANE, LANE_GRAPH, Ports, _arc, _free_map, _plan

LEASED = dataclasses.replace(LANE, trip_lease=True)
LEASED_BOTH = dataclasses.replace(BOTH, trip_lease=True)


class LeaseCore:
    """CORE ``core/trip_lease.py`` as Fleet's own token sees it (one robot)."""

    def __init__(self) -> None:
        self.lease: dict | None = None
        self.ended: dict[str, dict] = {}
        self.puts: list[dict] = []
        self.deletes: list[tuple] = []
        self.refuse: str | None = None  # an open-time refusal code (D-541 2)
        self.down = False  # the renew never answers (Wi-Fi gone)
        self.stops = 0  # halts Fleet sent, to check a DELETE comes after them

    def put(self, body: dict) -> dict:
        if self.down:
            raise OSError("no route to host")
        self.puts.append(dict(body))
        lease_id = body["lease_id"]
        if self.lease is None and lease_id in self.ended:
            raise RobotApiError("r", 404, "NOT_FOUND", "this trip lease has ended", {"ended": self.ended[lease_id]})
        if self.lease is not None:
            if self.lease["lease_id"] != lease_id:
                raise RobotApiError("r", 409, "TRIP_LEASED", "a Fleet trip lease is active", dict(self.lease))
            return {"trip_lease": dict(self.lease), "renewed": True}
        if self.refuse:
            raise RobotApiError("r", 409, self.refuse, "refused")
        self.lease = dict(body)
        return {"trip_lease": dict(body), "renewed": False}

    def end(self, reason: str, by: str = "") -> None:
        lease_id = self.lease["lease_id"]
        self.ended[lease_id] = {"lease_id": lease_id, "reason": reason, "by": by}
        self.lease = None

    def restart(self) -> None:
        self.lease, self.ended = None, {}

    def delete(self, lease_id: str) -> dict:
        self.deletes.append((lease_id, self.stops))
        if self.lease is None or self.lease["lease_id"] != lease_id:
            raise RobotApiError("r", 404, "NOT_FOUND", "no such active trip lease")
        self.end("released", "owner")
        return {"trip_lease_ended": self.ended[lease_id]}


class LeasePorts(Ports):
    def __init__(self, caps=LEASED):
        super().__init__(caps)
        self.lease = LeaseCore()

    async def trip_lease(self, robot_id, body):
        return self.lease.put(body)

    async def trip_lease_release(self, robot_id, lease_id):
        return self.lease.delete(lease_id)

    async def hold(self, robot_id):
        self.lease.stops += 1
        return await super().hold(robot_id)

    async def cancel_goal(self, robot_id):
        self.lease.stops += 1
        return await super().cancel_goal(robot_id)


def _setup(site_map=None, caps=LEASED, lease=None):
    ports = LeasePorts(caps)
    store = SiteMapStore(None, clock=lambda: ports.now)
    store.import_if_empty(site_map or from_lane_graph(LANE_GRAPH), source="test")
    runner = TripRunner(store=store, routing_config=store.routing_config, caps=ports.caps_for, poses=ports,
                        junction=ports, goal=ports.goal, cancel_goal=ports.cancel_goal,
                        blocked=lambda: ports.blocked, clock=lambda: ports.now, config=TripConfig(),
                        lease={"required": True, "holder": "site-a"} if lease is None else lease)
    runner.lease._clock = lambda: ports.now  # the runner gives it time.monotonic
    return runner, store, ports


async def _settle(runner):
    for _ in range(10):
        tasks = [t for t in (*runner.lease._inflight.values(), *runner.lease._releasing.values()) if not t.done()]
        if not tasks:
            return
        await asyncio.gather(*tasks)


def _do(runner, coro):
    """One operator action, with the lease calls it started landed."""
    async def go():
        result = await coro
        await _settle(runner)
        return result
    return asyncio.run(go())


def _ticks(runner, ports, n=1, dt=0.5):
    async def go():  # one loop, so each renew (and a lost lease's trip end) lands in its tick
        for _ in range(n):
            ports.now += dt
            await runner.tick()
            await _settle(runner)
    asyncio.run(go())


def _start(runner, store, ports, plan_id="p1"):
    _plan(store, ports, "east:fwd", 0.5, "SE", plan_id=plan_id)
    return _do(runner, runner.start(plan_id, "bob"))


def _refused(runner, coro) -> TripError:
    with pytest.raises(TripError) as err:
        _do(runner, coro)
    return err.value


# ---- capability, site setting -------------------------------------------------------------

def test_the_capability_is_read_from_the_controls_descriptor():
    item = {"kind": "base_velocity", "robot_kind": "pinky_pro", "drive_modes": ["lane"], "trip_max_linear": 0.1}
    assert trip_caps({"controls": {"items": [item]}}).trip_lease is False
    item["trip_lease"] = True
    assert trip_caps({"controls": {"items": [item]}}).trip_lease is True


def test_site_config_names_and_bounds(tmp_path):
    path = tmp_path / "site.yaml"
    assert _trip_lease(SimpleNamespace(site_config=None)) == {"required": False, "ttl_s": 5.0}
    path.write_text("fleet:\n  trip_lease_required: true\n  trip_lease_ttl_s: 10\n", encoding="utf-8")
    assert _trip_lease(SimpleNamespace(site_config=path)) == {"required": True, "ttl_s": 10.0}
    for bad in ("trip_lease_required: 'yes'", "trip_lease_ttl_s: 11", "trip_lease_ttl_s: 0.5"):
        path.write_text(f"fleet:\n  {bad}\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            _trip_lease(SimpleNamespace(site_config=path))


def test_the_lease_token_is_fleets_own_not_the_console_token_browsers_hold():
    def app(console_token, trip_lease):
        console = FleetConsole([RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "robot-t")], [FakeRobot("rosy_60")])
        return create_app(console, console_token=console_token, trip_lease=trip_lease)

    with pytest.raises(ValueError, match="D-541"):
        app("robot-t", {"required": True, "ttl_s": 5.0})
    app("robot-t", {"required": False, "ttl_s": 5.0})  # no lease: today's behaviour, today's checks
    runner = app("console-t", {"required": True, "ttl_s": 7.0}).state.trip_runner
    assert (runner.lease.required, runner.lease.holder, runner.lease.ttl_s) == (True, "rosy-site", 7.0)


def test_setting_off_opens_no_lease_and_runs_as_before():
    runner, store, ports = _setup(caps=LANE, lease={})  # a robot without the capability, too
    view = _start(runner, store, ports)
    assert view["lease"] is None
    _ticks(runner, ports, 3)
    _do(runner, runner.cancel("p1", "bob"))
    assert ports.lease.puts == [] and ports.lease.deletes == [] and runner.view("p1")["state"] == "canceled"


def test_required_refuses_a_robot_whose_core_has_no_lease():
    runner, store, ports = _setup(caps=LANE)
    _plan(store, ports, "east:fwd", 0.5, "SE")
    assert _refused(runner, runner.start("p1", "bob")).code == "TRIP_LEASE_UNSUPPORTED"
    assert ports.lease.puts == [] and runner.running() is None


# ---- open, renew, release -----------------------------------------------------------------

def test_open_renew_release():
    runner, store, ports = _setup()
    view = _start(runner, store, ports)
    lease_id = view["lease"]["lease_id"]
    assert view["lease"]["state"] == "held"
    assert ports.lease.puts == [{"lease_id": lease_id, "trip_id": "p1", "holder": "site-a",
                                 "operator_name": "bob", "ttl_s": 5.0}]
    _ticks(runner, ports, 4)
    assert len(ports.lease.puts) == 5 and {body["lease_id"] for body in ports.lease.puts} == {lease_id}
    _do(runner, runner.cancel("p1", "bob"))
    assert ports.lease.deletes == [(lease_id, 1)]  # after the halt went out
    assert runner.view("p1")["lease"]["state"] == "released"
    _ticks(runner, ports, 2)
    assert len(ports.lease.puts) == 5  # nothing renews a closed trip


def test_an_arrived_trip_releases_its_lease():
    runner, store, ports = _setup(_free_map(), caps=LEASED_BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    lease_id = _do(runner, runner.start("p1", "bob"))["lease"]["lease_id"]
    ports.at(_arc(store, "bc:fwd"), 0.97)
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "arrived" and [d[0] for d in ports.lease.deletes] == [lease_id]


def test_each_trip_gets_a_new_lease_id():
    runner, store, ports = _setup()
    first = _start(runner, store, ports)["lease"]["lease_id"]
    _do(runner, runner.cancel("p1", "bob"))
    ports.core.mode = "CAMERA_LINE"  # the cancel turned line following off
    second = _start(runner, store, ports, plan_id="p2")["lease"]["lease_id"]
    assert first != second and ports.lease.lease["lease_id"] == second


@pytest.mark.parametrize("core_code, trip_code", [("TRIP_LEASED", "TRIP_ROBOT_LEASED"),
                                                  ("MANUAL_MODE", "TRIP_ROBOT_MANUAL"),
                                                  ("CALIBRATION_ACTIVE", "CALIBRATION_ACTIVE"),
                                                  ("EMERGENCY_ACTIVE", "TRIP_LEASE_REFUSED")])
def test_core_open_refusals_refuse_the_start(core_code, trip_code):
    runner, store, ports = _setup()
    ports.lease.refuse = core_code
    _plan(store, ports, "east:fwd", 0.5, "SE")
    err = _refused(runner, runner.start("p1", "bob"))
    assert (err.code, err.detail.get("code")) == (trip_code, core_code)
    assert runner.running() is None and ports.sent == [] and ports.goals == []


def test_a_start_refused_after_the_lease_opened_releases_it():
    runner, store, ports = _setup()
    runner.traffic.signal_refusal = lambda *_args: ("TRIP_SIGNAL_START_IN_ZONE", {})
    _plan(store, ports, "east:fwd", 0.5, "SE")
    assert _refused(runner, runner.start("p1", "bob")).code == "TRIP_SIGNAL_START_IN_ZONE"
    assert ports.lease.lease is None and len(ports.lease.deletes) == 1


# ---- a lost lease ends the trip and is never opened again ---------------------------------

def _lost(runner, ports):
    view = runner.view("p1")
    assert (view["state"], view["reason"]) == ("stopped", "lease_lost")
    puts = len(ports.lease.puts)
    _ticks(runner, ports, 3)
    assert len(ports.lease.puts) == puts and runner.running() is None  # never reopened
    return view


def test_renewed_false_is_a_lost_lease_core_restarted():
    runner, store, ports = _setup()
    _start(runner, store, ports)
    _ticks(runner, ports)
    ports.lease.restart()  # CORE restarted: memory only, so the renew opens a fresh lease
    _ticks(runner, ports)
    view = _lost(runner, ports)
    assert view["detail"]["lease_reason"] == "core_restarted" and view["lease"]["state"] == "lost"
    assert ports.lease.lease is None  # the lease that renew opened by accident is released


@pytest.mark.parametrize("reason", ["taken_over", "expired", "mode_left", "estop"])
def test_an_ended_lease_ends_the_trip_with_cores_reason(reason):
    runner, store, ports = _setup()
    _start(runner, store, ports)
    _ticks(runner, ports)
    ports.lease.end(reason, by="kim-tablet")
    sent = len(ports.sent)
    _ticks(runner, ports)
    view = _lost(runner, ports)
    assert (view["detail"]["lease_reason"], view["detail"]["lease_by"]) == (reason, "kim-tablet")
    assert len(ports.sent) == sent and ports.goals == []  # no instruction after the loss


def test_a_step_in_flight_when_the_lease_is_lost_sends_nothing_more():
    runner, store, ports = _setup(_free_map(), caps=LEASED_BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    _do(runner, runner.start("p1", "bob"))
    _ticks(runner, ports)
    goals = len(ports.goals)

    async def go():
        gate = asyncio.Event()

        async def slow(robot_id):
            await gate.wait()
            return ports.pose
        ports.arbitrated_pose = slow
        ports.now += 0.5
        await runner.tick()  # this step waits on its pose, holding the robot lock
        ports.lease.end("taken_over", by="kim-tablet")
        ports.now += 0.5
        await runner.tick()  # the renew finds the loss while that step is in flight
        for _ in range(5):
            await asyncio.sleep(0)
        ports.at(_arc(store, "ab:fwd"), 0.5)  # far enough that the step would send a new goal
        gate.set()
        await asyncio.gather(*runner._inflight.values(), *runner.lease._inflight.values())
    asyncio.run(go())
    view = runner.view("p1")
    assert (view["state"], view["reason"], view["detail"]["lease_reason"]) == ("stopped", "lease_lost", "taken_over")
    assert len(ports.goals) == goals and ports.canceled == ["rosy_60"]


def test_another_lease_on_the_robot_ends_the_trip():
    runner, store, ports = _setup()
    _start(runner, store, ports)
    ports.lease.lease = {"lease_id": "someone-else"}
    _ticks(runner, ports)
    assert _lost(runner, ports)["detail"]["lease_reason"] == "leased"


def test_no_confirmed_renew_for_the_ttl_ends_the_trip():
    runner, store, ports = _setup()
    _start(runner, store, ports)
    ports.lease.down = True
    _ticks(runner, ports, 9)  # 4.5 s: CORE still holds it
    assert runner.view("p1")["state"] in ("started", "running")
    _ticks(runner, ports)
    ports.lease.down = False
    assert _lost(runner, ports)["detail"]["lease_reason"] == "renew_timeout"


# ---- the trip's own holds, laps and replans keep the lease --------------------------------

def test_a_replan_hold_keeps_the_lease():
    runner, store, ports = _setup()
    ring_s = _arc(store, "ring_s:fwd")
    _plan(store, ports, "ring_s:fwd", 0.1, "NW")
    lease_id = _do(runner, runner.start("p1", "bob"))["lease"]["lease_id"]
    ports.blocked = frozenset({"ring_e"})
    _ticks(runner, ports)
    assert runner.running()["hold"]["reason"] == "replan" and ports.sent[0][0] == "stop"  # Fleet's stop is no end
    ports.at(ring_s, ring_s.length_m - 0.05)
    _ticks(runner, ports, 2)
    _do(runner, runner.confirm_replan("p1", "bob"))
    _ticks(runner, ports)
    assert runner.running()["lease"]["state"] == "held" and ports.lease.deletes == []
    assert {body["lease_id"] for body in ports.lease.puts} == {lease_id}


class LeaseFleet(Fleet):
    def __init__(self, ids):
        super().__init__(ids)
        self.lease = {robot_id: LeaseCore() for robot_id in ids}

    def caps_for(self, robot_id):
        return LEASED

    async def trip_lease(self, robot_id, body):
        return self.lease[robot_id].put(body)

    async def trip_lease_release(self, robot_id, lease_id):
        return self.lease[robot_id].delete(lease_id)


def test_the_next_lap_keeps_the_lease():
    fleet = LeaseFleet(("a",))
    store = SiteMapStore(None, clock=lambda: fleet.now)
    from test_routing import demo_site
    store.import_if_empty(demo_site(), source="test")
    runner = TripRunner(store=store, routing_config=store.routing_config, caps=fleet.caps_for, poses=fleet,
                        junction=fleet, goal=fleet.goal, cancel_goal=fleet.cancel_goal,
                        blocked=lambda: fleet.blocked, clock=lambda: fleet.now, lease={"required": True})
    lease_id = _lap_trip(runner, store, fleet, "a", "east:fwd", _s_of(store, "east:fwd", START_N))["lease"]["lease_id"]
    _to_tail(runner, store, fleet, "a")

    async def go():
        fleet.advance(0.5)
        await runner.tick()
        await _settle(runner)
    asyncio.run(go())
    view = runner.view("a")
    assert view["lap"] == 2 and view["state"] == "running" and view["lease"]["state"] == "held"
    assert {body["lease_id"] for body in fleet.lease["a"].puts} == {lease_id} and fleet.lease["a"].deletes == []
