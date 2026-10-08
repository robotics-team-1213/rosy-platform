"""D-517 M1a: one trip per robot, repeat laps, the Fleet block table (computed, shown, never sent)."""

from __future__ import annotations

import asyncio
import time

import pytest

from fleet.localization.map_pose import MapPose
from fleet.routing.execute import ends_at_place, plan_body
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.server.lane_traffic import TrafficService
from fleet.server.site_map_store import SiteMapStore
from fleet.server.trip_ports import TripConfig
from fleet.server.trip_runner import TripError, TripRunner
from test_routing import demo_site
from test_trip_runner import LANE, Ports, _activate_again, run


class Fleet:
    """Several ``test_trip_runner.Ports`` (one fake CORE each) behind the runner's ports."""

    def __init__(self, ids):
        self.p = {robot_id: Ports() for robot_id in ids}
        self.blocked: frozenset = frozenset()
        self.now = 1000.0

    def advance(self, dt):
        self.now += dt
        for ports in self.p.values():
            ports.now = self.now

    def caps_for(self, robot_id):
        return LANE

    async def arbitrated_pose(self, robot_id):
        return await self.p[robot_id].arbitrated_pose(robot_id)

    async def refresh(self, robot_id, force_rest=False):
        pass

    async def junction_state(self, robot_id):
        return await self.p[robot_id].junction_state(robot_id)

    async def hold(self, robot_id):
        return await self.p[robot_id].hold(robot_id)

    async def line_follow_mode(self, robot_id):
        return await self.p[robot_id].line_follow_mode(robot_id)

    async def send_junction(self, robot_id, *args, **kwargs):
        return await self.p[robot_id].send_junction(robot_id, *args, **kwargs)

    async def goal(self, robot_id, *args):
        return await self.p[robot_id].goal(robot_id, *args)

    async def cancel_goal(self, robot_id):
        return await self.p[robot_id].cancel_goal(robot_id)

    def at(self, robot_id, arc, s, anchor_age_s=0.1):
        x, y, yaw = arc.point_at(s)
        self.p[robot_id].pose = MapPose(x, y, yaw, "LOCALIZED", "sighting", 0.0, 0.1, anchor_age_s)


def _setup(ids=("a", "b"), **config):
    fleet = Fleet(ids)
    store = SiteMapStore(None, clock=lambda: fleet.now)
    store.import_if_empty(demo_site(), source="test")
    runner = TripRunner(store=store, routing_config=store.routing_config, caps=fleet.caps_for, poses=fleet,
                        junction=fleet, goal=fleet.goal, cancel_goal=fleet.cancel_goal,
                        blocked=lambda: fleet.blocked, clock=lambda: fleet.now, config=TripConfig(**config))
    return runner, store, fleet


def _trip(runner, store, fleet, robot_id, arc_id, s, to="start_n", via=("start_s",), repeat=True, plan_id=None):
    graph = store.active()[2]
    arc = graph.arcs[arc_id]
    fleet.at(robot_id, arc, s)
    plan = plan_trip(graph, PlanRequest(store.active()[0], arc.point_at(s), to, via=tuple(via)), store.routing_config)
    plan_id = plan_id or robot_id
    store.record_plan(plan_id=plan_id, robot_id=robot_id, principal_id="bob", map_version=plan.map_version,
                      request={"to": to, "via": list(via), "repeat": repeat}, result={"plan": plan_body(plan)})
    return run(runner.start(plan_id, "bob"))


def _ticks(runner, fleet, n=1, dt=0.5):
    for _ in range(n):
        fleet.advance(dt)
        run(runner.tick())


def _arc(store, arc_id):
    return store.active()[2].arcs[arc_id]


def _s_of(store, arc_id, xy):
    return _arc(store, arc_id).project(*xy)[1]


START_N = (0.83, -0.50)
START_S = (-1.30, 0.53)


def test_each_robot_runs_its_own_trip_and_busy_means_that_robot():
    runner, store, fleet = _setup()
    _trip(runner, store, fleet, "a", "east:fwd", _s_of(store, "east:fwd", START_N))
    _trip(runner, store, fleet, "b", "west:fwd", _s_of(store, "west:fwd", START_S), to="start_s", via=("start_n",))
    assert {v["robot_id"] for v in runner.open_trips()} == {"a", "b"} and runner.running() is not None
    with pytest.raises(TripError) as err:
        _trip(runner, store, fleet, "a", "east:fwd", _s_of(store, "east:fwd", START_N), plan_id="a2")
    assert (err.value.code, err.value.detail) == ("TRIP_BUSY", {"trip_id": "a"})
    _ticks(runner, fleet)
    assert runner.view("a")["state"] == runner.view("b")["state"] == "running"
    view = runner.traffic.view()
    assert view["map_version"] == store.active()[0] and [r["robot_id"] for r in view["robots"]] == ["a", "b"]
    assert view["loop_capacity"] == [{"edges": ["east", "ring_n", "ring_s", "west"], "capacity": 3,
                                      "robots": ["a", "b"]}]
    assert 0.6 < view["block_length_m"]["east"] < 0.7 and view["wait_cycle"] is None
    assert {u["state"] for u in view["units"]} <= {"FREE", "GRANTED", "OCCUPIED", "UNKNOWN"}
    assert any(u["state"] == "OCCUPIED" and u["holders"] == ["a"] for u in view["units"])
    run(runner.cancel("a", "bob"))  # an operator stop ends that robot's trip only
    assert runner.view("a")["state"] == "canceled" and runner.view("b")["state"] == "running"


def test_a_slow_robot_never_holds_another_back():
    runner, store, fleet = _setup(period_s=0.05)
    _trip(runner, store, fleet, "a", "east:fwd", _s_of(store, "east:fwd", START_N))
    _trip(runner, store, fleet, "b", "west:fwd", _s_of(store, "west:fwd", START_S), to="start_s", via=("start_n",))
    calls = []

    async def stuck(robot_id):
        calls.append(robot_id)
        await asyncio.sleep(5)

    fleet.p["a"].arbitrated_pose = stuck

    async def two_periods():
        started = time.monotonic()
        await runner.tick()
        await runner.tick()  # a is still in its first step: not started again
        return time.monotonic() - started

    assert run(two_periods()) < 1.0
    assert calls == ["a"] and runner.view("b")["state"] == "running" and runner.view("a")["state"] == "started"


def _tail(live):
    return max(i for i in range(len(live.segments)) if live.place(i))


def _to_tail(runner, store, fleet, robot_id, before=0.3, anchor_age_s=0.1):
    live = runner._live[robot_id]
    tail = _tail(live)
    live.view["segment_index"] = tail
    arc = live.arc(tail)
    fleet.at(robot_id, arc, live.segments[tail]["s_to"] - before, anchor_age_s=anchor_age_s)
    return live, tail


def test_a_repeat_trip_plans_the_next_lap_before_its_last_place_and_drives_through():
    runner, store, fleet = _setup(ids=("a",))
    _trip(runner, store, fleet, "a", "east:fwd", _s_of(store, "east:fwd", START_N))
    live, tail = _to_tail(runner, store, fleet, "a")
    count = len(live.segments)
    _ticks(runner, fleet)
    view = runner.view("a")
    assert view["lap"] == 2 and view["hold"] is None and view["state"] == "running"
    assert len(view["plan"]["segments"]) == count + 4  # the lap end and the next lap's start are one segment
    assert fleet.p["a"].sent[-1][0] in ("straight", "left", "right")  # no stop at the lap end


def test_a_new_lap_drives_its_bends_again():
    """D-507 addendum: a bend done on the last lap is the same place id on the next one."""
    runner, store, fleet = _setup(ids=("a",))
    _trip(runner, store, fleet, "a", "east:fwd", _s_of(store, "east:fwd", START_N))
    live, _ = _to_tail(runner, store, fleet, "a")
    live.bends_done.add("B_SW")
    _ticks(runner, fleet)
    assert runner.view("a")["lap"] == 2 and live.bends_done == set()


def test_a_lap_whose_start_check_fails_holds_at_its_last_place():
    runner, store, fleet = _setup(ids=("a",))
    _trip(runner, store, fleet, "a", "east:fwd", _s_of(store, "east:fwd", START_N))
    _to_tail(runner, store, fleet, "a", anchor_age_s=2.5)
    _ticks(runner, fleet)
    hold = runner.view("a")["hold"]
    assert (hold["reason"], hold["code"], hold["plan"]) == ("lap", "TRIP_POSE_UNTRUSTED", None)
    assert fleet.p["a"].sent[-1][0] == "stop" and runner.view("a")["lap"] == 1
    with pytest.raises(TripError) as err:
        run(runner.confirm_replan("a", "bob"))
    assert err.value.code == "TRIP_REPLAN_FAILED"


def test_a_lap_on_another_route_holds_until_the_operator_confirms_it():
    runner, store, fleet = _setup(ids=("a",))
    _trip(runner, store, fleet, "a", "ring_s:fwd", 0.05)  # lap 1 starts on the ring, lap 2 at start_n
    _to_tail(runner, store, fleet, "a")
    _ticks(runner, fleet)
    hold = runner.view("a")["hold"]
    assert hold["reason"] == "lap" and hold["plan"] is not None and fleet.p["a"].sent[-1][0] == "stop"
    live = runner._live["a"]  # review LOW 9: the held plan's places match its own segments
    assert len(hold["plan"]["places"]) == sum(1 for seg in hold["plan"]["segments"] if ends_at_place(live.graph, seg))
    assert runner._live["a"].at is not None
    view = run(runner.confirm_replan("a", "bob"))
    assert view["hold"] is None and view["lap"] == 2 and view["segment_index"] == 0
    assert runner._live["a"].at is None  # review LOW 7: no old-plan position in the table's new route


def test_the_loop_capacity_refuses_one_more_repeat_trip():
    runner, store, fleet = _setup(ids=("a", "b", "c", "d"))
    for robot_id, s in (("a", 0.2), ("b", 1.4), ("c", 2.6)):
        _trip(runner, store, fleet, robot_id, "east:fwd", s)
    with pytest.raises(TripError) as err:
        _trip(runner, store, fleet, "d", "west:fwd", _s_of(store, "west:fwd", START_S), to="start_s",
              via=("start_n",))
    assert (err.value.code, err.value.detail) == ("TRIP_LOOP_FULL", {"robots": 4, "capacity": 3,
                                                                       "held_per_robot": 3})
    run(runner.cancel("c", "bob"))
    _trip(runner, store, fleet, "d", "west:fwd", _s_of(store, "west:fwd", START_S), to="start_s",
          via=("start_n",), plan_id="d2")


def test_waiting_behind_a_robot_is_not_a_stall():
    runner, store, fleet = _setup()
    middle = _arc(store, "east:fwd").length_m / 2  # a block boundary: east is cut into 6 (test_blocks)
    _trip(runner, store, fleet, "a", "east:fwd", middle + 0.15)
    _trip(runner, store, fleet, "b", "east:fwd", middle - 0.05)  # its stop gap reaches into a's block
    _ticks(runner, fleet)
    assert runner._live["b"].traffic["waiting_for"] == ["a"]
    assert next(r for r in runner.traffic.view()["robots"] if r["robot_id"] == "b")["waiting_for"] == ["a"]
    _ticks(runner, fleet, n=42)  # 21 s with nobody moving
    assert runner.view("a")["reason"] == "stall" and runner.view("b")["state"] == "running"


def test_no_junction_instruction_into_a_refused_block():
    runner, store, fleet = _setup()
    _trip(runner, store, fleet, "a", "ring_n:fwd", 0.15)
    east = _arc(store, "east:fwd")
    _trip(runner, store, fleet, "b", "east:fwd", east.length_m - 0.75)
    _ticks(runner, fleet)  # b is not armed yet; the table already asks past the place for it
    assert runner._live["b"].traffic["refused_at_m"] is not None
    fleet.at("b", east, east.length_m - 0.3)
    _ticks(runner, fleet)
    assert fleet.p["b"].sent == []  # CORE waits at the junction
    run(runner.cancel("a", "bob"))
    _ticks(runner, fleet, n=2)  # review HIGH 2 (D-517 6): a ended its trip but still stands in the ring
    assert fleet.p["b"].sent == [] and runner.traffic.pinned() == ["a"]
    fleet.p["a"].pose = MapPose(5.0, 5.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, 0.1)  # seen off the lanes
    _ticks(runner, fleet, n=2)
    assert runner.traffic.pinned() == []
    assert len(fleet.p["b"].sent) == 1 and fleet.p["b"].sent[0][0] in ("straight", "left", "right")


def test_traffic_api_is_read_only_and_repeat_needs_a_place_cycle(tmp_path):
    from test_trip_runner import OPERATOR, VIEWER, _app

    client, *_rest = _app(tmp_path, Ports())
    body = client.get("/api/fleet/traffic", headers=VIEWER).json()
    assert set(body) == {"map_version", "block_length_m", "units", "robots", "loop_capacity", "wait_cycle",
                         "unplaced"}
    assert client.get("/api/fleet/traffic").status_code in (401, 403)
    trips = client.get("/api/fleet/trips", headers=VIEWER).json()
    assert trips["open"] == [] and trips["running"] is None
    for request in ({"to": "NW", "repeat": True}, {"to": {"x": 0.0, "y": 0.0}, "via": ["NE"], "repeat": True}):
        assert client.post("/api/fleet/robots/rosy_60/trip", json=request, headers=OPERATOR).status_code == 422


def test_traffic_service_without_an_active_map_is_empty():
    class NoMap:
        def active(self):
            return None

    service = TrafficService(NoMap())
    service.step([])
    assert service.view()["units"] == [] and service.loop_full(("e:fwd",), []) is None


def test_estop_ends_every_open_trip():
    from fakes import FakeRobot
    from fleet.server.console import FleetConsole
    from fleet.server.trip_guard import install_trip_guard
    from fleet.swarm.robots import RobotEndpoint

    runner, store, fleet = _setup()
    _trip(runner, store, fleet, "a", "east:fwd", _s_of(store, "east:fwd", START_N))
    _trip(runner, store, fleet, "b", "west:fwd", _s_of(store, "west:fwd", START_S), to="start_s", via=("start_n",))
    robots = [FakeRobot("a"), FakeRobot("b")]
    console = FleetConsole([RobotEndpoint(r.robot_id, "http://x", "t") for r in robots], robots)
    seen = []
    estop = console.estop_all

    async def recorded_estop(*args, **kwargs):
        seen.append(runner.open_trips())  # review MED 6: every trip is closed before the E-stop goes out
        return await estop(*args, **kwargs)

    console.estop_all = recorded_estop
    install_trip_guard(console, runner)
    halts = []

    async def slow_hold(robot_id):
        halts.append(robot_id)
        await asyncio.sleep(0.3)
        return {"mode": "OFF"}

    fleet.hold = slow_hold
    started = time.monotonic()
    run(console.estop_all())
    assert time.monotonic() - started < 0.55  # both robots halted at once, not one after the other
    assert seen == [[]] and runner.open_trips() == [] and sorted(halts) == ["a", "b"]
    assert runner.view("a")["reason"] == runner.view("b")["reason"] == "operator_estop"
    assert store.trip("a")["state"] == "canceled"


def test_a_robot_never_localized_holds_every_junction_instruction():
    runner, store, fleet = _setup(ids=("a", "b", "c"))
    _trip(runner, store, fleet, "a", "east:fwd", 0.2)
    _trip(runner, store, fleet, "b", "west:fwd", 0.2, to="start_s", via=("start_n",))
    _ticks(runner, fleet)
    assert runner._live["a"].traffic["refused_at_m"] is None
    _trip(runner, store, fleet, "c", "east:fwd", 2.6)  # opened, not yet located by a step
    runner.traffic.step(runner._live.values())
    assert runner.traffic.view()["unplaced"] == ["c"]
    for robot_id in ("a", "b"):
        live = runner._live[robot_id]
        assert live.traffic == {"waiting_for": ["c"], "authority_end_m": live.traffic["authority_end_m"],
                                "refused_at_m": 0.0}
        assert runner.traffic.holds(live, live.view["segment_index"])


def test_a_loop_is_its_lap_cycle_not_the_approach_to_it():
    """Review HIGH 1: a trip that joins the loop from ring_w shares the loop of the trips on east."""
    runner, store, fleet = _setup(ids=("a", "d"))
    _trip(runner, store, fleet, "a", "east:fwd", _s_of(store, "east:fwd", START_N))
    _trip(runner, store, fleet, "d", "ring_w:fwd", 0.05, to="start_s", via=("start_n",))
    assert "ring_w" in {seg["edge_id"] for seg in runner._live["d"].segments}
    _ticks(runner, fleet)
    assert runner.traffic.view()["loop_capacity"] == [{"edges": ["east", "ring_n", "ring_s", "west"],
                                                       "capacity": 3, "robots": ["a", "d"]}]
    runner, store, fleet = _setup(ids=("a", "b", "c", "d"))
    for robot_id, s in (("a", 0.2), ("b", 1.4), ("c", 2.6)):
        _trip(runner, store, fleet, robot_id, "east:fwd", s)
    with pytest.raises(TripError) as err:
        _trip(runner, store, fleet, "d", "ring_w:fwd", 0.05, to="start_s", via=("start_n",))
    assert (err.value.code, err.value.detail["robots"]) == ("TRIP_LOOP_FULL", 4)


def test_a_map_activation_keeps_every_robots_occupancy():
    """Review HIGH 2: a new map version re-pins each robot from its last LOCALIZED pose."""
    runner, store, fleet = _setup(ids=("a",))
    _trip(runner, store, fleet, "a", "ring_n:fwd", 0.15)
    _ticks(runner, fleet)
    run(runner.cancel("a", "bob"))
    fleet.p["a"].pose = None  # no pose any more: only the last one can place it
    _activate_again(store)
    _ticks(runner, fleet)
    view = runner.traffic.view()
    assert view["map_version"] == store.active()[0] and runner.traffic.pinned() == ["a"]
    assert [u["id"] for u in view["units"] if u["state"] == "UNKNOWN" and u["holders"] == ["a"]]
    _ticks(runner, fleet, n=3)
    assert runner.traffic.pinned() == ["a"]  # still nothing shows it left


def test_a_failing_block_table_drops_every_stale_answer(caplog):
    """Review MED 3: refusals of the last good period do not hold forever; logged once."""
    runner, store, fleet = _setup()
    middle = _arc(store, "east:fwd").length_m / 2
    _trip(runner, store, fleet, "a", "east:fwd", middle + 0.15)
    _trip(runner, store, fleet, "b", "east:fwd", middle - 0.05)
    _ticks(runner, fleet)
    assert runner._live["b"].traffic["waiting_for"] == ["a"]

    def broken(*_args, **_kwargs):
        raise RuntimeError("table")

    runner.traffic.step = broken
    _ticks(runner, fleet, n=2)
    assert runner._live["a"].traffic is None and runner._live["b"].traffic is None
    assert sum("traffic table step failed" in r.getMessage() for r in caplog.records) == 1


def test_the_hold_back_covers_the_entry_past_the_place():
    """Review MED 4: a block refused just past the place (within PAST_PLACE_M) holds the instruction."""
    from fleet.server.lane_traffic import PAST_PLACE_M

    runner, store, fleet = _setup(ids=("a",))
    _trip(runner, store, fleet, "a", "east:fwd", 0.2)
    live = runner._live["a"]
    index = next(i for i in range(len(live.segments)) if live.place(i))
    place_m = live.progress(index, live.segments[index]["s_to"])
    for refused, holds in ((place_m + 0.02, True), (place_m + PAST_PLACE_M - 1e-3, True),
                           (place_m + PAST_PLACE_M + 0.01, False), (None, False)):
        live.traffic = {"waiting_for": [], "authority_end_m": None, "refused_at_m": refused}
        assert runner.traffic.holds(live, index) is holds, refused


def test_a_failed_lap_check_is_tried_again_then_left_to_the_operator():
    """Review MED 5: every LAP_RETRY_S up to LAP_RETRIES times, and on the operator's confirm."""
    from fleet.server.trip_runner import LAP_RETRIES, LAP_RETRY_S

    runner, store, fleet = _setup(ids=("a",))
    _trip(runner, store, fleet, "a", "east:fwd", _s_of(store, "east:fwd", START_N))
    live, tail = _to_tail(runner, store, fleet, "a", anchor_age_s=2.5)
    _ticks(runner, fleet)
    assert runner.view("a")["hold"]["code"] == "TRIP_POSE_UNTRUSTED" and live.lap_tries == 1
    _ticks(runner, fleet, n=int(LAP_RETRY_S / 0.5) - 1)
    assert live.lap_tries == 1  # not yet
    _ticks(runner, fleet, n=1 + int(LAP_RETRY_S / 0.5) * LAP_RETRIES)
    assert live.lap_tries == 1 + LAP_RETRIES and runner.view("a")["hold"]["reason"] == "lap"
    _ticks(runner, fleet, n=int(LAP_RETRY_S / 0.5) * 2)
    assert live.lap_tries == 1 + LAP_RETRIES  # the budget is spent: the resolver or the operator
    fleet.at("a", live.arc(tail), live.segments[tail]["s_to"] - 0.3)  # a fresh sighting again
    view = run(runner.confirm_replan("a", "bob"))
    assert view["hold"] is None and view["lap"] == 2 and live.lap_tries == 0


def test_a_failed_lap_check_carries_on_once_a_retry_passes():
    runner, store, fleet = _setup(ids=("a",))
    _trip(runner, store, fleet, "a", "east:fwd", _s_of(store, "east:fwd", START_N))
    live, tail = _to_tail(runner, store, fleet, "a", anchor_age_s=2.5)
    _ticks(runner, fleet)
    assert runner.view("a")["hold"]["reason"] == "lap" and fleet.p["a"].sent[-1][0] == "stop"
    fleet.at("a", live.arc(tail), live.segments[tail]["s_to"] - 0.3)
    _ticks(runner, fleet, n=10)
    view = runner.view("a")
    assert view["hold"] is None and view["lap"] == 2 and view["state"] == "running"


def test_the_loop_period_includes_the_tick_and_finished_steps_are_dropped(monkeypatch):
    """Review LOW 11: sleep only the rest of period_s; no done future stays in _inflight."""
    import fleet.server.trip_runner as trip_runner

    runner, store, fleet = _setup(ids=("a",), period_s=0.2)
    _trip(runner, store, fleet, "a", "east:fwd", 0.2)
    _ticks(runner, fleet)
    assert runner._inflight == {}
    real_sleep, slept = asyncio.sleep, []

    async def slow_tick():
        await real_sleep(0.15)

    async def sleep(delay, *args):
        slept.append(delay)
        raise asyncio.CancelledError

    runner.tick = slow_tick
    monkeypatch.setattr(trip_runner.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        run(runner._loop())
    assert len(slept) == 1 and slept[0] < 0.1


def test_a_repeat_trip_drops_finished_laps_and_the_table_follows():
    """Review LOW 8: the plan keeps the current and the next lap; indices, places and grants stay consistent."""
    runner, store, fleet = _setup(ids=("a",))
    _trip(runner, store, fleet, "a", "east:fwd", _s_of(store, "east:fwd", START_N))
    live, _tail = _to_tail(runner, store, fleet, "a")
    _ticks(runner, fleet)
    two_laps = len(live.segments)
    for lap in (3, 4, 5):
        live, _tail = _to_tail(runner, store, fleet, "a")
        _ticks(runner, fleet)
        plan = runner.view("a")["plan"]
        assert runner.view("a")["lap"] == lap and runner.view("a")["hold"] is None
        assert len(live.segments) == two_laps and live.trim_m > 0
        assert plan["places"] == [action["place_id"] for action in plan["actions"][:-1]]
        assert len(plan["places"]) == sum(1 for i in range(len(live.segments)) if live.place(i))
        assert live.at[0] == live.view["segment_index"]
        assert live.sent is None or 0 <= live.sent["index"] <= live.view["segment_index"]
        spans = runner.traffic._seen["a"][2]
        held = runner.traffic._state.held["a"]
        assert held and all(spans[i].unit == unit for i, (unit, _forward) in held.items())
    assert fleet.p["a"].sent[-1][0] != "stop"


def test_a_shift_past_every_grant_drops_the_authority():
    """Review: two trims between table steps dropped all grants; authority must not outlive them."""
    from fleet.routing import blocks
    from fleet.server.lane_traffic import _shift
    spans = (blocks.Span("a", 0, 1), blocks.Span("b", 1, 2), blocks.Span("c", 2, 3))
    state = blocks.TableState(held={"r": {0: ("a", True), 1: ("b", True)}}, authority={"r": 1.9})
    _shift(state, "r", spans, 2.0)
    assert state.held["r"] == {} and "r" not in state.authority
    state = blocks.TableState(held={"r": {1: ("b", True), 2: ("c", True)}}, authority={"r": 2.9})
    _shift(state, "r", spans, 1.0)
    assert state.held["r"] == {0: ("b", True), 1: ("c", True)} and abs(state.authority["r"] - 1.9) < 1e-9
